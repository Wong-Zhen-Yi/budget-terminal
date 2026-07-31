from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.paper_trading import (
    PaperOrderRequest,
    PaperQuote,
    PaperTradingEngine,
    PaperTradingStore,
    YahooPaperQuoteService,
)
from budget_terminal_app.paper_trading.engine import MarketSession


NOW = dt.datetime(2026, 7, 15, 14, 0, tzinfo=dt.timezone.utc)


def _quote(
    symbol: str = "AAPL",
    *,
    bid: float | None = 99.0,
    ask: float | None = 100.0,
    timestamp: dt.datetime | None = NOW,
    exchange: str = "NMS",
    quote_type: str = "EQUITY",
    market_state: str = "REGULAR",
    mark_price: float | None = None,
    mark_timestamp: dt.datetime | None = None,
    mark_session: str = "",
) -> PaperQuote:
    return PaperQuote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        bid_size=10,
        ask_size=10,
        last_price=99.5,
        exchange=exchange,
        currency="USD",
        quote_type=quote_type,
        market_state=market_state,
        source_timestamp=timestamp,
        fetched_at=NOW,
        mark_price=mark_price,
        mark_timestamp=mark_timestamp,
        mark_session=mark_session,
    )


def _open_session(now: dt.datetime) -> MarketSession:
    return MarketSession(True, now + dt.timedelta(hours=2), now + dt.timedelta(hours=2))


def _engine(path: Path, now=lambda: NOW) -> tuple[PaperTradingStore, PaperTradingEngine]:
    store = PaperTradingStore(path)
    engine = PaperTradingEngine(store, now=now, session_resolver=_open_session)
    return store, engine


def test_market_limit_stop_and_average_cost() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "paper.db")
        account = store.create_account("Core", 100_000)
        store.update_account(account["id"], initial_cash=120_000)
        assert store.cash_balance(account["id"]) == 120_000

        market = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 10, "market", "day"),
            quote=_quote(),
        )
        result = engine.process_pending_orders(quotes={"AAPL": _quote()})
        assert result["filled"] == 1
        fill = store.list_fills(account["id"])[0]
        assert fill["order_id"] == market["id"]
        assert abs(float(fill["fill_price"]) - 100.05) < 1e-9
        try:
            store.update_account(account["id"], initial_cash=125_000)
        except ValueError as exc:
            assert "first order" in str(exc)
        else:
            raise AssertionError("starting cash should lock after the first submitted order")
        position = store.list_positions(account["id"])[0]
        assert position["quantity"] == 10
        assert abs(float(position["average_cost"]) - 100.05) < 1e-9

        limit = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 5, "limit", "gtc", limit_price=98),
            quote=_quote(),
        )
        engine.process_pending_orders(quotes={"AAPL": _quote(bid=98.4, ask=98.5)})
        assert store.get_order(limit["id"])["status"] == "pending"
        engine.process_pending_orders(quotes={"AAPL": _quote(bid=97.8, ask=97.9)})
        limit_fill = next(item for item in store.list_fills(account["id"]) if item["order_id"] == limit["id"])
        assert float(limit_fill["fill_price"]) <= 98.0

        stop = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "sell", 5, "stop", "gtc", stop_price=95),
            quote=_quote(),
        )
        engine.process_pending_orders(quotes={"AAPL": _quote(bid=96, ask=96.2)})
        assert store.get_order(stop["id"])["status"] == "pending"
        engine.process_pending_orders(quotes={"AAPL": _quote(bid=94.8, ask=95)})
        sell_fill = next(item for item in store.list_fills(account["id"]) if item["order_id"] == stop["id"])
        assert abs(float(sell_fill["fill_price"]) - (94.8 * 0.9995)) < 1e-6
        assert store.get_order(stop["id"])["triggered_at"] is not None
        remaining = store.list_positions(account["id"])[0]
        assert remaining["quantity"] == 10
        assert float(remaining["realized_pnl"]) < 0


