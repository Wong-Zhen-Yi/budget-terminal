from __future__ import annotations

import os
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.dependencies import pd
from budget_terminal_app.etf_holdings import EtfHolding, EtfHoldingsResult, EtfHoldingsService
from budget_terminal_app.persistence import (
    _normalize_up_down_page_settings,
    load_up_down_page_settings,
    save_up_down_page_settings,
)
from budget_terminal_app.services.up_down import (
    UP_DOWN_PAYLOAD_CACHE_NAMESPACE,
    UpDownDataService,
    calculate_up_down_row,
    normalize_up_down_symbols,
    sort_up_down_rows,
)
from budget_terminal_app.mixins.up_down_page import P27_NUMERIC_ROLE


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_up_down_calculation_and_sorting() -> None:
    index = pd.date_range("2026-01-02", periods=6, freq="D")
    close = pd.Series([100, 101, 100, 100, 102, 101], index=index)

    one_day = calculate_up_down_row("AAA", close, "1d", name="Alpha")
    _assert(one_day is not None, "1D row should be calculated")
    _assert(one_day["days_up"] == 0, "latest down day should not count as up")
    _assert(one_day["days_down"] == 1, "latest down day should count as down")
    _assert(one_day["trading_days"] == 1, "1D should include one return observation")

    five_day = calculate_up_down_row("AAA", close, "5d", name="Alpha")
    _assert(five_day is not None, "5D row should be calculated")
    _assert(five_day["days_up"] == 2, "5D should count two up days")
    _assert(five_day["days_down"] == 2, "5D should count two down days")
    _assert(five_day["flat_days"] == 1, "flat days should be neither up nor down")
    _assert(five_day["trading_days"] == 5, "5D should include five return observations when available")

    ytd = calculate_up_down_row("AAA", close, "ytd", name="Alpha")
    one_year = calculate_up_down_row("AAA", close, "1y", name="Alpha")
    _assert(ytd is not None and ytd["trading_days"] == 5, "YTD should use current-year observations")
    _assert(one_year is not None and one_year["trading_days"] == 5, "1Y should use one-year observations")

    rows = sort_up_down_rows([
        {"ticker": "BBB", "days_up": 3, "days_down": 2},
        {"ticker": "AAA", "days_up": 3, "days_down": 1},
        {"ticker": "CCC", "days_up": 2, "days_down": 0},
    ])
    _assert([row["ticker"] for row in rows] == ["AAA", "BBB", "CCC"], "default sort should rank up days, then down days, then ticker")
    _assert(normalize_up_down_symbols("aaa, BBB\ncash aaa") == ["AAA", "BBB"], "custom symbols should normalize and de-dupe")


class _FakeTargetService(UpDownDataService):
    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        super().__init__(cache_manager=cache_manager)
        self.calls: list[str] = []

    def _load_price_target(self, symbol: str) -> float | None:
        self.calls.append(symbol)
        return {"PTA": 125.5, "PTB": None}.get(symbol)


def test_price_target_batches_and_cache() -> None:
    symbols = ["PTA", "PTB"]
    with tempfile.TemporaryDirectory() as temp_dir:
        cache = CacheManager(Path(temp_dir) / "up-down-cache.db")
        service = _FakeTargetService(cache)
        first = {}
        for batch in service.iter_price_target_batches(symbols):
            first.update(batch)
        _assert(first == {"PTA": 125.5, "PTB": None}, "target batches should preserve valid and unavailable results")
        _assert(sorted(service.calls) == symbols, "uncached targets should be fetched once")

        restarted_service = _FakeTargetService(cache)
        second = {}
        for batch in restarted_service.iter_price_target_batches(symbols):
            second.update(batch)
        _assert(second == first, "persisted target batches should survive a service restart")
        _assert(not restarted_service.calls, "fresh persisted targets should not be fetched again")
        forced = {}
        for batch in restarted_service.iter_price_target_batches(symbols, force_refresh=True):
            forced.update(batch)
        _assert(forced == first, "forced target refresh should preserve the result shape")
        _assert(sorted(restarted_service.calls) == symbols, "forced target refresh should bypass persisted values")


