from __future__ import annotations
from typing import Any
from ..compat import *

class PortfolioSetupMixin:

    def _p4_get_portfolio_slots(self) -> Any:
        """Return a normalized list of up to 3 portfolio slot dicts."""
        slots = []
        raw = getattr(self, 'portfolio_slots', None)
        if isinstance(raw, list):
            for index, entry in enumerate(raw[:3]):
                if isinstance(entry, dict):
                    slots.append({
                        'id': int(entry.get('id', index)),
                        'name': str(entry.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                    })
        for index in range(len(slots), 3):
            slots.append({'id': index, 'name': f'Portfolio {index + 1}'})
        return slots

    def _p4_get_active_portfolio_index(self) -> int:
        """Return the selected portfolio index for the page-4 workspace."""
        value = getattr(self, 'active_portfolio_index', 0)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return min(max(value, 0), 2)

    def _p4_get_main_portfolio_index(self) -> int:
        """Return the app-wide main portfolio index."""
        for attr_name in ('main_portfolio_index', 'primary_portfolio_index'):
            value = getattr(self, attr_name, None)
            if value is None:
                continue
            try:
                return min(max(int(value), 0), 2)
            except (TypeError, ValueError):
                return 0
        return self._p4_get_active_portfolio_index()

    def _p4_portfolio_name(self, index: int) -> str:
        """Resolve a portfolio display name."""
        slots = self._p4_get_portfolio_slots()
        if 0 <= index < len(slots):
            return str(slots[index].get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}')
        return f'Portfolio {index + 1}'

    def _p4_apply_fallback_portfolio_identity(self, index: int, *, make_main: bool=False) -> None:
        """Update local identity state when shared runtime helpers are unavailable."""
        index = min(max(int(index), 0), 2)
        self.active_portfolio_index = index
        slots = self._p4_get_portfolio_slots()
        self.portfolio_slots = slots
        if make_main:
            self.main_portfolio_index = index

    def _p4_refresh_portfolio_selector(self) -> None:
        """Refresh portfolio tab labels and action copy."""
        if not hasattr(self, 'p4_portfolio_tabs'):
            return
        slots = self._p4_get_portfolio_slots()
        active_index = self._p4_get_active_portfolio_index()
        main_index = self._p4_get_main_portfolio_index()
        self.p4_portfolio_tabs.blockSignals(True)
        while self.p4_portfolio_tabs.count() < len(slots):
            self.p4_portfolio_tabs.addTab(QWidget(), '')
        for index, slot in enumerate(slots):
            label = str(slot.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}')
            if index == main_index:
                label = f'{label} *'
            self.p4_portfolio_tabs.setTabText(index, label)
        self.p4_portfolio_tabs.setCurrentIndex(active_index)
        self.p4_portfolio_tabs.blockSignals(False)
        if hasattr(self, 'p4_main_portfolio_label'):
            self.p4_main_portfolio_label.setText(f'Main Portfolio: {self._p4_portfolio_name(main_index)}')
        if hasattr(self, 'p4_set_main_btn'):
            if active_index == main_index:
                self.p4_set_main_btn.setText('Main Portfolio')
                self.p4_set_main_btn.setEnabled(False)
            else:
                self.p4_set_main_btn.setText('Set as Main')
                self.p4_set_main_btn.setEnabled(True)
        if hasattr(self, 'port_header_lbl'):
            self.port_header_lbl.setText(f'{self._p4_portfolio_name(main_index)} ({len(getattr(self, "tickers", []))})')

    def _p4_try_call_runtime(self, names: Any, *args: Any) -> bool:
        """Call the first runtime helper that exists."""
        for name in names:
            fn = getattr(self, name, None)
            if callable(fn):
                fn(*args)
                return True
        return False

    def _p4_on_portfolio_changed(self, index: int) -> None:
        """Switch the shared page-4 workspace to a different portfolio."""
        index = min(max(int(index), 0), 2)
        if not self._p4_try_call_runtime(
            ('set_active_portfolio_index', '_set_active_portfolio_index', '_activate_portfolio_index', '_switch_active_portfolio'),
            index,
        ):
            self._p4_apply_fallback_portfolio_identity(index)
        self._p4_refresh_portfolio_selector()
        if hasattr(self, '_reload_options_table'):
            self._reload_options_table()
        if getattr(self, 'last_data', None):
            self.update_page4(self.last_data)
            fetched = set(self.last_data.get('portfolio', {}).keys())
            active_tickers = set(self._p4_active_tickers()) if hasattr(self, '_p4_active_tickers') else set()
            if active_tickers - fetched and hasattr(self, 'refresh_data'):
                self.refresh_data()
        elif hasattr(self, 'p4_table'):
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)

    def _p4_rename_active_portfolio(self) -> None:
        """Prompt the user to rename the selected portfolio slot."""
        active_index = self._p4_get_active_portfolio_index()
        current_name = self._p4_portfolio_name(active_index)
        name, ok = QInputDialog.getText(self, 'Rename Portfolio', 'Portfolio name:', text=current_name)
        if not ok:
            return
        clean_name = str(name or '').strip() or f'Portfolio {active_index + 1}'
        if not self._p4_try_call_runtime(
            ('rename_portfolio', '_rename_portfolio', 'set_portfolio_name', '_set_portfolio_name'),
            active_index,
            clean_name,
        ):
            slots = self._p4_get_portfolio_slots()
            slots[active_index]['name'] = clean_name
            self.portfolio_slots = slots
        self._p4_refresh_portfolio_selector()

    def _p4_set_active_as_main(self) -> None:
        """Mark the selected portfolio as the app-wide main portfolio."""
        active_index = self._p4_get_active_portfolio_index()
        if not self._p4_try_call_runtime(
            ('set_main_portfolio_index', '_set_main_portfolio_index', '_select_main_portfolio', 'use_portfolio_as_main'),
            active_index,
        ):
            self._p4_apply_fallback_portfolio_identity(active_index, make_main=True)
        self._p4_refresh_portfolio_selector()
        if hasattr(self, 'refresh_data'):
            self.refresh_data()

    def init_page4(self) -> None:
        """Initialize page4."""
        layout = QVBoxLayout(self.page4)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        summary_bar = QHBoxLayout()
        title_lbl = QLabel('<b>Portfolio</b>')
        title_lbl.setStyleSheet('font-size: 18px; color: white;')
        self.p4_total_label = QLabel('Total:  $0.00  USD')
        self.p4_total_label.setStyleSheet('font-size: 15px; font-weight: bold; color: #ffd700;')
        self.p4_opt_pl_label = QLabel('Options P&L:  $0.00')
        self.p4_opt_pl_label.setStyleSheet('QLabel { background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: bold; color: #888; }')
        summary_bar.addWidget(title_lbl)
        summary_bar.addStretch()
        summary_bar.addWidget(self.p4_opt_pl_label)
        summary_bar.addWidget(self.p4_total_label)
        layout.addLayout(summary_bar)
        selector_bar = QHBoxLayout()
        selector_bar.setSpacing(8)
        selector_label = QLabel('Portfolio Slots')
        selector_label.setStyleSheet('font-size: 12px; font-weight: bold; color: #8888aa;')
        self.p4_portfolio_tabs = QTabWidget()
        self.p4_portfolio_tabs.setDocumentMode(True)
        self.p4_portfolio_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.p4_portfolio_tabs.setStyleSheet('QTabWidget::pane { border: 1px solid #2a2a4a; background: #12122a; }QTabBar::tab { background: #17172b; color: #8888aa; padding: 6px 12px; border: 1px solid #2a2a4a; border-bottom: none; min-width: 110px; }QTabBar::tab:selected { background: #20203a; color: white; }')
        for _ in range(3):
            self.p4_portfolio_tabs.addTab(QWidget(), '')
        self.p4_portfolio_tabs.currentChanged.connect(self._p4_on_portfolio_changed)
        self.p4_rename_btn = QPushButton('Rename')
        self.p4_rename_btn.setMinimumHeight(26)
        self.p4_rename_btn.clicked.connect(self._p4_rename_active_portfolio)
        self.p4_set_main_btn = QPushButton('Set as Main')
        self.p4_set_main_btn.setMinimumHeight(26)
        self.p4_set_main_btn.setStyleSheet('QPushButton { background: #1a1a3a; color: #4a90e2; border: 1px solid #2a2a5a; border-radius: 4px; padding: 4px 10px; font-weight: bold; font-size: 10px; }QPushButton:hover { background: #1a1a4a; border: 1px solid #4a90e2; }QPushButton:disabled { color: #7b8794; border-color: #2a2a4a; }')
        self.p4_set_main_btn.clicked.connect(self._p4_set_active_as_main)
        self.p4_main_portfolio_label = QLabel('Main Portfolio: Portfolio 1')
        self.p4_main_portfolio_label.setStyleSheet('font-size: 11px; color: #9aa4ad;')
        selector_bar.addWidget(selector_label)
        selector_bar.addWidget(self.p4_portfolio_tabs, 1)
        selector_bar.addWidget(self.p4_rename_btn)
        selector_bar.addWidget(self.p4_set_main_btn)
        selector_bar.addWidget(self.p4_main_portfolio_label)
        layout.addLayout(selector_bar)
        self.p4_main_splitter = QSplitter(Qt.Orientation.Vertical)
        stock_widget = QWidget()
        stock_layout = QVBoxLayout(stock_widget)
        stock_layout.setContentsMargins(0, 4, 0, 0)
        stock_layout.setSpacing(4)
        stock_header_layout = QHBoxLayout()
        stock_header = QLabel('Stock Positions')
        stock_header.setStyleSheet('font-size: 13px; font-weight: bold; color: #8888aa;')
        add_stock_btn = QPushButton('+ Add Position')
        add_stock_btn.setMinimumHeight(24)
        add_stock_btn.setStyleSheet('QPushButton { background: #1a3a1a; color: #4caf50; border: 1px solid #2a5a2a; border-radius: 4px; padding: 2px 10px; font-weight: bold; font-size: 10px; }QPushButton:hover { background: #1e4a1e; border: 1px solid #4caf50; }')
        add_stock_btn.clicked.connect(self._on_add_stock_clicked)
        stock_header_layout.addWidget(stock_header)
        stock_header_layout.addSpacing(10)
        stock_header_layout.addWidget(add_stock_btn)
        stock_header_layout.addStretch()
        stock_layout.addLayout(stock_header_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p4_table = QTableWidget(0, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        hh = self.p4_table.horizontalHeader()
        hh.setSectionsMovable(True)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_SYMBOL, QHeaderView.ResizeMode.Fixed)
        self.p4_table.setColumnWidth(P4_PORTFOLIO_COL_SYMBOL, 78)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_SHARES, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_AVG_PRICE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_COST, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_PRICE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_DAY_CHANGE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_MARKET_VALUE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_WEIGHT, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_DOLLAR_GAIN, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_GROWTH, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_MARKET_CAP, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(P4_PORTFOLIO_COL_ACTION, QHeaderView.ResizeMode.Fixed)
        self.p4_table.setColumnWidth(P4_PORTFOLIO_COL_ACTION, 36)
        self.p4_table.verticalHeader().setVisible(False)
        self.p4_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.p4_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p4_table.verticalHeader().setDefaultSectionSize(52)
        self.p4_table.itemChanged.connect(self._on_tracker_cell_changed)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)
        dip_finder_label = QLabel('Dip Finder')
        dip_finder_label.setStyleSheet('font-size: 12px; color: #aaaaaa; font-weight: bold;')
        dip_finder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p4_returns_tabs = QTabWidget()
        self.p4_returns_tabs.setDocumentMode(True)
        self.p4_returns_tabs.setStyleSheet('QTabWidget::pane { border: 1px solid #2a2a4a; background: #12122a; }QTabBar::tab { background: #17172b; color: #8888aa; padding: 6px 12px; border: 1px solid #2a2a4a; border-bottom: none; min-width: 72px; }QTabBar::tab:selected { background: #20203a; color: white; }')
        self.p4_return_timeframes = [('dip_finder', '1 Month'), ('ytd', 'YTD'), ('1y', '1Y')]
        self.p4_returns_charts = {}
        for timeframe_key, tab_label in self.p4_return_timeframes:
            chart = pg.PlotWidget()
            chart.setBackground('#1a1a2e')
            chart.getPlotItem().setMenuEnabled(False)
            chart.getPlotItem().hideButtons()
            chart.getPlotItem().hideAxis('bottom')
            chart.getPlotItem().hideAxis('left')
            chart.setMouseEnabled(x=False, y=False)
            self.p4_returns_charts[timeframe_key] = chart
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(0)
            tab_layout.addWidget(chart)
            self.p4_returns_tabs.addTab(tab, tab_label)
        self.p4_returns_tabs.currentChanged.connect(self._on_returns_timeframe_changed)
        weight_label = QLabel('Portfolio Weight')
        weight_label.setStyleSheet('font-size: 12px; color: #aaaaaa; font-weight: bold;')
        weight_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p4_weight_chart = pg.PlotWidget()
        self.p4_weight_chart.setBackground('#1a1a2e')
        self.p4_weight_chart.getPlotItem().setMenuEnabled(False)
        self.p4_weight_chart.getPlotItem().hideButtons()
        self.p4_weight_chart.setMouseEnabled(x=False, y=False)
        weight_container = QWidget()
        weight_container_layout = QVBoxLayout(weight_container)
        weight_container_layout.setContentsMargins(0, 0, 0, 0)
        weight_container_layout.setSpacing(2)
        weight_container_layout.addWidget(weight_label)
        weight_container_layout.addWidget(self.p4_weight_chart, 1)
        right_layout.addWidget(dip_finder_label)
        right_layout.addWidget(self.p4_returns_tabs, 1)
        right_layout.addWidget(weight_container, 1)
        splitter.addWidget(self.p4_table)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        stock_layout.addWidget(splitter, 1)
        self.p4_main_splitter.addWidget(stock_widget)
        options_widget = self._init_options_tab()
        self.p4_main_splitter.addWidget(options_widget)
        self.p4_main_splitter.setStretchFactor(0, 3)
        self.p4_main_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.p4_main_splitter, 1)
        self._p4_refresh_portfolio_selector()

    def _on_add_stock_clicked(self) -> None:
        """Handle add stock clicked."""
        ticker, ok = QInputDialog.getText(self, 'Add Stock Position', 'Enter Ticker Symbol:')
        if ok and ticker:
            ticker = ticker.upper().strip()
            tickers = self._p4_active_tickers() if hasattr(self, '_p4_active_tickers') else self.active_tickers
            tracker_data = self._p4_active_tracker_data() if hasattr(self, '_p4_active_tracker_data') else self.active_tracker_data
            if ticker and ticker not in tickers:
                tickers.append(ticker)
                if ticker not in tracker_data:
                    tracker_data[ticker] = {'shares': 0, 'avg_price': 0}
                if hasattr(self, '_p4_invalidate_returns_cache'):
                    self._p4_invalidate_returns_cache(self.active_portfolio_id)
                self._persist_all_portfolios()
                self.refresh_data()

    def _init_options_tab(self) -> Any:
        """Build the Options section widget and return it."""
        options_widget = QWidget()
        layout = QVBoxLayout(options_widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        title_lbl = QLabel('Options Positions')
        title_lbl.setStyleSheet('font-size: 13px; font-weight: bold; color: #8888aa;')
        header.addWidget(title_lbl)
        header.addSpacing(10)
        add_btn = QPushButton('+ Add Position')
        add_btn.setMinimumHeight(24)
        add_btn.setStyleSheet('QPushButton { background: #1a3a1a; color: #4caf50; border: 1px solid #2a5a2a; border-radius: 4px; padding: 2px 10px; font-weight: bold; font-size: 10px; }QPushButton:hover { background: #1e4a1e; border: 1px solid #4caf50; }')
        add_btn.clicked.connect(self._add_options_row)
        refresh_opt_btn = QPushButton('↻ Sync')
        refresh_opt_btn.setMinimumHeight(24)
        refresh_opt_btn.setStyleSheet('QPushButton { background: #1a1a3a; color: #4a90e2; border: 1px solid #2a2a5a; border-radius: 4px; padding: 2px 10px; font-weight: bold; font-size: 10px; }QPushButton:hover { background: #1a1a4a; border: 1px solid #4a90e2; }')
        refresh_opt_btn.clicked.connect(self._sync_all_options)
        header.addWidget(add_btn)
        header.addSpacing(6)
        header.addWidget(refresh_opt_btn)
        header.addStretch()
        layout.addLayout(header)
        self.p4_opt_table = QTableWidget(0, 16)
        self.p4_opt_table.setHorizontalHeaderLabels(['Ticker', 'Type', 'Expiry', 'DTE', 'Strike', 'Qty', 'Premium', 'Market Price', 'IV (%)', 'Delta', 'Theta', 'P&L ($)', 'Return %', 'Annual %', 'Status', ''])
        oh = self.p4_opt_table.horizontalHeader()
        for col in range(15):
            oh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        oh.setSectionResizeMode(15, QHeaderView.ResizeMode.Fixed)
        self.p4_opt_table.setColumnWidth(15, 36)
        self.p4_opt_table.verticalHeader().setVisible(False)
        self.p4_opt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.p4_opt_table.verticalHeader().setDefaultSectionSize(38)
        self.p4_opt_table.setStyleSheet('QTableWidget { background-color: #12122a; gridline-color: #2a2a4a; border: none; }QHeaderView::section { background: #1a1a3a; color: #8888aa; border: 1px solid #2a2a4a; padding: 4px; font-weight: bold; font-size: 11px; }QTableWidget::item { border-bottom: 1px solid #1e1e3a; }')
        self.p4_opt_table.itemChanged.connect(self._on_options_cell_changed)
        layout.addWidget(self.p4_opt_table, 1)
        for pos in self.options_data:
            self._insert_options_row(pos)
        return options_widget

    def _sync_all_options(self) -> None:
        """Refresh expiries and current prices for all options in the table sequentially."""
        t = self.p4_opt_table
        if t.rowCount() == 0:
            return
        self.status_bar.setText('Syncing all options...')
        self.status_bar.setStyleSheet('color: #4a90e2;')

        def _run_sync() -> None:
            """Handle run sync."""
            success_count = 0
            fail_count = 0
            total = t.rowCount()
            for row in range(total):
                ticker_item = t.item(row, 0)
                if not ticker_item:
                    continue
                ticker = ticker_item.text().strip().upper()
                if not ticker:
                    continue
                self._invoke_main.emit(lambda r=row, sym=ticker: self.status_bar.setText(f'Syncing {sym} ({r + 1}/{total})...'))
                self._invoke_main.emit(lambda r=row: self._set_row_fetching_status(r))
                self._fetch_option_expiries_sync(row, ticker)
                self._fetch_single_option_price_sync(row)
                price_item = t.item(row, 7)
                if price_item and 'Err' in price_item.text():
                    fail_count += 1
                else:
                    success_count += 1
            msg = f'Sync Complete: {success_count} succeeded, {fail_count} failed'
            color = '#80ff80' if fail_count == 0 else '#f0c040'
            self._invoke_main.emit(lambda: self.status_bar.setText(msg))
            self._invoke_main.emit(lambda: self.status_bar.setStyleSheet(f'color: {color};'))
        threading.Thread(target=_run_sync, daemon=True).start()
