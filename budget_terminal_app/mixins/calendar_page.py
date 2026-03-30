from __future__ import annotations
import calendar as _calendar_mod
from typing import Any
from ..compat import *

_P7_SPLITTER_CONFIG = user_data_path('p7_splitter.json')

class CalendarPageMixin:
    def _p7_calendar_display_flags(self) -> Any:
        """Return the current calendar/export category visibility toggles."""
        show_econ = self.p7_export_economic_cb.isChecked() if hasattr(self, 'p7_export_economic_cb') else True
        show_company = self.p7_export_company_cb.isChecked() if hasattr(self, 'p7_export_company_cb') else True
        show_options = self.p7_export_options_cb.isChecked() if hasattr(self, 'p7_export_options_cb') else True
        return show_econ, show_company, show_options

    def _p7_on_calendar_filter_changed(self, *_: Any) -> None:
        """Re-render the calendar immediately when a category toggle changes."""
        self._p7_render_month()

    def _p7_compact_detail_tables(self, *tables: Any, max_rows: int = 6) -> None:
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
        if hasattr(self, 'p7_options_exp_table'):
            self._p7_apply_equal_table_widths(self.p7_options_exp_table)

    def _p7_save_splitter_sizes(self, *_: Any) -> None:
        """Persist the calendar detail splitter sizes to disk."""
        if not hasattr(self, 'p7_details_splitter'):
            return
        sizes = [int(s) for s in self.p7_details_splitter.sizes() if int(s) > 0]
        if len(sizes) == 4:
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
            if isinstance(sizes, list) and len(sizes) == 4:
                self.p7_details_splitter.setSizes([int(s) for s in sizes])
        except Exception:
            pass

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
        self._p7_render_month()

    def init_page7(self) -> None:
        """Build the Calendar page UI."""
        layout = QVBoxLayout(self.page7)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
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
        refresh_cal_btn = QPushButton('Refresh')
        refresh_cal_btn.clicked.connect(self._p7_fetch_events)
        self.p7_tz_combo = QComboBox()
        self.p7_tz_combo.setFixedWidth(120)
        self.p7_tz_combo.setStyleSheet('QComboBox { font-size: 11px; }')
        for name, _ in self._tz_choices:
            self.p7_tz_combo.addItem(name)
        self.p7_tz_combo.currentIndexChanged.connect(self._p7_on_timezone_changed)
        header.addWidget(self.p7_prev_btn)
        header.addWidget(self.p7_month_label)
        header.addWidget(self.p7_next_btn)
        header.addSpacing(12)
        header.addWidget(QLabel('Ref TZ'))
        header.addWidget(self.p7_tz_combo)
        header.addSpacing(8)
        header.addWidget(refresh_cal_btn)
        export_btn = QPushButton('Export for LLM')
        export_btn.clicked.connect(self._p7_export_for_llm)
        header.addWidget(export_btn)
        layout.addLayout(header)
        self.p7_grid = QGridLayout()
        self.p7_grid.setSpacing(2)
        for col, day_name in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
            lbl = QLabel(day_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('font-weight: bold; color: #888; font-size: 20px; padding: 4px;')
            self.p7_grid.addWidget(lbl, 0, col)
        self.p7_day_cells = []
        for row in range(6):
            row_cells = []
            for col in range(7):
                cell = QLabel()
                cell.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                cell.setWordWrap(True)
                cell.setStyleSheet('QLabel { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 4px; padding: 3px; font-size: 12px; min-height: 70px; }')
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
        company_layout.setContentsMargins(6, 6, 6, 6)
        company_layout.setSpacing(2)
        company_lbl = QLabel('<b>Upcoming Earnings & Corporate Events</b>')
        company_lbl.setStyleSheet('font-size: 15px; color: #8888aa;')
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
        econ_layout.setContentsMargins(6, 6, 6, 6)
        econ_layout.setSpacing(2)
        econ_lbl = QLabel('<b>Upcoming Economic Events</b>')
        econ_lbl.setStyleSheet('font-size: 15px; color: #8888aa;')
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
        options_widget = QWidget()
        options_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        options_widget.setStyleSheet('background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;')
        options_tab_layout = QVBoxLayout(options_widget)
        options_tab_layout.setContentsMargins(6, 6, 6, 6)
        options_tab_layout.setSpacing(2)
        self.p7_options_exp_label = QLabel('<b>Options Expiration</b>')
        self.p7_options_exp_label.setStyleSheet('font-size: 15px; color: #8888aa;')
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
        export_opts_layout.setContentsMargins(6, 6, 6, 6)
        export_opts_layout.setSpacing(4)
        export_opts_lbl = QLabel('<b>Show on Calendar</b>')
        export_opts_lbl.setStyleSheet('font-size: 15px; color: #8888aa;')
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
        export_opts_layout.addStretch()
        self.p7_details_splitter.addWidget(export_opts_widget)
        for i in range(4):
            self.p7_details_splitter.setStretchFactor(i, 1)
        self._p7_restore_splitter_sizes()
        self.p7_details_splitter.splitterMoved.connect(self._p7_save_splitter_sizes)
        layout.addWidget(self.p7_details_splitter)
        today = self._p7_get_reference_today()
        self._p7_year = today.year
        self._p7_month = today.month
        self._p7_events = {}
        self._p7_fetching = False
        self._p7_render_month()
        self._p7_apply_detail_table_widths()

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
        self._p7_render_month()

    def _p7_fetch_events(self) -> None:
        """Handle p7 fetch events."""
        self._launch_worker(CalendarWorker(self.tickers[:]), self._p7_on_events_ready, '_p7_fetching')

    def _p7_on_events_ready(self, results: Any) -> None:
        """Handle p7 on events ready."""
        self._p7_fetching = False
        self._p7_events = results
        self._p7_render_month()

    def _p7_render_month(self) -> None:
        """Handle p7 render month."""
        import calendar
        today = self._p7_get_reference_today()
        year, month = (self._p7_year, self._p7_month)
        show_econ, show_company, show_options = self._p7_calendar_display_flags()
        self.p7_month_label.setText(f'{calendar.month_name[month]} {year}')
        _ECON_COLORS = {'FOMC Decision': '#e040fb', 'CPI Release': '#ff5252', 'NFP Jobs Report': '#ffab40', 'PCE Inflation': '#7c4dff', 'GDP Report': '#69f0ae'}
        econ_events = _get_economic_events(year, month) if show_econ else []
        date_events = {}
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
        for table, rows in ((self.p7_company_events_table, company_events), (self.p7_economic_events_table, economic_events)):
            table.setRowCount(len(rows))
            for i, (d, ticker, evt, detail, color) in enumerate(rows):
                date_str = d.strftime('%b %d')
                for col, text in enumerate([date_str, ticker, evt, detail]):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col == 2:
                        item.setForeground(QColor(color))
                    table.setItem(i, col, item)
        self._p7_refresh_options_expirations()
        self._p7_compact_detail_tables(
            self.p7_company_events_table,
            self.p7_economic_events_table,
            self.p7_options_exp_table,
        )
        self._p7_apply_detail_table_widths()

    def _p7_export_for_llm(self) -> None:
        """Copy the current month's calendar data with LLM instructions to the clipboard."""
        year, month = self._p7_year, self._p7_month
        month_name = _calendar_mod.month_name[month]
        today = self._p7_get_reference_today()
        inc_econ, inc_company, inc_options = self._p7_calendar_display_flags()

        # --- Collect economic events ---
        econ_events = []
        if inc_econ:
            for d, name, imp in _get_economic_events(year, month):
                econ_events.append((d, name, imp))
            econ_events.sort(key=lambda x: x[0])

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
        if inc_company:
            lines.append('  Earnings         -> "[EARNINGS] <TICKER>"')
            lines.append('  Ex-Dividend      -> "[EX-DIV] <TICKER>"')
        if inc_options:
            lines.append('  Options Expiry   -> "[OPTIONS] <TICKER> <STRIKE> <STRATEGY> x<QTY> expires"')
        lines.append('')
        lines.append('IMPORTANT:')
        lines.append('  - Do NOT create duplicate events if they already exist on the calendar.')
        lines.append('  - Skip any events with dates that have already passed.')
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
