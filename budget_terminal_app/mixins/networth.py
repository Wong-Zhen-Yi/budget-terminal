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

    def _p6_set_pie_from_amounts(self, pie: Any, amounts: dict[str, Any]) -> None:
        """Convert positive component amounts into pie-chart percentages."""
        positive_amounts = {label: float(value) for label, value in amounts.items() if float(value or 0) > 0}
        total_amount = sum(positive_amounts.values())
        if total_amount > 0:
            pie.set_data({label: value / total_amount * 100 for label, value in positive_amounts.items()})
        else:
            pie.set_data({})

    def init_page6(self) -> None:
        """Build the Personal Finance page UI."""
        layout = QVBoxLayout(self.page6)
        layout.setContentsMargins(10, 2, 10, 10)
        layout.setSpacing(8)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        tables_splitter = QSplitter(Qt.Orientation.Vertical)
        cash_widget = QWidget()
        cash_layout = QVBoxLayout(cash_widget)
        cash_layout.setContentsMargins(0, 0, 0, 2)
        cash_layout.setSpacing(6)
        cash_hdr = QHBoxLayout()
        cash_hdr.setContentsMargins(0, 0, 0, 2)
        cash_hdr.setSpacing(8)
        cash_lbl = QLabel('<b>CASH & ASSETS</b>')
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
        debt_widget = QWidget()
        debt_layout = QVBoxLayout(debt_widget)
        debt_layout.setContentsMargins(0, 2, 0, 0)
        debt_layout.setSpacing(6)
        debt_hdr = QHBoxLayout()
        debt_hdr.setContentsMargins(0, 0, 0, 2)
        debt_hdr.setSpacing(8)
        debt_lbl = QLabel('<b>DEBT & LIABILITIES</b>')
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
        main_splitter.addWidget(tables_splitter)
        visuals_widget = QWidget()
        visuals_layout = QHBoxLayout(visuals_widget)
        visuals_layout.setContentsMargins(5, 0, 0, 0)
        visuals_layout.setSpacing(8)
        total_box = QGroupBox('Total Personal Finance')
        self.set_theme_role(total_box, 'panel')
        total_inner = QVBoxLayout(total_box)
        total_inner.setContentsMargins(6, 6, 6, 6)
        total_inner.setSpacing(4)
        self.p6_total_summary = QLabel('')
        self.p6_total_summary.setStyleSheet('font-size: 12px;')
        self.p6_total_summary.setWordWrap(True)
        total_inner.addWidget(self.p6_total_summary)
        self.p6_total_pie = PieChartWidget()
        self.p6_total_pie.setMinimumHeight(180)
        self.p6_total_pie.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        total_inner.addWidget(self.p6_total_pie, 1)
        visuals_layout.addWidget(total_box)
        liquid_box = QGroupBox('Liquid Personal Finance')
        self.set_theme_role(liquid_box, 'panel')
        liquid_inner = QVBoxLayout(liquid_box)
        liquid_inner.setContentsMargins(6, 6, 6, 6)
        liquid_inner.setSpacing(4)
        self.p6_liquid_summary = QLabel('')
        self.p6_liquid_summary.setStyleSheet('font-size: 12px;')
        self.p6_liquid_summary.setWordWrap(True)
        liquid_inner.addWidget(self.p6_liquid_summary)
        self.p6_liquid_pie = PieChartWidget()
        self.p6_liquid_pie.setMinimumHeight(180)
        self.p6_liquid_pie.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        liquid_inner.addWidget(self.p6_liquid_pie, 1)
        visuals_layout.addWidget(liquid_box)
        main_splitter.addWidget(visuals_widget)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 3)
        layout.addWidget(main_splitter)
        self._p6_populate_tables()

    def _p6_populate_tables(self) -> None:
        """Handle p6 populate tables."""
        for category in ['cash', 'debt']:
            table = self.p6_cash_table if category == 'cash' else self.p6_debt_table
            data_list = self.networth_data.get(category, [])
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
        table = self.p6_cash_table if category == 'cash' else self.p6_debt_table
        table.blockSignals(True)
        self._p6_insert_row_ui(table, category, 'New Item', 0.0)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_remove_row(self, category: Any, row_idx: Any) -> None:
        """Handle p6 remove row."""
        table = self.p6_cash_table if category == 'cash' else self.p6_debt_table
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
        table = self.p6_cash_table if category == 'cash' else self.p6_debt_table
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
        self.networth_data[category] = new_data
        save_networth_data(self.networth_data)
        self._p6_update_total()

    def _p6_update_total(self) -> None:
        """Handle p6 update total."""
        manual_cash = sum((item.get('amount', 0.0) for item in self.networth_data.get('cash', [])))
        manual_debt = sum((item.get('amount', 0.0) for item in self.networth_data.get('debt', [])))
        portfolio_breakdown = self._p6_portfolio_breakdown()
        stock_mv = sum((item['stocks'] for item in portfolio_breakdown))
        options_equity = sum((item['options'] for item in portfolio_breakdown))
        net_worth = manual_cash + stock_mv + options_equity - manual_debt
        liquid_net_worth = manual_cash - manual_debt
        positive_color = self.theme_color('accent_positive')
        negative_color = self.theme_color('accent_negative')
        nw_color = positive_color if net_worth >= 0 else negative_color
        summary_lines = [f"Cash: <span style='color: {positive_color};'>${manual_cash:,.2f}</span>"]
        for item in portfolio_breakdown:
            summary_lines.append(f"{item['name']} Stocks: <span style='color: {positive_color};'>${item['stocks']:,.2f}</span>")
            summary_lines.append(f"{item['name']} Options: <span style='color: {(positive_color if item['options'] >= 0 else negative_color)};'>${item['options']:,.2f}</span>")
        summary_lines.append(f"Liabilities: <span style='color: {negative_color};'>-${manual_debt:,.2f}</span>")
        summary_lines.append(f"<b style='font-size: 14px;'>Total: <span style='color: {nw_color};'>${net_worth:,.2f}</span></b>")
        total_summary = '<br/>'.join(summary_lines)
        self.p6_total_summary.setText(total_summary)
        total_components = {'Cash': manual_cash, 'Debt': manual_debt}
        for item in portfolio_breakdown:
            total_components[f"{item['name']} Stocks"] = item['stocks']
            total_components[f"{item['name']} Options"] = abs(item['options'])
        self._p6_set_pie_from_amounts(self.p6_total_pie, total_components)
        lnw_color = positive_color if liquid_net_worth >= 0 else negative_color
        liquid_summary = f"Assets: <span style='color: {positive_color};'>${manual_cash:,.2f}</span><br/>Liabilities: <span style='color: {negative_color};'>-${manual_debt:,.2f}</span><br/><b style='font-size: 14px;'>Liquid: <span style='color: {lnw_color};'>${liquid_net_worth:,.2f}</span></b>"
        self.p6_liquid_summary.setText(liquid_summary)
        liquid_components = {
            'Cash': manual_cash,
            'Debt': manual_debt,
        }
        self._p6_set_pie_from_amounts(self.p6_liquid_pie, liquid_components)

    def _apply_networth_theme(self) -> None:
        """Refresh Personal Finance theme surfaces."""
        if hasattr(self, 'p6_total_pie'):
            self.p6_total_pie.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        if hasattr(self, 'p6_liquid_pie'):
            self.p6_liquid_pie.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        if hasattr(self, 'p6_total_summary') and hasattr(self, 'p6_liquid_summary'):
            self._p6_update_total()
