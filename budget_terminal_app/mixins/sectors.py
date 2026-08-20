from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.data_service.results import strip_market_data_keys
from budget_terminal_app.sector_universe import (
    SECTORS_PAGE_DATA,
    sectors_page_symbols,
    sectors_page_unique_symbols,
)
from budget_terminal_app.widgets.table_render import SortableTableWidgetItem
from budget_terminal_app.workers.market_metrics import MarketCapWorker
from .sectors_presenters import SectorStats, calculate_sector_stats, filter_sector_rows


@dataclass
class SectorTickerSnapshot:
    price: Any=None
    mkt_cap: Any=None
    change: Any=None


class SectorsMixin:
    _P8_HEAT_CARD_MIN_WIDTH = 180
    _P8_HEAT_CARD_MAX_WIDTH = 320
    _P8_HEAT_CARD_SPACING = 8
    _P8_MAX_GRID_COLUMNS = 5
    _P8_MIN_GRID_COLUMNS = 2
    _P8_DETAIL_TABLE_ROW_HEIGHT = 24
    _P8_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0
    _P8_SECTOR_AFTER = {'Crypto': 'Utilities', 'Metals': 'Crypto'}

    def init_page8(self) -> None:
        """Build the Sectors page UI with summary bar, heat cards, and detail panel."""
        self._p8_all_results = {}
        self._p8_sector_averages = {}
        self._p8_sector_stats = {}
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
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # -- Summary bar --
        self.p8_summary_frame = QFrame()
        summary_layout = QHBoxLayout(self.p8_summary_frame)
        summary_layout.setContentsMargins(10, 4, 10, 4)
        summary_layout.setSpacing(0)

        self.p8_summary_labels = {}
        self.p8_summary_headers = {}
        self.p8_summary_separators = []
        summary_items = [
            ('updated', 'Last Updated', '--'),
            ('coverage', 'Coverage', '--'),
            ('strongest', 'Strongest', '--'),
            ('weakest', 'Weakest', '--'),
            ('leaders', 'Leaders', '--'),
            ('laggards', 'Laggards', '--'),
        ]
        for i, (key, label, default) in enumerate(summary_items):
            if i > 0:
                sep = QFrame()
                sep.setFixedWidth(1)
                summary_layout.addWidget(sep)
                self.p8_summary_separators.append(sep)

            cell = QVBoxLayout()
            cell.setContentsMargins(8, 1, 8, 1)
            cell.setSpacing(1)
            header = QLabel(label)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel(default)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(header)
            cell.addWidget(value)
            summary_layout.addLayout(cell, 1)
            self.p8_summary_headers[key] = header
            self.p8_summary_labels[key] = value

        layout.addWidget(self.p8_summary_frame)

        # -- Status label --
        self.p8_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p8_status_lbl, 'status_muted')
        self.p8_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.p8_status_lbl)

        # -- Main content: resizable heat cards + detail table --
        self.p8_main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.p8_main_splitter.setChildrenCollapsible(False)

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

        self.p8_main_splitter.addWidget(self.p8_card_scroll)

        self.p8_detail_panel = QFrame()
        detail_layout = QVBoxLayout(self.p8_detail_panel)
        detail_layout.setContentsMargins(8, 6, 8, 6)
        detail_layout.setSpacing(4)

        detail_header = QHBoxLayout()
        detail_header.setSpacing(8)
        self.p8_detail_title = QLabel('Select a sector')
        self.p8_detail_meta = QLabel('0 of 0')
        self.p8_detail_meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.p8_detail_filter = QLineEdit()
        self.p8_detail_filter.setPlaceholderText('Filter ticker or company')
        self.p8_detail_filter.setClearButtonEnabled(True)
        self.p8_detail_filter.setMaximumWidth(260)
        self.p8_detail_filter.textChanged.connect(self._p8_on_detail_filter_changed)
        detail_header.addWidget(self.p8_detail_title)
        detail_header.addStretch()
        detail_header.addWidget(self.p8_detail_meta)
        detail_header.addWidget(self.p8_detail_filter)
        detail_layout.addLayout(detail_header)

        self.p8_detail_table = QTableWidget(0, 5)
        self.p8_detail_table.setHorizontalHeaderLabels(['Ticker', 'Company', 'Price', 'Day %', 'Market Cap'])
        hh = self.p8_detail_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, 5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSortIndicator(3, Qt.SortOrder.DescendingOrder)
        self.p8_detail_table.verticalHeader().setVisible(False)
        self.p8_detail_table.verticalHeader().setDefaultSectionSize(self._P8_DETAIL_TABLE_ROW_HEIGHT)
        self.p8_detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p8_detail_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p8_detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p8_detail_table.setAlternatingRowColors(True)
        self.p8_detail_table.setSortingEnabled(True)
        self.p8_detail_table.doubleClicked.connect(self._p8_on_detail_double_click)
        self.p8_detail_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p8_detail_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        detail_layout.addWidget(self.p8_detail_table)

        self.p8_main_splitter.addWidget(self.p8_detail_panel)
        self.p8_main_splitter.setStretchFactor(0, 1)
        self.p8_main_splitter.setStretchFactor(1, 1)
        self.p8_main_splitter.setSizes([320, 300])
        layout.addWidget(self.p8_main_splitter, 1)
        self._apply_sectors_theme()

    def _p8_build_sector_order(self) -> list[str]:
        """Build sector card order with explicit overrides for special placements."""
        ordered = sorted(SECTORS_PAGE_DATA.keys())
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
        card.setFixedHeight(108)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(2)

        # Row 1: Sector name + change %
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        name_lbl = QLabel(f'<b>{sector}</b>')
        name_lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 15px; border: none;')
        change_lbl = QLabel('Avg --')
        change_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(name_lbl)
        top_row.addStretch()
        top_row.addWidget(change_lbl)
        card_layout.addLayout(top_row)

        # Row 2: Ticker count
        count_lbl = QLabel(f'{len(SECTORS_PAGE_DATA[sector])} equities • 0/{len(SECTORS_PAGE_DATA[sector])} quotes')
        card_layout.addWidget(count_lbl)

        breadth_lbl = QLabel('↑ 0   ↓ 0   • 0')
        card_layout.addWidget(breadth_lbl)

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
            'breadth_lbl': breadth_lbl,
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

        if prev != sector and hasattr(self, 'p8_detail_filter') and self.p8_detail_filter.text():
            self.p8_detail_filter.clear()

        # Restyle previous card
        if prev and prev in self.p8_heat_cards:
            prev_change = self._p8_sector_averages.get(prev)
            self._p8_style_card(self.p8_heat_cards[prev]['frame'], prev, selected=False, change=prev_change)

        # Style newly selected card
        cur_change = self._p8_sector_averages.get(sector)
        self._p8_style_card(self.p8_heat_cards[sector]['frame'], sector, selected=True, change=cur_change)

        # Populate detail table
        self._p8_populate_detail_table(sector)
        self._p8_request_detail_market_caps(sectors_page_symbols(sector))

    def _p8_on_detail_filter_changed(self, _text: str) -> None:
        """Rebuild the selected-sector detail rows for the active filter."""
        if self._p8_selected_sector:
            self._p8_populate_detail_table(self._p8_selected_sector)

    def _p8_populate_detail_table(self, sector: str) -> None:
        """Fill the detail panel table with the selected sector's constituents."""
        constituents = SECTORS_PAGE_DATA.get(sector, ())
        query = self.p8_detail_filter.text() if hasattr(self, 'p8_detail_filter') else ''
        filtered = filter_sector_rows(constituents, query)
        stats = self._p8_sector_stats.get(sector) or calculate_sector_stats(
            (constituent.symbol for constituent in constituents),
            self._p8_all_results,
        )
        avg = self._p8_sector_averages.get(sector)
        if avg is not None:
            sign = '+' if avg >= 0 else ''
            color = CLR_UP if avg >= 0 else CLR_DOWN
            self.p8_detail_title.setText(
                f"<b>{sector}</b> <span style='color:{color}; font-size: 15px;'>Avg {sign}{avg:.2f}%</span>"
            )
        else:
            self.p8_detail_title.setText(f'<b>{sector}</b>')

        unchanged_text = f' • {stats.unchanged} flat' if stats.unchanged else ''
        self.p8_detail_meta.setText(
            f'{len(filtered)} of {stats.total} • {stats.quote_count}/{stats.total} quotes '
            f'• ↑ {stats.advancers}  ↓ {stats.decliners}{unchanged_text}'
        )

        table = self.p8_detail_table
        header = table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        sorting_enabled = table.isSortingEnabled()
        table.setSortingEnabled(False)
        table.setRowCount(len(filtered))
        missing_sort = float('-inf')
        for row, constituent in enumerate(filtered):
            ticker = constituent.symbol
            result = self._p8_all_results.get(ticker) or SectorTickerSnapshot()

            ticker_item = QTableWidgetItem(ticker)
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ticker_item.setForeground(self.theme_qcolor('text_primary'))
            font = ticker_item.font()
            font.setBold(True)
            ticker_item.setFont(font)
            table.setItem(row, 0, ticker_item)

            company_item = QTableWidgetItem(constituent.name)
            company_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            company_item.setForeground(self.theme_qcolor('text_primary'))
            table.setItem(row, 1, company_item)

            price = result.price
            price_text = f'${price:.2f}' if isinstance(price, (int, float)) else '--'
            price_item = SortableTableWidgetItem(price_text)
            price_item.setData(Qt.ItemDataRole.UserRole, float(price) if isinstance(price, (int, float)) else missing_sort)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price_item.setForeground(self.theme_qcolor('text_primary') if isinstance(price, (int, float)) else self.theme_qcolor('text_muted'))
            table.setItem(row, 2, price_item)

            change = result.change
            if isinstance(change, (int, float)):
                sign = '+' if change >= 0 else ''
                change_item = SortableTableWidgetItem(f'{sign}{change:.2f}%')
                change_item.setData(Qt.ItemDataRole.UserRole, float(change))
                change_item.setForeground(QColor(CLR_UP) if change >= 0 else QColor(CLR_DOWN))
            else:
                change_item = SortableTableWidgetItem('--')
                change_item.setData(Qt.ItemDataRole.UserRole, missing_sort)
                change_item.setForeground(self.theme_qcolor('text_muted'))
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, change_item)

            mkt_cap = result.mkt_cap
            valid_mkt_cap = isinstance(mkt_cap, (int, float)) and mkt_cap > 0
            cap_text = f'${fmt_num(mkt_cap)}' if valid_mkt_cap else '--'
            cap_item = SortableTableWidgetItem(cap_text)
            cap_item.setData(Qt.ItemDataRole.UserRole, float(mkt_cap) if valid_mkt_cap else missing_sort)
            cap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cap_item.setForeground(QColor(self._mktcap_color(mkt_cap)) if valid_mkt_cap else self.theme_qcolor('text_muted'))
            table.setItem(row, 4, cap_item)
        table.setSortingEnabled(sorting_enabled)
        if sorting_enabled and sort_column >= 0:
            table.sortItems(sort_column, sort_order)

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
        if getattr(self, '_p8_render_pending', False) and getattr(self, '_p8_all_results', None) is not None:
            self._p8_render_pending = False
            self._p8_apply_all_data(self._p8_all_results)
        else:
            self._p8_relayout_cards()
        self._p8_request_refresh()

    def _p8_page_is_visible(self) -> bool:
        page = getattr(self, 'page8', None)
        page_check = getattr(self, '_is_current_page', None)
        if page is None or not callable(page_check):
            return True
        try:
            return bool(page_check(page))
        except (AttributeError, RuntimeError):
            return False

    def _p8_request_refresh(self, *, force: bool=False, status_text: str='Refreshing sector data...') -> bool:
        """Start a sectors refresh if it is not throttled or already running."""
        if getattr(self, '_refresh_shutdown', False):
            return False
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
            if not getattr(self, '_refresh_shutdown', False):
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
                    snapshot.mkt_cap = mc.get('size_value') if isinstance(mc, dict) else mc
        self._p8_apply_mktcap_cache_updates(updates)
        if self._p8_selected_sector and self._p8_page_is_visible():
            self._p8_populate_detail_table(self._p8_selected_sector)
        elif self._p8_selected_sector:
            self._p8_render_pending = True
        queued = list(getattr(self, '_p8_mktcap_queued_tickers', set()))
        self._p8_mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if ticker not in request_tickers]
            self._p8_request_detail_market_caps(remaining)

    def _p8_fetch_all_sectors(self) -> None:
        """Fetch sector prices in batch and reuse cached market caps where available."""
        all_tickers = sectors_page_unique_symbols()
        all_results = {ticker: SectorTickerSnapshot() for ticker in all_tickers}
        try:
            batch = yf.download(all_tickers, period='5d', interval='1d', group_by='ticker', progress=False, auto_adjust=False, threads=True)
            is_multi = isinstance(batch.columns, pd.MultiIndex)
            cache, _ = self._p8_ensure_mktcap_cache_state()
            for ticker in all_tickers:
                symbol = str(ticker or '').strip().upper()
                if symbol in cache:
                    cached_value = cache.get(symbol)
                    all_results[ticker].mkt_cap = (
                        cached_value.get('size_value')
                        if isinstance(cached_value, dict)
                        else cached_value
                    )
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
            if not getattr(self, '_refresh_shutdown', False):
                self._invoke_main.emit(lambda results=all_results: self._p8_complete_refresh(results))
        except Exception as e:
            logger.error(f'Failed to fetch all sector data: {e}')
            if not getattr(self, '_refresh_shutdown', False):
                self._invoke_main.emit(self._p8_fail_refresh)

    def _p8_complete_refresh(self, all_results: Any, mktcap_updates: Any=None) -> None:
        """Apply fetched sector data and clear the active refresh flag."""
        self.p8_fetch_in_progress = False
        self._p8_apply_mktcap_cache_updates(mktcap_updates if isinstance(mktcap_updates, dict) else {})
        self._p8_all_results = all_results
        if self._p8_page_is_visible():
            self._p8_render_pending = False
            self._p8_apply_all_data(all_results)
        else:
            self._p8_render_pending = True

    def _p8_fail_refresh(self) -> None:
        """Handle a failed sector refresh and allow retries."""
        self.p8_fetch_in_progress = False
        self.set_status_text(self.p8_status_lbl, 'Sector data refresh failed', status='negative')

    def _p8_apply_all_data(self, all_results: Any) -> None:
        """Update heat cards, summary bar, and detail panel with fetched data."""
        populated = 0
        sector_averages = {}
        sector_stats = {}

        for sector in SECTORS_PAGE_DATA:
            stats = calculate_sector_stats(sectors_page_symbols(sector), all_results)
            sector_stats[sector] = stats
            populated += stats.quote_count
            avg = stats.average_change
            if avg is not None:
                sector_averages[sector] = avg
            self._p8_update_heat_card(sector, stats)

        self._p8_sector_averages = sector_averages
        self._p8_sector_stats = sector_stats
        self._p8_update_summary_bar(sector_averages, sector_stats, populated)

        # Refresh detail table if a sector is selected
        if self._p8_selected_sector:
            self._p8_populate_detail_table(self._p8_selected_sector)
            cur_change = sector_averages.get(self._p8_selected_sector)
            self._p8_style_card(
                self.p8_heat_cards[self._p8_selected_sector]['frame'],
                self._p8_selected_sector, selected=True, change=cur_change
            )
            self._p8_request_detail_market_caps(sectors_page_symbols(self._p8_selected_sector))

        # Auto-select strongest sector if none selected
        if not self._p8_selected_sector and sector_averages:
            best = max(sector_averages, key=sector_averages.get)
            self._p8_select_sector(best)

        self._p8_relayout_cards()

    def _p8_update_heat_card(self, sector: str, stats: SectorStats) -> None:
        """Update one heat card with coverage, breadth, and mover data."""
        card_data = self.p8_heat_cards.get(sector)
        if not card_data:
            return

        avg_change = stats.average_change
        if avg_change is not None:
            sign = '+' if avg_change >= 0 else ''
            color = CLR_UP if avg_change >= 0 else CLR_DOWN
            card_data['change_lbl'].setText(f'Avg {sign}{avg_change:.2f}%')
            card_data['change_lbl'].setStyleSheet(f'color: {color}; font-size: 13px; font-weight: bold; border: none;')
        else:
            card_data['change_lbl'].setText('Avg --')
            card_data['change_lbl'].setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 13px; font-weight: bold; border: none;')

        card_data['count_lbl'].setText(f'{stats.total} equities • {stats.quote_count}/{stats.total} quotes')
        card_data['breadth_lbl'].setText(f'↑ {stats.advancers}   ↓ {stats.decliners}   • {stats.unchanged}')

        def _mover_html(label: str, movers: tuple[tuple[str, float], ...]) -> str:
            if not movers:
                return ''
            values = '  '.join(
                f"<span style='color:{CLR_UP if change >= 0 else CLR_DOWN}'>{ticker} {change:+.1f}%</span>"
                for ticker, change in movers
            )
            muted = self.theme_color('text_muted')
            return f"<span style='color:{muted}'>{label}</span>  {values}"

        card_data['gainers_lbl'].setText(_mover_html('Leaders', stats.leaders))
        card_data['losers_lbl'].setText(_mover_html('Laggards', stats.laggards))

        is_selected = (self._p8_selected_sector == sector)
        self._p8_style_card(card_data['frame'], sector, selected=is_selected, change=avg_change)

    def _p8_update_summary_bar(
        self,
        sector_averages: dict[str, float],
        sector_stats: dict[str, SectorStats],
        populated: int,
    ) -> None:
        """Update the top summary bar labels."""
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        total_memberships = sum(stats.total for stats in sector_stats.values())
        unique_symbols = len(sectors_page_unique_symbols())
        self.p8_summary_labels['updated'].setText(now_str)
        self.p8_summary_labels['coverage'].setText(f'{populated}/{total_memberships}')
        self.p8_summary_labels['coverage'].setToolTip(
            f'{unique_symbols} unique symbols across {total_memberships} sector slots'
        )
        self.set_status_text(
            self.p8_status_lbl,
            f'Updated {now_str}  |  {populated}/{total_memberships} quotes  |  {unique_symbols} unique symbols',
            status='positive' if populated == total_memberships else 'warning',
        )

        if sector_averages:
            strongest = max(sector_averages, key=sector_averages.get)
            weakest = min(sector_averages, key=sector_averages.get)
            s_val = sector_averages[strongest]
            w_val = sector_averages[weakest]
            self.p8_summary_labels['strongest'].setText(f'{strongest} {s_val:+.2f}%')
            self.p8_summary_labels['strongest'].setStyleSheet(f'color: {CLR_UP}; font-size: 12px; font-weight: bold; border: none;')
            self.p8_summary_labels['weakest'].setText(f'{weakest} {w_val:+.2f}%')
            self.p8_summary_labels['weakest'].setStyleSheet(f'color: {CLR_DOWN}; font-size: 12px; font-weight: bold; border: none;')

            leaders = sorted(sector_averages.items(), key=lambda x: x[1], reverse=True)[:3]
            laggards = sorted(sector_averages.items(), key=lambda x: x[1])[:3]
            self.p8_summary_labels['leaders'].setText(', '.join(f'{s} {v:+.1f}%' for s, v in leaders))
            self.p8_summary_labels['leaders'].setStyleSheet(f'color: {CLR_UP}; font-size: 11px; font-weight: bold; border: none;')
            self.p8_summary_labels['laggards'].setText(', '.join(f'{s} {v:+.1f}%' for s, v in laggards))
            self.p8_summary_labels['laggards'].setStyleSheet(f'color: {CLR_DOWN}; font-size: 11px; font-weight: bold; border: none;')
            for key in ('strongest', 'weakest', 'leaders', 'laggards'):
                self.p8_summary_labels[key].setToolTip(self.p8_summary_labels[key].text())
        else:
            for key in ('strongest', 'weakest', 'leaders', 'laggards'):
                self.p8_summary_labels[key].setText('--')
                self.p8_summary_labels[key].setStyleSheet(
                    f'color: {self.theme_color("text_muted")}; font-size: 12px; font-weight: bold; border: none;'
                )

    def _apply_sectors_theme(self) -> None:
        """Refresh all page-specific sector surfaces after a theme change."""
        if not hasattr(self, 'p8_summary_frame'):
            return
        panel_style = (
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        self.p8_summary_frame.setStyleSheet(panel_style)
        self.p8_detail_panel.setStyleSheet(panel_style)
        for separator in self.p8_summary_separators:
            separator.setStyleSheet(f'background: {self.theme_color("panel_border")}; border: none;')
        for header in self.p8_summary_headers.values():
            header.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
        for key in ('updated', 'coverage'):
            self.p8_summary_labels[key].setStyleSheet(
                f'color: {self.theme_color("text_primary")}; font-size: 15px; font-weight: bold; border: none;'
            )
        self.p8_detail_title.setStyleSheet(
            f'font-size: 18px; font-weight: bold; color: {self.theme_color("warning")}; '
            f'border: none; padding: 2px 0;'
        )
        self.p8_detail_meta.setStyleSheet(
            f'color: {self.theme_color("text_muted")}; font-size: 11px; border: none;'
        )
        self.p8_main_splitter.setStyleSheet(
            f'QSplitter::handle {{ background: {self.theme_color("panel_border")}; border-radius: 2px; }} '
            f'QSplitter::handle:hover {{ background: {self.theme_color("accent")}; }}'
        )
        self.p8_detail_table.setStyleSheet(
            'QTableWidget { font-size: 13px; } QHeaderView::section { font-size: 13px; }'
        )
        for sector, card_data in self.p8_heat_cards.items():
            card_data['name_lbl'].setStyleSheet(
                f'color: {self.theme_color("text_primary")}; font-size: 15px; border: none;'
            )
            if self._p8_sector_averages.get(sector) is None:
                card_data['change_lbl'].setStyleSheet(
                    f'color: {self.theme_color("text_muted")}; font-size: 13px; font-weight: bold; border: none;'
                )
            for key in ('count_lbl', 'breadth_lbl', 'gainers_lbl', 'losers_lbl'):
                card_data[key].setStyleSheet(
                    f'color: {self.theme_color("text_muted")}; font-size: 11px; border: none;'
                )
            change = self._p8_sector_averages.get(sector)
            self._p8_style_card(
                card_data['frame'],
                sector,
                selected=self._p8_selected_sector == sector,
                change=change,
            )
        if self._p8_selected_sector:
            self._p8_populate_detail_table(self._p8_selected_sector)

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

        def _apply_chart_symbol() -> None:
            if hasattr(self, 'p10_symbol_input'):
                self.p10_symbol_input.setText(symbol)
            if page_ready and hasattr(self, '_p10_load_from_input'):
                self._p10_load_from_input()

        self._run_after_page_built(target_index, _apply_chart_symbol)
