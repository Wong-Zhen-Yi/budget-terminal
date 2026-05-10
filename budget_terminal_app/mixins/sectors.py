from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.data_service.results import strip_market_data_keys
from budget_terminal_app.workers.market_metrics import MarketCapWorker


@dataclass
class SectorTickerSnapshot:
    price: Any=None
    mkt_cap: Any=None
    change: Any=None


class SectorsMixin:
    _P8_HEAT_CARD_MIN_WIDTH = 200
    _P8_HEAT_CARD_MAX_WIDTH = 320
    _P8_HEAT_CARD_SPACING = 8
    _P8_MAX_GRID_COLUMNS = 5
    _P8_MIN_GRID_COLUMNS = 2
    _P8_DETAIL_TABLE_ROW_HEIGHT = 32
    _P8_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0
    _P8_SECTOR_AFTER = {'Crypto': 'Utilities', 'Metals': 'Crypto'}

    def init_page8(self) -> None:
        """Build the Sectors page UI with summary bar, heat cards, and detail panel."""
        self._p8_all_results = {}
        self._p8_sector_averages = {}
        self._p8_selected_sector = None
        self._p8_mktcap_fetching = False
        self._p8_mktcap_inflight_tickers = set()
        self._p8_mktcap_queued_tickers = set()
        self._p8_mktcap_worker = None
        self.p8_last_fetch = 0
        self.p8_fetch_in_progress = False
        self.p8_column_count = 0
        self.p8_sector_order = self._p8_build_sector_order()

        layout = QVBoxLayout(self.page8)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # -- Summary bar --
        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 6, 12, 6)
        summary_layout.setSpacing(0)

        self.p8_summary_labels = {}
        summary_items = [
            ('updated', 'Last Updated', '--'),
            ('tickers', 'Tickers', '--'),
            ('strongest', 'Strongest', '--'),
            ('weakest', 'Weakest', '--'),
            ('inflows', 'Top Inflows', '--'),
            ('outflows', 'Top Outflows', '--'),
        ]
        for i, (key, label, default) in enumerate(summary_items):
            if i > 0:
                sep = QFrame()
                sep.setFixedWidth(1)
                sep.setStyleSheet(f'background: {self.theme_color("panel_border")};')
                summary_layout.addWidget(sep)

            cell = QVBoxLayout()
            cell.setContentsMargins(12, 2, 12, 2)
            cell.setSpacing(1)
            header = QLabel(label)
            header.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel(default)
            value.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 15px; font-weight: bold; border: none;')
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(header)
            cell.addWidget(value)
            summary_layout.addLayout(cell, 1)
            self.p8_summary_labels[key] = value

        layout.addWidget(summary_frame)

        # -- Status label --
        self.p8_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p8_status_lbl, 'status_muted')
        self.p8_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.p8_status_lbl)

        # -- Main content: heat cards (top) + detail panel (bottom) --
        # Heat card grid in scroll area
        self.p8_card_scroll = QScrollArea()
        self.p8_card_scroll.setWidgetResizable(True)
        self.p8_card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p8_card_scroll.setStyleSheet('background: transparent;')
        self.p8_card_container = QWidget()
        self.p8_card_container.setStyleSheet('background: transparent;')
        self.p8_card_grid = QGridLayout(self.p8_card_container)
        self.p8_card_grid.setContentsMargins(0, 0, 0, 0)
        self.p8_card_grid.setHorizontalSpacing(self._P8_HEAT_CARD_SPACING)
        self.p8_card_grid.setVerticalSpacing(self._P8_HEAT_CARD_SPACING)
        self.p8_card_scroll.setWidget(self.p8_card_container)
        self.p8_card_scroll.viewport().installEventFilter(self)

        # Build heat cards
        self.p8_heat_cards = {}
        for sector in self.p8_sector_order:
            self._p8_create_heat_card(sector)
        self._p8_relayout_cards()

        layout.addWidget(self.p8_card_scroll, 1)

        # Detail panel (bottom, fixed height for 10 rows)
        self.p8_detail_panel = QFrame()
        self.p8_detail_panel.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        detail_layout = QVBoxLayout(self.p8_detail_panel)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        detail_layout.setSpacing(6)

        self.p8_detail_title = QLabel('Select a sector')
        self.p8_detail_title.setStyleSheet(
            f'font-size: 18px; font-weight: bold; color: {self.theme_color("warning")}; '
            f'border: none; padding: 2px 0;'
        )
        detail_layout.addWidget(self.p8_detail_title)

        self.p8_detail_table = QTableWidget(0, 4)
        self.p8_detail_table.setHorizontalHeaderLabels(['Ticker', 'Price', 'Chg %', 'Mkt Cap'])
        hh = self.p8_detail_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.p8_detail_table.verticalHeader().setVisible(False)
        self.p8_detail_table.verticalHeader().setDefaultSectionSize(self._P8_DETAIL_TABLE_ROW_HEIGHT)
        self.p8_detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p8_detail_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p8_detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p8_detail_table.setAlternatingRowColors(True)
        self.p8_detail_table.setStyleSheet('QTableWidget { font-size: 13px; } QHeaderView::section { font-size: 13px; }')
        self.p8_detail_table.doubleClicked.connect(self._p8_on_detail_double_click)
        self.p8_detail_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_layout.addWidget(self.p8_detail_table)

        # Fixed height: title(~30) + 10 rows × 32px + header(~30) + margins(~22) + spacing
        self.p8_detail_panel.setFixedHeight(10 * self._P8_DETAIL_TABLE_ROW_HEIGHT + 90)

        layout.addWidget(self.p8_detail_panel)

    def _p8_build_sector_order(self) -> list[str]:
        """Build sector card order with explicit overrides for special placements."""
        ordered = sorted(SECTOR_DATA.keys())
        for sector, anchor in self._P8_SECTOR_AFTER.items():
            if sector not in ordered or anchor not in ordered:
                continue
            ordered.remove(sector)
            ordered.insert(ordered.index(anchor) + 1, sector)
        return ordered

    def _p8_heat_bg(self, change: float | None) -> str:
        """Return a subtle heatmap background color based on % change."""
        if change is None:
            return self.theme_color('panel_background')
        if change > 2.0:
            return '#1a3a2a'
        elif change > 0.5:
            return '#162e22'
        elif change > 0:
            return '#14261e'
        elif change > -0.5:
            return '#261418'
        elif change > -2.0:
            return '#2e161a'
        else:
            return '#3a1a1e'

    def _p8_create_heat_card(self, sector: str) -> None:
        """Create a compact clickable heat card for one sector."""
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumWidth(self._P8_HEAT_CARD_MIN_WIDTH)
        card.setMaximumWidth(self._P8_HEAT_CARD_MAX_WIDTH)
        card.setFixedHeight(110)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(3)

        # Row 1: Sector name + change %
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        name_lbl = QLabel(f'<b>{sector}</b>')
        name_lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 15px; border: none;')
        change_lbl = QLabel('--')
        change_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 16px; font-weight: bold; border: none;')
        change_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(name_lbl)
        top_row.addStretch()
        top_row.addWidget(change_lbl)
        card_layout.addLayout(top_row)

        # Row 2: Ticker count
        count_lbl = QLabel(f'{len(SECTOR_DATA[sector])} tickers')
        count_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
        card_layout.addWidget(count_lbl)

        card_layout.addStretch()

        # Row 3: Top gainers
        gainers_lbl = QLabel('')
        gainers_lbl.setStyleSheet(f'color: {CLR_UP}; font-size: 12px; border: none;')
        card_layout.addWidget(gainers_lbl)

        # Row 4: Top losers
        losers_lbl = QLabel('')
        losers_lbl.setStyleSheet(f'color: {CLR_DOWN}; font-size: 12px; border: none;')
        card_layout.addWidget(losers_lbl)

        # Default card style
        self._p8_style_card(card, sector, selected=False)

        # Click handler via mouse press
        card.mousePressEvent = lambda event, s=sector: self._p8_select_sector(s)

        self.p8_heat_cards[sector] = {
            'frame': card,
            'name_lbl': name_lbl,
            'change_lbl': change_lbl,
            'count_lbl': count_lbl,
            'gainers_lbl': gainers_lbl,
            'losers_lbl': losers_lbl,
        }

    def _p8_style_card(self, card: QFrame, sector: str, *, selected: bool = False, change: float | None = None) -> None:
        """Apply heatmap background and selection border to a card."""
        bg = self._p8_heat_bg(change)
        border_color = self.theme_color('accent') if selected else self.theme_color('panel_border')
        border_width = 2 if selected else 1
        card.setStyleSheet(
            f'QFrame {{ background: {bg}; border: {border_width}px solid {border_color}; border-radius: 6px; }}'
        )

    def _p8_select_sector(self, sector: str) -> None:
        """Handle sector heat card click: show detail table."""
        prev = self._p8_selected_sector
        self._p8_selected_sector = sector

        # Restyle previous card
        if prev and prev in self.p8_heat_cards:
            prev_change = self._p8_sector_averages.get(prev)
            self._p8_style_card(self.p8_heat_cards[prev]['frame'], prev, selected=False, change=prev_change)

        # Style newly selected card
        cur_change = self._p8_sector_averages.get(sector)
        self._p8_style_card(self.p8_heat_cards[sector]['frame'], sector, selected=True, change=cur_change)

        # Populate detail table
        self._p8_populate_detail_table(sector)
        self._p8_request_detail_market_caps(SECTOR_DATA.get(sector, []))

    def _p8_populate_detail_table(self, sector: str) -> None:
        """Fill the detail panel table with the selected sector's constituents."""
        tickers = SECTOR_DATA.get(sector, [])
        avg = self._p8_sector_averages.get(sector)
        if avg is not None:
            sign = '+' if avg >= 0 else ''
            color = CLR_UP if avg >= 0 else CLR_DOWN
            self.p8_detail_title.setText(
                f"<b>{sector}</b> <span style='color:{color}; font-size: 15px;'>{sign}{avg:.2f}%</span>"
            )
        else:
            self.p8_detail_title.setText(f'<b>{sector}</b>')

        self.p8_detail_table.setRowCount(len(tickers))
        for row, ticker in enumerate(tickers):
            result = self._p8_all_results.get(ticker) or SectorTickerSnapshot()

            ticker_item = QTableWidgetItem(ticker)
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ticker_item.setForeground(self.theme_qcolor('text_primary'))
            font = ticker_item.font()
            font.setBold(True)
            ticker_item.setFont(font)
            self.p8_detail_table.setItem(row, 0, ticker_item)

            price = result.price
            price_text = f'${price:.2f}' if isinstance(price, (int, float)) else '--'
            price_item = QTableWidgetItem(price_text)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price_item.setForeground(self.theme_qcolor('text_primary') if isinstance(price, (int, float)) else QColor('#555'))
            self.p8_detail_table.setItem(row, 1, price_item)

            change = result.change
            if isinstance(change, (int, float)):
                sign = '+' if change >= 0 else ''
                change_item = QTableWidgetItem(f'{sign}{change:.2f}%')
                change_item.setForeground(QColor(CLR_UP) if change >= 0 else QColor(CLR_DOWN))
            else:
                change_item = QTableWidgetItem('--')
                change_item.setForeground(QColor('#555'))
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p8_detail_table.setItem(row, 2, change_item)

            mkt_cap = result.mkt_cap
            cap_text = fmt_num(mkt_cap) if isinstance(mkt_cap, (int, float)) and mkt_cap > 0 else '--'
            cap_item = QTableWidgetItem(cap_text)
            cap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cap_item.setForeground(QColor(self._mktcap_color(mkt_cap)) if isinstance(mkt_cap, (int, float)) and mkt_cap > 0 else QColor('#555'))
            self.p8_detail_table.setItem(row, 3, cap_item)

    def _p8_on_detail_double_click(self, index: Any) -> None:
        """Double-click a row in the detail table to jump to Charts."""
        row = index.row()
        item = self.p8_detail_table.item(row, 0)
        if item:
            self._p8_analyze_ticker(item.text())

    def _p8_grid_columns(self) -> int:
        """Choose responsive column count for heat cards."""
        viewport = self.p8_card_scroll.viewport().width() if hasattr(self, 'p8_card_scroll') else 0
        if viewport <= 0:
            return 3
        card_w = self._P8_HEAT_CARD_MIN_WIDTH + self._P8_HEAT_CARD_SPACING
        for cols in range(self._P8_MAX_GRID_COLUMNS, self._P8_MIN_GRID_COLUMNS - 1, -1):
            if viewport >= cols * card_w:
                return cols
        return self._P8_MIN_GRID_COLUMNS

    def _p8_relayout_cards(self) -> None:
        """Rebuild heat card grid for current viewport width."""
        if not hasattr(self, 'p8_card_grid'):
            return
        cols = self._p8_grid_columns()
        if cols == self.p8_column_count and self.p8_card_grid.count() == len(self.p8_sector_order):
            return
        while self.p8_card_grid.count():
            item = self.p8_card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.p8_card_container)
        for col in range(self._P8_MAX_GRID_COLUMNS):
            self.p8_card_grid.setColumnStretch(col, 0)
        for idx, sector in enumerate(self.p8_sector_order):
            card = self.p8_heat_cards[sector]['frame']
            row = idx // cols
            col = idx % cols
            self.p8_card_grid.addWidget(card, row, col)
        for col in range(cols):
            self.p8_card_grid.setColumnStretch(col, 1)
        self.p8_column_count = cols

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Relayout heat cards when the scroll viewport resizes."""
        viewport = self.p8_card_scroll.viewport() if hasattr(self, 'p8_card_scroll') else None
        if watched is viewport and event.type() == QEvent.Type.Resize:
            self._p8_relayout_cards()
        return super().eventFilter(watched, event)

    def _p8_on_show(self) -> None:
        """Refresh sector data when the tab is shown."""
        self._p8_relayout_cards()
        self._p8_request_refresh()

    def _p8_request_refresh(self, *, force: bool=False, status_text: str='Refreshing sector data...') -> bool:
        """Start a sectors refresh if it is not throttled or already running."""
        if getattr(self, 'p8_fetch_in_progress', False):
            return False
        now = datetime.datetime.now().timestamp()
        if not force and now - getattr(self, 'p8_last_fetch', 0) <= 120:
            return False
        self.p8_last_fetch = now
        self.p8_fetch_in_progress = True
        self.set_status_text(self.p8_status_lbl, status_text, status='info')
        threading.Thread(target=self._p8_fetch_all_sectors, daemon=True).start()
        return True

    def _p8_mktcap_cache_now(self) -> float:
        """Return the current timestamp for sectors market-cap freshness checks."""
        helper = getattr(self, '_p4_mktcap_cache_now', None)
        if callable(helper):
            return float(helper())
        return datetime.datetime.now(datetime.timezone.utc).timestamp()

    def _p8_mktcap_cache_ttl_seconds(self) -> float:
        """Return the reuse window for cached sectors market caps."""
        helper = getattr(self, '_p4_mktcap_cache_ttl_seconds', None)
        if callable(helper):
            return float(helper())
        return float(getattr(self, '_mktcap_cache_ttl_seconds', self._P8_MKTCAP_CACHE_TTL_SECONDS))

    def _p8_ensure_mktcap_cache_state(self) -> tuple[dict[str, Any], dict[str, float]]:
        """Ensure the shared market-cap caches exist before sectors reuse them."""
        if not hasattr(self, '_mktcap_cache') or not isinstance(self._mktcap_cache, dict):
            self._mktcap_cache = {}
        if not hasattr(self, '_mktcap_cache_ts') or not isinstance(self._mktcap_cache_ts, dict):
            self._mktcap_cache_ts = {}
        return self._mktcap_cache, self._mktcap_cache_ts

    def _p8_has_fresh_mktcap(self, ticker: Any) -> bool:
        """Return whether one cached market-cap entry is still fresh for sectors."""
        symbol = str(ticker or '').strip().upper()
        if not symbol:
            return False
        _, cache_ts = self._p8_ensure_mktcap_cache_state()
        fetched_at = cache_ts.get(symbol)
        if fetched_at is None:
            return False
        return (self._p8_mktcap_cache_now() - float(fetched_at)) < self._p8_mktcap_cache_ttl_seconds()

    def _p8_cached_mktcap(self, ticker: Any) -> Any:
        """Return the shared cached market-cap value for one ticker if present."""
        symbol = str(ticker or '').strip().upper()
        if not symbol:
            return None
        cache, _ = self._p8_ensure_mktcap_cache_state()
        return cache.get(symbol)

    def _p8_market_cap_refresh_candidates(self, tickers: list[str]) -> list[str]:
        """Return missing or stale tickers that still need sectors market-cap refreshes."""
        cache, _ = self._p8_ensure_mktcap_cache_state()
        inflight = set(getattr(self, '_p8_mktcap_inflight_tickers', set()))
        queued = set(getattr(self, '_p8_mktcap_queued_tickers', set()))
        needed = []
        for ticker in tickers:
            symbol = str(ticker or '').strip().upper()
            if not symbol:
                continue
            if symbol in inflight or symbol in queued:
                continue
            if (symbol not in cache) or (not self._p8_has_fresh_mktcap(symbol)):
                needed.append(symbol)
        return needed

    def _p8_apply_mktcap_cache_updates(self, updates: dict[str, tuple[Any, float]]) -> None:
        """Merge sector market-cap refresh results into the shared cache."""
        if not updates:
            return
        cache, cache_ts = self._p8_ensure_mktcap_cache_state()
        for ticker, payload in updates.items():
            if not isinstance(payload, tuple) or len(payload) != 2:
                continue
            mc, fetched_at = payload
            symbol = str(ticker or '').strip().upper()
            if not symbol:
                continue
            cache[symbol] = mc
            cache_ts[symbol] = float(fetched_at)

    def _p8_request_detail_market_caps(self, tickers: Any = None) -> bool:
        """Fetch market caps only for the selected-sector detail table."""
        symbols = list(tickers if isinstance(tickers, (list, tuple, set)) else [])
        needed = self._p8_market_cap_refresh_candidates(symbols)
        if not needed:
            return False
        if getattr(self, '_p8_mktcap_fetching', False):
            queued = set(getattr(self, '_p8_mktcap_queued_tickers', set()))
            queued.update(needed)
            self._p8_mktcap_queued_tickers = queued
            return False
        self._p8_mktcap_fetching = True
        self._p8_mktcap_inflight_tickers = set(needed)
        self._p8_mktcap_worker = None

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                results = client.fetch_market_caps(needed) if client is not None else MarketCapWorker(needed).fetch()
            except Exception as exc:
                logger.warning('Embedded data service sector market-cap request failed; falling back to direct worker: %s', exc)
                if hasattr(self, '_record_data_health_fallback'):
                    self._record_data_health_fallback('Sectors market caps', exc, symbols=needed)
                results = MarketCapWorker(needed).fetch()
            self._invoke_main.emit(lambda payload=results: self._p8_on_market_caps_ready(payload))

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _p8_on_market_caps_ready(self, results: Any) -> None:
        """Merge fetched market caps and refresh the selected-sector detail table."""
        self._p8_mktcap_fetching = False
        request_tickers = set(getattr(self, '_p8_mktcap_inflight_tickers', set()))
        self._p8_mktcap_inflight_tickers = set()
        self._p8_mktcap_worker = None
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Sectors market caps', results, symbols=request_tickers)
        updates = {}
        fetched_at = self._p8_mktcap_cache_now()
        results = strip_market_data_keys(results) if isinstance(results, dict) else results
        if isinstance(results, dict):
            for ticker, mc in results.items():
                symbol = str(ticker or '').strip().upper()
                if not symbol:
                    continue
                updates[symbol] = (mc, fetched_at)
                snapshot = self._p8_all_results.get(symbol)
                if snapshot is not None:
                    snapshot.mkt_cap = mc
        self._p8_apply_mktcap_cache_updates(updates)
        if self._p8_selected_sector:
            self._p8_populate_detail_table(self._p8_selected_sector)
        queued = list(getattr(self, '_p8_mktcap_queued_tickers', set()))
        self._p8_mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if ticker not in request_tickers]
            self._p8_request_detail_market_caps(remaining)

    def _p8_fetch_all_sectors(self) -> None:
        """Fetch sector prices in batch and reuse cached market caps where available."""
        all_tickers = sorted({ticker for tickers in SECTOR_DATA.values() for ticker in tickers})
        all_results = {ticker: SectorTickerSnapshot() for ticker in all_tickers}
        try:
            batch = yf.download(all_tickers, period='5d', interval='1d', group_by='ticker', progress=False, auto_adjust=False, threads=True)
            is_multi = isinstance(batch.columns, pd.MultiIndex)
            cache, _ = self._p8_ensure_mktcap_cache_state()
            for ticker in all_tickers:
                symbol = str(ticker or '').strip().upper()
                if symbol in cache:
                    all_results[ticker].mkt_cap = cache.get(symbol)
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
            self._invoke_main.emit(lambda results=all_results: self._p8_complete_refresh(results))
        except Exception as e:
            logger.error(f'Failed to fetch all sector data: {e}')
            self._invoke_main.emit(self._p8_fail_refresh)

    def _p8_complete_refresh(self, all_results: Any, mktcap_updates: Any=None) -> None:
        """Apply fetched sector data and clear the active refresh flag."""
        self.p8_fetch_in_progress = False
        self._p8_apply_mktcap_cache_updates(mktcap_updates if isinstance(mktcap_updates, dict) else {})
        self._p8_all_results = all_results
        self._p8_apply_all_data(all_results)

    def _p8_fail_refresh(self) -> None:
        """Handle a failed sector refresh and allow retries."""
        self.p8_fetch_in_progress = False
        self.set_status_text(self.p8_status_lbl, 'Sector data refresh failed', status='negative')

    def _p8_apply_all_data(self, all_results: Any) -> None:
        """Update heat cards, summary bar, and detail panel with fetched data."""
        populated = 0
        sector_averages = {}

        for sector, tickers in SECTOR_DATA.items():
            changes = []
            count = 0
            for ticker in tickers:
                result = all_results.get(ticker) or SectorTickerSnapshot()
                if isinstance(result.price, (int, float)):
                    count += 1
                if isinstance(result.change, (int, float)):
                    changes.append((ticker, float(result.change)))
            populated += count
            avg = sum(c for _, c in changes) / len(changes) if changes else None
            if avg is not None:
                sector_averages[sector] = avg
            self._p8_update_heat_card(sector, avg, changes)

        self._p8_sector_averages = sector_averages
        self._p8_update_summary_bar(sector_averages, populated)

        # Refresh detail table if a sector is selected
        if self._p8_selected_sector:
            self._p8_populate_detail_table(self._p8_selected_sector)
            cur_change = sector_averages.get(self._p8_selected_sector)
            self._p8_style_card(
                self.p8_heat_cards[self._p8_selected_sector]['frame'],
                self._p8_selected_sector, selected=True, change=cur_change
            )
            self._p8_request_detail_market_caps(SECTOR_DATA.get(self._p8_selected_sector, []))

        # Auto-select strongest sector if none selected
        if not self._p8_selected_sector and sector_averages:
            best = max(sector_averages, key=sector_averages.get)
            self._p8_select_sector(best)

        self._p8_relayout_cards()

    def _p8_update_heat_card(self, sector: str, avg_change: float | None, changes: list[tuple[str, float]]) -> None:
        """Update one heat card with sector data."""
        card_data = self.p8_heat_cards.get(sector)
        if not card_data:
            return

        # Change label
        if avg_change is not None:
            sign = '+' if avg_change >= 0 else ''
            color = CLR_UP if avg_change >= 0 else CLR_DOWN
            card_data['change_lbl'].setText(f'{sign}{avg_change:.2f}%')
            card_data['change_lbl'].setStyleSheet(f'color: {color}; font-size: 13px; font-weight: bold; border: none;')
        else:
            card_data['change_lbl'].setText('--')
            card_data['change_lbl'].setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 13px; font-weight: bold; border: none;')

        # Gainers / losers
        sorted_changes = sorted(changes, key=lambda x: x[1], reverse=True)
        if sorted_changes:
            top2 = sorted_changes[:2]
            gainers_text = '  '.join(f'{t} {c:+.1f}%' for t, c in top2)
            card_data['gainers_lbl'].setText(gainers_text)

            bot2 = sorted_changes[-2:]
            bot2.reverse()
            losers_text = '  '.join(f'{t} {c:+.1f}%' for t, c in bot2)
            card_data['losers_lbl'].setText(losers_text)
        else:
            card_data['gainers_lbl'].setText('')
            card_data['losers_lbl'].setText('')

        # Heatmap background (only if not the selected card)
        is_selected = (self._p8_selected_sector == sector)
        self._p8_style_card(card_data['frame'], sector, selected=is_selected, change=avg_change)

    def _p8_update_summary_bar(self, sector_averages: dict[str, float], populated: int) -> None:
        """Update the top summary bar labels."""
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        self.p8_summary_labels['updated'].setText(now_str)
        self.p8_summary_labels['tickers'].setText(str(populated))
        self.p8_status_lbl.setText(f'Updated {now_str}  |  {populated} tickers')

        if sector_averages:
            strongest = max(sector_averages, key=sector_averages.get)
            weakest = min(sector_averages, key=sector_averages.get)
            s_val = sector_averages[strongest]
            w_val = sector_averages[weakest]
            self.p8_summary_labels['strongest'].setText(f'{strongest} {s_val:+.2f}%')
            self.p8_summary_labels['strongest'].setStyleSheet(f'color: {CLR_UP}; font-size: 12px; font-weight: bold; border: none;')
            self.p8_summary_labels['weakest'].setText(f'{weakest} {w_val:+.2f}%')
            self.p8_summary_labels['weakest'].setStyleSheet(f'color: {CLR_DOWN}; font-size: 12px; font-weight: bold; border: none;')

            inflows = sorted(sector_averages.items(), key=lambda x: x[1], reverse=True)[:3]
            outflows = sorted(sector_averages.items(), key=lambda x: x[1])[:3]
            self.p8_summary_labels['inflows'].setText(', '.join(f'{s} {v:+.1f}%' for s, v in inflows))
            self.p8_summary_labels['inflows'].setStyleSheet(f'color: {CLR_UP}; font-size: 11px; font-weight: bold; border: none;')
            self.p8_summary_labels['outflows'].setText(', '.join(f'{s} {v:+.1f}%' for s, v in outflows))
            self.p8_summary_labels['outflows'].setStyleSheet(f'color: {CLR_DOWN}; font-size: 11px; font-weight: bold; border: none;')
        else:
            for key in ('strongest', 'weakest', 'inflows', 'outflows'):
                self.p8_summary_labels[key].setText('--')

    def _p8_analyze_ticker(self, ticker: Any) -> None:
        """Jump from sectors to Charts and load the selected ticker."""
        symbol = str(ticker or '').upper().strip()
        if not symbol:
            return
        self.p10_symbol = symbol
        if isinstance(getattr(self, 'chart_page_state', None), dict):
            self.chart_page_state = {
                **self.chart_page_state,
                'symbol': symbol,
            }
        page_index = self.stacked_widget.indexOf(self.page10) if hasattr(self, 'stacked_widget') and hasattr(self, 'page10') else 9
        target_index = page_index if page_index >= 0 else 9
        page_ready = self._page_initialized(index=target_index)
        self.switch_page(target_index)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(symbol)
        if page_ready and hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()
