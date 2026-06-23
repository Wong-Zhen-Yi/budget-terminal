from __future__ import annotations

import json
import sys
import threading
from typing import Any, BinaryIO, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .bridge import BudgetTerminalBridge
from .protocol import McpProtocol


def read_messages(stream: BinaryIO):
    """Read MCP JSON-lines messages, also accepting legacy Content-Length frames."""
    while True:
        line = stream.readline()
        if not line:
            return
        if not line.strip():
            continue
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
            while True:
                header = stream.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
            payload = stream.read(length)
        else:
            payload = line
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            yield value


class QtMcpDispatcher(QObject):
    request_received = pyqtSignal(object)
    input_closed = pyqtSignal()

    def __init__(self, protocol: McpProtocol, output: BinaryIO) -> None:
        super().__init__()
        self.protocol = protocol
        self.output = output
        self._write_lock = threading.Lock()
        self.request_received.connect(self._handle_request)

    def _handle_request(self, message: dict[str, Any]) -> None:
        response = self.protocol.handle(message)
        if response is None:
            return
        payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        with self._write_lock:
            self.output.write(payload)
            self.output.flush()


def run_server(
    window: Any,
    qt_app: Any,
    *,
    input_stream: Optional[BinaryIO] = None,
    output_stream: Optional[BinaryIO] = None,
) -> int:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    dispatcher = QtMcpDispatcher(McpProtocol(BudgetTerminalBridge(window)), output_stream)

    def shutdown() -> None:
        # Some pages own unparented QThreads. Let their current work finish before
        # Qt destroys the application; directly quitting the event loop can abort
        # on macOS while one of those threads still has live Qt objects.
        threads = []
        for value in vars(window).values():
            if isinstance(value, QThread) and value not in threads and value.isRunning():
                threads.append(value)
        for thread in threads:
            thread.requestInterruption()
            thread.quit()
        for thread in threads:
            if not thread.wait(30_000):
                thread.terminate()
                thread.wait(3_000)
        window.close()
        QTimer.singleShot(50, qt_app.quit)

    dispatcher.input_closed.connect(shutdown)

    def read_loop() -> None:
        try:
            for message in read_messages(input_stream):
                dispatcher.request_received.emit(message)
        finally:
            dispatcher.input_closed.emit()

    reader = threading.Thread(target=read_loop, name="BudgetTerminalMcpInput", daemon=True)
    reader.start()
    return int(qt_app.exec())