def test_fractional_manual_orders_reservations_positions_and_pnl() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "fractional.db")
        account = store.create_account("Fractional", 10_000)
        order = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1.234567, "market", "day"),
            quote=_quote(),
        )
        assert store.get_order(order["id"])["quantity"] == 1.234567
        assert engine.process_pending_orders(quotes={"AAPL": _quote()})["filled"] == 1
        position = store.list_positions(account["id"])[0]
        assert float(position["quantity"]) == 1.234567

        sell = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "sell", 0.234567, "limit", "gtc", limit_price=99),
            quote=_quote(),
        )
        assert abs(store.available_shares(account["id"], "AAPL") - 1.0) < 1e-7
        assert engine.process_pending_orders(quotes={"AAPL": _quote()})["filled"] == 1
        assert store.get_order(sell["id"])["status"] == "filled"
        remaining = store.list_positions(account["id"])[0]
        assert abs(float(remaining["quantity"]) - 1.0) < 1e-7
        assert float(remaining["realized_pnl"]) != 0


def test_exact_cash_balance_adjustments_and_atomic_validation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "paper.db")
        account = store.create_account("Cash editor", 10_000)
        store.update_account(account["id"], target_cash=12_000)
        updated = store.get_account(account["id"])
        assert float(updated["initial_cash"]) == 12_000
        assert store.cash_balance(account["id"]) == 12_000
        assert [event["event_type"] for event in store.list_cash_events(account["id"])] == ["initial_deposit"]

        order = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 10, "market", "day"),
            quote=_quote(),
        )
        assert engine.process_pending_orders(quotes={"AAPL": _quote()})["filled"] == 1
        assert store.get_order(order["id"])["status"] == "filled"
        positions_before = store.list_positions(account["id"])
        fills_before = store.list_fills(account["id"])
        return_before = store.account_summary(account["id"])["equity"] - store.net_contributions(account["id"])

        prior_cash = store.cash_balance(account["id"])
        store.update_account(account["id"], target_cash=prior_cash + 5_000)
        assert store.cash_balance(account["id"]) == prior_cash + 5_000
        assert store.net_contributions(account["id"]) == 17_000
        assert store.list_cash_events(account["id"])[-1]["event_type"] == "deposit"
        assert float(store.list_cash_events(account["id"])[-1]["amount"]) == 5_000

        store.update_account(account["id"], target_cash=prior_cash + 3_000)
        assert store.cash_balance(account["id"]) == prior_cash + 3_000
        assert store.net_contributions(account["id"]) == 15_000
        assert store.list_cash_events(account["id"])[-1]["event_type"] == "withdrawal"
        assert float(store.list_cash_events(account["id"])[-1]["amount"]) == -2_000
        return_after = store.account_summary(account["id"])["equity"] - store.net_contributions(account["id"])
        assert abs(float(return_after) - float(return_before)) < 1e-7
        assert store.list_positions(account["id"]) == positions_before
        assert store.list_fills(account["id"]) == fills_before

        other = store.create_account("Duplicate", 2_000)
        account_before = store.get_account(account["id"])
        cash_before = store.cash_balance(account["id"])
        try:
            store.update_account(account["id"], name=other["name"], target_cash=cash_before + 100)
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("duplicate account names should reject the entire account update")
        assert store.get_account(account["id"]) == account_before
        assert store.cash_balance(account["id"]) == cash_before

        try:
            store.update_account(account["id"], target_cash=-1)
        except ValueError as exc:
            assert "zero or greater" in str(exc)
        else:
            raise AssertionError("negative target cash should be rejected")

        store.archive_account(account["id"])
        try:
            store.update_account(account["id"], target_cash=cash_before + 1_000)
        except ValueError as exc:
            assert "Restore" in str(exc)
        else:
            raise AssertionError("archived accounts should reject cash adjustments")


def test_reserved_cash_floor_and_v2_cash_event_migration() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store, engine = _engine(root / "reserved.db")
        account = store.create_account("Reserved", 1_000)
        engine.submit_order(
            PaperOrderRequest(account["id"], "MSFT", "buy", 5, "limit", "gtc", limit_price=100),
            quote=_quote("MSFT"),
        )
        account_before = store.get_account(account["id"])
        try:
            store.update_account(account["id"], name="Should roll back", target_cash=499)
        except ValueError as exc:
            assert "$500.00" in str(exc)
        else:
            raise AssertionError("cash below pending-order reservations should be rejected")
        assert store.get_account(account["id"]) == account_before
        assert store.cash_balance(account["id"]) == 1_000

        migration_path = root / "migration.db"
        migration_store = PaperTradingStore(migration_path)
        migrated_account = migration_store.create_account("Migrated", 3_000)
        connection = sqlite3.connect(migration_path)
        try:
            connection.executescript(
                """
                ALTER TABLE cash_events RENAME TO cash_events_v3_source;
                CREATE TABLE cash_events (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    fill_id TEXT UNIQUE REFERENCES fills(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL CHECK (event_type IN ('initial_deposit', 'trade')),
                    amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO cash_events SELECT * FROM cash_events_v3_source;
                DROP TABLE cash_events_v3_source;
                CREATE INDEX idx_cash_events_account_time ON cash_events(account_id, created_at);
                PRAGMA user_version = 2;
                """
            )
        finally:
            connection.close()
        migrated_store = PaperTradingStore(migration_path)
        assert migrated_store.cash_balance(migrated_account["id"]) == 3_000
        migrated_store.update_account(migrated_account["id"], target_cash=4_000)
        assert migrated_store.cash_balance(migrated_account["id"]) == 4_000


