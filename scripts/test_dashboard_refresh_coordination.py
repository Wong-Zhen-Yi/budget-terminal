from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from budget_terminal_app.mixins.dashboard import DashboardMixin
from budget_terminal_app.services.refresh_control import RefreshCoordinator


class _QueuedInvoker(QObject):
    dispatched = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.dispatched.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, callback: Callable[[], None]) -> None:
        callback()

    def emit(self, callback: Callable[[], None]) -> None:
        self.dispatched.emit(callback)


class _DashboardCoordinationProbe(DashboardMixin, QObject):
    def __init__(self) -> None:
        QObject.__init__(self)
        self._invoke_main = _QueuedInvoker()
        self._refresh_coordinator = RefreshCoordinator()
        self._dashboard_fetch_executor = None
        self._dashboard_request_seq = 0
        self._dashboard_latest_request_id = 0
        self._dashboard_pending_refresh_reason = "full"
        self._dashboard_refresh_contexts = {}
        self._startup_recent_data_request_keys = set()
        self._startup_dashboard_data_done = True
        self._startup_dashboard_data_actual_done = True
        self.dashboard_symbol = "AAPL"
        self.dashboard_symbol_input = QLineEdit("AAPL")
        self.dashboard_timeframe_label = "1 Day"
        self.dashboard_timeframe_map = {"1 Day": ("1d", "5m")}
        self.dashboard_chart_state = {"symbol": "AAPL", "timeframe_label": "1 Day"}
        self.dashboard_auto_follow = False
        self.dashboard_manual_x_range = None
        self.dashboard_load_btn = QPushButton()
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []
        self.active_jobs = 0
        self.max_active_jobs = 0
        self._lock = threading.Lock()

    def _dashboard_save_state(self) -> None:
        return

    def _get_fetch_tickers(self) -> list[str]:
        return ["AAA", "BBB"]

    def _dashboard_get_current_x_range(self) -> None:
        return None

    def _set_shell_refresh_busy(self, *_args: Any) -> None:
        return

    def _dashboard_set_status(self, *_args: Any) -> None:
        return

    def run_worker(
        self,
        _request_id: int,
        chart_configs_snapshot: Any,
        _refresh_reason: str,
        _allow_non_chart_reuse: bool,
        _fetch_tickers: Any = None,
    ) -> None:
        symbol = str(chart_configs_snapshot[0][0])
        with self._lock:
            self.calls.append(symbol)
            self.active_jobs += 1
            self.max_active_jobs = max(self.max_active_jobs, self.active_jobs)
            first = len(self.calls) == 1
        if first:
            self.started.set()
            if not self.release.wait(2.0):
                raise TimeoutError("test Dashboard provider was not released")
        with self._lock:
            self.active_jobs -= 1

    def close_probe(self) -> None:
        self.release.set()
        executor = self._dashboard_fetch_executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def _wait_until(app: QApplication, predicate: Callable[[], bool], message: str) -> None:
    deadline = time.perf_counter() + 2.0
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate(), message


def test_dashboard_duplicate_and_changed_inputs_are_coalesced() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _DashboardCoordinationProbe()
    key = ("dashboard", "main")
    try:
        probe.refresh_data(force=True, reason="manual_refresh")
        assert probe.started.wait(0.5), "Dashboard worker did not start"
        for _ in range(4):
            probe.refresh_data(force=True, reason="manual_refresh")
        assert probe.calls == ["AAPL"]
        assert probe._refresh_coordinator.pending_token(key) is None

        probe.dashboard_symbol_input.setText("MSFT")
        probe.refresh_data(force=True, reason="manual_refresh")
        probe.dashboard_symbol_input.setText("NVDA")
        probe.refresh_data(force=True, reason="manual_refresh")
        pending = probe._refresh_coordinator.pending_token(key)
        assert pending is not None and pending.input_signature[0] == "NVDA"
        assert probe.calls == ["AAPL"], "changed requests must wait for the active job"

        probe.release.set()
        _wait_until(
            app,
            lambda: probe._refresh_coordinator.active_token(key) is None,
            "Dashboard coordinator did not finish the newest rerun",
        )
        assert probe.calls == ["AAPL", "NVDA"]
        assert probe.max_active_jobs == 1
    finally:
        probe.close_probe()


if __name__ == "__main__":
    test_dashboard_duplicate_and_changed_inputs_are_coalesced()
    print("Dashboard refresh coordination tests passed.")
