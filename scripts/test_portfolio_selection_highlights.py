from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_terminal_app.constants import P4_PORTFOLIO_COL_SYMBOL, P4_PORTFOLIO_COLUMNS
from budget_terminal_app.mixins.portfolio_metrics import PortfolioMetricsMixin
from budget_terminal_app.mixins.portfolio_setup import PortfolioSetupMixin
from budget_terminal_app.table_cells import TableCell


class _HighlightProbe(PortfolioSetupMixin, PortfolioMetricsMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self.resize(720, 560)
        layout = QVBoxLayout(self)

        self.outside_button = QPushButton("Outside")
        layout.addWidget(self.outside_button)

        self.p4_table = QTableWidget(2, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        self.p4_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.p4_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        for row, ticker in enumerate(("AAA", "BBB")):
            self.p4_table.setItem(row, P4_PORTFOLIO_COL_SYMBOL, QTableWidgetItem(ticker))
        layout.addWidget(self.p4_table)

        self.p4_opt_table = QTableWidget(1, 3)
        self.p4_opt_table.setHorizontalHeaderLabels(("Ticker", "Type", "Expiry"))
        self.p4_opt_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.p4_opt_table.setItem(0, 0, QTableWidgetItem("AAA"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(("Calls", "Puts"))
        self.p4_opt_table.setCellWidget(0, 1, self.strategy_combo)
        self.expiry_combo = QComboBox()
        self.expiry_combo.addItem("2026-08-21", "2026-08-21")
        self.expiry_combo.addItem("2026-09-18", "2026-09-18")
        self.p4_opt_table.setCellWidget(0, 2, self.expiry_combo)
        layout.addWidget(self.p4_opt_table)

        self._p4_initialize_position_highlight_behavior()
        self.show()

    def _p4_apply_visible_symbol_checkboxes(self) -> None:
        return None

    def _p4_apply_table_width_preferences(self, _table_key: str) -> None:
        return None


def _has_selection(table: QTableWidget) -> bool:
    selection_model = table.selectionModel()
    return bool(selection_model is not None and selection_model.hasSelection())


def _stock_rows(*tickers: str) -> list[tuple[TableCell, ...]]:
    rows = []
    for ticker in tickers:
        cells = [TableCell("") for _ in P4_PORTFOLIO_COLUMNS]
        cells[P4_PORTFOLIO_COL_SYMBOL] = TableCell(ticker)
        rows.append(tuple(cells))
    return rows


def test_portfolio_highlight_lifetime_and_mouse_scope() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _HighlightProbe()
    app.processEvents()

    try:
        stock_timer = probe._p4_stock_highlight_timer
        options_timer = probe._p4_options_highlight_timer
        assert stock_timer.isSingleShot() and stock_timer.interval() == 30_000
        assert options_timer.isSingleShot() and options_timer.interval() == 30_000

        probe.p4_table.setCurrentCell(0, P4_PORTFOLIO_COL_SYMBOL)
        probe.p4_table.selectRow(0)
        app.processEvents()
        original_timer_id = stock_timer.timerId()
        probe.p4_table.selectRow(1)
        app.processEvents()
        assert stock_timer.timerId() == original_timer_id, "programmatic selection must not extend an active deadline"

        current_row = probe.p4_table.currentRow()
        stock_timer.timeout.emit()
        app.processEvents()
        assert not _has_selection(probe.p4_table), "stock highlight should clear on timeout"
        assert probe.p4_table.currentRow() == current_row, "timeout should preserve the stock current row"

        probe.p4_opt_table.setCurrentCell(0, 0)
        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        options_timer.timeout.emit()
        app.processEvents()
        assert not _has_selection(probe.p4_opt_table), "options highlight should clear on timeout"
        assert probe.p4_opt_table.currentRow() == 0, "timeout should preserve the options current row"

        probe.p4_table.selectRow(0)
        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        QTest.mouseClick(probe.outside_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert not _has_selection(probe.p4_table) and not _has_selection(probe.p4_opt_table)

        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        stock_cell = probe.p4_table.visualItemRect(probe.p4_table.item(0, P4_PORTFOLIO_COL_SYMBOL)).center()
        QTest.mouseClick(probe.p4_table.viewport(), Qt.MouseButton.LeftButton, pos=stock_cell)
        app.processEvents()
        assert _has_selection(probe.p4_table), "clicking a stock row should retain its highlight"
        assert not _has_selection(probe.p4_opt_table), "clicking a stock row should clear the option highlight"
        user_timer_id = stock_timer.timerId()
        QTest.mouseClick(probe.p4_table.viewport(), Qt.MouseButton.LeftButton, pos=stock_cell)
        app.processEvents()
        assert stock_timer.timerId() != user_timer_id, "repeated stock interaction should restart its deadline"

        probe.p4_opt_table.selectRow(0)
        probe.p4_table.selectRow(0)
        app.processEvents()
        QTest.mouseClick(probe.expiry_combo, Qt.MouseButton.LeftButton, pos=QPoint(24, probe.expiry_combo.height() // 2))
        app.processEvents()
        assert not _has_selection(probe.p4_table), "an option combo click should clear the stock highlight"
        assert _has_selection(probe.p4_opt_table), "an option combo click should retain its owning row highlight"
        assert probe.expiry_combo.view().isVisible(), "the highlight filter must not interrupt the expiry popup"

        popup_timer_id = options_timer.timerId()
        popup_index = probe.expiry_combo.model().index(1, 0)
        popup_position = probe.expiry_combo.view().visualRect(popup_index).center()
        QTest.mouseMove(probe.expiry_combo.view().viewport(), pos=popup_position)
        QTest.mouseClick(probe.expiry_combo.view().viewport(), Qt.MouseButton.LeftButton, pos=popup_position)
        app.processEvents()
        assert probe.expiry_combo.currentData() == "2026-09-18", "the expiry popup should accept a selection"
        assert _has_selection(probe.p4_opt_table), "a popup entry should count as owning-row interaction"
        assert options_timer.timerId() != popup_timer_id, "a popup entry should restart the options deadline"

        probe.p4_table.selectRow(0)
        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        QTest.mouseClick(probe.p4_table.horizontalHeader().viewport(), Qt.MouseButton.LeftButton, pos=QPoint(10, 5))
        app.processEvents()
        assert not _has_selection(probe.p4_table) and not _has_selection(probe.p4_opt_table)

        probe.p4_table.selectRow(0)
        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        blank_position = QPoint(5, probe.p4_opt_table.viewport().height() - 3)
        assert not probe.p4_opt_table.indexAt(blank_position).isValid()
        QTest.mouseClick(probe.p4_opt_table.viewport(), Qt.MouseButton.LeftButton, pos=blank_position)
        app.processEvents()
        assert not _has_selection(probe.p4_table) and not _has_selection(probe.p4_opt_table)

        probe.p4_table.selectRow(0)
        probe.p4_opt_table.selectRow(0)
        app.processEvents()
        QTest.mouseClick(probe.p4_table.verticalScrollBar(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        app.processEvents()
        assert not _has_selection(probe.p4_table) and not _has_selection(probe.p4_opt_table)

        probe.p4_table.setCurrentCell(0, P4_PORTFOLIO_COL_SYMBOL)
        probe.p4_table.selectRow(0)
        probe.p4_table.editItem(probe.p4_table.item(0, P4_PORTFOLIO_COL_SYMBOL))
        app.processEvents()
        assert probe.p4_table.state() == QAbstractItemView.State.EditingState
        probe._p4_clear_stock_highlight()
        app.processEvents()
        assert probe.p4_table.state() == QAbstractItemView.State.EditingState, "clearing selection must not close an editor"
    finally:
        probe._p4_highlight_mouse_filter.detach()
        probe.close()
        app.processEvents()


def test_stock_refresh_restores_only_an_actual_highlight() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _HighlightProbe()
    app.processEvents()

    try:
        probe.p4_table.setSortingEnabled(False)
        probe.p4_table.setCurrentCell(0, P4_PORTFOLIO_COL_SYMBOL)
        probe.p4_table.selectRow(0)
        probe._p4_render_positions_rows(_stock_rows("BBB", "AAA"))
        app.processEvents()
        selected_items = probe.p4_table.selectedItems()
        assert selected_items, "an active highlight should survive a stock refresh"
        assert probe.p4_table.item(selected_items[0].row(), P4_PORTFOLIO_COL_SYMBOL).text() == "AAA"

        current_row = probe.p4_table.currentRow()
        probe._p4_clear_stock_highlight()
        probe._p4_render_positions_rows(_stock_rows("AAA", "BBB"))
        app.processEvents()
        assert not _has_selection(probe.p4_table), "an expired highlight must not return after refresh"
        assert probe.p4_table.currentRow() == current_row, "refresh should preserve logical current-row behavior"
    finally:
        probe._p4_highlight_mouse_filter.detach()
        probe.close()
        app.processEvents()


if __name__ == "__main__":
    test_portfolio_highlight_lifetime_and_mouse_scope()
    test_stock_refresh_restores_only_an_actual_highlight()
    print("portfolio selection highlight smoke tests passed")
