from __future__ import annotations

import datetime
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import QTimer, pd
from budget_terminal_app.persistence import (
    DEFAULT_NAVIGATION_PAGE_ORDER,
    load_charts_options_top_volume_page_settings,
    normalize_navigation_settings,
    save_charts_options_top_volume_page_settings,
)
from budget_terminal_app.services.options_data import OPTIONS_MARKET_TIMEZONE


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _InlineExecutor:
    def submit(self, fn: Any) -> None:
        fn()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _DeferredExecutor:
    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def submit(self, fn: Any) -> None:
        self.tasks.append(fn)

    def run_next(self) -> None:
        if not self.tasks:
            raise AssertionError('expected a queued Projections request')
        self.tasks.pop(0)()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeChartService:
    def __init__(self, cache_manager: Any) -> None:
        self.cache_manager = cache_manager

    def fetch_base_frame_payload(self, symbol: Any, *, period: Any, interval: Any, force_refresh: bool = False) -> dict[str, Any]:
        index = pd.date_range("2026-06-01", periods=6, freq="D")
        return {"df": pd.DataFrame({
            "Open": [100.0, 101.0, 102.0, 101.0, 104.0, 105.0],
            "High": [102.0, 103.0, 103.0, 105.0, 106.0, 108.0],
            "Low": [99.0, 100.0, 100.0, 101.0, 103.0, 104.0],
            "Close": [101.0, 102.0, 101.0, 104.0, 105.0, 107.0],
            "Volume": [1000, 1200, 900, 1600, 1800, 2200],
        }, index=index)}


class _FakeEmptyChartService:
    def __init__(self, cache_manager: Any) -> None:
        self.cache_manager = cache_manager

    def fetch_base_frame_payload(self, symbol: Any, *, period: Any, interval: Any, force_refresh: bool = False) -> dict[str, Any]:
        return {"df": pd.DataFrame()}


_FAKE_OPTIONS_TODAY = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()


class _FakeOptionsService:
    EXPIRIES = tuple((_FAKE_OPTIONS_TODAY + datetime.timedelta(days=days)).isoformat() for days in (30, 75))

    def __init__(self, cache_manager: Any) -> None:
        self.cache_manager = cache_manager
        self.chain_calls: list[tuple[str, str]] = []

    def fetch_expiries_payload(self, ticker: Any) -> dict[str, Any]:
        return {"expiries": list(self.EXPIRIES)}

    def fetch_chain_payload(self, ticker: Any, expiry: Any) -> dict[str, Any]:
        expiry_text = str(expiry)
        self.chain_calls.append((str(ticker), expiry_text))
        if expiry_text == self.EXPIRIES[1]:
            rows = [
                {"type": "Call", "strike": 100.0, "lastPrice": 9.0, "volume": 2000, "openInterest": 500},
                {"type": "Put", "strike": 95.0, "lastPrice": 1.1, "volume": 500, "openInterest": 600},
                {"type": "Call", "strike": 105.0, "lastPrice": 5.0, "volume": 100, "openInterest": 700},
            ]
        else:
            rows = [
                {"type": "Call", "strike": 100.0, "lastPrice": 8.5, "volume": 1000, "openInterest": 400},
                {"type": "Put", "strike": 95.0, "lastPrice": 1.3, "volume": 750, "openInterest": 600},
                {"type": "Call", "strike": 105.0, "lastPrice": 3.0, "volume": 250, "openInterest": 900},
            ]
        rows.extend(
            {"type": "Call", "strike": strike, "lastPrice": 0.1, "volume": 1, "openInterest": 1}
            for strike in range(150, 158)
        )
        rows.extend([
            {"type": "Call", "strike": None, "lastPrice": 0.1, "volume": 50, "openInterest": 1},
            {"type": "Put", "strike": 50.0, "lastPrice": 0.1, "volume": 0, "openInterest": 1},
        ])
        for row in rows:
            row.update({"ticker": ticker, "expiration": expiry_text})
            last = float(row.get("lastPrice") or 0.0)
            if last > 0:
                row["bid"] = max(last - 0.05, 0.01)
                row["ask"] = last + 0.05
                row["impliedVolatility"] = 0.35
        return {"chain": pd.DataFrame(rows)}