def test_reservations_rejections_stale_quotes_and_idempotency() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "paper.db")
        account = store.create_account("Risk", 1_000)
        order = engine.submit_order(
            PaperOrderRequest(account["id"], "MSFT", "buy", 5, "limit", "gtc", limit_price=100),
            quote=_quote("MSFT"),
        )
        assert store.reserved_cash(account["id"]) == 500
        try:
            engine.submit_order(
                PaperOrderRequest(account["id"], "MSFT", "buy", 6, "limit", "gtc", limit_price=100),
                quote=_quote("MSFT"),
            )
        except ValueError as exc:
            assert "buying power" in str(exc)
        else:
            raise AssertionError("reservation should block over-ordering")

        stale = _quote("MSFT", timestamp=NOW - dt.timedelta(minutes=21))
        engine.process_pending_orders(quotes={"MSFT": stale})
        assert store.get_order(order["id"])["status"] == "pending"
        assert "stale" in store.get_order(order["id"])["last_evaluation"].lower()
        engine.process_pending_orders(quotes={"MSFT": _quote("MSFT", bid=99, ask=100)})
        assert store.get_order(order["id"])["status"] == "filled"
        engine.process_pending_orders(quotes={"MSFT": _quote("MSFT", bid=99, ask=100)})
        assert len(store.list_fills(account["id"])) == 1

        try:
            engine.submit_order(
                PaperOrderRequest(account["id"], "MSFT", "sell", 6, "market", "day"),
                quote=_quote("MSFT"),
            )
        except ValueError as exc:
            assert "unreserved share" in str(exc)
        else:
            raise AssertionError("short sale should be rejected")


def test_day_expiry_archive_and_account_isolation() -> None:
    current = [NOW]

    def now() -> dt.datetime:
        return current[0]

    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "paper.db", now=now)
        first = store.create_account("One", 10_000)
        second = store.create_account("Two", 20_000)
        store.create_account("Three", 30_000)
        store.create_account("Four", 40_000)
        store.create_account("Five", 50_000)
        try:
            store.create_account("Six", 60_000)
        except ValueError as exc:
            assert "five accounts" in str(exc)
        else:
            raise AssertionError("the sixth paper account should be rejected")
        order = engine.submit_order(
            PaperOrderRequest(first["id"], "NVDA", "buy", 1, "limit", "day", limit_price=50),
            quote=_quote("NVDA", bid=99, ask=100),
        )
        expires = dt.datetime.fromisoformat(store.get_order(order["id"])["expires_at"])
        current[0] = expires + dt.timedelta(seconds=1)
        engine.process_pending_orders(quotes={"NVDA": _quote("NVDA", bid=49, ask=50, timestamp=current[0])})
        assert store.get_order(order["id"])["status"] == "expired"
        assert store.cash_balance(second["id"]) == 20_000

        pending = engine.submit_order(
            PaperOrderRequest(first["id"], "AAPL", "buy", 1, "limit", "gtc", limit_price=50),
            quote=_quote(timestamp=current[0]),
        )
        store.archive_account(first["id"])
        assert store.get_order(pending["id"])["status"] == "cancelled"
        assert store.get_account(first["id"])["status"] == "archived"
        store.restore_account(first["id"])
        assert store.get_account(first["id"])["status"] == "active"


