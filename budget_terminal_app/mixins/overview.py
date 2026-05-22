from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.overview import TradingVolumeWorker

_P20_HEADERS = (
    '#',
    'Ticker',
    'Name',
    'Market Cap',
    '1D ADV ($m)',
    '5D ADV ($m)',
    '30D ADV ($m)',
    'YTD ADV ($m)',
    '1Y ADV ($m)',
)
_P20_NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole
_P20_MISSING_SORT_VALUE = float('-inf')
_P20_DOT_METRICS = {
    '1d': ('1D', '1D ADV ($m)', 'one_day_dollar_volume'),
    '5d': ('5D', '5D ADV ($m)', 'five_day_avg_dollar_volume'),
    '30d': ('30D', '30D ADV ($m)', 'thirty_day_avg_dollar_volume'),
    'ytd': ('YTD', 'YTD ADV ($m)', 'ytd_avg_dollar_volume'),
    '1y': ('1Y', '1Y ADV ($m)', 'one_year_avg_dollar_volume'),
}
_P20_FILTER_DEFAULT = 'default'
_P20_FILTER_EXCLUDE = 'exclude'
_P20_FILTER_ROW_RANGE = 'row_range'
_P20_FILTER_MODES = {_P20_FILTER_DEFAULT, _P20_FILTER_EXCLUDE, _P20_FILTER_ROW_RANGE}


class _P20NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a stored numeric value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(_P20_NUMERIC_SORT_ROLE))
            right = float(other.data(_P20_NUMERIC_SORT_ROLE))
            return left < right
        except Exception:
            return super().__lt__(other)


class _P20CompactCurrencyAxisItem(pg.AxisItem):
    """Pyqtgraph axis that renders raw dollar values as compact currency."""

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> list[str]:
        strings = []
        for value in values:
            try:
                numeric = float(value)
            except Exception:
                strings.append('')
                continue
            if not math.isfinite(numeric):
                strings.append('')
                continue
            sign = '-' if numeric < 0 else ''
            numeric = abs(numeric)
            for divisor, suffix in ((1_000_000_000_000, 'T'), (1_000_000_000, 'B'), (1_000_000, 'M')):
                if numeric >= divisor:
                    strings.append(f'{sign}${numeric / divisor:,.1f}{suffix}')
                    break
            else:
                strings.append(f'{sign}${numeric:,.0f}')
        return strings


