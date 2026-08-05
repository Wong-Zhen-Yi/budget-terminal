from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QLabel, QPushButton

from budget_terminal_app.constants import P4_PORTFOLIO_COLUMNS
from budget_terminal_app.mixins.portfolio_setup import P4_OPTIONS_COLUMNS
from scripts.test_tab_picker_search import _build_window


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_table_fits(table, name: str) -> None:
    viewport_width = int(table.viewport().width())
    column_width = sum(table.columnWidth(column) for column in range(table.columnCount()))
    _assert(viewport_width > 0, f"{name} viewport should have a positive width")
    _assert(abs(column_width - viewport_width) <= 1, f"{name} columns should fit its viewport")
    _assert(
        table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        f"{name} horizontal scrollbar should always remain hidden",
    )
    _assert(not table.horizontalScrollBar().isVisible(), f"{name} horizontal scrollbar should not flash into view")
    _assert(table.horizontalScrollBar().maximum() == 0, f"{name} should not retain horizontal overflow")
    _assert(
        table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        f"{name} should retain vertical scrolling when rows overflow",
    )


def test_positions_layout_and_table_fit() -> None:
    app, window = _build_window()
    try:
        window.resize(1600, 1000)
        window.switch_page(1)
        window.show()
        app.processEvents()

        _assert(
            [window.p4_content_tabs.tabText(index) for index in range(window.p4_content_tabs.count())]
            == ["Positions", "Pie Chart", "Portfolio Heatmap", "Momentum Tracker", "Portfolio Metrics"],
            "Portfolio sub-tabs should remain unchanged",
        )
        _assert(
            [window.p4_table.horizontalHeaderItem(index).text() for index in range(window.p4_table.columnCount())]
            == list(P4_PORTFOLIO_COLUMNS),
            "stock columns should remain unchanged",
        )
        _assert(
            [window.p4_opt_table.horizontalHeaderItem(index).text() for index in range(window.p4_opt_table.columnCount())]
            == list(P4_OPTIONS_COLUMNS),
            "options columns should remain unchanged",
        )
        _assert(window.p4_table.isSortingEnabled(), "stock sorting should remain enabled")
        _assert(
            window.p4_table.editTriggers() == QAbstractItemView.EditTrigger.AllEditTriggers,
            "stock editing behavior should remain unchanged",
        )
        _assert(window.p4_table.verticalHeader().defaultSectionSize() == 52, "stock row height should remain unchanged")
        _assert(window.p4_opt_table.verticalHeader().defaultSectionSize() == 38, "options row height should remain unchanged")
        _assert(window.p4_cash_include_checkbox.isChecked(), "Cash should default to included in Portfolio Weight")
        _assert(window.p4_cash_include_checkbox.text() == "BROKERAGE CASH", "Cash checkbox should label the cash position")
        _assert(window.p4_stock_positions_label.text().startswith("Positions:"), "position count should use the renamed label")
        visible_labels = {
            label.text()
            for label in window.p4_positions_page.findChildren(QLabel)
        }
        _assert("Positions" in visible_labels, "stock section should be renamed to Positions")
        _assert("Stock Positions" not in visible_labels, "old Stock Positions heading should be removed")

        action_buttons = {
            button.text(): button
            for button in window.p4_positions_page.findChildren(QPushButton)
        }
        action_labels = set(action_buttons)
        _assert(
            {
                "+ Add Position",
                "Remove Position",
                "Refresh Holdings",
                "Export for LLM",
                "Export Tickers",
                "↻ Sync",
            }.issubset(action_labels),
            "Positions actions should remain available",
        )
        _assert(
            window.p4_remove_stock_btn.geometry().x()
            < action_buttons["Refresh Holdings"].geometry().x()
            < action_buttons["Export for LLM"].geometry().x(),
            "Refresh Holdings should sit directly after Remove Position and before the export actions",
        )

        total_width = sum(window.p4_main_splitter.sizes())
        for left_width in (max(total_width - 260, 1), int(total_width * 0.72), int(total_width * 0.60)):
            window.p4_main_splitter.setSizes([left_width, max(total_width - left_width, 1)])
            app.processEvents()
            window._p4_refit_tables_after_splitter_move()
            app.processEvents()
            app.processEvents()
            _assert_table_fits(window.p4_table, "stock table")
            _assert_table_fits(window.p4_opt_table, "options table")

        window.p4_table.setRowCount(50)
        window.p4_opt_table.setRowCount(50)
        app.processEvents()
        window._p4_refit_tables_after_splitter_move()
        app.processEvents()
        app.processEvents()
        _assert(window.p4_table.verticalScrollBar().maximum() > 0, "stock rows should retain vertical overflow")
        _assert(window.p4_opt_table.verticalScrollBar().maximum() > 0, "options rows should retain vertical overflow")
        _assert_table_fits(window.p4_table, "stock table with vertical overflow")
        _assert_table_fits(window.p4_opt_table, "options table with vertical overflow")

        _assert(
            all(size > 0 for size in window.p4_positions_splitter.sizes()),
            "stock and options sections should remain non-collapsible",
        )
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_positions_layout_and_table_fit()
    print("portfolio positions layout smoke passed")
    sys.stdout.flush()
    os._exit(0)
