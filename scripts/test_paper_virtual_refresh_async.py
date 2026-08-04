from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QWidget

from budget_terminal_app.mixins.virtual_trading import VirtualTradingMixin


_APP = QApplication.instance() or QApplication([])


class _QueuedInvoker(QObject):
    dispatched = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.dispatched.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object)
    def _run(self, callback: Callable[[], None]) -> None:
        callback()

    def emit(self, callback: Callable[[], None]) -> None:
        self.dispatched.emit(callback)


class _Tabs:
    def currentIndex(self) -> int:
        return 0


class _OrderFilter:
    def currentData(self) -> str:
        return "all"


class _ThreadRecordingStore:
    def __init__(self) -> None:
        self.first_read_started = threading.Event()
        self.release_first_read = threading.Event()
        self.calls: list[tuple[str, str, int]] = []
        self._lock = threading.Lock()
        self._blocked_once = False

    def _record(self, method: str, account_id: str) -> None:
        should_block = False
        with self._lock:
            self.calls.append((method, account_id, threading.get_ident()))
            if account_id == "old" and not self._blocked_once:
                self._blocked_once = True
                should_block = True
        if should_block:
            self.first_read_started.set()
            if not self.release_first_read.wait(2.0):
                raise TimeoutError("test database read was not released")

    def account_summary(self, account_id: str) -> dict[str, Any]:
        self._record("account_summary", account_id)
        return {"marker": account_id, "equity": 100.0}

    def list_positions(self, account_id: str) -> list[dict[str, Any]]:
        self._record("list_positions", account_id)
        return [{"marker": account_id}]

    def get_account(self, account_id: str) -> dict[str, Any]:
        self._record("get_account", account_id)
        return {
            "id": account_id,
            "initial_cash": 100.0,
            "marker": account_id,
            "status": "active",
        }

    def net_contributions(self, account_id: str) -> float:
        self._record("net_contributions", account_id)
        return 100.0

    def list_equity_snapshots(self, account_id: str) -> list[dict[str, Any]]:
        self._record("list_equity_snapshots", account_id)
        return [{"marker": account_id}]

    def list_cash_events(self, account_id: str, *, external_only: bool) -> list[dict[str, Any]]:
        assert external_only is True
        self._record("list_cash_events", account_id)
        return []


class _AccountListStore:
    def __init__(self) -> None:
        self.first_read_started = threading.Event()
        self.release_first_read = threading.Event()
        self.calls: list[int] = []
        self._call_count = 0

    def list_accounts(self, *, include_archived: bool) -> list[dict[str, Any]]:
        assert include_archived is True
        self.calls.append(threading.get_ident())
        self._call_count += 1
        if self._call_count == 1:
            self.first_read_started.set()
            if not self.release_first_read.wait(2.0):
                raise TimeoutError("test account read was not released")
        return [
            {"id": "old", "name": "Old", "status": "active"},
            {"id": "new", "name": "New", "status": "active"},
        ]


class _VirtualAccountHarness(VirtualTradingMixin, QObject):
    def __init__(self, store: _AccountListStore) -> None:
        QObject.__init__(self)
        self._invoke_main = _QueuedInvoker()
        self._p32_store = store
        self._p32_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="VirtualAccountsTest")
        self._p32_active_account_id = "old"
        self._p32_active_account_snapshot = None
        self._p32_accounts = []
        self._p32_accounts_request_seq = 0
        self._p32_accounts_refresh_running = False
        self._p32_accounts_refresh_context = ""
        self._p32_accounts_refresh_pending = None
        self._p32_task_inflight = False
        self.p32_account_combo = QComboBox()
        self.p32_empty_state = QWidget()
        self.p32_workspace = QWidget()
        self.p32_edit_account_btn = QPushButton()
        self.p32_archive_account_btn = QPushButton()
        self.p32_review_btn = QPushButton()
        self.statuses: list[str] = []

    def _p32_refresh_all(self) -> None:
        return

    def _p32_set_status(self, message: str, status: str = "muted") -> None:
        self.statuses.append(f"{status}:{message}")

    def close_harness(self) -> None:
        self._p32_executor.shutdown(wait=True, cancel_futures=True)


