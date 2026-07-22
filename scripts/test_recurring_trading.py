from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.paper_trading import (
    PaperOrderRequest,
    PaperQuote,
    PaperTradingEngine,
    PaperTradingStore,
    RecurringScheduleSpec,
    RecurringTradingService,
    next_recurring_run,
    recurring_due_window,
)
from budget_terminal_app.paper_trading.engine import MarketSession
import budget_terminal_app.mixins.window_bootstrap as window_bootstrap_module
from budget_terminal_app.mixins.window_bootstrap import WindowBootstrapMixin


NOW = dt.datetime(2026, 7, 15, 14, 0, tzinfo=dt.timezone.utc)


class _Quotes:
    def __init__(self, price: float | None = 100.0) -> None:
        self.price = price

    def fetch(self, symbol: str) -> PaperQuote:
        return PaperQuote(
            symbol=symbol,
            bid=99.0 if self.price else None,
            ask=101.0 if self.price else None,
            bid_size=10,
            ask_size=10,
            last_price=self.price,
            exchange="NMS",
            currency="USD",
            quote_type="EQUITY",
            market_state="REGULAR",
            source_timestamp=NOW,
            fetched_at=NOW,
        )


def _open_session(now: dt.datetime) -> MarketSession:
    return MarketSession(True, now + dt.timedelta(hours=2), now + dt.timedelta(hours=2))


def _spec(
    account_id: str,
    kind: str,
    cadence: str = "daily",
    *,
    amount: float = 100.0,
    symbol: str = "",
    local_time: str = "09:00",
    weekday: int | None = None,
    month_day: int | None = None,
    timezone: str = "America/New_York",
) -> RecurringScheduleSpec:
    return RecurringScheduleSpec(
        account_id=account_id,
        kind=kind,
        cadence=cadence,
        amount=amount,
        symbol=symbol,
        timezone=timezone,
        local_time=local_time,
        weekday=weekday,
        month_day=month_day,
    )


def test_schedule_calculations_and_catch_up_once() -> None:
    daily = _spec("account", "funding")
    assert next_recurring_run(daily, NOW) == dt.datetime(2026, 7, 16, 13, 0, tzinfo=dt.timezone.utc)

    weekly = _spec("account", "funding", "weekly", weekday=2)
    assert next_recurring_run(weekly, NOW) == dt.datetime(2026, 7, 22, 13, 0, tzinfo=dt.timezone.utc)

    monthly = _spec("account", "funding", "monthly", month_day=31)
    february = dt.datetime(2027, 2, 1, 12, 0, tzinfo=dt.timezone.utc)
    assert next_recurring_run(monthly, february) == dt.datetime(
        2027, 2, 28, 14, 0, tzinfo=dt.timezone.utc
    )

    schedule = {
        **daily.__dict__,
        "next_run_at": "2026-07-10T13:00:00Z",
    }
    due, future = recurring_due_window(schedule, NOW)
    assert due == dt.datetime(2026, 7, 15, 13, 0, tzinfo=dt.timezone.utc)
    assert future == dt.datetime(2026, 7, 16, 13, 0, tzinfo=dt.timezone.utc)


def test_funding_before_buy_fractional_budget_and_targeted_execution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Automation", 50, commission_per_fill=1.0)
        funding = store.create_recurring_schedule(
            _spec(account["id"], "funding", amount=200),
            next_run_at="2026-07-15T13:59:00Z",
        )
        recurring_buy = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=100, symbol="AAPL"),
            next_run_at="2026-07-15T13:59:00Z",
        )

        manual_engine = PaperTradingEngine(
            store,
            _Quotes(),
            now=lambda: NOW,
            session_resolver=_open_session,
        )
        unrelated = manual_engine.submit_order(
            PaperOrderRequest(account["id"], "MSFT", "buy", 1.25, "limit", "gtc", limit_price=10),
            quote=_Quotes().fetch("MSFT"),
        )

        service = RecurringTradingService(
            store,
            _Quotes(),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: True,
        )
        result = service.run_due()
        assert result["claimed"] == 2
        assert result["success"] == 2
        assert store.get_order(unrelated["id"])["status"] == "pending"

        funding_run = store.list_recurring_runs(funding["id"])[0]
        buy_run = store.list_recurring_runs(recurring_buy["id"])[0]
        assert funding_run["status"] == "success"
        assert funding_run["cash_event_id"]
        funding_event = next(
            event for event in store.list_cash_events(account["id"])
            if event["id"] == funding_run["cash_event_id"]
        )
        assert funding_event["event_type"] == "deposit"
        assert float(funding_event["amount"]) == 200.0
        assert buy_run["status"] == "success"
        assert buy_run["order_id"]
        quantity = float(buy_run["quantity"])
        assert 0 < quantity < 1
        fill = next(row for row in store.list_fills(account["id"]) if row["order_id"] == buy_run["order_id"])
        debit = float(fill["fill_price"]) * quantity + float(fill["commission"])
        assert debit <= 100.0 + 1e-7
        assert float(store.list_positions(account["id"])[0]["quantity"]) == quantity
        assert store.net_contributions(account["id"]) == 250.0

        assert service.run_due()["claimed"] == 0
        store.archive_account(account["id"])
        assert all(row["status"] == "paused" for row in store.list_recurring_schedules(account["id"]))
        store.restore_account(account["id"])
        assert all(row["status"] == "paused" for row in store.list_recurring_schedules(account["id"]))


