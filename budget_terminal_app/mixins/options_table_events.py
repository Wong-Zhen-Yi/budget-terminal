from __future__ import annotations
from typing import Any
from ..compat import *

class OptionsTableEventsMixin:

    def _on_expiry_combo_changed_by_row(self, row: Any, ticker: Any, combo: Any, *_: Any) -> None:
        """Handle expiry combo changes using row-based validation."""
        row = self._resolve_active_option_row(row, ticker, getattr(self, 'active_portfolio_id', None))
        if row is None:
            return
        expiry = combo.currentData()
        if expiry:
            self.options_data[row]['expiry'] = expiry
            self._save_active_options_data()
            self._fetch_single_option_price(row)
            self._recalc_options_row(row)

    def _on_expiry_changed_item(self, ticker_item: Any, expiry: Any) -> None:
        """Handle expiry changed item."""
        row = self.p4_opt_table.row(ticker_item)
        if 0 <= row < len(self.options_data):
            self.options_data[row]['expiry'] = expiry
            self._save_active_options_data()

    def _on_strategy_changed_item(self, ticker_item: Any, strategy: Any) -> None:
        """Handle strategy changed item."""
        row = self.p4_opt_table.row(ticker_item)
        if 0 <= row < len(self.options_data):
            self.options_data[row]['strategy'] = strategy
            self._save_active_options_data()
            self._fetch_single_option_price(row)
            self._recalc_options_row(row)

    def _on_expiry_combo_changed(self, ticker_item: Any, combo: Any, *_: Any) -> None:
        """Handle expiry combo changed."""
        row = self.p4_opt_table.row(ticker_item)
        if 0 <= row < len(self.options_data):
            expiry = combo.currentData()
            if expiry:
                self.options_data[row]['expiry'] = expiry
                self._save_active_options_data()
                self._fetch_single_option_price(row)
                self._recalc_options_row(row)

    def _on_status_changed_item(self, ticker_item: Any, status: Any) -> None:
        """Handle status changed item."""
        row = self.p4_opt_table.row(ticker_item)
        if 0 <= row < len(self.options_data):
            self.options_data[row]['status'] = status
            self._save_active_options_data()

    def _on_expiry_changed(self, row: Any, expiry: Any) -> None:
        """Handle expiry changed."""
        if row < len(self.options_data):
            self.options_data[row]['expiry'] = expiry
            self._save_active_options_data()

    def _on_strategy_changed(self, row: Any, strategy: Any) -> None:
        """Handle strategy changed."""
        if row < len(self.options_data):
            self.options_data[row]['strategy'] = strategy
            self._save_active_options_data()

    def _on_options_cell_changed(self, item: Any) -> None:
        """Handle options cell changed."""
        col = item.column()
        if col not in (0, 4, 5, 6):
            return
        row = item.row()
        if row >= len(self.options_data):
            return
        pos = self.options_data[row]
        text = item.text().strip()
        try:
            if col == 0:
                ticker = text.upper()
                pos['ticker'] = ticker
                self.p4_opt_table.blockSignals(True)
                item.setText(ticker)
                self.p4_opt_table.blockSignals(False)
                placeholder = QTableWidgetItem('fetching...')
                placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setForeground(self.theme_qcolor('text_muted'))
                self.p4_opt_table.setItem(row, 2, placeholder)
                if ticker:
                    row_id = str(pos.get('row_id', '') or '').strip()
                    self._fetch_option_expiries(row_id, ticker)
            elif col == 4:
                pos['strike'] = float(text.replace('$', '').replace(',', ''))
                self._fetch_single_option_price(row)
            elif col == 5:
                pos['contracts'] = int(float(text))
            elif col == 6:
                pos['premium'] = float(text.replace('$', '').replace(',', ''))
        except (ValueError, TypeError):
            pass
        self._save_active_options_data()
        self._recalc_options_row(row)

    def _recalc_options_row(self, row: Any) -> Any:
        """Recalculate DTE, P&L, return %, and ITM status."""
        if row >= len(self.options_data):
            return
        t = self.p4_opt_table
        t.blockSignals(True)
        pos = self.options_data[row]
        ticker = pos.get('ticker', '').upper()
        contracts = pos.get('contracts', 1)
        premium = pos.get('premium', 0.0)
        current = pos.get('current_price', 0.0)
        strike = pos.get('strike', 0.0)
        strategy = pos.get('strategy', 'Calls')
        expiry = pos.get('expiry', '')
        is_seller = strategy in ('Covered Call', 'Cash Secured Put')
        is_call = 'Call' in strategy or strategy == 'Calls'
        underlying_price = 0.0
        if self.last_data and 'portfolio' in self.last_data:
            underlying_price = self.last_data['portfolio'].get(ticker, {}).get('price', 0.0)
        dte = 0
        if expiry:
            try:
                exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
                dte = max(0, (exp_date - datetime.date.today()).days)
            except (TypeError, ValueError):
                pass
        itm_text = '—'
        itm_color = self.theme_color('text_muted')
        if underlying_price > 0 and strike > 0:
            if is_call:
                itm = underlying_price > strike
            else:
                itm = underlying_price < strike
            itm_text = 'ITM' if itm else 'OTM'
            itm_color = self.theme_color('warning' if itm else 'accent')
        pl_dollar = (premium - current if is_seller else current - premium) * contracts * 100
        if is_seller:
            capital = strike * contracts * 100 if strike > 0 else 0
            return_pct = premium * contracts * 100 / capital * 100 if capital > 0 else 0.0
        else:
            return_pct = (current - premium) / premium * 100 if premium > 0 else 0.0
        open_date_str = pos.get('open_date', '')
        dte_at_open = dte
        if open_date_str and expiry:
            try:
                od = datetime.datetime.strptime(open_date_str, '%Y-%m-%d').date()
                ed = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
                dte_at_open = max(1, (ed - od).days)
            except (TypeError, ValueError):
                pass
        annual_pct = return_pct * (365.0 / max(1, dte_at_open))
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        def _ro(text: Any, color: Any=None) -> Any:
            """Handle ro."""
            it = QTableWidgetItem(text)
            it.setFlags(ro_flags)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                it.setForeground(QColor(color))
            return it
        dte_color = self.theme_color('accent_negative' if 0 < dte <= 7 else 'warning' if dte <= 30 else 'text_muted')
        t.setItem(row, 3, _ro(f'{dte}d ({itm_text})' if expiry else '—', dte_color if not expiry else itm_color))
        pl_clr = self.theme_color('accent_positive' if pl_dollar >= 0 else 'accent_negative')
        t.setItem(row, 11, _ro(f'{pl_dollar:+.2f}', pl_clr))
        t.setItem(row, 12, _ro(f'{return_pct:+.1f}%', pl_clr))
        t.setItem(row, 13, _ro(f'{annual_pct:+.1f}%', pl_clr))
        t.blockSignals(False)
        self._update_total_pl_label()
