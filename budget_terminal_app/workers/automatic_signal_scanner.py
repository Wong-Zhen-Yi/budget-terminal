from __future__ import annotations

import threading

from ..dependencies import QObject, logger, Signal
from ..services.automatic_signal_scanner import AutomaticSignalScannerService
from ..services.signal_scanner import ScanCancelled


class AutomaticSignalScannerWorker(QObject):
    """Run one universe-and-signal scan outside the Qt UI thread."""

    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)
    cancelled = Signal()

    def __init__(
        self,
        service: AutomaticSignalScannerService,
        *,
        force_universe_refresh: bool = False,
        force_market_refresh: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.force_universe_refresh = bool(force_universe_refresh)
        self.force_market_refresh = bool(force_market_refresh)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the running scan to stop at its next checkpoint.

        ``QThread.quit`` only unwinds the thread's event loop, which does nothing while ``run`` is
        still inside one long synchronous call. Without this flag, closing the window mid-scan
        blocks until the wait timeout expires.
        """

        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:
        logger.info("Starting Signals scan")
        try:
            payload = self.service.run_scan(
                force_universe_refresh=self.force_universe_refresh,
                force_market_refresh=self.force_market_refresh,
                progress=self.progress.emit,
                cancel=self._cancel_event.is_set,
            )
        except ScanCancelled:
            logger.info("Signals scan cancelled")
            self.cancelled.emit()
            return
        except Exception as exc:
            logger.exception("Signals scan failed")
            self.error.emit(str(exc))
            return
        logger.info(
            "Signals completed: %s result(s), %s error(s)",
            len(payload.results),
            len(payload.errors),
        )
        self.finished.emit(payload)
