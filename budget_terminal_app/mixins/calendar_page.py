from __future__ import annotations
import calendar as _calendar_mod
from typing import Any
from ..compat import *
from budget_terminal_app.workers.calendar import (
    CalendarWorker,
    MarketHolidayWarmupWorker,
    _get_economic_events,
    _get_economic_events_for_year,
    _get_market_holiday_events,
    _market_holidays_cached_for_year,
)
from budget_terminal_app.workers.earnings_calendar import (
    EARNINGS_CALENDAR_CACHE_TTL_SECONDS,
    EARNINGS_CALENDAR_SOURCE_NAME,
    EARNINGS_DEFAULT_RANGE_KEY,
    EarningsCalendarService,
    EarningsCalendarWorker,
)

_P7_SPLITTER_CONFIG = user_data_path('p7_splitter.json')
_P7_SPLITTER_PANE_COUNT = 5
_P7_EARNINGS_WEEKDAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri')
_P7_EARNINGS_VISIBLE_DAY_COUNT = len(_P7_EARNINGS_WEEKDAY_LABELS)

class CalendarPageMixin:
    def _p7_calendar_display_flags(self) -> Any:
        """Return the current calendar/export category visibility toggles."""
        show_econ = self.p7_export_economic_cb.isChecked() if hasattr(self, 'p7_export_economic_cb') else True
        show_company = self.p7_export_company_cb.isChecked() if hasattr(self, 'p7_export_company_cb') else True
        show_options = self.p7_export_options_cb.isChecked() if hasattr(self, 'p7_export_options_cb') else True
        show_market_holidays = self.p7_export_market_holidays_cb.isChecked() if hasattr(self, 'p7_export_market_holidays_cb') else True
        return show_econ, show_company, show_options, show_market_holidays

    def _p7_normalize_event_date(self, value: Any) -> Any:
        """Return a date object for cached Calendar event values when possible."""
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            return None

    def _p7_normalize_event_payload(self, payload: Any) -> dict[str, dict[str, Any]]:
        """Normalize Calendar worker/session payloads into the runtime event shape."""
        normalized: dict[str, dict[str, Any]] = {}
        raw_events = payload if isinstance(payload, dict) else {}
        for raw_ticker, raw_info in raw_events.items():
            ticker = str(raw_ticker or '').upper().strip()
            if not ticker or not isinstance(raw_info, dict):
                continue
            info: dict[str, Any] = {}
            earnings_date = self._p7_normalize_event_date(raw_info.get('earnings'))
            exdiv_date = self._p7_normalize_event_date(raw_info.get('exdiv'))
            analyst = str(raw_info.get('analyst', '') or '').strip()
            if earnings_date is not None:
                info['earnings'] = earnings_date
            if exdiv_date is not None:
                info['exdiv'] = exdiv_date
            if analyst:
                info['analyst'] = analyst
            normalized[ticker] = info
        return normalized

    def _p7_session_snapshot(self) -> dict[str, Any] | None:
        events = self._p7_normalize_event_payload(getattr(self, '_p7_events', {}))
        if not events:
            return None
        tz_index = self.p7_tz_combo.currentIndex() if hasattr(self, 'p7_tz_combo') else 0
        return {
            'events': serialize_session_value(events),
            'year': int(getattr(self, '_p7_year', 0) or 0),
            'month': int(getattr(self, '_p7_month', 0) or 0),
            'timezone_index': int(tz_index),
        }

    def _p7_save_session_snapshot(self, *, immediate: bool = False) -> None:
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('calendar', self._p7_session_snapshot(), immediate=immediate)

    def _p7_restore_session_snapshot(self, snapshot: Any) -> bool:
        payload = snapshot if isinstance(snapshot, dict) else {}
        events = self._p7_normalize_event_payload(deserialize_session_value(payload.get('events')))
        if not events:
            return False
        self._p7_events = events
        try:
            year = int(payload.get('year') or 0)
            month = int(payload.get('month') or 0)
        except (TypeError, ValueError):
            year = month = 0
        if year > 0 and 1 <= month <= 12:
            self._p7_year = year
            self._p7_month = month
        if hasattr(self, 'p7_tz_combo'):
            try:
                tz_index = int(payload.get('timezone_index', self.p7_tz_combo.currentIndex()) or 0)
            except (TypeError, ValueError):
                tz_index = self.p7_tz_combo.currentIndex()
            if 0 <= tz_index < self.p7_tz_combo.count():
                self.p7_tz_combo.blockSignals(True)
                self.p7_tz_combo.setCurrentIndex(tz_index)
                self.p7_tz_combo.blockSignals(False)
        self._p7_render_month()
        return True

    def _p7_restore_startup_session(self, snapshot: Any) -> None:
        self._p7_restore_session_snapshot(snapshot)

    def _p7_on_calendar_filter_changed(self, *_: Any) -> None:
        """Re-render the calendar immediately when a category toggle changes."""
        self._p7_render_month()

    def _p7_queue_market_holiday_year(self, year: Any, *, force_refresh: bool=False) -> None:
        """Warm the selected market-holiday year in the background when cache is missing."""
        try:
            year_value = int(year)
        except (TypeError, ValueError):
            return
        if (not force_refresh) and _market_holidays_cached_for_year(year_value):
            return
        pending_years = list(getattr(self, '_p7_market_holiday_pending_years', []))
        if year_value not in pending_years:
            pending_years.append(year_value)
        self._p7_market_holiday_pending_years = pending_years
        self._p7_market_holiday_force_refresh = bool(getattr(self, '_p7_market_holiday_force_refresh', False) or force_refresh)
        self._p7_start_market_holiday_warmup()

    def _p7_start_market_holiday_warmup(self) -> None:
        """Launch one background warmup worker for any pending market-holiday years."""
        if getattr(self, '_p7_market_holiday_fetching', False):
            return
        years = list(getattr(self, '_p7_market_holiday_pending_years', []))
        if not years:
            return
        self._p7_market_holiday_pending_years = []
        force_refresh = bool(getattr(self, '_p7_market_holiday_force_refresh', False))
        self._p7_market_holiday_force_refresh = False
        self._launch_worker(
            MarketHolidayWarmupWorker(years, force_refresh=force_refresh),
            self._p7_on_market_holidays_ready,
            '_p7_market_holiday_fetching',
        )

    def _p7_on_market_holidays_ready(self, _results: Any) -> None:
        """Re-render the calendar once background market-holiday data is ready."""
        self._p7_market_holiday_fetching = False
        if hasattr(self, 'p7_month_label'):
            self._p7_render_month()
        self._p7_start_market_holiday_warmup()

    def _p7_compact_detail_tables(self, *tables: Any, max_rows: int = 4) -> None:
        """Set all detail tables to the same height based on the tallest one."""
        valid = [t for t in tables if t is not None]
        if not valid:
            return
        max_row_count = max(max(t.rowCount(), 1) for t in valid)
        visible_rows = min(max_row_count, max_rows)
        for table in valid:
            header_height = table.horizontalHeader().height() if table.horizontalHeader() else 24
            row_height = table.verticalHeader().defaultSectionSize() or 24
            frame = table.frameWidth() * 2
            scrollbar_pad = 4
            target_height = header_height + visible_rows * row_height + frame + scrollbar_pad
            table.setMinimumHeight(target_height)
            table.setMaximumHeight(target_height)

    def _p7_prepare_detail_table(self, table: Any) -> None:
        """Configure detail tables to keep text compact inside fixed panel widths."""
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(44)

    def _p7_apply_equal_table_widths(self, table: Any) -> None:
        """Distribute visible width evenly so no single column dominates the panel."""
        if table is None:
            return
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        viewport_width = max(table.viewport().width(), table.width() - (table.frameWidth() * 2))
        column_count = max(1, table.columnCount())
        base_width = max(44, viewport_width // column_count)
        for col in range(column_count):
            table.setColumnWidth(col, base_width)

    def _p7_apply_detail_table_widths(self) -> None:
        """Keep Calendar detail tables evenly spaced as their containers resize."""
        if hasattr(self, 'p7_company_events_table'):
            self._p7_apply_equal_table_widths(self.p7_company_events_table)
        if hasattr(self, 'p7_economic_events_table'):
            self._p7_apply_equal_table_widths(self.p7_economic_events_table)
        if hasattr(self, 'p7_market_holidays_table'):
            self._p7_apply_equal_table_widths(self.p7_market_holidays_table)
        if hasattr(self, 'p7_options_exp_table'):
            self._p7_apply_equal_table_widths(self.p7_options_exp_table)

    def _p7_save_splitter_sizes(self, *_: Any) -> None:
        """Persist the calendar detail splitter sizes to disk."""
        if not hasattr(self, 'p7_details_splitter'):
            return
        sizes = [int(s) for s in self.p7_details_splitter.sizes() if int(s) > 0]
        if len(sizes) == _P7_SPLITTER_PANE_COUNT:
            try:
                _P7_SPLITTER_CONFIG.write_text(json.dumps(sizes))
            except Exception:
                pass

    def _p7_restore_splitter_sizes(self) -> None:
        """Restore saved calendar detail splitter sizes from disk."""
        if not hasattr(self, 'p7_details_splitter'):
            return
        try:
            sizes = json.loads(_P7_SPLITTER_CONFIG.read_text())
            if not isinstance(sizes, list):
                return
            clean_sizes = []
            for value in sizes[:_P7_SPLITTER_PANE_COUNT]:
                try:
                    clean_sizes.append(int(value))
                except Exception:
                    return
            if len(clean_sizes) == _P7_SPLITTER_PANE_COUNT:
                self.p7_details_splitter.setSizes(clean_sizes)
            elif len(clean_sizes) == 4:
                legacy_company, legacy_econ, legacy_options, legacy_filters = clean_sizes
                self.p7_details_splitter.setSizes(
                    [legacy_company, legacy_econ, legacy_econ, legacy_options, legacy_filters]
                )
        except Exception:
            pass

    def _p7_populate_detail_table(self, table: Any, rows: Any) -> None:
        """Populate a standard 4-column calendar detail table."""
        table.setRowCount(len(rows))
        for i, (event_date, label, event_name, detail, color) in enumerate(rows):
            date_str = event_date.strftime('%b %d')
            for col, text in enumerate([date_str, label, event_name, detail]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 2:
                    item.setForeground(QColor(color))
                table.setItem(i, col, item)

    def _p7_collect_year_market_holidays(self, year: Any, *, blocking: bool=True) -> Any:
        """Return holiday and early-close rows for the displayed calendar year."""
        rows = []
        for event_month in range(1, 13):
            for event in _get_market_holiday_events(year, event_month, blocking=blocking):
                event_date = event.get('date')
                if event_date is None:
                    continue
                rows.append(
                    (
                        event_date,
                        str(event.get('market', 'US Equities') or 'US Equities'),
                        str(event.get('event', 'Holiday') or 'Holiday'),
                        str(event.get('detail', '') or ''),
                        str(event.get('color', '#26c6da') or '#26c6da'),
                    )
                )
        rows.sort(key=lambda item: (item[0], item[2], item[1]))
        return rows

    def _p7_get_main_portfolio_options(self) -> Any:
        """Return saved options positions for the current main portfolio."""
        if not hasattr(self, '_get_portfolio_entry'):
            return []
        entry = self._get_portfolio_entry(getattr(self, 'main_portfolio_id', None))
        options_data = entry.get('options_tracker', []) if isinstance(entry, dict) else []
        return list(options_data) if isinstance(options_data, list) else []

    def _p7_refresh_options_expirations(self) -> None:
        """Refresh the main-portfolio options-expiration table."""
        if not hasattr(self, 'p7_options_exp_table'):
            return
        today = self._p7_get_reference_today()
        rows = []
        for pos in self._p7_get_main_portfolio_options():
            expiry_text = str(pos.get('expiry', '') or '').strip()
            if not expiry_text:
                continue
            try:
                expiry_date = datetime.datetime.strptime(expiry_text, '%Y-%m-%d').date()
            except ValueError:
                continue
            if expiry_date < today:
                continue
            dte = (expiry_date - today).days
            strategy = str(pos.get('strategy', 'Calls') or 'Calls')
            strike = float(pos.get('strike', 0.0) or 0.0)
            contracts = int(float(pos.get('contracts', 1) or 1))
            ticker = str(pos.get('ticker', '') or '').upper().strip()
            status = str(pos.get('status', 'Open') or 'Open')
            rows.append((expiry_date, ticker, strategy, strike, contracts, status, f'in {dte}d'))
        rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        self.p7_options_exp_table.setRowCount(len(rows))
        for row_index, (expiry_date, ticker, strategy, strike, contracts, status, detail) in enumerate(rows):
            values = [
                expiry_date.strftime('%b %d, %Y'),
                ticker,
                strategy,
                f'{strike:.2f}',
                f'{contracts:g}',
                status,
                detail,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 5:
                    color = '#4caf50' if status.lower() == 'open' else '#888888'
                    item.setForeground(QColor(color))
                self.p7_options_exp_table.setItem(row_index, col, item)
        if hasattr(self, 'p7_options_exp_label'):
            main_name = 'Main Portfolio'
            if hasattr(self, '_p4_portfolio_name') and hasattr(self, 'main_portfolio_index'):
                main_name = self._p4_portfolio_name(self.main_portfolio_index)
            self.p7_options_exp_label.setText(f'<b>Options Expiration</b>  <span style="color: #9aa4ad;">{main_name}</span>')

    def _p7_get_reference_today(self) -> Any:
        """Return today's date for the calendar page's selected timezone."""
        idx = self.p7_tz_combo.currentIndex() if hasattr(self, 'p7_tz_combo') else 0
        return self._now_for_timezone_index(idx).date()

    def _p7_on_timezone_changed(self, *_: Any) -> None:
        """Refresh the calendar using the page-specific reference timezone."""
        today = self._p7_get_reference_today()
        self._p7_year = today.year
        self._p7_month = today.month
        self._p7_queue_market_holiday_year(self._p7_year)
        self._p7_render_month()

    def init_page7(self) -> None:
        """Build the Calendar page UI."""
        page_layout = QVBoxLayout(self.page7)
        page_layout.setContentsMargins(8, 6, 8, 6)
        page_layout.setSpacing(4)
        self.p7_tabs = QTabWidget()
        self.p7_calendar_tab = QWidget()
        self.p7_earnings_tab = QWidget()
        self.p7_tabs.addTab(self.p7_calendar_tab, 'Calendar')
        self.p7_tabs.addTab(self.p7_earnings_tab, 'Earnings')
        self.p7_tabs.currentChanged.connect(self._p7_on_tab_changed)
        page_layout.addWidget(self.p7_tabs)
        layout = QVBoxLayout(self.p7_calendar_tab)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        title_lbl = QLabel('<b>Calendar</b>')
        title_lbl.setStyleSheet('font-size: 18px; color: white;')
        header.addWidget(title_lbl)
        header.addStretch()
        self.p7_prev_btn = QPushButton('◀')
        self.p7_prev_btn.setFixedSize(30, 26)
        self.p7_prev_btn.clicked.connect(partial(self._p7_change_month, -1))
        self.p7_month_label = QLabel()
        self.p7_month_label.setStyleSheet('font-size: 15px; font-weight: bold; color: #ffd700;')
        self.p7_next_btn = QPushButton('▶')
        self.p7_next_btn.setFixedSize(30, 26)
        self.p7_next_btn.clicked.connect(partial(self._p7_change_month, 1))
        self.p7_today_btn = QPushButton('Jump to present')
        self.p7_today_btn.setFixedHeight(26)
        self.p7_today_btn.clicked.connect(self._p7_jump_to_present)
        self.p7_tz_combo = QComboBox()
        self.p7_tz_combo.setFixedWidth(120)
        self.p7_tz_combo.setStyleSheet('QComboBox { font-size: 11px; }')
        for name, _ in self._tz_choices:
            self.p7_tz_combo.addItem(name)
        self.p7_tz_combo.currentIndexChanged.connect(self._p7_on_timezone_changed)
        header.addWidget(self.p7_prev_btn)
        header.addWidget(self.p7_month_label)
        header.addWidget(self.p7_next_btn)
        header.addWidget(self.p7_today_btn)
        header.addSpacing(12)
        header.addWidget(QLabel('Ref TZ'))
        header.addWidget(self.p7_tz_combo)
        header.addSpacing(8)
        export_btn = QPushButton('Export for LLM')
        export_btn.clicked.connect(self._p7_export_for_llm)
        header.addWidget(export_btn)
        layout.addLayout(header)
        self.p7_grid = QGridLayout()
        self.p7_grid.setSpacing(2)
        for col, day_name in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
            lbl = QLabel(day_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('font-weight: bold; color: #888; font-size: 16px; padding: 2px;')
            self.p7_grid.addWidget(lbl, 0, col)
        self.p7_day_cells = []
        for row in range(6):
            row_cells = []
            for col in range(7):
                cell = QLabel()
                cell.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                cell.setWordWrap(True)
                cell.setStyleSheet('QLabel { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 4px; padding: 2px; font-size: 11px; min-height: 48px; }')
                self.p7_grid.addWidget(cell, row + 1, col)
                row_cells.append(cell)
            self.p7_day_cells.append(row_cells)
        layout.addLayout(self.p7_grid, 1)
        self.p7_details_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p7_details_splitter.setHandleWidth(6)
        self.p7_details_splitter.setStyleSheet(
            'QSplitter::handle { background: #2a2a4a; border-radius: 2px; }'
        )
        company_widget = QWidget()
        company_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        company_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        company_layout = QVBoxLayout(company_widget)
        company_layout.setContentsMargins(4, 4, 4, 4)
        company_layout.setSpacing(2)
        company_lbl = QLabel('<b>Upcoming Earnings & Corporate Events</b>')
        company_lbl.setStyleSheet('font-size: 13px; color: #8888aa;')
        company_layout.addWidget(company_lbl)
        self.p7_company_events_table = QTableWidget(0, 4)
        self.p7_company_events_table.setHorizontalHeaderLabels(['Date', 'Ticker', 'Event', 'Details'])
        self._p7_prepare_detail_table(self.p7_company_events_table)
        self.p7_company_events_table.verticalHeader().setVisible(False)
        self.p7_company_events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p7_company_events_table.verticalHeader().setDefaultSectionSize(24)
        self.p7_company_events_table.setStyleSheet(
            'QTableWidget { background: #0d0d1f; border: 1px solid #333; '
            'border-radius: 4px; gridline-color: #24243a; }'
            'QHeaderView::section { background: #16162b; color: #aaa; '
            'border: 0; border-bottom: 1px solid #333; padding: 4px 6px; }'
        )
        company_layout.addWidget(self.p7_company_events_table)
        self.p7_details_splitter.addWidget(company_widget)
        econ_widget = QWidget()
        econ_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        econ_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        econ_layout = QVBoxLayout(econ_widget)
        econ_layout.setContentsMargins(4, 4, 4, 4)
        econ_layout.setSpacing(2)
        econ_lbl = QLabel('<b>Upcoming Economic Events</b>')
        econ_lbl.setStyleSheet('font-size: 13px; color: #8888aa;')
        econ_layout.addWidget(econ_lbl)
        self.p7_economic_events_table = QTableWidget(0, 4)
        self.p7_economic_events_table.setHorizontalHeaderLabels(['Date', 'Ticker', 'Event', 'Details'])
        self._p7_prepare_detail_table(self.p7_economic_events_table)
        self.p7_economic_events_table.verticalHeader().setVisible(False)
        self.p7_economic_events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p7_economic_events_table.verticalHeader().setDefaultSectionSize(24)
        self.p7_economic_events_table.setStyleSheet(
            'QTableWidget { background: #0d0d1f; border: 1px solid #333; '
            'border-radius: 4px; gridline-color: #24243a; }'
            'QHeaderView::section { background: #16162b; color: #aaa; '
            'border: 0; border-bottom: 1px solid #333; padding: 4px 6px; }'
        )
        econ_layout.addWidget(self.p7_economic_events_table)
        self.p7_details_splitter.addWidget(econ_widget)
        market_holidays_widget = QWidget()
        market_holidays_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        market_holidays_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        market_holidays_layout = QVBoxLayout(market_holidays_widget)
        market_holidays_layout.setContentsMargins(4, 4, 4, 4)
        market_holidays_layout.setSpacing(2)
        self.p7_market_holidays_label = QLabel('<b>US Market Holidays & Early Closes</b>')
        self.p7_market_holidays_label.setStyleSheet('font-size: 13px; color: #8888aa;')
        market_holidays_layout.addWidget(self.p7_market_holidays_label)
        self.p7_market_holidays_table = QTableWidget(0, 4)
        self.p7_market_holidays_table.setHorizontalHeaderLabels(['Date', 'Market', 'Event', 'Details'])
        self._p7_prepare_detail_table(self.p7_market_holidays_table)
        self.p7_market_holidays_table.verticalHeader().setVisible(False)
        self.p7_market_holidays_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p7_market_holidays_table.verticalHeader().setDefaultSectionSize(24)
        self.p7_market_holidays_table.setStyleSheet(
            'QTableWidget { background: #0d0d1f; border: 1px solid #333; '
            'border-radius: 4px; gridline-color: #24243a; }'
            'QHeaderView::section { background: #16162b; color: #aaa; '
            'border: 0; border-bottom: 1px solid #333; padding: 4px 6px; }'
        )
        market_holidays_layout.addWidget(self.p7_market_holidays_table)
        self.p7_details_splitter.addWidget(market_holidays_widget)
        options_widget = QWidget()
        options_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        options_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        options_tab_layout = QVBoxLayout(options_widget)
        options_tab_layout.setContentsMargins(4, 4, 4, 4)
        options_tab_layout.setSpacing(2)
        self.p7_options_exp_label = QLabel('<b>Options Expiration</b>')
        self.p7_options_exp_label.setStyleSheet('font-size: 13px; color: #8888aa;')
        options_tab_layout.addWidget(self.p7_options_exp_label)
        self.p7_options_exp_table = QTableWidget(0, 7)
        self.p7_options_exp_table.setHorizontalHeaderLabels(['Expiry', 'Ticker', 'Strategy', 'Strike', 'Qty', 'Status', 'Details'])
        self._p7_prepare_detail_table(self.p7_options_exp_table)
        self.p7_options_exp_table.verticalHeader().setVisible(False)
        self.p7_options_exp_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p7_options_exp_table.verticalHeader().setDefaultSectionSize(24)
        self.p7_options_exp_table.setStyleSheet(
            'QTableWidget { background: #0d0d1f; border: 1px solid #333; '
            'border-radius: 4px; gridline-color: #24243a; }'
            'QHeaderView::section { background: #16162b; color: #aaa; '
            'border: 0; border-bottom: 1px solid #333; padding: 4px 6px; }'
        )
        options_tab_layout.addWidget(self.p7_options_exp_table)
        self.p7_details_splitter.addWidget(options_widget)
        export_opts_widget = QWidget()
        export_opts_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        export_opts_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        export_opts_layout = QVBoxLayout(export_opts_widget)
        export_opts_layout.setContentsMargins(4, 4, 4, 4)
        export_opts_layout.setSpacing(4)
        export_opts_lbl = QLabel('<b>Show on Calendar</b>')
        export_opts_lbl.setStyleSheet('font-size: 13px; color: #8888aa;')
        export_opts_layout.addWidget(export_opts_lbl)
        cb_style = 'QCheckBox { color: #ccc; font-size: 12px; border: none; }'
        self.p7_export_economic_cb = QCheckBox('Economic Events')
        self.p7_export_economic_cb.setChecked(True)
        self.p7_export_economic_cb.setStyleSheet(cb_style)
        self.p7_export_economic_cb.toggled.connect(self._p7_on_calendar_filter_changed)
        export_opts_layout.addWidget(self.p7_export_economic_cb)
        self.p7_export_company_cb = QCheckBox('Earnings && Corporate Events')
        self.p7_export_company_cb.setChecked(True)
        self.p7_export_company_cb.setStyleSheet(cb_style)
        self.p7_export_company_cb.toggled.connect(self._p7_on_calendar_filter_changed)
        export_opts_layout.addWidget(self.p7_export_company_cb)
        self.p7_export_options_cb = QCheckBox('Options Expirations')
        self.p7_export_options_cb.setChecked(True)
        self.p7_export_options_cb.setStyleSheet(cb_style)
        self.p7_export_options_cb.toggled.connect(self._p7_on_calendar_filter_changed)
        export_opts_layout.addWidget(self.p7_export_options_cb)
        self.p7_export_market_holidays_cb = QCheckBox('Market Holidays')
        self.p7_export_market_holidays_cb.setChecked(True)
        self.p7_export_market_holidays_cb.setStyleSheet(cb_style)
        self.p7_export_market_holidays_cb.toggled.connect(self._p7_on_calendar_filter_changed)
        export_opts_layout.addWidget(self.p7_export_market_holidays_cb)
        export_opts_layout.addStretch()
        self.p7_details_splitter.addWidget(export_opts_widget)
        for i in range(_P7_SPLITTER_PANE_COUNT):
            self.p7_details_splitter.setStretchFactor(i, 1)
        self._p7_restore_splitter_sizes()
        self.p7_details_splitter.splitterMoved.connect(self._p7_save_splitter_sizes)
        layout.addWidget(self.p7_details_splitter)
        today = self._p7_get_reference_today()
        self._p7_year = today.year
        self._p7_month = today.month
        self._p7_events = {}
        self._p7_fetching = False
        self._p7_force_economic_refresh = False
        self._p7_market_holiday_fetching = False
        self._p7_market_holiday_force_refresh = False
        self._p7_market_holiday_pending_years = []
        self._p7_earnings_rows: list[dict[str, Any]] = []
        self._p7_earnings_fetching = False
        self._p7_earnings_loaded = False
        self._p7_earnings_worker = None
        self._p7_earnings_source = EARNINGS_CALENDAR_SOURCE_NAME
        self._p7_earnings_fetched_at = ''
        self._p7_earnings_request: dict[str, Any] = {}
        self._p7_earnings_panel_widgets: list[Any] = []
        self._p7_earnings_week_start = self._p7_start_of_week(today)
        self._p7_build_earnings_tab()
        self._p7_restore_cached_earnings()
        self._p7_apply_detail_table_widths()
        self._apply_calendar_theme()

    def _p7_build_earnings_tab(self) -> None:
        """Build the all-market earnings calendar subpage."""
        layout = QVBoxLayout(self.p7_earnings_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QFrame()
        self.set_theme_role(toolbar, 'panel')
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title = QLabel('Earnings')
        self.set_theme_role(title, 'section_title')
        self.p7_earnings_status_lbl = QLabel('Loading cached earnings data...')
        self.set_theme_role(self.p7_earnings_status_lbl, 'status_muted')
        title_col.addWidget(title)
        title_col.addWidget(self.p7_earnings_status_lbl)
        toolbar_layout.addLayout(title_col)
        toolbar_layout.addStretch()

        self.p7_earnings_prev_week_btn = QPushButton('<')
        self.p7_earnings_prev_week_btn.setFixedSize(30, 28)
        self.p7_earnings_prev_week_btn.clicked.connect(lambda *_: self._p7_change_earnings_week(-1))
        toolbar_layout.addWidget(self.p7_earnings_prev_week_btn)
        self.p7_earnings_week_label = QLabel('')
        self.p7_earnings_week_label.setMinimumWidth(190)
        self.p7_earnings_week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.p7_earnings_week_label, 'status_muted')
        toolbar_layout.addWidget(self.p7_earnings_week_label)
        self.p7_earnings_next_week_btn = QPushButton('>')
        self.p7_earnings_next_week_btn.setFixedSize(30, 28)
        self.p7_earnings_next_week_btn.clicked.connect(lambda *_: self._p7_change_earnings_week(1))
        toolbar_layout.addWidget(self.p7_earnings_next_week_btn)
        self.p7_earnings_current_week_btn = QPushButton('Current week')
        self.p7_earnings_current_week_btn.setMinimumHeight(28)
        self.p7_earnings_current_week_btn.clicked.connect(self._p7_jump_earnings_current_week)
        toolbar_layout.addWidget(self.p7_earnings_current_week_btn)
        toolbar_layout.addSpacing(8)

        toolbar_layout.addWidget(QLabel('Range'))
        self.p7_earnings_range_combo = QComboBox()
        self.p7_earnings_range_combo.addItem('Current + next 12 months', 'rolling')
        self.p7_earnings_range_combo.addItem('Selected year', 'year')
        self.p7_earnings_range_combo.setMinimumWidth(180)
        self.p7_earnings_range_combo.currentIndexChanged.connect(self._p7_on_earnings_range_changed)
        toolbar_layout.addWidget(self.p7_earnings_range_combo)

        toolbar_layout.addWidget(QLabel('Year'))
        self.p7_earnings_year_spin = QSpinBox()
        current_year = datetime.date.today().year
        self.p7_earnings_year_spin.setRange(1990, current_year + 10)
        self.p7_earnings_year_spin.setValue(current_year)
        self.p7_earnings_year_spin.setEnabled(False)
        self.p7_earnings_year_spin.valueChanged.connect(self._p7_on_earnings_range_changed)
        toolbar_layout.addWidget(self.p7_earnings_year_spin)

        self.p7_earnings_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p7_earnings_refresh_btn, 'accent')
        self.p7_earnings_refresh_btn.clicked.connect(lambda *_: self._p7_refresh_earnings(force=True))
        toolbar_layout.addWidget(self.p7_earnings_refresh_btn)
        self.p7_earnings_export_llm_btn = QPushButton('Export to LLM')
        self.p7_earnings_export_llm_btn.setMinimumHeight(28)
        self.p7_earnings_export_llm_btn.clicked.connect(self._p7_export_earnings_week_for_llm)
        toolbar_layout.addWidget(self.p7_earnings_export_llm_btn)
        layout.addWidget(toolbar)
        self._p7_earnings_panel_widgets.append(toolbar)

        filter_bar = QFrame()
        self.set_theme_role(filter_bar, 'panel')
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(8)

        self.p7_earnings_search_input = QLineEdit()
        self.p7_earnings_search_input.setPlaceholderText('Search symbol, company, or event')
        self.p7_earnings_search_input.textChanged.connect(self._p7_render_earnings_rows)
        filter_layout.addWidget(self.p7_earnings_search_input, 1)

        self.p7_earnings_timing_combo = QComboBox()
        self.p7_earnings_timing_combo.addItems(['All timing', 'BMO', 'AMC', 'TAS', 'TBD'])
        self.p7_earnings_timing_combo.currentIndexChanged.connect(self._p7_render_earnings_rows)
        filter_layout.addWidget(self.p7_earnings_timing_combo)

        self.p7_earnings_changed_only_cb = QCheckBox('Changed dates only')
        self.p7_earnings_changed_only_cb.toggled.connect(self._p7_render_earnings_rows)
        filter_layout.addWidget(self.p7_earnings_changed_only_cb)

        self.p7_earnings_cache_lbl = QLabel('Cache not loaded')
        self.p7_earnings_cache_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p7_earnings_cache_lbl, 'status_muted')
        filter_layout.addWidget(self.p7_earnings_cache_lbl)
        layout.addWidget(filter_bar)
        self._p7_earnings_panel_widgets.append(filter_bar)

        week_panel = QFrame()
        self.set_theme_role(week_panel, 'panel')
        week_layout = QVBoxLayout(week_panel)
        week_layout.setContentsMargins(8, 8, 8, 8)
        week_layout.setSpacing(6)
        week_header = QHBoxLayout()
        week_title = QLabel('Weekly Earnings Calendar')
        self.set_theme_role(week_title, 'section_title')
        self.p7_earnings_count_lbl = QLabel('0 rows')
        self.p7_earnings_count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p7_earnings_count_lbl, 'status_muted')
        week_header.addWidget(week_title)
        week_header.addStretch()
        week_header.addWidget(self.p7_earnings_count_lbl)
        week_layout.addLayout(week_header)

        self.p7_earnings_week_grid = QGridLayout()
        self.p7_earnings_week_grid.setSpacing(6)
        self.p7_earnings_day_headers: list[QLabel] = []
        self.p7_earnings_day_counts: list[QLabel] = []
        self.p7_earnings_day_layouts: list[QVBoxLayout] = []
        self.p7_earnings_day_empty_labels: list[QLabel] = []
        self.p7_earnings_day_cards: list[list[Any]] = [[] for _ in range(_P7_EARNINGS_VISIBLE_DAY_COUNT)]
        self.p7_earnings_day_card_symbols: list[list[str]] = [[] for _ in range(_P7_EARNINGS_VISIBLE_DAY_COUNT)]
        for day_index in range(_P7_EARNINGS_VISIBLE_DAY_COUNT):
            day_frame = QFrame()
            day_frame.setObjectName(f'p7EarningsDay{day_index}')
            day_frame.setStyleSheet(
                'QFrame { background: #101827; border: 1px solid #27344a; border-radius: 6px; }'
            )
            day_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            day_layout = QVBoxLayout(day_frame)
            day_layout.setContentsMargins(6, 6, 6, 6)
            day_layout.setSpacing(5)

            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header = QLabel(_P7_EARNINGS_WEEKDAY_LABELS[day_index])
            header.setObjectName(f'p7EarningsDayHeader{day_index}')
            header.setStyleSheet('font-size: 12px; font-weight: bold; color: #d6e0f0; border: none;')
            count = QLabel('0')
            count.setObjectName(f'p7EarningsDayCount{day_index}')
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count.setStyleSheet('font-size: 11px; color: #9aa4ad; border: none;')
            header_row.addWidget(header)
            header_row.addStretch()
            header_row.addWidget(count)
            day_layout.addLayout(header_row)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            content = QWidget()
            content.setStyleSheet('background: transparent; border: none;')
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(5)
            empty_label = QLabel('No earnings')
            empty_label.setObjectName(f'p7EarningsEmptyDay{day_index}')
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet('font-size: 11px; color: #667085; border: none; padding: 14px 2px;')
            content_layout.addWidget(empty_label)
            content_layout.addStretch()
            scroll.setWidget(content)
            day_layout.addWidget(scroll, 1)

            self.p7_earnings_day_headers.append(header)
            self.p7_earnings_day_counts.append(count)
            self.p7_earnings_day_layouts.append(content_layout)
            self.p7_earnings_day_empty_labels.append(empty_label)
            self.p7_earnings_week_grid.addWidget(day_frame, 0, day_index)
            self.p7_earnings_week_grid.setColumnStretch(day_index, 1)
        week_layout.addLayout(self.p7_earnings_week_grid, 1)
        layout.addWidget(week_panel, 1)
        self._p7_earnings_panel_widgets.append(week_panel)

    def _p7_on_tab_changed(self, index: Any) -> None:
        """Start the all-market earnings load the first time the Earnings tab is opened."""
        if not hasattr(self, 'p7_tabs') or self.p7_tabs.widget(int(index)) is not getattr(self, 'p7_earnings_tab', None):
            return
        if not getattr(self, '_p7_earnings_loaded', False) and not getattr(self, '_p7_earnings_fetching', False):
            if not self._p7_restore_cached_earnings():
                self._p7_refresh_earnings(force=False)

    def _p7_current_earnings_range(self) -> tuple[datetime.date, datetime.date, str, str]:
        """Return the selected earnings request range and cache key."""
        mode = self.p7_earnings_range_combo.currentData() if hasattr(self, 'p7_earnings_range_combo') else 'rolling'
        if mode == 'year':
            year_value = int(self.p7_earnings_year_spin.value()) if hasattr(self, 'p7_earnings_year_spin') else datetime.date.today().year
            start_date, end_date = EarningsCalendarService.year_date_range(year_value)
            return start_date, end_date, f'year_{year_value}', str(year_value)
        start_date, end_date = EarningsCalendarService.default_date_range()
        return start_date, end_date, EARNINGS_DEFAULT_RANGE_KEY, 'Current + next 12 months'

    def _p7_on_earnings_range_changed(self, *_: Any) -> None:
        """Reload cached earnings when the selected range changes."""
        if hasattr(self, 'p7_earnings_year_spin') and hasattr(self, 'p7_earnings_range_combo'):
            self.p7_earnings_year_spin.setEnabled(self.p7_earnings_range_combo.currentData() == 'year')
        if not hasattr(self, 'p7_earnings_week_grid'):
            return
        self._p7_clamp_earnings_week_to_range()
        restored = self._p7_restore_cached_earnings()
        if self._p7_earnings_tab_is_active() and not restored and not getattr(self, '_p7_earnings_fetching', False):
            self._p7_refresh_earnings(force=False)

    def _p7_earnings_tab_is_active(self) -> bool:
        return (
            hasattr(self, 'p7_tabs')
            and hasattr(self, 'p7_earnings_tab')
            and self.p7_tabs.currentWidget() is self.p7_earnings_tab
        )

    def _p7_restore_cached_earnings(self) -> bool:
        """Load cached all-market earnings rows for the selected range without refreshing."""
        if not hasattr(self, 'p7_earnings_week_grid'):
            return False
        start_date, end_date, cache_key, label = self._p7_current_earnings_range()
        cached = EarningsCalendarService.load_cached_payload(
            start_date=start_date,
            end_date=end_date,
            cache_key=cache_key,
            allow_stale=True,
        )
        if not cached:
            self._p7_earnings_loaded = False
            self._p7_earnings_rows = []
            self._p7_render_earnings_rows()
            self._p7_set_earnings_status(f'No cached earnings data for {label}.', 'warning')
            self._p7_set_earnings_cache_text('No cache loaded', 'warning')
            return False
        self._p7_apply_earnings_payload(cached, restored=True)
        return bool(cached.get('rows'))

    def _p7_refresh_earnings(self, *, force: bool = False) -> bool:
        """Refresh all-market US-listed company earnings rows."""
        if getattr(self, '_p7_earnings_fetching', False):
            self._p7_set_earnings_status('Earnings refresh already running...', 'muted')
            return False
        start_date, end_date, cache_key, label = self._p7_current_earnings_range()
        worker = EarningsCalendarWorker(
            start_date=start_date,
            end_date=end_date,
            cache_key=cache_key,
            force=force,
        )
        worker.error.connect(self._p7_on_earnings_error)
        self._p7_earnings_request = {
            'start_date': start_date,
            'end_date': end_date,
            'cache_key': cache_key,
            'label': label,
        }
        self._p7_earnings_worker = worker
        launched = self._launch_worker(worker, self._p7_on_earnings_ready, '_p7_earnings_fetching')
        if launched:
            self._p7_update_earnings_refresh_button_state()
            self._p7_set_earnings_status(f'Refreshing earnings for {label}...', 'muted')
            self._p7_set_earnings_cache_text('Refreshing...', 'muted')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Refreshing earnings for {label}...', status='muted')
        return bool(launched)

    def _p7_on_earnings_ready(self, payload: Any) -> None:
        """Render all-market earnings rows returned by the worker."""
        self._p7_earnings_fetching = False
        self._p7_earnings_worker = None
        self._p7_update_earnings_refresh_button_state()
        self._p7_apply_earnings_payload(payload, restored=False)
        row_count = len(getattr(self, '_p7_earnings_rows', []) or [])
        if hasattr(self, 'status_bar'):
            self.set_status_text(
                self.status_bar,
                f'Earnings calendar refreshed: {row_count} row(s).',
                status='positive' if row_count else 'warning',
            )

    def _p7_on_earnings_error(self, message: Any) -> None:
        """Display an earnings refresh error while preserving any stale cache."""
        self._p7_earnings_fetching = False
        self._p7_earnings_worker = None
        self._p7_update_earnings_refresh_button_state()
        text = str(message or 'Earnings calendar unavailable').strip()
        request = getattr(self, '_p7_earnings_request', {}) if isinstance(getattr(self, '_p7_earnings_request', {}), dict) else {}
        start_date = request.get('start_date')
        end_date = request.get('end_date')
        cache_key = str(request.get('cache_key') or EARNINGS_DEFAULT_RANGE_KEY)
        if isinstance(start_date, datetime.date) and isinstance(end_date, datetime.date):
            cached = EarningsCalendarService.load_cached_payload(
                start_date=start_date,
                end_date=end_date,
                cache_key=cache_key,
                allow_stale=True,
            )
        else:
            cached = None
        if cached and cached.get('rows'):
            self._p7_apply_earnings_payload(cached, restored=True)
            self._p7_set_earnings_status(f'Refresh failed; showing stale cache. {text}', 'warning')
        else:
            self._p7_set_earnings_status(f'Earnings refresh failed: {text}', 'negative')
            self._p7_set_earnings_cache_text('Refresh failed', 'negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Earnings refresh failed: {text}', status='negative')

    def _p7_apply_earnings_payload(self, payload: Any, *, restored: bool) -> None:
        """Apply earnings cache/live payload to the Earnings weekly view."""
        data = payload if isinstance(payload, dict) else {}
        rows = [dict(row) for row in list(data.get('rows') or []) if isinstance(row, dict)]
        self._p7_earnings_rows = rows
        self._p7_earnings_loaded = True
        self._p7_earnings_source = str(data.get('source') or EARNINGS_CALENDAR_SOURCE_NAME).strip()
        self._p7_earnings_fetched_at = str(data.get('fetched_at') or '').strip()
        self._p7_clamp_earnings_week_to_range()
        self._p7_render_earnings_rows()

        source = self._p7_earnings_source or EARNINGS_CALENDAR_SOURCE_NAME
        start_text = str(data.get('start_date') or '')
        end_text = str(data.get('end_date') or '')
        range_text = f'{start_text} to {end_text}' if start_text and end_text else 'selected range'
        fetched = self._p7_format_timestamp(self._p7_earnings_fetched_at)
        from_cache = bool(data.get('from_cache')) or restored
        stale = bool(data.get('stale'))
        changed_count = sum(1 for row in rows if bool(row.get('changed_date')))
        status = f'{len(rows)} earnings row(s) for {range_text} from {source}'
        if changed_count:
            status = f'{status}; {changed_count} changed date(s)'
        if fetched:
            status = f'{status}; fetched {fetched}'
        if from_cache:
            status = f'{status}; cache loaded'
        if stale:
            warning = str(data.get('warning') or '').strip()
            status = f'{status}; refresh failed, stale cache shown'
            if warning:
                self.p7_earnings_status_lbl.setToolTip(warning)
        else:
            self.p7_earnings_status_lbl.setToolTip(status)
        if not rows:
            status = f'No earnings rows available for {range_text}.'
        self._p7_set_earnings_status(status, 'warning' if stale or not rows else 'positive')
        self._p7_set_earnings_cache_text(self._p7_earnings_cache_status_text(data), 'warning' if stale else 'muted')

    def _p7_filtered_earnings_rows(self) -> list[dict[str, Any]]:
        """Return earnings rows after visible filters are applied."""
        rows = [dict(row) for row in getattr(self, '_p7_earnings_rows', []) or [] if isinstance(row, dict)]
        search = str(self.p7_earnings_search_input.text() if hasattr(self, 'p7_earnings_search_input') else '').casefold().strip()
        timing = str(self.p7_earnings_timing_combo.currentText() if hasattr(self, 'p7_earnings_timing_combo') else 'All timing').upper()
        changed_only = bool(self.p7_earnings_changed_only_cb.isChecked()) if hasattr(self, 'p7_earnings_changed_only_cb') else False
        if search:
            rows = [
                row for row in rows
                if search in str(row.get('symbol') or '').casefold()
                or search in str(row.get('company') or '').casefold()
                or search in str(row.get('event_name') or '').casefold()
            ]
        if timing and timing != 'ALL TIMING':
            rows = [row for row in rows if str(row.get('timing') or '').upper() == timing]
        if changed_only:
            rows = [row for row in rows if bool(row.get('changed_date'))]
        return rows

    def _p7_earnings_row_date(self, row: dict[str, Any]) -> datetime.date | None:
        """Return the normalized date for one earnings row."""
        try:
            return datetime.date.fromisoformat(str(row.get('date') or '')[:10])
        except ValueError:
            return self._p7_normalize_event_date(row.get('date_display'))

    @staticmethod
    def _p7_earnings_market_cap_sort_key(row: dict[str, Any]) -> tuple[int, float, str, str]:
        """Sort known market caps highest first, then fall back to time and symbol."""
        try:
            market_cap = float(row.get('market_cap_value'))
        except (TypeError, ValueError):
            market_cap = None
        if market_cap is None or market_cap != market_cap:
            return (1, 0.0, str(row.get('datetime_utc') or ''), str(row.get('symbol') or ''))
        return (0, -market_cap, str(row.get('datetime_utc') or ''), str(row.get('symbol') or ''))

    @staticmethod
    def _p7_start_of_week(value: datetime.date) -> datetime.date:
        """Return the Monday for the provided date."""
        return value - datetime.timedelta(days=value.weekday())

    def _p7_clamp_earnings_week_to_range(self) -> None:
        """Keep the visible earnings week inside the selected request range."""
        start_date, end_date, _cache_key, _label = self._p7_current_earnings_range()
        week_start = getattr(self, '_p7_earnings_week_start', None)
        if not isinstance(week_start, datetime.date):
            week_start = self._p7_start_of_week(datetime.date.today())
        start_limit = self._p7_start_of_week(start_date)
        end_limit = self._p7_start_of_week(end_date)
        if week_start < start_limit:
            week_start = start_limit
        if week_start > end_limit:
            week_start = end_limit
        self._p7_earnings_week_start = week_start

    def _p7_change_earnings_week(self, delta_weeks: int) -> None:
        """Move the Earnings weekly calendar by whole weeks."""
        week_start = getattr(self, '_p7_earnings_week_start', None)
        if not isinstance(week_start, datetime.date):
            week_start = self._p7_start_of_week(datetime.date.today())
        self._p7_earnings_week_start = week_start + datetime.timedelta(days=7 * int(delta_weeks or 0))
        self._p7_clamp_earnings_week_to_range()
        self._p7_render_earnings_rows()

    def _p7_jump_earnings_current_week(self, *_: Any) -> None:
        """Move the Earnings weekly calendar to the current week."""
        self._p7_earnings_week_start = self._p7_start_of_week(datetime.date.today())
        self._p7_clamp_earnings_week_to_range()
        self._p7_render_earnings_rows()

    def _p7_update_earnings_week_label(self) -> None:
        """Refresh the visible week label and navigation enabled states."""
        if not hasattr(self, 'p7_earnings_week_label'):
            return
        self._p7_clamp_earnings_week_to_range()
        start_date, end_date, _cache_key, _label = self._p7_current_earnings_range()
        week_start = self._p7_earnings_week_start
        week_end = week_start + datetime.timedelta(days=_P7_EARNINGS_VISIBLE_DAY_COUNT - 1)
        if week_start.year == week_end.year:
            display = f'{week_start.strftime("%b %d")} - {week_end.strftime("%b %d, %Y")}'
        else:
            display = f'{week_start.strftime("%b %d, %Y")} - {week_end.strftime("%b %d, %Y")}'
        self.p7_earnings_week_label.setText(display)
        start_limit = self._p7_start_of_week(start_date)
        end_limit = self._p7_start_of_week(end_date)
        if hasattr(self, 'p7_earnings_prev_week_btn'):
            self.p7_earnings_prev_week_btn.setEnabled(week_start > start_limit)
        if hasattr(self, 'p7_earnings_next_week_btn'):
            self.p7_earnings_next_week_btn.setEnabled(week_start < end_limit)

    def _p7_visible_earnings_week_rows(self) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
        """Return filtered earnings rows grouped into the visible Monday-Friday week."""
        self._p7_clamp_earnings_week_to_range()
        rows = self._p7_filtered_earnings_rows()
        week_start = self._p7_earnings_week_start
        week_end = week_start + datetime.timedelta(days=_P7_EARNINGS_VISIBLE_DAY_COUNT - 1)
        rows_by_day: list[list[dict[str, Any]]] = [[] for _ in range(_P7_EARNINGS_VISIBLE_DAY_COUNT)]
        for row in rows:
            row_date = self._p7_earnings_row_date(row)
            if row_date is None or row_date < week_start or row_date > week_end:
                continue
            day_index = (row_date - week_start).days
            if 0 <= day_index < _P7_EARNINGS_VISIBLE_DAY_COUNT:
                rows_by_day[day_index].append(row)
        for day_rows in rows_by_day:
            day_rows.sort(key=self._p7_earnings_market_cap_sort_key)
        return rows_by_day, rows

    def _p7_clear_earnings_day_layout(self, day_index: int) -> None:
        """Remove existing event cards from one earnings day column."""
        if not hasattr(self, 'p7_earnings_day_layouts'):
            return
        layout = self.p7_earnings_day_layouts[day_index]
        empty_label = self.p7_earnings_day_empty_labels[day_index]
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not empty_label:
                widget.deleteLater()

    def _p7_create_earnings_card(self, row: dict[str, Any]) -> QFrame:
        """Create one compact weekly-calendar earnings event card."""
        symbol = str(row.get('symbol') or '--').upper()
        company = str(row.get('company') or '--')
        timing = str(row.get('timing') or '--')
        time_display = str(row.get('time_display') or '--')
        event_name = str(row.get('event_name') or '--')
        status = str(row.get('status') or '--')
        eps_est = str(row.get('eps_estimate') or '--')
        reported = str(row.get('reported_eps') or '--')
        surprise = str(row.get('surprise_pct') or '--')
        market_cap = str(row.get('market_cap') or '--')
        changed = bool(row.get('changed_date'))

        card = QFrame()
        card.setObjectName(f'p7EarningsCard_{symbol}')
        card.setProperty('symbol', symbol)
        card.setProperty('changed_date', changed)
        border = '#ffca28' if changed else '#34425a'
        card.setStyleSheet(
            f'QFrame {{ background: #182235; border: 1px solid {border}; border-radius: 5px; }}'
            'QLabel { border: none; background: transparent; }'
        )
        card.setToolTip(event_name)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 5, 6, 5)
        card_layout.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        ticker_label = QLabel(symbol)
        ticker_label.setStyleSheet('font-size: 13px; font-weight: bold; color: #ffffff;')
        status_label = QLabel(status)
        status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_color = '#4caf50' if status.casefold() == 'reported' else '#ffd700' if status.casefold() == 'today' else '#9aa4ad'
        status_label.setStyleSheet(f'font-size: 10px; color: {status_color};')
        top_row.addWidget(ticker_label)
        top_row.addStretch()
        top_row.addWidget(status_label)
        card_layout.addLayout(top_row)

        company_label = QLabel(company)
        company_label.setWordWrap(True)
        company_label.setStyleSheet('font-size: 11px; color: #d6e0f0;')
        card_layout.addWidget(company_label)

        time_label = QLabel(f'{timing} | {time_display}')
        time_label.setWordWrap(True)
        time_label.setStyleSheet('font-size: 10px; color: #9aa4ad;')
        card_layout.addWidget(time_label)

        eps_label = QLabel(f'EPS {eps_est} / {reported} | Surprise {surprise}')
        eps_label.setWordWrap(True)
        eps_label.setStyleSheet('font-size: 10px; color: #b7c2d0;')
        card_layout.addWidget(eps_label)

        cap_label = QLabel(f'Market cap {market_cap}')
        cap_label.setWordWrap(True)
        cap_label.setStyleSheet('font-size: 10px; color: #8ea0b8;')
        card_layout.addWidget(cap_label)

        if changed:
            previous = str(row.get('previous_date') or 'previous date')
            changed_label = QLabel(f'Changed from {previous}')
            changed_label.setWordWrap(True)
            changed_label.setStyleSheet('font-size: 10px; color: #ffca28; font-weight: bold;')
            card_layout.addWidget(changed_label)
        return card

    def _p7_render_earnings_rows(self, *_: Any) -> None:
        """Render the filtered all-market earnings rows as a weekly calendar."""
        if not hasattr(self, 'p7_earnings_week_grid'):
            return
        self._p7_update_earnings_week_label()
        rows_by_day, rows = self._p7_visible_earnings_week_rows()
        week_start = self._p7_earnings_week_start
        today = datetime.date.today()
        self.p7_earnings_day_cards = [[] for _ in range(_P7_EARNINGS_VISIBLE_DAY_COUNT)]
        self.p7_earnings_day_card_symbols = [[] for _ in range(_P7_EARNINGS_VISIBLE_DAY_COUNT)]
        visible_week_count = 0
        for day_index in range(_P7_EARNINGS_VISIBLE_DAY_COUNT):
            day_date = week_start + datetime.timedelta(days=day_index)
            day_rows = rows_by_day[day_index]
            visible_week_count += len(day_rows)
            self._p7_clear_earnings_day_layout(day_index)
            header = self.p7_earnings_day_headers[day_index]
            count_label = self.p7_earnings_day_counts[day_index]
            header.setText(f'{_P7_EARNINGS_WEEKDAY_LABELS[day_index]} {day_date.strftime("%b %d")}')
            header_color = '#ffd700' if day_date == today else '#d6e0f0'
            header.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {header_color}; border: none;')
            count_label.setText(str(len(day_rows)))
            layout = self.p7_earnings_day_layouts[day_index]
            empty_label = self.p7_earnings_day_empty_labels[day_index]
            if not day_rows:
                empty_label.show()
                layout.addWidget(empty_label)
            else:
                empty_label.hide()
                for row in day_rows:
                    card = self._p7_create_earnings_card(row)
                    layout.addWidget(card)
                    self.p7_earnings_day_cards[day_index].append(card)
                    self.p7_earnings_day_card_symbols[day_index].append(str(row.get('symbol') or '').upper())
            layout.addStretch()
        if hasattr(self, 'p7_earnings_count_lbl'):
            total = len(getattr(self, '_p7_earnings_rows', []) or [])
            filtered = len(rows)
            label = f'{visible_week_count} this week'
            if filtered != total:
                label = f'{label}; {filtered} filtered of {total}'
            self.set_status_text(self.p7_earnings_count_lbl, label, status='muted')

    @staticmethod
    def _p7_earnings_export_value(value: Any, default: str = '--') -> str:
        text = str(value if value is not None else '').replace('\r', ' ').replace('\n', ' ').strip()
        return text or default

    def _p7_build_earnings_week_llm_export(self) -> tuple[str, int]:
        """Build an LLM-friendly export for the currently visible earnings business week."""
        rows_by_day, filtered_rows = self._p7_visible_earnings_week_rows()
        week_start = self._p7_earnings_week_start
        week_end = week_start + datetime.timedelta(days=_P7_EARNINGS_VISIBLE_DAY_COUNT - 1)
        visible_count = sum(len(day_rows) for day_rows in rows_by_day)
        total_rows = len(getattr(self, '_p7_earnings_rows', []) or [])
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        source = self._p7_earnings_export_value(getattr(self, '_p7_earnings_source', EARNINGS_CALENDAR_SOURCE_NAME))
        fetched_at = self._p7_format_timestamp(str(getattr(self, '_p7_earnings_fetched_at', '') or '')) or '--'
        range_start, range_end, _cache_key, range_label = self._p7_current_earnings_range()

        search = self._p7_earnings_export_value(self.p7_earnings_search_input.text() if hasattr(self, 'p7_earnings_search_input') else '', '')
        timing = self._p7_earnings_export_value(self.p7_earnings_timing_combo.currentText() if hasattr(self, 'p7_earnings_timing_combo') else 'All timing')
        changed_only = bool(self.p7_earnings_changed_only_cb.isChecked()) if hasattr(self, 'p7_earnings_changed_only_cb') else False
        filters = []
        if search:
            filters.append(f'search="{search}"')
        if timing and timing.upper() != 'ALL TIMING':
            filters.append(f'timing={timing}')
        if changed_only:
            filters.append('changed_dates_only=true')
        filter_text = ', '.join(filters) if filters else 'none'

        lines: list[str] = []
        lines.append('=' * 70)
        lines.append('BUDGET TERMINAL - EARNINGS WEEK EXPORT')
        lines.append(f'Business week: {week_start.isoformat()} to {week_end.isoformat()} (Monday-Friday)')
        lines.append(f'Exported: {exported_at}')
        lines.append(f'Source: {source}')
        lines.append(f'Data fetched: {fetched_at}')
        lines.append(f'Selected range: {range_label} ({range_start.isoformat()} to {range_end.isoformat()})')
        lines.append(f'Visible filters: {filter_text}')
        lines.append(f'Visible events: {visible_count}; filtered rows in range: {len(filtered_rows)}; cached rows: {total_rows}')
        lines.append('=' * 70)
        lines.append('')
        lines.append('LLM INSTRUCTIONS')
        lines.append('- Review these US-listed company earnings for the visible business week.')
        lines.append('- Identify the most important events, crowded reporting days, notable date changes, and names where EPS expectations or reported results deserve follow-up.')
        lines.append('- Treat DATE CHANGED markers as schedule-risk signals.')
        lines.append('- Do not assume rows outside this Monday-Friday view are included.')
        lines.append('')
        lines.append('EARNINGS BY DAY')
        lines.append('-' * 70)
        for day_index, day_rows in enumerate(rows_by_day):
            day_date = week_start + datetime.timedelta(days=day_index)
            lines.append(f'{_P7_EARNINGS_WEEKDAY_LABELS[day_index]} {day_date.isoformat()} ({len(day_rows)} events)')
            if not day_rows:
                lines.append('  (none)')
            for row in day_rows:
                symbol = self._p7_earnings_export_value(row.get('symbol')).upper()
                company = self._p7_earnings_export_value(row.get('company'))
                event_name = self._p7_earnings_export_value(row.get('event_name'))
                timing = self._p7_earnings_export_value(row.get('timing'))
                time_display = self._p7_earnings_export_value(row.get('time_display'))
                eps_est = self._p7_earnings_export_value(row.get('eps_estimate'))
                reported = self._p7_earnings_export_value(row.get('reported_eps'))
                surprise = self._p7_earnings_export_value(row.get('surprise_pct'))
                market_cap = self._p7_earnings_export_value(row.get('market_cap'))
                status = self._p7_earnings_export_value(row.get('status'))
                changed = bool(row.get('changed_date'))
                changed_text = ''
                if changed:
                    previous = self._p7_earnings_export_value(row.get('previous_date'), 'unknown previous date')
                    changed_text = f' | DATE CHANGED from {previous}'
                lines.append(
                    f'  - {symbol} | {company} | {event_name} | timing={timing} | time={time_display} | '
                    f'eps_estimate={eps_est} | reported_eps={reported} | surprise={surprise} | '
                    f'market_cap={market_cap} | status={status}{changed_text}'
                )
            lines.append('')
        lines.append('=' * 70)
        lines.append('END OF EXPORT')
        lines.append('=' * 70)
        return '\n'.join(lines), visible_count

    def _p7_export_earnings_week_for_llm(self, *_: Any) -> None:
        """Copy the currently visible earnings business week to the clipboard."""
        content, visible_count = self._p7_build_earnings_week_llm_export()
        try:
            QApplication.clipboard().setText(content)
            message = f'Earnings week export copied to clipboard ({visible_count} events)'
            self._p7_set_earnings_status(message, 'positive')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, message, status='positive')
        except Exception as e:
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Earnings export failed: {e}', status='negative')
            QMessageBox.warning(self, 'Export Failed', f'Could not copy earnings export to the clipboard:\n{e}')

    def _p7_update_earnings_refresh_button_state(self) -> None:
        fetching = bool(getattr(self, '_p7_earnings_fetching', False))
        if hasattr(self, 'p7_earnings_refresh_btn'):
            self.p7_earnings_refresh_btn.setEnabled(not fetching)

    def _p7_set_earnings_status(self, text: Any, status: str = 'muted') -> None:
        if hasattr(self, 'p7_earnings_status_lbl'):
            self.set_status_text(self.p7_earnings_status_lbl, str(text or ''), status=status)

    def _p7_set_earnings_cache_text(self, text: Any, status: str = 'muted') -> None:
        if hasattr(self, 'p7_earnings_cache_lbl'):
            self.set_status_text(self.p7_earnings_cache_lbl, str(text or ''), status=status)

    def _p7_earnings_cache_status_text(self, payload: dict[str, Any]) -> str:
        age_seconds = payload.get('cache_age_seconds')
        age_text = self._p7_format_age(age_seconds)
        fetched = self._p7_format_timestamp(str(payload.get('fetched_at') or ''))
        universe = payload.get('symbol_universe') if isinstance(payload.get('symbol_universe'), dict) else {}
        universe_count = int(universe.get('count') or 0) if isinstance(universe, dict) else 0
        universe_text = f'; {universe_count:,} US company symbols' if universe_count else ''
        if age_text:
            freshness = 'fresh' if float(age_seconds or 0.0) <= EARNINGS_CALENDAR_CACHE_TTL_SECONDS else 'stale'
            return f'Cache {freshness}: {age_text} old{universe_text}'
        if fetched:
            return f'Cached at {fetched}{universe_text}'
        return f'Cache status unavailable{universe_text}'

    @staticmethod
    def _p7_format_timestamp(value: str) -> str:
        try:
            parsed = datetime.datetime.fromisoformat(str(value or ''))
        except ValueError:
            return ''
        return parsed.strftime('%Y-%m-%d %H:%M')

    @staticmethod
    def _p7_format_age(value: Any) -> str:
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
    def _p7_numeric_sort_value(value: Any) -> float:
        try:
            numeric = float(value)
        except Exception:
            return float('-inf')
        return numeric if math.isfinite(numeric) else float('-inf')

    def _apply_calendar_theme(self) -> None:
        """Refresh theme-dependent Calendar subpage surfaces."""
        for panel in getattr(self, '_p7_earnings_panel_widgets', []):
            self.set_theme_role(panel, 'panel')
        for label_name in ('p7_earnings_status_lbl', 'p7_earnings_cache_lbl', 'p7_earnings_count_lbl'):
            label = getattr(self, label_name, None)
            if label is not None and not str(label.styleSheet() or '').strip():
                self.set_theme_role(label, 'status_muted')

    def _p7_change_month(self, delta: Any, *_: Any) -> None:
        """Handle p7 change month."""
        m = self._p7_month + delta
        y = self._p7_year
        if m < 1:
            m = 12
            y -= 1
        elif m > 12:
            m = 1
            y += 1
        self._p7_month = m
        self._p7_year = y
        self._p7_queue_market_holiday_year(self._p7_year)
        self._p7_render_month()

    def _p7_jump_to_present(self, *_: Any) -> None:
        """Move the calendar view to the current day in the selected reference timezone."""
        today = self._p7_get_reference_today()
        self._p7_year = today.year
        self._p7_month = today.month
        self._p7_queue_market_holiday_year(self._p7_year)
        self._p7_render_month()
        self._p7_save_session_snapshot()

    def _p7_fetch_events(self) -> None:
        """Handle p7 fetch events."""
        self._p7_force_economic_refresh = True
        self._p7_queue_market_holiday_year(self._p7_year, force_refresh=True)
        self._launch_worker(CalendarWorker(self.tickers[:]), self._p7_on_events_ready, '_p7_fetching')

    def _p7_on_events_ready(self, results: Any) -> None:
        """Handle p7 on events ready."""
        self._p7_fetching = False
        self._p7_events = self._p7_normalize_event_payload(results)
        self._p7_render_month()
        self._p7_save_session_snapshot()

    def _p7_render_month(self) -> None:
        """Handle p7 render month."""
        import calendar
        today = self._p7_get_reference_today()
        year, month = (self._p7_year, self._p7_month)
        show_econ, show_company, show_options, show_market_holidays = self._p7_calendar_display_flags()
        economic_years = {year}
        for m_offset in range(3):
            em = month + m_offset
            ey = year
            if em > 12:
                em -= 12
                ey += 1
            economic_years.add(ey)
        if show_econ and getattr(self, '_p7_force_economic_refresh', False):
            for econ_year in sorted(economic_years):
                _get_economic_events_for_year(econ_year, force_refresh=True)
            self._p7_force_economic_refresh = False
        self.p7_month_label.setText(f'{calendar.month_name[month]} {year}')
        _ECON_COLORS = {'FOMC Decision': '#e040fb', 'PCE Inflation': '#7c4dff', 'GDP Report': '#69f0ae'}
        econ_events = _get_economic_events(year, month) if show_econ else []
        if show_market_holidays:
            self._p7_queue_market_holiday_year(year)
        market_holiday_events = _get_market_holiday_events(year, month, blocking=False) if show_market_holidays else []
        date_events = {}
        if show_market_holidays:
            for event in market_holiday_events:
                event_date = event.get('date')
                if event_date is None or event_date.year != year or event_date.month != month:
                    continue
                date_events.setdefault(event_date.day, []).append(
                    (
                        str(event.get('cell_label', 'Holiday') or 'Holiday'),
                        '',
                        str(event.get('color', '#26c6da') or '#26c6da'),
                    )
                )
        if show_econ:
            for d, name, _imp in econ_events:
                color = _ECON_COLORS.get(name, '#aaa')
                short = name.split()[0]
                date_events.setdefault(d.day, []).append((short, '', color))
        if show_company:
            for ticker, info in self._p7_events.items():
                if info.get('earnings'):
                    d = info['earnings']
                    if d.year == year and d.month == month:
                        date_events.setdefault(d.day, []).append((ticker, 'Earnings', '#ff9800'))
                if info.get('exdiv'):
                    d = info['exdiv']
                    if d.year == year and d.month == month:
                        date_events.setdefault(d.day, []).append((ticker, 'ExDiv', '#4fc3f7'))
        _STRATEGY_SHORT = {'Calls': 'C', 'Puts': 'P', 'Covered Call': 'CC', 'Cash Secured Put': 'CSP'}
        if show_options:
            for pos in self._p7_get_main_portfolio_options():
                status = str(pos.get('status', 'Open') or 'Open')
                if status.lower() != 'open':
                    continue
                expiry_text = str(pos.get('expiry', '') or '').strip()
                if not expiry_text:
                    continue
                try:
                    expiry_date = datetime.datetime.strptime(expiry_text, '%Y-%m-%d').date()
                except ValueError:
                    continue
                if expiry_date.year == year and expiry_date.month == month:
                    ticker_opt = str(pos.get('ticker', '') or '').upper().strip()
                    strategy = str(pos.get('strategy', 'Calls') or 'Calls')
                    short = _STRATEGY_SHORT.get(strategy, strategy[:2])
                    date_events.setdefault(expiry_date.day, []).append((ticker_opt, short, '#e91e63'))
        cal = calendar.Calendar(firstweekday=0)
        month_days = list(cal.itermonthdays(year, month))
        for row in range(6):
            for col in range(7):
                idx = row * 7 + col
                cell = self.p7_day_cells[row][col]
                if idx >= len(month_days) or month_days[idx] == 0:
                    cell.setText('')
                    cell.setStyleSheet('QLabel { background: #12122a; border: 1px solid #1a1a2e; border-radius: 4px; padding: 3px; font-size: 18px; min-height: 70px; }')
                    continue
                day = month_days[idx]
                is_today = year == today.year and month == today.month and (day == today.day)
                bg = '#2a2a4a' if is_today else '#1a1a2e'
                border = '#ffd700' if is_today else '#2a2a4a'
                day_color = '#ffd700' if is_today else '#ccc'
                parts = [f"<span style='font-size:15px; font-weight:bold; color:{day_color};'>{day}</span>"]
                events = date_events.get(day, [])
                for label, suffix, color in events[:5]:
                    tag = f'{label} {suffix}'.strip()
                    parts.append(f"<span style='color:{color}; font-size:15px;'>{tag}</span>")
                cell.setText('<br>'.join(parts))
                cell.setStyleSheet(f'QLabel {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; padding: 3px; font-size: 10px; min-height: 70px; }}')
        economic_events = []
        company_events = []
        holiday_events = self._p7_collect_year_market_holidays(year, blocking=False) if show_market_holidays else []
        if hasattr(self, 'p7_market_holidays_label'):
            self.p7_market_holidays_label.setText(
                f'<b>US Market Holidays & Early Closes</b>  <span style="color: #9aa4ad;">{year}</span>'
            )
        for m_offset in range(3):
            em = month + m_offset
            ey = year
            if em > 12:
                em -= 12
                ey += 1
            for d, name, imp in _get_economic_events(ey, em):
                if d >= today:
                    days_away = (d - today).days
                    economic_events.append((d, 'ECON', name, f'in {days_away}d', _ECON_COLORS.get(name, '#aaa')))
        for ticker, info in self._p7_events.items():
            if info.get('earnings') and info['earnings'] >= today:
                d = info['earnings']
                days_away = (d - today).days
                company_events.append((d, ticker, 'Earnings', f'in {days_away}d', '#ff9800'))
            if info.get('exdiv') and info['exdiv'] >= today:
                d = info['exdiv']
                days_away = (d - today).days
                company_events.append((d, ticker, 'Ex-Dividend', f'in {days_away}d', '#4fc3f7'))
        economic_events.sort(key=lambda x: x[0])
        company_events.sort(key=lambda x: x[0])
        self._p7_populate_detail_table(self.p7_company_events_table, company_events)
        self._p7_populate_detail_table(self.p7_economic_events_table, economic_events)
        self._p7_populate_detail_table(self.p7_market_holidays_table, holiday_events)
        self._p7_refresh_options_expirations()
        self._p7_compact_detail_tables(
            self.p7_company_events_table,
            self.p7_economic_events_table,
            self.p7_market_holidays_table,
            self.p7_options_exp_table,
        )
        self._p7_apply_detail_table_widths()

    def _p7_export_for_llm(self) -> None:
        """Copy the current month's calendar data with LLM instructions to the clipboard."""
        year, month = self._p7_year, self._p7_month
        month_name = _calendar_mod.month_name[month]
        today = self._p7_get_reference_today()
        inc_econ, inc_company, inc_options, inc_market_holidays = self._p7_calendar_display_flags()

        # --- Collect economic events ---
        econ_events = []
        if inc_econ:
            for d, name, imp in _get_economic_events(year, month):
                econ_events.append((d, name, imp))
            econ_events.sort(key=lambda x: x[0])

        # --- Collect market holidays and early closes ---
        market_holiday_events = []
        if inc_market_holidays:
            for event in _get_market_holiday_events(year, month, blocking=True):
                event_date = event.get('date')
                if event_date is None:
                    continue
                market_holiday_events.append(
                    (
                        event_date,
                        str(event.get('market', 'US Equities') or 'US Equities'),
                        str(event.get('event', 'Holiday') or 'Holiday'),
                        str(event.get('detail', '') or ''),
                    )
                )
            market_holiday_events.sort(key=lambda x: (x[0], x[2], x[1]))

        # --- Collect company events (earnings, ex-div) ---
        company_events = []
        if inc_company:
            for ticker, info in self._p7_events.items():
                if info.get('earnings'):
                    d = info['earnings']
                    if d.year == year and d.month == month:
                        company_events.append((d, ticker, 'Earnings'))
                if info.get('exdiv'):
                    d = info['exdiv']
                    if d.year == year and d.month == month:
                        company_events.append((d, ticker, 'Ex-Dividend'))
            company_events.sort(key=lambda x: (x[0], x[1]))

        # --- Collect options expirations ---
        options_events = []
        if inc_options:
            for pos in self._p7_get_main_portfolio_options():
                status = str(pos.get('status', 'Open') or 'Open')
                if status.lower() != 'open':
                    continue
                expiry_text = str(pos.get('expiry', '') or '').strip()
                if not expiry_text:
                    continue
                try:
                    expiry_date = datetime.datetime.strptime(expiry_text, '%Y-%m-%d').date()
                except ValueError:
                    continue
                if expiry_date.year == year and expiry_date.month == month:
                    ticker = str(pos.get('ticker', '') or '').upper().strip()
                    strategy = str(pos.get('strategy', 'Calls') or 'Calls')
                    strike = float(pos.get('strike', 0.0) or 0.0)
                    contracts = int(float(pos.get('contracts', 1) or 1))
                    options_events.append((expiry_date, ticker, strategy, strike, contracts))
            options_events.sort(key=lambda x: (x[0], x[1]))

        # --- Build the export text ---
        lines = []
        lines.append('=' * 70)
        lines.append('BUDGET TERMINAL - CALENDAR EXPORT')
        lines.append(f'Month: {month_name} {year}')
        lines.append(f'Exported: {today.strftime("%Y-%m-%d")}')
        lines.append('=' * 70)
        lines.append('')
        lines.append('-' * 70)
        lines.append('LLM INSTRUCTIONS')
        lines.append('-' * 70)
        lines.append('')
        lines.append('You are being given financial calendar data from Budget Terminal.')
        lines.append('Your task is to create calendar events from this data.')
        lines.append('')
        lines.append('For each event below, create a calendar entry with:')
        lines.append('  - Title: Use the format shown in each section')
        lines.append('  - Date: As specified (YYYY-MM-DD)')
        lines.append('  - All-day event: Yes (unless noted otherwise)')
        lines.append('  - Calendar: Use the user\'s default calendar or a "Finance" calendar if available')
        lines.append('')
        lines.append('TITLE FORMATS:')
        if inc_econ:
            lines.append('  Economic events  -> "[ECON] <Event Name>"')
        if inc_market_holidays:
            lines.append('  Market holidays  -> "[MARKET] <Holiday Name>"')
            lines.append('  Early closes     -> "[MARKET] <Holiday Name> Early Close"')
        if inc_company:
            lines.append('  Earnings         -> "[EARNINGS] <TICKER>"')
            lines.append('  Ex-Dividend      -> "[EX-DIV] <TICKER>"')
        if inc_options:
            lines.append('  Options Expiry   -> "[OPTIONS] <TICKER> <STRIKE> <STRATEGY> x<QTY> expires"')
        lines.append('')
        lines.append('IMPORTANT:')
        lines.append('  - Do NOT create duplicate events if they already exist on the calendar.')
        lines.append('  - Skip any events with dates that have already passed.')
        if inc_market_holidays:
            lines.append('  - Early closes should be timed events at 1:00 PM Eastern Time, not all-day events.')
        lines.append(f'  - Today\'s date is {today.strftime("%Y-%m-%d")}.')
        lines.append('')

        # Economic events section
        if inc_econ:
            lines.append('-' * 70)
            lines.append('ECONOMIC EVENTS')
            lines.append('-' * 70)
            if econ_events:
                for d, name, imp in econ_events:
                    lines.append(f'  {d.strftime("%Y-%m-%d")}  {name}  (Importance: {imp})')
            else:
                lines.append('  (none)')
            lines.append('')

        # Market holidays section
        if inc_market_holidays:
            lines.append('-' * 70)
            lines.append('MARKET HOLIDAYS & EARLY CLOSES')
            lines.append('-' * 70)
            if market_holiday_events:
                for event_date, market, event_name, detail in market_holiday_events:
                    if event_date is None:
                        continue
                    suffix = '  (timed event)' if 'close' in str(detail or '').lower() else ''
                    lines.append(f'  {event_date.strftime("%Y-%m-%d")}  {market}  {event_name}  {detail}{suffix}')
            else:
                lines.append('  (none)')
            lines.append('')

        # Company events section
        if inc_company:
            lines.append('-' * 70)
            lines.append('COMPANY EVENTS (Earnings & Ex-Dividend)')
            lines.append('-' * 70)
            if company_events:
                for d, ticker, event_type in company_events:
                    lines.append(f'  {d.strftime("%Y-%m-%d")}  {ticker}  {event_type}')
            else:
                lines.append('  (none)')
            lines.append('')

        # Options expirations section
        if inc_options:
            lines.append('-' * 70)
            lines.append('OPTIONS EXPIRATIONS')
            lines.append('-' * 70)
            if options_events:
                for expiry, ticker, strategy, strike, contracts in options_events:
                    lines.append(f'  {expiry.strftime("%Y-%m-%d")}  {ticker}  {strike:.2f} {strategy} x{contracts}')
            else:
                lines.append('  (none)')
            lines.append('')
        lines.append('=' * 70)
        lines.append('END OF EXPORT')
        lines.append('=' * 70)

        content = '\n'.join(lines)
        try:
            QApplication.clipboard().setText(content)
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Calendar export copied to clipboard for {month_name} {year}', status='positive')
        except Exception as e:
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Calendar export failed: {e}', status='negative')
            QMessageBox.warning(self, 'Export Failed', f'Could not copy calendar export to the clipboard:\n{e}')