def test_skips_duplicate_claims_and_backup_compatibility() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = PaperTradingStore(root / "source.db")
        account = store.create_account("Skips", 20)
        insufficient = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=100, symbol="AAPL"),
            next_run_at="2026-07-15T13:59:00Z",
        )
        service = RecurringTradingService(
            store,
            _Quotes(),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: True,
        )
        result = service.run_due()
        assert result["claimed"] == 1
        assert result["skipped"] == 1
        assert "available" in store.list_recurring_runs(insufficient["id"])[0]["message"]
        assert service.run_due()["claimed"] == 0

        closed = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=10, symbol="MSFT"),
            next_run_at="2026-07-15T13:59:00Z",
        )
        closed_service = RecurringTradingService(
            store,
            _Quotes(),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: False,
        )
        assert closed_service.run_due()["skipped"] == 1
        assert "NYSE trading day" in store.list_recurring_runs(closed["id"])[0]["message"]

        unusable = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=10, symbol="TSLA"),
            next_run_at="2026-07-15T13:59:00Z",
        )
        quote_service = RecurringTradingService(
            store,
            _Quotes(price=None),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: True,
        )
        assert quote_service.run_due()["skipped"] == 1
        assert "usable Virtual price" in store.list_recurring_runs(unusable["id"])[0]["message"]

        limit_account = store.create_account("Funding limit", 999_999_990)
        over_limit = store.create_recurring_schedule(
            _spec(limit_account["id"], "funding", amount=20),
            next_run_at="2026-07-15T13:59:00Z",
        )
        limit_result = RecurringTradingService(
            store,
            _Quotes(),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: True,
        ).run_due()
        assert limit_result["failed"] == 1
        assert store.cash_balance(limit_account["id"]) == 999_999_990
        assert "cash limit" in store.list_recurring_runs(over_limit["id"])[0]["message"]

        payload = store.build_backup()
        assert payload["version"] == 4
        assert len(payload["tables"]["recurring_schedules"]) == 4
        target = PaperTradingStore(root / "target.db")
        target.import_backup(payload)
        assert len(target.list_recurring_schedules(account["id"])) == 3
        assert len(target.list_recurring_runs(closed["id"])) == 1

        legacy = json.loads(json.dumps(payload))
        legacy["version"] = 3
        legacy["tables"].pop("recurring_schedules")
        legacy["tables"].pop("recurring_runs")
        legacy_path = root / "legacy.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        normalized = PaperTradingStore.load_backup(legacy_path)
        assert normalized["tables"]["recurring_schedules"] == []
        assert normalized["tables"]["recurring_runs"] == []

        migration_path = root / "migration-v3.db"
        migration_store = PaperTradingStore(migration_path)
        migrated_account = migration_store.create_account("Existing v3", 5_000)
        connection = sqlite3.connect(migration_path)
        try:
            connection.execute("DROP TABLE recurring_runs")
            connection.execute("DROP TABLE recurring_schedules")
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        finally:
            connection.close()
        migrated = PaperTradingStore(migration_path)
        assert migrated.cash_balance(migrated_account["id"]) == 5_000
        connection = sqlite3.connect(migration_path)
        try:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        finally:
            connection.close()
        migrated.create_recurring_schedule(
            _spec(migrated_account["id"], "funding", amount=25),
            next_run_at="2026-07-16T13:00:00Z",
        )


class _QueuedInvokeSignal:
    def __init__(self) -> None:
        self.callbacks = []
        self.ready = threading.Event()

    def emit(self, callback) -> None:
        self.callbacks.append(callback)
        self.ready.set()


