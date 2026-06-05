from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtTest import QTest

from budget_terminal_app.dependencies import QApplication, QGridLayout, QPoint, QTableWidget, Qt, QWidget, pd
from budget_terminal_app.mixins.options_chain_presenters import (
    build_chain_rows,
    build_option_summary_rows,
    format_top_volume_expiration,
    prepare_strike_records,
    prepare_top_volume_records,
)
from budget_terminal_app.mixins.options_chain import OptionsChainMixin
from budget_terminal_app.widgets.table_render import render_table_rows


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_expiration_formatting() -> None:
    _assert(format_top_volume_expiration("2026-06-19") == "JUN 19 '26", "ISO expiry should use compact label")
    _assert(format_top_volume_expiration("") == "", "empty expiry should stay empty")
    _assert(format_top_volume_expiration("weekly") == "weekly", "non-date expiry labels should pass through")


def test_top_volume_preparation_and_rows() -> None:
    frame = pd.DataFrame(
        [
            {"type": "Call", "strike": "100", "lastPrice": "1.20", "volume": "50", "openInterest": "200"},
            {"type": "Put", "strike": "95", "lastPrice": "2.25", "volume": "75", "openInterest": "10"},
            {"type": "Call", "strike": "105", "lastPrice": "0.80", "volume": "90", "openInterest": "5"},
        ]
    )
    call_records = prepare_top_volume_records(
        frame,
        ticker="SPY",
        expiry="2026-06-19",
        option_type="Call",
        pd_module=pd,
    )
    _assert(len(call_records) == 2, "type filter should keep only calls")
    _assert(call_records[0]["strike"] == 105, "top-volume rows should sort by volume first")
    _assert(call_records[0]["ticker"] == "SPY", "missing ticker should be filled")
    _assert(call_records[0]["expiration"] == "2026-06-19", "missing expiration should be filled")

    rows = build_option_summary_rows(
        call_records,
        ticker="SPY",
        expiry="2026-06-19",
        positive_color="#00ff00",
        negative_color="#ff0000",
        pd_module=pd,
    )
    _assert(rows[0][1].text == "Call", "type cell should render call")
    _assert(rows[0][1].foreground == "#00ff00", "call type should use positive color")
    _assert(rows[0][2].sort_value == 105.0, "strike cell should carry numeric sort value")
    _assert(rows[0][4].sort_value == 0.8, "last price cell should carry numeric sort value")
    _assert(rows[0][5].sort_value == 90.0, "volume cell should carry numeric sort value")
    _assert(rows[0][3].text == "JUN 19 '26", "expiry cell should use compact label")
    _assert(rows[0][5].text == "90", "volume cell should format integer-like values")


