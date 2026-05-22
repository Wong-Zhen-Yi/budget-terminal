from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.crypto import CryptoMarketWorker


class CryptoMixin:
    P19_HEATMAP_LIMIT = 30
    P19_HEATMAP_COLUMNS = 6
    P19_NEWS_LIMIT = 10

    def init_page19(self) -> None:
        """Build the Crypto market dashboard page."""
        self._p19_thread: QThread | None = None
        self._p19_worker: CryptoMarketWorker | None = None
        self._p19_last_payload: dict[str, Any] = {}
        self._p19_progress: dict[str, str] = {}
        self._p19_watchlist_load_guard = False
        self._p19_panel_widgets: list[QFrame] = []
        self._p19_table_widgets: list[QTableWidget] = []
        self.p19_metric_widgets: dict[str, tuple[QLabel, QLabel]] = {}

        layout = QVBoxLayout(self.page19)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        layout.addWidget(self._p19_build_toolbar())
        layout.addLayout(self._p19_build_kpi_strip())
        layout.addWidget(self._p19_build_main_panel(), 3)
        layout.addWidget(self._p19_build_bottom_panels(), 2)

        self._p19_set_loading_state()
        self._p19_apply_styles()
        QTimer.singleShot(0, self._p19_refresh_data)

    def _p19_build_toolbar(self) -> QFrame:
        toolbar = self._p19_make_panel()
        toolbar.setFixedHeight(42)
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        title = QLabel('Crypto Market')
        self.set_theme_role(title, 'page_title')
        row.addWidget(title)

        row.addStretch()

        self.p19_refresh_status = QLabel('Loading crypto market data...')
        self.set_theme_role(self.p19_refresh_status, 'status_muted')
        row.addWidget(self.p19_refresh_status)

        self.p19_refresh_btn = QPushButton('Refresh')
        self.p19_export_btn = QPushButton('Export')
        self.set_theme_variant(self.p19_refresh_btn, 'accent')
        self.p19_refresh_btn.clicked.connect(self._p19_refresh_data)
        self.p19_export_btn.clicked.connect(self._p19_export_snapshot)
        row.addWidget(self.p19_refresh_btn)
        row.addWidget(self.p19_export_btn)
        return toolbar

    def _p19_build_kpi_strip(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        metrics = [
            ('BTC', '--', 'Loading', 'muted'),
            ('ETH', '--', 'Loading', 'muted'),
            ('SOL', '--', 'Loading', 'muted'),
            ('Total Market Cap', '--', 'Loading', 'muted'),
            ('Fear & Greed', '--', 'Loading', 'muted'),
            ('24h Volume', '--', 'Loading', 'muted'),
        ]
        for label, value, change, status in metrics:
            row.addWidget(self._p19_metric_tile(label, value, change, status), 1)
        return row

    def _p19_build_main_panel(self) -> QFrame:
        panel = self._p19_build_heatmap_panel()
        panel.setMinimumHeight(200)
        return panel

    def _p19_build_bottom_panels(self) -> QWidget:
        container = QWidget()
        container.setMinimumHeight(150)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        watch_panel = self._p19_make_panel()
        watch_layout = QVBoxLayout(watch_panel)
        watch_layout.setContentsMargins(8, 6, 8, 6)
        watch_layout.setSpacing(4)
        watch_layout.addWidget(self._p19_section_title('Watchlist / Movers'))
        self.p19_watchlist_table = self._p19_make_table(['Symbol', 'Last', '24h', 'Vol', 'Mkt Cap'])
        watch_layout.addWidget(self.p19_watchlist_table, 1)

        news_panel = self._p19_make_panel()
        news_layout = QVBoxLayout(news_panel)
        news_layout.setContentsMargins(8, 6, 8, 6)
        news_layout.setSpacing(4)
        news_layout.addWidget(self._p19_section_title('Crypto News Feed'))
        self.p19_news_table = self._p19_make_table(['Time', 'Headline', 'Tone'])
        news_layout.addWidget(self.p19_news_table, 1)

        proxies_panel = self._p19_make_panel()
        proxies_layout = QVBoxLayout(proxies_panel)
        proxies_layout.setContentsMargins(8, 6, 8, 6)
        proxies_layout.setSpacing(4)
        proxies_layout.addWidget(self._p19_section_title('ETF / Equity Proxies'))
        self.p19_proxy_table = self._p19_make_table(['Ticker', 'Type', 'AUM / Mkt Cap', '1D'])
        proxies_layout.addWidget(self.p19_proxy_table, 1)

        row.addWidget(watch_panel, 1)
        row.addWidget(news_panel, 2)
        row.addWidget(proxies_panel, 1)
        return container

    def _p19_build_heatmap_panel(self) -> QFrame:
        panel = self._p19_make_panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.addWidget(self._p19_section_title('Top 30 Cryptocurrencies'))
        title_row.addStretch()
        self.p19_heatmap_status = QLabel('Live coverage --/30 | Updated --')
        self.p19_heatmap_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.p19_heatmap_status, 'status_muted')
        title_row.addWidget(self.p19_heatmap_status)
        layout.addLayout(title_row)
        layout.addWidget(self._p19_build_heatmap(), 1)
        return panel

    def _p19_build_heatmap(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.p19_heatmap_by_rank: dict[int, QLabel] = {}
        self.p19_heatmap_cells: list[QLabel] = []
        for rank in range(1, self.P19_HEATMAP_LIMIT + 1):
            row = (rank - 1) // self.P19_HEATMAP_COLUMNS
            col = (rank - 1) % self.P19_HEATMAP_COLUMNS
            label = QLabel(f'#{rank}\n--\n--')
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(26)
            label.setWordWrap(True)
            label.setProperty('bt_change', 'muted')
            label.setProperty('bt_intensity', 0.0)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            grid.addWidget(label, row, col)
            self.p19_heatmap_cells.append(label)
            self.p19_heatmap_by_rank[rank] = label
        for col in range(self.P19_HEATMAP_COLUMNS):
            grid.setColumnStretch(col, 1)
        for row in range((self.P19_HEATMAP_LIMIT + self.P19_HEATMAP_COLUMNS - 1) // self.P19_HEATMAP_COLUMNS):
            grid.setRowStretch(row, 1)
        return widget

    def _p19_metric_tile(self, label: str, value: str, change: str, status: str) -> QFrame:
        frame = self._p19_make_panel()
        frame.setFixedHeight(54)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)
        label_widget = QLabel(label)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(label_widget, 'status_muted')
        value_widget = QLabel(value)
        value_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_widget.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 16px; font-weight: 700; border: none;')
        change_widget = QLabel(change)
        change_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        change_widget.setProperty('bt_status', status)
        change_widget.setStyleSheet(f'color: {self.status_color(status)}; border: none; font-weight: 700;')
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        layout.addWidget(change_widget)
        self.p19_metric_widgets[label] = (value_widget, change_widget)
        return frame

    def _p19_make_panel(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._p19_panel_widgets.append(frame)
        return frame

    def _p19_section_title(self, text: str) -> QLabel:
        label = QLabel(f'<b>{text}</b>')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_theme_role(label, 'section_title')
        return label

    def _p19_make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(20)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(False)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        table.horizontalHeader().setStretchLastSection(True)
        for col in range(len(headers) - 1):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        self._p19_table_widgets.append(table)
        return table

    def _p19_set_loading_state(self) -> None:
        self._p19_set_table_rows(self.p19_watchlist_table, [('Loading...', '--', '--', '--', '--')])
        self._p19_set_table_rows(self.p19_news_table, [('--', 'Loading live market news...', '--')])
        self._p19_set_table_rows(self.p19_proxy_table, [('Loading...', '--', '--', '--')])
        self._p19_set_refresh_status('Loading crypto market data...')
        self._p19_progress = {
            'heatmap': 'pending',
            'quotes': 'pending',
            'market': 'pending',
            'news': 'pending',
        }

    def _p19_set_table_rows(self, table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        if table is getattr(self, 'p19_watchlist_table', None):
            self._p19_watchlist_load_guard = True
        table.setRowCount(len(rows))
        try:
            for row_index, row in enumerate(rows):
                for col_index, value in enumerate(row):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if value.startswith('+') or value == 'Bullish':
                        item.setForeground(QColor(self.theme_color('accent_positive')))
                    elif value.startswith('-'):
                        item.setForeground(QColor(self.theme_color('accent_negative')))
                    elif value == 'Mixed':
                        item.setForeground(QColor(self.theme_color('warning')))
                    else:
                        item.setForeground(QColor(self.theme_color('text_primary')))
                    table.setItem(row_index, col_index, item)
            table.resizeRowsToContents()
        finally:
            if table is getattr(self, 'p19_watchlist_table', None):
                self._p19_watchlist_load_guard = False

    def _p19_set_refresh_status(self, text: str) -> None:
        if hasattr(self, 'p19_refresh_status'):
            self.p19_refresh_status.setText(text)

    def _p19_merge_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        incoming = payload if isinstance(payload, dict) else {}
        merged = dict(getattr(self, '_p19_last_payload', {}) if isinstance(getattr(self, '_p19_last_payload', {}), dict) else {})
        for key, value in incoming.items():
            if key == 'progress' and isinstance(value, dict):
                progress = dict(getattr(self, '_p19_progress', {}) if isinstance(getattr(self, '_p19_progress', {}), dict) else {})
                progress.update(value)
                self._p19_progress = progress
                merged[key] = dict(progress)
            else:
                merged[key] = value
        if 'progress' not in merged:
            merged['progress'] = dict(getattr(self, '_p19_progress', {}))
        self._p19_last_payload = merged
        return merged

    def _p19_refresh_data(self) -> bool:
        thread = getattr(self, '_p19_thread', None)
        if thread is not None and thread.isRunning():
            self._p19_set_refresh_status('Crypto refresh already running...')
            return False
        self._p19_progress = {
            'heatmap': 'pending',
            'quotes': 'pending',
            'market': 'pending',
            'news': 'pending',
        }
        self._p19_set_refresh_status('Fetching live crypto market data...')
        if hasattr(self, 'p19_heatmap_status'):
            self.p19_heatmap_status.setText('Live coverage --/30 | Loading...')
        self.p19_refresh_btn.setEnabled(False)
        worker = CryptoMarketWorker()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.partial.connect(self._p19_on_partial_data)
        worker.finished.connect(self._p19_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p19_on_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._p19_on_thread_finished)
        self._p19_worker = worker
        self._p19_thread = thread
        thread.start()
        return True

    def _p19_on_partial_data(self, payload: dict[str, Any]) -> None:
        incoming = payload if isinstance(payload, dict) else {}
        merged = self._p19_merge_payload(incoming)
        self._p19_apply_payload(merged, updated_keys=set(incoming.keys()), partial=True)

    def _p19_on_data(self, payload: dict[str, Any]) -> None:
        merged = self._p19_merge_payload(payload if isinstance(payload, dict) else {})
        self._p19_apply_payload(merged, partial=False)

    def _p19_on_error(self, message: str) -> None:
        self._p19_set_refresh_status(f'Crypto data refresh failed: {message}')

    def _p19_on_thread_finished(self) -> None:
        worker = getattr(self, '_p19_worker', None)
        if worker is not None:
            worker.deleteLater()
            self._p19_worker = None
        thread = getattr(self, '_p19_thread', None)
        if thread is not None:
            thread.deleteLater()
            self._p19_thread = None
        if hasattr(self, 'p19_refresh_btn'):
            self.p19_refresh_btn.setEnabled(True)

    def _p19_apply_payload(self, payload: dict[str, Any], updated_keys: set[str] | None = None, *, partial: bool = False) -> None:
        quotes = payload.get('quotes', {}) if isinstance(payload.get('quotes'), dict) else {}
        global_data = payload.get('global', {}) if isinstance(payload.get('global'), dict) else {}
        fear_greed = payload.get('fear_greed', {}) if isinstance(payload.get('fear_greed'), dict) else {}
        active_keys = set(updated_keys or ())
        full_update = updated_keys is None
        if full_update or active_keys.intersection({'quotes', 'global', 'fear_greed'}):
            self._p19_update_kpis(quotes, global_data, fear_greed)
        if full_update or 'quotes' in active_keys:
            self._p19_update_watchlist(quotes)
            self._p19_update_proxy_table(quotes)
        if full_update or 'heatmap' in active_keys:
            self._p19_update_heatmap(payload.get('heatmap') if isinstance(payload.get('heatmap'), dict) else {})
        if full_update or 'news' in active_keys:
            self._p19_update_news(payload.get('news') or [])
        fetched_at = payload.get('fetched_at') or datetime.datetime.now().isoformat(timespec='seconds')
        if partial:
            self._p19_set_refresh_status(f'Crypto data loading... {self._p19_loaded_stage_count()}/4 stages ready')
        else:
            if self._p19_has_unavailable_stage():
                self._p19_set_refresh_status(f'Live partial data at {fetched_at[-8:]}')
            else:
                self._p19_set_refresh_status(f'Live data refreshed at {fetched_at[-8:]}')

    def _p19_loaded_stage_count(self) -> int:
        progress = getattr(self, '_p19_progress', {}) if isinstance(getattr(self, '_p19_progress', {}), dict) else {}
        return sum(1 for value in progress.values() if value in {'loaded', 'unavailable'})

    def _p19_has_unavailable_stage(self) -> bool:
        progress = getattr(self, '_p19_progress', {}) if isinstance(getattr(self, '_p19_progress', {}), dict) else {}
        return any(value == 'unavailable' for value in progress.values())

    def _p19_update_kpis(self, quotes: dict[str, Any], global_data: dict[str, Any], fear_greed: dict[str, Any]) -> None:
        for key in ('BTC', 'ETH', 'SOL'):
            quote = quotes.get(key, {}) if isinstance(quotes.get(key), dict) else {}
            self._p19_set_metric(key, self._p19_format_price(quote.get('price')), self._p19_format_pct(quote.get('change_pct')), self._p19_status_for_change(quote.get('change_pct')))
        self._p19_set_metric(
            'Total Market Cap',
            self._p19_format_money(global_data.get('market_cap')),
            self._p19_format_pct(global_data.get('change_pct')),
            self._p19_status_for_change(global_data.get('change_pct')),
        )
        fg_value = fear_greed.get('value')
        fg_label = fear_greed.get('classification') or '--'
        fg_change = f'{fg_label} - {fear_greed.get("source", "Alternative.me")}' if fg_value is not None else '--'
        self._p19_set_metric('Fear & Greed', '--' if fg_value is None else f'{fg_value:.0f}', fg_change, 'warning' if fg_value is not None else 'muted')
        self._p19_set_metric('24h Volume', self._p19_format_money(global_data.get('volume_24h')), 'CoinGecko global', 'secondary')

    def _p19_set_metric(self, label: str, value: str, change: str, status: str) -> None:
        widgets = self.p19_metric_widgets.get(label)
        if not widgets:
            return
        value_widget, change_widget = widgets
        value_widget.setText(value)
        change_widget.setText(change)
        change_widget.setStyleSheet(f'color: {self.status_color(status)}; border: none; font-weight: 700;')

    def _p19_update_watchlist(self, quotes: dict[str, Any]) -> None:
        order = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'COIN', 'MSTR', 'BMNR', 'IBIT', 'ETHA']
        rows = []
        for label in order:
            quote = quotes.get(label, {}) if isinstance(quotes.get(label), dict) else {}
            rows.append((
                label,
                self._p19_format_price(quote.get('price')),
                self._p19_format_pct(quote.get('change_pct')),
                self._p19_format_money(quote.get('volume'), compact=True),
                self._p19_format_money(quote.get('market_cap'), compact=True),
            ))
        self._p19_set_table_rows(self.p19_watchlist_table, rows)

    def _p19_update_proxy_table(self, quotes: dict[str, Any]) -> None:
        types = {
            'IBIT': 'Spot BTC ETF',
            'ETHA': 'Spot ETH ETF',
            'COIN': 'Exchange',
            'MSTR': 'BTC treasury',
            'BITQ': 'Crypto equity ETF',
        }
        rows = []
        for label in ('IBIT', 'ETHA', 'COIN', 'MSTR', 'BITQ'):
            quote = quotes.get(label, {}) if isinstance(quotes.get(label), dict) else {}
            rows.append((
                label,
                types[label],
                self._p19_format_money(quote.get('market_cap'), compact=True),
                self._p19_format_pct(quote.get('change_pct')),
            ))
        self._p19_set_table_rows(self.p19_proxy_table, rows)

    def _p19_update_heatmap(self, heatmap: dict[str, Any]) -> None:
        tiles = heatmap.get('tiles') if isinstance(heatmap, dict) else []
        sorted_tiles = sorted(
            [tile for tile in tiles if isinstance(tile, dict)],
            key=lambda tile: self._p19_rank_sort_value(tile.get('rank')),
        )[:len(getattr(self, 'p19_heatmap_cells', [])) or self.P19_HEATMAP_LIMIT]
        for index, cell in getattr(self, 'p19_heatmap_by_rank', {}).items():
            tile = sorted_tiles[index - 1] if index - 1 < len(sorted_tiles) else {}
            rank = tile.get('rank') or index
            symbol = str(tile.get('symbol') or '').strip().upper()
            name = str(tile.get('name') or symbol or '').strip()
            price = tile.get('price')
            market_cap = tile.get('market_cap')
            volume = tile.get('volume')
            source = str(tile.get('source') or '--').strip()
            change = tile.get('change_pct')
            status = self._p19_status_for_change(change)
            intensity = self._p19_heatmap_intensity(change)
            if symbol:
                cell.setText(
                    f'#{rank} {symbol}\n'
                    f'{self._p19_format_price(price)}  {self._p19_format_pct(change)}\n'
                    f'{self._p19_format_money(market_cap, compact=True)}'
                )
                cell.setToolTip(
                    '\n'.join(part for part in (
                        f'Rank: #{rank}',
                        f'Name: {name or symbol}',
                        f'Symbol: {symbol}',
                        f'Price: {self._p19_format_price(price)}',
                        f'24h: {self._p19_format_pct(change)}',
                        f'Market cap: {self._p19_format_money(market_cap)}',
                        f'Volume: {self._p19_format_money(volume)}',
                        f'Source: {source}',
                    ) if part)
                )
                cell.setAccessibleName(name or symbol)
            else:
                cell.setText(f'#{index}\n--\n--')
                cell.setToolTip('Top cryptocurrency data has not loaded yet.')
            cell.setProperty('bt_change', status)
            cell.setProperty('bt_intensity', intensity)
        coverage = heatmap.get('coverage') if isinstance(heatmap, dict) else {}
        loaded = coverage.get('loaded') if isinstance(coverage, dict) else None
        total = coverage.get('total') if isinstance(coverage, dict) else None
        updated_at = str(heatmap.get('updated_at') or '').strip() if isinstance(heatmap, dict) else ''
        coverage_text = f'{loaded}/{total}' if isinstance(loaded, int) and isinstance(total, int) else '--'
        updated_text = updated_at[-8:] if updated_at else '--'
        if hasattr(self, 'p19_heatmap_status'):
            self.p19_heatmap_status.setText(f'Live coverage {coverage_text} | Updated {updated_text}')
        self._p19_apply_styles()

    @staticmethod
    def _p19_rank_sort_value(value: Any) -> int:
        try:
            return int(float(value))
        except Exception:
            return 999

    def _p19_update_news(self, articles: list[dict[str, Any]]) -> None:
        rows = []
        for article in articles[:self.P19_NEWS_LIMIT]:
            title = str(article.get('title') or article.get('headline') or '').strip()
            if not title:
                continue
            tone = self._p19_news_tone(title)
            rows.append((str(article.get('time') or '--'), title, tone))
        if not rows:
            rows = [('--', 'No crypto-related keyless news returned yet.', '--')]
        self._p19_set_table_rows(self.p19_news_table, rows)

    def _p19_export_snapshot(self) -> None:
        payload = getattr(self, '_p19_last_payload', {}) if isinstance(getattr(self, '_p19_last_payload', {}), dict) else {}
        quotes = payload.get('quotes', {}) if isinstance(payload.get('quotes'), dict) else {}
        lines = [
            'Budget Terminal Crypto Market Snapshot',
            f'Refreshed: {payload.get("fetched_at") or "--"}',
        ]
        for label in ('BTC', 'ETH', 'SOL'):
            quote = quotes.get(label, {}) if isinstance(quotes.get(label), dict) else {}
            lines.append(f'{label} {self._p19_format_price(quote.get("price"))} {self._p19_format_pct(quote.get("change_pct"))}')
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText('\n'.join(lines))
        self._p19_set_refresh_status('Snapshot copied to clipboard')

    def _p19_format_price(self, value: Any) -> str:
        try:
            number = float(value)
        except Exception:
            return '--'
        if not math.isfinite(number):
            return '--'
        if number >= 1000:
            return f'${number:,.0f}'
        if number >= 1:
            return f'${number:,.2f}'
        return f'${number:,.4f}'

    def _p19_format_money(self, value: Any, *, compact: bool = False) -> str:
        try:
            number = float(value)
        except Exception:
            return '--'
        if not math.isfinite(number):
            return '--'
        abs_number = abs(number)
        if abs_number >= 1_000_000_000_000:
            return f'${number / 1_000_000_000_000:.2f}T'
        if abs_number >= 1_000_000_000:
            return f'${number / 1_000_000_000:.2f}B'
        if abs_number >= 1_000_000:
            return f'${number / 1_000_000:.1f}M'
        if compact and abs_number >= 1_000:
            return f'${number / 1_000:.1f}K'
        return f'${number:,.0f}'

    def _p19_format_pct(self, value: Any) -> str:
        try:
            number = float(value)
        except Exception:
            return '--'
        if not math.isfinite(number):
            return '--'
        return f'{number:+.2f}%'

    def _p19_status_for_change(self, value: Any) -> str:
        try:
            return 'positive' if float(value) >= 0 else 'negative'
        except Exception:
            return 'muted'

    def _p19_news_tone(self, title: str) -> str:
        lowered = title.casefold()
        if any(word in lowered for word in ('surge', 'rally', 'gain', 'record', 'inflow', 'approves', 'breakout')):
            return 'Bullish'
        if any(word in lowered for word in ('fall', 'drop', 'outflow', 'probe', 'hack', 'lawsuit', 'selloff')):
            return 'Bearish'
        return 'Neutral'

    def _p19_heatmap_intensity(self, value: Any) -> float:
        try:
            number = abs(float(value))
        except Exception:
            return 0.0
        if not math.isfinite(number):
            return 0.0
        return max(0.0, min(number / 5.0, 1.0))

    def _p19_heatmap_background(self, status: str, intensity: Any) -> str:
        try:
            amount = float(intensity)
        except Exception:
            amount = 0.0
        amount = max(0.0, min(amount, 1.0))
        if status == 'positive':
            return self._p19_mix_color(self.theme_color('panel_background'), self.theme_color('accent_positive'), 0.18 + amount * 0.42)
        if status == 'negative':
            return self._p19_mix_color(self.theme_color('panel_background'), self.theme_color('accent_negative'), 0.18 + amount * 0.42)
        return self.theme_color('panel_background')

    @staticmethod
    def _p19_mix_color(left: str, right: str, amount: float) -> str:
        amount = max(0.0, min(float(amount), 1.0))
        left_color = QColor(left)
        right_color = QColor(right)
        if not left_color.isValid() or not right_color.isValid():
            return left
        return QColor(
            round(left_color.red() + (right_color.red() - left_color.red()) * amount),
            round(left_color.green() + (right_color.green() - left_color.green()) * amount),
            round(left_color.blue() + (right_color.blue() - left_color.blue()) * amount),
        ).name()

    def _p19_apply_styles(self) -> None:
        panel_style = (
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        for panel in getattr(self, '_p19_panel_widgets', []):
            panel.setStyleSheet(panel_style)
        for table in getattr(self, '_p19_table_widgets', []):
            table.setStyleSheet(
                f'QTableWidget {{ background: {self.theme_color("table_row_bg")}; '
                f'alternate-background-color: {self.theme_color("table_row_alt_bg")}; '
                f'color: {self.theme_color("text_primary")}; border: none; gridline-color: {self.theme_color("gridline")}; }}'
                f'QHeaderView::section {{ background: {self.theme_color("table_header_bg")}; '
                f'color: {self.theme_color("text_secondary")}; border: none; padding: 4px 6px; }}'
            )
        for label in getattr(self, 'p19_heatmap_cells', []):
            status = label.property('bt_change')
            intensity = label.property('bt_intensity')
            bg = self._p19_heatmap_background(str(status or 'muted'), intensity)
            if status == 'positive':
                fg = self.theme_color('accent_positive')
            elif status == 'negative':
                fg = self.theme_color('accent_negative')
            else:
                fg = self.theme_color('text_muted')
            label.setStyleSheet(
                f'background: {bg}; color: {fg}; border: 1px solid {self.theme_color("panel_border")}; '
                f'border-radius: 4px; font-size: 11px; font-weight: 700; padding: 2px;'
            )

    def _apply_crypto_theme(self) -> None:
        """Refresh Crypto page surfaces after theme changes."""
        self._p19_apply_styles()
        if hasattr(self, 'p19_watchlist_table'):
            payload = getattr(self, '_p19_last_payload', {})
            if isinstance(payload, dict) and payload:
                self._p19_apply_payload(payload)