def test_persistent_payload_freshness_and_separation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cache = CacheManager(Path(temp_dir) / "up-down-cache.db")
        service = UpDownDataService(cache)
        payload = {"rows": [{"ticker": "AAA", "price_target_mean": 120.0}], "missing": []}
        service.save_cached_payload("qqq", "5d", payload)
        fresh = service.load_cached_payload("qqq", "5d")
        _assert(fresh is not None and fresh[0] == payload and fresh[1]["fresh"], "new payloads should load as fresh")
        _assert(service.load_cached_payload("spy", "5d") is None, "SPY and QQQ disk payloads should remain separate")
        _assert(service.load_cached_payload("qqq", "30d") is None, "interval disk payloads should remain separate")
        service.save_cached_holdings("QQQ", ["AAA", "BBB"], {"AAA": "Alpha", "BBB": "Beta"})
        cached_holdings = service.load_cached_holdings("QQQ", fresh_only=True)
        _assert(cached_holdings is not None and cached_holdings[0]["symbols"] == ["AAA", "BBB"], "QQQ holdings should persist")
        _assert(service.load_cached_holdings("SPY", fresh_only=True) is None, "SPY and QQQ holdings should remain separate")

        stale_time = (dt.datetime.now() - dt.timedelta(minutes=20)).isoformat()
        with cache._connect() as conn:
            conn.execute(
                "UPDATE json_payload_cache SET last_updated=? WHERE namespace=? AND cache_key=?",
                (stale_time, UP_DOWN_PAYLOAD_CACHE_NAMESPACE, "qqq:5d"),
            )
        stale = service.load_cached_payload("qqq", "5d")
        _assert(stale is not None and not stale[1]["fresh"], "recent stale payloads should remain usable")

        expired_time = (dt.datetime.now() - dt.timedelta(days=8)).isoformat()
        with cache._connect() as conn:
            conn.execute(
                "UPDATE json_payload_cache SET last_updated=? WHERE namespace=? AND cache_key=?",
                (expired_time, UP_DOWN_PAYLOAD_CACHE_NAMESPACE, "qqq:5d"),
            )
        _assert(service.load_cached_payload("qqq", "5d") is None, "payloads older than the stale fallback window should expire")


class _InlineExecutor:
    def submit(self, fn: Any) -> None:
        fn()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _QueuedExecutor:
    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def submit(self, fn: Any) -> None:
        self.tasks.append(fn)

    def run_all(self) -> None:
        while self.tasks:
            self.tasks.pop(0)()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        self.tasks.clear()


class _FakeUpDownService(UpDownDataService):
    def __init__(self) -> None:
        super().__init__(cache_manager=None)
        self.fetch_calls: list[tuple[list[str], str, dict[str, str]]] = []
        self.target_force_calls: list[bool] = []

    def fetch(self, symbols: list[str], interval_key: Any, *, names: dict[str, str] | None = None) -> dict[str, Any]:
        self.fetch_calls.append((list(symbols), str(interval_key), dict(names or {})))
        rows = []
        for index, symbol in enumerate(symbols):
            rows.append({
                "ticker": symbol,
                "name": (names or {}).get(symbol, f"{symbol} Inc"),
                "last_close": 100.0 + index,
                "interval_return": 1.0 - index,
                "trading_days": 5,
                "days_up": 5 - index,
                "days_down": index,
            })
        return {"rows": sort_up_down_rows(rows), "missing": [], "as_of": "2026-06-26 09:00", "source": "test"}

    def iter_price_target_batches(self, symbols: list[str], *, cancel_check=None, force_refresh: bool = False):
        self.target_force_calls.append(bool(force_refresh))
        if cancel_check is not None and cancel_check():
            return
        targets = {"AAA": 120.0, "BBB": 90.0}
        yield {symbol: targets.get(symbol) for symbol in symbols}


class _CachedFakeUpDownService(_FakeUpDownService):
    def __init__(self, *, fresh: bool, fail_fetch: bool = False) -> None:
        super().__init__()
        self.fresh = fresh
        self.fail_fetch = fail_fetch
        self.cached_payload = {
            "rows": [{
                "ticker": "AAA",
                "name": "Cached Alpha",
                "last_close": 100.0,
                "interval_return": 1.0,
                "trading_days": 5,
                "days_up": 4,
                "days_down": 1,
                "price_target_mean": 120.0,
            }],
            "missing": [],
            "symbols": ["AAA"],
        }

    def load_cached_payload(self, source_key: Any, interval_key: Any):
        if str(source_key) == "qqq" and str(interval_key) == "5d":
            return dict(self.cached_payload), {"fresh": self.fresh, "cache_age_seconds": 60.0 if self.fresh else 1200.0}
        return None

    def load_cached_holdings(self, etf_symbol: Any, *, fresh_only: bool):
        return {"symbols": ["AAA"], "names": {"AAA": "Fresh Alpha"}}, {"fresh": True, "cache_age_seconds": 0.0}

    def fetch(self, symbols: list[str], interval_key: Any, *, names: dict[str, str] | None = None) -> dict[str, Any]:
        if self.fail_fetch:
            raise RuntimeError("simulated refresh failure")
        return super().fetch(symbols, interval_key, names=names)