class _RecurringSchedulerProbe(WindowBootstrapMixin):
    def __init__(self) -> None:
        self.health_warnings = []
        self._invoke_main = _QueuedInvokeSignal()

    def drain_main_callbacks(self) -> None:
        while self._invoke_main.callbacks:
            self._invoke_main.callbacks.pop(0)()
        self._invoke_main.ready.clear()

    def _record_data_health_exception(self, subsystem, error, *, symbols=None, severity="issue") -> None:
        self.health_warnings.append({
            "subsystem": subsystem,
            "error": str(error),
            "severity": severity,
        })


def test_recurring_scheduler_startup_is_deferred_and_store_failure_is_optional() -> None:
    scheduled = []
    service_calls = []

    class _DeferredTimer:
        @staticmethod
        def singleShot(delay, callback) -> None:
            scheduled.append((delay, callback))

    class _UnavailableService:
        def __init__(self) -> None:
            service_calls.append(True)
            raise sqlite3.DatabaseError("paper database is malformed")

    original_timer = window_bootstrap_module.QTimer
    original_service = window_bootstrap_module.RecurringTradingService
    try:
        window_bootstrap_module.QTimer = _DeferredTimer
        window_bootstrap_module.RecurringTradingService = _UnavailableService
        probe = _RecurringSchedulerProbe()
        probe._init_recurring_scheduler()

        assert probe._recurring_scheduler_startup_status == "pending"
        assert probe._recurring_scheduler_activation_pending is True
        assert service_calls == []
        assert len(scheduled) == 1
        assert scheduled[0][0] == probe._RECURRING_SCHEDULER_START_DELAY_MS
        assert scheduled[0][0] > 0

        scheduled[0][1]()
        assert probe._invoke_main.ready.wait(2.0)
        probe.drain_main_callbacks()

        assert service_calls == [True]
        assert probe._recurring_scheduler_startup_status == "disabled"
        assert probe._recurring_scheduler_available is False
        assert probe._recurring_scheduler_service is None
        assert probe._recurring_scheduler_executor is None
        assert probe._recurring_scheduler_timer is None
        assert "paper database is malformed" in probe._recurring_scheduler_startup_error
        assert probe.health_warnings == [{
            "subsystem": "Recurring automation",
            "error": "paper database is malformed",
            "severity": "warning",
        }]
    finally:
        window_bootstrap_module.QTimer = original_timer
        window_bootstrap_module.RecurringTradingService = original_service


def test_recurring_scheduler_partial_startup_failure_releases_resources() -> None:
    scheduled = []
    timer_instances = []
    executor_instances = []

    class _BrokenTimer:
        @staticmethod
        def singleShot(delay, callback) -> None:
            scheduled.append((delay, callback))

        def __init__(self, _parent=None) -> None:
            self.stopped = False
            self.released = False
            timer_instances.append(self)

        def setInterval(self, _interval) -> None:
            raise RuntimeError("timer initialization failed")

        def stop(self) -> None:
            self.stopped = True

        def deleteLater(self) -> None:
            self.released = True

    class _Executor:
        def __init__(self, **_kwargs) -> None:
            self.shutdown_args = None
            executor_instances.append(self)

        def submit(self, callback):
            future = Future()
            try:
                future.set_result(callback())
            except Exception as exc:
                future.set_exception(exc)
            return future

        def shutdown(self, *, wait, cancel_futures) -> None:
            self.shutdown_args = (wait, cancel_futures)

    class _Service:
        def run_due(self):
            return {"claimed": 0}

    original_timer = window_bootstrap_module.QTimer
    original_service = window_bootstrap_module.RecurringTradingService
    original_executor = window_bootstrap_module.ThreadPoolExecutor
    try:
        window_bootstrap_module.QTimer = _BrokenTimer
        window_bootstrap_module.RecurringTradingService = _Service
        window_bootstrap_module.ThreadPoolExecutor = _Executor
        probe = _RecurringSchedulerProbe()
        probe._init_recurring_scheduler()
        scheduled[0][1]()
        probe.drain_main_callbacks()

        assert probe._recurring_scheduler_startup_status == "disabled"
        assert probe._recurring_scheduler_service is None
        assert probe._recurring_scheduler_executor is None
        assert probe._recurring_scheduler_timer is None
        assert len(timer_instances) == 1
        assert timer_instances[0].stopped is True
        assert timer_instances[0].released is True
        assert len(executor_instances) == 1
        assert executor_instances[0].shutdown_args == (False, True)
        assert "timer initialization failed" in probe._recurring_scheduler_startup_error
    finally:
        window_bootstrap_module.QTimer = original_timer
        window_bootstrap_module.RecurringTradingService = original_service
        window_bootstrap_module.ThreadPoolExecutor = original_executor


