from __future__ import annotations

import socket
import threading
import time
from typing import Any

from ..dependencies import logger


class EmbeddedDataServiceRuntime:
    """Start and stop the private FastAPI server used by the desktop UI."""

    def __init__(self, host: str = "127.0.0.1", preferred_port: int = 8765) -> None:
        self.host = host
        self.preferred_port = int(preferred_port)
        self.port: int | None = None
        self.base_url: str | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._ready = threading.Event()

    @property
    def client(self) -> Any:
        return self._client if self._ready.is_set() else None

    def start(self, timeout_seconds: float = 8.0) -> bool:
        if self._ready.is_set():
            return True
        try:
            import uvicorn
            from .client import DataServiceClient
            from .server import create_app

            self.port = self._find_available_port()
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
            self._thread = threading.Thread(target=self._server.run, name="BudgetTerminalDataService", daemon=True)
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
        self._server = None
        self._thread = None

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

    def _find_available_port(self) -> int:
        for port in range(self.preferred_port, self.preferred_port + 50):
            if self._port_available(port):
                return port
        raise RuntimeError("no available localhost port for embedded data service")

    def _port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, int(port)))
                return True
            except OSError:
                return False