def test_backup_import_and_reset_round_trip() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, source_engine = _engine(root / "source.db")
        account = source.create_account("Backup", 12_345)
        source.save_journal_entry(account["id"], "Keep this", ["audit"])
        source_engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "market", "day"),
            quote=_quote(),
        )
        assert source_engine.process_pending_orders(quotes={"AAPL": _quote()})["filled"] == 1
        source.update_account(account["id"], target_cash=15_000)
        backup_path = root / "paper.json"
        source.export_backup(backup_path)
        payload = source.load_backup(backup_path)
        assert payload["backup_type"] == "budget_terminal_paper_trading"

        target, _ = _engine(root / "target.db")
        target.create_account("Replace", 1_000)
        rollback = target.import_backup(payload)
        assert Path(rollback).exists()
        assert [item["name"] for item in target.list_accounts()] == ["Backup"]
        assert target.list_journal(account["id"])[0]["note"] == "Keep this"
        assert target.cash_balance(account["id"]) == 15_000
        assert target.list_cash_events(account["id"])[-1]["event_type"] == "deposit"
        reset_rollback = target.reset()
        assert Path(reset_rollback).exists()
        assert target.list_accounts(include_archived=True) == []

        parsed = json.loads(backup_path.read_text(encoding="utf-8"))
        parsed["tables"]["accounts"][0]["currency"] = "SGD"
        bad_path = root / "bad.json"
        bad_path.write_text(json.dumps(parsed), encoding="utf-8")
        target.create_account("Still Here", 5_000)
        try:
            target.import_backup(target.load_backup(bad_path))
        except Exception:
            pass
        else:
            raise AssertionError("invalid account currency should fail import")
        assert [item["name"] for item in target.list_accounts()] == ["Still Here"]


def test_cycle_deduplicates_order_and_position_symbols() -> None:
    class CountingQuotes:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch(self, symbol: str) -> PaperQuote:
            self.calls.append(symbol)
            return _quote(symbol)

    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        quotes = CountingQuotes()
        engine = PaperTradingEngine(store, quote_service=quotes, now=lambda: NOW, session_resolver=_open_session)
        account = store.create_account("Dedupe", 100_000)
        first = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "market", "day"),
            quote=_quote(),
        )
        engine.process_pending_orders(quotes={"AAPL": _quote()})
        assert store.get_order(first["id"])["status"] == "filled"
        engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "limit", "gtc", limit_price=50),
            quote=_quote(),
        )
        result = engine.run_cycle(mark=True)
        assert quotes.calls == ["AAPL"]
        assert result["marks"]["updated"] == 1


def test_yahoo_quote_extracts_premarket_mark_without_replacing_execution_fields() -> None:
    regular_time = int(NOW.timestamp())
    premarket_time = int((NOW + dt.timedelta(hours=1)).timestamp())
    service = YahooPaperQuoteService(
        fetch_info=lambda _symbol: {
            "symbol": "AAPL",
            "bid": 99.0,
            "ask": 100.0,
            "regularMarketPrice": 98.5,
            "regularMarketTime": regular_time,
            "preMarketPrice": 101.25,
            "preMarketTime": premarket_time,
            "marketState": "PRE",
            "exchange": "NMS",
            "currency": "USD",
            "quoteType": "EQUITY",
        }
    )
    quote = service.fetch("aapl")
    assert quote.symbol == "AAPL"
    assert quote.bid == 99.0
    assert quote.ask == 100.0
    assert quote.last_price == 98.5
    assert quote.source_timestamp == dt.datetime.fromtimestamp(regular_time, tz=dt.timezone.utc)
    assert quote.mark_price == 101.25
    assert quote.mark_timestamp == dt.datetime.fromtimestamp(premarket_time, tz=dt.timezone.utc)
    assert quote.mark_session == "PRE"

    missing = YahooPaperQuoteService(
        fetch_info=lambda _symbol: {
            "regularMarketPrice": 98.5,
            "regularMarketTime": regular_time,
            "marketState": "PRE",
            "exchange": "NMS",
            "currency": "USD",
            "quoteType": "EQUITY",
        }
    ).fetch("AAPL")
    assert missing.mark_price is None
    assert missing.mark_timestamp is None
    assert missing.mark_session == ""


