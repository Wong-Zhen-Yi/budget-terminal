from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

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
    YahooPaperQuoteService,
    next_recurring_run,
    recurring_due_occurrences,
    recurring_due_window,
)
from budget_terminal_app.paper_trading.engine import MarketSession


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

    def fetch_historical(self, symbol: str, scheduled_for: dt.datetime) -> PaperQuote:
        quote = self.fetch(symbol)
        return PaperQuote(
            **{
                **quote.__dict__,
                "bid": self.price,
                "ask": self.price,
                "last_price": self.price,
                "source_timestamp": scheduled_for,
                "fetched_at": NOW,
                "source": "Historical test quote",
            }
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


def test_schedule_calculations_and_all_due_occurrences() -> None:
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
    occurrences = recurring_due_occurrences(schedule, NOW)
    assert [due.day for due, _future in occurrences] == [10, 11, 12, 13, 14, 15]
    assert occurrences[-1][1] == dt.datetime(2026, 7, 16, 13, 0, tzinfo=dt.timezone.utc)


def test_full_historical_catch_up_orders_every_occurrence_and_preserves_timestamps() -> None:
    current = dt.datetime(2026, 7, 15, 14, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Catch up", 1)
        funding = store.create_recurring_schedule(
            _spec(account["id"], "funding", amount=50),
            next_run_at="2026-07-13T13:00:00+00:00",
        )
        recurring_buy = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=50, symbol="SPYM"),
            next_run_at="2026-07-13T13:00:00+00:00",
        )
        service = RecurringTradingService(
            store,
            _Quotes(100),
            now=lambda: current,
            trading_day_resolver=lambda _date: True,
        )

        result = service.run_due(catch_up=True)
        assert result["claimed"] == 6
        assert result["success"] == 6
        assert service.run_due(catch_up=True)["claimed"] == 0
        assert store.get_recurring_schedule(funding["id"])["next_run_at"] == "2026-07-16T13:00:00+00:00"
        assert store.get_recurring_schedule(recurring_buy["id"])["next_run_at"] == "2026-07-16T13:00:00+00:00"

        buy_runs = store.list_recurring_runs(recurring_buy["id"])
        assert len(buy_runs) == 3
        assert all(run["status"] == "success" for run in buy_runs)
        orders = store.list_orders(account["id"])
        assert [row["submitted_at"] for row in reversed(orders)] == [
            "2026-07-13T13:00:00+00:00",
            "2026-07-14T13:00:00+00:00",
            "2026-07-15T13:00:00+00:00",
        ]
        fills = list(reversed(store.list_fills(account["id"])))
        assert [row["filled_at"] for row in fills] == [row["submitted_at"] for row in reversed(orders)]
        assert [row["quote_timestamp"] for row in fills] == [row["filled_at"] for row in fills]
        funding_events = [
            event for event in store.list_cash_events(account["id"])
            if event["event_type"] == "deposit"
        ]
        assert [event["created_at"] for event in funding_events] == [
            "2026-07-13T13:00:00+00:00",
            "2026-07-14T13:00:00+00:00",
            "2026-07-15T13:00:00+00:00",
        ]


def test_historical_quote_window_validation_and_skipped_run_replay() -> None:
    target = dt.datetime(2026, 7, 23, 13, 0, tzinfo=dt.timezone.utc)
    info = {
        "regularMarketPrice": 88.0,
        "regularMarketTime": int(target.timestamp()),
        "marketState": "REGULAR",
        "exchange": "PCX",
        "currency": "USD",
        "quoteType": "EQUITY",
    }
    history = pd.DataFrame(
        {"Open": [86.9, 87.16, 99.0]},
        index=pd.DatetimeIndex([
            target - dt.timedelta(minutes=1),
            target + dt.timedelta(minutes=2),
            target + dt.timedelta(minutes=16),
        ]),
    )
    service = YahooPaperQuoteService(
        fetch_info=lambda _symbol: info,
        fetch_history=lambda _symbol, _start, _end: history,
    )
    quote = service.fetch_historical("SPYM", target)
    assert quote.quote_type == "EQUITY"
    assert quote.exchange == "PCX"
    assert quote.mark_price == 87.16
    assert quote.mark_timestamp == target + dt.timedelta(minutes=2)

    empty_window = YahooPaperQuoteService(
        fetch_info=lambda _symbol: info,
        fetch_history=lambda _symbol, _start, _end: history.iloc[[2]],
    )
    try:
        empty_window.fetch_historical("SPYM", target)
    except RuntimeError as exc:
        assert "within 15 minutes" in str(exc)
    else:
        raise AssertionError("historical quotes outside the allowed window should fail")

    class _RejectedThenHistorical(_Quotes):
        def fetch(self, symbol: str) -> PaperQuote:
            quote_value = super().fetch(symbol)
            return PaperQuote(**{**quote_value.__dict__, "exchange": "PNK"})

        def fetch_historical(self, symbol: str, scheduled_for: dt.datetime) -> PaperQuote:
            return _Quotes(self.price).fetch_historical(symbol, scheduled_for)

    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Replay", 500)
        schedule = store.create_recurring_schedule(
            _spec(account["id"], "buy", amount=50, symbol="SPYM"),
            next_run_at="2026-07-15T13:00:00+00:00",
        )
        recurring = RecurringTradingService(
            store,
            _RejectedThenHistorical(100),
            now=lambda: NOW,
            trading_day_resolver=lambda _date: True,
        )
        assert recurring.run_due()["skipped"] == 1
        skipped = store.list_recurring_runs(schedule["id"])[0]
        assert "exchange=PNK" in skipped["message"]
        next_run_before = store.get_recurring_schedule(schedule["id"])["next_run_at"]

        replayed = recurring.replay_skipped_run(skipped["id"])
        assert replayed["status"] == "success"
        assert "Recovered after prior skip" in replayed["message"]
        assert "exchange=PNK" in replayed["message"]
        assert store.get_recurring_schedule(schedule["id"])["next_run_at"] == next_run_before
        order = store.get_order(replayed["order_id"])
        assert order["submitted_at"] == skipped["scheduled_for"]
        assert store.list_fills(account["id"])[0]["filled_at"] == skipped["scheduled_for"]


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


if __name__ == "__main__":
    test_schedule_calculations_and_all_due_occurrences()
    test_full_historical_catch_up_orders_every_occurrence_and_preserves_timestamps()
    test_historical_quote_window_validation_and_skipped_run_replay()
    test_funding_before_buy_fractional_budget_and_targeted_execution()
    test_skips_duplicate_claims_and_backup_compatibility()
    print("recurring funding and recurring buy smoke passed")
