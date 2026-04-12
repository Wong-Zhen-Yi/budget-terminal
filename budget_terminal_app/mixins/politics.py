from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.workers.politics import PoliticsExportWorker, PoliticsWorker

PARTY_COLORS = {'Democrat': '#2196f3', 'Republican': '#f44336', 'Independent': '#9e9e9e', 'Unknown': '#666666'}
TRADE_COLORS = {'Purchase': '#00c853', 'Sale (Full)': '#ff1744', 'Sale (Partial)': '#ff5252', 'Exchange': '#ffc107'}


class PoliticsMixin:

    def init_page15(self) -> None:
        self._p15_thread: QThread | None = None
        self._p15_export_thread: QThread | None = None
        self._p15_all_trades: list[dict] = []
        self._p15_current_page: int = 1

        layout = QVBoxLayout(self.page15)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        self._p15_scroll = scroll
        self._p15_container = container

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>Congressional Stock Trades</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        self.p15_export_btn = QPushButton('Export for LLM')
        self.p15_export_btn.setFixedWidth(120)
        self.p15_export_btn.clicked.connect(self._p15_export_trades)
        title_row.addWidget(self.p15_export_btn)
        self.p15_refresh_btn = QPushButton('Refresh')
        self.p15_refresh_btn.setFixedWidth(90)
        self.p15_refresh_btn.clicked.connect(lambda: self._p15_load_page(self._p15_current_page, force=True))
        title_row.addWidget(self.p15_refresh_btn)
        container_layout.addLayout(title_row)

        # Status
        self.p15_status_lbl = QLabel('')
        self.set_theme_role(self.p15_status_lbl, 'status_muted')
        container_layout.addWidget(self.p15_status_lbl)

        # Filter row
        filter_row = QHBoxLayout()
        self.p15_politician_combo = QComboBox()
        self.p15_politician_combo.setFixedWidth(220)
        self.p15_politician_combo.addItem('All')
        filter_row.addWidget(self.p15_politician_combo)

        self.p15_search_ticker = QLineEdit()
        self.p15_search_ticker.setPlaceholderText('Search ticker...')
        self.p15_search_ticker.setFixedWidth(120)
        filter_row.addWidget(self.p15_search_ticker)

        self.p15_chamber_combo = QComboBox()
        self.p15_chamber_combo.addItems(['All', 'House', 'Senate'])
        self.p15_chamber_combo.setFixedWidth(100)
        filter_row.addWidget(self.p15_chamber_combo)

        self.p15_party_combo = QComboBox()
        self.p15_party_combo.addItems(['All', 'Democrat', 'Republican', 'Independent'])
        self.p15_party_combo.setFixedWidth(120)
        filter_row.addWidget(self.p15_party_combo)

        self.p15_type_combo = QComboBox()
        self.p15_type_combo.addItems(['All', 'Purchase', 'Sale (Full)', 'Sale (Partial)', 'Exchange'])
        self.p15_type_combo.setFixedWidth(120)
        filter_row.addWidget(self.p15_type_combo)

        self.p15_theme_combo = QComboBox()
        self.p15_theme_combo.setFixedWidth(150)
        self.p15_theme_combo.addItem('All')
        filter_row.addWidget(self.p15_theme_combo)

        filter_btn = QPushButton('Apply')
        filter_btn.setFixedWidth(70)
        filter_btn.clicked.connect(self._p15_apply_filters)
        filter_row.addWidget(filter_btn)
        filter_row.addStretch()
        container_layout.addLayout(filter_row)

        # Connect combo selection and enter key to filter
        self.p15_politician_combo.activated.connect(lambda _: self._p15_apply_filters())
        self.p15_theme_combo.activated.connect(lambda _: self._p15_apply_filters())
        self.p15_search_ticker.returnPressed.connect(self._p15_apply_filters)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: trades table
        self.p15_trades_table = QTableWidget()
        self.p15_trades_table.setColumnCount(8)
        self.p15_trades_table.setHorizontalHeaderLabels(
            ['Politician', 'Chamber', 'Party', 'Ticker', 'Type', 'Amount', 'Tx Date', 'Filed']
        )
        self.p15_trades_table.setAlternatingRowColors(True)
        self.p15_trades_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p15_trades_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p15_configure_trades_table_widths()
        self.p15_trades_table.setSortingEnabled(True)
        self.p15_trades_table.cellDoubleClicked.connect(self._p15_on_ticker_dblclick)
        splitter.addWidget(self.p15_trades_table)

        # Right: summary panel
        right_panel = QWidget()
        right_layout = QHBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(8)

        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)

        theme_panel = QWidget()
        theme_layout = QVBoxLayout(theme_panel)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setSpacing(8)

        # Theme flow group
        theme_group = QGroupBox('Market Flow by Theme')
        theme_group_layout = QVBoxLayout(theme_group)
        self.p15_theme_flow_table = QTableWidget()
        self.p15_theme_flow_table.setColumnCount(4)
        self.p15_theme_flow_table.setHorizontalHeaderLabels(['Theme', 'Buy $', 'Sell $', 'Net $'])
        self.p15_theme_flow_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p15_theme_flow_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p15_configure_theme_flow_table_widths()
        self.p15_theme_flow_table.cellDoubleClicked.connect(self._p15_on_theme_dblclick)
        theme_group_layout.addWidget(self.p15_theme_flow_table, 1)
        theme_layout.addWidget(theme_group, 3)

        flow_chart_group = QGroupBox('Flow Breakdown')
        flow_chart_layout = QVBoxLayout(flow_chart_group)
        self.p15_flow_pie = PieChartWidget()
        self.p15_flow_pie.setMinimumHeight(220)
        self.p15_flow_pie.set_donut(True, hole_ratio=0.58)
        flow_chart_layout.addWidget(self.p15_flow_pie, 1)
        theme_layout.addWidget(flow_chart_group, 2)

        # Top tickers group
        tickers_group = QGroupBox('Most Traded Tickers')
        tickers_group_layout = QVBoxLayout(tickers_group)
        self.p15_top_tickers_table = QTableWidget()
        self.p15_top_tickers_table.setColumnCount(2)
        self.p15_top_tickers_table.setHorizontalHeaderLabels(['Ticker', 'Trades'])
        self.p15_top_tickers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p15_top_tickers_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p15_configure_summary_table_widths(self.p15_top_tickers_table)
        self.p15_top_tickers_table.cellDoubleClicked.connect(self._p15_on_summary_ticker_dblclick)
        tickers_group_layout.addWidget(self.p15_top_tickers_table, 1)
        summary_layout.addWidget(tickers_group, 1)

        # Top politicians group
        politicians_group = QGroupBox('Most Active Politicians')
        politicians_group_layout = QVBoxLayout(politicians_group)
        self.p15_top_politicians_table = QTableWidget()
        self.p15_top_politicians_table.setColumnCount(2)
        self.p15_top_politicians_table.setHorizontalHeaderLabels(['Politician', 'Trades'])
        self.p15_top_politicians_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p15_top_politicians_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p15_configure_summary_table_widths(self.p15_top_politicians_table)
        self.p15_top_politicians_table.cellDoubleClicked.connect(self._p15_on_summary_politician_dblclick)
        politicians_group_layout.addWidget(self.p15_top_politicians_table, 1)
        summary_layout.addWidget(politicians_group, 1)

        right_layout.addWidget(summary_panel, 2)
        right_layout.addWidget(theme_panel, 3)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        container_layout.addWidget(splitter, 1)

        # Page navigation row
        page_row = QHBoxLayout()
        page_row.addStretch()
        self.p15_btn_prev = QPushButton('< Prev')
        self.p15_btn_prev.setFixedWidth(80)
        self.p15_btn_prev.clicked.connect(self._p15_prev_page)
        page_row.addWidget(self.p15_btn_prev)

        self.p15_page_label = QLabel('Page 1')
        self.p15_page_label.setFixedWidth(60)
        self.p15_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_row.addWidget(self.p15_page_label)

        self.p15_btn_next = QPushButton('Next >')
        self.p15_btn_next.setFixedWidth(80)
        self.p15_btn_next.clicked.connect(self._p15_next_page)
        page_row.addWidget(self.p15_btn_next)
        page_row.addStretch()
        container_layout.addLayout(page_row)

        self._p15_update_page_buttons()

    # -- Page navigation --

    def _p15_prev_page(self) -> None:
        if self._p15_current_page > 1:
            self._p15_load_page(self._p15_current_page - 1)

    def _p15_next_page(self) -> None:
        self._p15_load_page(self._p15_current_page + 1)

    def _p15_update_page_buttons(self) -> None:
        self.p15_btn_prev.setEnabled(self._p15_current_page > 1)
        self.p15_btn_next.setEnabled(True)
        self.p15_page_label.setText(f'Page {self._p15_current_page}')

    def _p15_configure_trades_table_widths(self) -> None:
        header = self.p15_trades_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self.p15_trades_table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    def _p15_fit_trades_table_to_data(self) -> None:
        table = self.p15_trades_table
        if table.columnCount() == 0:
            return
        self._p15_configure_trades_table_widths()
        for col in range(1, table.columnCount()):
            table.resizeColumnToContents(col)

    def _p15_configure_summary_table_widths(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def _p15_fit_summary_table_to_data(self, table: QTableWidget) -> None:
        if table.columnCount() < 2:
            return
        self._p15_configure_summary_table_widths(table)
        table.resizeColumnToContents(1)

    def _p15_configure_theme_flow_table_widths(self) -> None:
        header = self.p15_theme_flow_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self.p15_theme_flow_table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    def _p15_fit_theme_flow_table_to_data(self) -> None:
        table = self.p15_theme_flow_table
        if table.columnCount() == 0:
            return
        self._p15_configure_theme_flow_table_widths()
        for col in range(1, table.columnCount()):
            table.resizeColumnToContents(col)

    # -- Data fetching --

    def _p15_refresh(self, force: bool = False) -> None:
        self._p15_load_page(1, force=force)

    def _p15_load_page(self, page: int, force: bool = False) -> None:
        if self._p15_thread is not None and self._p15_thread.isRunning():
            return
        self._p15_current_page = page
        self._p15_update_page_buttons()
        self.p15_refresh_btn.setEnabled(False)
        self.p15_btn_prev.setEnabled(False)
        self.p15_btn_next.setEnabled(False)
        self.set_status_text(self.p15_status_lbl, f'Fetching page {page}...', status='muted')
        worker = PoliticsWorker(page=page, force_refresh=force)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._p15_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p15_on_error)
        worker.error.connect(thread.quit)
        self._p15_thread = thread
        self._p15_worker = worker
        thread.start()

    def _p15_on_data(self, result: dict) -> None:
        self.p15_refresh_btn.setEnabled(True)
        self._p15_all_trades = result.get('trades', [])
        count = len(self._p15_all_trades)
        self.set_status_text(self.p15_status_lbl,
            f'Page {self._p15_current_page} — {count} trades',
            status='positive')
        self._p15_populate_politician_combo()
        self._p15_populate_theme_combo()
        self._p15_apply_filters()
        self._p15_update_page_buttons()
        # Disable next if server returned fewer than a full page
        if result.get('raw_count', count) < 100:
            self.p15_btn_next.setEnabled(False)

    def _p15_populate_politician_combo(self) -> None:
        current = self.p15_politician_combo.currentText()
        self.p15_politician_combo.clear()
        self.p15_politician_combo.addItem('All')
        names = sorted({t.get('politician', '') for t in self._p15_all_trades if t.get('politician')})
        self.p15_politician_combo.addItems(names)
        idx = self.p15_politician_combo.findText(current)
        self.p15_politician_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _p15_populate_theme_combo(self) -> None:
        current = self.p15_theme_combo.currentText()
        self.p15_theme_combo.clear()
        self.p15_theme_combo.addItem('All')
        themes = sorted({
            str(t.get('theme', '') or 'Other').strip() or 'Other'
            for t in self._p15_all_trades
        }, key=lambda theme: (theme == 'Other', theme))
        self.p15_theme_combo.addItems(themes)
        idx = self.p15_theme_combo.findText(current)
        self.p15_theme_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _p15_on_error(self, msg: str) -> None:
        self.p15_refresh_btn.setEnabled(True)
        self._p15_update_page_buttons()
        self.set_status_text(self.p15_status_lbl, f'Error: {msg}', status='negative')

    # -- Export --

    def _p15_export_trades(self) -> None:
        if self._p15_export_thread is not None and self._p15_export_thread.isRunning():
            return
        self.p15_export_btn.setEnabled(False)
        self.set_status_text(self.p15_status_lbl, 'Exporting pages 1-5...', status='muted')
        worker = PoliticsExportWorker(pages=5)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda p: self.set_status_text(
            self.p15_status_lbl, f'Fetching page {p}/5...', status='muted'))
        worker.finished.connect(self._p15_on_export_done)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p15_on_export_error)
        worker.error.connect(thread.quit)
        self._p15_export_thread = thread
        self._p15_export_worker = worker
        thread.start()

    def _p15_on_export_done(self, trades: list) -> None:
        self.p15_export_btn.setEnabled(True)
        if not trades:
            self.set_status_text(self.p15_status_lbl, 'No trades to export', status='warning')
            return
        lines = ['Politician | Chamber | Party | Ticker | Type | Amount | Tx Date | Filed']
        lines.append('-' * 90)
        for t in trades:
            lines.append(
                f"{t.get('politician', '')} | {t.get('chamber', '')} | "
                f"{t.get('party', '')} | {t.get('ticker', '')} | "
                f"{t.get('trade_type', '')} | {t.get('amount', '')} | "
                f"{t.get('transaction_date', '')} | {t.get('disclosure_date', '')}"
            )
        text = '\n'.join(lines)
        QApplication.clipboard().setText(text)
        self.set_status_text(self.p15_status_lbl,
            f'Copied {len(trades)} trades to clipboard', status='positive')

    def _p15_on_export_error(self, msg: str) -> None:
        self.p15_export_btn.setEnabled(True)
        self.set_status_text(self.p15_status_lbl, f'Export error: {msg}', status='negative')

    def _p15_apply_filters(self) -> None:
        politician_q = self.p15_politician_combo.currentText().strip()
        ticker_q = self.p15_search_ticker.text().strip().upper()
        chamber = self.p15_chamber_combo.currentText()
        party = self.p15_party_combo.currentText()
        trade_type = self.p15_type_combo.currentText()
        theme = self.p15_theme_combo.currentText().strip()

        filtered = []
        for t in self._p15_all_trades:
            if politician_q != 'All' and t.get('politician', '') != politician_q:
                continue
            if ticker_q and ticker_q not in t.get('ticker', '').upper():
                continue
            if chamber != 'All' and t.get('chamber') != chamber:
                continue
            if party != 'All' and t.get('party') != party:
                continue
            if trade_type != 'All' and t.get('trade_type') != trade_type:
                continue
            if theme != 'All' and (str(t.get('theme', '') or 'Other').strip() or 'Other') != theme:
                continue
            filtered.append(t)
        self._p15_populate_trades_table(filtered)
        self._p15_populate_summaries(filtered)

    def _p15_populate_trades_table(self, trades: list[dict]) -> None:
        self.p15_trades_table.setSortingEnabled(False)
        self.p15_trades_table.setRowCount(len(trades))
        for r, t in enumerate(trades):
            self.p15_trades_table.setItem(r, 0, QTableWidgetItem(t.get('politician', '')))
            self.p15_trades_table.setItem(r, 1, QTableWidgetItem(t.get('chamber', '')))

            party = t.get('party', 'Unknown')
            party_item = QTableWidgetItem(party)
            party_item.setForeground(QColor(PARTY_COLORS.get(party, '#666666')))
            self.p15_trades_table.setItem(r, 2, party_item)

            ticker_item = QTableWidgetItem(t.get('ticker', ''))
            ticker_item.setForeground(QColor('#42a5f5'))
            self.p15_trades_table.setItem(r, 3, ticker_item)

            trade_type = t.get('trade_type', '')
            type_item = QTableWidgetItem(trade_type)
            type_item.setForeground(QColor(TRADE_COLORS.get(trade_type, '#888888')))
            self.p15_trades_table.setItem(r, 4, type_item)

            self.p15_trades_table.setItem(r, 5, QTableWidgetItem(t.get('amount', '')))
            self.p15_trades_table.setItem(r, 6, QTableWidgetItem(t.get('transaction_date', '')))
            self.p15_trades_table.setItem(r, 7, QTableWidgetItem(t.get('disclosure_date', '')))
        self._p15_fit_trades_table_to_data()
        self.p15_trades_table.setSortingEnabled(True)

    @staticmethod
    def _p15_top_counts(trades: list[dict], key: str, limit: int) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for trade in trades:
            value = str(trade.get(key, '') or '').strip()
            if value and value != 'Unknown':
                counts[value] = counts.get(value, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return ranked[:limit]

    @staticmethod
    def _p15_format_amount(value: int | float, *, signed: bool = False) -> str:
        amount = abs(float(value))
        if amount >= 1_000_000:
            body = f'${amount / 1_000_000:.1f}M'
        elif amount >= 1_000:
            body = f'${amount / 1_000:.0f}K'
        else:
            body = f'${amount:,.0f}'
        if not signed or value == 0:
            return body
        return f'+{body}' if value > 0 else f'-{body}'

    def _p15_build_theme_flow_rows(self, trades: list[dict]) -> list[tuple[str, int, int, int]]:
        flow_by_theme: dict[str, dict[str, int]] = {}
        for trade in trades:
            theme = str(trade.get('theme', '') or 'Other').strip() or 'Other'
            entry = flow_by_theme.setdefault(theme, {'buy': 0, 'sell': 0})
            amount = int(trade.get('amount_value') or 0)
            trade_type = str(trade.get('trade_type', '') or '')
            if trade_type == 'Purchase':
                entry['buy'] += amount
            elif trade_type in ('Sale (Full)', 'Sale (Partial)'):
                entry['sell'] += amount
        rows = []
        for theme, totals in flow_by_theme.items():
            buy_total = totals['buy']
            sell_total = totals['sell']
            rows.append((theme, buy_total, sell_total, buy_total - sell_total))
        rows.sort(key=lambda item: (-(item[1] + item[2]), -abs(item[3]), item[0]))
        return rows

    def _p15_update_flow_chart(self, theme_rows: list[tuple[str, int, int, int]]) -> None:
        ranked = sorted(
            ((theme, buy_total + sell_total) for theme, buy_total, sell_total, _net_total in theme_rows),
            key=lambda item: (-item[1], item[0]),
        )
        ranked = [(theme, gross_total) for theme, gross_total in ranked if gross_total > 0]
        total_flow = sum(gross_total for _theme, gross_total in ranked)
        if total_flow <= 0:
            self.p15_flow_pie.set_data({})
            self.p15_flow_pie.set_center_text('No Flow', 'Filtered')
            return
        visible = ranked[:6]
        other_total = sum(gross_total for _theme, gross_total in ranked[6:])
        if other_total > 0:
            visible.append(('Other', other_total))
        self.p15_flow_pie.set_data({theme: gross_total for theme, gross_total in visible})
        self.p15_flow_pie.set_center_text(self._p15_format_amount(total_flow), 'Gross Flow')

    def _p15_populate_summaries(self, trades: list[dict]) -> None:
        top_tickers = self._p15_top_counts(trades, 'ticker', 15)
        top_politicians = self._p15_top_counts(trades, 'politician', 15)
        self.p15_top_tickers_table.setRowCount(len(top_tickers))
        for r, (name, count) in enumerate(top_tickers):
            item = QTableWidgetItem(name)
            item.setForeground(QColor('#42a5f5'))
            self.p15_top_tickers_table.setItem(r, 0, item)
            self.p15_top_tickers_table.setItem(r, 1, QTableWidgetItem(str(count)))
        self._p15_fit_summary_table_to_data(self.p15_top_tickers_table)

        self.p15_top_politicians_table.setRowCount(len(top_politicians))
        for r, (name, count) in enumerate(top_politicians):
            self.p15_top_politicians_table.setItem(r, 0, QTableWidgetItem(name))
            self.p15_top_politicians_table.setItem(r, 1, QTableWidgetItem(str(count)))
        self._p15_fit_summary_table_to_data(self.p15_top_politicians_table)

        theme_rows = self._p15_build_theme_flow_rows(trades)
        self.p15_theme_flow_table.setRowCount(len(theme_rows))
        for r, (theme, buy_total, sell_total, net_total) in enumerate(theme_rows):
            self.p15_theme_flow_table.setItem(r, 0, QTableWidgetItem(theme))
            self.p15_theme_flow_table.setItem(r, 1, QTableWidgetItem(self._p15_format_amount(buy_total)))
            self.p15_theme_flow_table.setItem(r, 2, QTableWidgetItem(self._p15_format_amount(sell_total)))
            net_item = QTableWidgetItem(self._p15_format_amount(net_total, signed=True))
            if net_total > 0:
                net_item.setForeground(QColor(CLR_UP))
            elif net_total < 0:
                net_item.setForeground(QColor(CLR_DOWN))
            self.p15_theme_flow_table.setItem(r, 3, net_item)
        self._p15_fit_theme_flow_table_to_data()
        self._p15_update_flow_chart(theme_rows)

    def _p15_on_ticker_dblclick(self, row: int, col: int) -> None:
        ticker_item = self.p15_trades_table.item(row, 3)
        if ticker_item and ticker_item.text():
            self._p15_navigate_to_charts(ticker_item.text())

    def _p15_on_summary_ticker_dblclick(self, row: int, col: int) -> None:
        item = self.p15_top_tickers_table.item(row, 0)
        if item and item.text():
            self._p15_navigate_to_charts(item.text())

    def _p15_on_theme_dblclick(self, row: int, col: int) -> None:
        item = self.p15_theme_flow_table.item(row, 0)
        if item and item.text():
            idx = self.p15_theme_combo.findText(item.text())
            if idx >= 0:
                self.p15_theme_combo.setCurrentIndex(idx)
            self._p15_apply_filters()

    def _p15_on_summary_politician_dblclick(self, row: int, col: int) -> None:
        item = self.p15_top_politicians_table.item(row, 0)
        if item:
            idx = self.p15_politician_combo.findText(item.text())
            if idx >= 0:
                self.p15_politician_combo.setCurrentIndex(idx)
            else:
                self.p15_politician_combo.setCurrentText(item.text())
            self._p15_apply_filters()

    def _p15_navigate_to_charts(self, ticker: str) -> None:
        ticker = str(ticker or '').upper().strip()
        if not ticker:
            return
        self.p10_symbol = ticker
        if isinstance(getattr(self, 'chart_page_state', None), dict):
            self.chart_page_state = {
                **self.chart_page_state,
                'symbol': ticker,
            }
        page_index = self.stacked_widget.indexOf(self.page10) if hasattr(self, 'stacked_widget') and hasattr(self, 'page10') else 8
        target_index = page_index if page_index >= 0 else 8
        page_ready = self._page_initialized(index=target_index)
        self.switch_page(target_index)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(ticker)
        if page_ready and hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()

    def _apply_politics_theme(self) -> None:
        bg = self.theme_color('panel_background')
        border = self.theme_color('panel_border')
        text = self.theme_color('text_primary')
        muted = self.theme_color('text_muted')
        style = f'background-color: {bg}; color: {text}; border: 1px solid {border};'
        for table in (self.p15_trades_table, self.p15_theme_flow_table, self.p15_top_tickers_table, self.p15_top_politicians_table):
            table.setStyleSheet(style)
        self.p15_flow_pie.set_theme(self.theme_pie_palette(), text)
        self.p15_search_ticker.setStyleSheet(f'background-color: {bg}; color: {text}; border: 1px solid {border}; padding: 4px;')
        self._p15_scroll.setStyleSheet(f'QScrollArea {{ background: transparent; border: none; }}')
