from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .paths import user_data_dir


CommandHandler = Callable[[dict[str, Any]], dict[str, Any]]


def single_instance_server_name() -> str:
    """Return the per-user local server name for Budget Terminal."""
    root = str(user_data_dir().resolve()).casefold()
    digest = hashlib.sha1(root.encode("utf-8")).hexdigest()[:16]
    return f"budget-terminal-{digest}"


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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._command_handler = command_handler
        self._activate_callback = activate_callback
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_pending_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def start(self) -> bool:
        name = single_instance_server_name()
        if self._server.listen(name):
            return True
        QLocalServer.removeServer(name)
        return self._server.listen(name)

    def close(self) -> None:
        self._server.close()
        QLocalServer.removeServer(single_instance_server_name())

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
    mcp_handler: Callable[[dict[str, Any]], dict[str, Any] | None],
    activate_callback: Callable[[], bool],
) -> CommandHandler:
    def handle(request: dict[str, Any]) -> dict[str, Any]:
        command = str(request.get("command") or "")
        if command == "activate":
            return {"ok": True, "activated": bool(activate_callback())}
        if command == "mcp_request":
            message = request.get("message")
            if not isinstance(message, dict):
                return {"ok": False, "error": "mcp_request requires a message object."}
            return {"ok": True, "response": mcp_handler(message)}
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


def activate_existing_instance(*, timeout_ms: int = 1500) -> bool:
    response = send_single_instance_command({"command": "activate"}, timeout_ms=timeout_ms)
    return bool(response and response.get("ok") and response.get("activated"))
