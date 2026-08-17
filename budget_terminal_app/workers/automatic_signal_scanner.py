from __future__ import annotations

from ..dependencies import QObject, logger, pyqtSignal
from ..services.automatic_signal_scanner import AutomaticSignalScannerService


class AutomaticSignalScannerWorker(QObject):
    """Run one universe-and-signal scan outside the Qt UI thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

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

    def run(self) -> None:
        logger.info("Starting Signals scan")
        try:
            payload = self.service.run_scan(
                force_universe_refresh=self.force_universe_refresh,
                force_market_refresh=self.force_market_refresh,
                progress=self.progress.emit,
            )
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