def test_top_volume_metric_cell_highlights() -> None:
    records = [
        {"type": "Call", "strike": 100, "lastPrice": 10.00, "volume": 500},
        {"type": "Put", "strike": 101, "lastPrice": 9.00, "volume": 10},
        {"type": "Call", "strike": 102, "lastPrice": 1.00, "volume": 900},
        {"type": "Put", "strike": 103, "lastPrice": 2.00, "volume": 800},
        {"type": "Call", "strike": 104, "lastPrice": 3.00, "volume": 20},
        {"type": "Put", "strike": 105, "lastPrice": 8.00, "volume": 300},
    ]
    price_highlights = ("#004d24", "#0c6b37")
    low_price_highlights = ("#6b2f0c", "#4f2509")
    top_volume_highlights = ("#665500", "#4c4100")
    low_volume_highlights = ("#5c1b1b", "#401313")
    rows = build_option_summary_rows(
        records,
        ticker="SPY",
        expiry="2026-06-19",
        positive_color="#00ff00",
        negative_color="#ff0000",
        price_highlight_backgrounds=price_highlights,
        low_price_highlight_backgrounds=low_price_highlights,
        top_volume_highlight_backgrounds=top_volume_highlights,
        low_volume_highlight_backgrounds=low_volume_highlights,
        pd_module=pd,
    )

    def assert_metric_backgrounds(row_index: int, expected_price: str | None, expected_volume: str | None) -> None:
        _assert(rows[row_index][4].background == expected_price, f"row {row_index} price should have background {expected_price}")
        _assert(rows[row_index][5].background == expected_volume, f"row {row_index} volume should have background {expected_volume}")
        _assert(
            all(cell.background is None for cell in rows[row_index][:4]),
            f"row {row_index} non-metric cells should not be highlighted",
        )

    assert_metric_backgrounds(0, price_highlights[0], None)
    assert_metric_backgrounds(1, price_highlights[1], low_volume_highlights[0])
    assert_metric_backgrounds(2, low_price_highlights[0], top_volume_highlights[0])
    assert_metric_backgrounds(3, low_price_highlights[1], top_volume_highlights[1])
    assert_metric_backgrounds(4, None, low_volume_highlights[1])
    assert_metric_backgrounds(5, None, None)
    _assert(rows[1][1].foreground == "#ff0000", "put type foreground should survive metric highlights")
    _assert(rows[2][1].foreground == "#00ff00", "call type foreground should survive metric highlights")

    tiny_rows = build_option_summary_rows(
        [
            {"type": "Call", "strike": 100, "lastPrice": 10.00, "volume": 1},
            {"type": "Put", "strike": 101, "lastPrice": 9.00, "volume": 2},
        ],
        ticker="SPY",
        expiry="2026-06-19",
        positive_color="#00ff00",
        negative_color="#ff0000",
        price_highlight_backgrounds=price_highlights,
        low_price_highlight_backgrounds=low_price_highlights,
        top_volume_highlight_backgrounds=top_volume_highlights,
        low_volume_highlight_backgrounds=low_volume_highlights,
        pd_module=pd,
    )
    _assert(tiny_rows[0][4].background == price_highlights[0], "tiny panel top price should use green")
    _assert(tiny_rows[1][4].background == price_highlights[1], "tiny panel second price should use green")
    _assert(tiny_rows[0][5].background == top_volume_highlights[1], "tiny panel second volume should use yellow")
    _assert(tiny_rows[1][5].background == top_volume_highlights[0], "tiny panel top volume should use yellow")
    _assert(
        all(low_price not in {tiny_rows[row][4].background for row in range(len(tiny_rows))} for low_price in low_price_highlights),
        "tiny panel should exclude top prices from lowest-price highlights",
    )
    _assert(
        all(low_volume not in {tiny_rows[row][5].background for row in range(len(tiny_rows))} for low_volume in low_volume_highlights),
        "tiny panel should exclude top volumes from lowest-volume highlights",
    )


def test_strike_preparation() -> None:
    frame = pd.DataFrame(
        [
            {"type": "Put", "strike": 100.0, "lastPrice": 2.0, "volume": 20, "openInterest": 10},
            {"type": "Call", "strike": 100.0, "lastPrice": 1.5, "volume": 5, "openInterest": 50},
            {"type": "Call", "strike": 101.0, "lastPrice": 1.1, "volume": 999, "openInterest": 999},
        ]
    )
    records = prepare_strike_records(
        frame,
        ticker="SPY",
        expiry="2026-06-19",
        selected_strike=100.0,
        tolerance=0.0001,
        pd_module=pd,
    )
    _assert([record["type"] for record in records] == ["Call", "Put"], "strike rows should order calls before puts")
    _assert(all(record["strike"] == 100.0 for record in records), "strike rows should keep only matching strike")


