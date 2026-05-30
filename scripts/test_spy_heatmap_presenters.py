from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.spy_heatmap_presenters import (
    build_heatmap_detail,
    build_heatmap_summary,
    build_spy_heatmap_rows,
    format_heatmap_pct,
    format_heatmap_weight_pct,
    select_heatmap_row,
    weighted_change_from_heatmap_rows,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _holding(
    symbol: str,
    *,
    name: str = "",
    sector: str = "",
    weight: float | None = 0.01,
    price: float | None = 100.0,
    change_pct: float | None = None,
    changes: dict[str, float] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        name=name,
        sector=sector,
        weight=weight,
        price=price,
        change_pct=change_pct,
        changes=changes or {},
    )


def test_empty_result_rows_summary_and_detail() -> None:
    result = SimpleNamespace(holdings=[], holdings_loaded=0, quote_coverage=0, interval_summaries={})
    rows = build_spy_heatmap_rows(
        result,
        etf_symbol="SPY",
        etf_label="SPY",
        interval_key="live",
        interval_label="Live",
    )
    _assert(rows == [], "empty heatmap result should produce no widget rows")
    summary = build_heatmap_summary(result, "live")
    _assert(summary.holdings_loaded == 0, "empty summary should preserve zero holdings")
    _assert(summary.quote_coverage == 0, "empty summary should preserve zero quote coverage")
    _assert(summary.weighted_move is None, "empty summary should not invent weighted move")
    _assert(summary.strongest.text == "--", "empty strongest should use placeholder")
    _assert(summary.weakest.text == "--", "empty weakest should use placeholder")
    detail = build_heatmap_detail(None, "Live")
    _assert(detail.symbol == "Select a holding", "empty detail should prompt selection")
    _assert(detail.change_text == "Change: --", "empty detail should preserve change placeholder")


def test_live_fallback_and_row_contract() -> None:
    result = SimpleNamespace(
        holdings=[
            _holding(
                " aapl ",
                name="Apple Inc.",
                sector="",
                weight=0.065,
                price=212.345,
                change_pct=1.234,
                changes={},
            )
        ]
    )
    rows = build_spy_heatmap_rows(
        result,
        etf_symbol="SPY",
        etf_label="SPY",
        interval_key="live",
        interval_label="Live",
    )
    row = rows[0]
    _assert(row["symbol"] == "AAPL", "symbol should be uppercased and trimmed")
    _assert(row["name"] == "Apple Inc.", "name should pass through")
    _assert(row["sector"] == "Unclassified", "empty sector should use Unclassified")
    _assert(row["weight"] == 0.065, "weight should pass through")
    _assert(row["price"] == 212.345, "price should pass through")
    _assert(row["change_pct"] == 1.234, "live interval should fall back to holding change_pct")
    _assert(row["changes"] == {}, "changes map should pass through")
    _assert(row["interval_key"] == "live", "interval key should be preserved")
    _assert(row["interval_label"] == "Live", "interval label should be preserved")
    _assert(row["change_label"] == "Live Change", "change label should match existing text")
    _assert(row["etf"] == "SPY", "ETF key should be preserved")
    _assert(row["etf_label"] == "SPY", "ETF label should be preserved")


def test_non_live_interval_change_and_summary() -> None:
    strong = _holding("MSFT", change_pct=0.5, changes={"1w": 4.25})
    weak = _holding("TSLA", change_pct=-0.5, changes={"1w": -3.5})
    result = SimpleNamespace(
        holdings=[strong, weak],
        holdings_loaded=2,
        quote_coverage=1,
        weighted_day_move=0.0,
        strongest=None,
        weakest=None,
        interval_summaries={
            "1w": SimpleNamespace(
                quote_coverage=2,
                weighted_move=1.5,
                strongest=strong,
                weakest=weak,
            )
        },
    )
    rows = build_spy_heatmap_rows(
        result,
        etf_symbol="NDX",
        etf_label="QQQ",
        interval_key="1w",
        interval_label="1W",
    )
    _assert(rows[0]["change_pct"] == 4.25, "non-live interval should use holding changes map")
    _assert(rows[0]["change_label"] == "1W Change", "non-live change label should use interval label")
    summary = build_heatmap_summary(result, "1w")
    _assert(summary.holdings_loaded == 2, "summary should preserve holdings count")
    _assert(summary.quote_coverage == 2, "summary should prefer interval quote coverage")
    _assert(summary.weighted_move == 1.5, "summary should prefer interval weighted move")
    _assert(summary.strongest.text == "MSFT +4.25%", "strongest should format symbol and signed change")
    _assert(summary.strongest.change_pct == 4.25, "strongest should expose numeric change")
    _assert(summary.weakest.text == "TSLA -3.50%", "weakest should format negative change")


def test_formatting_detail_selection_and_weighted_change() -> None:
    _assert(format_heatmap_pct(1.234, signed=True) == "+1.23%", "signed positive percent should include plus")
    _assert(format_heatmap_pct(-1.234, signed=True) == "-1.23%", "signed negative percent should include minus")
    _assert(format_heatmap_pct(None, signed=True) == "--", "missing percent should use placeholder")
    _assert(format_heatmap_weight_pct(0.01234) == "1.23%", "weight should render as percent")

    rows = [
        {"symbol": "AAA", "etf": "SPY", "weight": 0.25, "change_pct": 2.0},
        {"symbol": "BBB", "etf": "SPY", "weight": 0.75, "change_pct": -1.0},
    ]
    _assert(weighted_change_from_heatmap_rows(rows) == -0.25, "weighted change should use row weights")
    _assert(select_heatmap_row(rows, {"symbol": "BBB", "etf": "SPY"}, "SPY") == rows[1], "selection should preserve same ETF and symbol")
    _assert(select_heatmap_row(rows, {"symbol": "BBB", "etf": "DIA"}, "SPY") == rows[0], "different ETF selection should fall back to first row")
    _assert(select_heatmap_row([], {"symbol": "BBB", "etf": "SPY"}, "SPY") is None, "empty rows should select nothing")

    detail = build_heatmap_detail(
        {
            "symbol": "AAA",
            "name": "AAA Corp",
            "sector": "Technology",
            "weight": 0.1234,
            "price": 42.5,
            "change_pct": 2.25,
            "change_label": "1M Change",
        },
        "Live",
    )
    _assert(detail.symbol == "AAA", "detail symbol should pass through")
    _assert(detail.name == "AAA Corp", "detail name should pass through")
    _assert(detail.sector == "Sector: Technology", "detail sector should preserve prefix")
    _assert(detail.weight == "Weight: 12.34%", "detail weight should preserve prefix and percent")
    _assert(detail.price == "Price: $42.50", "detail price should preserve currency")
    _assert(detail.change_text == "1M Change: +2.25%", "detail change text should preserve label and sign")
    _assert(detail.change_pct == 2.25, "detail should expose numeric change for color styling")


def test_offscreen_widget_row_smoke() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from budget_terminal_app.widgets.etf_heatmap import EtfHeatmapWidget

    app = QApplication.instance() or QApplication([])
    widget = EtfHeatmapWidget()
    widget.resize(360, 260)
    rows = [
        {
            "symbol": "AAA",
            "name": "AAA Corp",
            "sector": "Technology",
            "weight": 0.6,
            "price": 100.0,
            "change_pct": 1.0,
            "interval_label": "Live",
            "change_label": "Live Change",
        },
        {
            "symbol": "",
            "name": "No Symbol",
            "sector": "Cash",
            "weight": 0.4,
            "price": 1.0,
            "change_pct": 0.0,
        },
        {
            "symbol": "BBB",
            "name": "BBB Corp",
            "sector": "Healthcare",
            "weight": 0.0,
            "price": 20.0,
            "change_pct": -1.0,
        },
    ]
    widget.set_data(rows, reset_view=True)
    app.processEvents()
    pixmap = widget.grab()
    _assert(not pixmap.isNull(), "offscreen heatmap grab should produce a pixmap")
    _assert(widget.selected_symbol() == "", "setting data should not create a selection")
    _assert(len(getattr(widget, "_rows", [])) == 1, "widget should keep only rows with symbol and positive weight")
    widget.deleteLater()


def main() -> None:
    test_empty_result_rows_summary_and_detail()
    test_live_fallback_and_row_contract()
    test_non_live_interval_change_and_summary()
    test_formatting_detail_selection_and_weighted_change()
    test_offscreen_widget_row_smoke()
    print("spy heatmap presenter smoke tests passed")


if __name__ == "__main__":
    main()
