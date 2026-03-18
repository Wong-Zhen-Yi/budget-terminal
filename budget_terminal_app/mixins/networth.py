from __future__ import annotations
from typing import Any
from ..compat import *

class NetWorthMixin:

    def _p6_portfolio_breakdown(self) -> Any:
        """Return per-portfolio stock/options values using saved portfolio names."""
        portfolio_quotes = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        breakdown = []
        all_state = getattr(self, 'all_portfolios_state', {})
        portfolios = all_state.get('portfolios', {}) if isinstance(all_state, dict) else {}
        for portfolio_id in PORTFOLIO_IDS:
            entry = portfolios.get(portfolio_id, {})
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id))
            tickers = list(entry.get('portfolio', []))
            tracker_data = dict(entry.get('portfolio_tracker', {})) if isinstance(entry.get('portfolio_tracker', {}), dict) else {}
            options_data = list(entry.get('options_tracker', [])) if isinstance(entry.get('options_tracker', []), list) else []
            stock_mv = sum((tracker_data.get(ticker, {}).get('shares', 0) * portfolio_quotes.get(ticker, {}).get('price', 0) for ticker in tickers))
            options_equity = 0.0
            for pos in options_data:
                strategy = pos.get('strategy', 'Calls')
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                premium = pos.get('premium', 0)
                current = pos.get('current_price', 0)
                qty = pos.get('contracts', 1)
                if is_seller:
                    options_equity += (premium - current) * qty * 100
                else:
                    options_equity += current * qty * 100
            breakdown.append({'id': portfolio_id, 'name': name, 'stocks': stock_mv, 'options': options_equity})
        return breakdown

    ASSET_COLORS = ['#66bb6a', '#81c784', '#a5d6a7', '#c8e6c9', '#4caf50', '#43a047']
    PENSION_COLORS = ['#42a5f5', '#64b5f6', '#90caf9', '#bbdefb', '#1e88e5', '#1565c0']
    DEBT_COLORS = ['#ef5350', '#e57373', '#ef9a9a', '#f44336', '#d32f2f', '#c62828']

    def _p6_table_for(self, category: Any) -> Any:
        """Return the QTableWidget for a given net-worth category."""
        if category == 'cash':
            return self.p6_cash_table
        if category == 'pension_insurance':
            return self.p6_pension_table
        return self.p6_debt_table

    def init_page6(self) -> None:
        """Build the Personal Finance page UI."""
        layout = QVBoxLayout(self.page6)
        layout.setContentsMargins(10, 2, 10, 10)
        layout.setSpacing(8)
        tables_splitter = QSplitter(Qt.Orientation.Horizontal)
        cash_widget = QWidget()
        cash_layout = QVBoxLayout(cash_widget)
        cash_layout.setContentsMargins(0, 0, 0, 2)
        cash_layout.setSpacing(6)
        cash_hdr = QHBoxLayout()
        cash_hdr.setContentsMargins(0, 0, 0, 2)
        cash_hdr.setSpacing(8)
        cash_lbl = QLabel('<b>CASH</b>')
        self.set_theme_role(cash_lbl, 'section_title')
        add_cash_btn = QPushButton('+ Add')
        add_cash_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_cash_btn, 'positive')
        add_cash_btn.clicked.connect(lambda: self._p6_add_row('cash'))
        cash_hdr.addWidget(cash_lbl)
        cash_hdr.addStretch()
        cash_hdr.addWidget(add_cash_btn)
        self.p6_cash_table = QTableWidget(0, 3)
        self.p6_cash_table.setHorizontalHeaderLabels(['Description', 'Amount ($)', ''])
        self.p6_cash_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_cash_table.setColumnWidth(2, 30)
        self.p6_cash_table.itemChanged.connect(lambda: self._p6_on_data_changed('cash'))
        cash_layout.addLayout(cash_hdr)
        cash_layout.addWidget(self.p6_cash_table)
        tables_splitter.addWidget(cash_widget)
        pension_widget = QWidget()
        pension_layout = QVBoxLayout(pension_widget)
        pension_layout.setContentsMargins(0, 0, 0, 2)
        pension_layout.setSpacing(6)
        pension_hdr = QHBoxLayout()
        pension_hdr.setContentsMargins(0, 0, 0, 2)
        pension_hdr.setSpacing(8)
        pension_lbl = QLabel('<b>PENSION & INSURANCE</b>')
        self.set_theme_role(pension_lbl, 'section_title')
        add_pension_btn = QPushButton('+ Add')
        add_pension_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_pension_btn, 'accent')
        add_pension_btn.clicked.connect(lambda: self._p6_add_row('pension_insurance'))
        pension_hdr.addWidget(pension_lbl)
        pension_hdr.addStretch()
        pension_hdr.addWidget(add_pension_btn)
        self.p6_pension_table = QTableWidget(0, 3)
        self.p6_pension_table.setHorizontalHeaderLabels(['Description', 'Amount ($)', ''])
        self.p6_pension_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_pension_table.setColumnWidth(2, 30)
        self.p6_pension_table.itemChanged.connect(lambda: self._p6_on_data_changed('pension_insurance'))
        pension_layout.addLayout(pension_hdr)
        pension_layout.addWidget(self.p6_pension_table)
        tables_splitter.addWidget(pension_widget)
        debt_widget = QWidget()
        debt_layout = QVBoxLayout(debt_widget)
        debt_layout.setContentsMargins(0, 2, 0, 0)
        debt_layout.setSpacing(6)
        debt_hdr = QHBoxLayout()
        debt_hdr.setContentsMargins(0, 0, 0, 2)
        debt_hdr.setSpacing(8)
        debt_lbl = QLabel('<b>DEBT</b>')
        self.set_theme_role(debt_lbl, 'section_title')
        add_debt_btn = QPushButton('+ Add')
        add_debt_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_debt_btn, 'danger')
        add_debt_btn.clicked.connect(lambda: self._p6_add_row('debt'))
        debt_hdr.addWidget(debt_lbl)
        debt_hdr.addStretch()
        debt_hdr.addWidget(add_debt_btn)
        self.p6_debt_table = QTableWidget(0, 3)
        self.p6_debt_table.setHorizontalHeaderLabels(['Description', 'Amount ($)', ''])
        self.p6_debt_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_debt_table.setColumnWidth(2, 30)
        self.p6_debt_table.itemChanged.connect(lambda: self._p6_on_data_changed('debt'))
        debt_layout.addLayout(debt_hdr)
        debt_layout.addWidget(self.p6_debt_table)
        tables_splitter.addWidget(debt_widget)
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 2)
        summary_layout.setSpacing(6)
        summary_lbl = QLabel('<b>SUMMARY</b>')
        self.set_theme_role(summary_lbl, 'section_title')
        summary_layout.addWidget(summary_lbl)
        self.p6_total_summary = QLabel('')
        self.p6_total_summary.setStyleSheet('font-size: 12px;')
        self.p6_total_summary.setWordWrap(True)
        self.p6_total_summary.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.p6_total_summary, 1)
        tables_splitter.addWidget(summary_widget)
        layout.addWidget(tables_splitter, 1)
        silo_box = QGroupBox('Personal Finance Silos')
        self.set_theme_role(silo_box, 'panel')
        silo_inner = QVBoxLayout(silo_box)
        silo_inner.setContentsMargins(6, 6, 6, 6)
        silo_inner.setSpacing(4)
        silo_toolbar = QHBoxLayout()
        silo_toolbar.addStretch()
        self.p6_scale_btn = QPushButton('Log')
        self.p6_scale_btn.setCheckable(True)
        self.p6_scale_btn.setChecked(True)
        self.p6_scale_btn.setFixedSize(52, 24)
        self.set_theme_variant(self.p6_scale_btn, 'accent')
        self.p6_scale_btn.clicked.connect(self._p6_toggle_scale)
        silo_toolbar.addWidget(self.p6_scale_btn)
        silo_inner.addLayout(silo_toolbar)
        self.p6_silo_bar = BarChartWidget()
        self.p6_silo_bar.setMinimumHeight(120)
        self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
        silo_inner.addWidget(self.p6_silo_bar, 1)
        layout.addWidget(silo_box, 1)
        self._p6_populate_tables()

    def _p6_populate_tables(self) -> None:
        """Handle p6 populate tables."""
        for category in ['cash', 'pension_insurance', 'debt']:
            table = self._p6_table_for(category)
            data_list = sorted(self.networth_data.get(category, []), key=lambda x: x.get('amount', 0.0), reverse=True)
            table.blockSignals(True)
            table.setRowCount(0)
            for item in data_list:
                self._p6_insert_row_ui(table, category, item.get('desc', ''), item.get('amount', 0.0))
            table.blockSignals(False)
        self._p6_update_total()

    def _p6_insert_row_ui(self, table: Any, category: Any, desc: Any, amount: Any) -> None:
        """Handle p6 insert row ui."""
        row = table.rowCount()
        table.insertRow(row)
        desc_item = QTableWidgetItem(desc)
        amt_item = QTableWidgetItem(f'{amount:.2f}')
        amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, 0, desc_item)
        table.setItem(row, 1, amt_item)
        del_btn = QPushButton('×')
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(f'background-color: {self.theme_color("accent_negative_bg")}; color: {self.theme_color("accent_negative")}; border-radius: 4px; border: 1px solid {self.theme_color("accent_negative")};')
        del_btn.clicked.connect(lambda: self._p6_remove_row(category, row))
        table.setCellWidget(row, 2, del_btn)

    def _p6_add_row(self, category: Any) -> None:
        """Handle p6 add row."""
        table = self._p6_table_for(category)
        table.blockSignals(True)
        self._p6_insert_row_ui(table, category, 'New Item', 0.0)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_remove_row(self, category: Any, row_idx: Any) -> None:
        """Handle p6 remove row."""
        table = self._p6_table_for(category)
        button = self.sender()
        if button:
            pos = button.parent().mapTo(table, button.pos())
            actual_row = table.rowAt(pos.y())
            if actual_row >= 0:
                table.blockSignals(True)
                table.removeRow(actual_row)
                table.blockSignals(False)
                self._p6_on_data_changed(category)

    def _p6_on_data_changed(self, category: Any) -> None:
        """Handle p6 on data changed."""
        table = self._p6_table_for(category)
        new_data = []
        for r in range(table.rowCount()):
            d_item = table.item(r, 0)
            a_item = table.item(r, 1)
            if d_item and a_item:
                try:
                    amt = float(a_item.text().replace('$', '').replace(',', ''))
                except:
                    amt = 0.0
                new_data.append({'desc': d_item.text(), 'amount': amt})
        new_data.sort(key=lambda x: x.get('amount', 0.0), reverse=True)
        self.networth_data[category] = new_data
        save_networth_data(self.networth_data)
        self._p6_populate_tables()

    def _p6_update_total(self) -> None:
        """Handle p6 update total."""
        manual_cash = sum((item.get('amount', 0.0) for item in self.networth_data.get('cash', [])))
        manual_pension = sum((item.get('amount', 0.0) for item in self.networth_data.get('pension_insurance', [])))
        manual_debt = sum((item.get('amount', 0.0) for item in self.networth_data.get('debt', [])))
        portfolio_breakdown = self._p6_portfolio_breakdown()
        stock_mv = sum((item['stocks'] for item in portfolio_breakdown))
        options_equity = sum((item['options'] for item in portfolio_breakdown))
        net_worth = manual_cash + manual_pension + stock_mv + options_equity - manual_debt
        positive_color = self.theme_color('accent_positive')
        negative_color = self.theme_color('accent_negative')
        pension_color = '#42a5f5'
        nw_color = positive_color if net_worth >= 0 else negative_color
        summary_lines = [f"Cash: <span style='color: {positive_color};'>${manual_cash:,.2f}</span>"]
        summary_lines.append(f"Pension & Insurance: <span style='color: {pension_color};'>${manual_pension:,.2f}</span>")
        for item in portfolio_breakdown:
            summary_lines.append(f"{item['name']} Stocks: <span style='color: {positive_color};'>${item['stocks']:,.2f}</span>")
            summary_lines.append(f"{item['name']} Options: <span style='color: {(positive_color if item['options'] >= 0 else negative_color)};'>${item['options']:,.2f}</span>")
        summary_lines.append(f"Liabilities: <span style='color: {negative_color};'>-${manual_debt:,.2f}</span>")
        summary_lines.append(f"<b style='font-size: 14px;'>Total: <span style='color: {nw_color};'>${net_worth:,.2f}</span></b>")
        total_summary = '<br/>'.join(summary_lines)
        self.p6_total_summary.setText(total_summary)
        bar_data = []
        asset_idx = 0
        for ci in self.networth_data.get('cash', []):
            amt = ci.get('amount', 0.0)
            if amt > 0:
                bar_data.append((ci.get('desc', 'Cash'), amt, self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]))
                asset_idx += 1
        pension_idx = 0
        for pi in self.networth_data.get('pension_insurance', []):
            amt = pi.get('amount', 0.0)
            if amt > 0:
                bar_data.append((pi.get('desc', 'Pension'), amt, self.PENSION_COLORS[pension_idx % len(self.PENSION_COLORS)]))
                pension_idx += 1
        for item in portfolio_breakdown:
            if item['stocks'] > 0:
                bar_data.append((f"{item['name']} Stocks", item['stocks'], self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]))
                asset_idx += 1
            if item['options'] != 0:
                color = self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)] if item['options'] > 0 else self.DEBT_COLORS[0]
                bar_data.append((f"{item['name']} Options", abs(item['options']), color))
                asset_idx += 1
        debt_idx = 0
        for di in self.networth_data.get('debt', []):
            amt = di.get('amount', 0.0)
            if amt > 0:
                bar_data.append((di.get('desc', 'Debt'), amt, self.DEBT_COLORS[debt_idx % len(self.DEBT_COLORS)]))
                debt_idx += 1
        self.p6_silo_bar.set_data(bar_data)

    def _p6_toggle_scale(self) -> None:
        """Toggle between log and linear scale for the silo bar chart."""
        use_log = self.p6_scale_btn.isChecked()
        self.p6_scale_btn.setText('Log' if use_log else 'Linear')
        self.set_theme_variant(self.p6_scale_btn, 'accent' if use_log else None)
        self.p6_scale_btn.setProperty('bt_checked', 'true' if use_log else 'false')
        self._repolish_widget(self.p6_scale_btn)
        self.p6_silo_bar.use_log = use_log
        self.p6_silo_bar.update()

    def _apply_networth_theme(self) -> None:
        """Refresh Personal Finance theme surfaces."""
        if hasattr(self, 'p6_silo_bar'):
            self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
        if hasattr(self, 'p6_total_summary'):
            self._p6_update_total()