def _build_window(*, state: dict[str, Any] | None = None, service: UpDownDataService | None = None):
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window.up_down_page_state = state or {"active_source": "custom", "interval_key": "5d", "custom_symbols": []}
        window._up_down_data_service = service or _FakeUpDownService()
        window._ensure_page_initialized(26)
        window._p27_executor = _InlineExecutor()
        window._p27_target_executor = _InlineExecutor()
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_cache_first_visible_lifecycle() -> None:
    app = None
    window = None
    try:
        fresh_service = _CachedFakeUpDownService(fresh=True)
        app, window = _build_window(
            state={"active_source": "qqq", "interval_key": "5d", "custom_symbols": []},
            service=fresh_service,
        )
        _assert(not fresh_service.fetch_calls, "hidden startup initialization should not fetch QQQ data")
        window.switch_page(26)
        for _ in range(10):
            app.processEvents()
        _assert(not fresh_service.fetch_calls, "fresh cached QQQ data should avoid live network work")
        _assert(window._p27_tables["qqq"].item(0, 2).text() == "Cached Alpha", "fresh cached rows should render on first show")
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()

    app = None
    window = None
    try:
        stale_service = _CachedFakeUpDownService(fresh=False, fail_fetch=True)
        app, window = _build_window(
            state={"active_source": "qqq", "interval_key": "5d", "custom_symbols": []},
            service=stale_service,
        )
        queued = _QueuedExecutor()
        window._p27_executor = queued
        window.switch_page(26)
        for _ in range(10):
            app.processEvents()
        _assert(len(queued.tasks) == 1, "stale QQQ cache should schedule one visible background refresh")
        _assert(not window._p27_request_refresh(force=False), "an identical in-flight refresh should be coalesced")
        _assert(len(queued.tasks) == 1, "coalescing should not queue duplicate background work")
        _assert(window._p27_tables["qqq"].item(0, 2).text() == "Cached Alpha", "stale rows should render before refresh completes")
        queued.run_all()
        app.processEvents()
        _assert(window._p27_tables["qqq"].item(0, 2).text() == "Cached Alpha", "failed refresh should retain stale rows")
        _assert("Cached data retained" in window.p27_status_label.text(), "failed refresh should report retained cached data")
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_up_down_page_smoke() -> None:
    original_state = load_up_down_page_settings()
    app = None
    window = None
    try:
        saved_qqq = save_up_down_page_settings({"active_source": "qqq", "interval_key": "30d", "custom_symbols": []})
        _assert(saved_qqq["active_source"] == "qqq", "QQQ should survive settings normalization")
        _assert(load_up_down_page_settings()["active_source"] == "qqq", "QQQ should survive settings persistence")
        invalid = _normalize_up_down_page_settings({"active_source": "invalid"})
        _assert(invalid["active_source"] == "portfolio", "invalid saved sources should still fall back to Portfolio")

        app, window = _build_window()
        _assert(window._PAGE_LABELS[26] == "Up/Down", "page label should be registered")
        _assert(window.btn_page27.text() == "Up/Down", "nav button should be registered")
        _assert(window.p27_tabs.count() == 4, "Up/Down should have four source tabs")
        _assert(
            [window.p27_tabs.tabText(i) for i in range(4)] == ["Portfolio", "SPY Holdings", "QQQ Holdings", "Custom"],
            "source tabs should match the plan",
        )
        window._refresh_main_tab_picker_items()
        picker_labels = [entry["label"] for entry in getattr(window, "_tab_picker_entries", [])]
        _assert("Up/Down > QQQ Holdings" in picker_labels, "QQQ Holdings should be registered in the picker")
        _assert("Up/Down > Custom" in picker_labels, "Up/Down subtabs should be registered in the picker")
        qqq_picker_match = window._find_tab_picker_match("QQQ Up/Down")
        _assert(qqq_picker_match["tab_text"] == "QQQ Holdings", "QQQ Up/Down alias should resolve to QQQ Holdings")
        custom_table = window._p27_tables["custom"]
        headers = [custom_table.horizontalHeaderItem(i).text() for i in range(custom_table.columnCount())]
        _assert(headers[-3:] == ["Days Up", "Days Down", "Price Targets"], "Price Targets should follow Days Down")
        _assert(window.p27_interval_key == "5d", "saved interval should initialize")
        _assert(window._p27_interval_buttons["5d"].isChecked(), "saved interval button should be checked")
        spy_cache_key = window._p27_cache_key("spy", "5d")
        qqq_cache_key = window._p27_cache_key("qqq", "5d")
        _assert(spy_cache_key != qqq_cache_key, "SPY and QQQ should use distinct cache keys")
        _assert(spy_cache_key[-1] == ("SPY_HOLDINGS",), "SPY should retain its holdings cache identity")
        _assert(qqq_cache_key[-1] == ("QQQ_HOLDINGS",), "QQQ should have its own holdings cache identity")

        original_holdings_load = EtfHoldingsService.load
        try:
            def _fake_holdings_load(_service, ticker: str, *, enrich: bool = True) -> EtfHoldingsResult:
                _assert(ticker == "QQQ", "QQQ source should request official QQQ holdings")
                _assert(not enrich, "Up/Down holdings should skip unnecessary fund metadata enrichment")
                return EtfHoldingsResult(
                    ticker="QQQ",
                    issuer="Invesco",
                    holdings=[
                        EtfHolding(symbol="AAA", name="Alpha Corp", weight=0.6),
                        EtfHolding(symbol="BBB", name="Beta Corp", weight=0.4),
                        EtfHolding(symbol="CASH", name="Cash", weight=0.01),
                        EtfHolding(symbol="123", name="Invalid", weight=0.01),
                    ],
                )

            EtfHoldingsService.load = _fake_holdings_load
            _assert(window._p27_request_refresh(force=True, source="qqq"), "QQQ refresh should be scheduled")
        finally:
            EtfHoldingsService.load = original_holdings_load
        qqq_call = window._up_down_data_service.fetch_calls[-1]
        _assert(qqq_call == (["AAA", "BBB"], "5d", {"AAA": "Alpha Corp", "BBB": "Beta Corp"}), "QQQ symbols and company names should flow into the Up/Down service")
        _assert(window._up_down_data_service.target_force_calls[-1], "forced Refresh should bypass the analyst-target cache")
        qqq_payload = window._p27_payload_cache.get(qqq_cache_key, {})
        _assert([row["name"] for row in qqq_payload.get("rows", [])] == ["Alpha Corp", "Beta Corp"], "QQQ company names should survive the payload stage")
        qqq_table = window._p27_tables["qqq"]
        qqq_headers = [qqq_table.horizontalHeaderItem(i).text() for i in range(qqq_table.columnCount())]
        _assert(qqq_headers[-1] == "Price Targets", "QQQ should retain the Price Targets column")

        window.p27_custom_input.setPlainText("aaa, bbb\ncash aaa")
        window._p27_apply_custom_symbols(save=True)
        app.processEvents()
        _assert(window.p27_custom_symbols == ["AAA", "BBB"], "custom symbols should normalize on save")
        saved = load_up_down_page_settings()
        _assert(saved["custom_symbols"] == ["AAA", "BBB"], "custom symbols should persist")
        _assert(custom_table.rowCount() == 0, "hidden Up/Down completion should defer table rendering")
        window.switch_page(26)
        for _ in range(10):
            app.processEvents()
        _assert(custom_table.rowCount() == 2, "custom tab should render fake service rows")
        _assert(custom_table.item(0, 1).text() == "AAA", "highest days-up ticker should render first")
        target_by_ticker = {
            custom_table.item(row, 1).text(): custom_table.item(row, 8).text()
            for row in range(custom_table.rowCount())
        }
        _assert(target_by_ticker["AAA"] == "$120 (+20%)", "positive target upside should render in the combined cell")
        _assert(target_by_ticker["BBB"] == "$90 (-10.9%)", "negative target downside should render in the combined cell")
        _assert(window._p27_price_target_display(100.0, None) == ("N/A", None), "missing targets should render as N/A")
        target_sort_by_ticker = {
            custom_table.item(row, 1).text(): custom_table.item(row, 8).data(P27_NUMERIC_ROLE)
            for row in range(custom_table.rowCount())
        }
        _assert(abs(float(target_sort_by_ticker["AAA"]) - 20.0) < 0.0001, "target cells should sort by upside percentage")
        _assert(float(target_sort_by_ticker["BBB"]) < 0, "downside target cells should carry a negative sort value")
        stale_request = window._p27_active_request - 1
        window._p27_apply_target_batch(stale_request, "custom", "5d", {"AAA": 999.0})
        current_target = next(
            custom_table.item(row, 8).text()
            for row in range(custom_table.rowCount())
            if custom_table.item(row, 1).text() == "AAA"
        )
        _assert(current_target == "$120 (+20%)", "stale target callbacks should not overwrite the current request")
    finally:
        save_up_down_page_settings(original_state)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


if __name__ == "__main__":
    test_up_down_calculation_and_sorting()
    test_price_target_batches_and_cache()
    test_persistent_payload_freshness_and_separation()
    test_cache_first_visible_lifecycle()
    test_up_down_page_smoke()
    print("Up/Down page smoke passed.")
    sys.stdout.flush()
    os._exit(0)