class OverviewMixin:
    def init_page20(self) -> None:
        """Build the Trading Volumes page UI."""
        self._p20_trading_volume_all_rows: list[dict[str, Any]] = []
        self._p20_trading_volume_rows: list[dict[str, Any]] = []
        self._p20_trading_volume_fetching = False
        self._p20_trading_volume_loaded = False
        self._p20_trading_volume_cache_restored = False
        self._p20_trading_volume_auto_refresh_started = False
        self._p20_trading_volume_worker = None
        self._p20_trading_volume_source = ''
        self._p20_trading_volume_as_of = ''
        self._p20_filter_mode = _P20_FILTER_DEFAULT
        self._p20_exclude_top_count = 0
        self._p20_row_range_start = 1
        self._p20_row_range_end = 100
        self._p20_dot_metric = '1d'
        self._p20_dot_plot_points: list[tuple[float, float, str]] = []
        self._p20_dot_label_items: list[Any] = []

        layout = QVBoxLayout(self.page20)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        title_lbl = QLabel('<b>Trading Volumes</b>')
        self.set_theme_role(title_lbl, 'page_title')
        self.p20_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p20_refresh_btn, 'accent')
        self.p20_refresh_btn.clicked.connect(lambda *_: self._p20_refresh_trading_volume(force=True))
        self.p20_export_llm_btn = QPushButton('Export to LLM')
        self.set_theme_variant(self.p20_export_llm_btn, 'accent')
        self.p20_export_llm_btn.clicked.connect(self._p20_export_trading_volume_for_llm)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        header_row.addWidget(self.p20_export_llm_btn)
        header_row.addWidget(self.p20_refresh_btn)
        layout.addLayout(header_row)

        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)

        panel_header = QHBoxLayout()
        panel_title = QLabel('<b>Trading Volumes</b>')
        self.set_theme_role(panel_title, 'section_title')
        exclude_lbl = QLabel('Exclude top')
        self.set_theme_role(exclude_lbl, 'status_muted')
        self.p20_exclude_top_spin = QSpinBox()
        self.p20_exclude_top_spin.setRange(0, 100)
        self.p20_exclude_top_spin.setValue(self._p20_exclude_top_count)
        self.p20_exclude_top_spin.setFixedWidth(70)
        self.p20_exclude_top_spin.setToolTip('Hide this many highest-ranked stocks from the current Trading Volumes result.')
        self.p20_exclude_top_spin.valueChanged.connect(self._p20_on_exclude_top_changed)
        from_row_lbl = QLabel('From row')
        self.set_theme_role(from_row_lbl, 'status_muted')
        self.p20_row_range_start_spin = QSpinBox()
        self.p20_row_range_start_spin.setRange(1, 100)
        self.p20_row_range_start_spin.setValue(self._p20_row_range_start)
        self.p20_row_range_start_spin.setFixedWidth(70)
        self.p20_row_range_start_spin.setToolTip('First original rank to show when searching rows.')
        to_row_lbl = QLabel('To row')
        self.set_theme_role(to_row_lbl, 'status_muted')
        self.p20_row_range_end_spin = QSpinBox()
        self.p20_row_range_end_spin.setRange(1, 100)
        self.p20_row_range_end_spin.setValue(self._p20_row_range_end)
        self.p20_row_range_end_spin.setFixedWidth(70)
        self.p20_row_range_end_spin.setToolTip('Last original rank to show when searching rows.')
        self.p20_search_rows_btn = QPushButton('Search Rows')
        self.p20_search_rows_btn.clicked.connect(self._p20_search_row_range)
        self.p20_reset_filters_btn = QPushButton('Reset')
        self.p20_reset_filters_btn.clicked.connect(self._p20_reset_trading_volume_filters)
        self.p20_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p20_status_lbl, 'status_muted')
        self.p20_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        panel_header.addWidget(panel_title)
        panel_header.addSpacing(12)
        panel_header.addWidget(exclude_lbl)
        panel_header.addWidget(self.p20_exclude_top_spin)
        panel_header.addSpacing(10)
        panel_header.addWidget(from_row_lbl)
        panel_header.addWidget(self.p20_row_range_start_spin)
        panel_header.addWidget(to_row_lbl)
        panel_header.addWidget(self.p20_row_range_end_spin)
        panel_header.addWidget(self.p20_search_rows_btn)
        panel_header.addWidget(self.p20_reset_filters_btn)
        panel_header.addStretch()
        panel_header.addWidget(self.p20_status_lbl)
        panel_layout.addLayout(panel_header)

        self.p20_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p20_body_splitter.setChildrenCollapsible(False)

        self.p20_trading_volume_table = QTableWidget(0, len(_P20_HEADERS))
        self.p20_trading_volume_table.setHorizontalHeaderLabels(list(_P20_HEADERS))
        self.p20_trading_volume_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p20_trading_volume_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p20_trading_volume_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p20_trading_volume_table.setAlternatingRowColors(True)
        self.p20_trading_volume_table.verticalHeader().setVisible(False)
        self.p20_trading_volume_table.verticalHeader().setDefaultSectionSize(24)
        table_header = self.p20_trading_volume_table.horizontalHeader()
        table_header.setMinimumHeight(28)
        table_header.setSectionsMovable(True)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(_P20_HEADERS)):
            table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.p20_trading_volume_table.setColumnWidth(0, 48)
        self.p20_trading_volume_table.setColumnWidth(1, 90)
        self.p20_trading_volume_table.setColumnWidth(3, 130)
        for column in range(4, len(_P20_HEADERS)):
            self.p20_trading_volume_table.setColumnWidth(column, 130)
        self.p20_trading_volume_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.p20_trading_volume_table.setSortingEnabled(True)
        self.p20_body_splitter.addWidget(self.p20_trading_volume_table)

        dot_plot_pane = QWidget()
        dot_plot_layout = QVBoxLayout(dot_plot_pane)
        dot_plot_layout.setContentsMargins(8, 0, 0, 0)
        dot_plot_layout.setSpacing(6)
        dot_header = QHBoxLayout()
        dot_title = QLabel('<b>Trading Volumes Dot Plot</b>')
        self.set_theme_role(dot_title, 'section_title')
        dot_header.addWidget(dot_title)
        dot_header.addStretch()
        self.p20_dot_metric_buttons: dict[str, QPushButton] = {}
        self.p20_dot_metric_group = QButtonGroup(self.page20)
        self.p20_dot_metric_group.setExclusive(True)
        for metric_key in _P20_DOT_METRICS:
            button_label = _P20_DOT_METRICS[metric_key][0]
            button = QPushButton(button_label)
            button.setCheckable(True)
            button.setMinimumWidth(48)
            button.clicked.connect(partial(self._p20_set_dot_metric, metric_key))
            self.p20_dot_metric_group.addButton(button)
            self.p20_dot_metric_buttons[metric_key] = button
            dot_header.addWidget(button)
        self.p20_dot_metric_buttons[self._p20_dot_metric].setChecked(True)
        if hasattr(self, 'update_checked_button_state'):
            self.update_checked_button_state(self.p20_dot_metric_buttons, self._p20_dot_metric)
        dot_plot_layout.addLayout(dot_header)

        self.p20_dot_empty_lbl = QLabel('Load Trading Volumes to plot tickers.')
        self.set_theme_role(self.p20_dot_empty_lbl, 'status_muted')
        self.p20_dot_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot_plot_layout.addWidget(self.p20_dot_empty_lbl)

        self.p20_dot_plot = pg.PlotWidget(axisItems={'bottom': _P20CompactCurrencyAxisItem(orientation='bottom')})
        self.p20_dot_plot.setMinimumWidth(360)
        self.p20_dot_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if hasattr(self, 'style_plot_widget'):
            self.style_plot_widget(self.p20_dot_plot, show_y_grid=True)
        self.p20_dot_plot.showAxis('left', True)
        self.p20_dot_plot.showAxis('right', False)
        self.p20_dot_plot.setMouseEnabled(x=True, y=True)
        self.p20_dot_plot.setMenuEnabled(False)
        self.p20_dot_plot.getPlotItem().hideButtons()
        left_axis = self.p20_dot_plot.getPlotItem().getAxis('left')
        left_axis.setTextPen(self.theme_color('chart_axis') if hasattr(self, 'theme_color') else '#9aa4b2')
        left_axis.setStyle(tickTextOffset=6)
        try:
            left_axis.setWidth(52)
        except Exception:
            pass
        self.p20_dot_plot.setLabel('left', _P20_DOT_METRICS[self._p20_dot_metric][1])
        self.p20_dot_plot.setLabel('bottom', 'Market Cap')
        dot_plot_layout.addWidget(self.p20_dot_plot, 1)
        self.p20_body_splitter.addWidget(dot_plot_pane)
        self.p20_body_splitter.setStretchFactor(0, 1)
        self.p20_body_splitter.setStretchFactor(1, 1)
        self.p20_body_splitter.setSizes([600, 600])
        panel_layout.addWidget(self.p20_body_splitter, 1)
        layout.addWidget(panel, 1)
        self._p20_restore_cached_trading_volume()

    def _p20_on_show(self) -> None:
        """Load the Trading Volumes table when the page is first opened."""
        if getattr(self, '_p20_trading_volume_fetching', False):
            return
        if not getattr(self, '_p20_trading_volume_loaded', False):
            if not self._p20_restore_cached_trading_volume():
                QTimer.singleShot(0, lambda: self._p20_refresh_trading_volume(force=False))
                return
        if (
            getattr(self, '_p20_trading_volume_cache_restored', False)
            and not getattr(self, '_p20_trading_volume_auto_refresh_started', False)
        ):
            self._p20_trading_volume_auto_refresh_started = True
            QTimer.singleShot(0, lambda: self._p20_refresh_trading_volume(force=True))

    def _p20_refresh_trading_volume(self, *, force: bool = False) -> None:
        """Fetch or refresh the trading-volume table."""
        if getattr(self, '_p20_trading_volume_fetching', False):
            return
        if getattr(self, '_p20_trading_volume_loaded', False) and not force:
            return
        worker = TradingVolumeWorker()
        worker.error.connect(self._p20_on_trading_volume_error)
        self._p20_trading_volume_worker = worker
        launched = self._launch_worker(worker, self._p20_on_trading_volume_ready, '_p20_trading_volume_fetching')
        if launched:
            action = 'Refreshing' if getattr(self, '_p20_trading_volume_rows', []) else 'Loading'
            self.set_status_text(self.p20_status_lbl, f'{action} trading volume...', status='muted')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'{action} Trading Volumes...', status='muted')

    def _p20_on_trading_volume_ready(self, payload: Any) -> None:
        """Render trading-volume rows returned by the worker."""
        self._p20_trading_volume_fetching = False
        self._p20_trading_volume_loaded = True
        self._p20_trading_volume_worker = None
        data = payload if isinstance(payload, dict) else {}
        rows = [dict(row) for row in list(data.get('rows') or []) if isinstance(row, dict)]
        self._p20_trading_volume_all_rows = rows
        self._p20_trading_volume_cache_restored = False
        source = str(data.get('source') or 'Yahoo Finance')
        as_of = str(data.get('as_of') or '').strip()
        self._p20_trading_volume_source = source
        self._p20_trading_volume_as_of = as_of
        self._p20_apply_trading_volume_filter()
        self._p20_save_session_snapshot()
        visible_rows = len(getattr(self, '_p20_trading_volume_rows', []) or [])
        status = self._p20_trading_volume_status_text(visible_rows, len(rows), 'rows shown')
        if source:
            status = f'{status} from {source}'
        if as_of:
            status = f'{status} at {as_of}'
        self.set_status_text(self.p20_status_lbl, status, status='positive' if visible_rows else 'warning')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Trading Volumes refreshed: {status}.', status='positive' if visible_rows else 'warning')

    def _p20_on_trading_volume_error(self, message: Any) -> None:
        """Display a trading-volume fetch error."""
        self._p20_trading_volume_fetching = False
        self._p20_trading_volume_worker = None
        text = str(message or 'Trading Volumes unavailable').strip()
        self.set_status_text(self.p20_status_lbl, f'Error: {text}', status='negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Trading Volumes failed: {text}', status='negative')

    def _p20_session_snapshot(self) -> dict[str, Any] | None:
        """Return a compact JSON-safe snapshot for Trading Volumes startup restore."""
        rows = self._p20_snapshot_rows(getattr(self, '_p20_trading_volume_all_rows', []) or getattr(self, '_p20_trading_volume_rows', []) or [])
        if not rows:
            return None
        return {
            'rows': rows,
            'as_of': str(getattr(self, '_p20_trading_volume_as_of', '') or '').strip(),
            'source': str(getattr(self, '_p20_trading_volume_source', '') or 'Yahoo Finance').strip(),
            'filter_mode': self._p20_normalize_filter_mode(getattr(self, '_p20_filter_mode', _P20_FILTER_DEFAULT)),
            'exclude_top_count': self._p20_exclude_top_value(),
            'row_range_start': self._p20_row_range_values()[0],
            'row_range_end': self._p20_row_range_values()[1],
        }

    def _p20_save_session_snapshot(self, *, immediate: bool = False) -> None:
        """Persist the latest Trading Volumes table through the shared tab-session cache."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('overview', self._p20_session_snapshot(), immediate=immediate)

    def _p20_restore_cached_trading_volume(self) -> bool:
        """Restore cached Trading Volumes rows without starting a network fetch."""
        if getattr(self, '_p20_trading_volume_loaded', False):
            return bool(getattr(self, '_p20_trading_volume_rows', []))
        snapshot = self._get_tab_session_snapshot('overview') if hasattr(self, '_get_tab_session_snapshot') else None
        return self._p20_restore_session_snapshot(snapshot)

    def _p20_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Render a cached Trading Volumes table snapshot."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        rows = [dict(row) for row in list(payload.get('rows') or []) if isinstance(row, dict)]
        rows = self._p20_snapshot_rows(rows)
        if not rows:
            return False
        self._p20_trading_volume_all_rows = rows
        self._p20_trading_volume_loaded = True
        self._p20_trading_volume_cache_restored = True
        self._p20_trading_volume_source = str(payload.get('source') or 'Yahoo Finance').strip()
        self._p20_trading_volume_as_of = str(payload.get('as_of') or '').strip()
        self._p20_set_exclude_top_count(payload.get('exclude_top_count'), render=False)
        self._p20_set_row_range_values(payload.get('row_range_start'), payload.get('row_range_end'))
        filter_mode = self._p20_normalize_filter_mode(payload.get('filter_mode'))
        if filter_mode == _P20_FILTER_DEFAULT and self._p20_exclude_top_value() > 0:
            filter_mode = _P20_FILTER_EXCLUDE
        self._p20_filter_mode = filter_mode
        self._p20_apply_trading_volume_filter()
        visible_rows = len(getattr(self, '_p20_trading_volume_rows', []) or [])
        status = self._p20_trading_volume_status_text(visible_rows, len(rows), 'cached rows shown')
        if self._p20_trading_volume_source:
            status = f'{status} from {self._p20_trading_volume_source}'
        if self._p20_trading_volume_as_of:
            status = f'{status} at {self._p20_trading_volume_as_of}'
        self.set_status_text(self.p20_status_lbl, status, status='positive')
        return True

    def _p20_snapshot_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize Trading Volumes rows into the compact persisted shape."""
        snapshot_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get('ticker') or '').upper().strip()
            if not ticker:
                continue
            snapshot_rows.append({
                'ticker': ticker,
                'name': str(row.get('name') or ticker),
                'sector': str(row.get('sector') or 'N/A'),
                'market_cap': self._p20_json_number(row.get('market_cap')),
                'one_day_dollar_volume': self._p20_json_number(row.get('one_day_dollar_volume')),
                'five_day_avg_dollar_volume': self._p20_json_number(row.get('five_day_avg_dollar_volume')),
                'thirty_day_avg_dollar_volume': self._p20_json_number(row.get('thirty_day_avg_dollar_volume')),
                'ytd_avg_dollar_volume': self._p20_json_number(row.get('ytd_avg_dollar_volume')),
                'one_year_avg_dollar_volume': self._p20_json_number(row.get('one_year_avg_dollar_volume')),
            })
        return snapshot_rows[:100]

    def _p20_json_number(self, value: Any) -> float | None:
        try:
            numeric = float(value)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None

    def _p20_export_escape(self, value: Any) -> str:
        """Escape a value for a single Markdown table cell."""
        text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
        return text.replace('|', '\\|') or 'N/A'

    def _p20_format_export_currency(self, value: Any) -> str:
        numeric = self._p20_numeric_value(value)
        if numeric == _P20_MISSING_SORT_VALUE:
            return 'N/A'
        return f'${numeric:,.0f}'

    def _p20_build_trading_volume_llm_export(self, rows: list[dict[str, Any]]) -> str:
        """Build a Markdown payload for external LLM analysis of Trading Volumes."""
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        source = str(getattr(self, '_p20_trading_volume_source', '') or 'Yahoo Finance').strip()
        as_of = str(getattr(self, '_p20_trading_volume_as_of', '') or '').strip()
        modifier_text = self._p20_filter_description(len(getattr(self, '_p20_trading_volume_all_rows', []) or []))
        lines = [
            '# Trading Volumes Export',
            '',
            '- Page: Trading Volumes',
            '- Panel: Trading Volumes',
            f'- Exported at: {exported_at}',
            f'- Data source: {source or "N/A"}',
            f'- Data as of: {as_of or "N/A"}',
            f'- Active modifier: {modifier_text}',
            f'- Rows exported: {len(rows)}',
            '',
            '## Trading Volumes Data',
            '',
            '| Rank | Ticker | Name | Sector | Market Cap ($) | 1D ADV ($) | 5D ADV ($) | 30D ADV ($) | YTD ADV ($) | 1Y ADV ($) |',
            '| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |',
        ]
        for row_index, row in enumerate(rows):
            lines.append(
                '| {rank} | {ticker} | {name} | {sector} | {market_cap} | {one_day_adv} | {five_day_adv} | {thirty_day_adv} | {ytd_adv} | {one_year_adv} |'.format(
                    rank=self._p20_row_rank(row, row_index),
                    ticker=self._p20_export_escape(str(row.get('ticker') or '').upper()),
                    name=self._p20_export_escape(row.get('name') or row.get('ticker') or ''),
                    sector=self._p20_export_escape(row.get('sector') or 'N/A'),
                    market_cap=self._p20_format_export_currency(row.get('market_cap')),
                    one_day_adv=self._p20_format_export_currency(row.get('one_day_dollar_volume')),
                    five_day_adv=self._p20_format_export_currency(row.get('five_day_avg_dollar_volume')),
                    thirty_day_adv=self._p20_format_export_currency(row.get('thirty_day_avg_dollar_volume')),
                    ytd_adv=self._p20_format_export_currency(row.get('ytd_avg_dollar_volume')),
                    one_year_adv=self._p20_format_export_currency(row.get('one_year_avg_dollar_volume')),
                )
            )
        return '\n'.join(lines).rstrip() + '\n'

    def _p20_export_trading_volume_for_llm(self) -> None:
        """Copy the loaded trading-volume panel data to the clipboard."""
        rows = [dict(row) for row in getattr(self, '_p20_trading_volume_rows', []) or [] if isinstance(row, dict)]
        if not rows:
            self.set_status_text(self.p20_status_lbl, 'Load trading volume before exporting data.', status='warning')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Trading Volumes export failed: no data loaded.', status='warning')
            return
        try:
            QApplication.clipboard().setText(self._p20_build_trading_volume_llm_export(rows))
        except Exception as exc:
            self.set_status_text(self.p20_status_lbl, f'Export failed: {exc}', status='negative')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Trading Volumes export failed: {exc}', status='negative')
            QMessageBox.warning(self, 'Export Failed', f'Unable to copy Trading Volumes data to the clipboard:\n{exc}')
            return
        self.set_status_text(self.p20_status_lbl, f'Copied {len(rows)} trading-volume rows to clipboard.', status='positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Trading Volumes data copied to clipboard: {len(rows)} rows.', status='positive')

    def _p20_export_tickers_for_llm(self) -> None:
        """Backward-compatible wrapper for the Trading Volumes LLM export action."""
        self._p20_export_trading_volume_for_llm()

    def _p20_render_trading_volume_rows(self, rows: list[dict[str, Any]]) -> None:
        self._p20_trading_volume_rows = [dict(row) for row in rows if isinstance(row, dict)]
        table = self.p20_trading_volume_table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._p20_trading_volume_rows))
        for row_index, row in enumerate(self._p20_trading_volume_rows):
            rank = self._p20_row_rank(row, row_index)
            values = (
                str(rank),
                str(row.get('ticker') or '').upper(),
                str(row.get('name') or ''),
                self._p20_format_compact_currency(row.get('market_cap')),
                self._p20_format_dollar_volume_m(row.get('one_day_dollar_volume')),
                self._p20_format_dollar_volume_m(row.get('five_day_avg_dollar_volume')),
                self._p20_format_dollar_volume_m(row.get('thirty_day_avg_dollar_volume')),
                self._p20_format_dollar_volume_m(row.get('ytd_avg_dollar_volume')),
                self._p20_format_dollar_volume_m(row.get('one_year_avg_dollar_volume')),
            )
            sort_values = (
                float(rank),
                None,
                None,
                self._p20_numeric_value(row.get('market_cap')),
                self._p20_numeric_value(row.get('one_day_dollar_volume')),
                self._p20_numeric_value(row.get('five_day_avg_dollar_volume')),
                self._p20_numeric_value(row.get('thirty_day_avg_dollar_volume')),
                self._p20_numeric_value(row.get('ytd_avg_dollar_volume')),
                self._p20_numeric_value(row.get('one_year_avg_dollar_volume')),
            )
            for col_index, value in enumerate(values):
                if col_index == 0 or col_index >= 3:
                    item = _P20NumericTableWidgetItem(value)
                    item.setData(_P20_NUMERIC_SORT_ROLE, sort_values[col_index])
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item = QTableWidgetItem(value)
                    if col_index == 1:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, col_index, item)
        table.setSortingEnabled(True)
        table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self._p20_render_dot_plot(self._p20_trading_volume_rows)

    def _p20_exclude_top_value(self) -> int:
        """Return the current top-stock exclusion count."""
        spin = getattr(self, 'p20_exclude_top_spin', None)
        if spin is not None:
            value = spin.value()
        else:
            value = getattr(self, '_p20_exclude_top_count', 0)
        try:
            count = int(value)
        except Exception:
            count = 0
        return max(0, min(100, count))

    def _p20_set_exclude_top_count(self, value: Any, *, render: bool = True) -> None:
        """Set the Trading Volumes top-stock exclusion count."""
        try:
            count = int(value)
        except Exception:
            count = 0
        count = max(0, min(100, count))
        self._p20_exclude_top_count = count
        spin = getattr(self, 'p20_exclude_top_spin', None)
        if spin is not None and spin.value() != count:
            blocker = spin.blockSignals(True)
            try:
                spin.setValue(count)
            finally:
                spin.blockSignals(blocker)
        if render:
            self._p20_filter_mode = _P20_FILTER_EXCLUDE if count > 0 else _P20_FILTER_DEFAULT
            self._p20_apply_trading_volume_filter()
            self._p20_save_session_snapshot()

    def _p20_on_exclude_top_changed(self, value: Any) -> None:
        """Apply the top-stock exclusion when the user edits the spinbox."""
        self._p20_set_exclude_top_count(value, render=True)

    def _p20_visible_trading_volume_rows(self) -> list[dict[str, Any]]:
        """Return displayed rows for the active Trading Volumes modifier."""
        source_rows = [dict(row) for row in getattr(self, '_p20_trading_volume_all_rows', []) or [] if isinstance(row, dict)]
        filter_mode = self._p20_normalize_filter_mode(getattr(self, '_p20_filter_mode', _P20_FILTER_DEFAULT))
        start_rank = 1
        end_rank = len(source_rows)
        if filter_mode == _P20_FILTER_EXCLUDE:
            start_rank = min(self._p20_exclude_top_value(), len(source_rows)) + 1
        elif filter_mode == _P20_FILTER_ROW_RANGE:
            start_rank, end_rank = self._p20_row_range_values()
        visible_rows: list[dict[str, Any]] = []
        for original_index, row in enumerate(source_rows, start=1):
            if original_index < start_rank or original_index > end_rank:
                continue
            visible_row = dict(row)
            visible_row['_p20_rank'] = original_index
            visible_rows.append(visible_row)
        return visible_rows

    def _p20_apply_trading_volume_filter(self) -> None:
        """Refresh the Trading Volumes table and dot plot from the filtered row set."""
        all_rows = [dict(row) for row in getattr(self, '_p20_trading_volume_all_rows', []) or [] if isinstance(row, dict)]
        visible_rows = self._p20_visible_trading_volume_rows()
        self._p20_render_trading_volume_rows(visible_rows)
        if all_rows:
            status = self._p20_trading_volume_status_text(len(visible_rows), len(all_rows), 'rows shown')
            self.set_status_text(self.p20_status_lbl, status, status='positive' if visible_rows else 'warning')

    def _p20_trading_volume_status_text(self, visible_count: int, total_count: int, suffix: str) -> str:
        filter_mode = self._p20_normalize_filter_mode(getattr(self, '_p20_filter_mode', _P20_FILTER_DEFAULT))
        if filter_mode == _P20_FILTER_EXCLUDE:
            excluded_count = min(self._p20_exclude_top_value(), total_count)
            if excluded_count:
                return f'{visible_count} {suffix}, {excluded_count} excluded'
        if filter_mode == _P20_FILTER_ROW_RANGE:
            start_rank, end_rank = self._p20_row_range_values()
            return f'{visible_count} {suffix}, rows {start_rank}-{end_rank}'
        return f'{total_count} {suffix}'

    def _p20_filter_description(self, total_count: int) -> str:
        filter_mode = self._p20_normalize_filter_mode(getattr(self, '_p20_filter_mode', _P20_FILTER_DEFAULT))
        if filter_mode == _P20_FILTER_EXCLUDE:
            excluded_count = min(self._p20_exclude_top_value(), total_count)
            return f'Exclude top {excluded_count}' if excluded_count else 'None'
        if filter_mode == _P20_FILTER_ROW_RANGE:
            start_rank, end_rank = self._p20_row_range_values()
            return f'Rows {start_rank}-{end_rank}'
        return 'None'

    def _p20_normalize_filter_mode(self, value: Any) -> str:
        mode = str(value or _P20_FILTER_DEFAULT).strip().lower()
        return mode if mode in _P20_FILTER_MODES else _P20_FILTER_DEFAULT

    def _p20_row_range_values(self) -> tuple[int, int]:
        start_spin = getattr(self, 'p20_row_range_start_spin', None)
        end_spin = getattr(self, 'p20_row_range_end_spin', None)
        start_value = start_spin.value() if start_spin is not None else getattr(self, '_p20_row_range_start', 1)
        end_value = end_spin.value() if end_spin is not None else getattr(self, '_p20_row_range_end', 100)
        try:
            start_rank = int(start_value)
        except Exception:
            start_rank = 1
        try:
            end_rank = int(end_value)
        except Exception:
            end_rank = 100
        start_rank = max(1, min(100, start_rank))
        end_rank = max(1, min(100, end_rank))
        if start_rank > end_rank:
            start_rank, end_rank = end_rank, start_rank
        return start_rank, end_rank

    def _p20_set_row_range_values(self, start_value: Any, end_value: Any) -> None:
        try:
            start_rank = int(start_value)
        except Exception:
            start_rank = 1
        try:
            end_rank = int(end_value)
        except Exception:
            end_rank = 100
        start_rank = max(1, min(100, start_rank))
        end_rank = max(1, min(100, end_rank))
        self._p20_row_range_start = start_rank
        self._p20_row_range_end = end_rank
        for spin, value in (
            (getattr(self, 'p20_row_range_start_spin', None), start_rank),
            (getattr(self, 'p20_row_range_end_spin', None), end_rank),
        ):
            if spin is None or spin.value() == value:
                continue
            blocker = spin.blockSignals(True)
            try:
                spin.setValue(value)
            finally:
                spin.blockSignals(blocker)

    def _p20_search_row_range(self) -> None:
        """Activate row-range search for the current Trading Volumes rows."""
        start_rank, end_rank = self._p20_row_range_values()
        self._p20_set_row_range_values(start_rank, end_rank)
        self._p20_filter_mode = _P20_FILTER_ROW_RANGE
        self._p20_apply_trading_volume_filter()
        self._p20_save_session_snapshot()

    def _p20_reset_trading_volume_filters(self) -> None:
        """Reset Trading Volumes modifiers without refetching data."""
        self._p20_filter_mode = _P20_FILTER_DEFAULT
        self._p20_set_exclude_top_count(0, render=False)
        self._p20_set_row_range_values(1, 100)
        self._p20_apply_trading_volume_filter()
        self._p20_save_session_snapshot()

    def _p20_row_rank(self, row: dict[str, Any], row_index: int) -> int:
        try:
            rank = int(row.get('_p20_rank'))
        except Exception:
            rank = row_index + 1
        return max(1, rank)

    def _p20_set_dot_metric(self, metric_key: str, checked: Any = True) -> None:
        """Switch the Trading Volumes dot plot between supported volume metrics."""
        if checked is False or metric_key not in _P20_DOT_METRICS:
            return
        self._p20_dot_metric = metric_key
        if hasattr(self, 'update_checked_button_state') and hasattr(self, 'p20_dot_metric_buttons'):
            self.update_checked_button_state(self.p20_dot_metric_buttons, self._p20_dot_metric)
        self._p20_render_dot_plot(getattr(self, '_p20_trading_volume_rows', []) or [])

    def _p20_render_dot_plot(self, rows: list[dict[str, Any]]) -> None:
        """Render the right-side Trading volume dot plot."""
        plot = getattr(self, 'p20_dot_plot', None)
        if plot is None:
            return
        metric_key = str(getattr(self, '_p20_dot_metric', '1d') or '1d').lower()
        if metric_key not in _P20_DOT_METRICS:
            metric_key = '1d'
            self._p20_dot_metric = metric_key
        _button_label, axis_label, row_key = _P20_DOT_METRICS[metric_key]
        plot.clear()
        self._p20_dot_label_items = []
        plot.setLabel('left', axis_label)
        plot.setLabel('bottom', 'Market Cap')
        points: list[tuple[float, float, str]] = []
        for row_index, row in enumerate((rows or [])[:100]):
            if not isinstance(row, dict):
                continue
            rank = row_index + 1
            ticker = str(row.get('ticker') or '').upper().strip() or str(rank)
            market_cap = self._p20_numeric_value(row.get('market_cap'))
            volume_value = self._p20_numeric_value(row.get(row_key))
            if market_cap == _P20_MISSING_SORT_VALUE or volume_value == _P20_MISSING_SORT_VALUE:
                continue
            points.append((market_cap, volume_value / 1_000_000, ticker))
        self._p20_dot_plot_points = list(points)
        if not points:
            empty_text = f'No rows with numeric Market Cap and {axis_label} values to plot.'
            if not rows:
                empty_text = 'Load Trading Volumes to plot tickers.'
            self.p20_dot_empty_lbl.setText(empty_text)
            self.p20_dot_empty_lbl.setVisible(True)
            plot.setXRange(0, 1, padding=0)
            plot.setYRange(0, 1, padding=0)
            return
        self.p20_dot_empty_lbl.setVisible(False)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        scatter = pg.ScatterPlotItem(
            x=xs,
            y=ys,
            size=7,
            brush=self.theme_brush('accent') if hasattr(self, 'theme_brush') else pg.mkBrush('#42a5f5'),
            pen=self.theme_pen('chart_reference', width=0.6) if hasattr(self, 'theme_pen') else pg.mkPen('#9aa4b2', width=0.6),
            data=[point[2] for point in points],
        )
        plot.addItem(scatter)
        label_color = self.theme_color('text_primary') if hasattr(self, 'theme_color') else '#e5e7eb'
        for x_value, y_value, ticker in points:
            label = pg.TextItem(text=ticker, color=label_color, anchor=(0.5, 1.15))
            label.setPos(x_value, y_value)
            plot.addItem(label)
            self._p20_dot_label_items.append(label)
        max_x = max(xs) if xs else 1
        max_y = max(ys) if ys else 1
        plot.setXRange(0, max_x * 1.08 if max_x > 0 else 1, padding=0)
        plot.setYRange(0, max_y * 1.18 if max_y > 0 else 1, padding=0)

    def _p20_numeric_value(self, value: Any) -> float:
        try:
            numeric = float(value)
        except Exception:
            return _P20_MISSING_SORT_VALUE
        return numeric if math.isfinite(numeric) else _P20_MISSING_SORT_VALUE

    def _p20_format_compact_currency(self, value: Any) -> str:
        numeric = self._p20_numeric_value(value)
        if numeric == _P20_MISSING_SORT_VALUE:
            return 'N/A'
        sign = '-' if numeric < 0 else ''
        numeric = abs(numeric)
        for divisor, suffix in ((1_000_000_000_000, 'T'), (1_000_000_000, 'B'), (1_000_000, 'M')):
            if numeric >= divisor:
                return f'{sign}${numeric / divisor:,.1f}{suffix}'
        return f'{sign}${numeric:,.0f}'

    def _p20_format_dollar_volume_m(self, value: Any) -> str:
        numeric = self._p20_numeric_value(value)
        if numeric == _P20_MISSING_SORT_VALUE:
            return 'N/A'
        return f'{numeric / 1_000_000:,.0f}'