def test_virtual_opt_in_marks_premarket_without_filling_orders() -> None:
    premarket_now = dt.datetime(2026, 7, 15, 11, 0, tzinfo=dt.timezone.utc)

    class CountingQuotes:
        def __init__(self, quote: PaperQuote) -> None:
            self.quote = quote
            self.calls: list[str] = []

        def fetch(self, symbol: str) -> PaperQuote:
            self.calls.append(symbol)
            return self.quote

    with tempfile.TemporaryDirectory() as directory:
        store, regular_engine = _engine(Path(directory) / "paper.db")
        account = store.create_account("Pre-market", 10_000)
        market_order = regular_engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 10, "market", "day"),
            quote=_quote(),
        )
        regular_engine.process_pending_orders(quotes={"AAPL": _quote()})
        assert store.get_order(market_order["id"])["status"] == "filled"
        pending = regular_engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "limit", "gtc", limit_price=50),
            quote=_quote(),
        )

        quotes = CountingQuotes(
            _quote(
                market_state="PRE",
                timestamp=NOW,
                mark_price=105.0,
                mark_timestamp=premarket_now,
                mark_session="PRE",
            )
        )
        def premarket_session(_now: dt.datetime) -> MarketSession:
            return MarketSession(False, None, NOW, is_premarket=True)

        engine = PaperTradingEngine(
            store,
            quote_service=quotes,
            now=lambda: premarket_now,
            session_resolver=premarket_session,
            allow_premarket_marks=True,
        )
        result = engine.run_cycle(mark=True)
        position = store.list_positions(account["id"])[0]
        assert quotes.calls == ["AAPL"]
        assert result["market_phase"] == "premarket"
        assert result["marks"]["updated"] == 1
        assert float(position["mark_price"]) == 105.0
        assert position["mark_source"] == "Yahoo Finance (pre-market)"
        assert position["mark_is_stale"] == 0
        assert store.get_order(pending["id"])["status"] == "pending"
        assert "regular US market session" in store.get_order(pending["id"])["last_evaluation"]
        assert abs(float(store.account_summary(account["id"])["equity"]) - 10_049.5) < 1e-9

        quotes.quote = _quote(
            market_state="PRE",
            timestamp=NOW,
            mark_price=110.0,
            mark_timestamp=premarket_now - dt.timedelta(minutes=21),
            mark_session="PRE",
        )
        stale_result = engine.run_cycle(mark=True)
        stale_position = store.list_positions(account["id"])[0]
        assert stale_result["marks"]["updated"] == 0
        assert stale_result["marks"]["errors"]
        assert float(stale_position["mark_price"]) == 105.0
        assert stale_position["mark_is_stale"] == 1

        default_quotes = CountingQuotes(quotes.quote)
        default_engine = PaperTradingEngine(
            store,
            quote_service=default_quotes,
            now=lambda: premarket_now,
            session_resolver=premarket_session,
        )
        default_result = default_engine.run_cycle(mark=True)
        assert default_result["market_phase"] == "premarket"
        assert default_result["marks"]["updated"] == 0
        assert default_quotes.calls == []

        closed_quotes = CountingQuotes(quotes.quote)
        closed_engine = PaperTradingEngine(
            store,
            quote_service=closed_quotes,
            now=lambda: premarket_now,
            session_resolver=lambda _now: MarketSession(False, None, NOW),
            allow_premarket_marks=True,
        )
        closed_result = closed_engine.run_cycle(mark=True)
        assert closed_result["market_phase"] == "closed"
        assert closed_result["marks"]["updated"] == 0
        assert closed_quotes.calls == []


def test_market_session_detects_trading_day_premarket_only() -> None:
    premarket = PaperTradingEngine._resolve_us_session(dt.datetime(2026, 7, 15, 11, 0, tzinfo=dt.timezone.utc))
    regular = PaperTradingEngine._resolve_us_session(dt.datetime(2026, 7, 15, 14, 0, tzinfo=dt.timezone.utc))
    postmarket = PaperTradingEngine._resolve_us_session(dt.datetime(2026, 7, 15, 22, 0, tzinfo=dt.timezone.utc))
    weekend = PaperTradingEngine._resolve_us_session(dt.datetime(2026, 7, 18, 11, 0, tzinfo=dt.timezone.utc))
    assert premarket.is_premarket is True and premarket.is_open is False
    assert regular.is_open is True and regular.is_premarket is False
    assert postmarket.is_open is False and postmarket.is_premarket is False
    assert weekend.is_open is False and weekend.is_premarket is False


