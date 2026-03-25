from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.etf_holdings import EtfHoldingsResult, EtfHoldingsService

ETF_UNIVERSE = [
    # Broad US market
    'SPY', 'VOO', 'IVV', 'VTI', 'QQQ', 'DIA', 'IWM', 'IWF', 'IWD', 'RSP',
    'SPLG', 'SCHB', 'ITOT', 'VV', 'MGK', 'VUG', 'VTV', 'SCHG', 'SCHV',
    # International
    'VEA', 'VWO', 'IEFA', 'IEMG', 'EFA', 'EEM', 'VXUS', 'IXUS', 'SPDW', 'SPEM',
    'FXI', 'EWJ', 'EWZ', 'EWG', 'EWU', 'INDA', 'VGK', 'VPL',
    # Fixed income
    'BND', 'AGG', 'TLT', 'IEF', 'SHY', 'LQD', 'HYG', 'JNK', 'TIP', 'VCIT',
    'VCSH', 'VGSH', 'VGIT', 'VGLT', 'MUB', 'EMB', 'BNDX', 'SCHZ',
    # Sector
    'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLP', 'XLY', 'XLU', 'XLC', 'XLB',
    'XLRE', 'VGT', 'VFH', 'VHT', 'VDE', 'VIS', 'VCR', 'VDC', 'VNQ',
    # Thematic
    'ARKK', 'ARKW', 'ARKG', 'ARKF', 'ARKQ', 'BOTZ', 'ROBO', 'HACK', 'SKYY',
    'KWEB', 'CIBR', 'WCLD', 'IGV', 'SOXX', 'SMH', 'QCLN', 'TAN', 'ICLN',
    # Commodities
    'GLD', 'SLV', 'IAU', 'GDX', 'GDXJ', 'USO', 'UNG', 'DBC', 'PDBC', 'PPLT',
    # Dividend
    'VYM', 'SCHD', 'DVY', 'HDV', 'DGRO', 'SDY', 'NOBL', 'SPYD', 'VIG', 'DGRW',
    # Leveraged / Inverse
    'TQQQ', 'SQQQ', 'SPXL', 'SPXS', 'UPRO', 'SDS', 'QLD', 'SSO', 'SOXL', 'SOXS',
    # Crypto
    'BITO', 'GBTC', 'ETHE', 'IBIT', 'FBTC',
    # Real estate
    'VNQI', 'IYR', 'REET', 'RWR',
]

_AUM_RANGES = [
    ('$100M – $500M', 100_000_000, 500_000_000),
    ('$500M – $1B', 500_000_000, 1_000_000_000),
    ('$1B+', 1_000_000_000, None),
]