def _build_window(chart_service_cls: Any = _FakeChartService, options_service_cls: Any = _FakeOptionsService):
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window._ensure_page_initialized(27)
        cache_manager = window._get_cache_manager()
        window._chart_data_service = chart_service_cls(cache_manager)
        window._options_data_service = options_service_cls(cache_manager)
        window._p28_fetch_executor = _InlineExecutor()
        window._p28_initial_load_requested = True
        window.switch_page(27)
        app.processEvents()
        window._p28_initial_load_requested = False
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
    return app, window


def _drain_projection_render(app: Any, window: Any, timeout: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout
    handle = None
    while time.monotonic() < deadline:
        app.processEvents()
        handles = getattr(window, '_budget_terminal_batched_render_handles', {})
        handle = handles.get('projections-option-sections') if isinstance(handles, dict) else None
        if handle is None or handle.finished:
            return handle
        time.sleep(0.001)
    raise AssertionError('timed out waiting for Projections option sections')


def _marker_layers(window: Any, kind: str) -> list[Any]:
    return [item for item in getattr(window, "_p28_projection_marker_items", []) if getattr(item, "_p28_marker_kind", "") == kind]


def _point_count(layer: Any) -> int:
    return int(getattr(layer, "_p28_point_count", 0))


def test_navigation_normalization() -> None:
    state = normalize_navigation_settings({"page_order": [0, 9, 13], "hidden_pages": []})
    _assert(27 in DEFAULT_NAVIGATION_PAGE_ORDER, "Projections should remain in default navigation")
    _assert(state["page_order"].index(27) == state["page_order"].index(9) + 1, "Projections should follow Charts")


def test_projection_state_migration() -> None:
    original = load_charts_options_top_volume_page_settings()
    try:
        saved = save_charts_options_top_volume_page_settings({
            "symbol": "spy", "timeframe_label": "1 Day", "type_filter": "both",
            "expiration_scope": "year", "show_dots": False, "splitter_sizes": [5, 3],
        })
        _assert(saved["type_filter"] == "calls", "legacy both should migrate to calls")
        _assert(saved["expiration_scope"] == "all", "legacy projection scopes should migrate to all")
        _assert("show_dots" not in saved, "obsolete dots state should no longer be written")
    finally:
        save_charts_options_top_volume_page_settings(original)


def test_projection_first_show_loads_last_ticker_once() -> None:
    original = load_charts_options_top_volume_page_settings()
    app = window = None
    try:
        save_charts_options_top_volume_page_settings({
            "symbol": "AAA", "timeframe_label": "1 Day", "type_filter": "calls",
            "expiration_scope": "all", "splitter_sizes": [5, 3],
        })
        app, window = _build_window()
        _assert(window.p28_symbol_input.text() == "AAA", "saved ticker should populate the Projections input")
        _assert(not window._options_data_service.chain_calls, "lazy page initialization should not fetch projections")

        window._p28_on_show()
        app.processEvents()
        initial_chain_calls = len(window._options_data_service.chain_calls)
        _assert(window._p28_payload["ticker"] == "AAA", "first show should load the saved ticker")
        _assert(initial_chain_calls == len(_FakeOptionsService.EXPIRIES), "first show should fetch each saved-ticker expiration once")

        window._p28_on_show()
        app.processEvents()
        _assert(len(window._options_data_service.chain_calls) == initial_chain_calls, "later page visits should not repeat the automatic load")

        window.p28_symbol_input.setText("BBB")
        window._p28_load(force_refresh=True)
        app.processEvents()
        _assert(window._p28_payload["ticker"] == "BBB", "manual loading should still replace the completed view")
        _assert(load_charts_options_top_volume_page_settings()["symbol"] == "BBB", "a successful manual load should persist the new ticker")
    finally:
        save_charts_options_top_volume_page_settings(original)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_projections_page_smoke() -> None:
    original = load_charts_options_top_volume_page_settings()
    app = window = None
    try:
        save_charts_options_top_volume_page_settings({
            "symbol": "AAA", "timeframe_label": "1 Day", "type_filter": "calls",
            "expiration_scope": "all", "splitter_sizes": [5, 3],
        })
        app, window = _build_window()
        _assert(set(window._p28_type_buttons) == {"calls", "puts"}, "table filter should expose calls and puts only")
        _assert(window.p28_projection_range_label.text() == "Projection range: All expirations", "projection range should be fixed to all")
        _assert(not hasattr(window, "p28_show_dots_btn"), "obsolete dots control should be removed")
        window._p28_load(force_refresh=True)
        app.processEvents()

        projections = window._p28_payload["projections"]
        weekly = window._p28_payload["weekly_points"]
        _assert(set(projections) == {"calls", "puts", "combined"}, "payload should expose call, put, and combined anchors")
        _assert(len(projections["calls"]) == 2 and len(projections["puts"]) == 2, "both sides should cover all expirations")
        _assert(len(projections["combined"]) == 2, "combined projection should cover expirations with both sides")
        first_call = projections["calls"][_FakeOptionsService.EXPIRIES[0]]
        first_put = projections["puts"][_FakeOptionsService.EXPIRIES[0]]
        _assert(first_call["projected_price"] >= 107.0, "call break-even scenario should not project below spot")
        _assert(first_put["projected_price"] <= 107.0, "put break-even scenario should not project above spot")
        _assert(first_call["confidence_label"] in {"Low", "Moderate", "High"}, "anchor should expose confidence")
        _assert(len(weekly["calls"]) > 2 and len(weekly["puts"]) > 2, "weekly paths should interpolate between anchors")
        _assert(len(weekly["combined"]) > 2, "combined weekly path should interpolate between combined anchors")
        call_dates = [datetime.date.fromisoformat(point["date"]) for point in weekly["calls"]]
        _assert(_FakeOptionsService.EXPIRIES[0] in {point["date"] for point in weekly["calls"]}, "exact expiration should be a path point")
        _assert(any((right - left).days == 7 for left, right in zip(call_dates, call_dates[1:])), "path should contain seven-day points")

        _assert(len(_marker_layers(window, "calls_projection_points")) == 1, "call weekly dots should render")
        _assert(len(_marker_layers(window, "puts_projection_points")) == 1, "put weekly dots should render")
        _assert(len(_marker_layers(window, "combined_projection_points")) == 1, "combined weekly dots should render")
        _assert(not _marker_layers(window, "proxy_bubbles"), "individual option bubbles should never render")
        _assert({getattr(item, "_p28_path_kind", "") for item in window._p28_projection_path_items} == {"calls", "puts", "combined"}, "three solid projection paths should render")
        _assert(_point_count(_marker_layers(window, "calls_projection_points")[0]) == len(weekly["calls"]) - 1, "every future call point should get a dot")
        marker_tip = _marker_layers(window, "calls_projection_points")[0].opts["tip"](x=1.0, y=2.0, data=weekly["calls"][1])
        _assert("Calls projection" in marker_tip and "Projected price:" in marker_tip, "scatter should use the projection tooltip")
        _assert("x:" not in marker_tip and "y:" not in marker_tip and "data=" not in marker_tip, "scatter must not expose pyqtgraph's fallback x/y/data tooltip")
        tooltip = window._p28_projection_point_tooltip(weekly["calls"][1])
        _assert("Date:" in tooltip and "Projected price:" in tooltip and "Anchors:" in tooltip, "hover text should include weekly date, price, and anchors")
        window._p28_show_projection_point_tooltip(None, np.array([], dtype=object), None)

        call_path_before = [dict(point) for point in weekly["calls"]]
        chain_calls = len(window._options_data_service.chain_calls)
        window._p28_set_type_filter("puts")
        app.processEvents()
        table = window._p28_sections[_FakeOptionsService.EXPIRIES[0]]["table"]
        _assert(all(table.item(row, 1).text() == "Put" for row in range(table.rowCount())), "puts filter should affect table rows")
        _assert(len(window._options_data_service.chain_calls) == chain_calls, "table filter should reuse loaded chains")
        _assert(window._p28_payload["weekly_points"]["calls"] == call_path_before, "table filter must not change call projection")

        export = window._p28_build_export()
        _assert("Nearest Call Projection" in export and "Nearest Put Projection" in export and "Nearest Combined Projection" in export, "export should include all three projections")
        _assert("Projection Period: All" in export and "Table Rows: Puts" in export, "export should state fixed range and table filter")
        _assert("not true forecasts" in export and "| Side | Expiration | Projection |" in export, "export should preserve caveat and separated schema")
    finally:
        save_charts_options_top_volume_page_settings(original)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_all_expirations_are_kept() -> None:
    app = window = None
    try:
        app, window = _build_window()
        today = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()
        expiries = [(today + datetime.timedelta(days=days)).isoformat() for days in (30, 365, 366, 800)]
        window._p28_set_expiration_scope("year")
        config = window._p28_build_bucket_config(expiries)
        _assert([item[0] for item in config] == expiries, "legacy scope requests must not filter valid expirations")
        _assert(window.p28_expiration_scope == "all", "scope should remain all")
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_projection_math_and_quality() -> None:
    app = window = None
    try:
        app, window = _build_window()
        records = [
            {"type": "Call", "strike": 105.0, "bid": 1.9, "ask": 2.1, "volume": 400, "openInterest": 300, "impliedVolatility": 0.30},
            {"type": "Call", "strike": 180.0, "bid": 0.1, "ask": 5.0, "volume": 5000, "openInterest": 100000, "impliedVolatility": 0.90},
            {"type": "Put", "strike": 95.0, "bid": 1.9, "ask": 2.1, "volume": 350, "openInterest": 250, "impliedVolatility": 0.32},
        ]
        calls = window._p28_projection_side_summary(records, side="calls", bucket_key="x", expiry="2026-08-21", days_out=45, current_close=100.0)
        puts = window._p28_projection_side_summary(records, side="puts", bucket_key="x", expiry="2026-08-21", days_out=45, current_close=100.0)
        _assert(calls is not None and abs(calls["projected_price"] - 107.0) < 0.001, "call anchor should use midpoint break-even and reject wide quote")
        _assert(puts is not None and abs(puts["projected_price"] - 93.0) < 0.001, "put anchor should use midpoint break-even")
        combined = window._p28_combined_projection_summary(calls, puts)
        _assert(combined is not None and puts["projected_price"] < combined["projected_price"] < calls["projected_price"], "combined anchor should lie between call and put scenarios")
        _assert(calls["wide_spread_count"] == 1, "wide-spread contract should be counted but excluded")

        missing_iv = window._p28_projection_side_summary(
            [{"type": "Call", "strike": 105.0, "bid": 1.9, "ask": 2.1, "volume": 400, "openInterest": 300}],
            side="calls", bucket_key="x", expiry="2026-08-21", days_out=45, current_close=100.0,
        )
        _assert(missing_iv is not None and missing_iv["iv_coverage"] == 0.0, "missing IV should remain usable with reduced coverage")
        _assert(missing_iv["confidence_score"] < calls["confidence_score"], "missing IV should lower confidence")
        invalid = window._p28_projection_side_summary(
            [{"type": "Call", "strike": 105.0, "bid": 0.0, "ask": 2.0, "volume": 400, "openInterest": 300}],
            side="calls", bucket_key="x", expiry="2026-08-21", days_out=45, current_close=100.0,
        )
        _assert(invalid is None, "zero or unusable quotes should be rejected")
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_projection_without_chart_close() -> None:
    app = window = None
    try:
        app, window = _build_window(chart_service_cls=_FakeEmptyChartService)
        window._p28_load(force_refresh=True)
        app.processEvents()
        _assert(window._p28_payload["projections"] == {"calls": {}, "puts": {}, "combined": {}}, "no close should produce no anchors")
        _assert(window._p28_payload["weekly_points"] == {"calls": [], "puts": [], "combined": []}, "no close should produce no weekly points")
        _assert(not window._p28_projection_marker_items and not window._p28_projection_path_items, "no overlay should render without chart data")
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_projection_refresh_keeps_completed_view() -> None:
    original = load_charts_options_top_volume_page_settings()
    app = window = None
    try:
        save_charts_options_top_volume_page_settings({
            "symbol": "AAA", "timeframe_label": "1 Day", "type_filter": "calls",
            "expiration_scope": "all", "splitter_sizes": [5, 3],
        })
        app, window = _build_window()
        executor = _DeferredExecutor()
        window._p28_fetch_executor = executor

        window._p28_load(force_refresh=True)
        _assert(len(executor.tasks) == 1, "initial load should queue a request")
        executor.run_next()
        app.processEvents()
        _assert(window._p28_payload["ticker"] == "AAA", "initial request should render the first completed view")
        old_markers = list(window._p28_projection_marker_items)
        old_paths = list(window._p28_projection_path_items)
        _assert(old_markers and old_paths, "initial request should render projection overlays")

        window.p28_symbol_input.setText("BBB")
        window._p28_load(force_refresh=True)
        _assert(window._p28_payload["ticker"] == "AAA", "pending refresh must retain the prior payload")
        _assert(window._p28_projection_marker_items == old_markers, "pending refresh must retain all projection dots")
        _assert(window._p28_projection_path_items == old_paths, "pending refresh must retain all projection paths")
        _assert("showing previous result" in window.p28_status_label.text(), "pending refresh should explain that prior results remain visible")

        window.p28_symbol_input.setText("CCC")
        window._p28_load(force_refresh=True)
        executor.run_next()
        app.processEvents()
        _assert(window._p28_payload["ticker"] == "AAA", "stale response must not replace the retained view")
        _assert(window._p28_projection_marker_items == old_markers, "stale response must not alter projection dots")

        executor.run_next()
        app.processEvents()
        _assert(window._p28_payload["ticker"] == "CCC", "latest completed request should replace the retained view")
        _assert(window.p28_symbol_label.text() == "CCC", "latest completed request should update the chart header")
        _assert(window._p28_projection_marker_items != old_markers, "successful replacement should redraw projection dots")
        _assert({getattr(item, "_p28_path_kind", "") for item in window._p28_projection_path_items} == {"calls", "puts", "combined"}, "replacement should retain all three paths")

        completed_markers = list(window._p28_projection_marker_items)
        completed_paths = list(window._p28_projection_path_items)
        cache_manager = window._get_cache_manager()
        window._chart_data_service = _FakeEmptyChartService(cache_manager)
        window.p28_symbol_input.setText("DDD")
        window._p28_load(force_refresh=True)
        executor.run_next()
        app.processEvents()
        _assert(window._p28_payload["ticker"] == "CCC", "failed refresh must retain the last completed payload")
        _assert(window._p28_projection_marker_items == completed_markers, "failed refresh must retain projection dots")
        _assert(window._p28_projection_path_items == completed_paths, "failed refresh must retain projection paths")
        _assert("Refresh failed for DDD; showing previous result" in window.p28_status_label.text(), "failed refresh should explain that prior results remain visible")
    finally:
        save_charts_options_top_volume_page_settings(original)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_hidden_completion_applies_once_without_refetch() -> None:
    original = load_charts_options_top_volume_page_settings()
    app = window = None
    try:
        save_charts_options_top_volume_page_settings({
            "symbol": "AAA", "timeframe_label": "1 Day", "type_filter": "calls",
            "expiration_scope": "all", "splitter_sizes": [5, 3],
        })
        app, window = _build_window()
        apply_calls: list[str] = []
        original_apply = window._p28_apply_completed_view

        def _tracked_apply(**payload: Any) -> None:
            apply_calls.append(str(payload.get('ticker') or ''))
            original_apply(**payload)

        window._p28_apply_completed_view = _tracked_apply
        window.switch_page(0)
        app.processEvents()
        window.p28_symbol_input.setText('HID')
        window._p28_load(force_refresh=True)
        app.processEvents()

        _assert(isinstance(window._p28_pending_completed_view, dict), 'hidden completion should cache the latest payload')
        _assert(window._p28_pending_completed_view['ticker'] == 'HID', 'hidden cache should retain the completed ticker')
        _assert(window._p28_payload.get('ticker') != 'HID', 'hidden completion must not rebuild the visible payload')
        _assert(apply_calls == [], 'hidden completion must not apply chart or option panels')
        chain_calls = len(window._options_data_service.chain_calls)

        window.switch_page(27)
        deadline = time.monotonic() + 3.0
        while not apply_calls and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        _drain_projection_render(app, window)
        _assert(apply_calls == ['HID'], 'returning to Projections should apply the cached result exactly once')
        _assert(window._p28_payload['ticker'] == 'HID', 'cached result should become the visible payload')
        _assert(window._p28_pending_completed_view is None, 'cached result should be consumed after rendering')
        _assert(len(window._options_data_service.chain_calls) == chain_calls, 'showing cached Projections must not refetch options')

        window.switch_page(0)
        app.processEvents()
        window.switch_page(27)
        app.processEvents()
        _assert(apply_calls == ['HID'], 'later page visits must not reapply an already-consumed completion')
    finally:
        save_charts_options_top_volume_page_settings(original)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


def test_expiration_sections_render_in_responsive_batches() -> None:
    from budget_terminal_app.mixins import charts_options_top_volume as projections_module

    app = window = None
    heartbeat = None
    original_render_rows = projections_module.render_table_rows
    try:
        app, window = _build_window()
        window._p28_load(force_refresh=True)
        app.processEvents()
        _drain_projection_render(app, window)
        loaded_records = window._p28_payload.get('records', {})
        sample_rows = list(next((rows for rows in loaded_records.values() if rows), []))
        _assert(bool(sample_rows), 'worst-case batching fixture requires at least one prepared option row')

        today = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()
        expiries = tuple((today + datetime.timedelta(days=14 + index * 7)).isoformat() for index in range(30))
        config = tuple((expiry, expiry, (datetime.date.fromisoformat(expiry) - today).days) for expiry in expiries)
        records = {expiry: [dict(row) for row in sample_rows] for expiry in expiries}
        expiration_map = {expiry: expiry for expiry in expiries}
        window._p28_set_bucket_config(config)
        window._p28_render_option_tables('AAA', records, expiration_map)
        first_handle = getattr(window, '_budget_terminal_batched_render_handles', {}).get('projections-option-sections')
        _assert(first_handle is not None and first_handle.processed_count == 0, 'section rendering should begin on a later event-loop turn')
        _drain_projection_render(app, window)

        first_table = window._p28_sections[expiries[0]]['table']
        _assert(first_table.rowCount() > 0, 'fixture should populate the first expiration table')
        first_table.setCurrentCell(0, 0)
        first_table.selectRow(0)
        selection_key = window._p28_table_selection_key(first_table)
        selected_filter = window.p28_type_filter
        window._p28_set_status('Batch status sentinel', 'warning')

        def _slow_render_rows(table: Any, rows: Any) -> None:
            started = time.perf_counter()
            while time.perf_counter() - started < 0.001:
                pass
            original_render_rows(table, rows)

        projections_module.render_table_rows = _slow_render_rows
        heartbeat_times: list[float] = []
        heartbeat = QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))
        heartbeat.start()

        window._p28_render_option_tables('AAA', records, expiration_map)
        handle = getattr(window, '_budget_terminal_batched_render_handles', {}).get('projections-option-sections')
        _assert(handle is not None and handle.processed_count == 0, 'worst-case sections must not render synchronously')
        _drain_projection_render(app, window)
        heartbeat.stop()

        _assert(handle.completed and handle.processed_count == len(expiries), 'every expiration section should complete')
        _assert(handle.batch_count >= math.ceil(len(expiries) / 4), 'section renderer should enforce the four-item slice bound')
        _assert(len(heartbeat_times) >= 2, 'event-loop heartbeat should run during section rendering')
        gaps = [right - left for left, right in zip(heartbeat_times, heartbeat_times[1:])]
        _assert(not gaps or max(gaps) <= 0.2, 'expiration rendering should not stall the event loop for 200 ms')
        _assert(window.p28_status_label.text() == 'Batch status sentinel', 'batched table work should preserve page status')
        _assert(window.p28_type_filter == selected_filter, 'batched table work should preserve the selected filter')
        _assert(window._p28_table_selection_key(first_table) == selection_key, 'batched rebuild should restore table selection')
        _assert(all(window._p28_sections[expiry]['table'].rowCount() > 0 for expiry in expiries), 'all expiration tables should render')
    finally:
        projections_module.render_table_rows = original_render_rows
        if heartbeat is not None:
            heartbeat.stop()
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


if __name__ == "__main__":
    test_navigation_normalization()
    test_projection_state_migration()
    test_projection_first_show_loads_last_ticker_once()
    test_projections_page_smoke()
    test_all_expirations_are_kept()
    test_projection_math_and_quality()
    test_projection_without_chart_close()
    test_projection_refresh_keeps_completed_view()
    test_hidden_completion_applies_once_without_refetch()
    test_expiration_sections_render_in_responsive_batches()
    print("Projections page smoke passed.")
    sys.stdout.flush()
    os._exit(0)
