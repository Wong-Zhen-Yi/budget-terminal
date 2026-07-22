from __future__ import annotations

import atexit
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QLockFile, QObject, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .paths import user_data_dir


CommandHandler = Callable[[dict[str, Any]], dict[str, Any]]
INSTANCE_LOCK_FILE_NAME = 'BudgetTerminal.instance.lock'


def single_instance_server_name() -> str:
    """Return the per-user local server name for Budget Terminal."""
    root = str(user_data_dir().resolve()).casefold()
    digest = hashlib.sha1(root.encode("utf-8")).hexdigest()[:16]
    return f"budget-terminal-{digest}"


def single_instance_lock_path() -> Path:
    """Return the per-user lock file used to choose the primary process."""
    return user_data_dir() / INSTANCE_LOCK_FILE_NAME


class BudgetTerminalInstanceOwnership:
    """Own the exclusive right to construct the desktop application."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else single_instance_lock_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(self.path))
        # A live desktop process can legitimately hold this lock for days. Disable
        # age-only expiry; QLockFile can still recover a lock whose process died.
        self._lock.setStaleLockTime(0)
        self._owns_lock = False
        self._process_exit_release_registered = False

    @property
    def owns_lock(self) -> bool:
        return self._owns_lock

    def try_acquire(self, *, timeout_ms: int = 0) -> bool:
        """Atomically acquire primary-process ownership."""
        if self._owns_lock:
            return True
        self._owns_lock = bool(self._lock.tryLock(max(0, int(timeout_ms))))
        return self._owns_lock

    def hold_until_process_exit(self) -> None:
        """Keep acquired ownership until Python has finished joining worker threads.

        ``ThreadPoolExecutor`` workers can keep the process alive after the Qt
        event loop and ``main()`` return. A normal ``atexit`` callback runs after
        Python's thread shutdown phase, so retaining this bound callback prevents
        a relaunch from acquiring the lock during that shutdown tail.
        """
        if not self._owns_lock or self._process_exit_release_registered:
            return
        atexit.register(self._release_at_process_exit)
        self._process_exit_release_registered = True

    def _release_at_process_exit(self) -> None:
        self._process_exit_release_registered = False
        self.release()

    def release(self) -> None:
        """Release primary ownership only when this object acquired it."""
        if not self._owns_lock:
            return
        self._lock.unlock()
        self._owns_lock = False


class QueuedActivation:
    """Queue one activation request until a splash or main window is available."""

    def __init__(self) -> None:
        self._callback: Callable[[], bool] | None = None
        self._pending = False

    @property
    def pending(self) -> bool:
        return self._pending

    def request(self) -> bool:
        """Activate now or remember the request for the first available surface."""
        callback = self._callback
        if callback is None:
            self._pending = True
            return True
        return bool(callback())

    def set_callback(self, callback: Callable[[], bool]) -> bool:
        """Install the current activation target and flush one queued request."""
        self._callback = callback
        if not self._pending:
            return False
        self._pending = False
        return bool(callback())

    def clear_callback(self) -> None:
        self._callback = None


def activate_qt_window(window: Any, *, repeat_ms: int | None = None) -> bool:
    """Show and request foreground focus for a Qt window-like object."""
    if window is None:
        return False
    try:
        if callable(getattr(window, "isMinimized", None)) and window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
    except RuntimeError:
        return False
    if repeat_ms is not None and repeat_ms >= 0:
        QTimer.singleShot(int(repeat_ms), lambda: activate_qt_window(window))
    return True


class BudgetTerminalSingleInstanceServer(QObject):
    """Small local IPC server used to reuse an existing Budget Terminal app."""

    def __init__(
        self,
        *,
        command_handler: CommandHandler,
        activate_callback: Callable[[], bool] | None = None,
        ownership: BudgetTerminalInstanceOwnership | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._command_handler = command_handler
        self._activate_callback = activate_callback
        self._ownership = ownership
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_pending_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._server_name = single_instance_server_name()
        self._owns_endpoint = False
        self._live_endpoint_detected = False

    @property
    def owns_endpoint(self) -> bool:
        return self._owns_endpoint

    @property
    def live_endpoint_detected(self) -> bool:
        return self._live_endpoint_detected

    @staticmethod
    def _endpoint_reachable(name: str, *, timeout_ms: int = 250) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(name)
        connected = socket.waitForConnected(max(1, int(timeout_ms)))
        if connected:
            socket.disconnectFromServer()
        else:
            socket.abort()
        return bool(connected)

    def start(self) -> bool:
        if self._owns_endpoint and self._server.isListening():
            return True
        self._live_endpoint_detected = False
        ownership = self._ownership
        if ownership is None or not ownership.owns_lock:
            return False
        # Windows named pipes can permit another listener with the same name, so
        # probe before listen rather than treating listen() success as proof that
        # no primary endpoint already exists.
        if self._endpoint_reachable(self._server_name):
            self._live_endpoint_detected = True
            return False
        if self._server.listen(self._server_name):
            self._owns_endpoint = True
            return True
        # A legacy process could have appeared between the probe and listen.
        if self._endpoint_reachable(self._server_name):
            self._live_endpoint_detected = True
            return False
        # Only the exclusive primary owner may remove an unreachable endpoint.
        # This recovers a stale Unix socket without letting a contender steal a
        # live Windows named pipe.
        if not QLocalServer.removeServer(self._server_name):
            return False
        if not self._server.listen(self._server_name):
            return False
        self._owns_endpoint = True
        return True

    def close(self) -> None:
        if not self._owns_endpoint:
            return
        self._server.close()
        self._owns_endpoint = False

    def _accept_pending_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda sock=socket: self._read_socket(sock))
            socket.disconnected.connect(lambda sock=socket: self._forget_socket(sock))

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.setdefault(socket, bytearray())
        buffer.extend(bytes(socket.readAll()))
        if b"\n" not in buffer:
            return
        line, _sep, _rest = bytes(buffer).partition(b"\n")
        self._buffers[socket] = bytearray()
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object.")
            response = self._command_handler(request)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        socket.write(payload)
        socket.flush()
        socket.disconnectFromServer()

    def _forget_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()


def make_window_command_handler(
    *,
    activate_callback: Callable[[], bool],
) -> CommandHandler:
    def handle(request: dict[str, Any]) -> dict[str, Any]:
        command = str(request.get("command") or "")
        if command == "activate":
            return {"ok": True, "activated": bool(activate_callback())}
        return {"ok": False, "error": f"Unknown single-instance command: {command}"}

    return handle


def send_single_instance_command(
    request: dict[str, Any],
    *,
    timeout_ms: int = 3000,
) -> dict[str, Any] | None:
    """Send one blocking JSON command to an existing Budget Terminal instance."""
    socket = QLocalSocket()
    socket.connectToServer(single_instance_server_name())
    if not socket.waitForConnected(max(1, int(timeout_ms))):
        return None
    payload = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    socket.write(payload)
    if not socket.waitForBytesWritten(max(1, int(timeout_ms))):
        socket.abort()
        return None
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
    buffer = bytearray()
    while time.monotonic() < deadline:
        wait_ms = max(1, min(250, int((deadline - time.monotonic()) * 1000)))
        if socket.waitForReadyRead(wait_ms):
            buffer.extend(bytes(socket.readAll()))
            if b"\n" in buffer:
                line, _sep, _rest = bytes(buffer).partition(b"\n")
                try:
                    value = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return value if isinstance(value, dict) else None
    socket.abort()
    return None


def activate_existing_instance(
    *,
    timeout_ms: int = 3000,
    retry_interval_ms: int = 50,
) -> bool:
    """Ask the primary process to activate, retrying while it starts its IPC server."""
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        response = send_single_instance_command(
            {"command": "activate"},
            timeout_ms=min(500, remaining_ms),
        )
        if response and response.get("ok") and response.get("activated"):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(max(1, int(retry_interval_ms)) / 1000.0, remaining))
    return False
