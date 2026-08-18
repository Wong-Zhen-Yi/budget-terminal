from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QTableWidgetItem

from budget_terminal_app.constants import P4_PORTFOLIO_COL_AVG_PRICE, P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_SYMBOL
from budget_terminal_app.persistence import COMBINED_PORTFOLIO_ID, _normalize_multi_portfolio_state
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


def test_settlement_draws_cash_then_margin() -> None:
    _app, window = _prepare()
    try:
        _assert(_balances(window) == (10000.0, 0.0), "unexpected starting balances")

        window._p4_apply_trade_cash_flow(20 * 150.0, "AAPL")
        _assert(_balances(window) == (7000.0, 0.0), "a covered buy should only draw cash")
        _assert(window.p4_cash_input.value() == 7000.0, "cash spinbox should track the settlement")

        window._p4_apply_trade_cash_flow(80 * 150.0, "AAPL")
        _assert(_balances(window) == (0.0, 5000.0), "an overdrawing buy should borrow the shortfall")
        _assert(window.p4_margin_input.value() == 5000.0, "margin spinbox should track the settlement")

        window._p4_apply_trade_cash_flow(-(80 * 150.0), "AAPL")
        _assert(_balances(window) == (7000.0, 0.0), "a sell should repay margin before crediting cash")
    finally:
        window.close()


def test_margin_utilization_label() -> None:
    _app, window = _prepare()
    try:
        window._p4_apply_trade_cash_flow(100 * 150.0, "AAPL")
        window.active_tracker_data["AAPL"] = {"shares": 100, "avg_price": 150.0}
        metrics_map = _refresh_summary(window)

        percent = window._p4_margin_utilization_percent(metrics_map)
        _assert(abs(percent - 100.0 / 3.0) < 1e-6, f"expected ~33.3% utilization, got {percent}")
        _assert("33.3% used" in window.p4_margin_pct_label.text(), "percent label should show utilization")
        _assert(not window.p4_margin_pct_label.isHidden(), "percent label should show while margin is open")
        # 33.3% falls in the 25-40 orange band.
        _assert("#ff8f5a" in window.p4_margin_pct_label.styleSheet().lower(), "expected the orange band colour")

        window._p4_apply_trade_cash_flow(-(100 * 150.0), "AAPL")
        _refresh_summary(window)
        _assert(window.p4_margin_pct_label.isHidden(), "percent label should hide once margin is repaid")
    finally:
        window.close()


def test_cell_edits_settle_and_renders_do_not() -> None:
    _app, window = _prepare()
    try:
        table = window.p4_table
        row = _stock_row(window, "AAPL")
        _assert(_balances(window) == (10000.0, 0.0), "rendering the table must not move money")

        table.setItem(row, P4_PORTFOLIO_COL_AVG_PRICE, QTableWidgetItem("150"))
        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("20"))
        _assert(_balances(window) == (7000.0, 0.0), "typing a position should draw its cost basis from cash")

        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("100"))
        _assert(_balances(window) == (0.0, 5000.0), "increasing shares should borrow the shortfall")

        table.setItem(row, P4_PORTFOLIO_COL_SHARES, QTableWidgetItem("20"))
        _assert(_balances(window) == (7000.0, 0.0), "reducing shares should repay margin first")

        window.update_page4(window.last_data)
        _assert(_balances(window) == (7000.0, 0.0), "a re-render must not trigger a phantom settlement")
    finally:
        window.close()


def test_removing_a_position_returns_capital() -> None:
    _app, window = _prepare()
    try:
        window.active_tracker_data["AAPL"] = {"shares": 20, "avg_price": 150.0}
        window._p4_apply_trade_cash_flow(20 * 150.0, "AAPL")
        _assert(_balances(window) == (7000.0, 0.0), "unexpected balances before removal")

        window._p4_remove_active_ticker("AAPL")
        _assert(_balances(window) == (10000.0, 0.0), "removing a position should return its capital")
    finally:
        window.close()


def test_combined_portfolio_does_not_settle() -> None:
    _app, window = _prepare()
    try:
        window.active_portfolio_id = COMBINED_PORTFOLIO_ID
        if not window._p4_active_portfolio_is_combined():
            return
        before = window._p4_active_cash_balance()
        window._p4_apply_trade_cash_flow(500.0, "AAPL")
        _assert(window._p4_active_cash_balance() == before, "the read-only Combined portfolio must not settle")
    finally:
        window.close()


def main() -> None:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"ok {name}")
    print("portfolio margin settlement UI smoke passed")


if __name__ == "__main__":
    main()
