from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QAbstractItemDelegate, QTableWidget

from budget_terminal_app.constants import P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_SYMBOL
from budget_terminal_app.persistence import _normalize_multi_portfolio_state
from scripts.test_tab_picker_search import _build_window


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _state() -> dict:
    return {
        "main_portfolio_id": "portfolio_1",
        "active_portfolio_id": "portfolio_1",
        "portfolio_order": ["portfolio_1"],
        "portfolios": {
            "portfolio_1": {
                "id": "portfolio_1",
                "name": "Broker One",
                "portfolio": ["AAPL", "MSFT"],
                "chart_slots": ["AAPL", "MSFT"],
                "portfolio_tracker": {
                    "AAPL": {"shares": 10, "avg_price": 100.0},
                    "MSFT": {"shares": 5, "avg_price": 200.0},
                },
                "options_tracker": [],
                "cash_balance": 100000.0,
                "margin_debt": 0.0,
            },
        },
    }


def _prepare():
    """Build a window with the Portfolio positions table rendered."""
    app, window = _build_window()
    window.all_portfolios_state = _normalize_multi_portfolio_state(_state())
    window.main_portfolio_id = "portfolio_1"
    window.active_portfolio_id = "portfolio_1"
    window._rebuild_portfolio_slots()
    window._apply_main_portfolio_runtime()
    window._apply_active_portfolio_editor_state()
    window._ensure_page_initialized(1)
    # The window is never shown offscreen, so update_page4 would early-return on its
    # visibility check and render nothing.
    window._p4_page_visible = lambda: True
    window._p4_active_content_key = lambda: "positions"
    window.last_data = {
        "portfolio": {
            "AAPL": {"price": 150.0, "change": 0.0},
            "MSFT": {"price": 250.0, "change": 0.0},
        }
    }
    window.update_page4(window.last_data)
    return app, window


def _row_for(window, ticker: str) -> int:
    table = window.p4_table
    for row in range(table.rowCount()):
        item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
        if item is not None and item.text() == ticker:
            return row
    raise AssertionError(f"{ticker} row should be rendered")


def _open_editor(window, ticker: str, column: int = P4_PORTFOLIO_COL_SHARES):
    table = window.p4_table
    item = table.item(_row_for(window, ticker), column)
    table.editItem(item)
    _assert(table.editor_open, "editItem should mark the table as editing")
    return item


def test_render_is_deferred_while_an_editor_is_open() -> None:
    _app, window = _prepare()
    try:
        item = _open_editor(window, "AAPL")
        item.setText("999")

        window.update_page4(window.last_data)

        _assert(item.text() == "999", "an open editor's cell must survive a re-render")
        _assert(
            "positions" in window._p4_dirty_subtabs,
            "the skipped render should mark positions dirty",
        )
    finally:
        window.close()


def test_deferred_render_applies_once_editing_ends() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        _open_editor(window, "AAPL")
        window.update_page4(window.last_data)
        _assert("positions" in window._p4_dirty_subtabs, "render should have been deferred")

        table.closeEditor(None, QAbstractItemDelegate.EndEditHint.NoHint)
        _assert(not table.editor_open, "closeEditor should clear the editing flag")

        window._p4_flush_deferred_positions_render()

        shares = table.item(_row_for(window, "AAPL"), P4_PORTFOLIO_COL_SHARES)
        _assert(shares.text() == "10", f"table should match the model after flush, got {shares.text()!r}")
    finally:
        window.close()


def test_recalc_row_does_not_rewrite_under_an_editor() -> None:
    _app, window = _prepare()
    try:
        item = _open_editor(window, "AAPL")
        item.setText("42")
        row = _row_for(window, "AAPL")

        window._recalc_tracker_row(row, "AAPL", window.last_data["portfolio"])

        _assert(item.text() == "42", "_recalc_tracker_row must not rewrite the edited cell")
    finally:
        window.close()


def test_navigation_does_not_open_an_editor() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        triggers = table.editTriggers()
        _assert(
            not (triggers & QTableWidget.EditTrigger.CurrentChanged),
            "navigating a cell must not be an edit trigger",
        )
        table.setCurrentCell(_row_for(window, "MSFT"), P4_PORTFOLIO_COL_SHARES)
        _assert(not table.editor_open, "setCurrentCell must not open an editor")
    finally:
        window.close()


def test_focus_entry_cell_opens_an_editor() -> None:
    _app, window = _prepare()
    try:
        window._p4_focus_stock_entry_cell("MSFT", P4_PORTFOLIO_COL_SHARES)
        _assert(window.p4_table.editor_open, "the Add Position path should land in an open editor")
    finally:
        window.close()


def test_weight_filter_refresh_respects_the_entry_guard() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        window._p4_begin_position_entry("AAPL", P4_PORTFOLIO_COL_SHARES)
        _assert(not table.isSortingEnabled(), "the guard should disable sorting")

        window._p4_refresh_weight_filter_views()

        _assert(
            not table.isSortingEnabled(),
            "refreshing weight views must not re-enable sorting behind an active guard",
        )
        window._p4_end_position_entry()
        _assert(table.isSortingEnabled(), "sorting should return once the guard is released")
    finally:
        window.close()


def test_remove_button_requires_a_selection() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        table.clearSelection()
        table.setCurrentCell(-1, -1)
        window._p4_update_remove_stock_button_state()
        _assert(
            not window.p4_remove_stock_btn.isEnabled(),
            "Remove should be disabled with nothing selected",
        )

        table.selectRow(_row_for(window, "AAPL"))
        window._p4_update_remove_stock_button_state()
        _assert(window.p4_remove_stock_btn.isEnabled(), "Remove should enable once a row is selected")
    finally:
        window.close()


def main() -> None:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"ok {name}")
    print("portfolio editing safety smoke passed")


if __name__ == "__main__":
    main()
