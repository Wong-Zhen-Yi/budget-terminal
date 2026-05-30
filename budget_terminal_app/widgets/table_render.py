from __future__ import annotations

from typing import Any, Iterable

from budget_terminal_app.dependencies import QColor, QTableWidgetItem, Qt
from budget_terminal_app.table_cells import TableCell, TableRow

_SORT_ROLE = Qt.ItemDataRole.UserRole


_ALIGNMENTS = {
    "center": Qt.AlignmentFlag.AlignCenter,
    "left": Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
    "right": Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
}


def _cell_alignment(value: Any) -> Any:
    if isinstance(value, str):
        return _ALIGNMENTS.get(value, Qt.AlignmentFlag.AlignCenter)
    return value


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that prefers an explicit numeric sort payload."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(_SORT_ROLE))
            right = float(other.data(_SORT_ROLE))
            return left < right
        except Exception:
            return super().__lt__(other)


def _cell_flags(cell: TableCell) -> Any:
    flags = Qt.ItemFlag.NoItemFlags
    if cell.enabled:
        flags |= Qt.ItemFlag.ItemIsEnabled
    if cell.selectable:
        flags |= Qt.ItemFlag.ItemIsSelectable
    if cell.editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    return flags


def _make_item(cell: TableCell) -> QTableWidgetItem:
    item = SortableTableWidgetItem(str(cell.text or "")) if cell.sort_value is not None else QTableWidgetItem(str(cell.text or ""))
    item.setFlags(_cell_flags(cell))
    item.setTextAlignment(_cell_alignment(cell.alignment))
    if cell.sort_value is not None:
        item.setData(_SORT_ROLE, cell.sort_value)
    for role, value in cell.data_roles:
        item.setData(role, value)
    if cell.tooltip:
        item.setToolTip(cell.tooltip)
    if cell.foreground:
        item.setForeground(QColor(cell.foreground))
    if cell.background:
        item.setBackground(QColor(cell.background))
    return item


def render_table_row(table: Any, row_index: int, row: TableRow) -> None:
    """Populate one existing QTableWidget row."""
    if row_index < 0:
        return
    if row_index >= table.rowCount():
        table.setRowCount(row_index + 1)
    for column_index, cell in enumerate(tuple(row)):
        render_table_cell(table, row_index, column_index, cell)


def render_table_cell(table: Any, row_index: int, column_index: int, cell: TableCell) -> None:
    """Populate one QTableWidget cell."""
    if row_index < 0 or column_index < 0:
        return
    if row_index >= table.rowCount():
        table.setRowCount(row_index + 1)
    if not isinstance(cell, TableCell):
        cell = TableCell(str(cell or ""))
    table.setItem(row_index, column_index, _make_item(cell))


def render_table_rows(table: Any, rows: Iterable[TableRow]) -> None:
    """Populate a QTableWidget in one update batch."""
    normalized_rows = [tuple(row) for row in rows]
    previous_updates = table.updatesEnabled()
    previous_signals = table.blockSignals(True)
    sorting_enabled = False
    if hasattr(table, "isSortingEnabled"):
        sorting_enabled = bool(table.isSortingEnabled())
    if sorting_enabled:
        table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            render_table_row(table, row_index, row)
    finally:
        table.setUpdatesEnabled(previous_updates)
        if sorting_enabled:
            table.setSortingEnabled(True)
        table.blockSignals(previous_signals)
        if previous_updates:
            table.viewport().update()