class EtfAnalyserMixin:
    def init_page13(self) -> None:
        """Build the ETF analyser page UI."""
        self._p13_rows: list[dict[str, Any]] = []
        self._p13_service = EtfHoldingsService()
        self._p13_aum_cache: dict[str, float] = {}
        self._p13_active_aum_range: int = -1
        self._p13_aum_fetch_in_progress: bool = False

        outer_layout = QHBoxLayout(self.page13)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._p13_build_aum_panel()
        splitter.addWidget(left_panel)

        right_widget = QWidget()
        layout = QVBoxLayout(right_widget)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer_layout.addWidget(splitter)

        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>ETF</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        controls = QFrame()
        controls.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        controls_layout.setSpacing(10)

        symbol_lbl = QLabel('ETF:')
        symbol_lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p13_etf_input = QLineEdit()
        self.p13_etf_input.setPlaceholderText('Enter ETF ticker (e.g. SPY, QQQ, VOO)')
        self.p13_etf_input.setMinimumWidth(220)
        self.p13_etf_input.returnPressed.connect(self._p13_load_etf)
        self.p13_load_btn = QPushButton('Load Holdings')
        self.set_theme_variant(self.p13_load_btn, 'accent')
        self.p13_load_btn.clicked.connect(self._p13_load_etf)
        controls_layout.addWidget(symbol_lbl)
        controls_layout.addWidget(self.p13_etf_input)
        self.p13_export_btn = QPushButton('Export')
        self.p13_export_btn.clicked.connect(self._p13_export_clipboard)
        controls_layout.addWidget(self.p13_load_btn)
        controls_layout.addWidget(self.p13_export_btn)
        controls_layout.addStretch()
        layout.addWidget(controls)

        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        summary_layout = QGridLayout(summary_frame)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(8)

        self.p13_name_lbl = QLabel('Fund: --')
        self.p13_category_lbl = QLabel('Issuer: --')
        self.p13_family_lbl = QLabel('As Of: --')
        self.p13_expense_lbl = QLabel('Expense Ratio: --')
        self.p13_assets_lbl = QLabel('Net Assets: --')
        self.p13_count_lbl = QLabel('Holdings Loaded: 0')
        for label in (
            self.p13_name_lbl,
            self.p13_category_lbl,
            self.p13_family_lbl,
            self.p13_expense_lbl,
            self.p13_assets_lbl,
            self.p13_count_lbl,
        ):
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        summary_layout.addWidget(self.p13_name_lbl, 0, 0)
        summary_layout.addWidget(self.p13_category_lbl, 0, 1)
        summary_layout.addWidget(self.p13_family_lbl, 0, 2)
        summary_layout.addWidget(self.p13_expense_lbl, 1, 0)
        summary_layout.addWidget(self.p13_assets_lbl, 1, 1)
        summary_layout.addWidget(self.p13_count_lbl, 1, 2)
        layout.addWidget(summary_frame)

        self.p13_sectors_lbl = QLabel('')
        self.p13_sectors_lbl.setWordWrap(True)
        self.p13_sectors_lbl.setStyleSheet(
            f'color: {self.theme_color("text_secondary")}; '
            f'background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 6px; padding: 8px 12px;'
        )
        self.p13_sectors_lbl.setVisible(False)
        layout.addWidget(self.p13_sectors_lbl)

        self.p13_status_lbl = QLabel('Enter an ETF ticker to load holdings from supported official issuer sources.')
        self.set_theme_role(self.p13_status_lbl, 'status_muted')
        layout.addWidget(self.p13_status_lbl)

        self.p13_table = QTableWidget(0, 3)
        self.p13_table.setHorizontalHeaderLabels(['Ticker', 'Name', 'Weight'])
        hh = self.p13_table.horizontalHeader()
        hh.setMinimumHeight(28)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionsMovable(True)
        self.p13_table.verticalHeader().setVisible(False)
        self.p13_table.verticalHeader().setDefaultSectionSize(28)
        self.p13_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p13_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p13_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p13_table.setAlternatingRowColors(True)
        self.p13_table.setSortingEnabled(True)
        self.p13_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        layout.addWidget(self.p13_table, 1)

        # Auto-select $1B+ range on startup
        self._p13_on_aum_filter_clicked(2)

    def _p13_load_etf(self) -> None:
        """Fetch ETF holdings data using supported official issuer sources."""
        ticker = self.p13_etf_input.text().upper().strip()
        if not ticker:
            self.set_status_text(self.p13_status_lbl, 'Enter an ETF ticker first.', status='warning')
            return
        self.set_status_text(self.p13_status_lbl, f'Loading ETF holdings for {ticker} from official issuer sources...', status='warning')
        self.p13_load_btn.setEnabled(False)

        def _run() -> None:
            """Fetch fund metadata and holdings off the UI thread."""
            try:
                result = self._p13_service.load(ticker)
                self._invoke_main.emit(lambda r=result: self._p13_update_view(r))
            except Exception as exc:
                logger.error(f'ETF analyser load failed for {ticker}: {exc}')
                self._invoke_main.emit(lambda t=ticker, err=str(exc): self._p13_handle_error(t, err))

        threading.Thread(target=_run, daemon=True).start()

    def _p13_update_view(self, result: EtfHoldingsResult) -> None:
        """Render ETF summary and holdings into the page table."""
        rows = [
            {
                'symbol': holding.symbol,
                'name': holding.name,
                'weight': holding.weight,
            }
            for holding in result.holdings
        ]
        self._p13_rows = rows
        self.p13_table.setSortingEnabled(False)
        self.p13_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            ticker_item = QTableWidgetItem(row.get('symbol', ''))
            ticker_item.setForeground(self.theme_qcolor('text_primary'))
            name_item = QTableWidgetItem(row.get('name', ''))
            name_item.setForeground(self.theme_qcolor('text_secondary'))
            weight_value = row.get('weight')
            weight_text = '--' if weight_value is None else f'{weight_value * 100:.2f}%'
            weight_item = QTableWidgetItem(weight_text)
            weight_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            weight_item.setForeground(self.theme_qcolor('accent_positive'))
            self.p13_table.setItem(row_index, 0, ticker_item)
            self.p13_table.setItem(row_index, 1, name_item)
            self.p13_table.setItem(row_index, 2, weight_item)
        self.p13_table.setSortingEnabled(True)
        self.p13_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.p13_name_lbl.setText(f'Fund: {result.fund_name or result.ticker}')
        self.p13_category_lbl.setText(f'Issuer: {result.issuer or "Unknown"}')
        self.p13_family_lbl.setText(f'As Of: {result.as_of_date or "--"}')
        self.p13_expense_lbl.setText(f'Expense Ratio: {result.expense_ratio or "--"}')
        self.p13_assets_lbl.setText(f'Net Assets: {result.net_assets or "--"}')
        self.p13_count_lbl.setText(f'Holdings Loaded: {len(rows)}')
        if result.sector_breakdown:
            parts = [f'{name} {pct:.1f}%' for name, pct in result.sector_breakdown.items()]
            self.p13_sectors_lbl.setText(f'<b>Sectors:</b>  {" | ".join(parts)}')
            self.p13_sectors_lbl.setVisible(True)
        else:
            self.p13_sectors_lbl.setVisible(False)
        if rows and result.is_partial:
            self.set_status_text(
                self.p13_status_lbl,
                f'Loaded {len(rows)} top holdings for {result.ticker} via Yahoo Finance fallback. This is not the full holdings list.',
                status='warning',
            )
        elif rows:
            self.set_status_text(
                self.p13_status_lbl,
                f'Loaded {len(rows)} holdings for {result.ticker} from {result.issuer}.',
                status='positive',
            )
        else:
            self.set_status_text(
                self.p13_status_lbl,
                f'No holdings were returned by the official issuer source for {result.ticker}.',
                status='warning',
            )
        self._set_data_collection_info([result.issuer or 'official issuer source'])
        self.p13_load_btn.setEnabled(True)

    def _p13_export_clipboard(self) -> None:
        """Copy holdings to clipboard in tab-separated format for spreadsheet pasting."""
        if not self._p13_rows:
            self.set_status_text(self.p13_status_lbl, 'No holdings to export.', status='warning')
            return
        lines = ['Ticker\tName\tWeight']
        for row in self._p13_rows:
            weight = row.get('weight')
            weight_text = '' if weight is None else f'{weight * 100:.2f}%'
            lines.append(f'{row.get("symbol", "")}\t{row.get("name", "")}\t{weight_text}')
        QApplication.clipboard().setText('\n'.join(lines))
        self.set_status_text(self.p13_status_lbl, f'Copied {len(self._p13_rows)} holdings to clipboard.', status='positive')

    def _p13_handle_error(self, ticker: str, exc: Any) -> None:
        """Show a user-facing error for ETF loads."""
        self.p13_load_btn.setEnabled(True)
        self.set_status_text(self.p13_status_lbl, f'Failed to load {ticker}: {exc}', status='negative')

    # ── AUM left panel ──────────────────────────────────────────────

    def _p13_build_aum_panel(self) -> QWidget:
        """Build the left-side 'ETF by AUM' panel."""
        panel = QWidget()
        panel.setMinimumWidth(240)
        panel.setStyleSheet(
            f'QWidget {{ background: {self.theme_color("panel_background")}; '
            f'border-right: 1px solid {self.theme_color("panel_border")}; }}'
        )
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        title = QLabel('<b>ETF by AUM</b>')
        title.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        vbox.addWidget(title)

        self._p13_aum_buttons: list[QPushButton] = []
        for idx, (label, _lo, _hi) in enumerate(_AUM_RANGES):
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(partial(self._p13_on_aum_filter_clicked, idx))
            self._p13_aum_buttons.append(btn)
            vbox.addWidget(btn)

        self._p13_aum_status_lbl = QLabel('')
        self._p13_aum_status_lbl.setWordWrap(True)
        self._p13_aum_status_lbl.setStyleSheet(
            f'color: {self.theme_color("text_secondary")}; border: none; font-size: 11px;'
        )
        vbox.addWidget(self._p13_aum_status_lbl)

        self._p13_aum_table = QTableWidget(0, 2)
        self._p13_aum_table.setHorizontalHeaderLabels(['Ticker', 'AUM'])
        hh = self._p13_aum_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._p13_aum_table.verticalHeader().setVisible(False)
        self._p13_aum_table.verticalHeader().setDefaultSectionSize(26)
        self._p13_aum_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._p13_aum_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._p13_aum_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p13_aum_table.setAlternatingRowColors(True)
        self._p13_aum_table.setSortingEnabled(True)
        self._p13_aum_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._p13_aum_table.cellClicked.connect(self._p13_on_aum_etf_clicked)
        vbox.addWidget(self._p13_aum_table, 1)

        return panel

    def _p13_on_aum_filter_clicked(self, range_index: int) -> None:
        """Handle an AUM range button click."""
        self._p13_active_aum_range = range_index
        for i, btn in enumerate(self._p13_aum_buttons):
            if i == range_index:
                self.set_theme_variant(btn, 'accent')
            else:
                self.set_theme_variant(btn, 'default')

        if self._p13_aum_cache:
            self._p13_apply_aum_filter()
            return

        if self._p13_aum_fetch_in_progress:
            return

        self._p13_aum_fetch_in_progress = True
        for btn in self._p13_aum_buttons:
            btn.setEnabled(False)
        self._p13_aum_status_lbl.setText('Fetching AUM data...')

        def _fetch() -> None:
            cache: dict[str, float] = {}
            total = len(ETF_UNIVERSE)
            for i, ticker in enumerate(ETF_UNIVERSE):
                try:
                    with YF_LOCK:
                        info = yf.Ticker(ticker).info
                    assets = info.get('totalAssets')
                    if assets and assets > 0:
                        cache[ticker] = float(assets)
                except Exception:
                    pass
                if (i + 1) % 10 == 0 or i == total - 1:
                    progress_msg = f'Fetching AUM data... {i + 1}/{total}'
                    self._invoke_main.emit(lambda m=progress_msg: self._p13_aum_status_lbl.setText(m))
            self._invoke_main.emit(lambda c=cache: self._p13_on_aum_data_ready(c))

        threading.Thread(target=_fetch, daemon=True).start()

    def _p13_on_aum_data_ready(self, cache: dict[str, float]) -> None:
        """Store AUM cache and apply the active filter."""
        self._p13_aum_cache = cache
        self._p13_aum_fetch_in_progress = False
        for btn in self._p13_aum_buttons:
            btn.setEnabled(True)
        self._p13_aum_status_lbl.setText(f'Loaded AUM for {len(cache)} ETFs.')
        self._p13_apply_aum_filter()

    def _p13_apply_aum_filter(self) -> None:
        """Filter and display ETFs matching the active AUM range."""
        if self._p13_active_aum_range < 0:
            return
        _label, lo, hi = _AUM_RANGES[self._p13_active_aum_range]
        filtered = []
        for ticker, aum in self._p13_aum_cache.items():
            if aum < lo:
                continue
            if hi is not None and aum >= hi:
                continue
            filtered.append((ticker, aum))
        filtered.sort(key=lambda x: x[1], reverse=True)

        self._p13_aum_table.setSortingEnabled(False)
        self._p13_aum_table.setRowCount(len(filtered))
        for row, (ticker, aum) in enumerate(filtered):
            t_item = QTableWidgetItem(ticker)
            t_item.setForeground(self.theme_qcolor('text_primary'))
            a_item = QTableWidgetItem(self._p13_format_aum(aum))
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            a_item.setForeground(self.theme_qcolor('accent_positive'))
            self._p13_aum_table.setItem(row, 0, t_item)
            self._p13_aum_table.setItem(row, 1, a_item)
        self._p13_aum_table.setSortingEnabled(True)
        self._p13_aum_status_lbl.setText(f'{len(filtered)} ETFs in {_label} range.')

    def _p13_on_aum_etf_clicked(self, row: int, _col: int) -> None:
        """Load the clicked ETF's holdings in the main view."""
        item = self._p13_aum_table.item(row, 0)
        if item:
            self.p13_etf_input.setText(item.text())
            self._p13_load_etf()

    @staticmethod
    def _p13_format_aum(value: float) -> str:
        """Format AUM value as human-readable string."""
        if value >= 1_000_000_000_000:
            return f'${value / 1_000_000_000_000:.1f}T'
        if value >= 1_000_000_000:
            return f'${value / 1_000_000_000:.1f}B'
        if value >= 1_000_000:
            return f'${value / 1_000_000:.0f}M'
        return f'${value:,.0f}'
