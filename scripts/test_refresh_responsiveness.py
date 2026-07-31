from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-refresh-responsive-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget

from test_portfolio_positions_row_stability import _PortfolioProbe
from test_tab_picker_search import _build_window


class _QueuedInvoker(QObject):
    invoked = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.invoked.connect(lambda callback: callback())

    def emit(self, callback) -> None:
        self.invoked.emit(callback)


class _BlockingPortfolioClient:
    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self.started = threading.Event()
        self.thread_ids: list[int] = []

    def fetch_portfolio_quotes(self, tickers):
        self.thread_ids.append(threading.get_ident())
        self.started.set()
        if not self.release.wait(2.0):
            raise TimeoutError("test quote provider was not released")
        return {
            "portfolio": {
                str(ticker): {"price": 100.0 + index, "change": 1.0}
                for index, ticker in enumerate(tickers)
            }
        }

    def fetch_market_caps(self, tickers):
        self.thread_ids.append(threading.get_ident())
        return {str(ticker): 1_000_000_000.0 for ticker in tickers}

    def fetch_month_returns(self, tickers, **_kwargs):
        self.thread_ids.append(threading.get_ident())
        return {str(ticker): 1.0 for ticker in tickers}

    def fetch_portfolio_momentum(self, *_args, **_kwargs):
        self.thread_ids.append(threading.get_ident())
        return {"dates": [], "returns": []}

    def fetch_portfolio_analytics(self, *_args, **_kwargs):
        self.thread_ids.append(threading.get_ident())
        return {"metrics": {}, "exposure": {}}


class _ResponsivePortfolioProbe(_PortfolioProbe):
    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self._queued_invoker = _QueuedInvoker()
        self._invoke_main = self._queued_invoker
        self._data_service_client = _BlockingPortfolioClient(release)
        self._test_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="RefreshResponsiveness")
        self.page4 = QWidget()
        self.destination_page = QWidget()
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.page4)
        self.stacked_widget.addWidget(self.destination_page)
        self.stacked_widget.setCurrentWidget(self.page4)

    def _p4_submit_background_task(self, fn) -> None:
        self._test_executor.submit(fn)

    def close_probe(self) -> None:
        self._test_executor.shutdown(wait=True, cancel_futures=True)


def test_blocked_holdings_provider_does_not_block_navigation() -> None:
    app = QApplication.instance() or QApplication([])
    release = threading.Event()
    probe = _ResponsivePortfolioProbe(release)
    heartbeat_times: list[float] = []
    started_at = time.perf_counter()
    navigation_times: list[float] = []
    heartbeat = QTimer()
    heartbeat.setInterval(25)
    heartbeat.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))
    heartbeat.start()

    try:
        main_thread_id = threading.get_ident()
        probe._p4_refresh_holdings()
        assert probe._data_service_client.started.wait(0.5), "quote provider did not start"

        def navigate() -> None:
            probe.stacked_widget.setCurrentWidget(probe.destination_page)
            navigation_times.append(time.perf_counter())

        loop = QEventLoop()
        QTimer.singleShot(25, navigate)
        QTimer.singleShot(350, loop.quit)
        loop.exec()

        assert not release.is_set(), "provider should still be blocked during the navigation check"
        assert probe.stacked_widget.currentWidget() is probe.destination_page
        navigation_limit = 0.35 if os.environ.get("CI") else 0.25
        assert navigation_times and navigation_times[0] - started_at <= navigation_limit
        assert len(heartbeat_times) >= 5, f"UI heartbeat fired only {len(heartbeat_times)} time(s)"
        samples = [started_at, *heartbeat_times]
        max_gap = max(right - left for left, right in zip(samples, samples[1:]))
        assert max_gap <= 0.20, f"UI heartbeat stalled for {max_gap:.3f}s"
        assert probe._data_service_client.thread_ids
        assert all(thread_id != main_thread_id for thread_id in probe._data_service_client.thread_ids)

        release.set()
        deadline = time.perf_counter() + 2.0
        while not probe.p4_refresh_holdings_btn.isEnabled() and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert probe.p4_refresh_holdings_btn.isEnabled(), "holdings refresh did not clear its busy state"
    finally:
        release.set()
        heartbeat.stop()
        deadline = time.perf_counter() + 1.0
        while not probe.p4_refresh_holdings_btn.isEnabled() and time.perf_counter() < deadline:
            app.processEvents()
        probe.close_probe()


def test_full_window_navigates_while_holdings_provider_is_blocked() -> None:
    app, window = _build_window()
    release = threading.Event()
    client = _BlockingPortfolioClient(release)
    heartbeat_times: list[float] = []
    navigation_times: list[float] = []
    heartbeat = QTimer()
    heartbeat.setInterval(25)
    heartbeat.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))

    try:
        window.switch_page(1)
        app.processEvents()
        window._data_service_client = client
        started_at = time.perf_counter()
        heartbeat.start()
        window._p4_refresh_holdings()
        assert client.started.wait(0.5), "full-window quote provider did not start"

        def navigate() -> None:
            window.switch_page(0)
            navigation_times.append(time.perf_counter())

        loop = QEventLoop()
        QTimer.singleShot(25, navigate)
        QTimer.singleShot(350, loop.quit)
        loop.exec()

        navigation_limit = 0.35 if os.environ.get("CI") else 0.25
        assert window.stacked_widget.currentIndex() == 0
        assert navigation_times and navigation_times[0] - started_at <= navigation_limit
        assert len(heartbeat_times) >= 5
        samples = [started_at, *heartbeat_times]
        assert max(right - left for left, right in zip(samples, samples[1:])) <= 0.20
        assert all(thread_id != threading.get_ident() for thread_id in client.thread_ids)
    finally:
        release.set()
        heartbeat.stop()
        deadline = time.perf_counter() + 2.0
        while not window.p4_refresh_holdings_btn.isEnabled() and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        executor = getattr(window, "_portfolio_task_executor", None)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    test_blocked_holdings_provider_does_not_block_navigation()
    test_full_window_navigates_while_holdings_provider_is_blocked()
    print("Refresh responsiveness smoke tests passed.")
