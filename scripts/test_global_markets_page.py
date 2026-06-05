from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

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
)
from budget_terminal_app.widgets.global_market_map import GlobalMarketMapWidget


def _series(values: list[float], dates: list[str]) -> Any:
    return pd.Series(values, index=pd.DatetimeIndex(pd.to_datetime(dates)))


def _index_config(short_name: str) -> Any:
    for config in GLOBAL_MARKET_INDEXES:
        if config.short_name == short_name:
            return config
    raise AssertionError(f"Missing global index config: {short_name}")


def _payload() -> dict[str, Any]:
    rows = [
        build_global_market_row(_index_config("S&P 500"), _series([100, 104, 110, 121], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"])),
        build_global_market_row(_index_config("CSI 300"), _series([3000, 3030, 3090, 3120], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"])),
        build_global_market_row(_index_config("Nifty"), _series([4000, 3960, 4040, 4080], ["2024-12-31", "2025-01-02", "2025-01-08", "2025-01-10"])),
        build_global_market_row(_index_config("TSX"), pd.Series(dtype=float)),
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
        window._global_markets_data_service = _FakeGlobalService()
        window._p26_executor = _InlineExecutor()
        window._p26_request_refresh(force=True)
        app.processEvents()
        assert window.p26_table.rowCount() == 4
        countries = [window.p26_table.item(row, 1).text() for row in range(window.p26_table.rowCount())]
        assert countries.count("China") == 1
        assert countries.count("India") == 1
        window._p26_set_interval("5D")
        assert window.p26_interval_label == "5D"
        export = window._p26_build_llm_export()
        assert "# Global Market Index Export" in export
        for label in GLOBAL_INTERVALS:
            assert f"### {label}" in export
        assert "S&P 500" in export
        assert "CSI 300" in export
        assert "Nifty" in export
        assert "SSEC" not in export
        assert "Sensex" not in export
        assert "^GSPTSE" in export
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    tests = [
        test_interval_calculation,
        test_nearest_prior_interval,
        test_missing_data_row,
        test_global_map_labels_do_not_overlap,
        test_global_page_smoke,
    ]
    for test in tests:
        test()
    print(f"global markets page tests passed ({len(tests)})")
    sys.stdout.flush()
    os._exit(0)