def test_extended_day_limit_executes_in_premarket_from_fresh_bid_ask() -> None:
    premarket_now = dt.datetime(2026, 7, 15, 11, 0, tzinfo=dt.timezone.utc)
    close = dt.datetime(2026, 7, 15, 20, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Extended Hours", 10_000)
        quote = _quote(
            bid=99.0,
            ask=100.0,
            market_state="PRE",
            timestamp=NOW,
            mark_price=101.5,
            mark_timestamp=premarket_now,
            mark_session="PRE",
        )
        engine = PaperTradingEngine(
            store,
            now=lambda: premarket_now,
            session_resolver=lambda _now: MarketSession(False, None, close, is_premarket=True),
            allow_premarket_marks=True,
        )
        order = engine.submit_order(
            PaperOrderRequest(
                account["id"],
                "AAPL",
                "buy",
                2,
                "limit",
                "day",
                limit_price=100.0,
                execution_session="extended",
            ),
            quote=quote,
        )
        result = engine.process_pending_orders(quotes={"AAPL": quote})
        assert result["filled"] == 1
        stored = store.get_order(order["id"])
        assert stored["execution_session"] == "extended"
        assert stored["expires_at"] == close.isoformat()
        fill = store.list_fills(account["id"])[0]
        assert float(fill["reference_price"]) == 100.0
        assert float(fill["fill_price"]) <= 100.0
        assert float(fill["fill_price"]) != 101.5
        assert fill["quote_source"] == "Yahoo Finance (pre-market bid/ask)"
        assert fill["quote_timestamp"] == premarket_now.isoformat()

        try:
            PaperOrderRequest(
                account["id"], "MSFT", "buy", 1, "market", "day", execution_session="extended"
            ).normalized()
        except ValueError as exc:
            assert "limit orders only" in str(exc)
        else:
            raise AssertionError("pre-market market orders must be rejected")

        try:
            PaperOrderRequest(
                account["id"],
                "MSFT",
                "buy",
                1,
                "limit",
                "gtc",
                limit_price=100,
                execution_session="extended",
            ).normalized()
        except ValueError as exc:
            assert "DAY" in str(exc)
        else:
            raise AssertionError("pre-market GTC orders must be rejected")


def test_virtual_instant_fill_ignores_spread_session_and_order_conditions() -> None:
    def closed_session(_now: dt.datetime) -> MarketSession:
        return MarketSession(False, None, NOW + dt.timedelta(days=1))

    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "instant.db")
        account = store.create_account("Instant Virtual", 100_000, slippage_bps=0)
        engine = PaperTradingEngine(
            store,
            now=lambda: NOW,
            session_resolver=closed_session,
            instant_fill=True,
        )
        no_spread = _quote(bid=None, ask=None)

        market = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 2, "market", "day"),
            quote=no_spread,
        )
        market_result = engine.process_pending_orders(quotes={"AAPL": no_spread})
        assert market_result["filled"] == 1
        market_fill = store.list_fills(account["id"])[0]
        assert market_fill["order_id"] == market["id"]
        assert float(market_fill["fill_price"]) == 99.5
        assert market_fill["quote_source"] == "Yahoo Finance (virtual last price)"

        limit = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "limit", "day", limit_price=25),
            quote=no_spread,
        )
        limit_result = engine.process_pending_orders(quotes={"AAPL": no_spread})
        assert limit_result["filled"] == 1
        limit_fill = store.list_fills(account["id"])[0]
        assert limit_fill["order_id"] == limit["id"]
        assert float(limit_fill["fill_price"]) == 25.0
        assert limit_fill["quote_source"] == "Virtual limit price"

        stop = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "stop", "day", stop_price=250),
            quote=no_spread,
        )
        stop_result = engine.process_pending_orders(quotes={"AAPL": no_spread})
        assert stop_result["filled"] == 1
        stop_fill = store.list_fills(account["id"])[0]
        assert stop_fill["order_id"] == stop["id"]
        assert float(stop_fill["fill_price"]) == 250.0
        assert stop_fill["quote_source"] == "Virtual stop price"

        pre_quote = _quote(
            "MSFT",
            bid=None,
            ask=None,
            market_state="PRE",
            mark_price=123.45,
            mark_timestamp=NOW,
            mark_session="PRE",
        )
        premarket = engine.submit_order(
            PaperOrderRequest(account["id"], "MSFT", "buy", 1, "market", "day"),
            quote=pre_quote,
        )
        premarket_result = engine.process_pending_orders(quotes={"MSFT": pre_quote})
        assert premarket_result["filled"] == 1
        premarket_fill = store.list_fills(account["id"])[0]
        assert premarket_fill["order_id"] == premarket["id"]
        assert float(premarket_fill["fill_price"]) == 123.45
        assert premarket_fill["quote_source"] == "Yahoo Finance (virtual PRE mark)"

        paper_store = PaperTradingStore(Path(directory) / "paper-realistic.db")
        paper_account = paper_store.create_account("Realistic Paper", 10_000)
        paper_engine = PaperTradingEngine(
            paper_store,
            now=lambda: NOW,
            session_resolver=_open_session,
        )
        pending = paper_engine.submit_order(
            PaperOrderRequest(paper_account["id"], "AAPL", "buy", 1, "market", "day"),
            quote=no_spread,
        )
        assert paper_engine.process_pending_orders(quotes={"AAPL": no_spread})["filled"] == 0
        assert paper_store.get_order(pending["id"])["status"] == "pending"