def test_recurring_scheduler_service_initialization_does_not_block_ui_thread() -> None:
    scheduled = []
    timer_instances = []
    service_started = threading.Event()
    release_service = threading.Event()

    class _TimeoutSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

    class _Timer:
        @staticmethod
        def singleShot(delay, callback) -> None:
            scheduled.append((delay, callback))

        def __init__(self, _parent=None) -> None:
            self.timeout = _TimeoutSignal()
            self.interval = None
            self.started = False
            self.stopped = False
            timer_instances.append(self)

        def setInterval(self, interval) -> None:
            self.interval = interval

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def deleteLater(self) -> None:
            return

    class _SlowService:
        def __init__(self) -> None:
            service_started.set()
            assert release_service.wait(2.0)

        def run_due(self):
            return {"claimed": 0}

    original_timer = window_bootstrap_module.QTimer
    original_service = window_bootstrap_module.RecurringTradingService
    try:
        window_bootstrap_module.QTimer = _Timer
        window_bootstrap_module.RecurringTradingService = _SlowService
        probe = _RecurringSchedulerProbe()
        probe._init_recurring_scheduler()

        started_at = time.perf_counter()
        scheduled.pop(0)[1]()
        activation_seconds = time.perf_counter() - started_at

        assert activation_seconds < 0.5
        assert service_started.wait(1.0)
        assert probe._recurring_scheduler_startup_status == "starting"
        assert probe._recurring_scheduler_service is None
        assert probe._recurring_scheduler_timer is None

        release_service.set()
        assert probe._invoke_main.ready.wait(2.0)
        probe.drain_main_callbacks()

        assert probe._recurring_scheduler_startup_status == "ready"
        assert probe._recurring_scheduler_available is True
        assert isinstance(probe._recurring_scheduler_service, _SlowService)
        assert len(timer_instances) == 1
        assert timer_instances[0].started is True
        assert scheduled == [(0, probe._run_recurring_scheduler)]
        probe._stop_recurring_scheduler()
        assert timer_instances[0].stopped is True
    finally:
        release_service.set()
        window_bootstrap_module.QTimer = original_timer
        window_bootstrap_module.RecurringTradingService = original_service


def test_recurring_scheduler_stop_during_initialization_is_race_safe() -> None:
    scheduled = []
    service_started = threading.Event()
    release_service = threading.Event()

    class _DeferredTimer:
        @staticmethod
        def singleShot(delay, callback) -> None:
            scheduled.append((delay, callback))

    class _SlowService:
        def __init__(self) -> None:
            service_started.set()
            assert release_service.wait(2.0)

    original_timer = window_bootstrap_module.QTimer
    original_service = window_bootstrap_module.RecurringTradingService
    try:
        window_bootstrap_module.QTimer = _DeferredTimer
        window_bootstrap_module.RecurringTradingService = _SlowService
        probe = _RecurringSchedulerProbe()
        probe._init_recurring_scheduler()
        scheduled[0][1]()
        assert service_started.wait(1.0)

        probe._stop_recurring_scheduler()
        assert probe._recurring_scheduler_startup_status == "stopped"
        assert probe._recurring_scheduler_executor is None
        assert probe._recurring_scheduler_init_future is None

        release_service.set()
        assert probe._invoke_main.ready.wait(2.0)
        probe.drain_main_callbacks()

        assert probe._recurring_scheduler_startup_status == "stopped"
        assert probe._recurring_scheduler_available is False
        assert probe._recurring_scheduler_service is None
        assert probe._recurring_scheduler_timer is None
    finally:
        release_service.set()
        window_bootstrap_module.QTimer = original_timer
        window_bootstrap_module.RecurringTradingService = original_service


if __name__ == "__main__":
    test_schedule_calculations_and_catch_up_once()
    test_funding_before_buy_fractional_budget_and_targeted_execution()
    test_skips_duplicate_claims_and_backup_compatibility()
    test_recurring_scheduler_startup_is_deferred_and_store_failure_is_optional()
    test_recurring_scheduler_partial_startup_failure_releases_resources()
    test_recurring_scheduler_service_initialization_does_not_block_ui_thread()
    test_recurring_scheduler_stop_during_initialization_is_race_safe()
    print("recurring funding and recurring buy smoke passed")