def test_top_volume_table_sorts_strike_numerically() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    table = QTableWidget(0, 6)
    table.setHorizontalHeaderLabels(["Ticker", "Type", "Strike", "Exp", "Last", "Vol"])
    table.setSortingEnabled(True)
    rows = build_option_summary_rows(
        [
            {"type": "Call", "strike": 100, "lastPrice": 1.0, "volume": 50},
            {"type": "Call", "strike": 95, "lastPrice": 2.0, "volume": 40},
            {"type": "Put", "strike": 105, "lastPrice": 3.0, "volume": 30},
        ],
        ticker="SPY",
        expiry="2026-06-19",
        positive_color="#00ff00",
        negative_color="#ff0000",
        pd_module=pd,
    )
    render_table_rows(table, rows)

    table.sortItems(2, Qt.SortOrder.AscendingOrder)
    _assert([table.item(row, 2).text() for row in range(table.rowCount())] == ["95.0", "100.0", "105.0"], "strike column should sort ascending numerically")
    table.sortItems(2, Qt.SortOrder.DescendingOrder)
    _assert([table.item(row, 2).text() for row in range(table.rowCount())] == ["105.0", "100.0", "95.0"], "strike column should sort descending numerically")


class _TopVolumeSortHarness(OptionsChainMixin):
    def set_theme_role(self, *_args: object, **_kwargs: object) -> None:
        pass


def _render_top_volume_table(table: QTableWidget, records: list[dict[str, object]]) -> None:
    render_table_rows(
        table,
        build_option_summary_rows(
            records,
            ticker="SPY",
            expiry="2026-06-19",
            positive_color="#00ff00",
            negative_color="#ff0000",
            pd_module=pd,
        ),
    )


def _table_column_text(table: QTableWidget, column: int) -> list[str]:
    return [table.item(row, column).text() for row in range(table.rowCount())]


