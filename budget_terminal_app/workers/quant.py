from __future__ import annotations

import threading
from typing import Any

from ..dependencies import QObject, logger, pyqtSignal
from ..services.quant import QuantAnalyticsService, QuantScanPayload
from ..services.signal_scanner import ScanCancelled


class QuantScanWorker(QObject):
    """Run one universe-and-factor Quant scan outside the Qt UI thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        service: QuantAnalyticsService,
        *,
        force_universe_refresh: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.force_universe_refresh = bool(force_universe_refresh)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the running scan to stop at its next checkpoint.

        ``QThread.quit`` only unwinds the thread's event loop, which does nothing while ``run`` is
        still inside one long synchronous download. Without this flag, closing the window mid-scan
        blocks until the wait timeout expires.
        """

        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def fetch(self) -> QuantScanPayload:
        """Run the scan synchronously, for callers that already own a background thread."""

        return self.service.run_scan(
            force_universe_refresh=self.force_universe_refresh,
            progress=self.progress.emit,
            cancel=self._cancel_event.is_set,
        )

    def run(self) -> None:
        logger.info("Starting Quant scan")
        try:
            payload = self.fetch()
        except ScanCancelled:
            logger.info("Quant scan cancelled")
            self.cancelled.emit()
            return
        except Exception as exc:
            logger.exception("Quant scan failed")
            self.error.emit(str(exc))
            return
        logger.info(
            "Quant scan completed: %s ranked ticker(s), %s pair(s), %s error(s)",
            len(payload.rows),
            len(payload.pairs),
            len(payload.errors),
        )
        self.finished.emit(payload)


class QuantPairWorker(QObject):
    """Resolve one ad-hoc pair on demand, for the manual pair override."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, service: QuantAnalyticsService, left: str, right: str) -> None:
        super().__init__()
        self.service = service
        self.left = str(left or "").upper().strip()
        self.right = str(right or "").upper().strip()

    def fetch(self) -> dict[str, Any]:
        return self.service.analyze_pair(self.left, self.right)

    def run(self) -> None:
        try:
            payload = self.fetch()
        except Exception as exc:
            logger.warning("Quant pair analysis failed for %s/%s: %s", self.left, self.right, exc)
            self.error.emit(str(exc))
            return
        self.finished.emit(payload)
