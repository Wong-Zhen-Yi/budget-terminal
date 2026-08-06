from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

from ..dependencies import logger
from .client import InProcessDataServiceClient


class EmbeddedDataServiceRuntime:
    """Start and stop the private FastAPI server used by the desktop UI."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        preferred_port: int = 8765,
        transport: str | None = None,
    ) -> None:
        self.host = host
        self.preferred_port = int(preferred_port)
        self.port: int | None = None
        self.base_url: str | None = None
        self._server: Any = None
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._ready = threading.Event()
        requested_transport = transport or os.environ.get("BUDGET_TERMINAL_DATA_TRANSPORT", "inprocess")
        requested_transport = str(requested_transport or "inprocess").strip().lower()
        if requested_transport not in {"inprocess", "http"}:
            logger.warning("Unknown data transport %r; using inprocess.", requested_transport)
            requested_transport = "inprocess"
        self.transport = requested_transport

    @property
    def client(self) -> Any:
        return self._client if self._ready.is_set() else None

    def start(self, timeout_seconds: float = 8.0) -> bool:
        if self._ready.is_set():
            return True
        if self.transport == "inprocess":
            try:
                self._client = InProcessDataServiceClient()
                self._ready.set()
                logger.info("In-process data service ready.")
                return True
            except Exception as exc:
                logger.warning("In-process data service failed to start: %s", exc)
                self.stop()
                return False
        try:
            import uvicorn
            from .client import DataServiceClient
            from .server import create_app

            self._server_socket = self._reserve_available_socket()
            self.port = int(self._server_socket.getsockname()[1])
            self.base_url = f"http://{self.host}:{self.port}"
            app = create_app()
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                lifespan="on",
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [self._server_socket]},
                name="BudgetTerminalDataService",
                daemon=True,
            )
            self._thread.start()
            self._client = DataServiceClient(self.base_url)
            if self._wait_until_ready(timeout_seconds):
                self._ready.set()
                logger.info("Embedded data service ready at %s.", self.base_url)
                return True
        except Exception as exc:
            logger.warning("Embedded data service failed to start: %s", exc)
        self.stop()
        return False

    def stop(self) -> None:
        self._ready.clear()
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        server = self._server
        if server is not None:
            server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        server_socket = self._server_socket
        self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass
        self._server = None
        self._thread = None
        self.port = None
        self.base_url = None

    def _wait_until_ready(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            try:
                if self._client is not None and self._client.health():
                    return True
            except Exception:
                time.sleep(0.1)
        logger.warning("Embedded data service did not become ready within %.1f seconds.", timeout_seconds)
        return False

    def _reserve_available_socket(self) -> socket.socket:
        for port in range(self.preferred_port, self.preferred_port + 50):
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                server_socket.bind((self.host, int(port)))
                return server_socket
            except OSError:
                server_socket.close()
        raise RuntimeError("no available localhost port for embedded data service")
