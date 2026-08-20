from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.data_service.results import market_data_meta
from budget_terminal_app.mixins.options_chain_presenters import (
    build_option_summary_rows,
    format_top_volume_expiration,
    prepare_top_volume_records,
)
from budget_terminal_app.services.options_data import OPTIONS_MARKET_TIMEZONE, is_options_expiry_closed
from budget_terminal_app.widgets.batched_render import run_batched
from budget_terminal_app.widgets.table_render import render_table_rows


P28_TIMEFRAME_OPTIONS = (
    ('1 Minute', '7d', '1m'),
    ('5 Minutes', '60d', '5m'),
    ('15 Minutes', '60d', '15m'),
    ('1 Hour', '730d', '1h'),
    ('4 Hours', '730d', '4h'),
    ('1 Day', '5y', '1d'),
    ('1 Week', '5y', '1wk'),
    ('1 Month', '5y', '1mo'),
)
P28_TYPE_FILTERS = (
    ('calls', 'Calls', 'Call'),
    ('puts', 'Puts', 'Put'),
)
P28_EXPIRATION_SCOPE_FILTERS = (
    ('all', 'All', None, None),
)
P28_TOP_VOLUME_COLUMNS = ('Ticker', 'Type', 'Strike', 'Exp', 'Price', 'Vol')
P28_GRID_COLUMNS = 3
P28_PROXY_SOURCE_NOTE = (
    'Call and put paths are separate options-implied scenarios built from full-chain bid/ask midpoints, break-even prices; the combined path '
    'is their confidence-and-coverage-weighted center. All paths use '
    'liquidity quality, moneyness, and implied-volatility plausibility checks. They are not true forecasts: volume and open interest '
    'do not reveal whether trades were bought or sold, and activity can reflect spreads, covered calls, hedges, or closing trades.'
)
P28_PROXY_EXPIRATION_STEP = 5
P28_PROJECTION_DOT_SIZE = 9.0
P28_PROXY_MAX_SPREAD_PCT = 0.60
P28_PROXY_MONEYNESS_SOFT_LIMIT = 0.35
P28_PROXY_MIN_MONEYNESS_WEIGHT = 0.10
P28_PROXY_IV_RANGE_MULTIPLIER = 1.5


