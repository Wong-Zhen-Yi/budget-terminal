from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.ipo_calendar import (
    IPO_CALENDAR_CACHE_TTL_SECONDS,
    IPO_CALENDAR_SOURCE_NAME,
    IpoCalendarWorker,
)

_P21_HEADERS = (
    'IPO Date',
    'Symbol',
    'Company',
    'Exchange',
    'Price Range',
    'Shares',
    'Deal Size',
    'Market Cap',
    'Revenue',
)
_P21_SORT_ROLE = Qt.ItemDataRole.UserRole


class _P21SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by an optional normalized value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(_P21_SORT_ROLE)
        right = other.data(_P21_SORT_ROLE)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class IpoPageMixin:
    def init_page21(self) -> None:
        """Build the IPO calendar page UI."""
        self._p21_ipo_rows: list[dict[str, Any]] = []
        self._p21_ipo_fetching = False
        self._p21_ipo_loaded = False
        self._p21_ipo_worker = None
        self._p21_ipo_source = IPO_CALENDAR_SOURCE_NAME
        self._p21_ipo_fetched_at = ''
        self._p21_panel_widgets: list[QFrame] = []

        layout = QVBoxLayout(self.page21)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QFrame()
        self.set_theme_role(toolbar, 'panel')
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 10, 14, 10)
        toolbar_layout.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title = QLabel('IPO')
        self.set_theme_role(title, 'page_title')
        subtitle = QLabel('Upcoming US IPO calendar. Dates are estimates and may change.')
        self.set_theme_role(subtitle, 'muted')
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        toolbar_layout.addLayout(title_col)
        toolbar_layout.addStretch()
        self.p21_status_lbl = QLabel('Loading cached IPO calendar...')
        self.p21_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.p21_status_lbl.setMinimumWidth(320)
        self.set_theme_role(self.p21_status_lbl, 'status_muted')
        toolbar_layout.addWidget(self.p21_status_lbl)
        self.p21_refresh_btn = QPushButton('Refresh')
        self.p21_refresh_btn.setMinimumHeight(34)
        self.p21_refresh_btn.setMinimumWidth(110)
        self.set_theme_variant(self.p21_refresh_btn, 'accent')
        self.p21_refresh_btn.clicked.connect(lambda *_: self._p21_refresh_ipo_calendar(force=True))
        toolbar_layout.addWidget(self.p21_refresh_btn)
        layout.addWidget(toolbar)
        self._p21_panel_widgets.append(toolbar)

        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)

        panel_header = QHBoxLayout()
        section_title = QLabel('Upcoming IPOs')
        self.set_theme_role(section_title, 'section_title')
        self.p21_cache_lbl = QLabel('Cache not loaded')
        self.p21_cache_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p21_cache_lbl, 'status_muted')
        panel_header.addWidget(section_title)
        panel_header.addStretch()
        panel_header.addWidget(self.p21_cache_lbl)
        panel_layout.addLayout(panel_header)

        self.p21_ipo_table = QTableWidget(0, len(_P21_HEADERS))
        self.p21_ipo_table.setHorizontalHeaderLabels(list(_P21_HEADERS))
        self.p21_ipo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p21_ipo_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p21_ipo_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p21_ipo_table.setAlternatingRowColors(True)
        self.p21_ipo_table.verticalHeader().setVisible(False)
        self.p21_ipo_table.verticalHeader().setDefaultSectionSize(24)
        header = self.p21_ipo_table.horizontalHeader()
        header.setMinimumHeight(28)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(_P21_HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.p21_ipo_table.setColumnWidth(0, 120)
        self.p21_ipo_table.setColumnWidth(1, 90)
        self.p21_ipo_table.setColumnWidth(3, 120)
        self.p21_ipo_table.setColumnWidth(4, 130)
        self.p21_ipo_table.setColumnWidth(5, 120)
        self.p21_ipo_table.setColumnWidth(6, 120)
        self.p21_ipo_table.setColumnWidth(7, 120)
        self.p21_ipo_table.setColumnWidth(8, 120)
        self.p21_ipo_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.p21_ipo_table.setSortingEnabled(True)
        panel_layout.addWidget(self.p21_ipo_table, 1)
        layout.addWidget(panel, 1)
        self._p21_panel_widgets.append(panel)

        self._p21_restore_cached_ipo_calendar()
        self._apply_ipo_theme()

    def _p21_restore_cached_ipo_calendar(self) -> bool:
        """Load cached IPO rows without starting a network refresh."""
        cached = IpoCalendarWorker.load_cached_payload(allow_stale=True)
        if not cached:
            self._p21_ipo_loaded = True
            self._p21_render_ipo_rows([])
            self._p21_set_status('No cached IPO calendar yet. Use Refresh to fetch upcoming IPOs.', 'warning')
            self._p21_set_cache_text('No cache loaded', 'warning')
            return False
        self._p21_apply_ipo_payload(cached, restored=True)
        return bool(cached.get('rows'))

    def _p21_refresh_ipo_calendar(self, *, force: bool = False) -> bool:
        """Refresh the IPO calendar from the configured source."""
        if getattr(self, '_p21_ipo_fetching', False):
            self._p21_set_status('IPO refresh already running...', 'muted')
            return False
        worker = IpoCalendarWorker(force=force)
        worker.error.connect(self._p21_on_ipo_error)
        self._p21_ipo_worker = worker
        launched = self._launch_worker(worker, self._p21_on_ipo_ready, '_p21_ipo_fetching')
        if launched:
            self._p21_set_status('Refreshing IPO calendar...', 'muted')
            self.p21_refresh_btn.setEnabled(False)
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Refreshing IPO calendar...', status='muted')
        return bool(launched)

    def _p21_on_ipo_ready(self, payload: Any) -> None:
        """Render IPO rows returned by the worker."""
        self._p21_ipo_fetching = False
        self._p21_ipo_worker = None
        self.p21_refresh_btn.setEnabled(True)
        self._p21_apply_ipo_payload(payload, restored=False)
        row_count = len(getattr(self, '_p21_ipo_rows', []) or [])
        if hasattr(self, 'status_bar'):
            self.set_status_text(
                self.status_bar,
                f'IPO calendar refreshed: {row_count} row(s).',
                status='positive' if row_count else 'warning',
            )

    def _p21_on_ipo_error(self, message: Any) -> None:
        """Display an IPO refresh error while preserving rendered cache."""
        self._p21_ipo_fetching = False
        self._p21_ipo_worker = None
        self.p21_refresh_btn.setEnabled(True)
        text = str(message or 'IPO calendar unavailable').strip()
        cached = IpoCalendarWorker.load_cached_payload(allow_stale=True)
        if cached and cached.get('rows'):
            self._p21_apply_ipo_payload(cached, restored=True)
            self._p21_set_status(f'Refresh failed; showing stale cache. {text}', 'warning')
        else:
            self._p21_set_status(f'IPO refresh failed: {text}', 'negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'IPO refresh failed: {text}', status='negative')

    def _p21_apply_ipo_payload(self, payload: Any, *, restored: bool) -> None:
        data = payload if isinstance(payload, dict) else {}
        rows = [dict(row) for row in list(data.get('rows') or []) if isinstance(row, dict)]
        self._p21_ipo_rows = rows
        self._p21_ipo_loaded = True
        self._p21_ipo_source = str(data.get('source') or IPO_CALENDAR_SOURCE_NAME).strip()
        self._p21_ipo_fetched_at = str(data.get('fetched_at') or '').strip()
        self._p21_render_ipo_rows(rows)

        source = self._p21_ipo_source or IPO_CALENDAR_SOURCE_NAME
        fetched = self._p21_format_timestamp(self._p21_ipo_fetched_at)
        from_cache = bool(data.get('from_cache')) or restored
        stale = bool(data.get('stale'))
        status = f'{len(rows)} upcoming IPO(s) from {source}'
        if fetched:
            status = f'{status}; fetched {fetched}'
        if from_cache:
            status = f'{status}; cache loaded'
        if stale:
            warning = str(data.get('warning') or '').strip()
            status = f'{status}; refresh failed, stale cache shown'
            if warning:
                self.p21_status_lbl.setToolTip(warning)
        else:
            self.p21_status_lbl.setToolTip(status)
        if not rows:
            status = 'No upcoming IPO rows available. Dates are estimated and may change.'
        self._p21_set_status(status, 'warning' if stale or not rows else 'positive')
        self._p21_set_cache_text(self._p21_cache_status_text(data), 'warning' if stale else 'muted')

    def _p21_render_ipo_rows(self, rows: list[dict[str, Any]]) -> None:
        table = self.p21_ipo_table
        table.setSortingEnabled(False)
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._p21_ipo_rows = normalized_rows
        table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            values = (
                self._p21_display_date(row),
                str(row.get('symbol') or '--').upper(),
                str(row.get('company') or '--'),
                str(row.get('exchange') or '--'),
                str(row.get('price_range') or '--'),
                str(row.get('shares_offered') or '--'),
                str(row.get('deal_size') or '--'),
                str(row.get('market_cap') or '--'),
                str(row.get('revenue') or '--'),
            )
            sort_values = (
                str(row.get('date') or ''),
                values[1],
                values[2].casefold(),
                values[3].casefold(),
                self._p21_numeric_sort_value(values[4]),
                self._p21_numeric_sort_value(values[5]),
                self._p21_numeric_sort_value(values[6]),
                self._p21_numeric_sort_value(values[7]),
                self._p21_numeric_sort_value(values[8]),
            )
            for column, value in enumerate(values):
                item = _P21SortableTableWidgetItem(value)
                item.setData(_P21_SORT_ROLE, sort_values[column])
                if column in (0, 1, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column >= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _p21_display_date(self, row: dict[str, Any]) -> str:
        display = str(row.get('date_display') or '').strip()
        if display:
            return display
        try:
            parsed = datetime.date.fromisoformat(str(row.get('date') or '')[:10])
        except ValueError:
            return '--'
        return parsed.strftime('%b %d, %Y')

    def _p21_set_status(self, text: Any, status: str = 'muted') -> None:
        self.set_status_text(self.p21_status_lbl, str(text or ''), status=status)

    def _p21_set_cache_text(self, text: Any, status: str = 'muted') -> None:
        self.set_status_text(self.p21_cache_lbl, str(text or ''), status=status)

    def _p21_cache_status_text(self, payload: dict[str, Any]) -> str:
        age_seconds = payload.get('cache_age_seconds')
        age_text = self._p21_format_age(age_seconds)
        fetched = self._p21_format_timestamp(str(payload.get('fetched_at') or ''))
        if age_text:
            freshness = 'fresh' if float(age_seconds or 0.0) <= IPO_CALENDAR_CACHE_TTL_SECONDS else 'stale'
            return f'Cache {freshness}: {age_text} old'
        if fetched:
            return f'Cached at {fetched}'
        return 'Cache status unavailable'

    @staticmethod
    def _p21_format_timestamp(value: str) -> str:
        try:
            parsed = datetime.datetime.fromisoformat(str(value or ''))
        except ValueError:
            return ''
        return parsed.strftime('%Y-%m-%d %H:%M')

    @staticmethod
    def _p21_format_age(value: Any) -> str:
        try:
            seconds = float(value)
        except Exception:
            return ''
        if not math.isfinite(seconds):
            return ''
        minutes = max(seconds / 60.0, 0.0)
        if minutes < 60:
            return f'{minutes:.0f}m'
        hours = minutes / 60.0
        if hours < 48:
            return f'{hours:.1f}h'
        return f'{hours / 24.0:.1f}d'

    @staticmethod
    def _p21_numeric_sort_value(value: Any) -> float:
        text = str(value or '').upper().replace('$', '').replace(',', '').strip()
        if not text or text == '--' or text == '-':
            return float('-inf')
        multiplier = 1.0
        if text.endswith('B'):
            multiplier = 1_000_000_000.0
            text = text[:-1]
        elif text.endswith('M'):
            multiplier = 1_000_000.0
            text = text[:-1]
        elif text.endswith('K'):
            multiplier = 1_000.0
            text = text[:-1]
        if '-' in text:
            text = text.split('-')[-1].strip()
        try:
            numeric = float(text)
        except Exception:
            return float('-inf')
        return numeric * multiplier if math.isfinite(numeric) else float('-inf')

    def _apply_ipo_theme(self) -> None:
        """Refresh IPO page theme-dependent surfaces."""
        for panel in getattr(self, '_p21_panel_widgets', []):
            self.set_theme_role(panel, 'panel')
        for label_name in ('p21_status_lbl', 'p21_cache_lbl'):
            label = getattr(self, label_name, None)
            if label is not None and not str(label.styleSheet() or '').strip():
                self.set_theme_role(label, 'status_muted')
