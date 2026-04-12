from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..compat import *
from budget_terminal_app.workers.youtube import YouTubeWorker


class _ClickableThumbnailLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class YouTubeMixin:

    _P16_DAYS_COLUMN = 5

    def init_page16(self) -> None:
        self._p16_thread: QThread | None = None
        self._p16_worker = None
        self._p16_items: list[dict[str, Any]] = []
        self._p16_warnings: list[str] = []
        self._p16_last_summary = self._p16_normalize_summary(None)
        self._p16_loaded_once = False
        self._p16_follow_newest = True
        self._p16_manual_selected_key = ''
        self._p16_selection_guard = False
        self._p16_selected_item: dict[str, Any] | None = None
        self._p16_thumbnail_pixmap: QPixmap | None = None
        self._p16_thumbnail_cache: dict[str, QPixmap] = {}
        self._p16_thumbnail_request_token = 0
        self._p16_pending_thumbnail_candidates: list[str] = []
        self._p16_thumbnail_video_url = ''
        self._p16_thumbnail_cache_key = ''
        self._p16_thumbnail_manager = QNetworkAccessManager(self)
        self._p16_thumbnail_reply: QNetworkReply | None = None
        self._p16_thumbnail_timeout = QTimer(self)
        self._p16_thumbnail_timeout.setSingleShot(True)
        self._p16_thumbnail_timeout.timeout.connect(self._p16_on_thumbnail_timeout)

        layout = QVBoxLayout(self.page16)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

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

        self.p16_status_lbl = QLabel('Open the tab to load YouTube results.')
        self.set_theme_role(self.p16_status_lbl, 'status_muted')
        layout.addWidget(self.p16_status_lbl)

        self.p16_warning_lbl = QLabel('')
        self.p16_warning_lbl.setWordWrap(True)
        self.set_theme_role(self.p16_warning_lbl, 'status_muted')
        self.p16_warning_lbl.setVisible(False)
        layout.addWidget(self.p16_warning_lbl)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p16_body_splitter = body_splitter

        detail_box = QGroupBox('Selected Video')
        self.set_theme_role(detail_box, 'panel')
        detail_box.setMinimumWidth(340)
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(10, 10, 10, 10)
        detail_layout.setSpacing(8)

        self.p16_thumbnail_lbl = _ClickableThumbnailLabel()
        self.p16_thumbnail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p16_thumbnail_lbl.setMinimumSize(320, 180)
        self.p16_thumbnail_lbl.setMaximumSize(320, 180)
        self.p16_thumbnail_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.p16_thumbnail_lbl.setScaledContents(False)
        self.p16_thumbnail_lbl.clicked.connect(self._p16_open_selected_thumbnail)
        detail_layout.addWidget(self.p16_thumbnail_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        self.p16_thumbnail_hint_lbl = QLabel('')
        self.p16_thumbnail_hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.p16_thumbnail_hint_lbl, 'muted')
        self.p16_thumbnail_hint_lbl.setVisible(False)
        detail_layout.addWidget(self.p16_thumbnail_hint_lbl)

        self.p16_video_title_lbl = QLabel('Select a video to preview')
        self.p16_video_title_lbl.setWordWrap(True)
        self.set_theme_role(self.p16_video_title_lbl, 'section_title')
        detail_layout.addWidget(self.p16_video_title_lbl)

        meta_grid = QGridLayout()
        meta_grid.setContentsMargins(0, 0, 0, 0)
        meta_grid.setHorizontalSpacing(10)
        meta_grid.setVerticalSpacing(4)
        self._p16_meta_value_labels: dict[str, QLabel] = {}
        meta_rows = (
            ('ticker', 'Ticker'),
            ('channel', 'Channel'),
            ('views', 'Views'),
            ('published', 'Published'),
            ('days_ago', 'Days Ago'),
            ('duration', 'Duration'),
        )
        for row, (key, label_text) in enumerate(meta_rows):
            label = QLabel(f'{label_text}:')
            self.set_theme_role(label, 'muted')
            value = QLabel('-')
            value.setWordWrap(True)
            meta_grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            meta_grid.addWidget(value, row, 1)
            self._p16_meta_value_labels[key] = value
        detail_layout.addLayout(meta_grid)

        description_title = QLabel('Description')
        self.set_theme_role(description_title, 'section_title')
        detail_layout.addWidget(description_title)

        self.p16_description_text = QTextEdit()
        self.p16_description_text.setReadOnly(True)
        self.p16_description_text.setPlaceholderText('Description unavailable.')
        self.p16_description_text.setStyleSheet('font-size: 12px; padding: 6px;')
        detail_layout.addWidget(self.p16_description_text, 1)

        body_splitter.addWidget(detail_box)

        results_box = QGroupBox('Portfolio YouTube Feed')
        self.set_theme_role(results_box, 'panel')
        results_layout = QVBoxLayout(results_box)
        results_layout.setContentsMargins(6, 8, 6, 6)
        results_layout.setSpacing(6)

        self.p16_table = QTableWidget(0, 7)
        self.p16_table.setHorizontalHeaderLabels(['Ticker', 'Title', 'Channel', 'Views', 'Published', 'Days Ago', 'Duration'])
        header = self.p16_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for index in range(2, self.p16_table.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionsClickable(False)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self._P16_DAYS_COLUMN, Qt.SortOrder.AscendingOrder)
        self.p16_table.verticalHeader().setVisible(False)
        self.p16_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p16_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p16_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p16_table.setAlternatingRowColors(True)
        self.p16_table.setSortingEnabled(False)
        self.p16_table.itemSelectionChanged.connect(self._p16_on_selection_changed)
        self.p16_table.cellDoubleClicked.connect(self._p16_open_link)
        results_layout.addWidget(self.p16_table, 1)

        body_splitter.addWidget(results_box)
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 5)
        body_splitter.setSizes([380, 900])
        layout.addWidget(body_splitter, 1)

        self._p16_clear_detail_panel(
            title='Select a video to preview',
            description='Open the YouTube tab and choose a result row to see the thumbnail and summary.',
        )

    def _p16_on_show(self) -> None:
        if not self._p16_loaded_once and (self._p16_thread is None or not self._p16_thread.isRunning()):
            self._p16_refresh(force=False, auto_trigger=True)

    def _p16_refresh(self, *, force: bool, auto_trigger: bool) -> None:
        if self._p16_thread is not None and self._p16_thread.isRunning():
            return
        tickers = list(self._get_fetch_tickers()) if hasattr(self, '_get_fetch_tickers') else []
        if not tickers:
            self._p16_loaded_once = True
            self._p16_items = []
            self._p16_warnings = ['No saved portfolio tickers are available yet.']
            self._p16_last_summary = self._p16_normalize_summary({'tickers_total': 0, 'from_cache_count': 0, 'fetched_count': 0})
            self._p16_follow_newest = True
            self._p16_manual_selected_key = ''
            self._p16_render_table()
            self._p16_apply_warnings(self._p16_warnings)
            self.set_status_text(self.p16_status_lbl, 'No saved portfolio tickers are available yet.', status='warning')
            self._p16_save_session_snapshot()
            return
        self._p16_loaded_once = True
        self._p16_set_busy(True)
        if auto_trigger and not force:
            start_text = 'Checking cached YouTube results...'
        elif force:
            start_text = 'Refreshing all YouTube results...'
        else:
            start_text = 'Refreshing cached/stale YouTube results...'
        self.set_status_text(self.p16_status_lbl, start_text, status='muted')
        if not self._p16_items:
            self._p16_warnings = []
            self._p16_apply_warnings([])
            self._p16_clear_detail_panel(
                title='Loading videos...',
                description='Checking cached YouTube results and refreshing stale matches.',
            )
            self.p16_table.setRowCount(0)
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

    def _p16_session_snapshot(self) -> dict[str, Any] | None:
        items = [dict(item) for item in self._p16_items if isinstance(item, dict)]
        warnings = self._p16_normalize_warnings(self._p16_warnings)
        summary = self._p16_normalize_summary(self._p16_last_summary)
        if not items and not warnings and int(summary.get('tickers_total', 0) or 0) <= 0:
            return None
        return {
            'items': serialize_session_value(items),
            'warnings': serialize_session_value(warnings),
            'summary': serialize_session_value(summary),
        }

    def _p16_save_session_snapshot(self, *, immediate: bool = False) -> None:
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('youtube', self._p16_session_snapshot(), immediate=immediate)

    def _p16_restore_session_snapshot(self, snapshot: Any) -> bool:
        payload = snapshot if isinstance(snapshot, dict) else {}
        items = self._p16_normalize_items(deserialize_session_value(payload.get('items')))
        warnings = self._p16_normalize_warnings(deserialize_session_value(payload.get('warnings')))
        summary = self._p16_normalize_summary(deserialize_session_value(payload.get('summary')))
        if not items and not warnings and int(summary.get('tickers_total', 0) or 0) <= 0:
            return False
        self._p16_loaded_once = True
        self._p16_items = self._p16_sorted_items(items)
        self._p16_warnings = warnings
        self._p16_last_summary = summary
        self._p16_follow_newest = True
        self._p16_manual_selected_key = ''
        self._p16_render_table()
        self._p16_apply_warnings(warnings)
        status_text, status = self._p16_status_state(self._p16_items, warnings, summary, restored=True)
        self.set_status_text(self.p16_status_lbl, status_text, status=status)
        return True

    def _p16_restore_startup_session(self, snapshot: Any) -> None:
        if self._p16_thread is not None and self._p16_thread.isRunning():
            return
        if self._p16_loaded_once:
            return
        restored = self._p16_restore_session_snapshot(snapshot)
        if restored:
            self._p16_refresh(force=False, auto_trigger=True)

    def _p16_on_worker_status(self, text: str) -> None:
        self.set_status_text(self.p16_status_lbl, text, status='muted')

    def _p16_on_item_ready(self, item: dict[str, Any]) -> None:
        if not isinstance(item, dict):
            return
        if self._p16_merge_items([item]):
            self._p16_render_table()

    def _p16_on_data(self, payload: dict[str, Any]) -> None:
        self._p16_set_busy(False)
        payload_items = self._p16_normalize_items(payload.get('items'))
        self._p16_items = self._p16_sorted_items(payload_items)
        self._p16_warnings = self._p16_normalize_warnings(payload.get('warnings'))
        self._p16_last_summary = self._p16_normalize_summary(payload)
        self._p16_render_table()
        self._p16_apply_warnings(self._p16_warnings)
        status_text, status = self._p16_status_state(self._p16_items, self._p16_warnings, self._p16_last_summary)
        self.set_status_text(self.p16_status_lbl, status_text, status=status)
        self._p16_save_session_snapshot()

    def _p16_on_error(self, message: str) -> None:
        self._p16_set_busy(False)
        error_text = f'YouTube refresh failed: {message}'
        self._p16_apply_warnings([message])
        if not self._p16_items:
            self._p16_clear_detail_panel(
                title='No video selected',
                description='YouTube results could not be loaded.',
            )
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

    def _p16_normalize_items(self, items: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not isinstance(items, list):
            return normalized
        by_key: dict[str, dict[str, Any]] = {}
        for raw_item in items:
            item = self._p16_normalize_item(raw_item)
            if item is None:
                continue
            key = self._p16_video_key(item)
            if not key:
                continue
            by_key[key] = item
        for item in by_key.values():
            normalized.append(item)
        return normalized

    def _p16_normalize_item(self, raw_item: Any) -> dict[str, Any] | None:
        if not isinstance(raw_item, dict):
            return None
        item = dict(raw_item)
        item['ticker'] = str(item.get('ticker', '') or '').upper().strip()
        item['title'] = str(item.get('title', '') or 'Untitled').strip() or 'Untitled'
        item['channel'] = str(item.get('channel', '') or 'Unknown').strip() or 'Unknown'
        item['url'] = str(item.get('url', '') or '').strip()
        item['thumbnail_url'] = str(item.get('thumbnail_url', '') or '').strip()
        item['description_snippet'] = str(item.get('description_snippet', '') or '').strip()
        view_count = YouTubeWorker._normalize_view_count(item.get('view_count'))
        item['view_count'] = view_count
        item['view_count_text'] = YouTubeWorker._format_view_count(view_count)
        published_text = str(item.get('published_text', '') or 'N/A').strip() or 'N/A'
        item['published_text'] = published_text
        published_days = YouTubeWorker._days_since_published(published_text)
        item['published_days'] = published_days
        item['published_days_text'] = YouTubeWorker._format_published_days(published_days)
        item['duration_text'] = str(item.get('duration_text', '') or 'N/A').strip() or 'N/A'
        return item if self._p16_video_key(item) else None

    def _p16_normalize_warnings(self, warnings: Any) -> list[str]:
        values = warnings if isinstance(warnings, list) else []
        cleaned: list[str] = []
        for warning in values:
            text = str(warning or '').strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def _p16_normalize_summary(self, summary: Any) -> dict[str, int]:
        payload = summary if isinstance(summary, dict) else {}

        def _as_int(key: str) -> int:
            try:
                return max(int(payload.get(key, 0) or 0), 0)
            except (TypeError, ValueError):
                return 0

        return {
            'tickers_total': _as_int('tickers_total'),
            'from_cache_count': _as_int('from_cache_count'),
            'fetched_count': _as_int('fetched_count'),
        }

    def _p16_sorted_items(self, items: Any) -> list[dict[str, Any]]:
        return sorted(self._p16_normalize_items(items), key=self._p16_sort_key)

    def _p16_sort_key(self, item: dict[str, Any]) -> tuple[Any, ...]:
        days_value = item.get('published_days')
        if isinstance(days_value, (int, float)):
            days_missing = 0
            days_sort = int(days_value)
        else:
            days_missing = 1
            days_sort = 10 ** 9
        published_text = str(item.get('published_text', '') or '').strip()
        try:
            published_ordinal = datetime.datetime.strptime(published_text, '%Y-%m-%d').date().toordinal()
        except ValueError:
            published_ordinal = 0
        view_count = item.get('view_count')
        view_sort = -int(view_count) if isinstance(view_count, (int, float)) else 1
        ticker = str(item.get('ticker', '') or '').upper().strip()
        title = str(item.get('title', '') or '').strip()
        return (days_missing, days_sort, -published_ordinal, view_sort, ticker, title)

    def _p16_merge_items(self, items: Any) -> bool:
        current = {self._p16_video_key(item): dict(item) for item in self._p16_items if self._p16_video_key(item)}
        changed = False
        for item in self._p16_normalize_items(items):
            key = self._p16_video_key(item)
            if not key:
                continue
            existing = current.get(key)
            if existing != item:
                current[key] = dict(item)
                changed = True
        if not changed:
            return False
        self._p16_items = self._p16_sorted_items(list(current.values()))
        return True

    def _p16_status_state(
        self,
        items: list[dict[str, Any]],
        warnings: list[str],
        summary: dict[str, int],
        *,
        restored: bool = False,
    ) -> tuple[str, str]:
        total = int(summary.get('tickers_total', 0) or 0)
        cached = int(summary.get('from_cache_count', 0) or 0)
        fetched = int(summary.get('fetched_count', 0) or 0)
        if restored:
            if items:
                if total > 0:
                    return (f'Restored {len(items)} YouTube video result(s) from last session for {total} ticker(s).', 'muted')
                return (f'Restored {len(items)} YouTube video result(s) from last session.', 'muted')
            if warnings:
                return ('Restored the last YouTube session state.', 'warning')
            return ('Restored the last YouTube session state.', 'muted')
        if not items:
            status = 'warning' if warnings else 'muted'
            text = f'No YouTube matches loaded for {total} ticker(s).' if total else 'No YouTube results found.'
            return (text, status)
        status = 'warning' if warnings else 'positive'
        return (f'Loaded {len(items)} video result(s) for {total} ticker(s) ({cached} cached, {fetched} fresh).', status)

    def _p16_render_table(self) -> None:
        target_key = ''
        if not self._p16_follow_newest and self._p16_manual_selected_key:
            if any(self._p16_video_key(item) == self._p16_manual_selected_key for item in self._p16_items):
                target_key = self._p16_manual_selected_key
            else:
                self._p16_manual_selected_key = ''
                self._p16_follow_newest = True
        selected_row = -1
        if self._p16_items:
            if target_key:
                for index, item in enumerate(self._p16_items):
                    if self._p16_video_key(item) == target_key:
                        selected_row = index
                        break
            if selected_row < 0:
                selected_row = 0
        self._p16_selection_guard = True
        self.p16_table.setUpdatesEnabled(False)
        try:
            self.p16_table.clearSelection()
            self.p16_table.setRowCount(0)
            for item in self._p16_items:
                self._p16_append_table_row(item)
            if selected_row >= 0:
                self.p16_table.selectRow(selected_row)
        finally:
            self.p16_table.setUpdatesEnabled(True)
            self._p16_selection_guard = False
        if selected_row >= 0:
            self._p16_show_detail_item(dict(self._p16_items[selected_row]))
        else:
            self._p16_clear_detail_panel(
                title='No video selected',
                description='No YouTube results are currently loaded.',
            )

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
        views_item = QTableWidgetItem(str(item.get('view_count_text', '') or 'N/A'))
        published_item = QTableWidgetItem(str(item.get('published_text', '') or 'N/A'))
        days_item = QTableWidgetItem(str(item.get('published_days_text', '') or 'N/A'))
        duration_item = QTableWidgetItem(str(item.get('duration_text', '') or 'N/A'))

        self.p16_table.setItem(row, 0, ticker_item)
        self.p16_table.setItem(row, 1, title_item)
        self.p16_table.setItem(row, 2, channel_item)
        self.p16_table.setItem(row, 3, views_item)
        self.p16_table.setItem(row, 4, published_item)
        self.p16_table.setItem(row, 5, days_item)
        self.p16_table.setItem(row, 6, duration_item)

    def _p16_on_selection_changed(self) -> None:
        model = self.p16_table.selectionModel()
        if model is None:
            return
        selected_rows = model.selectedRows()
        if not selected_rows:
            if self.p16_table.rowCount() == 0:
                self._p16_clear_detail_panel(
                    title='No video selected',
                    description='No YouTube results are currently loaded.',
                )
            return
        row = selected_rows[0].row()
        title_item = self.p16_table.item(row, 1)
        if title_item is None:
            return
        payload = title_item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(payload, dict):
            return
        if not self._p16_selection_guard:
            self._p16_follow_newest = False
            self._p16_manual_selected_key = self._p16_video_key(payload)
        self._p16_show_detail_item(dict(payload))

    def _p16_show_detail_item(self, item: dict[str, Any]) -> None:
        self._p16_selected_item = dict(item)
        self.p16_video_title_lbl.setText(str(item.get('title', '') or 'Untitled'))
        self._p16_set_detail_value('ticker', str(item.get('ticker', '') or '-'))
        self._p16_set_detail_value('channel', str(item.get('channel', '') or 'Unknown'))
        self._p16_set_detail_value('views', str(item.get('view_count_text', '') or 'N/A'))
        self._p16_set_detail_value('published', str(item.get('published_text', '') or 'N/A'))
        self._p16_set_detail_value('days_ago', str(item.get('published_days_text', '') or 'N/A'))
        self._p16_set_detail_value('duration', str(item.get('duration_text', '') or 'N/A'))
        description = str(item.get('description_snippet', '') or '').strip()
        self.p16_description_text.setPlainText(description or 'Description unavailable.')
        self.p16_thumbnail_hint_lbl.setText('Click the thumbnail to watch in your browser.')
        self.p16_thumbnail_hint_lbl.setVisible(True)
        self._p16_request_thumbnail(item)

    def _p16_set_detail_value(self, key: str, value: str) -> None:
        label = self._p16_meta_value_labels.get(key)
        if label is not None:
            label.setText(value or '-')

    def _p16_clear_detail_panel(self, *, title: str, description: str) -> None:
        self._p16_selected_item = None
        self._p16_thumbnail_pixmap = None
        self._p16_thumbnail_request_token += 1
        self._p16_cancel_thumbnail_request()
        self._p16_pending_thumbnail_candidates = []
        self._p16_thumbnail_video_url = ''
        self._p16_thumbnail_cache_key = ''
        self.p16_thumbnail_lbl.clear()
        self.p16_thumbnail_lbl.setPixmap(QPixmap())
        self.p16_thumbnail_lbl.setText(title)
        self.p16_thumbnail_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.p16_thumbnail_hint_lbl.setVisible(False)
        self.p16_video_title_lbl.setText(title)
        for key in self._p16_meta_value_labels:
            self._p16_set_detail_value(key, '-')
        self.p16_description_text.setPlainText(description)

    def _p16_request_thumbnail(self, item: dict[str, Any]) -> None:
        self._p16_thumbnail_pixmap = None
        self._p16_thumbnail_request_token += 1
        token = self._p16_thumbnail_request_token
        self._p16_cancel_thumbnail_request()
        candidates = self._p16_thumbnail_candidates(item)
        video_url = str(item.get('url', '') or '').strip()
        cache_key = self._p16_thumbnail_cache_key_for_item(item)
        self.p16_thumbnail_lbl.clear()
        self.p16_thumbnail_lbl.setPixmap(QPixmap())
        self.p16_thumbnail_lbl.setCursor(Qt.CursorShape.PointingHandCursor if video_url else Qt.CursorShape.ArrowCursor)
        self._p16_thumbnail_video_url = video_url
        self._p16_thumbnail_cache_key = cache_key
        cached_pixmap = self._p16_thumbnail_cache.get(cache_key) if cache_key else None
        if cached_pixmap is not None:
            self._p16_apply_thumbnail_pixmap(cached_pixmap, video_url=video_url)
            return
        if not candidates:
            self.p16_thumbnail_lbl.setText('Thumbnail unavailable')
            self.p16_thumbnail_hint_lbl.setText('Thumbnail unavailable. Click here to watch in your browser.')
            self.p16_thumbnail_hint_lbl.setVisible(True)
            return
        self.p16_thumbnail_lbl.setText('Loading thumbnail...')
        self._p16_pending_thumbnail_candidates = list(candidates)
        self._p16_fetch_next_thumbnail_candidate(token=token)

    def _p16_cancel_thumbnail_request(self) -> None:
        self._p16_thumbnail_timeout.stop()
        reply = self._p16_thumbnail_reply
        if reply is None:
            return
        self._p16_thumbnail_reply = None
        try:
            reply.finished.disconnect(self._p16_on_thumbnail_reply_finished)
        except TypeError:
            pass
        reply.abort()
        reply.deleteLater()

    def _p16_fetch_next_thumbnail_candidate(self, *, token: int) -> None:
        if token != self._p16_thumbnail_request_token:
            return
        if not self._p16_selected_item or str(self._p16_selected_item.get('url', '') or '').strip() != self._p16_thumbnail_video_url:
            return
        if not self._p16_pending_thumbnail_candidates:
            self._p16_show_thumbnail_unavailable(
                self._p16_thumbnail_video_url,
                message='Thumbnail unavailable right now. Click here to watch in your browser.',
            )
            return
        candidate = self._p16_pending_thumbnail_candidates.pop(0)
        request = QNetworkRequest(QUrl(candidate))
        request.setRawHeader(
            b'User-Agent',
            (
                b'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                b'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            ),
        )
        try:
            request.setTransferTimeout(8000)
        except Exception:
            pass
        reply = self._p16_thumbnail_manager.get(request)
        reply.setProperty('bt_token', token)
        reply.setProperty('bt_candidate', candidate)
        reply.finished.connect(self._p16_on_thumbnail_reply_finished)
        self._p16_thumbnail_reply = reply
        self._p16_thumbnail_timeout.start(8000)

    def _p16_on_thumbnail_timeout(self) -> None:
        reply = self._p16_thumbnail_reply
        if reply is None:
            return
        reply.setProperty('bt_timed_out', True)
        reply.abort()

    def _p16_on_thumbnail_reply_finished(self) -> None:
        reply = self._p16_thumbnail_reply
        if reply is None:
            return
        self._p16_thumbnail_reply = None
        self._p16_thumbnail_timeout.stop()
        try:
            token = int(reply.property('bt_token') or -1)
        except (TypeError, ValueError):
            token = -1
        candidate = str(reply.property('bt_candidate') or '').strip()
        timed_out = bool(reply.property('bt_timed_out'))
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error_code = reply.error()
        error_text = str(reply.errorString() or '').strip()
        content_type = bytes(reply.rawHeader(b'Content-Type')).decode('latin-1', errors='ignore').lower()
        raw_bytes = bytes(reply.readAll())
        reply.deleteLater()
        if token != self._p16_thumbnail_request_token:
            return
        if not self._p16_selected_item or str(self._p16_selected_item.get('url', '') or '').strip() != self._p16_thumbnail_video_url:
            return
        if error_code != QNetworkReply.NetworkError.NoError:
            detail = 'request timed out' if timed_out else (error_text or f'network error {int(error_code)}')
            logger.warning('YouTube thumbnail fetch failed for %s: %s', candidate, detail)
            self._p16_fetch_next_thumbnail_candidate(token=token)
            return
        if status not in (None, 200):
            logger.warning('YouTube thumbnail fetch returned HTTP %s for %s.', status, candidate)
            self._p16_fetch_next_thumbnail_candidate(token=token)
            return
        if not raw_bytes:
            logger.warning('YouTube thumbnail fetch returned no bytes for %s.', candidate)
            self._p16_fetch_next_thumbnail_candidate(token=token)
            return
        if content_type and 'image' not in content_type:
            logger.warning('YouTube thumbnail fetch returned non-image content for %s: %s', candidate, content_type)
            self._p16_fetch_next_thumbnail_candidate(token=token)
            return
        pixmap = self._p16_decode_thumbnail_pixmap(raw_bytes)
        if pixmap is None:
            logger.warning('YouTube thumbnail decode failed for %s.', candidate)
            self._p16_fetch_next_thumbnail_candidate(token=token)
            return
        if self._p16_thumbnail_cache_key:
            self._p16_thumbnail_cache[self._p16_thumbnail_cache_key] = pixmap
        self._p16_apply_thumbnail_pixmap(pixmap, video_url=self._p16_thumbnail_video_url)

    def _p16_decode_thumbnail_pixmap(self, data: Any) -> QPixmap | None:
        raw_bytes = bytes(data or b'')
        if not raw_bytes:
            return None
        pixmap = QPixmap()
        if pixmap.loadFromData(raw_bytes):
            return pixmap
        image = QImage.fromData(raw_bytes)
        if image.isNull():
            return None
        return QPixmap.fromImage(image)

    def _p16_apply_thumbnail_pixmap(self, pixmap: QPixmap, *, video_url: str) -> None:
        self._p16_thumbnail_pixmap = pixmap
        scaled = pixmap.scaled(
            self.p16_thumbnail_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.p16_thumbnail_lbl.clear()
        self.p16_thumbnail_lbl.setPixmap(scaled)
        self.p16_thumbnail_lbl.setCursor(Qt.CursorShape.PointingHandCursor if video_url else Qt.CursorShape.ArrowCursor)
        self.p16_thumbnail_hint_lbl.setText('Click the thumbnail to watch in your browser.')
        self.p16_thumbnail_hint_lbl.setVisible(bool(video_url))

    def _p16_show_thumbnail_unavailable(self, video_url: str, *, message: str) -> None:
        self.p16_thumbnail_lbl.clear()
        self.p16_thumbnail_lbl.setPixmap(QPixmap())
        self.p16_thumbnail_lbl.setText('Thumbnail unavailable')
        self.p16_thumbnail_lbl.setCursor(Qt.CursorShape.PointingHandCursor if video_url else Qt.CursorShape.ArrowCursor)
        self.p16_thumbnail_hint_lbl.setText(message)
        self.p16_thumbnail_hint_lbl.setVisible(True)

    def _p16_thumbnail_candidates(self, item: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        thumbnail_url = str(item.get('thumbnail_url', '') or '').strip()
        if thumbnail_url:
            candidates.append(thumbnail_url)
        video_id = self._p16_extract_video_id(item)
        if video_id:
            for filename in ('maxresdefault.jpg', 'sddefault.jpg', 'hqdefault.jpg', 'mqdefault.jpg', 'default.jpg'):
                candidate = f'https://i.ytimg.com/vi/{video_id}/{filename}'
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _p16_thumbnail_cache_key_for_item(self, item: dict[str, Any]) -> str:
        video_id = self._p16_extract_video_id(item)
        if video_id:
            return f'video:{video_id}'
        url = str(item.get('url', '') or '').strip()
        if url:
            return f'url:{url}'
        thumbnail_url = str(item.get('thumbnail_url', '') or '').strip()
        return f'thumb:{thumbnail_url}' if thumbnail_url else ''

    def _p16_video_key(self, item: dict[str, Any]) -> str:
        video_id = self._p16_extract_video_id(item)
        if video_id:
            return f'video:{video_id}'
        url = str(item.get('url', '') or '').strip()
        if url:
            return f'url:{url}'
        ticker = str(item.get('ticker', '') or '').upper().strip()
        title = str(item.get('title', '') or '').strip()
        published = str(item.get('published_text', '') or '').strip()
        channel = str(item.get('channel', '') or '').strip()
        fallback = '|'.join((ticker, title, published, channel)).strip('|')
        return f'fallback:{fallback}' if fallback else ''

    @staticmethod
    def _p16_extract_video_id(item: dict[str, Any]) -> str:
        url = str(item.get('url', '') or '').strip()
        if url:
            parsed = urlparse(url)
            query_value = parse_qs(parsed.query).get('v', [''])
            video_id = str(query_value[0] or '').strip()
            if video_id:
                return video_id
            if parsed.netloc.endswith('youtu.be'):
                short_id = parsed.path.strip('/').split('/', 1)[0]
                if short_id:
                    return short_id
        thumbnail_url = str(item.get('thumbnail_url', '') or '').strip()
        marker = '/vi/'
        if marker in thumbnail_url:
            return thumbnail_url.split(marker, 1)[1].split('/', 1)[0].strip()
        return ''

    def _p16_open_selected_thumbnail(self) -> None:
        if not self._p16_selected_item:
            return
        url = str(self._p16_selected_item.get('url', '') or '').strip()
        if not url:
            return
        logger.info('Opening YouTube link from thumbnail: %s', url)
        webbrowser.open(url)

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
            self.p16_warning_lbl.setVisible(True)
        else:
            self.set_status_text(self.p16_warning_lbl, '', status='muted')
            self.p16_warning_lbl.setVisible(False)

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
        if hasattr(self, 'p16_description_text'):
            self.p16_description_text.setStyleSheet(
                f'background-color: {bg}; color: {text}; border: 1px solid {border}; font-size: 12px; padding: 6px;'
            )
        if hasattr(self, 'p16_thumbnail_lbl'):
            self.p16_thumbnail_lbl.setStyleSheet(
                f'background-color: {bg}; color: {self.theme_color("text_muted")}; border: 1px solid {border}; border-radius: 6px;'
            )
        if hasattr(self, 'p16_status_lbl'):
            self.set_status_text(self.p16_status_lbl, self.p16_status_lbl.text(), status=self.p16_status_lbl.property('bt_status') or 'muted')
        if hasattr(self, 'p16_warning_lbl'):
            self.set_status_text(self.p16_warning_lbl, self.p16_warning_lbl.text(), status=self.p16_warning_lbl.property('bt_status') or 'muted')
