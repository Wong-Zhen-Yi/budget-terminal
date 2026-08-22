from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QTableWidgetItem

from budget_terminal_app.constants import P4_PORTFOLIO_COL_AVG_PRICE, P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_SYMBOL
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
                "portfolio": ["AAPL"],
                "chart_slots": ["AAPL"],
                "portfolio_tracker": {"AAPL": {"shares": 0, "avg_price": 0}},
                "options_tracker": [],
                "cash_balance": 10000.0,
                "margin_debt": 0.0,
            },
        },
    }


def _prepare():
    """Build a window with the Portfolio page rendered and one zero-cost AAPL row."""
    app, window = _build_window()
    window.all_portfolios_state = _normalize_multi_portfolio_state(_state())
    window.main_portfolio_id = "portfolio_1"
    window.active_portfolio_id = "portfolio_1"
    window._rebuild_portfolio_slots()
    window._apply_main_portfolio_runtime()
    window._apply_active_portfolio_editor_state()
    window._ensure_page_initialized(1)
    # The window is never shown offscreen, so update_page4 would early-return on
    # its visibility check and render no rows.
    window._p4_page_visible = lambda: True
    window._p4_active_content_key = lambda: "positions"
    window.last_data = {"portfolio": {"AAPL": {"price": 150.0, "change": 0.0}}}
    window.update_page4(window.last_data)
    return app, window


def _balances(window) -> tuple[float, float]:
    entry = window._get_portfolio_entry("portfolio_1")
    return entry["cash_balance"], entry["margin_debt"]


def _stock_row(window, ticker: str) -> int:
    table = window.p4_table
    for row in range(table.rowCount()):
        item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
        if item is not None and item.text() == ticker:
            return row
    raise AssertionError(f"{ticker} row should be rendered")


def _refresh_summary(window):
    metrics_map, _total = window._p4_build_tracker_metrics_map(window.last_data["portfolio"])
    window._p4_update_filtered_summary_labels(metrics_map)
    return metrics_map


def test_margin_utilization_label() -> None:
    _app, window = _prepare()
    try:
        window._p4_set_active_cash_balance(0.0)
        window._p4_set_active_margin_debt(5000.0)
        window.active_tracker_data["AAPL"] = {"shares": 100, "avg_price": 150.0}
        metrics_map = _refresh_summary(window)

        percent = window._p4_margin_utilization_percent(metrics_map)
        _assert(abs(percent - 100.0 / 3.0) < 1e-6, f"expected ~33.3% utilization, got {percent}")
        _assert("33.3% used" in window.p4_margin_pct_label.text(), "percent label should show utilization")
        _assert(not window.p4_margin_pct_label.isHidden(), "percent label should show while margin is open")
        # 33.3% falls in the 25-40 orange band.
        _assert("#ff8f5a" in window.p4_margin_pct_label.styleSheet().lower(), "expected the orange band colour")

        window._p4_set_active_margin_debt(0.0)
        _refresh_summary(window)
        _assert(window.p4_margin_pct_label.isHidden(), "percent label should hide once margin is repaid")
    finally:
        window.close()


def test_cell_edits_do_not_move_money() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        row = _stock_row(window, "AAPL")
        _assert(_balances(window) == (10000.0, 0.0), "unexpected starting balances")

        table.setItem(row, P4_PORTFOLIO_COL_AVG_PRICE, QTableWidgetItem("150"))
        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("20"))
        _assert(_balances(window) == (10000.0, 0.0), "typing a position must not draw cash or open margin")

        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("100"))
        _assert(_balances(window) == (10000.0, 0.0), "increasing shares must not borrow on margin")

        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("20"))
        _assert(_balances(window) == (10000.0, 0.0), "reducing shares must not credit cash")

        entry = window._get_portfolio_entry("portfolio_1")
        _assert(
            float(entry["portfolio_tracker"]["AAPL"]["shares"]) == 20.0,
            "the edited share count should still persist",
        )

        window.update_page4(window.last_data)
        _assert(_balances(window) == (10000.0, 0.0), "a re-render must not move money either")
    finally:
        window.close()


def test_removing_a_position_does_not_move_money() -> None:
    _app, window = _prepare()
    try:
        window.active_tracker_data["AAPL"] = {"shares": 20, "avg_price": 150.0}
        _assert(_balances(window) == (10000.0, 0.0), "unexpected balances before removal")

        window._p4_remove_active_ticker("AAPL")
        _assert(_balances(window) == (10000.0, 0.0), "removing a position must leave cash and margin alone")
        _assert("AAPL" not in window._p4_active_tickers(), "the ticker should still be removed")
    finally:
        window.close()


def test_manual_balances_still_persist() -> None:
    _app, window = _prepare()
    try:
        window._p4_set_active_cash_balance(2500.0)
        window._p4_set_active_margin_debt(750.0)
        _assert(_balances(window) == (2500.0, 750.0), "the spin-box setters should persist to the portfolio entry")
        window._p4_sync_cash_input()
        _assert(window.p4_cash_input.value() == 2500.0, "cash spinbox should show the stored balance")
        _assert(window.p4_margin_input.value() == 750.0, "margin spinbox should show the stored debt")
    finally:
        window.close()


def main() -> None:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"ok {name}")
    print("portfolio cash and margin UI smoke passed")


if __name__ == "__main__":
    main()
