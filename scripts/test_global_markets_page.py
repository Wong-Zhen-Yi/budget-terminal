from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.persistence import _normalize_global_page_settings
from budget_terminal_app.services.global_markets import (
    GLOBAL_INTERVALS,
    GLOBAL_MARKET_INDEXES,
    build_global_market_row,
    calculate_interval_performance,
    format_global_market_timing,
)
from budget_terminal_app.widgets.global_market_map import GlobalMarketMapWidget
from budget_terminal_app.mixins.global_page import P26_COL_MARKET, P26_COL_SESSION, P26_COL_SYMBOL, P26_TABLE_COLUMNS


def _series(values: list[float], dates: list[str]) -> Any:
    return pd.Series(values, index=pd.DatetimeIndex(pd.to_datetime(dates)))


def _epoch(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc).timestamp())


def _timing(start_hour: int | None, end_hour: int | None, *, last_tick_hour: int | None = None, exchange_timezone: str = "America/New_York") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "^TEST",
        "exchange_timezone": exchange_timezone,
        "regular_market_time": _epoch(2025, 1, 10, last_tick_hour, 0) if last_tick_hour is not None else None,
        "last_tick_time": _epoch(2025, 1, 10, last_tick_hour, 0) if last_tick_hour is not None else None,
    }
    if start_hour is not None:
        payload["regular_start"] = _epoch(2025, 1, 10, start_hour, 0)
    if end_hour is not None:
        payload["regular_end"] = _epoch(2025, 1, 10, end_hour, 0)
    return payload


def _index_config(short_name: str) -> Any:
    for config in GLOBAL_MARKET_INDEXES:
        if config.short_name == short_name:
            return config
    raise AssertionError(f"Missing global index config: {short_name}")


