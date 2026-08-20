from __future__ import annotations

import threading
from typing import Any

from ..dependencies import QObject, logger, pyqtSignal
from ..services.economic import EconomicDataService


class EconomicDataWorker(QObject):
    """Pull the FRED macro catalog outside the Qt UI thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    cancelled = pyqtSignal()

    def __init__(self, service: EconomicDataService, *, groups: Any = None, force: bool = False) -> None:
        super().__init__()
        self.service = service
        self.groups = None if groups is None else [str(item) for item in groups]
        self.force = bool(force)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the running fetch to stop at its next series boundary.

        ``QThread.quit`` only unwinds the thread's event loop, which does nothing while ``run``
        is still inside one synchronous HTTP download. Without this flag, closing the window
        mid-fetch blocks until the wait timeout expires.
        """
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def fetch(self) -> dict[str, Any]:
        """Run the fetch synchronously, for callers that already own a background thread."""
        return self.service.fetch(
            groups=self.groups,
            force=self.force,
            progress=self.progress.emit,
            cancel=self._cancel_event.is_set,
        )

    def run(self) -> None:
        logger.info('Starting economic data fetch')
        try:
            payload = self.fetch()
        except Exception as exc:
            logger.exception('Economic data fetch failed')
            self.error.emit(str(exc))
            return
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        logger.info(
            'Economic data fetch completed: %s series, %s unavailable',
            len(payload.get('rows') or []),
            len(payload.get('missing') or []),
        )
        self.finished.emit(payload)
