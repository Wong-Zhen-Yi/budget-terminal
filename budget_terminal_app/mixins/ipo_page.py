from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.ipo_calendar import (
    CompletedIpoWorker,
    IPO_CALENDAR_CACHE_TTL_SECONDS,
    IPO_CALENDAR_SOURCE_NAME,
    IPO_COMPLETED_SOURCE_NAME,
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
_P21_COMPLETED_HEADERS = (
    'IPO Date',
    'Symbol',
    'Company',
    'IPO Price',
    'Current',
    'Return',
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
        self._p21_completed_rows: list[dict[str, Any]] = []
        self._p21_completed_fetching = False
        self._p21_completed_loaded = False
        self._p21_completed_worker = None
        self._p21_completed_source = IPO_COMPLETED_SOURCE_NAME
        self._p21_completed_fetched_at = ''
        self._p21_completed_year = datetime.date.today().year
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
        subtitle = QLabel('Completed IPOs and upcoming US IPOs through year-end. Dates are estimates and may change.')
        self.set_theme_role(subtitle, 'muted')
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        toolbar_layout.addLayout(title_col)
        toolbar_layout.addStretch()
        self.p21_status_lbl = QLabel('Loading cached IPO data...')
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

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)
        body_splitter.setHandleWidth(6)

        completed_panel = QFrame()
        self.set_theme_role(completed_panel, 'panel')
        completed_layout = QVBoxLayout(completed_panel)
        completed_layout.setContentsMargins(10, 10, 10, 10)
        completed_layout.setSpacing(6)

        completed_header = QHBoxLayout()
        completed_title = QLabel('Completed IPOs')
        self.set_theme_role(completed_title, 'section_title')
        self.p21_completed_cache_lbl = QLabel('Cache not loaded')
        self.p21_completed_cache_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p21_completed_cache_lbl, 'status_muted')
        completed_header.addWidget(completed_title)
        completed_header.addStretch()
        completed_header.addWidget(self.p21_completed_cache_lbl)
        completed_layout.addLayout(completed_header)

        self.p21_completed_table = QTableWidget(0, len(_P21_COMPLETED_HEADERS))
        self.p21_completed_table.setHorizontalHeaderLabels(list(_P21_COMPLETED_HEADERS))
        self.p21_completed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p21_completed_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p21_completed_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p21_completed_table.setAlternatingRowColors(True)
        self.p21_completed_table.verticalHeader().setVisible(False)
        self.p21_completed_table.verticalHeader().setDefaultSectionSize(24)
        completed_table_header = self.p21_completed_table.horizontalHeader()
        completed_table_header.setMinimumHeight(28)
        completed_table_header.setSectionsMovable(True)
        completed_table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        completed_table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        completed_table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(_P21_COMPLETED_HEADERS)):
            completed_table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.p21_completed_table.setColumnWidth(0, 120)
        self.p21_completed_table.setColumnWidth(1, 90)
        self.p21_completed_table.setColumnWidth(3, 100)
        self.p21_completed_table.setColumnWidth(4, 100)
        self.p21_completed_table.setColumnWidth(5, 90)
        self.p21_completed_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.p21_completed_table.setSortingEnabled(True)
        completed_layout.addWidget(self.p21_completed_table, 1)
        body_splitter.addWidget(completed_panel)
        self._p21_panel_widgets.append(completed_panel)

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
        body_splitter.addWidget(panel)
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 3)
        layout.addWidget(body_splitter, 1)
        self._p21_panel_widgets.append(panel)

        self._p21_restore_cached_completed_ipos()
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

    def _p21_restore_cached_completed_ipos(self) -> bool:
        """Load cached completed IPO rows without starting a network refresh."""
        cached = CompletedIpoWorker.load_cached_payload(year=self._p21_completed_year, allow_stale=True)
        if not cached:
            self._p21_completed_loaded = True
            self._p21_render_completed_rows([])
            self._p21_set_completed_cache_text('No cache loaded', 'warning')
            return False
        self._p21_apply_completed_payload(cached, restored=True)
        return bool(cached.get('rows'))

    def _p21_refresh_ipo_calendar(self, *, force: bool = False) -> bool:
        """Refresh completed and upcoming IPO data from their configured sources."""
        completed_launched = self._p21_refresh_completed_ipos(force=force)
        upcoming_launched = self._p21_refresh_upcoming_ipo_calendar(force=force)
        launched = bool(completed_launched or upcoming_launched)
        if launched:
            self._p21_set_status('Refreshing IPO data...', 'muted')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Refreshing IPO data...', status='muted')
        elif getattr(self, '_p21_completed_fetching', False) or getattr(self, '_p21_ipo_fetching', False):
            self._p21_set_status('IPO refresh already running...', 'muted')
        return launched

    def _p21_refresh_upcoming_ipo_calendar(self, *, force: bool = False) -> bool:
        """Refresh upcoming IPO rows from the configured source."""
        if getattr(self, '_p21_ipo_fetching', False):
            return False
        worker = IpoCalendarWorker(force=force)
        worker.error.connect(self._p21_on_ipo_error)
        self._p21_ipo_worker = worker
        launched = self._launch_worker(worker, self._p21_on_ipo_ready, '_p21_ipo_fetching')
        if launched:
            self._p21_update_refresh_button_state()
        return bool(launched)

    def _p21_refresh_completed_ipos(self, *, force: bool = False) -> bool:
        """Refresh completed IPO rows from the current-year source."""
        if getattr(self, '_p21_completed_fetching', False):
            return False
        worker = CompletedIpoWorker(force=force, year=self._p21_completed_year)
        worker.error.connect(self._p21_on_completed_error)
        self._p21_completed_worker = worker
        launched = self._launch_worker(worker, self._p21_on_completed_ready, '_p21_completed_fetching')
        if launched:
            self._p21_update_refresh_button_state()
            self._p21_set_completed_cache_text('Refreshing completed IPOs...', 'muted')
        return bool(launched)

    def _p21_on_ipo_ready(self, payload: Any) -> None:
        """Render IPO rows returned by the worker."""
        self._p21_ipo_fetching = False
        self._p21_ipo_worker = None
        self._p21_update_refresh_button_state()
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
        self._p21_update_refresh_button_state()
        text = str(message or 'IPO calendar unavailable').strip()
        cached = IpoCalendarWorker.load_cached_payload(allow_stale=True)
        if cached and cached.get('rows'):
            self._p21_apply_ipo_payload(cached, restored=True)
            self._p21_set_status(f'Refresh failed; showing stale cache. {text}', 'warning')
        else:
            self._p21_set_status(f'IPO refresh failed: {text}', 'negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'IPO refresh failed: {text}', status='negative')

    def _p21_on_completed_ready(self, payload: Any) -> None:
        """Render completed IPO rows returned by the worker."""
        self._p21_completed_fetching = False
        self._p21_completed_worker = None
        self._p21_update_refresh_button_state()
        self._p21_apply_completed_payload(payload, restored=False)

    def _p21_on_completed_error(self, message: Any) -> None:
        """Display a completed IPO refresh error while preserving rendered cache."""
        self._p21_completed_fetching = False
        self._p21_completed_worker = None
        self._p21_update_refresh_button_state()
        text = str(message or 'Completed IPOs unavailable').strip()
        cached = CompletedIpoWorker.load_cached_payload(year=self._p21_completed_year, allow_stale=True)
        if cached and cached.get('rows'):
            self._p21_apply_completed_payload(cached, restored=True)
            self._p21_set_completed_cache_text(f'Refresh failed; stale cache shown', 'warning')
            self.p21_completed_cache_lbl.setToolTip(text)
        else:
            self._p21_set_completed_cache_text(f'Completed IPO refresh failed', 'negative')
            self.p21_completed_cache_lbl.setToolTip(text)

    def _p21_update_refresh_button_state(self) -> None:
        fetching = bool(getattr(self, '_p21_ipo_fetching', False) or getattr(self, '_p21_completed_fetching', False))
        if hasattr(self, 'p21_refresh_btn'):
            self.p21_refresh_btn.setEnabled(not fetching)

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
        year_end = datetime.date.today().strftime('%Y-12-31')
        status = f'{len(rows)} upcoming IPO(s) through {year_end} from {source}'
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
            status = f'No upcoming IPO rows available through {year_end}. Dates are estimated and may change.'
        self._p21_set_status(status, 'warning' if stale or not rows else 'positive')
        self._p21_set_cache_text(self._p21_cache_status_text(data), 'warning' if stale else 'muted')

    def _p21_apply_completed_payload(self, payload: Any, *, restored: bool) -> None:
        data = payload if isinstance(payload, dict) else {}
        rows = [dict(row) for row in list(data.get('rows') or []) if isinstance(row, dict)]
        self._p21_completed_rows = rows
        self._p21_completed_loaded = True
        self._p21_completed_source = str(data.get('source') or IPO_COMPLETED_SOURCE_NAME).strip()
        self._p21_completed_fetched_at = str(data.get('fetched_at') or '').strip()
        self._p21_completed_year = int(data.get('year') or self._p21_completed_year or datetime.date.today().year)
        self._p21_render_completed_rows(rows)

        source = self._p21_completed_source or IPO_COMPLETED_SOURCE_NAME
        fetched = self._p21_format_timestamp(self._p21_completed_fetched_at)
        from_cache = bool(data.get('from_cache')) or restored
        stale = bool(data.get('stale'))
        status = f'{len(rows)} completed IPO(s) in {self._p21_completed_year} from {source}'
        if fetched:
            status = f'{status}; fetched {fetched}'
        if from_cache:
            status = f'{status}; cache loaded'
        if stale:
            warning = str(data.get('warning') or '').strip()
            status = f'{status}; refresh failed, stale cache shown'
            if warning:
                self.p21_completed_cache_lbl.setToolTip(warning)
        else:
            self.p21_completed_cache_lbl.setToolTip(status)
        if not rows:
            status = f'No completed IPO rows available for {self._p21_completed_year}.'
        self._p21_set_completed_cache_text(
            self._p21_cache_status_text(data) if rows or from_cache else status,
            'warning' if stale or not rows else 'muted',
        )

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

    def _p21_render_completed_rows(self, rows: list[dict[str, Any]]) -> None:
        table = self.p21_completed_table
        table.setSortingEnabled(False)
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._p21_completed_rows = normalized_rows
        table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            values = (
                self._p21_display_date(row),
                str(row.get('symbol') or '--').upper(),
                str(row.get('company') or '--'),
                str(row.get('ipo_price') or '--'),
                str(row.get('current_price') or '--'),
                str(row.get('return') or '--'),
            )
            sort_values = (
                str(row.get('date') or ''),
                values[1],
                values[2].casefold(),
                self._p21_numeric_sort_value(values[3]),
                self._p21_numeric_sort_value(values[4]),
                self._p21_percent_sort_value(values[5]),
            )
            for column, value in enumerate(values):
                item = _P21SortableTableWidgetItem(value)
                item.setData(_P21_SORT_ROLE, sort_values[column])
                if column in (0, 1):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column >= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.DescendingOrder)

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

    def _p21_set_completed_cache_text(self, text: Any, status: str = 'muted') -> None:
        self.set_status_text(self.p21_completed_cache_lbl, str(text or ''), status=status)

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

    @staticmethod
    def _p21_percent_sort_value(value: Any) -> float:
        text = str(value or '').replace('%', '').replace(',', '').strip()
        if not text or text == '--' or text == '-':
            return float('-inf')
        try:
            numeric = float(text)
        except Exception:
            return float('-inf')
        return numeric if math.isfinite(numeric) else float('-inf')

    def _apply_ipo_theme(self) -> None:
        """Refresh IPO page theme-dependent surfaces."""
        for panel in getattr(self, '_p21_panel_widgets', []):
            self.set_theme_role(panel, 'panel')
        for label_name in ('p21_status_lbl', 'p21_cache_lbl', 'p21_completed_cache_lbl'):
            label = getattr(self, label_name, None)
            if label is not None and not str(label.styleSheet() or '').strip():
                self.set_theme_role(label, 'status_muted')