class ChartsOptionsTopVolumeMixin:
    """Standalone chart plus all-expiration top-volume options page."""

    def init_page28(self) -> None:
        """Build the Projections page."""
        state = getattr(self, 'charts_options_top_volume_page_state', load_charts_options_top_volume_page_settings())
        self.p28_symbol = str(state.get('symbol', 'SPY') or 'SPY').upper().strip()
        self.p28_timeframe_label = str(state.get('timeframe_label', '1 Day') or '1 Day').strip()
        self.p28_type_filter = self._p28_normalize_type_filter(state.get('type_filter', 'calls'))
        self.p28_expiration_scope = 'all'
        self.p28_splitter_sizes = list(state.get('splitter_sizes', [5, 3]))
        self._p28_timeframe_map = {label: (period, interval) for label, period, interval in P28_TIMEFRAME_OPTIONS}
        if self.p28_timeframe_label not in self._p28_timeframe_map:
            self.p28_timeframe_label = '1 Day'
        self._p28_timeframe_group = QButtonGroup(self)
        self._p28_timeframe_group.setExclusive(True)
        self._p28_type_group = QButtonGroup(self)
        self._p28_type_group.setExclusive(True)
        self._p28_timeframe_buttons = {}
        self._p28_type_buttons = {}
        self._p28_request_seq = 0
        self._p28_latest_request_id = 0
        self._p28_initial_load_requested = False
        self._p28_has_completed_view = False
        self._p28_last_applied_request_id = 0
        self._p28_pending_completed_view = None
        self._p28_pending_load_error = None
        self._p28_option_render_generation = 0
        self._p28_option_render_pending = False
        self._p28_bucket_config = ()
        self._p28_sections = {}
        self._p28_payload = self._p28_empty_payload(self.p28_symbol)
        self._p28_chart_rows = []
        self._p28_chart_df = pd.DataFrame()
        self._p28_chart_interval = '1d'
        self._p28_candle_item = None
        self._p28_volume_item = None
        self._p28_projection_marker_items = []
        self._p28_projection_path_items = []
        self._p28_projection_value_labels = {}
        self._p28_projection_meta_labels = {}

        layout = QVBoxLayout(self.page28)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel('<b>Projections</b>')
        self.set_theme_role(title, 'page_title')
        self.p28_symbol_input = QLineEdit(self.p28_symbol)
        self.p28_symbol_input.setPlaceholderText('Ticker')
        self.p28_symbol_input.setFixedWidth(110)
        self.p28_symbol_input.returnPressed.connect(lambda: self._p28_load(force_refresh=True))
        self.p28_load_btn = QPushButton('Load')
        self.set_theme_variant(self.p28_load_btn, 'accent')
        self.p28_load_btn.clicked.connect(lambda: self._p28_load(force_refresh=True))
        self.p28_export_btn = QPushButton('Export Top Volume')
        self.set_theme_variant(self.p28_export_btn, 'accent')
        self.p28_export_btn.clicked.connect(self._p28_export_top_volume)
        toolbar.addWidget(title)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.p28_symbol_input)
        toolbar.addWidget(self.p28_load_btn)
        toolbar.addWidget(self.p28_export_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        control_row = QHBoxLayout()
        timeframe_label = QLabel('Timeframe')
        self.set_theme_role(timeframe_label, 'muted')
        control_row.addWidget(timeframe_label)
        for label, _period, _interval in P28_TIMEFRAME_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(partial(self._p28_set_timeframe, label))
            self._p28_timeframe_group.addButton(btn)
            self._p28_timeframe_buttons[label] = btn
            control_row.addWidget(btn)
        control_row.addSpacing(16)
        type_label = QLabel('Table rows')
        self.set_theme_role(type_label, 'muted')
        control_row.addWidget(type_label)
        for mode_key, mode_label, _option_type in P28_TYPE_FILTERS:
            btn = QPushButton(mode_label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(partial(self._p28_set_type_filter, mode_key))
            self._p28_type_group.addButton(btn)
            self._p28_type_buttons[mode_key] = btn
            control_row.addWidget(btn)
        control_row.addSpacing(16)
        self.p28_projection_range_label = QLabel('Projection range: All expirations')
        self.set_theme_role(self.p28_projection_range_label, 'muted')
        control_row.addWidget(self.p28_projection_range_label)
        control_row.addStretch()
        self.p28_status_label = QLabel('Enter a ticker and load all-expiration top-volume options.')
        self.p28_status_label.setMinimumWidth(260)
        self.p28_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p28_status_label, 'status_muted')
        control_row.addWidget(self.p28_status_label)
        layout.addLayout(control_row)

        self.p28_projection_panel = QFrame()
        self.set_theme_role(self.p28_projection_panel, 'panel')
        projection_layout = QHBoxLayout(self.p28_projection_panel)
        projection_layout.setContentsMargins(10, 8, 10, 8)
        projection_layout.setSpacing(14)
        for key, title in (
            ('close', 'Current Close'),
            ('calls', 'Nearest Call Projection'),
            ('puts', 'Nearest Put Projection'),
            ('combined', 'Nearest Combined Projection'),
            ('confidence', 'Data Confidence / Coverage'),
        ):
            metric_widget = QWidget()
            metric_layout = QVBoxLayout(metric_widget)
            metric_layout.setContentsMargins(0, 0, 0, 0)
            metric_layout.setSpacing(2)
            title_label = QLabel(title)
            self.set_theme_role(title_label, 'muted')
            value_label = QLabel('--')
            value_label.setMinimumWidth(130)
            meta_label = QLabel('--')
            meta_label.setWordWrap(True)
            self.set_theme_role(meta_label, 'muted')
            metric_layout.addWidget(title_label)
            metric_layout.addWidget(value_label)
            metric_layout.addWidget(meta_label)
            projection_layout.addWidget(metric_widget, 1)
            self._p28_projection_value_labels[key] = value_label
            self._p28_projection_meta_labels[key] = meta_label
        layout.addWidget(self.p28_projection_panel)

        self.p28_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p28_body_splitter.splitterMoved.connect(self._p28_on_splitter_moved)
        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(6)
        chart_header = QHBoxLayout()
        self.p28_symbol_label = QLabel(self.p28_symbol)
        self.p28_symbol_label.setMinimumWidth(90)
        self.p28_price_label = QLabel('--')
        self.p28_change_label = QLabel('--')
        self.p28_call_legend = QLabel('● Calls')
        self.p28_put_legend = QLabel('● Puts')
        self.p28_combined_legend = QLabel('● Combined')
        chart_header.addWidget(self.p28_symbol_label)
        chart_header.addSpacing(10)
        chart_header.addWidget(self.p28_price_label)
        chart_header.addWidget(self.p28_change_label)
        chart_header.addStretch()
        chart_header.addWidget(self.p28_call_legend)
        chart_header.addSpacing(10)
        chart_header.addWidget(self.p28_put_legend)
        chart_header.addSpacing(10)
        chart_header.addWidget(self.p28_combined_legend)
        chart_layout.addLayout(chart_header)
        self.p28_chart_axis = DateAxisItem(orientation='bottom')
        self.p28_main_plot = pg.PlotWidget(axisItems={'bottom': self.p28_chart_axis})
        self.p28_main_plot.showGrid(x=True, y=True, alpha=0.15)
        self.p28_main_plot.getPlotItem().setMenuEnabled(False)
        self.p28_main_plot.getPlotItem().hideAxis('left')
        self.p28_main_plot.getPlotItem().showAxis('right')
        self.p28_volume_axis = DateAxisItem(orientation='bottom')
        self.p28_volume_plot = pg.PlotWidget(axisItems={'bottom': self.p28_volume_axis})
        self.p28_volume_plot.showGrid(x=True, y=False, alpha=0.1)
        self.p28_volume_plot.getPlotItem().setMenuEnabled(False)
        self.p28_volume_plot.getPlotItem().hideAxis('left')
        self.p28_volume_plot.getPlotItem().showAxis('right')
        self.p28_volume_plot.setMaximumHeight(155)
        self.p28_volume_plot.setXLink(self.p28_main_plot)
        chart_layout.addWidget(self.p28_main_plot, 5)
        chart_layout.addWidget(self.p28_volume_plot, 1)
        self.p28_body_splitter.addWidget(chart_widget)

        options_widget = QWidget()
        options_layout = QVBoxLayout(options_widget)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(6)
        options_title = QLabel('Options Top Volume')
        self.set_theme_role(options_title, 'section_title')
        self.p28_options_meta_label = QLabel('No options data loaded.')
        self.set_theme_role(self.p28_options_meta_label, 'muted')
        options_layout.addWidget(options_title)
        options_layout.addWidget(self.p28_options_meta_label)
        self.p28_options_scroll = QScrollArea()
        self.p28_options_scroll.setWidgetResizable(True)
        self.p28_options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p28_options_host = QWidget()
        self.p28_options_grid = QGridLayout(self.p28_options_host)
        self.p28_options_grid.setContentsMargins(0, 0, 0, 0)
        self.p28_options_grid.setHorizontalSpacing(10)
        self.p28_options_grid.setVerticalSpacing(10)
        self.p28_options_scroll.setWidget(self.p28_options_host)
        options_layout.addWidget(self.p28_options_scroll, 1)
        self.p28_body_splitter.addWidget(options_widget)
        self.p28_body_splitter.setStretchFactor(0, 5)
        self.p28_body_splitter.setStretchFactor(1, 3)
        layout.addWidget(self.p28_body_splitter, 1)

        self._p28_update_timeframe_buttons()
        self._p28_update_type_buttons()
        self._p28_apply_splitter_sizes()
        self._p28_update_projection_strip({}, None)
        self._apply_charts_options_top_volume_theme()

    def _p28_on_show(self) -> None:
        """Refresh lightweight state when the page is shown."""
        self._p28_update_timeframe_buttons()
        self._p28_update_type_buttons()
        self._p28_apply_splitter_sizes()
        if not self._p28_is_render_surface_visible():
            return
        applied_pending_view = False
        pending_view = getattr(self, '_p28_pending_completed_view', None)
        if isinstance(pending_view, dict):
            self._p28_pending_completed_view = None
            if int(pending_view.get('request_id', 0) or 0) == getattr(self, '_p28_latest_request_id', 0):
                self._p28_apply_completed_view(**pending_view)
                applied_pending_view = True
        pending_error = getattr(self, '_p28_pending_load_error', None)
        if not applied_pending_view and isinstance(pending_error, tuple) and len(pending_error) == 3:
            self._p28_pending_load_error = None
            self._p28_apply_load_error(*pending_error)
        if not applied_pending_view and getattr(self, '_p28_option_render_pending', False):
            payload = getattr(self, '_p28_payload', {})
            if isinstance(payload, dict) and getattr(self, '_p28_has_completed_view', False):
                records = payload.get('records', {}) if isinstance(payload.get('records'), dict) else {}
                expirations = payload.get('expirations', {}) if isinstance(payload.get('expirations'), dict) else {}
                self._p28_render_option_tables(str(payload.get('ticker') or ''), records, expirations)
        self._p28_sync_status_to_status_bar()
        if not getattr(self, '_p28_initial_load_requested', False):
            self._p28_load(force_refresh=False)

    def _p28_is_render_surface_visible(self) -> bool:
        """Return whether Projections UI work may be applied now."""
        page = getattr(self, 'page28', None)
        page_check = getattr(self, '_is_current_page', None)
        if page is None or not callable(page_check):
            return True
        try:
            return bool(page_check(page))
        except (AttributeError, RuntimeError):
            return False

    def _p28_empty_payload(self, ticker: str = '') -> dict[str, Any]:
        """Return an empty page payload."""
        return {
            'ticker': str(ticker or '').upper().strip(),
            'type_filter': self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls')),
            'expiration_scope': 'all',
            'bucket_order': [],
            'records': {},
            'records_by_filter': {},
            'projection_records': {},
            'projections': {},
            'weekly_points': {'calls': [], 'puts': [], 'combined': []},
            'expirations': {},
            'current_close': None,
        }

    def _p28_input_symbol(self) -> str:
        """Return the page input ticker."""
        if hasattr(self, 'p28_symbol_input'):
            return str(self.p28_symbol_input.text() or '').upper().strip()
        return str(getattr(self, 'p28_symbol', '') or '').upper().strip()

    def _p28_current_timeframe(self) -> tuple[str, str]:
        """Return the selected period and interval."""
        return self._p28_timeframe_map.get(self.p28_timeframe_label, ('5y', '1d'))

    def _p28_normalize_type_filter(self, mode: Any) -> str:
        """Normalize an option type filter key."""
        clean = str(mode or 'calls').strip().lower()
        return clean if clean in {'calls', 'puts'} else 'calls'

    def _p28_normalize_expiration_scope(self, scope: Any) -> str:
        """Normalize a projection-period / expiration-scope filter key."""
        return 'all'

    def _p28_expiration_scope_label(self, scope: Any = None) -> str:
        """Return a display label for the expiration-scope filter."""
        selected = self._p28_normalize_expiration_scope(scope or getattr(self, 'p28_expiration_scope', 'all'))
        for scope_key, scope_label, _min_days, _max_days in P28_EXPIRATION_SCOPE_FILTERS:
            if scope_key == selected:
                return scope_label
        return 'All'

    def _p28_option_type(self) -> str | None:
        """Return the option type used by the presenter."""
        selected = self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls'))
        for mode_key, _mode_label, option_type in P28_TYPE_FILTERS:
            if mode_key == selected:
                return option_type
        return 'Call'

    def _p28_type_label(self, mode: Any = None) -> str:
        """Return a display label for one type filter."""
        selected = self._p28_normalize_type_filter(mode or getattr(self, 'p28_type_filter', 'calls'))
        for mode_key, mode_label, _option_type in P28_TYPE_FILTERS:
            if mode_key == selected:
                return mode_label
        return 'Calls'

    def _p28_save_state(self) -> None:
        """Persist page-local controls."""
        self.charts_options_top_volume_page_state = save_charts_options_top_volume_page_settings({
            'symbol': getattr(self, 'p28_symbol', 'SPY'),
            'timeframe_label': getattr(self, 'p28_timeframe_label', '1 Day'),
            'type_filter': getattr(self, 'p28_type_filter', 'calls'),
            'expiration_scope': 'all',
            'splitter_sizes': list(self.p28_body_splitter.sizes()) if hasattr(self, 'p28_body_splitter') else getattr(self, 'p28_splitter_sizes', [5, 3]),
        })

    def _p28_update_timeframe_buttons(self) -> None:
        """Refresh selected timeframe button styles."""
        for label, button in getattr(self, '_p28_timeframe_buttons', {}).items():
            active = label == getattr(self, 'p28_timeframe_label', '1 Day')
            button.setChecked(active)
            self.set_theme_variant(button, 'accent' if active else None)

    def _p28_update_type_buttons(self) -> None:
        """Refresh selected type filter button styles."""
        selected = self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls'))
        self.p28_type_filter = selected
        for mode_key, button in getattr(self, '_p28_type_buttons', {}).items():
            active = mode_key == selected
            button.setChecked(active)
            self.set_theme_variant(button, 'accent' if active else None)

    def _p28_update_expiration_scope_buttons(self) -> None:
        """Keep legacy callers pinned to the all-expirations contract."""
        self.p28_expiration_scope = 'all'

    def _p28_update_show_dots_button(self) -> None:
        """Legacy no-op; weekly projection dots are always visible."""

    def _p28_set_timeframe(self, label: Any, *_: Any) -> None:
        """Select a chart timeframe."""
        clean = str(label or '').strip()
        if clean not in getattr(self, '_p28_timeframe_map', {}):
            return
        if clean == getattr(self, 'p28_timeframe_label', ''):
            self._p28_update_timeframe_buttons()
            return
        self.p28_timeframe_label = clean
        self._p28_update_timeframe_buttons()
        self._p28_save_state()
        if getattr(self, '_p28_chart_rows', []):
            self._p28_load(force_refresh=False)

    def _p28_set_type_filter(self, mode: Any, *_: Any) -> None:
        """Select calls or puts for the ranked option tables."""
        selected = self._p28_normalize_type_filter(mode)
        if selected == getattr(self, 'p28_type_filter', 'calls'):
            self._p28_update_type_buttons()
            return
        self.p28_type_filter = selected
        self._p28_update_type_buttons()
        self._p28_save_state()
        if self._p28_apply_loaded_type_filter():
            return
        if self._p28_loaded_row_count() > 0:
            self._p28_load(force_refresh=False)

    def _p28_set_expiration_scope(self, scope: Any, *_: Any) -> None:
        """Legacy entry point that now always selects every expiration."""
        self.p28_expiration_scope = 'all'
        self._p28_save_state()

    def _p28_set_show_dots(self, enabled: Any, *_: Any) -> None:
        """Legacy no-op; weekly projection dots cannot be disabled."""

    def _p28_on_splitter_moved(self, *_: Any) -> None:
        """Persist splitter movement."""
        self.p28_splitter_sizes = list(self.p28_body_splitter.sizes())
        self._p28_save_state()

    def _p28_apply_splitter_sizes(self) -> None:
        """Apply persisted splitter sizes."""
        if not hasattr(self, 'p28_body_splitter'):
            return
        sizes = list(getattr(self, 'p28_splitter_sizes', []) or [])
        if len(sizes) == 2 and all(int(value or 0) > 0 for value in sizes):
            self.p28_body_splitter.setSizes([int(value) for value in sizes])

    def _p28_set_status(self, text: Any, status: Any = 'muted') -> None:
        """Set the page status label."""
        if hasattr(self, 'p28_status_label'):
            self.set_status_text(self.p28_status_label, text, status=str(status))
        if self._p28_is_render_surface_visible() and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _p28_sync_status_to_status_bar(self) -> None:
        """Mirror page status into the shared status bar."""
        if hasattr(self, 'p28_status_label') and hasattr(self, 'status_bar'):
            self.set_status_text(
                self.status_bar,
                self.p28_status_label.text(),
                status=str(self.p28_status_label.property('bt_status') or 'muted'),
            )

    def _p28_set_loading(self, loading: bool) -> None:
        """Toggle page controls while a request is active."""
        if hasattr(self, 'p28_load_btn'):
            self.p28_load_btn.setEnabled(not loading)
            self.p28_load_btn.setText('Loading...' if loading else 'Load')
        if hasattr(self, 'p28_export_btn'):
            self.p28_export_btn.setEnabled(not loading)

    def _p28_executor(self) -> Any:
        """Return the page-local executor."""
        executor = getattr(self, '_p28_fetch_executor', None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=2)
            self._p28_fetch_executor = executor
        return executor

    def _p28_load(self, *, force_refresh: bool = False) -> None:
        """Fetch chart and all-expiration top-volume options data."""
        symbol = self._p28_input_symbol()
        if not symbol:
            self._p28_set_status('Enter a ticker before loading options top volume.', 'warning')
            return
        self._p28_initial_load_requested = True
        self.p28_symbol_input.setText(symbol)
        period, interval = self._p28_current_timeframe()
        self._p28_request_seq += 1
        request_id = self._p28_request_seq
        self._p28_latest_request_id = request_id
        self._p28_pending_completed_view = None
        self._p28_pending_load_error = None
        self._p28_save_state()
        self._p28_set_loading(True)
        if getattr(self, '_p28_has_completed_view', False):
            self._p28_set_status(f'Refreshing chart and all expirations for {symbol}; showing previous result...', 'warning')
        else:
            self.p28_symbol = symbol
            self._p28_set_status(f'Loading chart and all expirations for {symbol}...', 'warning')
            self.p28_options_meta_label.setText('Loading available expirations...')

        def _run() -> None:
            """Fetch the combined payload away from the UI thread."""
            try:
                chart_error = ''
                chart_payload = self._get_chart_data_service().fetch_base_frame_payload(
                    symbol,
                    period=period,
                    interval=interval,
                    force_refresh=force_refresh,
                )
                chart_df = chart_payload.get('df') if isinstance(chart_payload, dict) else pd.DataFrame()
                if chart_df is None or getattr(chart_df, 'empty', True):
                    chart_df = pd.DataFrame()
                    chart_meta = market_data_meta(chart_payload)
                    chart_error = str(chart_meta.get('failure_reason') or f'No chart data returned for {symbol}.')
                options_service = self._get_options_data_service()
                expiries_payload = options_service.fetch_expiries_payload(symbol)
                if hasattr(self, '_record_data_health_payload'):
                    self._record_data_health_payload('Options expiries', expiries_payload, symbols=[symbol])
                expiries = expiries_payload.get('expiries') if isinstance(expiries_payload, dict) else []
                bucket_config = self._p28_build_bucket_config(expiries)
                bucket_records = {bucket_key: [] for bucket_key, _label, _days_out in bucket_config}
                bucket_records_by_filter = {
                    'calls': {bucket_key: [] for bucket_key, _label, _days_out in bucket_config},
                    'puts': {bucket_key: [] for bucket_key, _label, _days_out in bucket_config},
                }
                bucket_projection_records = {bucket_key: [] for bucket_key, _label, _days_out in bucket_config}
                bucket_expirations = {bucket_key: bucket_key for bucket_key, _label, _days_out in bucket_config}
                selected_filter = self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls'))
                for bucket_key, _bucket_label, _days_out in bucket_config:
                    try:
                        chain_payload = options_service.fetch_chain_payload(symbol, bucket_key)
                        if hasattr(self, '_record_data_health_payload'):
                            self._record_data_health_payload('Options chain', chain_payload, symbols=[symbol])
                        chain_df = chain_payload.get('chain') if isinstance(chain_payload, dict) else None
                        bucket_records_by_filter['calls'][bucket_key] = prepare_top_volume_records(
                            chain_df,
                            ticker=symbol,
                            expiry=bucket_key,
                            option_type='Call',
                            pd_module=pd,
                        )
                        bucket_records_by_filter['puts'][bucket_key] = prepare_top_volume_records(
                            chain_df,
                            ticker=symbol,
                            expiry=bucket_key,
                            option_type='Put',
                            pd_module=pd,
                        )
                        bucket_projection_records[bucket_key] = self._p28_prepare_projection_records(
                            chain_df,
                            ticker=symbol,
                            expiry=bucket_key,
                        )
                        bucket_records[bucket_key] = bucket_records_by_filter.get(selected_filter, bucket_records_by_filter['calls']).get(bucket_key, [])
                    except Exception as exc:
                        logger.warning('Charts + Options top-volume load failed for %s %s: %s', symbol, bucket_key, exc)
                if request_id != getattr(self, '_p28_latest_request_id', 0):
                    return
                self._invoke_main.emit(
                    lambda rid=request_id, ticker=symbol, chart=chart_df, chart_msg=chart_error, chart_interval=interval, config=bucket_config, records=bucket_records, records_by_filter=bucket_records_by_filter, projection_records=bucket_projection_records, expirations=bucket_expirations: self._p28_update_view(
                        rid,
                        ticker,
                        chart,
                        chart_msg,
                        chart_interval,
                        config,
                        records,
                        records_by_filter,
                        projection_records,
                        expirations,
                    )
                )
            except Exception as exc:
                logger.exception('Projections load failed for %s.', symbol)
                if request_id != getattr(self, '_p28_latest_request_id', 0):
                    return
                self._invoke_main.emit(lambda rid=request_id, ticker=symbol, message=str(exc): self._p28_handle_load_error(rid, ticker, message))

        self._p28_executor().submit(_run)

    def _p28_build_bucket_config(self, expiries: Any) -> tuple[tuple[str, str, int], ...]:
        """Convert live expirations into grid metadata."""
        parsed = []
        seen = set()
        today = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()
        for expiry in list(expiries or []):
            expiry_text = str(expiry or '').strip()
            if not expiry_text or expiry_text in seen or is_options_expiry_closed(expiry_text):
                continue
            try:
                expiry_date = datetime.date.fromisoformat(expiry_text)
            except ValueError:
                continue
            days_out = max((expiry_date - today).days, 0)
            seen.add(expiry_text)
            parsed.append((expiry_text, expiry_date, days_out))
        parsed.sort(key=lambda item: item[1])
        return tuple(
            (expiry_text, expiry_text, days_out)
            for expiry_text, _expiry_date, days_out in parsed
        )

    @staticmethod
    def _p28_has_option_rows(bucket_records_by_filter: Any) -> bool:
        """Return whether any expiration returned top-volume rows for either option type."""
        if not isinstance(bucket_records_by_filter, dict):
            return False
        return any(
            any(list(rows or []) for rows in buckets.values())
            for buckets in bucket_records_by_filter.values()
            if isinstance(buckets, dict)
        )

    def _p28_update_view(
        self,
        request_id: int,
        ticker: str,
        chart_df: Any,
        chart_error: str,
        interval: str,
        bucket_config: tuple[tuple[str, str, int], ...],
        bucket_records: dict[str, list[dict[str, Any]]],
        bucket_records_by_filter: dict[str, dict[str, list[dict[str, Any]]]],
        bucket_projection_records: dict[str, list[dict[str, Any]]],
        bucket_expirations: dict[str, str],
    ) -> None:
        """Accept a completed combined payload and render it only while visible."""
        if request_id != getattr(self, '_p28_latest_request_id', 0):
            return
        if not isinstance(chart_df, pd.DataFrame):
            chart_df = pd.DataFrame()
        if chart_df.empty:
            chart_error = str(chart_error or f'No chart data returned for {ticker}.')
            if not self._p28_has_option_rows(bucket_records_by_filter):
                self._p28_handle_load_error(request_id, ticker, chart_error)
                return
        self._p28_set_loading(False)
        completed_view = {
            'request_id': request_id,
            'ticker': ticker,
            'chart_df': chart_df,
            'chart_error': chart_error,
            'interval': interval,
            'bucket_config': bucket_config,
            'bucket_records': bucket_records,
            'bucket_records_by_filter': bucket_records_by_filter,
            'bucket_projection_records': bucket_projection_records,
            'bucket_expirations': bucket_expirations,
        }
        self._p28_pending_load_error = None
        if not self._p28_is_render_surface_visible():
            self._p28_pending_completed_view = completed_view
            return
        self._p28_pending_completed_view = None
        self._p28_apply_completed_view(**completed_view)

    def _p28_apply_completed_view(
        self,
        request_id: int,
        ticker: str,
        chart_df: Any,
        chart_error: str,
        interval: str,
        bucket_config: tuple[tuple[str, str, int], ...],
        bucket_records: dict[str, list[dict[str, Any]]],
        bucket_records_by_filter: dict[str, dict[str, list[dict[str, Any]]]],
        bucket_projection_records: dict[str, list[dict[str, Any]]],
        bucket_expirations: dict[str, str],
    ) -> None:
        """Apply one latest combined result to the visible Projections panel."""
        if request_id != getattr(self, '_p28_latest_request_id', 0):
            return
        if request_id == getattr(self, '_p28_last_applied_request_id', 0):
            return
        self._p28_set_loading(False)
        self.p28_symbol = ticker
        self.p28_symbol_label.setText(ticker)
        bucket_order = [bucket_key for bucket_key, _label, _days_out in bucket_config]
        self._p28_payload = {
            'ticker': ticker,
            'type_filter': self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls')),
            'expiration_scope': 'all',
            'bucket_order': bucket_order,
            'records': bucket_records,
            'records_by_filter': bucket_records_by_filter,
            'projection_records': bucket_projection_records,
            'projections': {},
            'weekly_points': {'calls': [], 'puts': [], 'combined': []},
            'expirations': bucket_expirations,
            'current_close': None,
        }
        self._p28_render_chart(chart_df, interval)
        current_close = self._p28_latest_chart_close()
        projections = self._p28_build_projection_summaries(
            bucket_config,
            bucket_projection_records,
            bucket_expirations,
            current_close,
        )
        self._p28_payload['current_close'] = current_close
        self._p28_payload['projections'] = projections
        self._p28_payload['weekly_points'] = self._p28_build_weekly_projection_points(projections, current_close)
        self._p28_apply_proxy_axis_dates()
        self._p28_update_projection_strip(projections, current_close)
        self._p28_apply_chart_ranges()
        self._p28_render_projection_markers()
        self._p28_set_bucket_config(bucket_config)
        self._p28_render_option_tables(ticker, bucket_records, bucket_expirations)
        self._p28_has_completed_view = True
        self._p28_last_applied_request_id = request_id
        self._p28_save_state()
        row_total = self._p28_loaded_row_count()
        expiry_count = len(bucket_config)
        populated_count = sum(1 for rows in bucket_records.values() if rows)
        self.p28_options_meta_label.setText(f'{row_total} rows across {expiry_count} expirations | {self._p28_type_label()} | {self._p28_expiration_scope_label()}')
        if expiry_count <= 0:
            self._p28_set_status(f'No listed options expirations were available for {ticker}.', 'warning')
            return
        if row_total <= 0:
            self._p28_set_status(f'No top-volume options rows were available for {ticker}.', 'warning')
            return
        status = f'Updated {ticker}: {row_total} rows across {expiry_count} expirations'
        if chart_error:
            status += f' | chart unavailable: {chart_error}'
        elif populated_count < expiry_count:
            status += f' | {expiry_count - populated_count} expirations returned no rows'
        self._p28_set_status(status, 'warning' if chart_error or populated_count < expiry_count else 'positive')

    def _p28_handle_load_error(self, request_id: int, ticker: str, message: str) -> None:
        """Accept a load failure and defer its UI work while hidden."""
        if request_id != getattr(self, '_p28_latest_request_id', 0):
            return
        self._p28_set_loading(False)
        self._p28_pending_completed_view = None
        if not self._p28_is_render_surface_visible():
            self._p28_pending_load_error = (request_id, ticker, message)
            return
        self._p28_pending_load_error = None
        self._p28_apply_load_error(request_id, ticker, message)

    def _p28_apply_load_error(self, request_id: int, ticker: str, message: str) -> None:
        """Apply one latest load failure to the visible page."""
        if request_id != getattr(self, '_p28_latest_request_id', 0):
            return
        if getattr(self, '_p28_has_completed_view', False):
            self._p28_set_status(f'Refresh failed for {ticker}; showing previous result: {message}', 'negative')
            return
        self.p28_symbol = ticker
        self.p28_symbol_label.setText(ticker)
        self._p28_clear_option_grid()
        self._p28_payload = self._p28_empty_payload(ticker)
        self._p28_payload['projections'] = {'calls': {}, 'puts': {}, 'combined': {}}
        self._p28_has_completed_view = False
        self.p28_options_meta_label.setText('No options data loaded.')
        self._p28_update_projection_strip({}, None)
        self._p28_clear_projection_markers()
        self._p28_set_status(f'Error loading {ticker}: {message}', 'negative')

    def _p28_clear_option_grid(self) -> None:
        """Remove all expiration panels."""
        if not hasattr(self, 'p28_options_grid'):
            return
        while self.p28_options_grid.count():
            item = self.p28_options_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        try:
            for col in range(max(self.p28_options_grid.columnCount(), P28_GRID_COLUMNS)):
                self.p28_options_grid.setColumnStretch(col, 0)
            for row in range(max(self.p28_options_grid.rowCount(), 1)):
                self.p28_options_grid.setRowStretch(row, 0)
        except Exception:
            pass
        self._p28_bucket_config = ()
        self._p28_sections = {}

    def _p28_grid_column_count(self, count: int) -> int:
        """Return the options grid column count."""
        return 1

    def _p28_set_bucket_config(self, bucket_config: tuple[tuple[str, str, int], ...]) -> None:
        """Store the all-expiration layout; sections are built in render slices."""
        self._p28_clear_option_grid()
        self._p28_bucket_config = tuple(bucket_config or ())

    def _p28_ensure_option_section(self, bucket_key: str, index: int, grid_columns: int) -> dict[str, Any]:
        """Create one expiration panel when its render slice reaches it."""
        existing = getattr(self, '_p28_sections', {}).get(bucket_key)
        if isinstance(existing, dict):
            return existing
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.setSpacing(4)
        label = QLabel(format_top_volume_expiration(bucket_key) or bucket_key)
        self.set_theme_role(label, 'section_title')
        projection_label = QLabel('Options-volume projection unavailable')
        projection_label.setWordWrap(True)
        self.set_theme_role(projection_label, 'muted')
        table = self._p28_make_top_volume_table()
        panel_layout.addWidget(label)
        panel_layout.addWidget(projection_label)
        panel_layout.addWidget(table, 1)
        section = {'panel': panel, 'label': label, 'projection_label': projection_label, 'table': table}
        self._p28_sections[bucket_key] = section
        self.p28_options_grid.addWidget(panel, index // grid_columns, index % grid_columns)
        return section

    def _p28_make_top_volume_table(self) -> Any:
        """Build one compact top-volume table."""
        table = QTableWidget(0, len(P28_TOP_VOLUME_COLUMNS))
        table.setHorizontalHeaderLabels(list(P28_TOP_VOLUME_COLUMNS))
        table.horizontalHeader().setMinimumHeight(24)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        return table

    @staticmethod
    def _p28_table_selection_key(table: Any) -> tuple[str, ...] | None:
        """Return a stable text key for the selected option row."""
        row = int(table.currentRow()) if table is not None else -1
        if row < 0:
            return None
        return tuple(
            str(table.item(row, column).text() if table.item(row, column) is not None else '')
            for column in range(table.columnCount())
        )

    @staticmethod
    def _p28_restore_table_selection(table: Any, selection_key: tuple[str, ...] | None) -> None:
        """Restore an option-row selection after its table is rebuilt."""
        if table is None or selection_key is None:
            return
        for row in range(table.rowCount()):
            candidate = tuple(
                str(table.item(row, column).text() if table.item(row, column) is not None else '')
                for column in range(table.columnCount())
            )
            if candidate == selection_key:
                table.setCurrentCell(row, 0)
                table.selectRow(row)
                return

    def _p28_render_option_tables(self, ticker: str, bucket_records: dict[str, list[dict[str, Any]]], bucket_expirations: dict[str, str]) -> None:
        """Render expiration sections in bounded event-loop slices."""
        config = tuple(getattr(self, '_p28_bucket_config', ()) or ())
        if config:
            section_entries = [(index, str(bucket_key)) for index, (bucket_key, _label, _days_out) in enumerate(config)]
        else:
            section_entries = [(index, str(bucket_key)) for index, bucket_key in enumerate(getattr(self, '_p28_sections', {}))]
        grid_columns = self._p28_grid_column_count(len(section_entries))
        self._p28_option_render_generation = getattr(self, '_p28_option_render_generation', 0) + 1
        generation = self._p28_option_render_generation
        self._p28_option_render_pending = False
        selection_keys = {
            bucket_key: self._p28_table_selection_key(section.get('table'))
            for bucket_key, section in getattr(self, '_p28_sections', {}).items()
            if isinstance(section, dict)
        }
        host = getattr(self, 'p28_options_host', None)
        previous_updates = True
        prepared = False
        handle_box: dict[str, Any] = {}

        def _prepare() -> None:
            nonlocal previous_updates, prepared
            if host is not None:
                previous_updates = host.updatesEnabled()
                host.setUpdatesEnabled(False)
            prepared = True

        def _apply(_index: int, entry: tuple[int, str]) -> None:
            section_index, bucket_key = entry
            section = self._p28_ensure_option_section(bucket_key, section_index, grid_columns)
            table = section.get('table') if isinstance(section, dict) else None
            label = section.get('label') if isinstance(section, dict) else None
            projection_label = section.get('projection_label') if isinstance(section, dict) else None
            expiry = str(bucket_expirations.get(bucket_key, bucket_key) or bucket_key)
            display = format_top_volume_expiration(expiry) or expiry
            if label is not None:
                label.setText(display)
            self._p28_update_section_projection_label(projection_label, bucket_key)
            if table is None:
                return
            table.setToolTip(f'Using expiration {display}' if display else 'No expiration available')
            render_table_rows(
                table,
                build_option_summary_rows(
                    bucket_records.get(bucket_key, []),
                    ticker=ticker,
                    expiry=expiry,
                    positive_color=self.theme_color('accent_positive'),
                    negative_color=self.theme_color('accent_negative'),
                    price_highlight_backgrounds=self._p28_price_highlight_backgrounds(),
                    low_price_highlight_backgrounds=(),
                    top_volume_highlight_backgrounds=self._p28_volume_highlight_backgrounds(),
                    low_volume_highlight_backgrounds=(),
                    pd_module=pd,
                ),
            )
            self._p28_restore_table_selection(table, selection_keys.get(bucket_key))

        def _finish() -> None:
            if prepared and section_entries:
                for column in range(grid_columns):
                    self.p28_options_grid.setColumnStretch(column, 1)
                for row in range(max(1, math.ceil(len(section_entries) / grid_columns))):
                    self.p28_options_grid.setRowStretch(row, 1)
            if prepared and host is not None:
                host.setUpdatesEnabled(previous_updates)
                if previous_updates:
                    host.update()
            handle = handle_box.get('handle')
            if generation != getattr(self, '_p28_option_render_generation', 0) or handle is None:
                return
            self._p28_option_render_pending = not bool(handle.completed)

        def _on_error(exc: Exception) -> None:
            if generation == getattr(self, '_p28_option_render_generation', 0):
                self._p28_option_render_pending = True
                if self._p28_is_render_surface_visible():
                    self._p28_set_status(f'Unable to render all option expirations: {exc}', 'negative')

        handle = run_batched(
            self,
            'projections-option-sections',
            section_entries,
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            on_error=_on_error,
            is_current=lambda value: value == getattr(self, '_p28_option_render_generation', 0),
            is_visible=self._p28_is_render_surface_visible,
            max_batch_ms=8.0,
            max_items=4,
        )
        handle_box['handle'] = handle

    def _p28_loaded_row_count(self) -> int:
        """Return the number of loaded option rows."""
        payload = getattr(self, '_p28_payload', {})
        records = payload.get('records', {}) if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return 0
        return sum(len(list(rows or [])) for rows in records.values())

    def _p28_apply_loaded_type_filter(self) -> bool:
        """Re-render loaded option tables for the selected type filter without refetching."""
        payload = getattr(self, '_p28_payload', {})
        if not isinstance(payload, dict):
            return False
        records_by_filter = payload.get('records_by_filter', {})
        if not isinstance(records_by_filter, dict):
            return False
        selected = self._p28_normalize_type_filter(getattr(self, 'p28_type_filter', 'calls'))
        selected_records = records_by_filter.get(selected)
        if not isinstance(selected_records, dict):
            return False
        bucket_order = list(payload.get('bucket_order', []) or [])
        if not bucket_order:
            return False
        bucket_records = {str(bucket_key): list(selected_records.get(bucket_key, []) or []) for bucket_key in bucket_order}
        payload['type_filter'] = selected
        payload['records'] = bucket_records
        self._p28_payload = payload
        expirations = payload.get('expirations', {}) if isinstance(payload.get('expirations', {}), dict) else {}
        self._p28_render_option_tables(str(payload.get('ticker', getattr(self, 'p28_symbol', '')) or ''), bucket_records, expirations)
        self._p28_render_projection_markers()
        row_total = self._p28_loaded_row_count()
        expiry_count = len(bucket_order)
        self.p28_options_meta_label.setText(f'{row_total} rows across {expiry_count} expirations | {self._p28_type_label()} | {self._p28_expiration_scope_label()}')
        if row_total <= 0:
            self._p28_set_status(f'No {self._p28_type_label().lower()} top-volume options rows were available for {getattr(self, "p28_symbol", "")}.', 'warning')
        else:
            self._p28_set_status(f'Updated {getattr(self, "p28_symbol", "")}: {row_total} {self._p28_type_label().lower()} rows across {expiry_count} expirations', 'positive')
        return True

    def _p28_render_chart(self, df: Any, interval: str) -> None:
        """Render the OHLCV chart."""
        self._p28_chart_df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        self._p28_chart_interval = str(interval or '1d')
        self._p28_chart_rows = list(self._p28_chart_df.itertuples()) if not self._p28_chart_df.empty else []
        self.p28_main_plot.clear()
        self.p28_volume_plot.clear()
        self._p28_candle_item = None
        self._p28_volume_item = None
        self._p28_projection_marker_items = []
        self._p28_projection_path_items = []
        if self._p28_chart_df.empty or not self._p28_chart_rows:
            self.p28_price_label.setText('--')
            self.p28_change_label.setText('--')
            return
        dates = list(self._p28_chart_df.index)
        self.p28_chart_axis.set_dates(dates, interval)
        self.p28_volume_axis.set_dates(dates, interval)
        candle_data = []
        volumes = []
        brushes = []
        up_color = self.theme_color('accent_positive')
        down_color = self.theme_color('accent_negative')
        for index, row in enumerate(self._p28_chart_rows):
            open_value = float(getattr(row, 'Open'))
            close_value = float(getattr(row, 'Close'))
            low_value = float(getattr(row, 'Low'))
            high_value = float(getattr(row, 'High'))
            candle_data.append((index, open_value, close_value, low_value, high_value))
            volumes.append(float(getattr(row, 'Volume', 0.0) or 0.0))
            brushes.append(pg.mkBrush(up_color if close_value >= open_value else down_color))
        self._p28_candle_item = CandlestickItem(candle_data, up_color=up_color, down_color=down_color)
        self.p28_main_plot.addItem(self._p28_candle_item)
        self._p28_volume_item = pg.BarGraphItem(x=list(range(len(volumes))), height=volumes, width=0.7, brushes=brushes)
        self.p28_volume_plot.addItem(self._p28_volume_item)
        self._p28_apply_chart_ranges()
        self._p28_update_chart_header()

    def _p28_apply_chart_ranges(self) -> None:
        """Set chart ranges around the latest visible candles."""
        if not self._p28_chart_rows:
            return
        right = len(self._p28_chart_rows) - 1
        left = max(0, right - min(120, len(self._p28_chart_rows)) + 1)
        visible = self._p28_chart_rows[left:right + 1]
        lows = [float(getattr(row, 'Low')) for row in visible]
        highs = [float(getattr(row, 'High')) for row in visible]
        x_right = float(right) + 1.0
        for side in ('calls', 'puts', 'combined'):
            path_points = self._p28_projection_path_points(side)
            if path_points is not None:
                xs, ys = path_points
                lows.extend(ys)
                highs.extend(ys)
                if xs:
                    x_right = max(x_right, max(xs) + 1.0)
        min_low = min(lows)
        max_high = max(highs)
        pad = max((max_high - min_low) * 0.08, max_high * 0.005, 0.01)
        self.p28_main_plot.setXRange(float(left) - 1.0, x_right, padding=0)
        self.p28_main_plot.setYRange(min_low - pad, max_high + pad, padding=0)
        volumes = [float(getattr(row, 'Volume', 0.0) or 0.0) for row in visible]
        max_volume = max(volumes) if volumes else 0.0
        self.p28_volume_plot.setYRange(0.0, max_volume * 1.15 if max_volume > 0 else 1.0, padding=0)

    def _p28_update_chart_header(self) -> None:
        """Refresh the chart quote strip."""
        if not self._p28_chart_rows:
            self.p28_price_label.setText('--')
            self.p28_change_label.setText('--')
            return
        latest = self._p28_chart_rows[-1]
        previous = self._p28_chart_rows[-2] if len(self._p28_chart_rows) > 1 else latest
        close_value = float(getattr(latest, 'Close', 0.0) or 0.0)
        previous_close = float(getattr(previous, 'Close', close_value) or close_value)
        change_value = close_value - previous_close
        change_pct = change_value / previous_close * 100 if previous_close else 0.0
        sign = '+' if change_value >= 0 else ''
        color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        self.p28_symbol_label.setText(getattr(self, 'p28_symbol', ''))
        self.p28_price_label.setText(f'${close_value:,.2f}')
        self.p28_change_label.setText(f'{sign}{change_value:,.2f} ({sign}{change_pct:.2f}%)')
        self.p28_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {color};')

    def _p28_numeric_value(self, value: Any) -> float | None:
        """Return a finite float or None."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def _p28_effective_option_price(self, opt: dict[str, Any]) -> tuple[float | None, float | None]:
        """Return a valid bid/ask midpoint and spread percentage."""
        bid = self._p28_numeric_value(opt.get('bid'))
        ask = self._p28_numeric_value(opt.get('ask'))
        if bid is not None and ask is not None and bid > 0.0 and ask > 0.0 and ask >= bid:
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid if mid > 0.0 else None
            return mid, spread_pct
        return None, None

    def _p28_spread_quality_weight(self, spread_pct: float | None) -> tuple[float, bool]:
        """Return spread-quality weight and whether the contract is too wide."""
        if spread_pct is None:
            return 0.0, True
        if spread_pct > P28_PROXY_MAX_SPREAD_PCT:
            return 0.0, True
        weight = max(0.15, 1.0 - (spread_pct / P28_PROXY_MAX_SPREAD_PCT))
        return weight, False

    def _p28_moneyness_quality_weight(self, strike: float, spot: float) -> float:
        """Downweight very far-OTM/ITM strikes so lottery volume does not dominate."""
        if spot <= 0.0:
            return 1.0
        moneyness = abs(strike - spot) / spot
        scaled = min(moneyness, P28_PROXY_MONEYNESS_SOFT_LIMIT) / P28_PROXY_MONEYNESS_SOFT_LIMIT
        return max(P28_PROXY_MIN_MONEYNESS_WEIGHT, 1.0 - scaled)

    def _p28_liquidity_weight(
        self,
        *,
        volume: float,
        open_interest: float,
        strike: float,
        spot: float,
        spread_pct: float | None,
    ) -> tuple[float, bool]:
        """Return robust liquidity/quality weight and wide-spread flag."""
        spread_weight, is_wide_spread = self._p28_spread_quality_weight(spread_pct)
        if is_wide_spread or volume <= 0.0:
            return 0.0, is_wide_spread
        moneyness_weight = self._p28_moneyness_quality_weight(strike, spot)
        liquidity = math.sqrt(volume) * (1.0 + math.log1p(max(open_interest, 0.0)))
        return liquidity * spread_weight * moneyness_weight, False

    def _p28_latest_chart_close(self) -> float | None:
        """Return the latest chart close value if it is available."""
        rows = list(getattr(self, '_p28_chart_rows', []) or [])
        if not rows:
            return None
        return self._p28_numeric_value(getattr(rows[-1], 'Close', None))

    def _p28_prepare_projection_records(self, chain_df: Any, *, ticker: str, expiry: str) -> list[dict[str, Any]]:
        """Return all valid options-volume proxy input rows from one chain."""
        if chain_df is None or getattr(chain_df, 'empty', True):
            return []
        prepared = chain_df.copy()
        if 'ticker' not in prepared.columns:
            prepared['ticker'] = ticker
        if 'type' not in prepared.columns:
            prepared['type'] = ''
        if 'expiration' not in prepared.columns:
            prepared['expiration'] = expiry
        for col in ('strike', 'lastPrice', 'volume', 'openInterest', 'bid', 'ask', 'impliedVolatility'):
            if col not in prepared.columns:
                prepared[col] = 0.0
            prepared[col] = pd.to_numeric(prepared[col], errors='coerce')
        prepared = prepared.dropna(subset=['strike', 'volume']).copy()
        if prepared.empty:
            return []
        prepared = prepared[(prepared['strike'] > 0.0) & (prepared['volume'] > 0.0)].copy()
        if prepared.empty:
            return []
        prepared['openInterest'] = prepared['openInterest'].fillna(0.0)
        prepared['lastPrice'] = prepared['lastPrice'].fillna(0.0)
        prepared = prepared.sort_values(by=['volume', 'openInterest'], ascending=False, na_position='last')
        return prepared.to_dict('records')

    def _p28_weighted_average(self, pairs: list[tuple[float, float]]) -> float | None:
        """Return a weighted average from value/weight pairs."""
        total_weight = sum(weight for _value, weight in pairs if weight > 0.0)
        if total_weight <= 0.0:
            return None
        return sum(value * weight for value, weight in pairs if weight > 0.0) / total_weight

    def _p28_weighted_percentile(self, pairs: list[tuple[float, float]], percentile: float) -> float | None:
        """Return a weighted percentile from value/weight pairs."""
        clean = sorted((value, weight) for value, weight in pairs if weight > 0.0)
        if not clean:
            return None
        total_weight = sum(weight for _value, weight in clean)
        if total_weight <= 0.0:
            return None
        threshold = max(0.0, min(1.0, float(percentile))) * total_weight
        running = 0.0
        for value, weight in clean:
            running += weight
            if running >= threshold:
                return value
        return clean[-1][0]

    def _p28_build_projection_summaries(
        self,
        bucket_config: tuple[tuple[str, str, int], ...],
        bucket_projection_records: dict[str, list[dict[str, Any]]],
        bucket_expirations: dict[str, str],
        current_close: float | None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Build call, put, and combined projection anchors for every expiration."""
        summaries: dict[str, dict[str, dict[str, Any]]] = {'calls': {}, 'puts': {}, 'combined': {}}
        for bucket_key, _bucket_label, days_out in bucket_config:
            records = list(bucket_projection_records.get(bucket_key, [])) if isinstance(bucket_projection_records, dict) else []
            expiry = str(bucket_expirations.get(bucket_key, bucket_key) if isinstance(bucket_expirations, dict) else bucket_key)
            for side in ('calls', 'puts'):
                summary = self._p28_projection_side_summary(
                    records,
                    side=side,
                    bucket_key=bucket_key,
                    expiry=expiry,
                    days_out=days_out,
                    current_close=current_close,
                )
                if summary:
                    summaries[side][bucket_key] = summary
            combined = self._p28_combined_projection_summary(
                summaries['calls'].get(bucket_key),
                summaries['puts'].get(bucket_key),
            )
            if combined:
                summaries['combined'][bucket_key] = combined
        return summaries

    def _p28_combined_projection_summary(
        self,
        call_summary: dict[str, Any] | None,
        put_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Combine call and put anchors using confidence and coverage weights."""
        if not isinstance(call_summary, dict) or not isinstance(put_summary, dict):
            return None
        call_price = self._p28_numeric_value(call_summary.get('projected_price'))
        put_price = self._p28_numeric_value(put_summary.get('projected_price'))
        spot = self._p28_numeric_value(call_summary.get('spot'))
        if call_price is None or put_price is None or spot is None or spot <= 0.0:
            return None
        call_contracts = max(int(self._p28_numeric_value(call_summary.get('included_contract_count')) or 0), 1)
        put_contracts = max(int(self._p28_numeric_value(put_summary.get('included_contract_count')) or 0), 1)
        call_confidence = max(self._p28_numeric_value(call_summary.get('confidence_score')) or 0.0, 0.05)
        put_confidence = max(self._p28_numeric_value(put_summary.get('confidence_score')) or 0.0, 0.05)
        call_weight = call_confidence * math.sqrt(call_contracts)
        put_weight = put_confidence * math.sqrt(put_contracts)
        total_weight = call_weight + put_weight
        if total_weight <= 0.0:
            return None
        projected_price = (call_price * call_weight + put_price * put_weight) / total_weight
        change = projected_price - spot
        confidence_score = min(
            self._p28_numeric_value(call_summary.get('confidence_score')) or 0.0,
            self._p28_numeric_value(put_summary.get('confidence_score')) or 0.0,
        )
        confidence_label = 'High' if confidence_score >= 0.70 else ('Moderate' if confidence_score >= 0.45 else 'Low')
        return {
            'side': 'combined',
            'bucket_key': str(call_summary.get('bucket_key', '') or ''),
            'expiration': str(call_summary.get('expiration', '') or ''),
            'expiration_display': str(call_summary.get('expiration_display', '') or ''),
            'days_out': int(self._p28_numeric_value(call_summary.get('days_out')) or 0),
            'spot': spot,
            'current_close': spot,
            'projected_price': projected_price,
            'implied_price': projected_price,
            'projected_change': change,
            'projected_change_pct': change / spot * 100.0,
            'confidence_score': confidence_score,
            'confidence_label': confidence_label,
            'included_contract_count': call_contracts + put_contracts,
            'total_premium': (self._p28_numeric_value(call_summary.get('total_premium')) or 0.0) + (self._p28_numeric_value(put_summary.get('total_premium')) or 0.0),
            'call_weight': call_weight,
            'put_weight': put_weight,
        }

    def _p28_projection_summary_for_records(
        self,
        records: list[dict[str, Any]],
        *,
        bucket_key: str,
        expiry: str,
        days_out: int,
        current_close: float | None,
    ) -> dict[str, Any] | None:
        """Compatibility wrapper returning both independent side summaries."""
        calls = self._p28_projection_side_summary(records, side='calls', bucket_key=bucket_key, expiry=expiry, days_out=days_out, current_close=current_close)
        puts = self._p28_projection_side_summary(records, side='puts', bucket_key=bucket_key, expiry=expiry, days_out=days_out, current_close=current_close)
        if not calls and not puts:
            return None
        return {'calls': calls, 'puts': puts}

    def _p28_projection_side_summary(
        self,
        records: list[dict[str, Any]],
        *,
        side: str,
        bucket_key: str,
        expiry: str,
        days_out: int,
        current_close: float | None,
    ) -> dict[str, Any] | None:
        """Derive one robust call or put break-even scenario anchor."""
        spot = self._p28_numeric_value(current_close)
        if spot is None or spot <= 0.0:
            return None
        side = 'puts' if str(side).lower().startswith('put') else 'calls'
        prefix = 'put' if side == 'puts' else 'call'
        total_volume = total_open_interest = total_premium = 0.0
        wide_spread_count = 0
        quote_rows = 0
        iv_rows = 0
        candidate_pairs: list[tuple[float, float]] = []
        candidate_values: list[float] = []
        spreads: list[float] = []
        weights: list[float] = []
        for opt in list(records or []):
            if not isinstance(opt, dict):
                continue
            option_type = str(opt.get('type', '') or '').strip().lower()
            if not option_type.startswith(prefix):
                continue
            strike = self._p28_numeric_value(opt.get('strike'))
            volume = self._p28_numeric_value(opt.get('volume')) or 0.0
            effective_price, spread_pct = self._p28_effective_option_price(opt)
            open_interest = self._p28_numeric_value(opt.get('openInterest')) or 0.0
            if strike is None or volume <= 0.0 or effective_price is None or effective_price <= 0.0:
                continue
            weight, is_wide_spread = self._p28_liquidity_weight(
                volume=volume,
                open_interest=open_interest,
                strike=strike,
                spot=spot,
                spread_pct=spread_pct,
            )
            if is_wide_spread:
                wide_spread_count += 1
            if weight <= 0.0:
                continue
            quote_rows += 1
            premium_dollars = effective_price * volume * 100.0
            candidate = strike + effective_price if side == 'calls' else strike - effective_price
            iv = self._p28_numeric_value(opt.get('impliedVolatility'))
            if iv is not None and iv > 0.0 and days_out > 0:
                iv_rows += 1
                expected_move = spot * iv * math.sqrt(max(days_out, 1) / 365.0)
                bound = P28_PROXY_IV_RANGE_MULTIPLIER * expected_move
                low, high = spot - bound, spot + bound
                if candidate < low or candidate > high:
                    weight *= 0.25
                    candidate = min(max(candidate, low), high)
            candidate_pairs.append((candidate, weight))
            candidate_values.append(candidate)
            weights.append(weight)
            if spread_pct is not None:
                spreads.append(spread_pct)
            total_volume += volume
            total_open_interest += open_interest
            total_premium += premium_dollars
        total_weight = sum(weights)
        if not candidate_pairs or total_weight <= 0.0:
            return None
        projected_price = self._p28_weighted_percentile(candidate_pairs, 0.50)
        if projected_price is None:
            return None
        implied_change = projected_price - spot
        implied_change_pct = implied_change / spot * 100.0 if spot else None
        sorted_spreads = sorted(spreads)
        median_spread = sorted_spreads[len(sorted_spreads) // 2] if sorted_spreads else P28_PROXY_MAX_SPREAD_PCT
        dispersion = self._p28_weighted_percentile([(abs(value - projected_price) / spot, weight) for value, weight in candidate_pairs], 0.50) or 0.0
        iv_coverage = iv_rows / quote_rows if quote_rows else 0.0
        concentration = max(weights) / total_weight if weights else 1.0
        confidence_score = max(0.0, min(1.0,
            min(quote_rows / 12.0, 1.0) * 0.25
            + iv_coverage * 0.20
            + max(0.0, 1.0 - median_spread / P28_PROXY_MAX_SPREAD_PCT) * 0.20
            + max(0.0, 1.0 - min(dispersion / 0.25, 1.0)) * 0.20
            + max(0.0, 1.0 - concentration) * 0.15
        ))
        confidence_label = 'High' if confidence_score >= 0.70 else ('Moderate' if confidence_score >= 0.45 else 'Low')
        return {
            'side': side,
            'bucket_key': bucket_key,
            'expiration': expiry,
            'expiration_display': format_top_volume_expiration(expiry) or expiry,
            'days_out': int(days_out or 0),
            'spot': spot,
            'implied_price': projected_price,
            'projected_price': projected_price,
            'current_close': spot,
            'implied_change': implied_change,
            'implied_change_pct': implied_change_pct,
            'projected_change': implied_change,
            'projected_change_pct': implied_change_pct,
            'total_volume': total_volume,
            'total_open_interest': total_open_interest,
            'total_premium': total_premium,
            'total_signal_weight': total_weight,
            'wide_spread_count': wide_spread_count,
            'median_spread_pct': median_spread,
            'dispersion_pct': dispersion,
            'iv_coverage': iv_coverage,
            'concentration': concentration,
            'confidence_label': confidence_label,
            'confidence_score': confidence_score,
            'signal_quality': confidence_label,
            'signal_score': confidence_score,
            'row_count': quote_rows,
            'included_contract_count': quote_rows,
        }

    def _p28_projection_bucket_order(self) -> list[str]:
        """Return the loaded projection bucket order."""
        payload = getattr(self, '_p28_payload', {})
        order = payload.get('bucket_order', []) if isinstance(payload, dict) else []
        return [str(bucket_key) for bucket_key in list(order or [])]

    def _p28_projection_headlines(self, projections: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        """Return nearest valid call, put, and combined anchors."""
        calls = self._p28_projection_summaries_ordered('calls', projections)
        puts = self._p28_projection_summaries_ordered('puts', projections)
        combined = self._p28_projection_summaries_ordered('combined', projections)
        return (calls[0] if calls else None, puts[0] if puts else None, combined[0] if combined else None)

    def _p28_projection_summaries_ordered(self, side: str = 'calls', projections: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return one side's summaries in expiration order."""
        source = projections if isinstance(projections, dict) else getattr(self, '_p28_payload', {}).get('projections', {})
        side_source = source.get(side, {}) if isinstance(source, dict) else {}
        if not isinstance(side_source, dict):
            return []
        ordered = [side_source[key] for key in self._p28_projection_bucket_order() if isinstance(side_source.get(key), dict)]
        return [summary for summary in ordered if self._p28_numeric_value(summary.get('projected_price')) is not None]

    def _p28_latest_chart_date(self) -> datetime.date | None:
        """Return the latest chart date used as the weekly path origin."""
        frame = getattr(self, '_p28_chart_df', None)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        try:
            return pd.Timestamp(frame.index[-1]).date()
        except Exception:
            return None

    def _p28_build_weekly_projection_points(self, projections: dict[str, Any], current_close: float | None) -> dict[str, list[dict[str, Any]]]:
        """Interpolate seven-calendar-day points through each side's expiration anchors."""
        spot = self._p28_numeric_value(current_close)
        as_of = self._p28_latest_chart_date()
        result: dict[str, list[dict[str, Any]]] = {'calls': [], 'puts': [], 'combined': []}
        if spot is None or as_of is None:
            return result
        for side in ('calls', 'puts', 'combined'):
            summaries = self._p28_projection_summaries_ordered(side, projections)
            anchors: list[tuple[datetime.date, float, dict[str, Any] | None]] = [(as_of, spot, None)]
            for summary in summaries:
                try:
                    expiry_date = datetime.date.fromisoformat(str(summary.get('expiration', '') or ''))
                except ValueError:
                    continue
                price = self._p28_numeric_value(summary.get('projected_price'))
                if price is not None and expiry_date > as_of:
                    anchors.append((expiry_date, price, summary))
            anchors.sort(key=lambda item: item[0])
            if len(anchors) < 2:
                continue
            point_dates = {date_value for date_value, _price, _summary in anchors}
            cursor = as_of + datetime.timedelta(days=7)
            while cursor <= anchors[-1][0]:
                point_dates.add(cursor)
                cursor += datetime.timedelta(days=7)
            points: list[dict[str, Any]] = []
            for point_date in sorted(point_dates):
                left = anchors[0]
                right = anchors[-1]
                for index in range(1, len(anchors)):
                    if point_date <= anchors[index][0]:
                        left, right = anchors[index - 1], anchors[index]
                        break
                span_days = max((right[0] - left[0]).days, 1)
                ratio = max(0.0, min(1.0, (point_date - left[0]).days / span_days))
                price = left[1] + (right[1] - left[1]) * ratio
                right_summary = right[2] or {}
                left_label = left[0].isoformat()
                right_label = right[0].isoformat()
                points.append({
                    'side': side,
                    'date': point_date.isoformat(),
                    'projected_price': price,
                    'confidence_label': str(right_summary.get('confidence_label', 'Low') or 'Low'),
                    'confidence_score': self._p28_numeric_value(right_summary.get('confidence_score')) or 0.0,
                    'left_anchor': left_label,
                    'right_anchor': right_label,
                    'is_expiration_anchor': any(point_date == anchor[0] and anchor[2] is not None for anchor in anchors),
                })
            result[side] = points
        return result

    def _p28_weekly_x_by_date(self) -> dict[str, float]:
        """Map unique weekly path dates to stable future chart slots."""
        rows = list(getattr(self, '_p28_chart_rows', []) or [])
        if not rows:
            return {}
        payload = getattr(self, '_p28_payload', {})
        weekly = payload.get('weekly_points', {}) if isinstance(payload, dict) else {}
        dates = sorted({str(point.get('date', '')) for side in ('calls', 'puts', 'combined') for point in list(weekly.get(side, []) or []) if isinstance(point, dict) and point.get('date')})
        base = float(len(rows) - 1)
        return {date_text: base + index * P28_PROXY_EXPIRATION_STEP for index, date_text in enumerate(dates)}

    def _p28_projection_path_points(self, side: str) -> tuple[list[float], list[float]] | None:
        """Return x/y arrays for one side's weekly projection path."""
        payload = getattr(self, '_p28_payload', {})
        weekly = payload.get('weekly_points', {}) if isinstance(payload, dict) else {}
        points = list(weekly.get(side, []) or []) if isinstance(weekly, dict) else []
        x_by_date = self._p28_weekly_x_by_date()
        clean = [(x_by_date.get(str(point.get('date', ''))), self._p28_numeric_value(point.get('projected_price'))) for point in points if isinstance(point, dict)]
        clean = [(x, y) for x, y in clean if x is not None and y is not None]
        if len(clean) < 2:
            return None
        return [float(x) for x, _y in clean], [float(y) for _x, y in clean]

    def _p28_projection_aggregate(self, projections: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return combined data-confidence and coverage metadata."""
        summaries = self._p28_projection_summaries_ordered('calls', projections) + self._p28_projection_summaries_ordered('puts', projections)
        if not summaries:
            return None
        contracts = sum(int(self._p28_numeric_value(summary.get('included_contract_count')) or 0) for summary in summaries)
        expirations = len({str(summary.get('bucket_key', '')) for summary in summaries})
        weighted_total = sum(self._p28_numeric_value(summary.get('included_contract_count')) or 0.0 for summary in summaries)
        confidence = sum((self._p28_numeric_value(summary.get('confidence_score')) or 0.0) * (self._p28_numeric_value(summary.get('included_contract_count')) or 0.0) for summary in summaries) / max(weighted_total, 1.0)
        label = 'High' if confidence >= 0.70 else ('Moderate' if confidence >= 0.45 else 'Low')
        return {'confidence_score': confidence, 'confidence_label': label, 'included_contract_count': contracts, 'expiration_count': expirations}

    def _p28_projection_change_text(self, summary: dict[str, Any]) -> str:
        """Format projected change versus chart close."""
        change = self._p28_numeric_value(summary.get('projected_change'))
        pct = self._p28_numeric_value(summary.get('projected_change_pct'))
        if change is None or pct is None:
            return 'No chart close'
        sign = '+' if change >= 0.0 else '-'
        return f'{sign}${abs(change):,.2f} ({sign}{abs(pct):.2f}%)'

    def _p28_projection_color(self, summary: dict[str, Any] | None = None, *, bias_key: str | None = None) -> str:
        """Return a theme color for one projection value."""
        if bias_key is None and isinstance(summary, dict):
            change = self._p28_numeric_value(summary.get('projected_change'))
            if change is not None:
                bias_key = 'calls' if change >= 0.0 else 'puts'
            else:
                bias_key = str(summary.get('bias_key', '') or '')
        if bias_key == 'calls':
            return self.theme_color('accent_positive')
        if bias_key == 'puts':
            return self.theme_color('accent_negative')
        if bias_key == 'neutral':
            return self.theme_color('warning')
        return self.theme_color('text_primary')

    def _p28_set_projection_metric(self, key: str, value: str, meta: str, color: str | None = None) -> None:
        """Set one projection strip metric."""
        value_label = getattr(self, '_p28_projection_value_labels', {}).get(key)
        meta_label = getattr(self, '_p28_projection_meta_labels', {}).get(key)
        if value_label is not None:
            value_label.setText(value)
            value_label.setStyleSheet(f'font-size: 16px; font-weight: bold; color: {color or self.theme_color("text_primary")};')
        if meta_label is not None:
            meta_label.setText(meta)

    def _p28_format_projection_price(self, value: Any) -> str:
        """Format a projected stock price."""
        numeric = self._p28_numeric_value(value)
        return f'${numeric:,.2f}' if numeric is not None else '--'

    def _p28_format_projection_volume(self, value: Any) -> str:
        """Format projection volume."""
        numeric = self._p28_numeric_value(value) or 0.0
        return f'{int(round(numeric)):,}'

    def _p28_update_projection_strip(self, projections: dict[str, Any] | None = None, current_close: float | None = None) -> None:
        """Refresh separate call/put headline cards and confidence coverage."""
        if not hasattr(self, '_p28_projection_value_labels'):
            return
        close_value = self._p28_numeric_value(current_close)
        self._p28_set_projection_metric(
            'close',
            self._p28_format_projection_price(close_value),
            'Latest chart close' if close_value is not None else 'No chart close',
            self.theme_color('text_primary'),
        )
        nearest_call, nearest_put, nearest_combined = self._p28_projection_headlines(projections or {})
        for key, summary, color_key in (
            ('calls', nearest_call, 'accent_positive'),
            ('puts', nearest_put, 'accent_negative'),
            ('combined', nearest_combined, 'warning'),
        ):
            if summary:
                self._p28_set_projection_metric(
                    key,
                    self._p28_format_projection_price(summary.get('projected_price')),
                    '{expiration} | {change} | {confidence} confidence | Contracts {contracts}'.format(
                        expiration=summary.get('expiration_display', ''),
                        change=self._p28_projection_change_text(summary),
                        confidence=summary.get('confidence_label', 'Low'),
                        contracts=f"{int(self._p28_numeric_value(summary.get('included_contract_count')) or 0):,}",
                    ),
                    self.theme_color(color_key),
                )
            else:
                self._p28_set_projection_metric(key, '--', f'No {key[:-1]} projection available', self.theme_color('text_primary'))
        aggregate = self._p28_projection_aggregate(projections or {})
        if aggregate:
            self._p28_set_projection_metric(
                'confidence',
                f"{aggregate.get('confidence_label', 'Low')} ({(self._p28_numeric_value(aggregate.get('confidence_score')) or 0.0):.0%})",
                f"{int(aggregate.get('expiration_count', 0)):,} expirations | {int(aggregate.get('included_contract_count', 0)):,} valid contracts",
                self.theme_color('warning'),
            )
        else:
            self._p28_set_projection_metric('confidence', '--', 'No projection coverage', self.theme_color('text_primary'))

    def _p28_update_section_projection_label(self, label: Any, bucket_key: str) -> None:
        """Refresh one expiration panel projection summary."""
        if label is None:
            return
        payload = getattr(self, '_p28_payload', {})
        projections = payload.get('projections', {}) if isinstance(payload, dict) else {}
        call_summary = projections.get('calls', {}).get(bucket_key) if isinstance(projections, dict) and isinstance(projections.get('calls'), dict) else None
        put_summary = projections.get('puts', {}).get(bucket_key) if isinstance(projections, dict) and isinstance(projections.get('puts'), dict) else None
        combined_summary = projections.get('combined', {}).get(bucket_key) if isinstance(projections, dict) and isinstance(projections.get('combined'), dict) else None
        if not isinstance(call_summary, dict) and not isinstance(put_summary, dict):
            label.setText('Options-volume projection unavailable')
            label.setStyleSheet(f'font-size: 11px; color: {self.theme_color("text_secondary")};')
            return
        call_text = self._p28_format_projection_price(call_summary.get('projected_price')) if call_summary else '--'
        put_text = self._p28_format_projection_price(put_summary.get('projected_price')) if put_summary else '--'
        combined_text = self._p28_format_projection_price(combined_summary.get('projected_price')) if combined_summary else '--'
        call_conf = str(call_summary.get('confidence_label', 'Low')) if call_summary else 'Unavailable'
        put_conf = str(put_summary.get('confidence_label', 'Low')) if put_summary else 'Unavailable'
        label.setText(f'Call {call_text} ({call_conf}) | Put {put_text} ({put_conf}) | Combined {combined_text}')
        label.setStyleSheet(f'font-size: 11px; color: {self.theme_color("text_secondary")};')

    def _p28_apply_proxy_axis_dates(self) -> None:
        """Extend chart axes with future expiration labels for proxy slots."""
        if not getattr(self, '_p28_chart_rows', []):
            return
        dates = list(self._p28_chart_df.index) if isinstance(getattr(self, '_p28_chart_df', None), pd.DataFrame) and not self._p28_chart_df.empty else []
        x_by_date = self._p28_weekly_x_by_date()
        if x_by_date:
            max_index = int(round(max(x_by_date.values())))
            while len(dates) <= max_index:
                dates.append('')
            for date_text, x_value in x_by_date.items():
                label_index = int(round(x_value))
                if 0 <= label_index < len(dates):
                    dates[label_index] = date_text
        interval = getattr(self, '_p28_chart_interval', '1d')
        self.p28_chart_axis.set_dates(dates, interval)
        self.p28_volume_axis.set_dates(dates, interval)

    def _p28_projection_point_tooltip(self, data: dict[str, Any]) -> str:
        """Build a hover tooltip for one weekly projection point."""
        return (
            f"{str(data.get('side', '')).title()} projection\n"
            f"Date: {data.get('date', '')}\n"
            f"Projected price: {self._p28_format_projection_price(data.get('projected_price'))}\n"
            f"Confidence: {data.get('confidence_label', 'Low')} ({(self._p28_numeric_value(data.get('confidence_score')) or 0.0):.0%})\n"
            f"Anchors: {data.get('left_anchor', '')} to {data.get('right_anchor', '')}"
        )

    def _p28_show_projection_point_tooltip(self, _scatter: Any, points: Any, event: Any) -> None:
        """Show the date and price for a hovered weekly point."""
        point_list = list(points) if points is not None else []
        if not point_list:
            QToolTip.hideText()
            return
        data = point_list[0].data()
        if not isinstance(data, dict):
            QToolTip.hideText()
            return
        try:
            pos = event.screenPos().toPoint()
        except Exception:
            pos = QCursor.pos() if 'QCursor' in globals() else QPoint(0, 0)
        QToolTip.showText(pos, self._p28_projection_point_tooltip(data), self.p28_main_plot)

    def _p28_clear_projection_markers(self) -> None:
        """Remove chart projection marker and path items."""
        if not hasattr(self, 'p28_main_plot'):
            return
        items = list(getattr(self, '_p28_projection_marker_items', []) or [])
        items.extend(list(getattr(self, '_p28_projection_path_items', []) or []))
        for item in items:
            try:
                self.p28_main_plot.removeItem(item)
            except Exception:
                pass
        self._p28_projection_marker_items = []
        self._p28_projection_path_items = []

    def _p28_render_projection_markers(self) -> None:
        """Draw the options-volume pressure proxy overlay on the chart."""
        self._p28_clear_projection_markers()
        if not getattr(self, '_p28_chart_rows', []):
            return
        weekly = getattr(self, '_p28_payload', {}).get('weekly_points', {})
        if not isinstance(weekly, dict) or not any(weekly.get(side) for side in ('calls', 'puts', 'combined')):
            return
        self._p28_apply_proxy_axis_dates()
        for side in ('calls', 'puts', 'combined'):
            self._p28_render_projection_path(side)
            self._p28_render_projection_points(side)

    def _p28_render_projection_path(self, side: str) -> None:
        """Draw one solid projection path through weekly points."""
        points = self._p28_projection_path_points(side)
        if points is None:
            return
        xs, ys = points
        color_key = 'accent_positive' if side == 'calls' else ('accent_negative' if side == 'puts' else 'warning')
        color = self.theme_color(color_key)
        pen = pg.mkPen(color=color, width=2.4)
        line = self.p28_main_plot.plot(xs, ys, pen=pen, antialias=True)
        line.setZValue(8)
        line._p28_path_kind = side
        self._p28_projection_path_items.append(line)

    def _p28_render_projection_points(self, side: str) -> None:
        """Draw permanently visible, hoverable weekly dots for one side."""
        payload = getattr(self, '_p28_payload', {})
        weekly = payload.get('weekly_points', {}) if isinstance(payload, dict) else {}
        points = list(weekly.get(side, []) or []) if isinstance(weekly, dict) else []
        x_by_date = self._p28_weekly_x_by_date()
        spots = []
        for point in points[1:]:
            date_text = str(point.get('date', '') or '')
            x_value = x_by_date.get(date_text)
            y_value = self._p28_numeric_value(point.get('projected_price'))
            if x_value is None or y_value is None:
                continue
            color_key = 'accent_positive' if side == 'calls' else ('accent_negative' if side == 'puts' else 'warning')
            fill = QColor(self.theme_color(color_key))
            fill.setAlpha(235)
            spots.append({
                'pos': (x_value, y_value),
                'size': P28_PROJECTION_DOT_SIZE + (1.5 if point.get('is_expiration_anchor') else 0.0),
                'brush': pg.mkBrush(fill),
                'pen': pg.mkPen(self.theme_color('panel_background'), width=1.2),
                'data': dict(point),
            })
        if not spots:
            return
        scatter = pg.ScatterPlotItem(
            spots=spots,
            hoverable=True,
            tip=lambda x, y, data: self._p28_projection_point_tooltip(data),
        )
        scatter.setZValue(10)
        scatter._p28_marker_kind = f'{side}_projection_points'
        scatter._p28_point_count = len(spots)
        self.p28_main_plot.addItem(scatter)
        self._p28_projection_marker_items.append(scatter)

    def _p28_blend_colors(self, base_color: str, accent_color: str, amount: float) -> str:
        """Blend two colors and return a hex color string."""
        base = QColor(base_color)
        accent = QColor(accent_color)
        if not base.isValid() or not accent.isValid():
            return accent_color
        amount = max(0.0, min(1.0, float(amount)))
        red = round(base.red() + (accent.red() - base.red()) * amount)
        green = round(base.green() + (accent.green() - base.green()) * amount)
        blue = round(base.blue() + (accent.blue() - base.blue()) * amount)
        return QColor(red, green, blue).name()

    def _p28_price_highlight_backgrounds(self) -> tuple[str, str]:
        """Return price highlight backgrounds."""
        return (
            self._p28_blend_colors(self.theme_color('panel_background'), self.theme_color('accent_positive'), 0.42),
            self._p28_blend_colors(self.theme_color('panel_background'), self.theme_color('accent_positive'), 0.26),
        )

    def _p28_volume_highlight_backgrounds(self) -> tuple[str, str]:
        """Return volume highlight backgrounds."""
        return (
            self._p28_blend_colors(self.theme_color('panel_background'), self.theme_color('warning'), 0.46),
            self._p28_blend_colors(self.theme_color('panel_background'), self.theme_color('warning'), 0.30),
        )

    def _p28_format_export_value(self, value: Any, *, decimals: int = 2, integer: bool = False) -> str:
        """Format one export value."""
        if value is None:
            return ''
        try:
            if pd.isna(value):
                return ''
        except Exception:
            pass
        try:
            if integer:
                return f'{int(float(value)):,}'
            return f'{float(value):,.{decimals}f}'
        except (TypeError, ValueError, OverflowError):
            return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').strip()

    def _p28_projection_change_export_value(self, summary: dict[str, Any]) -> str:
        """Return the proxy-vs-close export value."""
        change = self._p28_numeric_value(summary.get('projected_change'))
        pct = self._p28_numeric_value(summary.get('projected_change_pct'))
        if change is None or pct is None:
            return ''
        sign = '+' if change >= 0.0 else '-'
        return f'{sign}${abs(change):,.2f} ({sign}{abs(pct):.2f}%)'

    def _p28_projection_summary_export_text(self, label: str, summary: dict[str, Any] | None) -> str:
        """Return one headline proxy export line."""
        if not summary:
            return f'- {label}: Unavailable'
        pieces = [
            f"{summary.get('expiration_display', '')} {self._p28_format_projection_price(summary.get('projected_price'))}",
            f"Confidence {summary.get('confidence_label', 'Low')} ({(self._p28_numeric_value(summary.get('confidence_score')) or 0.0):.0%})",
            f"Premium {self._p28_format_projection_price(summary.get('total_premium'))}",
            f"Contracts {int(self._p28_numeric_value(summary.get('included_contract_count')) or 0):,}",
        ]
        change_text = self._p28_projection_change_export_value(summary)
        if change_text:
            pieces.insert(1, change_text)
        return f'- {label}: ' + ' | '.join(piece for piece in pieces if piece)

    def _p28_projection_export_lines(self, payload: dict[str, Any]) -> list[str]:
        """Build call, put, and combined proxy results for the Markdown export."""
        projections = payload.get('projections', {}) if isinstance(payload, dict) else {}
        if not isinstance(projections, dict):
            projections = {}
        current_close = self._p28_numeric_value(payload.get('current_close') if isinstance(payload, dict) else None)
        nearest_call, nearest_put, nearest_combined = self._p28_projection_headlines(projections)
        aggregate = self._p28_projection_aggregate(projections)
        lines = [
            '## Options-Volume Projection',
            '',
            f'- Methodology Note: {P28_PROXY_SOURCE_NOTE}',
            f'- Current Chart Close: {self._p28_format_projection_price(current_close) if current_close is not None else "Unavailable"}',
            self._p28_projection_summary_export_text('Nearest Call Projection', nearest_call),
            self._p28_projection_summary_export_text('Nearest Put Projection', nearest_put),
            self._p28_projection_summary_export_text('Nearest Combined Projection', nearest_combined),
        ]
        if aggregate:
            lines.append(
                '- Data Confidence: {confidence} ({score:.0%}) | Expirations {expirations} | Contracts {contracts}'.format(
                    confidence=str(aggregate.get('confidence_label', 'Low') or 'Low'),
                    score=self._p28_numeric_value(aggregate.get('confidence_score')) or 0.0,
                    expirations=int(aggregate.get('expiration_count', 0)),
                    contracts=f"{int(self._p28_numeric_value(aggregate.get('included_contract_count')) or 0):,}",
                )
            )
        else:
            lines.append('- Data Confidence: Unavailable')
        lines.append('')
        if not any(isinstance(projections.get(side), dict) and projections.get(side) for side in ('calls', 'puts')):
            lines.extend(['No options-volume projection was available from the loaded option-chain rows.', ''])
            return lines
        lines.extend([
            '| Side | Expiration | Projection | Vs Close | Confidence | Contracts | Total Premium | Median Spread | IV Coverage |',
            '| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |',
        ])
        for side in ('calls', 'puts', 'combined'):
            for summary in self._p28_projection_summaries_ordered(side, projections):
                lines.append(
                    '| {side} | {expiration} | {projected} | {change} | {confidence} | {contracts} | {total} | {spread} | {iv} |'.format(
                        side='Calls' if side == 'calls' else ('Puts' if side == 'puts' else 'Combined'),
                        expiration=str(summary.get('expiration_display', '') or '').replace('|', '\\|'),
                        projected=self._p28_format_projection_price(summary.get('projected_price')),
                        change=self._p28_projection_change_export_value(summary),
                        confidence=f"{summary.get('confidence_label', 'Low')} ({(self._p28_numeric_value(summary.get('confidence_score')) or 0.0):.0%})",
                        contracts=f"{int(self._p28_numeric_value(summary.get('included_contract_count')) or 0):,}",
                        total=self._p28_format_projection_price(summary.get('total_premium')),
                        spread=f"{(self._p28_numeric_value(summary.get('median_spread_pct')) or 0.0):.1%}",
                        iv=f"{(self._p28_numeric_value(summary.get('iv_coverage')) or 0.0):.0%}",
                    )
                )
        lines.append('')
        return lines

    def _p28_build_export(self) -> str:
        """Build the Markdown export for loaded top-volume options."""
        payload = getattr(self, '_p28_payload', {})
        ticker = str(payload.get('ticker', getattr(self, 'p28_symbol', '')) or '').upper().strip()
        records_by_bucket = payload.get('records', {}) if isinstance(payload, dict) else {}
        expirations = payload.get('expirations', {}) if isinstance(payload, dict) else {}
        bucket_order = list(payload.get('bucket_order', [])) if isinstance(payload, dict) else []
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lines = [
            f'# Projections Export - {ticker or "Unavailable"}',
            '',
            f'- Symbol: {ticker or "Unavailable"}',
            f'- Chart Timeframe: {getattr(self, "p28_timeframe_label", "1 Day")}',
            f'- Table Rows: {self._p28_type_label(payload.get("type_filter", getattr(self, "p28_type_filter", "calls")) if isinstance(payload, dict) else getattr(self, "p28_type_filter", "calls"))}',
            f'- Projection Period: {self._p28_expiration_scope_label(payload.get("expiration_scope", getattr(self, "p28_expiration_scope", "all")) if isinstance(payload, dict) else getattr(self, "p28_expiration_scope", "all"))}',
            f'- Exported At: {exported_at}',
            '',
        ]
        lines.extend(self._p28_projection_export_lines(payload if isinstance(payload, dict) else {}))
        lines.extend([
            '## Data',
            '',
        ])
        for bucket_key in bucket_order:
            records = list(records_by_bucket.get(bucket_key, [])) if isinstance(records_by_bucket, dict) else []
            expiry = str(expirations.get(bucket_key, bucket_key) if isinstance(expirations, dict) else bucket_key)
            expiry_display = format_top_volume_expiration(expiry) or expiry
            lines.extend([
                f'### {expiry_display}',
                '',
                f'- Selected expiration: {expiry or "Unavailable"}',
                f'- Rows exported: {len(records)}',
                '',
            ])
            if not records:
                lines.extend(['No top options volume records were available for this expiration.', ''])
                continue
            lines.extend([
                '| Ticker | Type | Strike | Expiration | Last Price | Volume | Estimated Premium Dollars |',
                '| --- | --- | ---: | --- | ---: | ---: | ---: |',
            ])
            for opt in records:
                last_price = self._p28_numeric_value(opt.get('lastPrice')) or 0.0
                volume = self._p28_numeric_value(opt.get('volume')) or 0.0
                lines.append(
                    '| {ticker} | {type_} | {strike} | {expiration} | {last_price} | {volume} | {premium} |'.format(
                        ticker=str(opt.get('ticker', ticker) or ticker).replace('|', '\\|'),
                        type_=str(opt.get('type', '') or '').replace('|', '\\|'),
                        strike=self._p28_format_export_value(opt.get('strike'), decimals=1),
                        expiration=str(opt.get('expiration', '') or expiry).replace('|', '\\|'),
                        last_price=self._p28_format_export_value(opt.get('lastPrice')),
                        volume=self._p28_format_export_value(opt.get('volume', 0), integer=True),
                        premium=self._p28_format_projection_price(last_price * volume * 100.0),
                    )
                )
            lines.append('')
        return '\n'.join(lines).rstrip() + '\n'

    def _p28_export_top_volume(self) -> None:
        """Copy the current all-expiration top-volume payload to the clipboard."""
        if self._p28_loaded_row_count() <= 0:
            self._p28_set_status('No options top-volume data is currently loaded to export.', 'warning')
            QMessageBox.warning(self, 'No Options Data', 'Load options top-volume data first, then export it.')
            return
        try:
            QApplication.clipboard().setText(self._p28_build_export())
        except Exception as exc:
            self._p28_set_status(f'Export failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Export Failed', f'Unable to copy top-volume options to the clipboard.\n\n{exc}')
            return
        self._p28_set_status(f'Top-volume options export copied for {getattr(self, "p28_symbol", "")}', 'positive')

    def _apply_charts_options_top_volume_theme(self) -> None:
        """Refresh theme-dependent page surfaces."""
        if not hasattr(self, 'p28_main_plot'):
            return
        self.style_plot_widget(self.p28_main_plot)
        self.style_plot_widget(self.p28_volume_plot, show_y_grid=False)
        self.p28_symbol_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p28_price_label.setStyleSheet(f'font-size: 20px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p28_call_legend.setStyleSheet(f'font-size: 12px; font-weight: 600; color: {self.theme_color("accent_positive")};')
        self.p28_put_legend.setStyleSheet(f'font-size: 12px; font-weight: 600; color: {self.theme_color("accent_negative")};')
        self.p28_combined_legend.setStyleSheet(f'font-size: 12px; font-weight: 600; color: {self.theme_color("warning")};')
        self._p28_update_chart_header()
        self._p28_update_timeframe_buttons()
        self._p28_update_type_buttons()
        payload = getattr(self, '_p28_payload', {})
        projections = payload.get('projections', {}) if isinstance(payload, dict) else {}
        self._p28_apply_proxy_axis_dates()
        self._p28_update_projection_strip(projections if isinstance(projections, dict) else {}, payload.get('current_close') if isinstance(payload, dict) else None)
        self._p28_set_status(self.p28_status_label.text(), self.p28_status_label.property('bt_status') or 'muted')
        records = payload.get('records', {}) if isinstance(payload, dict) else {}
        expirations = payload.get('expirations', {}) if isinstance(payload, dict) else {}
        if isinstance(records, dict):
            self._p28_render_option_tables(getattr(self, 'p28_symbol', ''), records, expirations if isinstance(expirations, dict) else {})
        self._p28_render_projection_markers()
