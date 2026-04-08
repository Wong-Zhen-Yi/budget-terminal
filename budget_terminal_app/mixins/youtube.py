from __future__ import annotations

from typing import Any

from ..compat import *


class _SortableNumericTableWidgetItem(QTableWidgetItem):

    def __init__(self, text: str, sort_value: Any = None) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, sort_value)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, QTableWidgetItem):
            left = self.data(Qt.ItemDataRole.UserRole)
            right = other.data(Qt.ItemDataRole.UserRole)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left < right
        return super().__lt__(other)


class YouTubeMixin:

    def init_page16(self) -> None:
        self._p16_thread: QThread | None = None
        self._p16_worker = None
        self._p16_items: list[dict[str, Any]] = []
        self._p16_warnings: list[str] = []

        layout = QVBoxLayout(self.page16)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>YouTube</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        self.p16_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p16_refresh_btn, 'accent')
        self.p16_refresh_btn.clicked.connect(lambda: self._p16_refresh(force=False, auto_trigger=False))
        title_row.addWidget(self.p16_refresh_btn)
        layout.addLayout(title_row)

        intro_lbl = QLabel(
            'Search YouTube for all saved portfolio tickers using "<ticker> stock", reuse fresh cached matches, and fetch stale or missing tickers in parallel. Load up to 3 matching videos per ticker with at least 1,000 views and published within the last 90 days.'
        )
        intro_lbl.setWordWrap(True)
        self.set_theme_role(intro_lbl, 'muted')
        layout.addWidget(intro_lbl)

        self.p16_status_lbl = QLabel('Open the tab to load YouTube results.')
        self.set_theme_role(self.p16_status_lbl, 'status_muted')
        layout.addWidget(self.p16_status_lbl)

        self.p16_warning_lbl = QLabel('')
        self.p16_warning_lbl.setWordWrap(True)
        self.set_theme_role(self.p16_warning_lbl, 'status_muted')
        layout.addWidget(self.p16_warning_lbl)

        results_box = QGroupBox('Portfolio YouTube Feed')
        self.set_theme_role(results_box, 'panel')
        results_layout = QVBoxLayout(results_box)
        results_layout.setContentsMargins(6, 8, 6, 6)
        results_layout.setSpacing(6)

        self.p16_table = QTableWidget(0, 7)
        self.p16_table.setHorizontalHeaderLabels(['Ticker', 'Title', 'Channel', 'Views', 'Published', 'Days Ago', 'Duration'])
        self.p16_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.p16_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for index in range(2, self.p16_table.columnCount()):
            self.p16_table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self.p16_table.verticalHeader().setVisible(False)
        self.p16_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p16_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p16_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p16_table.setAlternatingRowColors(True)
        self.p16_table.setSortingEnabled(True)
        self.p16_table.cellDoubleClicked.connect(self._p16_open_link)
        results_layout.addWidget(self.p16_table, 1)

        layout.addWidget(results_box, 1)

    def _p16_on_show(self) -> None:
        self._p16_refresh(force=False, auto_trigger=True)

    def _p16_refresh(self, *, force: bool, auto_trigger: bool) -> None:
        if self._p16_thread is not None and self._p16_thread.isRunning():
            return
        tickers = list(self._get_fetch_tickers()) if hasattr(self, '_get_fetch_tickers') else []
        if not tickers:
            self._p16_items = []
            self._p16_warnings = ['No saved portfolio tickers are available yet.']
            self._p16_populate_table([])
            self._p16_apply_warnings(self._p16_warnings)
            self.set_status_text(self.p16_status_lbl, 'No saved portfolio tickers are available yet.', status='warning')
            return
        self._p16_items = []
        self._p16_warnings = []
        self.p16_table.setSortingEnabled(False)
        self.p16_table.setRowCount(0)
        self._p16_apply_warnings([])
        self._p16_set_busy(True)
        if auto_trigger and not force:
            start_text = 'Checking cached YouTube results...'
        elif force:
            start_text = 'Refreshing all YouTube results...'
        else:
            start_text = 'Refreshing cached/stale YouTube results...'
        self.set_status_text(self.p16_status_lbl, start_text, status='muted')
        worker = YouTubeWorker(tickers, force_refresh=force)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self._p16_on_worker_status)
        worker.item_ready.connect(self._p16_on_item_ready)
        worker.finished.connect(self._p16_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p16_on_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._p16_on_thread_finished)
        self._p16_thread = thread
        self._p16_worker = worker
        thread.start()

    def _p16_on_worker_status(self, text: str) -> None:
        self.set_status_text(self.p16_status_lbl, text, status='muted')

    def _p16_on_item_ready(self, item: dict[str, Any]) -> None:
        if not isinstance(item, dict):
            return
        item_copy = dict(item)
        self._p16_items.append(item_copy)
        self._p16_append_table_row(item_copy)

    def _p16_on_data(self, payload: dict[str, Any]) -> None:
        self._p16_set_busy(False)
        payload_items = [dict(item) for item in payload.get('items', []) if isinstance(item, dict)]
        self._p16_items = payload_items
        self._p16_populate_table(self._p16_items)
        self.p16_table.setSortingEnabled(True)
        self._p16_warnings = [str(message or '').strip() for message in payload.get('warnings', []) if str(message or '').strip()]
        self._p16_apply_warnings(self._p16_warnings)

        total = int(payload.get('tickers_total', 0) or 0)
        cached = int(payload.get('from_cache_count', 0) or 0)
        fetched = int(payload.get('fetched_count', 0) or 0)
        if not self._p16_items:
            status = 'warning' if self._p16_warnings else 'muted'
            text = f'No YouTube matches loaded for {total} ticker(s).' if total else 'No YouTube results found.'
        else:
            status = 'warning' if self._p16_warnings else 'positive'
            text = f'Loaded {len(self._p16_items)} video result(s) for {total} ticker(s) ({cached} cached, {fetched} fresh).'
        self.set_status_text(self.p16_status_lbl, text, status=status)

    def _p16_on_error(self, message: str) -> None:
        self._p16_set_busy(False)
        self.p16_table.setSortingEnabled(True)
        error_text = f'YouTube refresh failed: {message}'
        self._p16_apply_warnings([message])
        self.set_status_text(self.p16_status_lbl, error_text, status='negative')

    def _p16_on_thread_finished(self) -> None:
        if self._p16_worker is not None:
            self._p16_worker.deleteLater()
            self._p16_worker = None
        if self._p16_thread is not None:
            self._p16_thread.deleteLater()
            self._p16_thread = None

    def _p16_set_busy(self, busy: bool) -> None:
        self.p16_refresh_btn.setEnabled(not busy)

    def _p16_populate_table(self, items: list[dict[str, Any]]) -> None:
        self.p16_table.setSortingEnabled(False)
        self.p16_table.setRowCount(0)
        for item in items:
            self._p16_append_table_row(item)
        self.p16_table.setSortingEnabled(True)

    def _p16_append_table_row(self, item: dict[str, Any]) -> None:
        row = self.p16_table.rowCount()
        self.p16_table.insertRow(row)
        ticker_item = QTableWidgetItem(str(item.get('ticker', '') or ''))
        title_item = QTableWidgetItem(str(item.get('title', '') or 'Untitled'))
        title_item.setData(Qt.ItemDataRole.UserRole, str(item.get('url', '') or '').strip())
        title_item.setData(Qt.ItemDataRole.UserRole + 1, dict(item))
        title_item.setToolTip(str(item.get('description_snippet', '') or item.get('title', '') or ''))
        title_item.setForeground(QColor(self.theme_color('accent')))
        channel_item = QTableWidgetItem(str(item.get('channel', '') or 'Unknown'))
        views_value = item.get('view_count')
        views_text = str(item.get('view_count_text', '') or 'N/A')
        sort_value = int(views_value) if isinstance(views_value, (int, float)) else -1
        views_item = _SortableNumericTableWidgetItem(views_text, sort_value)
        published_item = QTableWidgetItem(str(item.get('published_text', '') or 'N/A'))
        days_value = item.get('published_days')
        days_text = str(item.get('published_days_text', '') or 'N/A')
        days_sort_value = int(days_value) if isinstance(days_value, (int, float)) else -1
        days_item = _SortableNumericTableWidgetItem(days_text, days_sort_value)
        duration_item = QTableWidgetItem(str(item.get('duration_text', '') or 'N/A'))

        self.p16_table.setItem(row, 0, ticker_item)
        self.p16_table.setItem(row, 1, title_item)
        self.p16_table.setItem(row, 2, channel_item)
        self.p16_table.setItem(row, 3, views_item)
        self.p16_table.setItem(row, 4, published_item)
        self.p16_table.setItem(row, 5, days_item)
        self.p16_table.setItem(row, 6, duration_item)

    def _p16_open_link(self, row: int, _column: int) -> None:
        title_item = self.p16_table.item(row, 1)
        if title_item is None:
            return
        url = str(title_item.data(Qt.ItemDataRole.UserRole) or '').strip()
        if not url:
            return
        logger.info('Opening YouTube link: %s', url)
        webbrowser.open(url)

    def _p16_apply_warnings(self, warnings: list[str]) -> None:
        text = self._p16_format_warnings(warnings)
        if text:
            self.set_status_text(self.p16_warning_lbl, text, status='warning')
        else:
            self.set_status_text(self.p16_warning_lbl, '', status='muted')

    def _p16_format_warnings(self, warnings: list[str]) -> str:
        cleaned = [str(message or '').strip() for message in warnings if str(message or '').strip()]
        if not cleaned:
            return ''
        display = cleaned[:5]
        if len(cleaned) > 5:
            display.append(f'+{len(cleaned) - 5} more warning(s)')
        return '\n'.join(display)

    def _apply_youtube_theme(self) -> None:
        bg = self.theme_color('panel_background')
        border = self.theme_color('panel_border')
        text = self.theme_color('text_primary')
        style = f'background-color: {bg}; color: {text}; border: 1px solid {border};'
        if hasattr(self, 'p16_table'):
            self.p16_table.setStyleSheet(style)
        if hasattr(self, 'p16_status_lbl'):
            self.set_status_text(self.p16_status_lbl, self.p16_status_lbl.text(), status=self.p16_status_lbl.property('bt_status') or 'muted')
        if hasattr(self, 'p16_warning_lbl'):
            self.set_status_text(self.p16_warning_lbl, self.p16_warning_lbl.text(), status=self.p16_warning_lbl.property('bt_status') or 'muted')