def test_us_etf_orders_fill_and_unsupported_funds_remain_blocked() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store, engine = _engine(Path(directory) / "paper.db")
        account = store.create_account("ETF Account", 100_000)
        spy_quote = _quote("SPY", bid=499.8, ask=500.0, exchange="PCX", quote_type="ETF")
        order = engine.submit_order(
            PaperOrderRequest(account["id"], "SPY", "buy", 10, "market", "day"),
            quote=spy_quote,
        )
        result = engine.process_pending_orders(quotes={"SPY": spy_quote})
        assert result["filled"] == 1
        assert store.get_order(order["id"])["status"] == "filled"
        position = store.list_positions(account["id"])[0]
        assert position["symbol"] == "SPY"
        assert position["quantity"] == 10

        spym_quote = _quote("SPYM", bid=87.1, ask=87.2, exchange="PCX", quote_type="EQUITY")
        spym_order = engine.submit_order(
            PaperOrderRequest(account["id"], "SPYM", "buy", 1, "market", "day"),
            quote=spym_quote,
        )
        assert engine.process_pending_orders(quotes={"SPYM": spym_quote})["filled"] == 1
        assert store.get_order(spym_order["id"])["status"] == "filled"

        qqq_quote = _quote("QQQ", bid=599.8, ask=600.0, exchange="NGM", quote_type="ETF")
        qqq_order = engine.submit_order(
            PaperOrderRequest(account["id"], "QQQ", "buy", 2, "limit", "gtc", limit_price=600),
            quote=qqq_quote,
        )
        assert store.get_order(qqq_order["id"])["status"] == "pending"

        try:
            engine.submit_order(
                PaperOrderRequest(account["id"], "VTSAX", "buy", 1, "market", "day"),
                quote=_quote("VTSAX", exchange="NMS", quote_type="MUTUALFUND"),
            )
        except ValueError as exc:
            assert "stocks and ETFs" in str(exc)
        else:
            raise AssertionError("mutual funds should remain unsupported")

        try:
            engine.submit_order(
                PaperOrderRequest(account["id"], "OTCETF", "buy", 1, "market", "day"),
                quote=_quote("OTCETF", exchange="PNK", quote_type="ETF"),
            )
        except ValueError as exc:
            assert "NYSE Arca" in str(exc)
            assert "type=ETF" in str(exc)
            assert "exchange=PNK" in str(exc)
        else:
            raise AssertionError("OTC ETFs should remain unsupported")


if __name__ == "__main__":
    test_market_limit_stop_and_average_cost()
    test_fractional_manual_orders_reservations_positions_and_pnl()
    test_exact_cash_balance_adjustments_and_atomic_validation()
    test_reserved_cash_floor_and_v2_cash_event_migration()
    test_reservations_rejections_stale_quotes_and_idempotency()
    test_day_expiry_archive_and_account_isolation()
    test_backup_import_and_reset_round_trip()
    test_cycle_deduplicates_order_and_position_symbols()
    test_yahoo_quote_extracts_premarket_mark_without_replacing_execution_fields()
    test_virtual_opt_in_marks_premarket_without_filling_orders()
    test_market_session_detects_trading_day_premarket_only()
    test_extended_day_limit_executes_in_premarket_from_fresh_bid_ask()
    test_virtual_instant_fill_ignores_spread_session_and_order_conditions()
    test_us_etf_orders_fill_and_unsupported_funds_remain_blocked()
    print("paper trading engine and persistence smoke passed")
