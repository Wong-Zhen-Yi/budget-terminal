from __future__ import annotations
from typing import Any
from ..compat import *


@dataclass
class SectorTickerSnapshot:
    price: Any=None
    mkt_cap: Any=None
    change: Any=None


class SectorsMixin:
    _P8_CARD_MARGIN = 16
    _P8_CARD_SPACING = 12
    _P8_TABLE_WIDTH = 74 + 78 + 72 + 120 + 58 + 6

    def init_page8(self) -> None:
        """Build the Sectors page UI with a responsive card grid."""
        layout = QVBoxLayout(self.page8)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title_lbl = QLabel('<b>Sectors</b>')
        self.set_theme_role(title_lbl, 'page_title')
        self.p8_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p8_status_lbl, 'status_muted')
        header.addWidget(title_lbl)
        header.addStretch()
        header.addWidget(self.p8_status_lbl)
        layout.addLayout(header)
        self.btn_page8.clicked.connect(self._p8_on_show)
        self.p8_scroll = QScrollArea()
        self.p8_scroll.setWidgetResizable(True)
        self.p8_container = QWidget()
        self.p8_container.setStyleSheet('background: transparent;')
        self.p8_container_layout = QGridLayout(self.p8_container)
        self.p8_container_layout.setContentsMargins(0, 0, 0, 0)
        self.p8_container_layout.setHorizontalSpacing(self._P8_CARD_SPACING)
        self.p8_container_layout.setVerticalSpacing(self._P8_CARD_SPACING)
        self.p8_sector_tables = {}
        self.p8_sector_cards = {}
        self.p8_sector_titles = {}
        self.p8_sector_order = sorted(SECTOR_DATA.keys())
        self.p8_last_fetch = 0
        self.p8_column_count = 0
        self.p8_card_min_width = self._P8_TABLE_WIDTH + self._P8_CARD_MARGIN
        self.p8_scroll.setWidget(self.p8_container)
        layout.addWidget(self.p8_scroll)
        for sector in self.p8_sector_order:
            self._p8_create_sector_card(sector)
        self._p8_relayout_cards()
        self._pages[7]['on_show'] = self._p8_on_show

    def _p8_create_sector_card(self, sector: str) -> None:
        """Create one reusable sector card and its table."""
        sec_box = QFrame()
        sec_box.setStyleSheet(f'QFrame {{ background: {self.theme_color("panel_background")}; border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}')
        sec_box.setMinimumWidth(self.p8_card_min_width)
        sec_layout = QVBoxLayout(sec_box)
        sec_layout.setContentsMargins(8, 8, 8, 8)
        sec_layout.setSpacing(5)
        sec_title = QLabel(f'<b>{sector}</b>')
        sec_title.setStyleSheet(f'font-size: 13px; color: {self.theme_color("warning")}; padding: 0 0 2px 2px;')
        sec_layout.addWidget(sec_title)
        table = QTableWidget(10, 5)
        table.setHorizontalHeaderLabels(['Ticker', 'Price', 'Chg %', 'Mkt Cap', ''])
        hh = table.horizontalHeader()
        for col in range(3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 74)
        table.setColumnWidth(1, 78)
        table.setColumnWidth(2, 72)
        table.setColumnWidth(3, 120)
        table.setColumnWidth(4, 58)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setAlternatingRowColors(True)
        table.setFixedHeight(300)
        for i, ticker in enumerate(SECTOR_DATA[sector]):
            item = QTableWidgetItem(ticker)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 0, item)
            for col in range(1, 4):
                placeholder = QTableWidgetItem('...')
                placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setForeground(self.theme_qcolor('text_muted'))
                table.setItem(i, col, placeholder)
            analyze_btn = QPushButton('View')
            self.set_theme_variant(analyze_btn, 'accent')
            analyze_btn.setStyleSheet('font-size: 10px; padding: 1px 4px;')
            analyze_btn.setMinimumSize(58, 24)
            analyze_btn.clicked.connect(lambda checked=False, sym=ticker: self._p8_analyze_ticker(sym))
            table.setCellWidget(i, 4, analyze_btn)
        sec_layout.addWidget(table)
        self.p8_sector_cards[sector] = sec_box
        self.p8_sector_tables[sector] = table
        self.p8_sector_titles[sector] = sec_title

    def _p8_grid_columns(self) -> int:
        """Choose a responsive column count from the available viewport width."""
        viewport = self.p8_scroll.viewport().width() if hasattr(self, 'p8_scroll') else 0
        if viewport <= 0:
            return 3
        total = max(0, viewport - self._P8_CARD_SPACING * 3)
        if total >= self.p8_card_min_width * 4:
            return 4
        return 3

    def _p8_relayout_cards(self) -> None:
        """Rebuild card placement for the current viewport width."""
        if not hasattr(self, 'p8_container_layout'):
            return
        cols = self._p8_grid_columns()
        if cols == self.p8_column_count and self.p8_container_layout.count() == len(self.p8_sector_order):
            return
        while self.p8_container_layout.count():
            item = self.p8_container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.p8_container)
        for col in range(4):
            self.p8_container_layout.setColumnStretch(col, 0)
        for idx, sector in enumerate(self.p8_sector_order):
            card = self.p8_sector_cards[sector]
            row = idx // cols
            col = idx % cols
            self.p8_container_layout.addWidget(card, row, col)
        for col in range(cols):
            self.p8_container_layout.setColumnStretch(col, 1)
        self.p8_column_count = cols

    def _p8_on_show(self) -> None:
        """Refresh sector data when the tab is shown."""
        self._p8_relayout_cards()
        now = datetime.datetime.now().timestamp()
        if now - self.p8_last_fetch > 120:
            self.p8_last_fetch = now
            self.set_status_text(self.p8_status_lbl, 'Refreshing sector data...', status='info')
            threading.Thread(target=self._p8_fetch_all_sectors, daemon=True).start()

    def _p8_fetch_all_sectors(self) -> None:
        """Fetch sector prices in batch and market caps through a smaller fallback path."""
        all_tickers = sorted({ticker for tickers in SECTOR_DATA.values() for ticker in tickers})
        all_results = {ticker: SectorTickerSnapshot() for ticker in all_tickers}
        try:
            batch = yf.download(all_tickers, period='5d', interval='1d', group_by='ticker', progress=False, auto_adjust=False, threads=True)
            is_multi = isinstance(batch.columns, pd.MultiIndex)
            for ticker in all_tickers:
                try:
                    if is_multi and ticker in batch.columns.get_level_values(0):
                        close = batch[ticker]['Close'].dropna()
                    elif (not is_multi) and 'Close' in batch.columns:
                        close = batch['Close'].dropna()
                    else:
                        close = pd.Series(dtype=float)
                    if len(close) >= 2:
                        price = float(close.iloc[-1])
                        prev = float(close.iloc[-2])
                        change = (price - prev) / prev * 100 if prev else 0.0
                        all_results[ticker].price = price
                        all_results[ticker].change = change
                    elif len(close) == 1:
                        all_results[ticker].price = float(close.iloc[-1])
                        all_results[ticker].change = 0.0
                except Exception:
                    continue

            def fetch_price_fallback(ticker: Any) -> Any:
                """Fetch price data for tickers missed by the batch request."""
                try:
                    with YF_LOCK:
                        history = yf.Ticker(ticker).history(period='5d', interval='1d')
                    close = history.get('Close')
                    if close is None:
                        return (ticker, None, None)
                    close = close.dropna()
                    if len(close) >= 2:
                        price = float(close.iloc[-1])
                        prev = float(close.iloc[-2])
                        change = (price - prev) / prev * 100 if prev else 0.0
                        return (ticker, price, change)
                    if len(close) == 1:
                        return (ticker, float(close.iloc[-1]), 0.0)
                except Exception:
                    pass
                try:
                    with YF_LOCK:
                        fast_info = getattr(yf.Ticker(ticker), 'fast_info', {}) or {}
                    price = fast_info.get('lastPrice')
                    prev = fast_info.get('previousClose')
                    if price:
                        change = ((float(price) - float(prev)) / float(prev) * 100) if prev else 0.0
                        return (ticker, float(price), change)
                except Exception:
                    pass
                return (ticker, None, None)

            missing_price = [ticker for ticker, result in all_results.items() if result.price is None]
            if missing_price:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    for ticker, price, change in executor.map(fetch_price_fallback, missing_price):
                        if price is not None:
                            all_results[ticker].price = price
                            all_results[ticker].change = change

            def fetch_mkt_cap(ticker: Any) -> Any:
                """Fetch market cap with fast_info first, info fallback second."""
                try:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        fast_info = getattr(t_obj, 'fast_info', {}) or {}
                    mc = fast_info.get('marketCap')
                    if mc:
                        return (ticker, float(mc))
                except Exception:
                    pass
                try:
                    with YF_LOCK:
                        info = yf.Ticker(ticker).info
                    mc = info.get('marketCap')
                    return (ticker, float(mc)) if mc else (ticker, None)
                except Exception:
                    return (ticker, None)

            with ThreadPoolExecutor(max_workers=10) as executor:
                for ticker, mc in executor.map(fetch_mkt_cap, all_tickers):
                    all_results[ticker].mkt_cap = mc
            self._invoke_main.emit(lambda results=all_results: self._p8_populate_all_tables(results))
        except Exception as e:
            logger.error(f'Failed to fetch all sector data: {e}')
            self._invoke_main.emit(lambda: self.set_status_text(self.p8_status_lbl, 'Sector data refresh failed', status='negative'))

    def _p8_populate_all_tables(self, all_results: Any) -> None:
        """Populate all sector cards with the latest fetched data."""
        populated = 0
        for sector, tickers in SECTOR_DATA.items():
            sector_results = {ticker: all_results.get(ticker, SectorTickerSnapshot()) for ticker in tickers}
            populated += self._p8_populate_sector_table(sector, sector_results)
        self.p8_status_lbl.setText(f"Updated {datetime.datetime.now().strftime('%H:%M:%S')}  |  {populated} tickers")
        self._p8_relayout_cards()

    def _p8_populate_sector_table(self, sector: Any, results: Any) -> int:
        """Populate one sector table."""
        table = self.p8_sector_tables.get(sector)
        if not table:
            return 0
        populated = 0
        sector_changes = []
        for row in range(table.rowCount()):
            ticker_item = table.item(row, 0)
            if not ticker_item:
                continue
            ticker = ticker_item.text()
            result = results.get(ticker) or SectorTickerSnapshot()
            price = result.price
            change = result.change
            mkt_cap = result.mkt_cap
            price_text = f'${price:.2f}' if isinstance(price, (int, float)) else 'N/A'
            price_item = QTableWidgetItem(price_text)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price_item.setForeground(QColor('white') if isinstance(price, (int, float)) else QColor('#777'))
            table.setItem(row, 1, price_item)
            if isinstance(price, (int, float)):
                populated += 1
            if isinstance(change, (int, float)):
                sign = '+' if change >= 0 else ''
                change_item = QTableWidgetItem(f'{sign}{change:.2f}%')
                change_item.setForeground(QColor(CLR_UP) if change >= 0 else QColor(CLR_DOWN))
                sector_changes.append(float(change))
            else:
                change_item = QTableWidgetItem('N/A')
                change_item.setForeground(QColor('#777'))
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, change_item)
            cap_text = fmt_num(mkt_cap) if isinstance(mkt_cap, (int, float)) and mkt_cap > 0 else 'N/A'
            cap_item = QTableWidgetItem(cap_text)
            cap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cap_item.setForeground(QColor(self._mktcap_color(mkt_cap)) if isinstance(mkt_cap, (int, float)) and mkt_cap > 0 else QColor('#777'))
            table.setItem(row, 3, cap_item)
        title = self.p8_sector_titles.get(sector)
        if title:
            if sector_changes:
                avg_change = sum(sector_changes) / len(sector_changes)
                sign = '+' if avg_change >= 0 else ''
                color = CLR_UP if avg_change >= 0 else CLR_DOWN
                title.setText(f"<b>{sector}</b>  <span style='color:{color};'>{sign}{avg_change:.2f}%</span>")
            else:
                title.setText(f'<b>{sector}</b>')
        return populated

    def _p8_analyze_ticker(self, ticker: Any) -> None:
        """Jump from sectors to fundamentals for the selected ticker."""
        self.p2_ticker_input.setText(ticker)
        self.switch_page(1)
        self.analyze_stock_p2()
