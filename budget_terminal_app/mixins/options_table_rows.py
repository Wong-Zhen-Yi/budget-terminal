from __future__ import annotations
from typing import Any
import uuid
from ..compat import *

DEFAULT_OPT_STRATEGIES = ('Calls', 'Puts', 'Covered Call', 'Cash Secured Put')
DEFAULT_OPT_STATUSES = ('Open', 'Closed', 'Expired', 'Assigned', 'Exercised')

class OptionsTableRowsMixin:
    _OPT_STRATEGIES = DEFAULT_OPT_STRATEGIES
    _OPT_STATUSES = DEFAULT_OPT_STATUSES

    def _ensure_option_row_id(self, pos: Any) -> Any:
        """Ensure a stable row identity exists for each options position."""
        row_id = str(pos.get('row_id', '') or '').strip() if isinstance(pos, dict) else ''
        if not row_id:
            row_id = uuid.uuid4().hex
            if isinstance(pos, dict):
                pos['row_id'] = row_id
        return row_id

    def _set_row_fetching_status(self, row: Any) -> None:
        """Handle set row fetching status."""
        t = self.p4_opt_table
        item = t.item(row, 2)
        if item and (not t.cellWidget(row, 2)):
            item.setText('fetching...')
            item.setForeground(self.theme_qcolor('text_muted'))

    def _add_options_row(self) -> None:
        """Add a blank options position row."""
        pos = {'ticker': '', 'strategy': 'Calls', 'expiry': '', 'strike': 0.0, 'contracts': 1, 'premium': 0.0, 'current_price': 0.0, 'iv': 0.0, 'delta': 0.0, 'theta': 0.0, 'status': 'Open', 'open_date': datetime.date.today().isoformat()}
        self._ensure_option_row_id(pos)
        self.options_data.append(pos)
        self._save_active_options_data()
        self._insert_options_row(pos)

    def _insert_options_row(self, pos: Any) -> Any:
        """Insert one row into p4_opt_table for the given position dict."""
        t = self.p4_opt_table
        t.blockSignals(True)
        row = t.rowCount()
        t.insertRow(row)
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        ed_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

        def _item(text: Any, editable: Any=True, align: Any=Qt.AlignmentFlag.AlignCenter) -> Any:
            """Handle item."""
            it = QTableWidgetItem(str(text))
            it.setFlags(ed_flags if editable else ro_flags)
            it.setTextAlignment(align)
            return it
        row_id = self._ensure_option_row_id(pos)
        ticker_item = _item(pos.get('ticker', ''), align=Qt.AlignmentFlag.AlignCenter)
        ticker_item.setData(Qt.ItemDataRole.UserRole, row_id)
        t.setItem(row, 0, ticker_item)
        strategy_combo = QComboBox()
        strategy_combo.addItems(list(getattr(self, '_OPT_STRATEGIES', DEFAULT_OPT_STRATEGIES)))
        strategy_combo.setCurrentText(pos.get('strategy', 'Calls'))
        strategy_combo.currentTextChanged.connect(partial(self._on_strategy_changed_item, ticker_item))
        t.setCellWidget(row, 1, strategy_combo)
        exp_saved = pos.get('expiry', '')
        ticker_val = pos.get('ticker', '').strip()
        placeholder_text = exp_saved if exp_saved else 'fetching...' if ticker_val else '—'
        expiry_placeholder = QTableWidgetItem(placeholder_text)
        expiry_placeholder.setFlags(ro_flags)
        expiry_placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        expiry_placeholder.setForeground(self.theme_qcolor('text_muted'))
        t.setItem(row, 2, expiry_placeholder)
        t.setItem(row, 3, _item('—', editable=False))
        t.setItem(row, 4, _item(f"{pos.get('strike', 0.0):.2f}"))
        t.setItem(row, 5, _item(f"{pos.get('contracts', 1):g}"))
        t.setItem(row, 6, _item(f"{pos.get('premium', 0.0):.2f}"))
        t.setItem(row, 7, _item(f"{pos.get('current_price', 0.0):.2f}", editable=False))
        t.setItem(row, 8, _item(f"{pos.get('iv', 0.0) * 100:.1f}%", editable=False))
        t.setItem(row, 9, _item(f"{pos.get('delta', 0.0):.3f}", editable=False))
        t.setItem(row, 10, _item(f"{pos.get('theta', 0.0):.3f}", editable=False))
        t.setItem(row, 11, _item('$0.00', editable=False))
        t.setItem(row, 12, _item('0.0%', editable=False))
        t.setItem(row, 13, _item('0.0%', editable=False))
        t.blockSignals(False)
        self._recalc_options_row(row)
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('options')
        if hasattr(self, '_p4_update_remove_options_button_state'):
            self._p4_update_remove_options_button_state()
        if ticker_val:
            self._fetch_option_expiries(row_id, ticker_val)

    def _update_total_pl_label(self) -> None:
        """Handle update total pl label."""
        total_pl = 0.0
        for p in self.options_data:
            strategy = p.get('strategy', 'Calls')
            is_seller = strategy in ('Covered Call', 'Cash Secured Put')
            prem = p.get('premium', 0)
            cur = p.get('current_price', 0)
            qty = p.get('contracts', 1)
            total_pl += (prem - cur if is_seller else cur - prem) * qty * 100
        color = self.theme_color('accent_positive' if total_pl >= 0 else 'accent_negative')
        self.p4_opt_pl_label.setText(f'Options P&L:  {total_pl:+.2f}')
        self.p4_opt_pl_label.setStyleSheet(f'background: {self.theme_color("background_secondary")}; border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: bold; color: {color};')

    def _remove_options_row(self, row: Any, *_: Any) -> None:
        """Remove an options position row."""
        if row < len(self.options_data):
            self.options_data.pop(row)
            self._save_active_options_data()
        t = self.p4_opt_table
        t.blockSignals(True)
        t.removeRow(row)
        for r in range(t.rowCount()):
            ticker_item = t.item(r, 0)
            s_combo = t.cellWidget(r, 1)
            if isinstance(s_combo, QComboBox) and ticker_item:
                try:
                    s_combo.currentTextChanged.disconnect()
                except:
                    pass
                s_combo.currentTextChanged.connect(partial(self._on_strategy_changed_item, ticker_item))
            e_combo = t.cellWidget(r, 2)
            if isinstance(e_combo, QComboBox) and ticker_item:
                try:
                    e_combo.currentIndexChanged.disconnect()
                except:
                    pass
                e_combo.currentIndexChanged.connect(partial(self._on_expiry_combo_changed, ticker_item, e_combo))
        t.blockSignals(False)
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('options')
        if hasattr(self, '_p4_update_remove_options_button_state'):
            self._p4_update_remove_options_button_state()
        self._update_total_pl_label()

    def _p4_selected_options_row(self) -> int:
        """Return the currently selected options row, or -1 if none is selected."""
        table = getattr(self, 'p4_opt_table', None)
        if table is None:
            return -1
        selection_model = table.selectionModel()
        row_candidates = []
        if selection_model is not None:
            row_candidates.extend(index.row() for index in selection_model.selectedRows())
            if not row_candidates:
                row_candidates.extend(index.row() for index in selection_model.selectedIndexes())
        row_candidates.append(table.currentRow())
        for row in row_candidates:
            if 0 <= row < table.rowCount() and row < len(self.options_data):
                return int(row)
        return -1

    def _p4_update_remove_options_button_state(self) -> None:
        """Enable options removal only when an options row exists."""
        button = getattr(self, 'p4_remove_options_btn', None)
        if button is None:
            return
        table = getattr(self, 'p4_opt_table', None)
        button.setEnabled(bool(table is not None and table.rowCount() > 0))

    def _p4_remove_selected_options_position(self) -> None:
        """Remove the selected options position from the active portfolio."""
        row = self._p4_selected_options_row()
        if row < 0:
            QMessageBox.information(self, 'Remove Position', 'Select an options position to remove.')
            self._p4_update_remove_options_button_state()
            return
        self._remove_options_row(row)