def _payload() -> dict[str, Any]:
    rows = [
        build_global_market_row(_index_config("S&P 500"), _series([100, 104, 110, 121], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"]), _timing(14, 21, last_tick_hour=15)),
        build_global_market_row(_index_config("CSI 300"), _series([3000, 3030, 3090, 3120], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"]), _timing(16, 20, last_tick_hour=13, exchange_timezone="Asia/Shanghai")),
        build_global_market_row(_index_config("Nifty"), _series([4000, 3960, 4040, 4080], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"]), _timing(8, 10, last_tick_hour=10, exchange_timezone="Asia/Kolkata")),
        build_global_market_row(_index_config("TSX"), pd.Series(dtype=float), _timing(None, None, last_tick_hour=13, exchange_timezone="America/Toronto")),
    ]
    return {
        "generated_at": "2025-01-10T16:00:00",
        "source": "unit-test",
        "intervals": list(GLOBAL_INTERVALS),
        "rows": rows,
        "missing": ["^GSPTSE"],
    }


class _InlineExecutor:
    def submit(self, fn: Any) -> None:
        fn()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeGlobalService:
    def fetch(self) -> dict[str, Any]:
        return _payload()


def test_interval_calculation() -> None:
    result = calculate_interval_performance(
        _series([100, 104, 110, 121], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"]),
        "YTD",
    )
    assert result["available"] is True
    assert result["start_date"] == "2025-01-02"
    assert round(float(result["change_pct"]), 4) == 16.3462


def test_nearest_prior_interval() -> None:
    result = calculate_interval_performance(
        _series([100, 110, 121], ["2025-01-01", "2025-01-08", "2025-01-10"]),
        "5D",
    )
    assert result["available"] is True
    assert result["start_date"] == "2025-01-01"
    assert round(float(result["change_pct"]), 4) == 21.0


def test_missing_data_row() -> None:
    row = build_global_market_row(_index_config("TSX"), pd.Series(dtype=float))
    assert row["last_close"] is None
    assert row["intervals"]["1D"]["available"] is False


def test_market_timing_formatter() -> None:
    timing = {
        "regular_start": _epoch(2025, 1, 10, 14, 30),
        "regular_end": _epoch(2025, 1, 10, 21, 0),
        "last_tick_time": _epoch(2025, 1, 10, 15, 45),
        "exchange_timezone": "America/New_York",
    }
    singapore = ZoneInfo("Asia/Singapore")
    opened = format_global_market_timing(
        timing,
        singapore,
        now=datetime.datetime(2025, 1, 10, 15, 0, tzinfo=datetime.timezone.utc),
    )
    assert opened["state"] == "open"
    assert opened["market"] == "Open"
    assert opened["session"] == "Open until Jan 11, 05:00"

    pre_open = format_global_market_timing(
        timing,
        singapore,
        now=datetime.datetime(2025, 1, 10, 13, 0, tzinfo=datetime.timezone.utc),
    )
    assert pre_open["state"] == "closed"
    assert pre_open["session"] == "Closed, opens 22:30"

    post_close = format_global_market_timing(
        timing,
        singapore,
        now=datetime.datetime(2025, 1, 10, 22, 0, tzinfo=datetime.timezone.utc),
    )
    assert post_close["state"] == "closed"
    assert post_close["session"] == "Closed since 05:00"

    unknown = format_global_market_timing(
        {"last_tick_time": _epoch(2025, 1, 10, 15, 45), "exchange_timezone": "America/New_York"},
        ZoneInfo("UTC"),
        now=datetime.datetime(2025, 1, 10, 16, 0, tzinfo=datetime.timezone.utc),
    )
    assert unknown["state"] == "unknown"
    assert unknown["market"] == "Unknown"
    assert unknown["session"] == "Unknown, last tick 15:45"


def _global_map_rows() -> list[dict[str, Any]]:
    close_series = _series([100, 103, 107, 109], ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    return [build_global_market_row(config, close_series) for config in GLOBAL_MARKET_INDEXES]


def _assert_global_map_labels_clear(width: int, height: int) -> None:
    from budget_terminal_app.main import QApplication

    app = QApplication.instance() or QApplication([])
    widget = GlobalMarketMapWidget()
    widget.resize(width, height)
    widget.set_data(_global_map_rows(), "1D")
    app.processEvents()
    map_rect = widget._map_rect()
    layout = widget._layout_labels(map_rect)
    rects = [item["rect"] for item in layout]
    assert len(rects) == len(GLOBAL_MARKET_INDEXES)
    assert widget._world_features
    assert any(item["country"] == "USA" and item["label"] == "S&P 500" for item in layout)
    for rect in rects:
        assert rect.left() >= map_rect.left()
        assert rect.right() <= map_rect.right()
        assert rect.top() >= map_rect.top()
        assert rect.bottom() <= map_rect.bottom()
    for index, rect in enumerate(rects):
        for other in rects[index + 1:]:
            assert not rect.intersects(other)
    for item in layout:
        rect = item["rect"].adjusted(-1, -1, 1, 1)
        for other in layout:
            if other is item:
                continue
            assert not rect.intersects(widget._pin_hit_rect(other["point"])), (
                f"{item['country']} {item['label']} label covers {other['country']} {other['label']} pin"
            )
    france = next(item for item in layout if item["country"] == "France" and item["label"] == "CAC")
    spain = next(item for item in layout if item["country"] == "Spain" and item["label"] == "IBEX")
    assert not france["rect"].adjusted(-1, -1, 1, 1).intersects(widget._pin_hit_rect(spain["point"]))
    visible_labels = [(item["country"], item["label"], item["leader_segment"], item["rect"]) for item in layout if item.get("leader_visible", True)]
    minimum_visible_leaders = 6 if width <= 720 else len(GLOBAL_MARKET_INDEXES) // 2
    assert len(visible_labels) >= minimum_visible_leaders
    labels = visible_labels
    for index, (country, label, segment, rect) in enumerate(labels):
        for other_country, other_label, other_segment, other_rect in labels[index + 1:]:
            assert not widget._segments_intersect(segment[0], segment[1], other_segment[0], other_segment[1]), (
                f"leader lines overlap: {country} {label} -> {other_country} {other_label}"
            )
            assert not widget._segment_intersects_rect(segment, other_rect.adjusted(-2, -2, 2, 2)), (
                f"leader line crosses label: {country} {label} -> {other_country} {other_label}"
            )
            assert not widget._segment_intersects_rect(other_segment, rect.adjusted(-2, -2, 2, 2)), (
                f"leader line crosses label: {other_country} {other_label} -> {country} {label}"
            )
    widget.close()
    app.processEvents()


def test_global_map_labels_do_not_overlap() -> None:
    _assert_global_map_labels_clear(720, 360)
    _assert_global_map_labels_clear(960, 360)
    _assert_global_map_labels_clear(1366, 440)
    _assert_global_map_labels_clear(1860, 550)


def _build_window():
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
        window.global_page_state = _normalize_global_page_settings({"interval_label": "YTD"})
        window._ensure_page_initialized(25)
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_global_page_smoke() -> None:
    app, window = _build_window()
    try:
        assert window._PAGE_LABELS[25] == "Global"
        assert window.btn_page26.text() == "Global"
        assert window.p26_interval_label == "YTD"
        window._clock_country_code = "SG"
        window._time_12h = False
        window._p26_market_status_now_override = datetime.datetime(2025, 1, 10, 15, 0, tzinfo=datetime.timezone.utc)
        window._global_markets_data_service = _FakeGlobalService()
        window._p26_executor = _InlineExecutor()
        window._p26_request_refresh(force=True)
        app.processEvents()
        assert window.p26_table.rowCount() == 4
        assert window.p26_table.columnCount() == len(P26_TABLE_COLUMNS)
        headers = [window.p26_table.horizontalHeaderItem(column).text() for column in range(window.p26_table.columnCount())]
        assert headers[P26_COL_MARKET] == "Market"
        assert headers[P26_COL_SESSION] == "Session (Clock TZ)"
        countries = [window.p26_table.item(row, 1).text() for row in range(window.p26_table.rowCount())]
        assert countries.count("China") == 1
        assert countries.count("India") == 1
        sp_row = _table_row_for_symbol(window, "^GSPC")
        assert window.p26_table.item(sp_row, P26_COL_MARKET).text() == "Open"
        assert window.p26_table.item(sp_row, P26_COL_SESSION).text() == "Open until Jan 11, 05:00"
        tsx_row = _table_row_for_symbol(window, "^GSPTSE")
        assert window.p26_table.item(tsx_row, P26_COL_MARKET).text() == "Unknown"
        assert window.p26_table.item(tsx_row, P26_COL_SESSION).text() == "Unknown, last tick 21:00"
        window._p26_set_interval("5D")
        assert window.p26_interval_label == "5D"
        export = window._p26_build_llm_export()
        assert "# Global Market Index Export" in export
        assert "Market status is inferred from yfinance timing metadata" in export
        assert "| S&P 500 | ^GSPC | Open | Open until Jan 11, 05:00 |" in export
        assert "Session (Clock TZ)" in export
        for label in GLOBAL_INTERVALS:
            assert f"### {label}" in export
        assert "S&P 500" in export
        assert "CSI 300" in export
        assert "Nifty" in export
        assert "SSEC" not in export
        assert "Sensex" not in export
        assert "^GSPTSE" in export
        rows_with_status = window._p26_rows_with_market_status()
        window.p26_map.set_data(rows_with_status, "1D")
        layout = window.p26_map._layout_labels(window.p26_map._map_rect())
        sp_label = next(item for item in layout if item["country"] == "USA" and item["label"] == "S&P 500")
        assert sp_label["show_status"] is True
        assert sp_label["status_text"].startswith("Open | 1D")
        assert "Open until Jan 11, 05:00" in window.p26_map._tooltip(sp_label["row"])
        window._p26_refresh_market_status_display(
            force=True,
            now=datetime.datetime(2025, 1, 10, 22, 0, tzinfo=datetime.timezone.utc),
        )
        sp_row = _table_row_for_symbol(window, "^GSPC")
        assert window.p26_table.item(sp_row, P26_COL_MARKET).text() == "Closed"
        assert window.p26_table.item(sp_row, P26_COL_SESSION).text() == "Closed since 05:00"
    finally:
        window.close()
        app.processEvents()


def _table_row_for_symbol(window: Any, symbol: str) -> int:
    for row in range(window.p26_table.rowCount()):
        item = window.p26_table.item(row, P26_COL_SYMBOL)
        if item is not None and item.text().upper().strip() == symbol.upper().strip():
            return row
    raise AssertionError(f"Missing table row for {symbol}")


if __name__ == "__main__":
    tests = [
        test_interval_calculation,
        test_nearest_prior_interval,
        test_missing_data_row,
        test_market_timing_formatter,
        test_global_map_labels_do_not_overlap,
        test_global_page_smoke,
    ]
    for test in tests:
        test()
    print(f"global markets page tests passed ({len(tests)})")
    sys.stdout.flush()
    os._exit(0)
