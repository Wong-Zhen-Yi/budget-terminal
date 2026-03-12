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
            item.setForeground(QColor('#888888'))

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
        strategy_combo.setStyleSheet('QComboBox { background: #1a1a2e; color: white; border: 1px solid #3a3a5a; border-radius: 3px; padding: 2px 4px; }QComboBox::drop-down { border: none; }QComboBox QAbstractItemView { background: #1a1a2e; color: white; selection-background-color: #2a2a5a; }')
        strategy_combo.currentTextChanged.connect(partial(self._on_strategy_changed_item, ticker_item))
        t.setCellWidget(row, 1, strategy_combo)
        exp_saved = pos.get('expiry', '')
        ticker_val = pos.get('ticker', '').strip()
        placeholder_text = exp_saved if exp_saved else 'fetching...' if ticker_val else '—'
        expiry_placeholder = QTableWidgetItem(placeholder_text)
        expiry_placeholder.setFlags(ro_flags)
        expiry_placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        expiry_placeholder.setForeground(QColor('#888888'))
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
        status_combo = QComboBox()
        status_combo.addItems(list(getattr(self, '_OPT_STATUSES', DEFAULT_OPT_STATUSES)))
        status_combo.setCurrentText(pos.get('status', 'Open'))
        status_combo.setStyleSheet('QComboBox { background: #1a1a2e; color: white; border: 1px solid #3a3a5a; border-radius: 3px; padding: 2px 4px; }QComboBox::drop-down { border: none; }QComboBox QAbstractItemView { background: #1a1a2e; color: white; selection-background-color: #2a2a5a; }')
        status_combo.currentTextChanged.connect(partial(self._on_status_changed_item, ticker_item))
        t.setCellWidget(row, 14, status_combo)
        rm_btn = QPushButton('×')
        rm_btn.setFixedSize(28, 28)
        rm_btn.setStyleSheet('QPushButton { background: #3a1a1a; color: #f44336; border: 1px solid #5a2a2a; border-radius: 4px; font-weight: bold; font-size: 14px; }QPushButton:hover { background: #5a1a1a; }')
        rm_btn.clicked.connect(partial(self._remove_options_row, row))
        t.setCellWidget(row, 15, rm_btn)
        t.blockSignals(False)
        self._recalc_options_row(row)
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
        color = '#4caf50' if total_pl >= 0 else '#f44336'
        self.p4_opt_pl_label.setText(f'Options P&L:  {total_pl:+.2f}')
        self.p4_opt_pl_label.setStyleSheet(f'QLabel {{ background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: bold; color: {color}; }}')

    def _remove_options_row(self, row: Any, *_: Any) -> None:
        """Remove an options position row."""
        if row < len(self.options_data):
            self.options_data.pop(row)
            self._save_active_options_data()
        t = self.p4_opt_table
        t.blockSignals(True)
        t.removeRow(row)
        for r in range(t.rowCount()):
            rm_btn = t.cellWidget(r, 15)
            if isinstance(rm_btn, QPushButton):
                try:
                    rm_btn.clicked.disconnect()
                except:
                    pass
                rm_btn.clicked.connect(partial(self._remove_options_row, r))
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
            st_combo = t.cellWidget(r, 14)
            if isinstance(st_combo, QComboBox) and ticker_item:
                try:
                    st_combo.currentTextChanged.disconnect()
                except:
                    pass
                st_combo.currentTextChanged.connect(partial(self._on_status_changed_item, ticker_item))
        t.blockSignals(False)
        self._update_total_pl_label()
