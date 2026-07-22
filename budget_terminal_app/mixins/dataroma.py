from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.dataroma import (
    DATAROMA_MOBILE_BASE_URL,
    DataromaWorker,
)


_P22_SOURCE_ROLE = Qt.ItemDataRole.UserRole
_P22_MANAGER_FALLBACKS = (
    ('BRK', 'Warren Buffett - Berkshire Hathaway'),
    ('psc', 'Bill Ackman - Pershing Square Capital Management'),
    ('TGM', 'Chase Coleman - Tiger Global Management'),
    ('GLRE', 'David Einhorn - Greenlight Capital'),
)
_P22_TIMEFRAMES = (
    ('Day', 'd'),
    ('Week', 'w'),
    ('Month', 'm'),
    ('3 Months', 'q'),
    ('6 Months', 'h'),
    ('1 Year', 'y'),
    ('2 Years', 'y2'),
)


class DataromaMixin:
    def init_page22(self) -> None:
        self._p22_thread: QThread | None = None
        self._p22_worker = None
        self._p22_payloads: dict[str, dict[str, Any]] = {}
        self._p22_managers: list[dict[str, Any]] = []
        self._p22_tables: list[QTableWidget] = []
        self._p22_panels: list[QFrame] = []
        self._p22_loaded_once = False

        layout = QVBoxLayout(self.page22)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        toolbar = QFrame()
        self.set_theme_role(toolbar, 'panel')
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 6, 10, 6)
        toolbar_layout.setSpacing(6)
        self._p22_panels.append(toolbar)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title = QLabel('DATAROMA')
        self.set_theme_role(title, 'page_title')
        subtitle = QLabel('Superinvestor portfolios, ownership lookup, and insider transactions.')
        self.set_theme_role(subtitle, 'muted')
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        toolbar_layout.addLayout(title_col)

        toolbar_layout.addStretch()
        self.p22_search_input = QLineEdit()
        self.p22_search_input.setPlaceholderText('Filter loaded rows...')
        self.p22_search_input.setFixedWidth(210)
        self.p22_search_input.textChanged.connect(self._p22_apply_table_filter)
        toolbar_layout.addWidget(self.p22_search_input)

        self.p22_status_lbl = QLabel('Open the page to load DATAROMA data.')
        self.p22_status_lbl.setMinimumWidth(300)
        self.p22_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p22_status_lbl, 'status_muted')
        toolbar_layout.addWidget(self.p22_status_lbl)

        self.p22_refresh_btn = QPushButton('Refresh Current')
        self.p22_refresh_btn.clicked.connect(lambda *_: self._p22_refresh_current(force=True))
        toolbar_layout.addWidget(self.p22_refresh_btn)

        self.p22_export_btn = QPushButton('Export for LLM')
        self.set_theme_variant(self.p22_export_btn, 'accent')
        self.p22_export_btn.clicked.connect(self._p22_export_for_llm)
        toolbar_layout.addWidget(self.p22_export_btn)
        layout.addWidget(toolbar)

        self.p22_tabs = QTabWidget()
        self.p22_tabs.currentChanged.connect(lambda *_: self._p22_apply_table_filter())
        layout.addWidget(self.p22_tabs, 1)

        self._p22_build_overview_tab()
        self._p22_build_ticker_tab()
        self._p22_build_manager_tab()
        self._p22_build_insider_tab()
        self._p22_populate_manager_combo([])

    def _p22_build_overview_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        overview_btn = QPushButton('Refresh Overview')
        overview_btn.clicked.connect(lambda *_: self._p22_refresh_overview(force=True))
        controls.addWidget(overview_btn)
        open_btn = QPushButton('Open DATAROMA')
        open_btn.clicked.connect(lambda *_: webbrowser.open(f'{DATAROMA_MOBILE_BASE_URL}/home.php'))
        controls.addWidget(open_btn)
        controls.addStretch()
        self.p22_overview_buttons = [overview_btn, open_btn]
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.p22_updates_table = self._p22_new_table(['Updated', 'Manager', 'ID'], stretch_columns=(1,))
        splitter.addWidget(self._p22_table_panel('Superinvestor Updates', self.p22_updates_table))
        self.p22_grand_table = self._p22_new_table(
            ['Symbol', 'Stock', '%', 'Owners', 'Hold Price', 'Max %', 'Current', '52w Low', '% Above Low', '52w High'],
            stretch_columns=(1,),
        )
        splitter.addWidget(self._p22_table_panel('Grand Portfolio Leaders', self.p22_grand_table))
        self.p22_managers_table = self._p22_new_table(['Manager', 'Portfolio Value', 'Stocks', 'Top Holdings'], stretch_columns=(0, 3))
        splitter.addWidget(self._p22_table_panel('Superinvestors', self.p22_managers_table))
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        layout.addWidget(splitter, 1)
        self.p22_tabs.addTab(tab, 'Overview')

    def _p22_build_ticker_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        controls.addWidget(QLabel('Ticker'))
        self.p22_ticker_input = QLineEdit('NVDA')
        self.p22_ticker_input.setFixedWidth(110)
        self.p22_ticker_input.returnPressed.connect(lambda: self._p22_refresh_ticker(force=True))
        controls.addWidget(self.p22_ticker_input)
        self.p22_ticker_btn = QPushButton('Load Ticker')
        self.p22_ticker_btn.clicked.connect(lambda *_: self._p22_refresh_ticker(force=True))
        controls.addWidget(self.p22_ticker_btn)
        self.p22_ticker_open_btn = QPushButton('Open Source')
        self.p22_ticker_open_btn.clicked.connect(self._p22_open_ticker_source)
        controls.addWidget(self.p22_ticker_open_btn)
        controls.addStretch()
        layout.addLayout(controls)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p22_ticker_stats_table = self._p22_new_table(['Metric', 'Value'], stretch_columns=(0, 1))
        top_splitter.addWidget(self._p22_table_panel('Ticker Stats', self.p22_ticker_stats_table))
        self.p22_ticker_insider_table = self._p22_new_table(['Type', 'Transactions', 'Total'], stretch_columns=(0,))
        top_splitter.addWidget(self._p22_table_panel('Insider Summary', self.p22_ticker_insider_table))
        top_splitter.setStretchFactor(0, 2)
        top_splitter.setStretchFactor(1, 1)
        layout.addWidget(top_splitter)

        self.p22_ownership_table = self._p22_new_table(
            ['Manager', 'ID', '% Portfolio', 'Activity', 'Shares', 'Value'],
            stretch_columns=(0,),
        )
        layout.addWidget(self._p22_table_panel('Superinvestor Ownership', self.p22_ownership_table), 1)
        self.p22_tabs.addTab(tab, 'Ticker Lookup')

    def _p22_build_manager_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        controls.addWidget(QLabel('Superinvestor'))
        self.p22_manager_combo = QComboBox()
        self.p22_manager_combo.setMinimumWidth(360)
        controls.addWidget(self.p22_manager_combo)
        self.p22_manager_btn = QPushButton('Load Manager')
        self.p22_manager_btn.clicked.connect(lambda *_: self._p22_refresh_manager(force=True))
        controls.addWidget(self.p22_manager_btn)
        self.p22_manager_open_btn = QPushButton('Open Source')
        self.p22_manager_open_btn.clicked.connect(self._p22_open_manager_source)
        controls.addWidget(self.p22_manager_open_btn)
        controls.addStretch()
        self.p22_manager_meta_lbl = QLabel('Choose a manager to load holdings.')
        self.set_theme_role(self.p22_manager_meta_lbl, 'muted')
        controls.addWidget(self.p22_manager_meta_lbl)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p22_manager_holdings_table = self._p22_new_table(
            ['Symbol', 'Company', '%', 'Activity', 'Shares', 'Reported', 'Value', 'Current', '+/-', '52w Low', '52w High'],
            stretch_columns=(1,),
        )
        splitter.addWidget(self._p22_table_panel('Portfolio Holdings', self.p22_manager_holdings_table))

        right = QSplitter(Qt.Orientation.Vertical)
        self.p22_manager_sector_table = self._p22_new_table(['Sector', '% Portfolio'], stretch_columns=(0,))
        right.addWidget(self._p22_table_panel('Sector Mix', self.p22_manager_sector_table))
        self.p22_manager_articles_table = self._p22_new_table(['Date', 'Article / Commentary'], stretch_columns=(1,))
        right.addWidget(self._p22_table_panel('Articles & Commentaries', self.p22_manager_articles_table))
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self.p22_tabs.addTab(tab, 'Manager Lookup')

    def _p22_build_insider_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        controls.addWidget(QLabel('Timeframe'))
        self.p22_insider_timeframe_combo = QComboBox()
        for label, value in _P22_TIMEFRAMES:
            self.p22_insider_timeframe_combo.addItem(label, value)
        controls.addWidget(self.p22_insider_timeframe_combo)
        controls.addWidget(QLabel('Type'))
        self.p22_insider_type_combo = QComboBox()
        self.p22_insider_type_combo.addItem('All', '')
        self.p22_insider_type_combo.addItem('Purchases only', 'purchases')
        self.p22_insider_type_combo.addItem('Sales only', 'sales')
        controls.addWidget(self.p22_insider_type_combo)
        controls.addWidget(QLabel('Min $'))
        self.p22_insider_amount_input = QLineEdit('0')
        self.p22_insider_amount_input.setFixedWidth(90)
        controls.addWidget(self.p22_insider_amount_input)
        controls.addWidget(QLabel('Symbols'))
        self.p22_insider_symbols_input = QLineEdit()
        self.p22_insider_symbols_input.setPlaceholderText('max 15 symbols')
        self.p22_insider_symbols_input.setFixedWidth(150)
        self.p22_insider_symbols_input.returnPressed.connect(lambda: self._p22_refresh_insider(force=True))
        controls.addWidget(self.p22_insider_symbols_input)
        self.p22_insider_10p_check = QCheckBox('10% owners')
        controls.addWidget(self.p22_insider_10p_check)
        self.p22_insider_pref_check = QCheckBox('Preferred')
        controls.addWidget(self.p22_insider_pref_check)
        self.p22_insider_btn = QPushButton('Load Insider')
        self.p22_insider_btn.clicked.connect(lambda *_: self._p22_refresh_insider(force=True))
        controls.addWidget(self.p22_insider_btn)
        controls.addStretch()
        layout.addLayout(controls)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p22_insider_summary_table = self._p22_new_table(['Type', 'Transactions', 'Amount'], stretch_columns=(0,))
        top_splitter.addWidget(self._p22_table_panel('Insider Totals', self.p22_insider_summary_table))
        self.p22_insider_filter_lbl = QLabel('Filters: Day, all transactions.')
        self.p22_insider_filter_lbl.setWordWrap(True)
        self.set_theme_role(self.p22_insider_filter_lbl, 'muted')
        filter_panel = QFrame()
        self.set_theme_role(filter_panel, 'panel')
        filter_layout = QVBoxLayout(filter_panel)
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_title = QLabel('Active Filters')
        self.set_theme_role(filter_title, 'section_title')
        filter_layout.addWidget(filter_title)
        filter_layout.addWidget(self.p22_insider_filter_lbl)
        filter_layout.addStretch()
        self._p22_panels.append(filter_panel)
        top_splitter.addWidget(filter_panel)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        layout.addWidget(top_splitter)

        self.p22_insider_transactions_table = self._p22_new_table(
            ['Filing', 'Symbol', 'Security', 'Reporting Name', 'Relationship', 'Tx Date', 'Type', 'Shares', 'Price', 'Amount', 'D/I', 'SEC'],
            stretch_columns=(2, 3),
        )
        layout.addWidget(self._p22_table_panel('Real Time Insider Transactions', self.p22_insider_transactions_table), 1)
        self.p22_tabs.addTab(tab, 'Insider')

    def _p22_table_panel(self, title: str, table: QTableWidget) -> QFrame:
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 6, 8, 6)
        panel_layout.setSpacing(4)
        label = QLabel(title)
        self.set_theme_role(label, 'section_title')
        panel_layout.addWidget(label)
        panel_layout.addWidget(table, 1)
        self._p22_panels.append(panel)
        return panel

    def _p22_new_table(self, headers: list[str], *, stretch_columns: tuple[int, ...] = ()) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.cellDoubleClicked.connect(lambda row, _col, widget=table: self._p22_open_table_row_source(widget, row))
        header = table.horizontalHeader()
        header.setMinimumHeight(24)
        header.setStretchLastSection(False)
        for column in range(len(headers)):
            if column in stretch_columns:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._p22_tables.append(table)
        return table

    def _p22_on_show(self) -> None:
        if not getattr(self, '_p22_loaded_once', False):
            self._p22_refresh_overview(force=False)

    def _p22_refresh_current(self, *, force: bool = False) -> None:
        current = self.p22_tabs.currentIndex()
        if current == 0:
            self._p22_refresh_overview(force=force)
        elif current == 1:
            self._p22_refresh_ticker(force=force)
        elif current == 2:
            self._p22_refresh_manager(force=force)
        else:
            self._p22_refresh_insider(force=force)

    def _p22_refresh_overview(self, *, force: bool = False) -> None:
        self._p22_start_worker('overview', force=force, message='Loading DATAROMA overview...')

    def _p22_refresh_ticker(self, *, force: bool = False) -> None:
        symbol = str(self.p22_ticker_input.text() or '').upper().strip()
        self.p22_ticker_input.setText(symbol)
        self._p22_start_worker('ticker', force=force, message=f'Loading DATAROMA ownership for {symbol or "ticker"}...', symbol=symbol)

    def _p22_refresh_manager(self, *, force: bool = False) -> None:
        manager_id = str(self.p22_manager_combo.currentData() or '').strip()
        manager_name = str(self.p22_manager_combo.currentText() or manager_id).strip()
        self._p22_start_worker('manager', force=force, message=f'Loading DATAROMA holdings for {manager_name}...', manager_id=manager_id)

    def _p22_refresh_insider(self, *, force: bool = False) -> None:
        self._p22_start_worker(
            'insider',
            force=force,
            message='Loading DATAROMA insider transactions...',
            timeframe=str(self.p22_insider_timeframe_combo.currentData() or 'd'),
            trade_type=str(self.p22_insider_type_combo.currentData() or ''),
            min_amount=str(self.p22_insider_amount_input.text() or '0'),
            symbols=str(self.p22_insider_symbols_input.text() or ''),
            ten_percent=self.p22_insider_10p_check.isChecked(),
            preferred=self.p22_insider_pref_check.isChecked(),
        )

    def _p22_start_worker(self, facet: str, *, force: bool, message: str, **params: Any) -> None:
        if self._p22_thread is not None and self._p22_thread.isRunning():
            self._p22_set_status('DATAROMA request already running...', 'muted')
            return
        self._p22_set_busy(True)
        self._p22_set_status(message, 'muted')
        worker = DataromaWorker(facet, force=force, **params)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._p22_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p22_on_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._p22_on_thread_finished)
        self._p22_thread = thread
        self._p22_worker = worker
        thread.start()

    def _p22_on_data(self, payload: dict[str, Any]) -> None:
        facet = str(payload.get('facet') or '').lower().strip()
        if not facet:
            facet = 'overview'
        self._p22_payloads[facet] = dict(payload)
        if facet == 'overview':
            self._p22_loaded_once = True
            self._p22_render_overview(payload)
        elif facet == 'ticker':
            self._p22_render_ticker(payload)
        elif facet == 'manager':
            self._p22_render_manager(payload)
        elif facet == 'insider':
            self._p22_render_insider(payload)
        warnings = list(payload.get('warnings') or [])
        row_count = self._p22_payload_row_count(payload)
        status = f'DATAROMA {facet} loaded: {row_count} row(s).'
        if payload.get('from_cache'):
            status = f'{status} Cache used.'
        if payload.get('stale'):
            status = f'{status} Stale cache shown.'
        if warnings:
            status = f'{status} {warnings[-1]}'
        self._p22_set_status(status, 'warning' if payload.get('stale') or warnings else 'positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, status, status='warning' if payload.get('stale') or warnings else 'positive')
        self._p22_apply_table_filter()

    def _p22_on_error(self, message: str) -> None:
        self._p22_set_status(f'DATAROMA refresh failed: {message}', 'negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'DATAROMA refresh failed: {message}', status='negative')

    def _p22_on_thread_finished(self) -> None:
        self._p22_set_busy(False)
        if self._p22_worker is not None:
            self._p22_worker.deleteLater()
            self._p22_worker = None
        if self._p22_thread is not None:
            self._p22_thread.deleteLater()
            self._p22_thread = None

    def _p22_render_overview(self, payload: dict[str, Any]) -> None:
        self._p22_set_rows(
            self.p22_updates_table,
            payload.get('updates') or [],
            [('updated', 'updated'), ('manager', 'manager'), ('manager_id', 'manager_id')],
        )
        self._p22_set_rows(
            self.p22_grand_table,
            payload.get('grand_rows') or [],
            [
                ('symbol', 'symbol'),
                ('stock', 'stock'),
                ('portfolio_pct', 'portfolio_pct'),
                ('ownership_count', 'ownership_count'),
                ('hold_price', 'hold_price'),
                ('max_pct', 'max_pct'),
                ('current_price', 'current_price'),
                ('week_52_low', 'week_52_low'),
                ('above_52_low_pct', 'above_52_low_pct'),
                ('week_52_high', 'week_52_high'),
            ],
        )
        managers = [dict(row) for row in list(payload.get('managers') or []) if isinstance(row, dict)]
        self._p22_managers = managers
        self._p22_populate_manager_combo(managers)
        self._p22_set_rows(
            self.p22_managers_table,
            managers,
            [('manager', 'manager'), ('portfolio_value', 'portfolio_value'), ('stock_count', 'stock_count'), ('top_holdings', 'top_holdings')],
        )

    def _p22_render_ticker(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get('symbol') or '').upper().strip()
        if symbol:
            self.p22_ticker_input.setText(symbol)
        stats_rows = [{'metric': 'Company', 'value': payload.get('company') or ''}, {'metric': 'Sector', 'value': payload.get('sector') or ''}]
        for key, value in dict(payload.get('stats') or {}).items():
            stats_rows.append({'metric': key, 'value': value})
        self._p22_set_rows(self.p22_ticker_stats_table, stats_rows, [('metric', 'metric'), ('value', 'value')])
        summary = payload.get('insider_summary') or {}
        self._p22_set_rows(
            self.p22_ticker_insider_table,
            [
                {'type': 'Buys', **dict(summary.get('buys') or {})},
                {'type': 'Sells', **dict(summary.get('sells') or {})},
            ],
            [('type', 'type'), ('transactions', 'transactions'), ('total', 'total')],
        )
        self._p22_set_rows(
            self.p22_ownership_table,
            payload.get('ownership_rows') or [],
            [
                ('manager', 'manager'),
                ('manager_id', 'manager_id'),
                ('portfolio_pct', 'portfolio_pct'),
                ('activity', 'activity'),
                ('shares', 'shares'),
                ('value', 'value'),
            ],
        )

    def _p22_render_manager(self, payload: dict[str, Any]) -> None:
        manager_name = str(payload.get('manager_name') or '').strip()
        meta_parts = [
            part for part in (
                manager_name,
                f"Period: {payload.get('period')}" if payload.get('period') else '',
                f"Portfolio date: {payload.get('portfolio_date')}" if payload.get('portfolio_date') else '',
                f"Stocks: {payload.get('stock_count')}" if payload.get('stock_count') else '',
                f"Value: {payload.get('portfolio_value')}" if payload.get('portfolio_value') else '',
            )
            if part
        ]
        self.p22_manager_meta_lbl.setText(' | '.join(meta_parts) if meta_parts else 'Manager loaded.')
        self._p22_select_manager_id(str(payload.get('manager_id') or ''))
        self._p22_set_rows(
            self.p22_manager_holdings_table,
            payload.get('holdings') or [],
            [
                ('symbol', 'symbol'),
                ('company', 'company'),
                ('portfolio_pct', 'portfolio_pct'),
                ('activity', 'activity'),
                ('shares', 'shares'),
                ('reported_price', 'reported_price'),
                ('value', 'value'),
                ('current_price', 'current_price'),
                ('reported_price_change', 'reported_price_change'),
                ('week_52_low', 'week_52_low'),
                ('week_52_high', 'week_52_high'),
            ],
        )
        self._p22_set_rows(self.p22_manager_sector_table, payload.get('sector_rows') or [], [('sector', 'sector'), ('portfolio_pct', 'portfolio_pct')])
        self._p22_set_rows(self.p22_manager_articles_table, payload.get('articles') or [], [('date', 'date'), ('title', 'title')])

    def _p22_render_insider(self, payload: dict[str, Any]) -> None:
        summary = payload.get('summary') or {}
        self._p22_set_rows(
            self.p22_insider_summary_table,
            [
                {'type': 'Buys', **dict(summary.get('buys') or {})},
                {'type': 'Sells', **dict(summary.get('sells') or {})},
            ],
            [('type', 'type'), ('transactions', 'transactions'), ('amount', 'amount')],
        )
        self._p22_set_rows(
            self.p22_insider_transactions_table,
            payload.get('transactions') or [],
            [
                ('filing', 'filing'),
                ('symbol', 'symbol'),
                ('security', 'security'),
                ('reporting_name', 'reporting_name'),
                ('relationship', 'relationship'),
                ('transaction_date', 'transaction_date'),
                ('trade_type', 'trade_type'),
                ('shares', 'shares'),
                ('price', 'price'),
                ('amount', 'amount'),
                ('direct_indirect', 'direct_indirect'),
                ('sec_url', 'sec_url'),
            ],
        )
        filters = dict(payload.get('filters') or {})
        filter_text = (
            f"Timeframe: {payload.get('timeframe') or 'd'} | Type: {filters.get('trade_type') or 'all'} | "
            f"Min amount: ${filters.get('min_amount') or 0} | Symbols: {filters.get('symbols') or 'all'} | "
            f"10% owners: {'yes' if filters.get('ten_percent') else 'no'} | Preferred: {'yes' if filters.get('preferred') else 'no'}"
        )
        self.p22_insider_filter_lbl.setText(filter_text)

    def _p22_set_rows(self, table: QTableWidget, rows: Any, columns: list[tuple[str, str]]) -> None:
        normalized_rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
        table.setSortingEnabled(False)
        table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            source_url = str(row.get('source_url') or row.get('sec_url') or '').strip()
            for column_index, (_label, key) in enumerate(columns):
                value = self._p22_cell_value(row, key)
                cell_source_url = str(row.get(key) if key.endswith('_url') else source_url or '').strip()
                item = QTableWidgetItem(value)
                item.setData(_P22_SOURCE_ROLE, cell_source_url)
                if cell_source_url:
                    item.setToolTip(cell_source_url)
                if self._p22_is_numeric_key(key):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key in {'symbol', 'manager_id', 'direct_indirect', 'trade_type'}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column_index, item)
        table.setSortingEnabled(True)

    @staticmethod
    def _p22_cell_value(row: dict[str, Any], key: str) -> str:
        value = row.get(key)
        if key == 'top_holdings' and isinstance(value, list):
            return ', '.join(str(item) for item in value if str(item or '').strip())
        if key == 'sec_url':
            return 'SEC' if value else ''
        if isinstance(value, (list, tuple)):
            return ', '.join(str(item) for item in value)
        return str(value or '')

    @staticmethod
    def _p22_is_numeric_key(key: str) -> bool:
        lowered = str(key or '').lower()
        return any(token in lowered for token in ('pct', 'count', 'price', 'value', 'shares', 'amount', 'total'))

    def _p22_apply_table_filter(self) -> None:
        query = str(getattr(self, 'p22_search_input', None).text() if hasattr(self, 'p22_search_input') else '' or '').strip().lower()
        for table in getattr(self, '_p22_tables', []):
            for row in range(table.rowCount()):
                if not query:
                    table.setRowHidden(row, False)
                    continue
                haystack = []
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item is not None:
                        haystack.append(item.text())
                table.setRowHidden(row, query not in ' '.join(haystack).lower())

    def _p22_populate_manager_combo(self, managers: list[dict[str, Any]]) -> None:
        current = str(self.p22_manager_combo.currentData() or 'BRK').strip()
        self.p22_manager_combo.blockSignals(True)
        self.p22_manager_combo.clear()
        source_rows = managers or [
            {'manager_id': manager_id, 'manager': name}
            for manager_id, name in _P22_MANAGER_FALLBACKS
        ]
        for row in source_rows:
            manager_id = str(row.get('manager_id') or '').strip()
            manager = str(row.get('manager') or manager_id).strip()
            if manager_id:
                self.p22_manager_combo.addItem(manager, manager_id)
        self.p22_manager_combo.blockSignals(False)
        self._p22_select_manager_id(current if current else 'BRK')

    def _p22_select_manager_id(self, manager_id: str) -> None:
        target = str(manager_id or '').strip()
        for index in range(self.p22_manager_combo.count()):
            if str(self.p22_manager_combo.itemData(index) or '').strip() == target:
                self.p22_manager_combo.setCurrentIndex(index)
                return

    def _p22_open_table_row_source(self, table: QTableWidget, row: int) -> None:
        for column in range(table.columnCount()):
            item = table.item(row, column)
            url = str(item.data(_P22_SOURCE_ROLE) if item is not None else '' or '').strip()
            if url:
                webbrowser.open(url)
                return
        self._p22_set_status('No source URL is attached to that row.', 'warning')

    def _p22_open_ticker_source(self) -> None:
        payload = self._p22_payloads.get('ticker') or {}
        url = str((payload.get('source_urls') or {}).get('ownership') or '').strip()
        if not url:
            symbol = str(self.p22_ticker_input.text() or 'AAPL').upper().strip() or 'AAPL'
            url = f'{DATAROMA_MOBILE_BASE_URL}/stock.php?sym={symbol}'
        webbrowser.open(url)

    def _p22_open_manager_source(self) -> None:
        payload = self._p22_payloads.get('manager') or {}
        url = str((payload.get('source_urls') or {}).get('holdings') or '').strip()
        if not url:
            manager_id = str(self.p22_manager_combo.currentData() or 'BRK').strip() or 'BRK'
            url = f'{DATAROMA_MOBILE_BASE_URL}/holdings.php?m={manager_id}'
        webbrowser.open(url)

    def _p22_set_busy(self, busy: bool) -> None:
        for button in (
            getattr(self, 'p22_refresh_btn', None),
            getattr(self, 'p22_ticker_btn', None),
            getattr(self, 'p22_manager_btn', None),
            getattr(self, 'p22_insider_btn', None),
        ):
            if button is not None:
                button.setEnabled(not busy)

    def _p22_set_status(self, text: Any, status: str = 'muted') -> None:
        self.set_status_text(self.p22_status_lbl, str(text or ''), status=status)

    @staticmethod
    def _p22_payload_row_count(payload: dict[str, Any]) -> int:
        count = 0
        for key in ('updates', 'latest_insider_buys', 'managers', 'grand_rows', 'ownership_rows', 'holdings', 'sector_rows', 'articles', 'transactions'):
            value = payload.get(key)
            if isinstance(value, list):
                count += len(value)
        return count

    def _p22_export_for_llm(self) -> None:
        if not self._p22_payloads:
            self._p22_set_status('Load DATAROMA data before exporting.', 'warning')
            return
        text = self._p22_build_export_text()
        QApplication.clipboard().setText(text)
        self._p22_set_status('Copied DATAROMA export to clipboard.', 'positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, 'DATAROMA export copied to clipboard.', status='positive')

    def _p22_build_export_text(self) -> str:
        lines = [
            '# DATAROMA Export',
            f'Generated: {datetime.datetime.now().isoformat(timespec="seconds")}',
            '',
            'DATAROMA data is extracted from financial filings and insider forms. Portfolio trades are delayed and may have occurred at any time during the reporting quarter. Use this as an informational starting point, cite DATAROMA, and verify independently.',
            '',
        ]
        overview = self._p22_payloads.get('overview') or {}
        ticker = self._p22_payloads.get('ticker') or {}
        manager = self._p22_payloads.get('manager') or {}
        insider = self._p22_payloads.get('insider') or {}

        if overview:
            summary = overview.get('grand_summary') or {}
            lines.extend(['## Overview', f"Fetched: {overview.get('fetched_at') or ''}"])
            if summary:
                lines.append(f"Grand Portfolio: {summary.get('total_stocks', '')} stocks; value {summary.get('portfolio_value', '')}.")
            self._p22_append_sources(lines, overview)
            self._p22_append_rows(lines, 'Superinvestor Updates', overview.get('updates') or [], ['updated', 'manager', 'manager_id', 'source_url'])
            self._p22_append_rows(lines, 'Grand Portfolio Leaders', overview.get('grand_rows') or [], ['symbol', 'stock', 'portfolio_pct', 'ownership_count', 'hold_price', 'max_pct', 'current_price', 'source_url'])
            self._p22_append_rows(lines, 'Superinvestors', overview.get('managers') or [], ['manager', 'manager_id', 'portfolio_value', 'stock_count', 'top_holdings', 'source_url'])

        if ticker:
            lines.extend(['', '## Ticker Lookup', f"{ticker.get('company', '')} ({ticker.get('symbol', '')})", f"Sector: {ticker.get('sector', '')}"])
            self._p22_append_sources(lines, ticker)
            stats = [{'metric': key, 'value': value} for key, value in dict(ticker.get('stats') or {}).items()]
            self._p22_append_rows(lines, 'Ticker Stats', stats, ['metric', 'value'])
            self._p22_append_rows(lines, 'Ownership Rows', ticker.get('ownership_rows') or [], ['manager', 'manager_id', 'portfolio_pct', 'activity', 'shares', 'value', 'source_url'])

        if manager:
            lines.extend([
                '',
                '## Manager Lookup',
                str(manager.get('manager_name') or ''),
                f"Period: {manager.get('period', '')}; portfolio date: {manager.get('portfolio_date', '')}; stocks: {manager.get('stock_count', '')}; value: {manager.get('portfolio_value', '')}",
            ])
            self._p22_append_sources(lines, manager)
            self._p22_append_rows(lines, 'Holdings', manager.get('holdings') or [], ['symbol', 'company', 'portfolio_pct', 'activity', 'shares', 'reported_price', 'value', 'current_price', 'reported_price_change', 'source_url'])
            self._p22_append_rows(lines, 'Sector Mix', manager.get('sector_rows') or [], ['sector', 'portfolio_pct'])
            self._p22_append_rows(lines, 'Articles', manager.get('articles') or [], ['date', 'title', 'source_url'])

        if insider:
            lines.extend(['', '## Insider Transactions', f"Timeframe: {insider.get('timeframe', '')}"])
            self._p22_append_sources(lines, insider)
            summary = insider.get('summary') or {}
            self._p22_append_rows(
                lines,
                'Insider Summary',
                [{'type': 'Buys', **dict(summary.get('buys') or {})}, {'type': 'Sells', **dict(summary.get('sells') or {})}],
                ['type', 'transactions', 'amount'],
            )
            self._p22_append_rows(lines, 'Transactions', insider.get('transactions') or [], ['filing', 'symbol', 'security', 'reporting_name', 'relationship', 'transaction_date', 'trade_type', 'shares', 'price', 'amount', 'direct_indirect', 'sec_url'])
        return '\n'.join(lines).strip() + '\n'

    @staticmethod
    def _p22_append_sources(lines: list[str], payload: dict[str, Any]) -> None:
        urls = payload.get('source_urls') or {}
        if not isinstance(urls, dict) or not urls:
            return
        lines.append('Sources:')
        for label, url in urls.items():
            lines.append(f'- {label}: {url}')
        lines.append('')

    def _p22_append_rows(self, lines: list[str], title: str, rows: Any, keys: list[str]) -> None:
        normalized = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
        lines.extend(['', f'### {title}'])
        if not normalized:
            lines.append('(no loaded rows)')
            return
        lines.append(' | '.join(keys))
        lines.append(' | '.join(['---'] * len(keys)))
        for row in normalized:
            values = [self._p22_export_value(row.get(key)) for key in keys]
            lines.append(' | '.join(values))

    @staticmethod
    def _p22_export_value(value: Any) -> str:
        if isinstance(value, list):
            text = ', '.join(str(item) for item in value)
        else:
            text = str(value or '')
        return text.replace('|', '/').replace('\n', ' ').strip()

    def _apply_dataroma_theme(self) -> None:
        table_style = (
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        for table in getattr(self, '_p22_tables', []):
            table.setStyleSheet(table_style)
        for label_name in ('p22_status_lbl', 'p22_manager_meta_lbl', 'p22_insider_filter_lbl'):
            label = getattr(self, label_name, None)
            if label is not None:
                status = label.property('bt_status') or 'muted'
                if label_name == 'p22_status_lbl':
                    self.set_status_text(label, label.text(), status=status)
                else:
                    label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        if hasattr(self, 'p22_search_input'):
            self.p22_search_input.setStyleSheet(
                f'background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
                f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 5px 8px;'
            )