class _VirtualRefreshHarness(VirtualTradingMixin, QObject):
    def __init__(self, store: _ThreadRecordingStore) -> None:
        QObject.__init__(self)
        self.page32 = object()
        self.visible = False
        self._invoke_main = _QueuedInvoker()
        self._p32_store = store
        self._p32_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="VirtualRefreshTest")
        self._p32_active_account_id = "old"
        self._p32_active_account_snapshot = None
        self._p32_pending_recurring_selection = None
        self._p32_view_request_seq = 0
        self._p32_view_refresh_running = False
        self._p32_view_refresh_context = None
        self._p32_view_refresh_pending = None
        self._p32_view_cache: dict[tuple[str, int, str], dict[str, Any]] = {}
        self.p32_tabs = _Tabs()
        self.p32_order_filter = _OrderFilter()
        self.rendered: list[tuple[str, str, int]] = []

    def _is_current_page(self, page: object) -> bool:
        return self.visible and page is self.page32

    def _p32_refresh_summary(self, snapshot: Any = None) -> None:
        self.rendered.append(
            ("summary", str(snapshot["summary"]["marker"]), threading.get_ident())
        )

    def _p32_refresh_performance(self, *_: Any, snapshot: Any = None) -> None:
        self.rendered.append(
            ("performance", str(snapshot["summary"]["marker"]), threading.get_ident())
        )

    def _p32_refresh_positions(self, rows: Any = None) -> None:
        self.rendered.append(("positions", str(rows[0]["marker"]), threading.get_ident()))

    def close_harness(self) -> None:
        self._p32_executor.shutdown(wait=True, cancel_futures=True)


def _wait_until(
    app: QApplication,
    predicate: Callable[[], bool],
    message: str,
    *,
    timeout: float = 2.0,
) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate(), message


def _assert_store_reads_are_background(store: _ThreadRecordingStore, main_thread_id: int) -> None:
    assert store.calls, "the refresh did not read the fake database"
    assert all(thread_id != main_thread_id for _method, _account, thread_id in store.calls)


def test_virtual_refresh_caches_hidden_newest_view_off_thread() -> None:
    app = QApplication.instance() or QApplication([])
    main_thread_id = threading.get_ident()
    store = _ThreadRecordingStore()
    harness = _VirtualRefreshHarness(store)
    old_context = ("old", 0, "all")
    new_context = ("new", 0, "all")
    try:
        assert harness._p32_has_window_refresh_runtime()
        harness._p32_refresh_all()
        assert store.first_read_started.wait(0.5), "Virtual database worker did not start"
        harness._p32_active_account_id = "new"
        harness._p32_refresh_all()
        assert harness._p32_view_refresh_pending == new_context
        store.release_first_read.set()

        _wait_until(
            app,
            lambda: not harness._p32_view_refresh_running and new_context in harness._p32_view_cache,
            "Virtual hidden refresh did not cache the pending newest context",
        )
        assert old_context in harness._p32_view_cache
        assert harness.rendered == []
        _assert_store_reads_are_background(store, main_thread_id)

        harness.visible = True
        harness._p32_refresh_all()
        assert [(part, marker) for part, marker, _thread in harness.rendered] == [
            ("summary", "new"),
            ("performance", "new"),
            ("positions", "new"),
        ]
        assert all(thread_id == main_thread_id for _part, _marker, thread_id in harness.rendered)

        harness.visible = False
        _wait_until(
            app,
            lambda: not harness._p32_view_refresh_running,
            "Virtual return refresh did not finish",
        )
        assert len(harness.rendered) == 3
        _assert_store_reads_are_background(store, main_thread_id)
    finally:
        store.release_first_read.set()
        harness.close_harness()


def _assert_account_selector_refresh_is_background(harness: Any, store: _AccountListStore) -> None:
    app = QApplication.instance() or QApplication([])
    main_thread_id = threading.get_ident()
    started_at = time.perf_counter()
    harness._p32_refresh_accounts("old")
    assert time.perf_counter() - started_at < 0.05, "Virtual account refresh blocked the UI thread"
    assert store.first_read_started.wait(0.5), "Virtual account worker did not start"
    harness._p32_refresh_accounts("new")
    store.release_first_read.set()
    _wait_until(
        app,
        lambda: not harness._p32_accounts_refresh_running and harness._p32_active_account_id == "new",
        "Virtual account selector did not apply the newest request",
    )
    assert len(store.calls) == 2, "Virtual account refresh should run one active and one newest rerun"
    assert all(thread_id != main_thread_id for thread_id in store.calls), "Virtual read accounts on the UI thread"


def test_virtual_account_selector_loads_off_thread() -> None:
    store = _AccountListStore()
    harness = _VirtualAccountHarness(store)
    try:
        _assert_account_selector_refresh_is_background(harness, store)
    finally:
        store.release_first_read.set()
        harness.close_harness()


if __name__ == "__main__":
    test_virtual_refresh_caches_hidden_newest_view_off_thread()
    test_virtual_account_selector_loads_off_thread()
    print("Virtual asynchronous refresh smoke tests passed.")