def _click_table_header(table: QTableWidget, column: int) -> None:
    app = QApplication.instance()
    header = table.horizontalHeader()
    table.show()
    if app is not None:
        app.processEvents()
    x_pos = header.sectionViewportPosition(column) + header.sectionSize(column) // 2
    y_pos = max(1, header.height() // 2)
    QTest.mouseClick(
        header.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(x_pos, y_pos),
    )
    if app is not None:
        app.processEvents()


def test_top_volume_panel_sort_sync() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    harness = _TopVolumeSortHarness()
    harness._p5_top_volume_sort_state = {}
    harness._p5_top_volume_sort_syncing = False
    left_table = harness._make_top_volume_table()
    right_table = harness._make_top_volume_table()
    harness.p5_top_volume_views = {
        "top_volume": {
            "sections": {
                "near": {"table": left_table},
                "far": {"table": right_table},
            }
        }
    }
    harness._p5_attach_top_volume_sort_sync("top_volume", left_table)
    harness._p5_attach_top_volume_sort_sync("top_volume", right_table)
    _render_top_volume_table(
        left_table,
        [
            {"type": "Call", "strike": 100, "lastPrice": 1.0, "volume": 50},
            {"type": "Call", "strike": 95, "lastPrice": 2.0, "volume": 40},
            {"type": "Put", "strike": 105, "lastPrice": 3.0, "volume": 30},
        ],
    )
    _render_top_volume_table(
        right_table,
        [
            {"type": "Put", "strike": 110, "lastPrice": 1.5, "volume": 20},
            {"type": "Put", "strike": 90, "lastPrice": 2.5, "volume": 60},
        ],
    )

    left_table.sortItems(2, Qt.SortOrder.AscendingOrder)
    _assert(_table_column_text(left_table, 2) == ["95.0", "100.0", "105.0"], "source panel should sort strike ascending")
    _assert(_table_column_text(right_table, 2) == ["90.0", "110.0"], "sibling panel should sync strike ascending")

    left_table.sortItems(2, Qt.SortOrder.DescendingOrder)
    _assert(_table_column_text(left_table, 2) == ["105.0", "100.0", "95.0"], "source panel should sort strike descending")
    _assert(_table_column_text(right_table, 2) == ["110.0", "90.0"], "sibling panel should sync strike descending")

    _render_top_volume_table(
        right_table,
        [
            {"type": "Put", "strike": 110, "lastPrice": 1.5, "volume": 20},
            {"type": "Put", "strike": 90, "lastPrice": 2.5, "volume": 60},
        ],
    )
    harness._p5_apply_top_volume_sort("top_volume")
    _assert(_table_column_text(right_table, 2) == ["110.0", "90.0"], "stored sort should reapply after panel rerender")


def test_top_volume_grid_builder_attaches_sort_sync() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    harness = _TopVolumeSortHarness()
    harness._p5_top_volume_sort_state = {}
    harness._p5_top_volume_sort_syncing = False
    scroll_contents = QWidget()
    harness.p5_top_volume_views = {
        "top_volume": {
            "grid_layout": QGridLayout(scroll_contents),
            "sections": {},
            "bucket_config": (),
        }
    }
    harness._p5_set_top_volume_bucket_config(
        "top_volume",
        (
            ("near", "Near", 0),
            ("far", "Far", 0),
        ),
    )
    sections = harness.p5_top_volume_views["top_volume"]["sections"]
    left_table = sections["near"]["table"]
    right_table = sections["far"]["table"]
    _render_top_volume_table(
        left_table,
        [
            {"type": "Call", "strike": 100, "lastPrice": 1.0, "volume": 50},
            {"type": "Call", "strike": 95, "lastPrice": 2.0, "volume": 40},
        ],
    )
    _render_top_volume_table(
        right_table,
        [
            {"type": "Put", "strike": 110, "lastPrice": 1.5, "volume": 20},
            {"type": "Put", "strike": 90, "lastPrice": 2.5, "volume": 60},
        ],
    )

    _click_table_header(left_table, 2)
    _assert(_table_column_text(right_table, 2) == ["90.0", "110.0"], "top-volume builder should wire panel sort sync")


def test_strike_grid_builder_stays_independent() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    harness = _TopVolumeSortHarness()
    scroll_contents = QWidget()
    harness.p5_strike_sections = {}
    harness.p5_strike_grid_layout = QGridLayout(scroll_contents)
    harness._p5_set_strike_bucket_config((("near", "Near", 0),))
    _assert("near" in harness.p5_strike_sections, "strike builder should still create its section")


def test_chain_rows() -> None:
    empty_rows = build_chain_rows(
        pd.DataFrame(),
        [("Strike", "strike", "{:.1f}")],
        {},
        {},
        strategy_tooltip=lambda rank, detail: "",
        strategy_bg=lambda rank: None,
        positive_color="#00ff00",
        negative_color="#ff0000",
        muted_color="#999999",
        pd_module=pd,
    )
    _assert(empty_rows == [], "empty chain should render no rows")

    frame = pd.DataFrame(
        [
            {
                "strike": 100.0,
                "lastPrice": 1.25,
                "change": 0.2,
                "iv_percent": 31.25,
            }
        ]
    )
    rows = build_chain_rows(
        frame,
        [
            ("Strike", "strike", "{:.1f}"),
            ("Last", "lastPrice", "{:.2f}"),
            ("Chg", "change", "{:+.2f}"),
            ("IV", "iv_percent", "{:.1f}%"),
        ],
        {0: 1},
        {0: {"score": 10}},
        strategy_tooltip=lambda rank, detail: f"rank {rank}" if rank else "",
        strategy_bg=lambda rank: "#101010" if rank else None,
        positive_color="#00ff00",
        negative_color="#ff0000",
        muted_color="#999999",
        pd_module=pd,
    )
    _assert(rows[0][0].text == "100.0  #1", "ranked strike should show rank suffix")
    _assert(rows[0][0].background == "#101010", "ranked cells should get strategy background")
    _assert(rows[0][0].tooltip == "rank 1", "ranked cells should get strategy tooltip")
    _assert(rows[0][2].foreground == "#00ff00", "positive change should use positive color")
    _assert(rows[0][3].foreground == "#999999", "IV should use muted color")


def main() -> None:
    test_expiration_formatting()
    test_top_volume_preparation_and_rows()
    test_top_volume_metric_cell_highlights()
    test_strike_preparation()
    test_top_volume_table_sorts_strike_numerically()
    test_top_volume_panel_sort_sync()
    test_top_volume_grid_builder_attaches_sort_sync()
    test_strike_grid_builder_stays_independent()
    test_chain_rows()
    print("options chain presenter smoke tests passed")


if __name__ == "__main__":
    main()
