from __future__ import annotations
import math
from typing import Any
from ..compat import *
from budget_terminal_app.data_service.results import (
    attach_market_data_result,
    data_sources_from_meta,
    describe_market_data_status,
    market_data_errors,
    market_data_meta,
)
from budget_terminal_app.services.chart_data import ChartDataService


P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS = [
    ('1 Minute', '7d', '1m'),
    ('5 Minutes', '60d', '5m'),
    ('15 Minutes', '60d', '15m'),
    ('1 Hour', '730d', '1h'),
    ('1 Day', '5y', '1d'),
    ('1 Week', '5y', '1wk'),
    ('1 Month', '5y', '1mo'),
]
P10_MAIN_TIMEFRAME_OPTIONS = [
    ('1 Minute', '7d', '1m'),
    ('5 Minutes', '60d', '5m'),
    ('15 Minutes', '60d', '15m'),
    ('1 Hour', '730d', '1h'),
    ('4 Hours', '730d', '4h'),
    ('1 Day', '5y', '1d'),
    ('1 Week', '5y', '1wk'),
    ('1 Month', '5y', '1mo'),
]
P10_COMPARE_INTERVAL_OPTIONS = [
    ('1 Day', '1d'),
    ('1 Week', '1wk'),
]
P10_COMPARE_RANGE_OPTIONS = [
    ('5Y', '5y'),
    ('3Y', '3y'),
    ('1Y', '1y'),
    ('YTD', 'ytd'),
    ('3M', '3mo'),
    ('1M', '1mo'),
]
P10_AUTO_ANCHOR = 0.85
P10_DEFAULT_STARTUP_SPAN = 80.0
P10_MIN_REUSABLE_SPAN = 10.0
P10_AVG_PRICE_LABEL = 'Avg Price'
P10_SUPPORT_RESISTANCE_LABEL = 'Support/Resistance'
P10_FIB_RETRACEMENT_LABEL = 'Fib Retracement'
P10_INDICATOR_ORDER = ('Volume', 'RSI', '200 MA', P10_AVG_PRICE_LABEL, P10_SUPPORT_RESISTANCE_LABEL, P10_FIB_RETRACEMENT_LABEL)
P10_SR_PIVOT_WINDOW = 3
P10_SR_LEVEL_TOLERANCE_PCT = 0.006
P10_FIB_DEFAULT_LOOKBACK = 120
P10_FIB_MIN_LOOKBACK = 20
P10_FIB_MAX_LOOKBACK = 500
P10_FIB_LOOKBACK_CANDLES = P10_FIB_DEFAULT_LOOKBACK
P10_FIB_LEVELS = (
    (0.0, '0%'),
    (0.236, '23.6%'),
    (0.382, '38.2%'),
    (0.5, '50%'),
    (0.618, '61.8%'),
    (0.786, '78.6%'),
    (1.0, '100%'),
)
P10_DEFAULT_PLAYBACK_SPEED = '5x'
P10_PLAYBACK_SPEEDS = {
    '1x': (180, 1),
    '2x': (120, 2),
    '5x': (80, 5),
    '10x': (50, 10),
}
P10_COMPARE_MAX_WORKERS = 4
P10_MULTI_INTERVAL_MAX_WORKERS = 4
P10_MULTI_INTERVAL_RSI_OVERBOUGHT = 70.0
P10_MULTI_INTERVAL_RSI_OVERSOLD = 30.0
P10_MULTI_INTERVAL_MFI_OVERBOUGHT = 80.0
P10_MULTI_INTERVAL_MFI_OVERSOLD = 20.0
P10_COMPARE_LABEL_MIN_PIXEL_GAP = 18.0
P10_CACHE_PERIOD_DAY_MAP = {
    'd': 1.0,
    'wk': 7.0,
    'mo': 30.0,
    'y': 365.0,
}


class ChartsPageMixin:
    def _get_chart_data_service(self) -> ChartDataService:
        """Return the shared chart data service for this window session."""
        service = getattr(self, '_chart_data_service', None)
        cache_manager = self._get_cache_manager()
        if service is None or getattr(service, 'cache_manager', None) is not cache_manager:
            service = ChartDataService(cache_manager=cache_manager)
            self._chart_data_service = service
        return service

    def _chart_required_span_days(self, period: Any) -> float | None:
        """Convert one yfinance period string into approximate calendar days."""
        return self._get_chart_data_service().required_span_days(period)

    def _chart_cache_covers_period(self, df: Any, period: Any) -> bool:
        """Return whether one cached OHLCV frame is long enough for the requested period."""
        return self._get_chart_data_service().cache_covers_period(df, period)

    def _p10_normalize_datetime_index(self, values: Any) -> Any:
        """Normalize chart timestamps for safe asof merges across pandas resolutions."""
        return self._get_chart_data_service().normalize_datetime_index(values)

    def _chart_extract_symbol_frame(self, symbol: Any, df: Any) -> Any:
        """Select one symbol frame from a single- or multi-ticker yfinance result."""
        return self._get_chart_data_service().extract_symbol_frame(symbol, df)

    def _chart_normalize_frame(self, symbol: Any, df: Any) -> Any:
        """Normalize raw yfinance OHLCV data into one chart-ready frame."""
        return self._get_chart_data_service().normalize_frame(symbol, df)

    def _chart_load_cached_frame(self, symbol: Any, *, period: Any, interval: Any) -> Any:
        """Return one normalized cached frame when it is present and long enough."""
        frame, _cache_meta = self._get_chart_data_service().load_cached_frame(symbol, period=period, interval=interval)
        return frame

    def _chart_fetch_base_frame(self, symbol: Any, *, period: Any, interval: Any, force_refresh: bool=False) -> Any:
        """Fetch one normalized OHLCV frame, optionally bypassing cache."""
        payload = self._get_chart_data_service().fetch_base_frame_payload(
            symbol,
            period=period,
            interval=interval,
            force_refresh=force_refresh,
        )
        self._p10_last_chart_fetch_payload = payload
        frame = payload.get('df') if isinstance(payload, dict) else None
        if frame is None or frame.empty:
            meta = market_data_meta(payload)
            raise ValueError(meta.get('failure_reason') or f'No chart data returned for {symbol}.')
        return frame

    def _p10_on_show(self) -> None:
        """Refresh sidebar state when the Charts page is shown."""
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        self._p10_update_auto_button_style()
        self._p10_update_indicator_button_styles()
        self._p10_update_fib_controls()
        self._p10_update_timeframe_button_styles()
        self._p10_update_multi_interval_button_styles()
        self._p10_render_indicator_panels()
        self._p10_refresh_active_subtab()

    def init_page10(self) -> None:
        """Build the dedicated chart workstation page."""
        state = getattr(self, 'chart_page_state', load_chart_page_settings())
        self.p10_symbol = str(state.get('symbol', 'SPY') or 'SPY').upper()
        self.p10_timeframe_label = str(state.get('timeframe_label', '1 Day') or '1 Day')
        self.p10_compare_interval_label = str(state.get('compare_interval_label', '1 Day') or '1 Day')
        self.p10_compare_range_label = str(state.get('compare_range_label', '5Y') or '5Y')
        self.p10_custom_watchlist = list(state.get('watchlist', []))
        self.p10_compare_symbols = list(state.get('compare_symbols', []))
        self.p10_compare_presets = list(state.get('compare_presets', []))
        self.p10_multi_interval_labels = self._p10_initial_multi_interval_labels(state.get('multi_interval_labels', []))
        self.p10_active_indicators = list(state.get('indicators', ['Volume', '200 MA', P10_AVG_PRICE_LABEL]))
        self.p10_active_indicators = [indicator for indicator in P10_INDICATOR_ORDER if indicator in self.p10_active_indicators]
        self.p10_auto_follow = bool(state.get('auto', True))
        self.p10_playback_speed_label = str(state.get('playback_speed_label', P10_DEFAULT_PLAYBACK_SPEED) or P10_DEFAULT_PLAYBACK_SPEED)
        if self.p10_playback_speed_label not in P10_PLAYBACK_SPEEDS:
            self.p10_playback_speed_label = P10_DEFAULT_PLAYBACK_SPEED
        fib_settings = state.get('fib_settings', {})
        if not isinstance(fib_settings, dict):
            fib_settings = {}
        self.p10_fib_mode = str(fib_settings.get('mode', 'auto') or 'auto').strip().lower()
        if self.p10_fib_mode not in ('auto', 'manual'):
            self.p10_fib_mode = 'auto'
        try:
            self.p10_fib_lookback = int(fib_settings.get('lookback', P10_FIB_DEFAULT_LOOKBACK))
        except (TypeError, ValueError):
            self.p10_fib_lookback = P10_FIB_DEFAULT_LOOKBACK
        self.p10_fib_lookback = max(P10_FIB_MIN_LOOKBACK, min(P10_FIB_MAX_LOOKBACK, self.p10_fib_lookback))
        manual_by_context = fib_settings.get('manual_by_context', {})
        self.p10_fib_manual_by_context = dict(manual_by_context) if isinstance(manual_by_context, dict) else {}
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self.p10_fib_click_proxy = None
        self.p10_fib_start_handle = None
        self.p10_fib_end_handle = None
        self.p10_fib_pending_handle = None
        self._p10_fib_drag_guard = False
        self._p10_fib_lookback_sync = False
        self.p10_chart_df = None
        self.p10_compare_df = None
        self.p10_compare_interval = '1d'
        self.p10_compare_errors = []
        self._p10_chart_rows = []
        self.p10_chart_stats = {}
        self.p10_active_interval = '1d'
        self.p10_rsi_series = None
        self.p10_rsi_ma_series = None
        self.p10_ma200_series = None
        self.p10_crosshair_proxy = None
        self._p10_request_seq = 0
        self._p10_active_request = 0
        self._p10_compare_request_seq = 0
        self._p10_compare_active_request = 0
        self._p10_timeframe_buttons = {}
        self._p10_compare_timeframe_buttons = {}
        self._p10_multi_interval_buttons = {}
        self._p10_compare_range_combo = None
        self.p10_compare_preset_combo = None
        self._p10_indicator_buttons = {}
        self._p10_view_change_guard = False
        self._p10_watchlist_sync_guard = False
        self._p10_compare_list_sync_guard = False
        self._p10_compare_preset_sync_guard = False
        self._p10_compare_target_preset_name = None
        self._p10_manual_x_range = None
        self._p10_pending_x_range = None
        self._p10_overlay_items = {}
        self._p10_chart_dirty = False
        self._p10_compare_dirty = True
        self._p10_compare_series_cache = {}
        self._p10_compare_plot_items = {}
        self._p10_compare_label_items = {}
        self._p10_compare_zero_line = None
        self._p10_compare_render_signature = None
        self._p10_compare_executor = ThreadPoolExecutor(max_workers=P10_COMPARE_MAX_WORKERS)
        self._p10_multi_interval_executor = ThreadPoolExecutor(max_workers=P10_MULTI_INTERVAL_MAX_WORKERS)
        self._p10_multi_interval_request_token = 0
        self._p10_multi_interval_cache = {}
        self._p10_playback_timer = QTimer(self)
        self._p10_playback_timer.timeout.connect(self._p10_step_playback)
        self._p10_playback_running = False
        self._p10_playback_index = 0
        self._p10_playback_slider_sync = False
        self.p10_multi_interval_frames = {}
        self.p10_candle_item = None
        self.p10_ma_line_item = None
        self.p10_avg_cost_line = None
        self.p10_last_price_line = None
        self.p10_volume_item = None
        self.p10_rsi_line_item = None
        self.p10_rsi_ma_line_item = None
        self.p10_rsi_upper_line = None
        self.p10_rsi_lower_line = None
        self.p10_support_line = None
        self.p10_resistance_line = None
        self.p10_support_label_item = None
        self.p10_resistance_label_item = None
        self.p10_support_resistance_levels = None
        self.p10_fib_line_items = []
        self.p10_fib_label_items = []
        self.p10_fib_anchor_item = None
        self.p10_fib_levels = None
        self._p10_fib_mode_group = QButtonGroup(self)
        self._p10_fib_mode_group.setExclusive(True)
        self._p10_timeframe_group = QButtonGroup(self)
        self._p10_timeframe_group.setExclusive(True)
        self._p10_compare_timeframe_group = QButtonGroup(self)
        self._p10_compare_timeframe_group.setExclusive(True)
        self._p10_timeframe_map = {label: (period, interval) for label, period, interval in P10_MAIN_TIMEFRAME_OPTIONS}
        self._p10_multi_interval_timeframe_map = {
            label: (period, interval) for label, period, interval in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS
        }
        self._p10_compare_interval_map = {label: interval for label, interval in P10_COMPARE_INTERVAL_OPTIONS}
        self._p10_compare_range_map = {label: period for label, period in P10_COMPARE_RANGE_OPTIONS}
        if self.p10_timeframe_label not in self._p10_timeframe_map:
            self.p10_timeframe_label = '1 Day'
        if self.p10_compare_interval_label not in self._p10_compare_interval_map:
            self.p10_compare_interval_label = '1 Day'
        if self.p10_compare_range_label not in self._p10_compare_range_map:
            self.p10_compare_range_label = '5Y'
        layout = QVBoxLayout(self.page10)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.p10_tabs = QTabWidget()
        self.p10_tabs.setDocumentMode(True)
        self.p10_chart_tab = QWidget()
        self.p10_multi_tab = QWidget()
        self.p10_compare_tab = QWidget()
        self.p10_tabs.addTab(self.p10_chart_tab, 'Main')
        self.p10_tabs.addTab(self.p10_multi_tab, 'Multi Charts')
        self.p10_tabs.addTab(self.p10_compare_tab, 'Compare')
        self.p10_tabs.currentChanged.connect(self._p10_on_subtab_changed)
        layout.addWidget(self.p10_tabs, 1)
        self._p10_build_chart_tab()
        self.init_page11(container=self.p10_multi_tab, show_title=False)
        self._p10_build_compare_tab()
        self.p10_tabs.setCurrentIndex(0)
        self._p10_update_timeframe_button_styles()
        self._p10_update_auto_button_style()
        self._p10_update_indicator_button_styles()
        self._p10_update_fib_controls()
        self._p10_update_multi_interval_button_styles()
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        self._p10_render_indicator_panels()
        self.p10_crosshair_proxy = pg.SignalProxy(self.p10_main_plot.scene().sigMouseMoved, rateLimit=30, slot=self._p10_on_mouse_moved)
        self.p10_fib_click_proxy = pg.SignalProxy(self.p10_main_plot.scene().sigMouseClicked, rateLimit=20, slot=self._p10_on_chart_clicked)
        self._apply_charts_page_theme()

    def _p10_build_chart_tab(self) -> None:
        """Build the original single-symbol chart workstation subtab."""
        layout = QVBoxLayout(self.p10_chart_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel('<b>Charts</b>')
        self.set_theme_role(title, 'page_title')
        self.p10_symbol_input = QLineEdit(self.p10_symbol)
        self.p10_symbol_input.setPlaceholderText('Ticker')
        self.p10_symbol_input.setFixedWidth(110)
        self.p10_symbol_input.returnPressed.connect(self._p10_load_from_input)
        self.p10_load_btn = QPushButton('Load')
        self.set_theme_variant(self.p10_load_btn, 'accent')
        self.p10_load_btn.clicked.connect(self._p10_load_from_input)
        self.p10_auto_btn = QPushButton('Auto')
        self.p10_auto_btn.setCheckable(True)
        self.p10_auto_btn.clicked.connect(self._p10_toggle_auto_follow)
        toolbar.addWidget(title)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.p10_symbol_input)
        toolbar.addWidget(self.p10_load_btn)
        toolbar.addSpacing(16)
        for label, _, _ in P10_MAIN_TIMEFRAME_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(partial(self._p10_set_timeframe, label))
            self._p10_timeframe_group.addButton(btn)
            self._p10_timeframe_buttons[label] = btn
            toolbar.addWidget(btn)
        toolbar.addStretch()
        toolbar.addWidget(self.p10_auto_btn)
        layout.addLayout(toolbar)

        indicator_row = QHBoxLayout()
        indicator_label = QLabel('Indicators')
        self.set_theme_role(indicator_label, 'muted')
        indicator_row.addWidget(indicator_label)
        indicator_row.addSpacing(8)
        for name in P10_INDICATOR_ORDER:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.clicked.connect(partial(self._p10_toggle_indicator, name))
            self._p10_indicator_buttons[name] = btn
            indicator_row.addWidget(btn)
        indicator_row.addStretch()
        layout.addLayout(indicator_row)

        self.p10_fib_controls_widget = QWidget()
        fib_row = QHBoxLayout(self.p10_fib_controls_widget)
        fib_row.setContentsMargins(0, 0, 0, 0)
        fib_row.setSpacing(6)
        fib_label = QLabel('Fib')
        self.set_theme_role(fib_label, 'muted')
        self.p10_fib_auto_btn = QPushButton('Auto')
        self.p10_fib_auto_btn.setCheckable(True)
        self.p10_fib_auto_btn.clicked.connect(lambda checked=False: self._p10_set_fib_mode('auto'))
        self.p10_fib_manual_btn = QPushButton('Manual')
        self.p10_fib_manual_btn.setCheckable(True)
        self.p10_fib_manual_btn.clicked.connect(lambda checked=False: self._p10_set_fib_mode('manual'))
        self._p10_fib_mode_group.addButton(self.p10_fib_auto_btn)
        self._p10_fib_mode_group.addButton(self.p10_fib_manual_btn)
        fib_lookback_label = QLabel('Lookback')
        self.set_theme_role(fib_lookback_label, 'muted')
        self.p10_fib_lookback_spin = QSpinBox()
        self.p10_fib_lookback_spin.setRange(P10_FIB_MIN_LOOKBACK, P10_FIB_MAX_LOOKBACK)
        self.p10_fib_lookback_spin.setValue(self.p10_fib_lookback)
        self.p10_fib_lookback_spin.setSuffix(' candles')
        self.p10_fib_lookback_spin.setMinimumWidth(118)
        self.p10_fib_lookback_spin.valueChanged.connect(self._p10_on_fib_lookback_changed)
        self.p10_fib_lookback_slider = QSlider(Qt.Orientation.Horizontal)
        self.p10_fib_lookback_slider.setRange(P10_FIB_MIN_LOOKBACK, P10_FIB_MAX_LOOKBACK)
        self.p10_fib_lookback_slider.setValue(self.p10_fib_lookback)
        self.p10_fib_lookback_slider.setTickInterval(40)
        self.p10_fib_lookback_slider.setSingleStep(1)
        self.p10_fib_lookback_slider.setPageStep(20)
        self.p10_fib_lookback_slider.setMinimumWidth(150)
        self.p10_fib_lookback_slider.valueChanged.connect(self._p10_on_fib_lookback_slider_changed)
        self.p10_fib_set_anchors_btn = QPushButton('Set Anchors')
        self.p10_fib_set_anchors_btn.clicked.connect(self._p10_start_fib_anchor_capture)
        self.p10_fib_reset_auto_btn = QPushButton('Reset Auto')
        self.p10_fib_reset_auto_btn.clicked.connect(self._p10_reset_fib_auto)
        self.p10_fib_status_label = QLabel('')
        self.set_theme_role(self.p10_fib_status_label, 'muted')
        fib_row.addWidget(fib_label)
        fib_row.addSpacing(4)
        fib_row.addWidget(self.p10_fib_auto_btn)
        fib_row.addWidget(self.p10_fib_manual_btn)
        fib_row.addSpacing(8)
        fib_row.addWidget(fib_lookback_label)
        fib_row.addWidget(self.p10_fib_lookback_spin)
        fib_row.addWidget(self.p10_fib_lookback_slider)
        fib_row.addWidget(self.p10_fib_set_anchors_btn)
        fib_row.addWidget(self.p10_fib_reset_auto_btn)
        fib_row.addWidget(self.p10_fib_status_label, 1)
        layout.addWidget(self.p10_fib_controls_widget)

        playback_row = QHBoxLayout()
        playback_label = QLabel('Playback')
        self.set_theme_role(playback_label, 'muted')
        self.p10_playback_btn = QPushButton('Play')
        self.p10_playback_btn.setMinimumHeight(24)
        self.p10_playback_btn.clicked.connect(self._p10_toggle_playback)
        self.p10_playback_restart_btn = QPushButton('Restart')
        self.p10_playback_restart_btn.setMinimumHeight(24)
        self.p10_playback_restart_btn.clicked.connect(self._p10_restart_playback)
        self.p10_playback_speed_combo = QComboBox()
        self.p10_playback_speed_combo.setMinimumHeight(24)
        self.p10_playback_speed_combo.setFixedWidth(72)
        for speed_label in P10_PLAYBACK_SPEEDS:
            self.p10_playback_speed_combo.addItem(speed_label)
        speed_index = self.p10_playback_speed_combo.findText(self.p10_playback_speed_label)
        self.p10_playback_speed_combo.setCurrentIndex(speed_index if speed_index >= 0 else 0)
        self.p10_playback_speed_combo.currentTextChanged.connect(self._p10_on_playback_speed_changed)
        self.p10_playback_slider = QSlider(Qt.Orientation.Horizontal)
        self.p10_playback_slider.setMinimum(0)
        self.p10_playback_slider.setMaximum(0)
        self.p10_playback_slider.valueChanged.connect(self._p10_on_playback_slider_changed)
        self.p10_playback_label = QLabel('-- / --')
        self.p10_playback_label.setMinimumWidth(150)
        self.set_theme_role(self.p10_playback_label, 'muted')
        playback_row.addWidget(playback_label)
        playback_row.addSpacing(8)
        playback_row.addWidget(self.p10_playback_btn)
        playback_row.addWidget(self.p10_playback_restart_btn)
        playback_row.addWidget(self.p10_playback_speed_combo)
        playback_row.addWidget(self.p10_playback_slider, 1)
        playback_row.addWidget(self.p10_playback_label)
        layout.addLayout(playback_row)
        self._p10_set_playback_enabled(False)

        info_strip = QHBoxLayout()
        self.p10_symbol_label = QLabel(self.p10_symbol)
        self.p10_symbol_label.setStyleSheet('font-size: 22px; font-weight: bold;')
        self.p10_price_label = QLabel('--')
        self.p10_price_label.setMinimumHeight(30)
        self.p10_price_label.setMinimumWidth(92)
        self.p10_price_label.setStyleSheet('font-size: 20px; font-weight: bold;')
        self.p10_change_label = QLabel('--')
        self.p10_change_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.p10_position_label = QLabel('Avg --  Gain --')
        self.p10_position_label.setStyleSheet('font-size: 12px; font-weight: bold;')
        self.p10_ohlc_label = QLabel('O --  H --  L --  C --')
        self.p10_ohlc_label.setMinimumWidth(220)
        self.p10_ohlc_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.p10_ohlc_label.setStyleSheet('font-size: 12px;')
        self.p10_indicator_values_label = QLabel('')
        self.p10_indicator_values_label.setMinimumWidth(260)
        self.p10_indicator_values_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.p10_indicator_values_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p10_indicator_values_label.setStyleSheet('font-size: 12px;')
        self.p10_status_label = QLabel('Ready')
        self.p10_status_label.setMinimumWidth(180)
        self.p10_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.p10_status_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.set_theme_role(self.p10_status_label, 'status_muted')
        info_strip.addWidget(self.p10_symbol_label)
        info_strip.addSpacing(16)
        info_strip.addWidget(self.p10_price_label)
        info_strip.addWidget(self.p10_change_label)
        info_strip.addWidget(self.p10_position_label)
        info_strip.addSpacing(20)
        info_strip.addWidget(self.p10_ohlc_label)
        info_strip.addWidget(self.p10_indicator_values_label, 2)
        info_strip.addWidget(self.p10_status_label)
        layout.addLayout(info_strip)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(6)
        self.p10_panels = QSplitter(Qt.Orientation.Vertical)
        self.p10_chart_axis = DateAxisItem(orientation='bottom')
        self.p10_main_plot = pg.PlotWidget(axisItems={'bottom': self.p10_chart_axis})
        self.p10_main_plot.showGrid(x=True, y=True, alpha=0.15)
        self.p10_main_plot.getPlotItem().setMenuEnabled(False)
        self.p10_main_plot.getPlotItem().hideAxis('left')
        self.p10_main_plot.getPlotItem().showAxis('right')
        self.p10_main_plot.getPlotItem().vb.sigXRangeChanged.connect(self._p10_on_x_range_changed)
        self.p10_main_plot.getPlotItem().vb.sigRangeChanged.connect(self._p10_refresh_overlay_positions)
        self.p10_volume_axis = DateAxisItem(orientation='bottom')
        self.p10_volume_plot = pg.PlotWidget(axisItems={'bottom': self.p10_volume_axis})
        self.p10_volume_plot.showGrid(x=True, y=False, alpha=0.1)
        self.p10_volume_plot.getPlotItem().setMenuEnabled(False)
        self.p10_volume_plot.getPlotItem().hideAxis('left')
        self.p10_volume_plot.getPlotItem().showAxis('right')
        self.p10_volume_plot.setMaximumHeight(160)
        self.p10_volume_plot.setXLink(self.p10_main_plot)
        self.p10_volume_plot.getPlotItem().vb.sigRangeChanged.connect(self._p10_refresh_overlay_positions)
        self.p10_rsi_axis = DateAxisItem(orientation='bottom')
        self.p10_rsi_plot = pg.PlotWidget(axisItems={'bottom': self.p10_rsi_axis})
        self.p10_rsi_plot.showGrid(x=True, y=True, alpha=0.1)
        self.p10_rsi_plot.getPlotItem().setMenuEnabled(False)
        self.p10_rsi_plot.getPlotItem().hideAxis('left')
        self.p10_rsi_plot.getPlotItem().showAxis('right')
        self.p10_rsi_plot.setMaximumHeight(160)
        self.p10_rsi_plot.setXLink(self.p10_main_plot)
        self.p10_rsi_plot.getPlotItem().vb.sigRangeChanged.connect(self._p10_refresh_overlay_positions)
        self.p10_panels.addWidget(self.p10_main_plot)
        self.p10_panels.addWidget(self.p10_volume_plot)
        self.p10_panels.addWidget(self.p10_rsi_plot)
        self.p10_panels.setStretchFactor(0, 6)
        self.p10_panels.setStretchFactor(1, 2)
        self.p10_panels.setStretchFactor(2, 2)
        chart_layout.addWidget(self.p10_panels, 1)
        body_splitter.addWidget(chart_container)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        portfolio_title = QLabel('Portfolio')
        self.set_theme_role(portfolio_title, 'section_title')
        portfolio_help = QLabel('Read-only symbols from your Portfolio page.')
        self.set_theme_role(portfolio_help, 'muted')
        portfolio_help.setWordWrap(True)
        self.p10_portfolio_list = QListWidget()
        self.p10_portfolio_list.currentItemChanged.connect(self._p10_watchlist_selection_changed)
        sidebar_layout.addWidget(portfolio_title)
        sidebar_layout.addWidget(portfolio_help)
        sidebar_layout.addWidget(self.p10_portfolio_list, 1)
        body_splitter.addWidget(sidebar)
        body_splitter.setStretchFactor(0, 5)
        body_splitter.setStretchFactor(1, 2)
        layout.addWidget(body_splitter, 1)

    def _p10_build_multi_interval_tab(self) -> None:
        """Build the multi-interval subtab for one symbol."""
        layout = QVBoxLayout(self.p10_multi_interval_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel('<b>Multi Intervals</b>')
        self.set_theme_role(title, 'page_title')
        self.p10_multi_interval_symbol_input = QLineEdit(self.p10_symbol)
        self.p10_multi_interval_symbol_input.setPlaceholderText('Ticker')
        self.p10_multi_interval_symbol_input.setFixedWidth(120)
        self.p10_multi_interval_symbol_input.returnPressed.connect(self._p10_load_multi_interval_from_input)
        self.p10_multi_interval_load_btn = QPushButton('Load')
        self.set_theme_variant(self.p10_multi_interval_load_btn, 'accent')
        self.p10_multi_interval_load_btn.clicked.connect(self._p10_load_multi_interval_from_input)
        toolbar.addWidget(title)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.p10_multi_interval_symbol_input)
        toolbar.addWidget(self.p10_multi_interval_load_btn)
        toolbar.addSpacing(16)
        interval_label = QLabel('Timeframes')
        self.set_theme_role(interval_label, 'muted')
        toolbar.addWidget(interval_label)
        for label, _, _ in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(partial(self._p10_toggle_multi_interval, label))
            self._p10_multi_interval_buttons[label] = btn
            toolbar.addWidget(btn)
        self.p10_multi_interval_all_btn = QPushButton('All')
        self.set_theme_variant(self.p10_multi_interval_all_btn, 'accent')
        self.p10_multi_interval_all_btn.clicked.connect(self._p10_select_all_multi_intervals)
        toolbar.addWidget(self.p10_multi_interval_all_btn)
        self.p10_multi_interval_clear_btn = QPushButton('Clear')
        self.p10_multi_interval_clear_btn.clicked.connect(self._p10_clear_multi_interval_selection)
        toolbar.addWidget(self.p10_multi_interval_clear_btn)
        toolbar.addStretch()
        self.p10_multi_interval_status_label = QLabel('Loading available timeframes.')
        self.set_theme_role(self.p10_multi_interval_status_label, 'status_muted')
        toolbar.addWidget(self.p10_multi_interval_status_label)
        layout.addLayout(toolbar)

        summary_row = QHBoxLayout()
        self.p10_multi_interval_symbol_label = QLabel(self.p10_symbol)
        self.p10_multi_interval_symbol_label.setStyleSheet('font-size: 22px; font-weight: bold;')
        self.p10_multi_interval_selection_label = QLabel('Showing RSI, MFI, and MACD panels for the selected timeframes.')
        self.set_theme_role(self.p10_multi_interval_selection_label, 'muted')
        summary_row.addWidget(self.p10_multi_interval_symbol_label)
        summary_row.addSpacing(14)
        summary_row.addWidget(self.p10_multi_interval_selection_label, 1)
        layout.addLayout(summary_row)

        self.p10_multi_interval_empty_label = QLabel('Select one or more timeframes to load RSI, MFI, and MACD panels.')
        self.set_theme_role(self.p10_multi_interval_empty_label, 'muted')
        self.p10_multi_interval_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.p10_multi_interval_empty_label)

        self.p10_multi_interval_scroll = QScrollArea()
        self.p10_multi_interval_scroll.setWidgetResizable(True)
        self.p10_multi_interval_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p10_multi_interval_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p10_multi_interval_panel_host = QWidget()
        self.p10_multi_interval_panel_layout = QVBoxLayout(self.p10_multi_interval_panel_host)
        self.p10_multi_interval_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.p10_multi_interval_panel_layout.setSpacing(10)
        self.p10_multi_interval_panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.p10_multi_interval_scroll.setWidget(self.p10_multi_interval_panel_host)
        self.p10_multi_interval_panel_widgets = {}
        layout.addWidget(self.p10_multi_interval_scroll, 1)

    def _p10_build_compare_tab(self) -> None:
        """Build the multi-symbol comparison subtab."""
        layout = QVBoxLayout(self.p10_compare_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel('<b>Compare</b>')
        self.set_theme_role(title, 'page_title')
        self.p10_compare_input = QLineEdit()
        self.p10_compare_input.setPlaceholderText('Ticker')
        self.p10_compare_input.setFixedWidth(120)
        self.p10_compare_input.returnPressed.connect(self._p10_add_compare_symbol)
        self.p10_compare_add_btn = QPushButton('Add')
        self.set_theme_variant(self.p10_compare_add_btn, 'accent')
        self.p10_compare_add_btn.clicked.connect(self._p10_add_compare_symbol)
        self.p10_compare_remove_btn = QPushButton('Remove')
        self.set_theme_variant(self.p10_compare_remove_btn, 'danger')
        self.p10_compare_remove_btn.clicked.connect(self._p10_remove_compare_symbol)
        toolbar.addWidget(title)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.p10_compare_input)
        toolbar.addWidget(self.p10_compare_add_btn)
        toolbar.addWidget(self.p10_compare_remove_btn)
        toolbar.addSpacing(16)
        interval_label = QLabel('Interval')
        self.set_theme_role(interval_label, 'muted')
        toolbar.addWidget(interval_label)
        for label, _ in P10_COMPARE_INTERVAL_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(partial(self._p10_set_compare_interval, label))
            self._p10_compare_timeframe_group.addButton(btn)
            self._p10_compare_timeframe_buttons[label] = btn
            toolbar.addWidget(btn)
        toolbar.addSpacing(10)
        range_label = QLabel('Range')
        self.set_theme_role(range_label, 'muted')
        toolbar.addWidget(range_label)
        self.p10_compare_range_combo = QComboBox()
        self.p10_compare_range_combo.setMinimumWidth(96)
        for label, period in P10_COMPARE_RANGE_OPTIONS:
            self.p10_compare_range_combo.addItem(label, period)
        self.p10_compare_range_combo.currentTextChanged.connect(self._p10_set_compare_range)
        toolbar.addWidget(self.p10_compare_range_combo)
        toolbar.addSpacing(10)
        preset_label = QLabel('Presets')
        self.set_theme_role(preset_label, 'muted')
        toolbar.addWidget(preset_label)
        self.p10_compare_preset_combo = QComboBox()
        self.p10_compare_preset_combo.setMinimumWidth(170)
        self.p10_compare_preset_combo.setPlaceholderText('Select preset')
        self.p10_compare_preset_combo.currentIndexChanged.connect(self._p10_on_compare_preset_selected)
        toolbar.addWidget(self.p10_compare_preset_combo)
        self.p10_compare_save_preset_btn = QPushButton('New Preset')
        self.set_theme_variant(self.p10_compare_save_preset_btn, 'accent')
        self.p10_compare_save_preset_btn.clicked.connect(self._p10_save_compare_preset)
        toolbar.addWidget(self.p10_compare_save_preset_btn)
        self.p10_compare_update_preset_btn = QPushButton('Update')
        self.set_theme_variant(self.p10_compare_update_preset_btn, 'accent')
        self.p10_compare_update_preset_btn.clicked.connect(self._p10_update_compare_preset)
        toolbar.addWidget(self.p10_compare_update_preset_btn)
        self.p10_compare_delete_preset_btn = QPushButton('Delete')
        self.set_theme_variant(self.p10_compare_delete_preset_btn, 'danger')
        self.p10_compare_delete_preset_btn.clicked.connect(self._p10_delete_compare_preset)
        toolbar.addWidget(self.p10_compare_delete_preset_btn)
        toolbar.addStretch()
        self.p10_compare_status_label = QLabel('Add symbols to compare.')
        self.set_theme_role(self.p10_compare_status_label, 'status_muted')
        toolbar.addWidget(self.p10_compare_status_label)
        layout.addLayout(toolbar)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        compare_title = QLabel('Symbols')
        self.set_theme_role(compare_title, 'section_title')
        compare_help = QLabel('Saved comparison tickers. Returns are rebased to the selected compare range start.')
        self.set_theme_role(compare_help, 'muted')
        compare_help.setWordWrap(True)
        self.p10_compare_list = QListWidget()
        self.p10_compare_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        sidebar_layout.addWidget(compare_title)
        sidebar_layout.addWidget(compare_help)
        sidebar_layout.addWidget(self.p10_compare_list, 1)
        body_splitter.addWidget(sidebar)

        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(6)
        self.p10_compare_empty_label = QLabel('Add one or more tickers to compare normalized performance.')
        self.set_theme_role(self.p10_compare_empty_label, 'muted')
        self.p10_compare_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p10_compare_axis = DateAxisItem(orientation='bottom')
        self.p10_compare_percent_axis = PercentAxisItem(orientation='right')
        self.p10_compare_plot = pg.PlotWidget(axisItems={'bottom': self.p10_compare_axis, 'right': self.p10_compare_percent_axis})
        self.p10_compare_plot.showGrid(x=True, y=True, alpha=0.15)
        self.p10_compare_plot.getPlotItem().setMenuEnabled(False)
        self.p10_compare_plot.getPlotItem().hideAxis('left')
        self.p10_compare_plot.getPlotItem().showAxis('right')
        compare_plot_item = self.p10_compare_plot.getPlotItem()
        try:
            compare_plot_item.setClipToView(True)
        except Exception:
            pass
        try:
            compare_plot_item.setDownsampling(auto=True, method='peak')
        except Exception:
            pass
        chart_layout.addWidget(self.p10_compare_empty_label)
        chart_layout.addWidget(self.p10_compare_plot, 1)
        body_splitter.addWidget(chart_container)
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 5)
        layout.addWidget(body_splitter, 1)
        self._p10_compare_zero_line = pg.InfiniteLine(
            pos=0,
            angle=0,
            pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine),
        )
        self.p10_compare_plot.addItem(self._p10_compare_zero_line)
        self._p10_compare_zero_line.hide()

    def _p10_set_status(self, text: Any, status: Any='muted') -> None:
        """Set charts page status text."""
        self.set_status_text(self.p10_status_label, text, status=str(status))
        if self._p10_active_subtab_key() == 'chart' and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _p10_set_compare_status(self, text: Any, status: Any='muted') -> None:
        """Set compare-subtab status text."""
        self.set_status_text(self.p10_compare_status_label, text, status=str(status))
        if self._p10_active_subtab_key() == 'compare' and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _p10_set_multi_interval_status(self, text: Any, status: Any='muted') -> None:
        """Set multi-interval subtab status text."""
        self.set_status_text(self.p10_multi_interval_status_label, text, status=str(status))
        if self._p10_active_subtab_key() == 'multiintervals' and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _p10_sync_active_status_to_status_bar(self) -> None:
        """Mirror the visible subtab status label into the shared window status bar."""
        if not hasattr(self, 'status_bar'):
            return
        active_key = self._p10_active_subtab_key()
        if active_key == 'compare':
            source = self.p10_compare_status_label
        elif active_key == 'multiintervals':
            source = self.p10_multi_interval_status_label
        elif active_key == 'multicharts' and hasattr(self, '_mc_status'):
            source = self._mc_status
        else:
            source = self.p10_status_label
        self.set_status_text(
            self.status_bar,
            source.text(),
            status=str(source.property('bt_status') or 'muted'),
        )

    def _p10_active_subtab_key(self) -> str:
        """Return the visible Charts-page subtab key."""
        if not hasattr(self, 'p10_tabs'):
            return 'chart'
        current = self.p10_tabs.currentWidget()
        if current is getattr(self, 'p10_compare_tab', None):
            return 'compare'
        if current is getattr(self, 'p10_multi_interval_tab', None):
            return 'multiintervals'
        if current is getattr(self, 'p10_multi_tab', None):
            return 'multicharts'
        return 'chart'

    def _p10_on_subtab_changed(self, _: int) -> None:
        """Refresh whichever Charts subtab becomes visible."""
        self._p10_refresh_active_subtab()
        self._p10_sync_active_status_to_status_bar()

    def _p10_save_state(self) -> None:
        """Persist charts page settings."""
        self.chart_page_state = save_chart_page_settings({
            'symbol': self.p10_symbol,
            'timeframe_label': self.p10_timeframe_label,
            'compare_interval_label': self.p10_compare_interval_label,
            'compare_range_label': self.p10_compare_range_label,
            'watchlist': self.p10_custom_watchlist,
            'compare_symbols': self.p10_compare_symbols,
            'compare_presets': self.p10_compare_presets,
            'multi_interval_labels': self.p10_multi_interval_labels,
            'indicators': self.p10_active_indicators,
            'auto': self.p10_auto_follow,
            'playback_speed_label': self.p10_playback_speed_label,
            'fib_settings': self._p10_fib_settings_payload(),
        })
        self.p10_compare_presets = list(self.chart_page_state.get('compare_presets', self.p10_compare_presets))
        fib_settings = self.chart_page_state.get('fib_settings', {})
        if isinstance(fib_settings, dict):
            self.p10_fib_mode = str(fib_settings.get('mode', self.p10_fib_mode) or self.p10_fib_mode)
            self.p10_fib_lookback = int(fib_settings.get('lookback', self.p10_fib_lookback) or self.p10_fib_lookback)
            manual_by_context = fib_settings.get('manual_by_context', self.p10_fib_manual_by_context)
            if isinstance(manual_by_context, dict):
                self.p10_fib_manual_by_context = dict(manual_by_context)

    def _p10_fib_settings_payload(self) -> dict[str, Any]:
        """Return the persistable Fibonacci settings payload."""
        return {
            'mode': self.p10_fib_mode if self.p10_fib_mode in ('auto', 'manual') else 'auto',
            'lookback': int(max(P10_FIB_MIN_LOOKBACK, min(P10_FIB_MAX_LOOKBACK, int(self.p10_fib_lookback)))),
            'manual_by_context': dict(getattr(self, 'p10_fib_manual_by_context', {}) or {}),
        }

    def _p10_fib_context_key(self, symbol: Any=None, timeframe_label: Any=None) -> str:
        """Return the current per-symbol/timeframe Fibonacci settings key."""
        symbol_text = str(symbol if symbol is not None else getattr(self, 'p10_symbol', '')).upper().strip()
        timeframe_text = str(timeframe_label if timeframe_label is not None else getattr(self, 'p10_timeframe_label', '')).strip()
        return f'{symbol_text}|{timeframe_text}' if symbol_text and timeframe_text else ''

    def _p10_refresh_active_subtab(self, *, force: bool=False) -> None:
        """Refresh the currently visible Charts subtab."""
        active_key = self._p10_active_subtab_key()
        if active_key == 'compare':
            self._p10_refresh_compare_view(force=force)
            return
        if active_key == 'multiintervals':
            self._p10_refresh_multi_interval_views(force=force)
            return
        if active_key == 'multicharts':
            self._mc_on_show()
            return
        if force or self._p10_chart_dirty or self.p10_chart_df is None:
            self._p10_chart_dirty = False
            self._p10_refresh_chart()
            return
        self._p10_sync_active_status_to_status_bar()

    def _p10_refresh_compare_symbol_list(self) -> None:
        """Rebuild the saved compare-symbol list."""
        if not hasattr(self, 'p10_compare_list'):
            return
        current_item = self.p10_compare_list.currentItem()
        current_symbol = current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else ''
        self._p10_compare_list_sync_guard = True
        try:
            self.p10_compare_list.clear()
            selected_row = 0
            for row, symbol in enumerate(self.p10_compare_symbols):
                item = QListWidgetItem(symbol)
                item.setData(Qt.ItemDataRole.UserRole, symbol)
                item.setForeground(QColor(self.theme_series_color(row)))
                self.p10_compare_list.addItem(item)
                if symbol == current_symbol:
                    selected_row = row
            if self.p10_compare_list.count():
                self.p10_compare_list.setCurrentRow(selected_row)
        finally:
            self._p10_compare_list_sync_guard = False
        self._p10_refresh_compare_preset_controls()

    def _p10_normalize_compare_symbol_list(self, values: Any) -> list[str]:
        """Normalize compare symbols into an uppercase unique list."""
        normalized = []
        for value in list(values or []):
            symbol = str(value or '').upper().strip()
            if symbol and symbol not in normalized:
                normalized.append(symbol)
        return normalized

    def _p10_compare_preset_key(self, value: Any) -> str:
        """Build a stable case-insensitive lookup key for compare preset names."""
        return str(value or '').strip().casefold()

    def _p10_compare_state_signature(
        self,
        symbols: Any=None,
        interval_label: Any=None,
        range_label: Any=None,
    ) -> tuple[tuple[str, ...], str, str]:
        """Build a canonical compare-state signature for preset matching."""
        normalized_symbols = tuple(self._p10_normalize_compare_symbol_list(
            self.p10_compare_symbols if symbols is None else symbols,
        ))
        normalized_interval = str(
            interval_label if interval_label is not None else self.p10_compare_interval_label
        ).strip()
        if normalized_interval not in self._p10_compare_interval_map:
            normalized_interval = '1 Day'
        normalized_range = str(
            range_label if range_label is not None else self.p10_compare_range_label
        ).strip().upper()
        if normalized_range not in self._p10_compare_range_map:
            normalized_range = '5Y'
        return (normalized_symbols, normalized_interval, normalized_range)

    def _p10_find_compare_preset(self, name: Any) -> Any:
        """Return one saved compare preset by name."""
        target_key = self._p10_compare_preset_key(name)
        if not target_key:
            return None
        for preset in list(self.p10_compare_presets or []):
            preset_name = str((preset or {}).get('name', '')).strip()
            if preset_name and self._p10_compare_preset_key(preset_name) == target_key:
                return preset
        return None

    def _p10_compare_preset_signature(self, preset: Any) -> tuple[tuple[str, ...], str, str]:
        """Build one canonical preset snapshot signature for compare matching."""
        return self._p10_compare_state_signature(
            (preset or {}).get('symbols', []),
            (preset or {}).get('interval_label'),
            (preset or {}).get('range_label'),
        )

    def _p10_matching_compare_preset_name(self, *, preferred_name: Any=None) -> str | None:
        """Return the preset whose snapshot matches the current compare state."""
        target_signature = self._p10_compare_state_signature()
        preferred_preset = self._p10_find_compare_preset(preferred_name)
        if preferred_preset is not None and self._p10_compare_preset_signature(preferred_preset) == target_signature:
            return str((preferred_preset or {}).get('name', '')).strip() or None
        for preset in list(self.p10_compare_presets or []):
            preset_name = str((preset or {}).get('name', '')).strip()
            if (not preset_name) or self._p10_compare_preset_signature(preset) != target_signature:
                continue
            return preset_name
        return None

    def _p10_refresh_compare_preset_controls(self, *, preserve_target: bool=True) -> None:
        """Rebuild compare preset widgets and align them to the current compare state."""
        combo = getattr(self, 'p10_compare_preset_combo', None)
        if combo is None:
            return
        preferred_name = str(self._p10_compare_target_preset_name or '').strip() if preserve_target else ''
        matching_name = self._p10_matching_compare_preset_name(preferred_name=preferred_name)
        if matching_name:
            self._p10_compare_target_preset_name = matching_name
        elif preserve_target:
            target_name = str(self._p10_compare_target_preset_name or '').strip()
            self._p10_compare_target_preset_name = target_name if self._p10_find_compare_preset(target_name) is not None else None
        else:
            self._p10_compare_target_preset_name = None
        self._p10_compare_preset_sync_guard = True
        try:
            combo.clear()
            selected_name = matching_name or ''
            for preset in list(self.p10_compare_presets or []):
                preset_name = str((preset or {}).get('name', '')).strip()
                if preset_name:
                    combo.addItem(preset_name, preset_name)
            selected_index = combo.findData(selected_name) if selected_name else -1
            combo.setCurrentIndex(selected_index if selected_index >= 0 else -1)
        finally:
            self._p10_compare_preset_sync_guard = False
        target_name = str(self._p10_compare_target_preset_name or '').strip()
        has_compare_symbols = bool(self.p10_compare_symbols)
        if hasattr(self, 'p10_compare_save_preset_btn'):
            self.p10_compare_save_preset_btn.setEnabled(has_compare_symbols)
        if hasattr(self, 'p10_compare_update_preset_btn'):
            self.p10_compare_update_preset_btn.setEnabled(has_compare_symbols and bool(target_name))
            self.p10_compare_update_preset_btn.setToolTip(
                f'Update "{target_name}" to match the current compare setup.' if target_name else ''
            )
        if hasattr(self, 'p10_compare_delete_preset_btn'):
            self.p10_compare_delete_preset_btn.setEnabled(bool(target_name))
            self.p10_compare_delete_preset_btn.setToolTip(
                f'Delete compare preset "{target_name}".' if target_name else ''
            )

    def _p10_on_compare_preset_selected(self, _: int) -> None:
        """Apply the selected compare preset immediately."""
        if self._p10_compare_preset_sync_guard:
            return
        combo = getattr(self, 'p10_compare_preset_combo', None)
        preset_name = str(combo.currentData() if combo is not None else '').strip()
        if not preset_name:
            self._p10_refresh_compare_preset_controls(preserve_target=False)
            return
        preset = self._p10_find_compare_preset(preset_name)
        if preset is None:
            self._p10_refresh_compare_preset_controls(preserve_target=False)
            return
        self._p10_compare_target_preset_name = str(preset.get('name', '')).strip()
        preset_symbols = list(preset.get('symbols', []))
        preset_interval_label = str(preset.get('interval_label', '1 Day') or '1 Day')
        preset_range_label = str(preset.get('range_label', '5Y') or '5Y')
        if self._p10_compare_state_signature(
            preset_symbols,
            preset_interval_label,
            preset_range_label,
        ) == self._p10_compare_state_signature():
            self._p10_refresh_compare_preset_controls()
            return
        self.p10_compare_symbols = self._p10_normalize_compare_symbol_list(preset_symbols)
        self.p10_compare_interval_label = preset_interval_label
        self.p10_compare_range_label = preset_range_label
        self._p10_compare_dirty = True
        self._p10_update_timeframe_button_styles()
        self._p10_save_state()
        self._p10_refresh_compare_symbol_list()
        if self._p10_active_subtab_key() == 'compare':
            self._p10_refresh_compare_view(force=True)

    def _p10_save_compare_preset(self) -> None:
        """Create one named compare preset from the current compare setup."""
        if not self.p10_compare_symbols:
            QMessageBox.warning(self, 'Save Compare Preset', 'Add at least one compare ticker before saving a preset.')
            self._p10_set_compare_status('Add symbols before saving a compare preset.', 'warning')
            return
        name, ok = QInputDialog.getText(self, 'Save Compare Preset', 'Preset name:')
        if not ok:
            return
        clean_name = str(name or '').strip()
        if not clean_name:
            QMessageBox.warning(self, 'Save Compare Preset', 'Preset name cannot be blank.')
            self._p10_set_compare_status('Preset name cannot be blank.', 'warning')
            return
        if self._p10_find_compare_preset(clean_name) is not None:
            QMessageBox.warning(self, 'Save Compare Preset', f'A compare preset named "{clean_name}" already exists.')
            self._p10_set_compare_status(f'Compare preset "{clean_name}" already exists.', 'warning')
            return
        self.p10_compare_presets.append({
            'name': clean_name,
            'symbols': list(self.p10_compare_symbols),
            'interval_label': self.p10_compare_interval_label,
            'range_label': self.p10_compare_range_label,
        })
        self._p10_compare_target_preset_name = clean_name
        self._p10_save_state()
        self._p10_refresh_compare_preset_controls()
        self._p10_set_compare_status(f'Saved compare preset "{clean_name}".', 'positive')

    def _p10_update_compare_preset(self) -> None:
        """Overwrite the targeted compare preset with the current compare setup."""
        preset_name = str(self._p10_compare_target_preset_name or '').strip()
        preset = self._p10_find_compare_preset(preset_name)
        if preset is None:
            self._p10_compare_target_preset_name = None
            self._p10_refresh_compare_preset_controls(preserve_target=False)
            self._p10_set_compare_status('Select a compare preset before updating it.', 'warning')
            return
        if not self.p10_compare_symbols:
            QMessageBox.warning(self, 'Update Compare Preset', 'Add at least one compare ticker before updating a preset.')
            self._p10_set_compare_status('Add symbols before updating a compare preset.', 'warning')
            return
        preset['symbols'] = list(self.p10_compare_symbols)
        preset['interval_label'] = self.p10_compare_interval_label
        preset['range_label'] = self.p10_compare_range_label
        self._p10_save_state()
        self._p10_refresh_compare_preset_controls()
        self._p10_set_compare_status(f'Updated compare preset "{preset_name}".', 'positive')

    def _p10_delete_compare_preset(self) -> None:
        """Delete the targeted compare preset without clearing the live compare setup."""
        preset_name = str(self._p10_compare_target_preset_name or '').strip()
        preset = self._p10_find_compare_preset(preset_name)
        if preset is None:
            self._p10_compare_target_preset_name = None
            self._p10_refresh_compare_preset_controls(preserve_target=False)
            self._p10_set_compare_status('Select a compare preset before deleting it.', 'warning')
            return
        answer = QMessageBox.question(
            self,
            'Delete Compare Preset',
            f'Delete compare preset "{preset_name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        preset_key = self._p10_compare_preset_key(preset_name)
        self.p10_compare_presets = [
            item for item in list(self.p10_compare_presets or [])
            if self._p10_compare_preset_key((item or {}).get('name')) != preset_key
        ]
        self._p10_compare_target_preset_name = None
        self._p10_save_state()
        self._p10_refresh_compare_preset_controls(preserve_target=False)
        self._p10_set_compare_status(f'Deleted compare preset "{preset_name}".', 'positive')

    def _p10_compare_cache_key(self, symbol: Any, interval_label: Any, range_label: Any) -> tuple[str, str, str]:
        """Build one stable in-memory cache key for compare series."""
        return (
            str(symbol or '').upper().strip(),
            str(interval_label or '').strip(),
            str(range_label or '').strip(),
        )

    def _p10_build_compare_frame(self, symbols: Any, interval_label: Any, range_label: Any, fresh_series: Any=None) -> Any:
        """Build one ordered compare frame from fresh or cached normalized series."""
        ordered_series = []
        fresh_series = fresh_series if isinstance(fresh_series, dict) else {}
        for raw_symbol in list(symbols or []):
            symbol = str(raw_symbol or '').upper().strip()
            if not symbol:
                continue
            series = fresh_series.get(symbol)
            if series is None:
                series = self._p10_compare_series_cache.get(self._p10_compare_cache_key(symbol, interval_label, range_label))
            if series is None or getattr(series, 'empty', True):
                continue
            normalized = pd.Series(series).copy()
            normalized.index = self._p10_normalize_datetime_index(normalized.index)
            normalized = normalized[~normalized.index.duplicated(keep='last')].sort_index()
            normalized.name = symbol
            if normalized.empty:
                continue
            ordered_series.append(normalized)
        if not ordered_series:
            return pd.DataFrame()
        frame = pd.concat(ordered_series, axis=1, join='outer').sort_index()
        ordered_columns = [str(symbol or '').upper().strip() for symbol in list(symbols or []) if str(symbol or '').upper().strip() in frame.columns]
        return frame.loc[:, ordered_columns]

    def _p10_get_compare_request_settings(self) -> tuple[str, str, str, str]:
        """Return the current compare range and interval settings."""
        interval_label = self.p10_compare_interval_label if self.p10_compare_interval_label in self._p10_compare_interval_map else '1 Day'
        range_label = self.p10_compare_range_label if self.p10_compare_range_label in self._p10_compare_range_map else '5Y'
        return (
            range_label,
            self._p10_compare_range_map[range_label],
            interval_label,
            self._p10_compare_interval_map[interval_label],
        )

    def _p10_build_compare_render_signature(self, frame: Any, interval: Any) -> Any:
        """Build a lightweight signature so no-op compare rerenders can be skipped."""
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return ('empty', str(interval or ''))
        numeric_frame = frame.apply(pd.to_numeric, errors='coerce')
        last_values = []
        valid_counts = []
        for symbol in numeric_frame.columns:
            valid_series = numeric_frame[symbol].dropna()
            valid_counts.append(int(valid_series.size))
            last_values.append(None if valid_series.empty else round(float(valid_series.iloc[-1]), 6))
        first_stamp = int(numeric_frame.index[0].value) if len(numeric_frame.index) else None
        last_stamp = int(numeric_frame.index[-1].value) if len(numeric_frame.index) else None
        return (
            str(interval or ''),
            tuple(str(symbol) for symbol in numeric_frame.columns),
            int(len(numeric_frame.index)),
            first_stamp,
            last_stamp,
            tuple(valid_counts),
            tuple(last_values),
        )

    def _p10_remove_compare_plot_symbol(self, symbol: Any) -> None:
        """Remove one compare line and its label from the plot."""
        symbol_text = str(symbol or '').upper().strip()
        plot_item = self._p10_compare_plot_items.pop(symbol_text, None)
        if plot_item is not None and hasattr(self, 'p10_compare_plot'):
            try:
                self.p10_compare_plot.removeItem(plot_item)
            except Exception:
                pass
        label_item = self._p10_compare_label_items.pop(symbol_text, None)
        if label_item is not None and hasattr(self, 'p10_compare_plot'):
            try:
                self.p10_compare_plot.removeItem(label_item)
            except Exception:
                pass

    def _p10_clear_compare_plot_items(self) -> None:
        """Remove all dynamic compare lines and labels while preserving the zero line."""
        for symbol in list(self._p10_compare_plot_items):
            self._p10_remove_compare_plot_symbol(symbol)
        self._p10_compare_plot_items = {}
        self._p10_compare_label_items = {}
        self._p10_compare_render_signature = None
        if self._p10_compare_zero_line is not None:
            self._p10_compare_zero_line.hide()

    def _p10_fetch_compare_frames_batch(self, symbols: Any, *, period: Any, interval: Any) -> tuple[dict[str, Any], list[str]]:
        """Fetch several compare frames with one yfinance batch request."""
        payload = self._get_chart_data_service().fetch_compare_frames_batch_payload(symbols, period=period, interval=interval)
        self._p10_last_compare_batch_payload = payload
        return dict(payload.get('frames', {})), list(payload.get('missing', []))

    def _p10_add_compare_symbol(self) -> None:
        """Add one ticker to the saved compare list."""
        symbol = self.p10_compare_input.text().upper().strip()
        if not symbol:
            return
        self.p10_compare_input.clear()
        if symbol in self.p10_compare_symbols:
            self._p10_set_compare_status(f'{symbol} is already in Compare.', 'warning')
            return
        self.p10_compare_symbols.append(symbol)
        self._p10_save_state()
        self._p10_refresh_compare_symbol_list()
        self._p10_compare_dirty = True
        if self._p10_active_subtab_key() == 'compare':
            self._p10_refresh_compare_view(force=True)

    def _p10_remove_compare_symbol(self) -> None:
        """Remove the selected ticker from the saved compare list."""
        item = self.p10_compare_list.currentItem() if hasattr(self, 'p10_compare_list') else None
        if item is None:
            return
        symbol = str(item.data(Qt.ItemDataRole.UserRole) or '').upper().strip()
        if not symbol:
            return
        self.p10_compare_symbols = [value for value in self.p10_compare_symbols if value != symbol]
        self._p10_save_state()
        self._p10_refresh_compare_symbol_list()
        self._p10_compare_dirty = True
        if self._p10_active_subtab_key() == 'compare':
            self._p10_refresh_compare_view(force=True)

    def _p10_update_auto_button_style(self) -> None:
        """Highlight the auto-follow toggle."""
        self.p10_auto_btn.blockSignals(True)
        self.p10_auto_btn.setChecked(self.p10_auto_follow)
        self.p10_auto_btn.blockSignals(False)
        self.set_theme_variant(self.p10_auto_btn, 'accent' if self.p10_auto_follow else None)
        self.p10_auto_btn.setProperty('bt_checked', 'true' if self.p10_auto_follow else 'false')
        self._repolish_widget(self.p10_auto_btn)

    def _p10_toggle_auto_follow(self, checked: Any=False) -> None:
        """Switch between auto-follow and manual viewport modes."""
        self.p10_auto_follow = bool(checked)
        if not self.p10_auto_follow:
            self._p10_manual_x_range = self._p10_get_current_x_range()
        self._p10_update_auto_button_style()
        self._p10_save_state()
        if self.p10_auto_follow and self._p10_chart_rows:
            self._p10_apply_auto_x_range(self._p10_get_current_x_range())

    def _p10_get_current_x_range(self) -> Any:
        """Return the current x-range of the main chart."""
        try:
            return tuple(self.p10_main_plot.getPlotItem().vb.viewRange()[0])
        except Exception:
            return None

    def _p10_set_x_range(self, x_range: Any) -> None:
        """Set the chart x-range without re-entering x-range handlers."""
        if not x_range:
            return
        left, right = x_range
        if right <= left:
            return
        self._p10_view_change_guard = True
        try:
            self.p10_main_plot.setXRange(float(left), float(right), padding=0)
        finally:
            self._p10_view_change_guard = False

    def _p10_normalize_x_range(self, x_range: Any) -> Any:
        """Clamp a proposed x-range to a valid span for the current dataset."""
        if not x_range or not self._p10_chart_rows:
            return None
        left, right = (float(x_range[0]), float(x_range[1]))
        span = max(2.0, right - left)
        latest_index = max(0.0, float(len(self._p10_chart_rows) - 1))
        center = max(0.0, min((left + right) / 2.0, latest_index))
        norm_left = center - span / 2.0
        norm_right = center + span / 2.0
        return (norm_left, norm_right)

    def _p10_is_reusable_x_range(self, x_range: Any) -> bool:
        """Return whether an x-range is meaningful enough to reuse."""
        if not x_range:
            return False
        try:
            left = float(x_range[0])
            right = float(x_range[1])
        except Exception:
            return False
        return right > left and (right - left) >= P10_MIN_REUSABLE_SPAN

    def _p10_apply_auto_x_range(self, source_range: Any=None) -> None:
        """Anchor the latest candle near the right side of the viewport."""
        if not self._p10_chart_rows:
            return
        latest_index = float(len(self._p10_chart_rows) - 1)
        if self._p10_is_reusable_x_range(source_range):
            span = max(P10_MIN_REUSABLE_SPAN, float(source_range[1]) - float(source_range[0]))
        else:
            span = max(20.0, min(P10_DEFAULT_STARTUP_SPAN, float(len(self._p10_chart_rows))))
        right_padding = span * (1.0 - P10_AUTO_ANCHOR)
        anchored = (latest_index - span * P10_AUTO_ANCHOR, latest_index + right_padding)
        self._p10_set_x_range(anchored)
        self._p10_apply_auto_y_range(anchored)

    def _p10_get_visible_rows(self, x_range: Any=None) -> Any:
        """Return the chart rows that fall inside the requested x-range."""
        if not self._p10_chart_rows:
            return []
        active_range = x_range or self._p10_get_current_x_range()
        if not active_range:
            return list(self._p10_chart_rows)
        left = max(0, int(math.floor(float(active_range[0]))))
        right = min(len(self._p10_chart_rows) - 1, int(math.ceil(float(active_range[1]))))
        if right < left:
            return []
        return self._p10_chart_rows[left:right + 1]

    def _p10_apply_auto_y_range(self, x_range: Any=None) -> None:
        """Fit the y-axis to the currently visible candles while auto mode is on."""
        visible_rows = self._p10_get_visible_rows(x_range)
        if not visible_rows:
            return
        lows = [float(getattr(row, 'Low')) for row in visible_rows]
        highs = [float(getattr(row, 'High')) for row in visible_rows]
        if self.p10_ma200_series is not None and '200 MA' in self.p10_active_indicators:
            active_range = x_range or self._p10_get_current_x_range()
            if active_range:
                left = max(0, int(math.floor(float(active_range[0]))))
                right = min(len(self.p10_ma200_series) - 1, int(math.ceil(float(active_range[1]))))
                if right >= left:
                    ma_values = [float(value) for value in self.p10_ma200_series.iloc[left:right + 1] if not pd.isna(value)]
                    if ma_values:
                        lows.append(min(ma_values))
                        highs.append(max(ma_values))
        self._p10_append_support_resistance_bounds(lows, highs)
        self._p10_append_fib_bounds(lows, highs)
        low_value = min(lows)
        high_value = max(highs)
        span = high_value - low_value
        padding = max(0.5, span * 0.08) if span > 0 else max(abs(high_value) * 0.03, 1.0)
        self.p10_main_plot.setYRange(low_value - padding, high_value + padding, padding=0)

    def _p10_safe_row_price(self, row: Any, field: str) -> float | None:
        """Return a finite OHLC value from one row when available."""
        try:
            value = float(getattr(row, field))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def _p10_clean_price_rows(self, rows: Any) -> list[tuple[int, float, float, float]]:
        """Return finite low/high/close tuples for support and resistance analysis."""
        clean_rows = []
        source_rows = [] if rows is None else list(rows)
        for index, row in enumerate(source_rows):
            low_value = self._p10_safe_row_price(row, 'Low')
            high_value = self._p10_safe_row_price(row, 'High')
            close_value = self._p10_safe_row_price(row, 'Close')
            if low_value is None or high_value is None or close_value is None:
                continue
            if high_value < low_value:
                continue
            clean_rows.append((index, low_value, high_value, close_value))
        return clean_rows

    def _p10_cluster_pivot_levels(self, pivots: list[tuple[float, int]]) -> list[dict[str, Any]]:
        """Cluster nearby swing pivots into candidate price levels."""
        clusters: list[dict[str, Any]] = []
        for price, index in sorted(pivots, key=lambda item: item[0]):
            matched = None
            for cluster in clusters:
                center = float(cluster['price'])
                tolerance = max(abs(center), abs(price), 1.0) * P10_SR_LEVEL_TOLERANCE_PCT
                if abs(price - center) <= tolerance:
                    matched = cluster
                    break
            if matched is None:
                clusters.append({'prices': [price], 'indexes': [index], 'price': price})
                continue
            matched['prices'].append(price)
            matched['indexes'].append(index)
            matched['price'] = sum(matched['prices']) / len(matched['prices'])
        return clusters

    def _p10_score_sr_cluster(self, cluster: dict[str, Any], current_close: float, row_count: int) -> float:
        """Score one support/resistance cluster by touches, recency, and price proximity."""
        price = float(cluster['price'])
        touches = len(cluster.get('prices', []))
        latest_index = max(cluster.get('indexes', [0]))
        recency = latest_index / max(row_count - 1, 1)
        proximity = 1.0 - min(abs(price - current_close) / max(abs(current_close), 1.0), 1.0)
        return touches * 10.0 + recency * 4.0 + proximity * 3.0

    def _p10_best_sr_level(self, clusters: list[dict[str, Any]], current_close: float, row_count: int) -> float | None:
        """Return the best scored clustered level from a filtered cluster list."""
        if not clusters:
            return None
        best = max(
            clusters,
            key=lambda cluster: self._p10_score_sr_cluster(cluster, current_close, row_count),
        )
        return float(best['price'])

    def _p10_calculate_support_resistance(self, rows: Any) -> tuple[float | None, float | None]:
        """Calculate one support and one resistance level from swing pivots."""
        clean_rows = self._p10_clean_price_rows(rows)
        if len(clean_rows) < 2:
            return (None, None)
        lows = [row[1] for row in clean_rows]
        highs = [row[2] for row in clean_rows]
        current_close = clean_rows[-1][3]
        fallback_support = min(lows)
        fallback_resistance = max(highs)
        required_rows = (P10_SR_PIVOT_WINDOW * 2) + 1
        if len(clean_rows) < required_rows:
            support = fallback_support if fallback_support <= current_close else None
            resistance = fallback_resistance if fallback_resistance >= current_close else None
            return self._p10_distinct_support_resistance(support, resistance)

        support_pivots: list[tuple[float, int]] = []
        resistance_pivots: list[tuple[float, int]] = []
        window = P10_SR_PIVOT_WINDOW
        for index in range(window, len(clean_rows) - window):
            source_index, low_value, high_value, _close_value = clean_rows[index]
            neighbors = clean_rows[index - window:index + window + 1]
            neighbor_lows = [row[1] for row in neighbors]
            neighbor_highs = [row[2] for row in neighbors]
            if low_value == min(neighbor_lows):
                support_pivots.append((low_value, source_index))
            if high_value == max(neighbor_highs):
                resistance_pivots.append((high_value, source_index))

        support_clusters = [
            cluster for cluster in self._p10_cluster_pivot_levels(support_pivots)
            if float(cluster['price']) <= current_close
        ]
        resistance_clusters = [
            cluster for cluster in self._p10_cluster_pivot_levels(resistance_pivots)
            if float(cluster['price']) >= current_close
        ]
        support = self._p10_best_sr_level(support_clusters, current_close, len(clean_rows))
        resistance = self._p10_best_sr_level(resistance_clusters, current_close, len(clean_rows))
        if support is None and fallback_support <= current_close:
            support = fallback_support
        if resistance is None and fallback_resistance >= current_close:
            resistance = fallback_resistance
        return self._p10_distinct_support_resistance(support, resistance)

    def _p10_distinct_support_resistance(self, support: Any, resistance: Any) -> tuple[float | None, float | None]:
        """Suppress duplicate or invalid support/resistance outputs."""
        try:
            support_value = float(support) if support is not None else None
        except (TypeError, ValueError):
            support_value = None
        try:
            resistance_value = float(resistance) if resistance is not None else None
        except (TypeError, ValueError):
            resistance_value = None
        if support_value is not None and not math.isfinite(support_value):
            support_value = None
        if resistance_value is not None and not math.isfinite(resistance_value):
            resistance_value = None
        if support_value is not None and resistance_value is not None:
            tolerance = max(abs(support_value), abs(resistance_value), 1.0) * 0.0001
            if abs(support_value - resistance_value) <= tolerance:
                resistance_value = None
        return (support_value, resistance_value)

    def _p10_rows_for_sr(self, row_limit: int | None=None) -> list[Any]:
        """Return the rows eligible for support/resistance calculation."""
        if row_limit is None:
            return list(self._p10_chart_rows)
        try:
            limit = int(row_limit)
        except (TypeError, ValueError):
            limit = len(self._p10_chart_rows)
        limit = max(0, min(limit, len(self._p10_chart_rows)))
        return list(self._p10_chart_rows[:limit])

    def _p10_clear_support_resistance_lines(self) -> None:
        """Remove support/resistance lines and labels from the main chart."""
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_support_line', None))
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_resistance_line', None))
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_support_label_item', None))
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_resistance_label_item', None))
        self.p10_support_line = None
        self.p10_resistance_line = None
        self.p10_support_resistance_levels = None
        self._p10_remove_legacy_overlay_item('support')
        self._p10_remove_legacy_overlay_item('resistance')
        self.p10_support_label_item = None
        self.p10_resistance_label_item = None
        self._p10_update_indicator_value_readout()

    def _p10_set_sr_line(self, attr_name: str, level: float | None, color_key: str) -> Any:
        """Create, update, or remove one support/resistance line."""
        line = getattr(self, attr_name, None)
        if level is None:
            self._p10_remove_chart_item(self.p10_main_plot, line)
            setattr(self, attr_name, None)
            return None
        pen = self.theme_pen(color_key, width=1.5, style=Qt.PenStyle.DashLine)
        if line is None:
            line = pg.InfiniteLine(pos=float(level), angle=0, pen=pen)
            self.p10_main_plot.addItem(line)
            setattr(self, attr_name, line)
        else:
            line.setPen(pen)
            line.setValue(float(level))
        line.setVisible(P10_SUPPORT_RESISTANCE_LABEL in self.p10_active_indicators)
        return line

    def _p10_refresh_support_resistance_lines(self, row_limit: int | None=None) -> None:
        """Draw the active support and resistance lines for the current chart frame."""
        if P10_SUPPORT_RESISTANCE_LABEL not in self.p10_active_indicators or not self._p10_chart_rows:
            self._p10_clear_support_resistance_lines()
            return
        rows = self._p10_rows_for_sr(row_limit)
        support, resistance = self._p10_calculate_support_resistance(rows)
        self.p10_support_resistance_levels = (support, resistance)
        self.p10_support_line = self._p10_set_sr_line('p10_support_line', support, 'accent_positive')
        self.p10_resistance_line = self._p10_set_sr_line('p10_resistance_line', resistance, 'accent_negative')
        self._p10_remove_legacy_overlay_item('support')
        self._p10_remove_legacy_overlay_item('resistance')
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_support_label_item', None))
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_resistance_label_item', None))
        self.p10_support_label_item = None
        self.p10_resistance_label_item = None
        self._p10_update_indicator_value_readout()

    def _p10_append_support_resistance_bounds(self, lows: list[float], highs: list[float], row_limit: int | None=None) -> None:
        """Include active support/resistance levels in chart y-axis bounds."""
        if P10_SUPPORT_RESISTANCE_LABEL not in self.p10_active_indicators:
            return
        levels = getattr(self, 'p10_support_resistance_levels', None)
        if levels is None or row_limit is not None:
            levels = self._p10_calculate_support_resistance(self._p10_rows_for_sr(row_limit))
        for level in levels or ():
            if level is None:
                continue
            try:
                value = float(level)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                lows.append(value)
                highs.append(value)

    def _p10_rows_for_fib(self, row_limit: int | None=None) -> list[tuple[int, Any]]:
        """Return recent chart rows eligible for automatic Fibonacci anchors."""
        if not self._p10_chart_rows:
            return []
        if row_limit is None:
            limit = len(self._p10_chart_rows)
        else:
            try:
                limit = int(row_limit)
            except (TypeError, ValueError):
                limit = len(self._p10_chart_rows)
        limit = max(0, min(limit, len(self._p10_chart_rows)))
        try:
            lookback = int(getattr(self, 'p10_fib_lookback', P10_FIB_DEFAULT_LOOKBACK))
        except (TypeError, ValueError):
            lookback = P10_FIB_DEFAULT_LOOKBACK
        lookback = max(P10_FIB_MIN_LOOKBACK, min(P10_FIB_MAX_LOOKBACK, lookback))
        start = max(0, limit - lookback)
        return [(index, self._p10_chart_rows[index]) for index in range(start, limit)]

    def _p10_fib_levels_from_anchors(
        self,
        start_index: int,
        start_price: float,
        start_role: str,
        end_index: int,
        end_price: float,
        end_role: str,
    ) -> dict[str, Any] | None:
        """Build Fibonacci levels from one explicit anchor pair."""
        try:
            start_index = int(start_index)
            end_index = int(end_index)
            start_price = float(start_price)
            end_price = float(end_price)
        except (TypeError, ValueError):
            return None
        if start_index < 0 or end_index < 0:
            return None
        if not math.isfinite(start_price) or not math.isfinite(end_price):
            return None
        span = abs(end_price - start_price)
        if not math.isfinite(span) or span <= 0:
            return None
        direction = 'up' if end_price > start_price else 'down'
        if direction == 'up':
            levels = [
                {'ratio': ratio, 'label': label, 'price': end_price - (span * ratio)}
                for ratio, label in P10_FIB_LEVELS
            ]
        else:
            levels = [
                {'ratio': ratio, 'label': label, 'price': end_price + (span * ratio)}
                for ratio, label in P10_FIB_LEVELS
            ]
        low_anchor = {'index': start_index, 'price': start_price} if start_price <= end_price else {'index': end_index, 'price': end_price}
        high_anchor = {'index': end_index, 'price': end_price} if start_price <= end_price else {'index': start_index, 'price': start_price}
        return {
            'direction': direction,
            'low': low_anchor,
            'high': high_anchor,
            'anchor_start': {'index': start_index, 'price': start_price, 'role': str(start_role or '').lower()},
            'anchor_end': {'index': end_index, 'price': end_price, 'role': str(end_role or '').lower()},
            'levels': levels,
        }

    def _p10_calculate_auto_fib_retracement(self, row_limit: int | None=None) -> dict[str, Any] | None:
        """Calculate automatic Fibonacci retracement levels from recent candles."""
        clean_rows = []
        for index, row in self._p10_rows_for_fib(row_limit):
            low_value = self._p10_safe_row_price(row, 'Low')
            high_value = self._p10_safe_row_price(row, 'High')
            if low_value is None or high_value is None or high_value < low_value:
                continue
            clean_rows.append((index, low_value, high_value))
        if len(clean_rows) < 2:
            return None
        low_index, low_price = min(clean_rows, key=lambda item: item[1])[:2]
        high_row = max(clean_rows, key=lambda item: item[2])
        high_index = high_row[0]
        high_price = high_row[2]
        is_upswing = low_index <= high_index
        if is_upswing:
            return self._p10_fib_levels_from_anchors(low_index, low_price, 'low', high_index, high_price, 'high')
        return self._p10_fib_levels_from_anchors(high_index, high_price, 'high', low_index, low_price, 'low')

    def _p10_calculate_manual_fib_retracement(self, row_limit: int | None=None) -> dict[str, Any] | None:
        """Calculate Fibonacci retracement levels from saved manual anchors."""
        anchor = self._p10_fib_manual_anchor()
        if not anchor:
            return None
        try:
            start_index = int(anchor.get('start_index'))
            end_index = int(anchor.get('end_index'))
        except (TypeError, ValueError):
            return None
        row_count = len(getattr(self, '_p10_chart_rows', []) or [])
        if start_index >= row_count or end_index >= row_count:
            return None
        if row_limit is not None:
            try:
                limit = int(row_limit)
            except (TypeError, ValueError):
                limit = row_count
            if start_index >= limit or end_index >= limit:
                return None
        return self._p10_fib_levels_from_anchors(
            start_index,
            float(anchor.get('start_price')),
            str(anchor.get('start_role', '')),
            end_index,
            float(anchor.get('end_price')),
            str(anchor.get('end_role', '')),
        )

    def _p10_calculate_fib_retracement(self, row_limit: int | None=None) -> dict[str, Any] | None:
        """Calculate Fibonacci retracement levels for the active Fib mode."""
        if getattr(self, 'p10_fib_mode', 'auto') == 'manual':
            return self._p10_calculate_manual_fib_retracement(row_limit)
        return self._p10_calculate_auto_fib_retracement(row_limit)

    def _p10_clear_fib_retracement(self) -> None:
        """Remove Fibonacci retracement lines and labels from the main chart."""
        for item in list(getattr(self, 'p10_fib_line_items', []) or []):
            self._p10_remove_chart_item(self.p10_main_plot, item)
        for item in list(getattr(self, 'p10_fib_label_items', []) or []):
            self._p10_remove_chart_item(self.p10_main_plot, item)
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_fib_anchor_item', None))
        self._p10_clear_fib_handles()
        self.p10_fib_line_items = []
        self.p10_fib_label_items = []
        self.p10_fib_anchor_item = None
        self.p10_fib_levels = None
        self._p10_update_indicator_value_readout()

    def _p10_refresh_fib_retracement(self, row_limit: int | None=None) -> None:
        """Draw the active Fibonacci retracement overlay for the recent candle swing."""
        if P10_FIB_RETRACEMENT_LABEL not in self.p10_active_indicators or not self._p10_chart_rows:
            self._p10_clear_fib_retracement()
            return
        fib = self._p10_calculate_fib_retracement(row_limit)
        self._p10_clear_fib_retracement()
        if not fib:
            if getattr(self, 'p10_fib_mode', 'auto') == 'manual':
                anchor = self._p10_fib_manual_anchor()
                status = 'Manual: set anchors' if anchor is None else 'Manual anchors are ahead of playback frame'
                self._p10_update_fib_controls(status)
            return
        line_pen = self.theme_pen('warning', width=1.0, style=Qt.PenStyle.DashLine)
        anchor_pen = self.theme_pen('chart_reference', width=1.0, style=Qt.PenStyle.DashLine)
        line_items = []
        for level in fib.get('levels', []):
            price = float(level['price'])
            line = pg.InfiniteLine(pos=price, angle=0, pen=line_pen)
            try:
                line.setZValue(5)
            except Exception:
                pass
            self.p10_main_plot.addItem(line)
            line_items.append(line)
        anchor_start = fib['anchor_start']
        anchor_end = fib['anchor_end']
        self.p10_fib_anchor_item = self.p10_main_plot.plot(
            [float(anchor_start['index']), float(anchor_end['index'])],
            [float(anchor_start['price']), float(anchor_end['price'])],
            pen=anchor_pen,
            antialias=True,
        )
        self.p10_fib_line_items = line_items
        self.p10_fib_label_items = []
        self.p10_fib_levels = fib
        self._p10_refresh_fib_handles(fib)
        self._p10_update_fib_controls()
        self._p10_update_indicator_value_readout()

    def _p10_refresh_fib_label_positions(self) -> None:
        """Compatibility hook; Fibonacci value text is rendered in the OHLC header."""

    def _p10_refresh_line_label_positions(self) -> None:
        """Compatibility hook; line value text is rendered in the OHLC header."""

    def _p10_make_fib_handle(self, anchor: dict[str, Any], label: str, color_key: str, *, movable: bool=True) -> Any:
        """Create one visual draggable Fibonacci anchor handle."""
        pen = self.theme_pen(color_key, width=1.6)
        hover_pen = self.theme_pen('accent', width=2.0)
        brush = self.theme_brush(color_key)
        hover_brush = self.theme_brush('accent')
        item = pg.TargetItem(
            pos=(float(anchor['index']), float(anchor['price'])),
            size=12,
            symbol='crosshair',
            pen=pen,
            hoverPen=hover_pen,
            brush=brush,
            hoverBrush=hover_brush,
            movable=bool(movable),
            label=label,
            labelOpts={'color': self.theme_color(color_key), 'offset': (10, -10)},
        )
        try:
            item.setZValue(10)
        except Exception:
            pass
        self.p10_main_plot.addItem(item, ignoreBounds=True)
        return item

    def _p10_clear_fib_handles(self) -> None:
        """Remove manual Fibonacci anchor handles from the main plot."""
        for attr_name in ('p10_fib_start_handle', 'p10_fib_end_handle', 'p10_fib_pending_handle'):
            item = getattr(self, attr_name, None)
            self._p10_remove_chart_item(self.p10_main_plot, item)
            setattr(self, attr_name, None)

    def _p10_set_fib_handle_position(self, handle: Any, anchor: dict[str, Any]) -> None:
        """Move one Fibonacci handle without re-entering drag callbacks."""
        if handle is None or not anchor:
            return
        self._p10_fib_drag_guard = True
        try:
            handle.setPos(float(anchor['index']), float(anchor['price']))
        except Exception:
            pass
        finally:
            self._p10_fib_drag_guard = False

    def _p10_playback_at_latest(self) -> bool:
        """Return whether the main chart is at the latest playback frame."""
        return bool(self._p10_chart_rows) and int(getattr(self, '_p10_playback_index', len(self._p10_chart_rows) - 1)) >= len(self._p10_chart_rows) - 1

    def _p10_fib_handles_movable(self) -> bool:
        """Return whether manual Fibonacci handles can be moved right now."""
        return not bool(getattr(self, '_p10_playback_running', False)) and self._p10_playback_at_latest()

    def _p10_refresh_fib_handles(self, fib: dict[str, Any] | None) -> None:
        """Render draggable handles for saved manual Fibonacci anchors."""
        if getattr(self, 'p10_fib_mode', 'auto') != 'manual' or not fib:
            return
        self._p10_clear_fib_handles()
        movable = self._p10_fib_handles_movable()
        self.p10_fib_start_handle = self._p10_make_fib_handle(fib['anchor_start'], 'Start', 'accent_positive', movable=movable)
        self.p10_fib_end_handle = self._p10_make_fib_handle(fib['anchor_end'], 'End', 'warning', movable=movable)
        self.p10_fib_start_handle.sigPositionChanged.connect(lambda item: self._p10_on_fib_handle_moved('start', item))
        self.p10_fib_end_handle.sigPositionChanged.connect(lambda item: self._p10_on_fib_handle_moved('end', item))
        self.p10_fib_start_handle.sigPositionChangeFinished.connect(lambda item: self._p10_on_fib_handle_released('start', item))
        self.p10_fib_end_handle.sigPositionChangeFinished.connect(lambda item: self._p10_on_fib_handle_released('end', item))

    def _p10_restore_fib_handles_from_saved_anchor(self) -> None:
        """Move visible handles back to the currently saved manual anchors."""
        anchor = self._p10_fib_manual_anchor()
        if not anchor:
            return
        start = {
            'index': int(anchor['start_index']),
            'price': float(anchor['start_price']),
            'role': str(anchor.get('start_role', '')),
        }
        end = {
            'index': int(anchor['end_index']),
            'price': float(anchor['end_price']),
            'role': str(anchor.get('end_role', '')),
        }
        self._p10_set_fib_handle_position(getattr(self, 'p10_fib_start_handle', None), start)
        self._p10_set_fib_handle_position(getattr(self, 'p10_fib_end_handle', None), end)

    def _p10_handle_anchor_from_item(self, handle: Any) -> dict[str, Any] | None:
        """Return the snapped candle anchor represented by one handle position."""
        if handle is None:
            return None
        try:
            pos = handle.pos()
            return self._p10_snap_fib_anchor(pos.x(), pos.y())
        except Exception:
            return None

    def _p10_on_fib_handle_moved(self, which: str, handle: Any) -> None:
        """Snap visible manual Fibonacci handles while they are dragged."""
        if getattr(self, '_p10_fib_drag_guard', False):
            return
        if not self._p10_fib_handles_movable():
            self._p10_update_fib_controls('Manual anchors disabled during playback')
            self._p10_restore_fib_handles_from_saved_anchor()
            return
        snapped = self._p10_handle_anchor_from_item(handle)
        if snapped is None:
            return
        self._p10_set_fib_handle_position(handle, snapped)
        label = 'Start' if which == 'start' else 'End'
        self._p10_update_fib_controls(f'Manual: dragging {label} {snapped["role"]} ${snapped["price"]:,.2f}')

    def _p10_on_fib_handle_released(self, which: str, handle: Any) -> None:
        """Persist a manual Fibonacci anchor after a drag ends."""
        if not self._p10_fib_handles_movable():
            self._p10_update_fib_controls('Manual anchors disabled during playback')
            self._p10_restore_fib_handles_from_saved_anchor()
            return
        snapped = self._p10_handle_anchor_from_item(handle)
        if snapped is None:
            self._p10_update_fib_controls('Manual: invalid anchor')
            self._p10_restore_fib_handles_from_saved_anchor()
            return
        if not self._p10_update_manual_fib_anchor(which, snapped):
            self._p10_update_fib_controls('Manual: choose a different anchor')
            self._p10_restore_fib_handles_from_saved_anchor()
            return
        self._p10_save_state()
        self._p10_refresh_fib_after_settings_change()

    def _p10_update_manual_fib_anchor(self, which: str, snapped_anchor: dict[str, Any]) -> bool:
        """Update one saved manual Fibonacci anchor for the current context."""
        if which not in ('start', 'end') or not snapped_anchor:
            return False
        key = self._p10_fib_context_key()
        current = self._p10_fib_manual_anchor(key)
        if not key or current is None:
            return False
        updated = dict(current)
        prefix = 'start' if which == 'start' else 'end'
        other_prefix = 'end' if which == 'start' else 'start'
        updated[f'{prefix}_index'] = int(snapped_anchor['index'])
        updated[f'{prefix}_price'] = float(snapped_anchor['price'])
        updated[f'{prefix}_role'] = str(snapped_anchor['role'])
        same_index = int(updated['start_index']) == int(updated['end_index'])
        same_price = abs(float(updated['start_price']) - float(updated['end_price'])) <= 0.000001
        if same_index and same_price:
            return False
        if abs(float(updated[f'{prefix}_price']) - float(updated[f'{other_prefix}_price'])) <= 0.000001:
            return False
        self.p10_fib_manual_by_context[key] = updated
        return True

    def _p10_append_fib_bounds(self, lows: list[float], highs: list[float], row_limit: int | None=None) -> None:
        """Include active Fibonacci levels in chart y-axis bounds."""
        if P10_FIB_RETRACEMENT_LABEL not in self.p10_active_indicators:
            return
        fib = getattr(self, 'p10_fib_levels', None)
        if fib is None or row_limit is not None:
            fib = self._p10_calculate_fib_retracement(row_limit)
        for level in (fib or {}).get('levels', []):
            try:
                value = float(level.get('price'))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                lows.append(value)
                highs.append(value)

    def _p10_configure_playback_controls(self) -> None:
        """Reset playback controls for the currently loaded main chart dataset."""
        self._p10_pause_playback()
        row_count = len(self._p10_chart_rows)
        enabled = row_count > 0
        if enabled:
            self._p10_playback_index = row_count - 1
        else:
            self._p10_playback_index = 0
        slider = getattr(self, 'p10_playback_slider', None)
        if slider is not None:
            self._p10_playback_slider_sync = True
            try:
                slider.setMinimum(0)
                slider.setMaximum(max(0, row_count - 1))
                slider.setValue(max(0, row_count - 1) if enabled else 0)
            finally:
                self._p10_playback_slider_sync = False
        self._p10_set_playback_enabled(enabled)
        self._p10_update_playback_label()

    def _p10_set_playback_enabled(self, enabled: bool) -> None:
        """Enable or disable compact playback controls."""
        for name in ('p10_playback_btn', 'p10_playback_restart_btn', 'p10_playback_speed_combo', 'p10_playback_slider'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(bool(enabled))
        if not enabled:
            self._p10_playback_running = False
            button = getattr(self, 'p10_playback_btn', None)
            if button is not None:
                button.setText('Play')
                self.set_theme_variant(button, None)
                button.setProperty('bt_checked', 'false')
                self._repolish_widget(button)

    def _p10_toggle_playback(self) -> None:
        """Start or pause candle-reveal playback."""
        if self._p10_playback_running:
            self._p10_pause_playback()
        else:
            self._p10_start_playback()

    def _p10_start_playback(self) -> None:
        """Start playback from the current slider position."""
        if not self._p10_chart_rows:
            self._p10_set_playback_enabled(False)
            return
        if len(self._p10_chart_rows) <= 1 or self._p10_playback_index >= len(self._p10_chart_rows) - 1:
            self._p10_set_playback_index(0)
        if len(self._p10_chart_rows) <= 1:
            self._p10_pause_playback()
            return
        speed_label = self.p10_playback_speed_label if self.p10_playback_speed_label in P10_PLAYBACK_SPEEDS else P10_DEFAULT_PLAYBACK_SPEED
        interval_ms, _step = P10_PLAYBACK_SPEEDS[speed_label]
        self._p10_playback_running = True
        self._p10_playback_timer.start(interval_ms)
        button = getattr(self, 'p10_playback_btn', None)
        if button is not None:
            button.setText('Pause')
            self.set_theme_variant(button, 'accent')
            button.setProperty('bt_checked', 'true')
            self._repolish_widget(button)

    def _p10_pause_playback(self) -> None:
        """Pause playback without changing the current reveal position."""
        timer = getattr(self, '_p10_playback_timer', None)
        if timer is not None:
            timer.stop()
        self._p10_playback_running = False
        button = getattr(self, 'p10_playback_btn', None)
        if button is not None:
            button.setText('Play')
            self.set_theme_variant(button, None)
            button.setProperty('bt_checked', 'false')
            self._repolish_widget(button)

    def _p10_restart_playback(self) -> None:
        """Restart playback at the first available candle."""
        if not self._p10_chart_rows:
            self._p10_set_playback_enabled(False)
            return
        self._p10_pause_playback()
        self._p10_set_playback_index(0)

    def _p10_step_playback(self) -> None:
        """Advance playback by the selected speed step."""
        if not self._p10_chart_rows:
            self._p10_pause_playback()
            self._p10_set_playback_enabled(False)
            return
        speed_label = self.p10_playback_speed_label if self.p10_playback_speed_label in P10_PLAYBACK_SPEEDS else P10_DEFAULT_PLAYBACK_SPEED
        _interval_ms, step = P10_PLAYBACK_SPEEDS[speed_label]
        latest_index = len(self._p10_chart_rows) - 1
        next_index = min(latest_index, int(self._p10_playback_index) + int(step))
        self._p10_set_playback_index(next_index)
        if next_index >= latest_index:
            self._p10_pause_playback()

    def _p10_set_playback_index(self, index: Any, *, render: bool=True) -> None:
        """Set the reveal endpoint and optionally redraw the playback frame."""
        if not self._p10_chart_rows:
            self._p10_playback_index = 0
            self._p10_update_playback_label()
            return
        try:
            row_index = int(index)
        except (TypeError, ValueError):
            row_index = 0
        row_index = max(0, min(row_index, len(self._p10_chart_rows) - 1))
        self._p10_playback_index = row_index
        slider = getattr(self, 'p10_playback_slider', None)
        if slider is not None and slider.value() != row_index:
            self._p10_playback_slider_sync = True
            try:
                slider.setValue(row_index)
            finally:
                self._p10_playback_slider_sync = False
        self._p10_update_playback_label()
        if render:
            self._p10_render_playback_frame()

    def _p10_on_playback_slider_changed(self, value: int) -> None:
        """Jump playback to the selected slider row."""
        if self._p10_playback_slider_sync:
            return
        self._p10_pause_playback()
        self._p10_set_playback_index(value)

    def _p10_on_playback_speed_changed(self, label: str) -> None:
        """Persist and apply the selected playback speed."""
        text = str(label or '').strip()
        if text not in P10_PLAYBACK_SPEEDS:
            text = P10_DEFAULT_PLAYBACK_SPEED
        self.p10_playback_speed_label = text
        self._p10_save_state()
        if self._p10_playback_running:
            interval_ms, _step = P10_PLAYBACK_SPEEDS[text]
            self._p10_playback_timer.start(interval_ms)

    def _p10_render_playback_frame(self) -> None:
        """Render the chart as a candle-reveal playback frame."""
        if not self._p10_chart_rows:
            return
        row_index = max(0, min(int(self._p10_playback_index), len(self._p10_chart_rows) - 1))
        stats = self._p10_stats_for_row(row_index)
        x_range = self._p10_get_current_x_range()
        y_range = self._p10_get_current_y_range()
        self._p10_render_main_chart(
            stats,
            getattr(self, 'p10_active_interval', self._p10_timeframe_map.get(self.p10_timeframe_label, ('', '1d'))[1]),
            self.p10_rsi_series,
            self.p10_rsi_ma_series,
            self.p10_ma200_series,
            row_limit=row_index + 1,
        )
        self._p10_update_quote_header(stats)
        self._p10_show_row_details(row_index)
        self._p10_restore_playback_view(x_range, y_range)

    def _p10_get_current_y_range(self) -> Any:
        """Return the current y-range of the main chart."""
        try:
            return tuple(self.p10_main_plot.getPlotItem().vb.viewRange()[1])
        except Exception:
            return None

    def _p10_restore_playback_view(self, x_range: Any, y_range: Any) -> None:
        """Restore the user's chart viewport after a playback redraw."""
        if x_range:
            try:
                left, right = float(x_range[0]), float(x_range[1])
            except (TypeError, ValueError):
                left = right = 0.0
            if math.isfinite(left) and math.isfinite(right) and right > left:
                self._p10_set_x_range((left, right))
        if y_range:
            try:
                low, high = float(y_range[0]), float(y_range[1])
            except (TypeError, ValueError):
                low = high = 0.0
            if math.isfinite(low) and math.isfinite(high) and high > low:
                self.p10_main_plot.setYRange(low, high, padding=0)

    def _p10_update_playback_label(self) -> None:
        """Refresh compact playback progress text."""
        label = getattr(self, 'p10_playback_label', None)
        if label is None:
            return
        if not self._p10_chart_rows:
            label.setText('-- / --')
            return
        row_count = len(self._p10_chart_rows)
        row_index = max(0, min(int(self._p10_playback_index), row_count - 1))
        date_text = ''
        try:
            date_value = self.p10_chart_df.index[row_index]
            if hasattr(date_value, 'strftime'):
                date_text = date_value.strftime('%Y-%m-%d')
            else:
                date_text = str(date_value)[:10]
        except Exception:
            date_text = ''
        suffix = f'  {date_text}' if date_text else ''
        label.setText(f'{row_index + 1} / {row_count}{suffix}')

    def _p10_stop_playback(self, reset_to_latest: bool=False) -> None:
        """Stop playback and optionally restore the full latest chart frame."""
        self._p10_pause_playback()
        if reset_to_latest and self._p10_chart_rows:
            self._p10_set_playback_index(len(self._p10_chart_rows) - 1, render=False)
            self._p10_render_main_chart(
                self.p10_chart_stats,
                getattr(self, 'p10_active_interval', self._p10_timeframe_map.get(self.p10_timeframe_label, ('', '1d'))[1]),
                self.p10_rsi_series,
                self.p10_rsi_ma_series,
                self.p10_ma200_series,
            )
            self._p10_update_quote_header(self.p10_chart_stats)
            self._p10_show_row_details(len(self._p10_chart_rows) - 1)
            self._p10_update_playback_label()

    def _p10_stats_for_row(self, row_index: Any) -> dict[str, float]:
        """Return header/stat payload values for one chart row."""
        if not self._p10_chart_rows:
            return {
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'close': 0.0,
                'volume': 0.0,
                'change_value': 0.0,
                'change_pct': 0.0,
            }
        index = max(0, min(int(row_index), len(self._p10_chart_rows) - 1))
        row = self._p10_chart_rows[index]
        prev_row = self._p10_chart_rows[index - 1] if index > 0 else row
        close_value = float(getattr(row, 'Close'))
        prev_close = float(getattr(prev_row, 'Close'))
        change_value = close_value - prev_close
        change_pct = change_value / prev_close * 100 if prev_close else 0.0
        return {
            'open': float(getattr(row, 'Open')),
            'high': float(getattr(row, 'High')),
            'low': float(getattr(row, 'Low')),
            'close': close_value,
            'volume': float(getattr(row, 'Volume', 0.0) or 0.0),
            'change_value': change_value,
            'change_pct': change_pct,
        }

    def _p10_restore_manual_x_range(self) -> None:
        """Restore the user's manual x-range when auto-follow is off."""
        x_range = self._p10_pending_x_range or self._p10_manual_x_range
        normalized = self._p10_normalize_x_range(x_range)
        if normalized:
            self._p10_set_x_range(normalized)
            self._p10_manual_x_range = normalized

    def _p10_on_x_range_changed(self, *_: Any) -> None:
        """Track user viewport changes and enforce auto-follow centering."""
        if self._p10_view_change_guard or not self._p10_chart_rows:
            return
        if self._p10_playback_running:
            self._p10_pause_playback()
            return
        current_range = self._p10_get_current_x_range()
        if not current_range:
            return
        if self.p10_auto_follow:
            self._p10_apply_auto_x_range(current_range)
            self._p10_apply_auto_y_range(self._p10_get_current_x_range())
        else:
            self._p10_manual_x_range = current_range

    def _p10_update_timeframe_button_styles(self) -> None:
        """Highlight the active timeframe button."""
        self.update_checked_button_state(self._p10_timeframe_buttons, self.p10_timeframe_label)
        for label, btn in self._p10_timeframe_buttons.items():
            btn.setChecked(label == self.p10_timeframe_label)
        self.update_checked_button_state(self._p10_compare_timeframe_buttons, self.p10_compare_interval_label)
        for label, btn in self._p10_compare_timeframe_buttons.items():
            btn.setChecked(label == self.p10_compare_interval_label)
        combo = getattr(self, 'p10_compare_range_combo', None)
        if combo is not None:
            index = combo.findText(self.p10_compare_range_label)
            if index >= 0 and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._p10_update_multi_interval_button_styles()

    def _p10_normalize_multi_interval_labels(self, values: Any) -> list[str]:
        """Normalize saved extra-timeframe selections into a stable ordered list."""
        normalized = []
        valid_labels = {label for label, _, _ in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS}
        for value in list(values or []):
            label = str(value or '').strip()
            if label in valid_labels and label not in normalized:
                normalized.append(label)
        return normalized

    def _p10_initial_multi_interval_labels(self, values: Any) -> list[str]:
        """Return saved multi-interval selections, defaulting to all available timeframes."""
        normalized = self._p10_normalize_multi_interval_labels(values)
        if normalized:
            return normalized
        return [label for label, _, _ in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS]

    def _p10_update_multi_interval_button_styles(self) -> None:
        """Refresh checked-state styling for the multi-interval selector buttons."""
        self.p10_multi_interval_labels = self._p10_normalize_multi_interval_labels(self.p10_multi_interval_labels)
        all_labels = [label for label, _, _ in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS]
        for label, btn in getattr(self, '_p10_multi_interval_buttons', {}).items():
            is_active = label in self.p10_multi_interval_labels
            btn.blockSignals(True)
            btn.setChecked(is_active)
            btn.blockSignals(False)
            self.set_theme_variant(btn, 'positive' if is_active else None)
            btn.setProperty('bt_checked', 'true' if is_active else 'false')
            self._repolish_widget(btn)
        selection_label = getattr(self, 'p10_multi_interval_selection_label', None)
        if selection_label is not None:
            if self.p10_multi_interval_labels:
                selection_label.setText(
                    f'Showing {len(self.p10_multi_interval_labels)} timeframe panel(s): {", ".join(self.p10_multi_interval_labels)}'
                )
            else:
                selection_label.setText('Showing RSI, MFI, and MACD panels for the selected timeframes.')
        clear_btn = getattr(self, 'p10_multi_interval_clear_btn', None)
        if clear_btn is not None:
            clear_btn.setEnabled(bool(self.p10_multi_interval_labels))
        all_btn = getattr(self, 'p10_multi_interval_all_btn', None)
        if all_btn is not None:
            all_btn.setEnabled(self.p10_multi_interval_labels != all_labels)
        symbol_label = getattr(self, 'p10_multi_interval_symbol_label', None)
        if symbol_label is not None:
            symbol_label.setText(str(self.p10_symbol or 'SPY').upper().strip() or 'SPY')
        symbol_input = getattr(self, 'p10_multi_interval_symbol_input', None)
        if symbol_input is not None:
            text = str(self.p10_symbol or 'SPY').upper().strip() or 'SPY'
            if symbol_input.text().upper().strip() != text:
                symbol_input.setText(text)

    def _p10_select_all_multi_intervals(self) -> None:
        """Select every available timeframe for the multi-interval panel view."""
        all_labels = [label for label, _, _ in P10_MULTI_INTERVAL_TIMEFRAME_OPTIONS]
        if all_labels == self.p10_multi_interval_labels:
            self._p10_update_multi_interval_button_styles()
            self._p10_refresh_multi_interval_views()
            return
        self.p10_multi_interval_labels = list(all_labels)
        self._p10_update_multi_interval_button_styles()
        self._p10_save_state()
        self._p10_refresh_multi_interval_views()

    def _p10_clear_multi_interval_selection(self) -> None:
        """Clear all selected extra intervals."""
        if not self.p10_multi_interval_labels:
            self._p10_update_multi_interval_button_styles()
            self._p10_refresh_multi_interval_views()
            return
        self.p10_multi_interval_labels = []
        self._p10_update_multi_interval_button_styles()
        self._p10_save_state()
        self._p10_refresh_multi_interval_views()

    def _p10_toggle_multi_interval(self, label: Any, checked: Any=False) -> None:
        """Toggle one timeframe in the multi-interval panel view."""
        text = str(label or '').strip()
        if text not in self._p10_multi_interval_timeframe_map:
            self._p10_update_multi_interval_button_styles()
            return
        current = list(self.p10_multi_interval_labels)
        if checked:
            if text not in current:
                current.append(text)
        else:
            current = [value for value in current if value != text]
        normalized = self._p10_normalize_multi_interval_labels(current)
        if normalized == self.p10_multi_interval_labels:
            self._p10_update_multi_interval_button_styles()
            return
        self.p10_multi_interval_labels = normalized
        self._p10_update_multi_interval_button_styles()
        self._p10_save_state()
        self._p10_refresh_multi_interval_views()

    def _p10_load_multi_interval_from_input(self) -> None:
        """Load the symbol for the multi-interval subtab."""
        symbol_input = getattr(self, 'p10_multi_interval_symbol_input', None)
        symbol = str(symbol_input.text() if symbol_input is not None else self.p10_symbol).upper().strip()
        if not symbol:
            return
        self.p10_symbol = symbol
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(symbol)
        self._p10_chart_dirty = True
        self._p10_update_multi_interval_button_styles()
        self._p10_save_state()
        self._p10_refresh_multi_interval_views(force=True)

    def _p10_multi_interval_cache_key(self, symbol: Any, label: Any) -> tuple[str, str]:
        """Build one stable cache key for a symbol/timeframe indicator payload."""
        return (str(symbol or '').upper().strip(), str(label or '').strip())

    def _p10_build_multi_interval_indicator_frame(
        self,
        symbol: Any,
        labels: Any,
        key: str,
        fresh_payloads: Any=None,
    ) -> Any:
        """Build one aligned indicator frame for the selected timeframes."""
        ordered_series = []
        payload_map = fresh_payloads if isinstance(fresh_payloads, dict) else {}
        for raw_label in list(labels or []):
            label = str(raw_label or '').strip()
            if not label:
                continue
            payload = payload_map.get(label)
            if payload is None:
                payload = self._p10_multi_interval_cache.get(self._p10_multi_interval_cache_key(symbol, label))
            series = payload.get(key) if isinstance(payload, dict) else None
            if series is None:
                continue
            normalized = pd.Series(series).astype(float).copy()
            normalized.index = self._p10_normalize_datetime_index(normalized.index)
            normalized = normalized[~normalized.index.duplicated(keep='last')].sort_index()
            normalized.name = label
            if normalized.empty:
                continue
            ordered_series.append(normalized)
        if not ordered_series:
            return pd.DataFrame()
        frame = pd.concat(ordered_series, axis=1, join='outer').sort_index()
        ordered_columns = [
            str(label or '').strip()
            for label in list(labels or [])
            if str(label or '').strip() in frame.columns
        ]
        return frame.loc[:, ordered_columns]

    def _p10_multi_interval_axis_mode(self, labels: Any) -> str:
        """Return the best-fit axis label mode for the selected timeframes."""
        labels_set = {str(label or '').strip() for label in list(labels or [])}
        if labels_set.issubset({'1 Minute', '5 Minutes', '15 Minutes', '1 Hour'}):
            return '1h'
        return '1d'

    def _p10_multi_interval_has_data(self, frames: dict[str, Any]) -> bool:
        """Return whether any multi-interval indicator frame has data."""
        for frame in list((frames or {}).values()):
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                return True
        return False

    def _p10_multi_interval_dates(self, frames: dict[str, Any]) -> list[Any]:
        """Return one ordered union of timestamps across indicator frames."""
        dates = None
        for frame in list((frames or {}).values()):
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            frame_index = self._p10_normalize_datetime_index(frame.index)
            dates = frame_index if dates is None else dates.union(frame_index)
        return [] if dates is None else list(dates.sort_values())

    def _p10_clear_multi_interval_plot(self) -> None:
        """Clear all rendered multi-interval timeframe panels."""
        layout = getattr(self, 'p10_multi_interval_panel_layout', None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
        self.p10_multi_interval_panel_widgets = {}
        self.p10_multi_interval_frames = {}

    def _p10_set_multi_interval_plot_title(self, plot: Any, title: str) -> None:
        """Apply themed HTML titles to multi-interval plots."""
        if plot is None:
            return
        plot.setTitle(f'<span style="color: {self.theme_color("text_primary")};">{title}</span>')

    def _p10_create_multi_interval_plot_widget(self, title: str, *, minimum_height: int) -> tuple[Any, Any]:
        """Create one themed plot widget used inside a timeframe panel."""
        axis = DateAxisItem(orientation='bottom')
        plot = pg.PlotWidget(axisItems={'bottom': axis})
        self.style_plot_widget(plot)
        plot.getPlotItem().setMenuEnabled(False)
        plot.getPlotItem().hideAxis('left')
        plot.getPlotItem().showAxis('right')
        plot.getPlotItem().hideButtons()
        plot.setMinimumHeight(minimum_height)
        self._p10_set_multi_interval_plot_title(plot, title)
        return plot, axis

    def _p10_create_multi_interval_panel(self, symbol: Any, label: str) -> dict[str, Any]:
        """Create one timeframe card containing RSI, MFI, and MACD panels."""
        frame = QFrame()
        self.set_theme_role(frame, 'panel')
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(8)

        header_row = QHBoxLayout()
        title_label = QLabel(label)
        self.set_theme_role(title_label, 'card_title')
        period, interval = self._p10_multi_interval_timeframe_map.get(label, ('', ''))
        detail_label = QLabel(f'{str(symbol or "").upper().strip() or "SPY"} • {period} / {interval}')
        self.set_theme_role(detail_label, 'muted')
        header_row.addWidget(title_label)
        header_row.addStretch()
        header_row.addWidget(detail_label)
        frame_layout.addLayout(header_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        rsi_plot, rsi_axis = self._p10_create_multi_interval_plot_widget('RSI', minimum_height=118)
        mfi_plot, mfi_axis = self._p10_create_multi_interval_plot_widget('MFI', minimum_height=118)
        macd_plot, macd_axis = self._p10_create_multi_interval_plot_widget('MACD', minimum_height=132)
        mfi_plot.setXLink(rsi_plot)
        macd_plot.setXLink(rsi_plot)
        splitter.addWidget(rsi_plot)
        splitter.addWidget(mfi_plot)
        splitter.addWidget(macd_plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([150, 150, 180])
        frame_layout.addWidget(splitter)

        self.p10_multi_interval_panel_layout.addWidget(frame)
        entry = {
            'frame': frame,
            'title_label': title_label,
            'detail_label': detail_label,
            'splitter': splitter,
            'rsi_plot': rsi_plot,
            'rsi_axis': rsi_axis,
            'mfi_plot': mfi_plot,
            'mfi_axis': mfi_axis,
            'macd_plot': macd_plot,
            'macd_axis': macd_axis,
        }
        self.p10_multi_interval_panel_widgets[label] = entry
        return entry

    def _p10_multi_interval_single_label_frame(self, frame: Any, label: str) -> Any:
        """Return one indicator frame reduced to a single timeframe column."""
        if not isinstance(frame, pd.DataFrame) or frame.empty or label not in frame.columns:
            return pd.DataFrame()
        return frame.loc[:, [label]].copy()

    def _p10_multi_interval_x_values(self, series: Any, date_to_index: dict[Any, int]) -> tuple[list[float], list[float]]:
        """Map one dated indicator series onto the shared x-axis positions."""
        x_values = []
        y_values = []
        normalized = pd.Series(series).astype(float)
        normalized.index = self._p10_normalize_datetime_index(normalized.index)
        for idx, value in normalized.items():
            if pd.isna(value) or idx not in date_to_index:
                continue
            x_values.append(float(date_to_index[idx]))
            y_values.append(float(value))
        return x_values, y_values

    def _p10_render_multi_interval_oscillator_plot(
        self,
        plot: Any,
        axis: Any,
        frame: Any,
        ma_frame: Any,
        dates: list[Any],
        labels: Any,
        *,
        upper_line: float,
        lower_line: float,
    ) -> None:
        """Render one oscillator panel for the provided timeframe list."""
        if plot is None or axis is None:
            return
        axis.set_dates(dates, self._p10_multi_interval_axis_mode(labels))
        plot_item = plot.getPlotItem()
        try:
            plot_item.addLegend(offset=(8, 8))
        except Exception:
            pass
        date_to_index = {stamp: index for index, stamp in enumerate(dates)}
        for row, label in enumerate(list(labels or [])):
            if not isinstance(frame, pd.DataFrame) or frame.empty or label not in frame.columns:
                continue
            x_values, y_values = self._p10_multi_interval_x_values(frame[label], date_to_index)
            if not x_values or not y_values:
                continue
            color = self.theme_series_color(row)
            plot.plot(
                x_values,
                y_values,
                pen=pg.mkPen(color=color, width=2),
                name=label,
                antialias=False,
            )
            if isinstance(ma_frame, pd.DataFrame) and not ma_frame.empty and label in ma_frame.columns:
                ma_x_values, ma_y_values = self._p10_multi_interval_x_values(ma_frame[label], date_to_index)
                if ma_x_values and ma_y_values:
                    plot.plot(
                        ma_x_values,
                        ma_y_values,
                        pen=pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine),
                        name=f'{label} MA',
                        antialias=False,
                    )
        plot.addItem(pg.InfiniteLine(pos=upper_line, angle=0, pen=self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine)))
        plot.addItem(pg.InfiniteLine(pos=lower_line, angle=0, pen=self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine)))
        if dates:
            plot.setXRange(-0.5, float(len(dates) - 1) + 0.5, padding=0)
        plot.setYRange(0, 100, padding=0.02)

    def _p10_render_multi_interval_macd_plot(
        self,
        plot: Any,
        axis: Any,
        macd_frame: Any,
        signal_frame: Any,
        dates: list[Any],
        labels: Any,
    ) -> None:
        """Render one MACD panel for the provided timeframe list."""
        if plot is None or axis is None:
            return
        axis.set_dates(dates, self._p10_multi_interval_axis_mode(labels))
        plot_item = plot.getPlotItem()
        try:
            plot_item.addLegend(offset=(8, 8))
        except Exception:
            pass
        date_to_index = {stamp: index for index, stamp in enumerate(dates)}
        valid_min = None
        valid_max = None
        for row, label in enumerate(list(labels or [])):
            color = self.theme_series_color(row)
            if isinstance(macd_frame, pd.DataFrame) and not macd_frame.empty and label in macd_frame.columns:
                x_values, y_values = self._p10_multi_interval_x_values(macd_frame[label], date_to_index)
                if x_values and y_values:
                    plot.plot(
                        x_values,
                        y_values,
                        pen=pg.mkPen(color=color, width=2),
                        name=f'{label} MACD',
                        antialias=False,
                    )
                    series_min = min(y_values)
                    series_max = max(y_values)
                    valid_min = series_min if valid_min is None else min(valid_min, series_min)
                    valid_max = series_max if valid_max is None else max(valid_max, series_max)
            if isinstance(signal_frame, pd.DataFrame) and not signal_frame.empty and label in signal_frame.columns:
                x_values, y_values = self._p10_multi_interval_x_values(signal_frame[label], date_to_index)
                if x_values and y_values:
                    plot.plot(
                        x_values,
                        y_values,
                        pen=pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine),
                        name=f'{label} Signal',
                        antialias=False,
                    )
                    series_min = min(y_values)
                    series_max = max(y_values)
                    valid_min = series_min if valid_min is None else min(valid_min, series_min)
                    valid_max = series_max if valid_max is None else max(valid_max, series_max)
        plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine)))
        if dates:
            plot.setXRange(-0.5, float(len(dates) - 1) + 0.5, padding=0)
        if valid_min is None or valid_max is None:
            plot.setYRange(-1, 1, padding=0.05)
            return
        span = valid_max - valid_min
        padding = max(0.2, span * 0.10) if span > 0 else max(abs(valid_max) * 0.15, 0.5)
        plot.setYRange(valid_min - padding, valid_max + padding, padding=0)

    def _p10_render_multi_interval_chart(self, symbol: Any, frames: dict[str, Any], labels: Any) -> None:
        """Render one RSI/MFI/MACD card per selected timeframe."""
        self._p10_clear_multi_interval_plot()
        if not self._p10_multi_interval_has_data(frames):
            self.p10_multi_interval_empty_label.show()
            return
        requested_labels = list(labels or [])
        rendered_labels = []
        normalized_frames = {
            'rsi': frames.get('rsi').copy() if isinstance(frames.get('rsi'), pd.DataFrame) else pd.DataFrame(),
            'rsi_ma': frames.get('rsi_ma').copy() if isinstance(frames.get('rsi_ma'), pd.DataFrame) else pd.DataFrame(),
            'mfi': frames.get('mfi').copy() if isinstance(frames.get('mfi'), pd.DataFrame) else pd.DataFrame(),
            'macd': frames.get('macd').copy() if isinstance(frames.get('macd'), pd.DataFrame) else pd.DataFrame(),
            'signal': frames.get('signal').copy() if isinstance(frames.get('signal'), pd.DataFrame) else pd.DataFrame(),
        }
        for label in requested_labels:
            label_frames = {
                'rsi': self._p10_multi_interval_single_label_frame(normalized_frames['rsi'], label),
                'rsi_ma': self._p10_multi_interval_single_label_frame(normalized_frames['rsi_ma'], label),
                'mfi': self._p10_multi_interval_single_label_frame(normalized_frames['mfi'], label),
                'macd': self._p10_multi_interval_single_label_frame(normalized_frames['macd'], label),
                'signal': self._p10_multi_interval_single_label_frame(normalized_frames['signal'], label),
            }
            if not self._p10_multi_interval_has_data(label_frames):
                continue
            dates = self._p10_multi_interval_dates(label_frames)
            if not dates:
                continue
            panel = self._p10_create_multi_interval_panel(symbol, label)
            self._p10_render_multi_interval_oscillator_plot(
                panel['rsi_plot'],
                panel['rsi_axis'],
                label_frames['rsi'],
                label_frames['rsi_ma'],
                dates,
                [label],
                upper_line=P10_MULTI_INTERVAL_RSI_OVERBOUGHT,
                lower_line=P10_MULTI_INTERVAL_RSI_OVERSOLD,
            )
            self._p10_render_multi_interval_oscillator_plot(
                panel['mfi_plot'],
                panel['mfi_axis'],
                label_frames['mfi'],
                pd.DataFrame(),
                dates,
                [label],
                upper_line=P10_MULTI_INTERVAL_MFI_OVERBOUGHT,
                lower_line=P10_MULTI_INTERVAL_MFI_OVERSOLD,
            )
            self._p10_render_multi_interval_macd_plot(
                panel['macd_plot'],
                panel['macd_axis'],
                label_frames['macd'],
                label_frames['signal'],
                dates,
                [label],
            )
            rendered_labels.append(label)
        if not rendered_labels:
            self.p10_multi_interval_empty_label.show()
            return
        self.p10_multi_interval_frames = {
            'symbol': str(symbol or '').upper().strip(),
            'labels': rendered_labels,
            'rsi': normalized_frames['rsi'],
            'rsi_ma': normalized_frames['rsi_ma'],
            'mfi': normalized_frames['mfi'],
            'macd': normalized_frames['macd'],
            'signal': normalized_frames['signal'],
        }
        self.p10_multi_interval_empty_label.hide()

    def _p10_refresh_multi_interval_views(self, *, force: bool=False) -> None:
        """Refresh the selected timeframe indicators for the active symbol."""
        if not hasattr(self, 'p10_multi_interval_panel_layout'):
            return
        self.p10_multi_interval_labels = self._p10_normalize_multi_interval_labels(self.p10_multi_interval_labels)
        self._p10_update_multi_interval_button_styles()
        labels = list(self.p10_multi_interval_labels)
        self._p10_multi_interval_request_token += 1
        request_token = self._p10_multi_interval_request_token
        symbol_input = getattr(self, 'p10_multi_interval_symbol_input', None)
        input_text = symbol_input.text() if symbol_input is not None else ''
        symbol = str(self.p10_symbol or input_text or 'SPY').upper().strip() or 'SPY'
        self.p10_symbol = symbol
        self._p10_update_multi_interval_button_styles()
        if not labels:
            self._p10_clear_multi_interval_plot()
            self.p10_multi_interval_empty_label.setText('Select one or more timeframes to load RSI, MFI, and MACD panels.')
            self.p10_multi_interval_empty_label.show()
            self._p10_set_multi_interval_status('Select one or more timeframes.', 'muted')
            return
        cached_payloads = {}
        refresh_labels = []
        for label in labels:
            cache_key = self._p10_multi_interval_cache_key(symbol, label)
            cached_payload = self._p10_multi_interval_cache.get(cache_key)
            if isinstance(cached_payload, dict):
                cached_payloads[label] = cached_payload
            if force or not isinstance(cached_payload, dict):
                refresh_labels.append(label)
        frames = {
            'rsi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi', cached_payloads),
            'rsi_ma': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi_ma', cached_payloads),
            'mfi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'mfi', cached_payloads),
            'macd': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd', cached_payloads),
            'signal': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd_signal', cached_payloads),
        }
        if self._p10_multi_interval_has_data(frames):
            self._p10_render_multi_interval_chart(symbol, frames, labels)
            self.p10_multi_interval_empty_label.setText('Select one or more timeframes to load RSI, MFI, and MACD panels.')
        else:
            self._p10_clear_multi_interval_plot()
            self.p10_multi_interval_empty_label.setText('Loading selected timeframe panels...')
            self.p10_multi_interval_empty_label.show()
        if not refresh_labels:
            self._p10_set_multi_interval_status(
                f'Loaded RSI, MFI, and MACD panels for {len(labels)} timeframe(s) from memory cache.',
                'positive',
            )
            return
        self._p10_set_multi_interval_status(
            f'Loading indicator panels for {len(refresh_labels)} timeframe(s)...',
            'info',
        )
        executor = getattr(self, '_p10_multi_interval_executor', None)
        if executor is None:
            return
        for label in refresh_labels:
            executor.submit(self._p10_request_multi_interval_payload, request_token, symbol, label, force)

    def _p10_request_multi_interval_payload(self, request_token: int, symbol: str, label: str, force_refresh: bool=False) -> None:
        """Background worker that fetches one selected indicator payload."""
        try:
            payload = self._p10_fetch_multi_interval_payload(symbol, label, force_refresh=force_refresh)
            self._invoke_main.emit(
                lambda token=request_token, sym=symbol, lbl=label, data=payload: self._p10_apply_multi_interval_payload(token, sym, lbl, data)
            )
        except Exception as exc:
            self._invoke_main.emit(
                lambda token=request_token, sym=symbol, lbl=label, err=str(exc): self._p10_handle_multi_interval_error(token, sym, lbl, err)
            )

    def _p10_fetch_multi_interval_payload(self, symbol: Any, label: Any, *, force_refresh: bool=False) -> Any:
        """Fetch one timeframe dataset for the multi-interval indicator view."""
        period, interval = self._p10_multi_interval_timeframe_map.get(
            label,
            self._p10_multi_interval_timeframe_map['1 Day'],
        )
        payload = self._chart_fetch_payload(
            symbol,
            period=period,
            interval=interval,
            timeframe_label=label,
            include_rsi=False,
            include_ma200=False,
            force_refresh=force_refresh,
        )
        df = payload.get('df') if isinstance(payload, dict) else None
        close_series = df['Close'] if isinstance(df, pd.DataFrame) and 'Close' in df else pd.Series(dtype=float)
        macd_line, signal_line, _ = self._p10_calculate_macd(close_series)
        payload['rsi'] = self._p10_calculate_rsi(close_series)
        payload['rsi_ma'] = self._p10_calculate_rsi_ma(payload['rsi'])
        payload['mfi'] = self._p10_calculate_mfi(df)
        payload['macd'] = macd_line
        payload['macd_signal'] = signal_line
        return payload

    def _p10_apply_multi_interval_payload(self, request_token: int, symbol: str, label: str, payload: Any) -> None:
        """Merge one fetched timeframe payload into the indicator view."""
        active_symbol = str(self.p10_symbol or 'SPY').upper().strip() or 'SPY'
        if request_token != self._p10_multi_interval_request_token or label not in self.p10_multi_interval_labels or symbol != active_symbol:
            return
        if isinstance(payload, dict):
            self._p10_multi_interval_cache[self._p10_multi_interval_cache_key(symbol, label)] = payload
        labels = list(self.p10_multi_interval_labels)
        frames = {
            'rsi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi'),
            'rsi_ma': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi_ma'),
            'mfi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'mfi'),
            'macd': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd'),
            'signal': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd_signal'),
        }
        if self._p10_multi_interval_has_data(frames):
            self._p10_render_multi_interval_chart(symbol, frames, labels)
            loaded_count = sum(
                1
                for current_label in labels
                if isinstance(self._p10_multi_interval_cache.get(self._p10_multi_interval_cache_key(symbol, current_label)), dict)
            )
            self._p10_set_multi_interval_status(
                f'Loaded timeframe panels for {loaded_count}/{len(labels)} timeframe(s).',
                'positive' if loaded_count >= len(labels) else 'info',
            )
            return
        self._p10_clear_multi_interval_plot()
        self.p10_multi_interval_empty_label.setText('No timeframe panel data could be loaded.')
        self.p10_multi_interval_empty_label.show()
        self._p10_set_multi_interval_status('No multi-interval timeframe data was available.', 'warning')

    def _p10_handle_multi_interval_error(self, request_token: int, symbol: str, label: str, message: str) -> None:
        """Show a fetch failure for one selected indicator timeframe."""
        active_symbol = str(self.p10_symbol or 'SPY').upper().strip() or 'SPY'
        if request_token != self._p10_multi_interval_request_token or label not in self.p10_multi_interval_labels or symbol != active_symbol:
            return
        labels = list(self.p10_multi_interval_labels)
        frames = {
            'rsi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi'),
            'rsi_ma': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'rsi_ma'),
            'mfi': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'mfi'),
            'macd': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd'),
            'signal': self._p10_build_multi_interval_indicator_frame(symbol, labels, 'macd_signal'),
        }
        if self._p10_multi_interval_has_data(frames):
            self._p10_render_multi_interval_chart(symbol, frames, labels)
        else:
            self._p10_clear_multi_interval_plot()
            self.p10_multi_interval_empty_label.setText('No timeframe panel data could be loaded.')
            self.p10_multi_interval_empty_label.show()
        self._p10_set_multi_interval_status(f'{label} timeframe load failed: {message}', 'negative')

    def _p10_apply_multi_interval_theme(self) -> None:
        """Restyle the multi-interval timeframe panels after a theme change."""
        if hasattr(self, 'p10_multi_interval_symbol_label'):
            self.p10_multi_interval_symbol_label.setStyleSheet(
                f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};'
            )
        if hasattr(self, 'p10_multi_interval_status_label'):
            self._p10_set_multi_interval_status(
                self.p10_multi_interval_status_label.text(),
                self.p10_multi_interval_status_label.property('bt_status') or 'muted',
            )
        self._p10_update_multi_interval_button_styles()
        frames = getattr(self, 'p10_multi_interval_frames', {})
        if self._p10_multi_interval_has_data(frames):
            self._p10_render_multi_interval_chart(
                frames.get('symbol', self.p10_symbol),
                {
                    'rsi': frames.get('rsi'),
                    'rsi_ma': frames.get('rsi_ma'),
                    'mfi': frames.get('mfi'),
                    'macd': frames.get('macd'),
                    'signal': frames.get('signal'),
                },
                frames.get('labels', self.p10_multi_interval_labels),
            )

    def _p10_update_indicator_button_styles(self) -> None:
        """Highlight active indicator buttons."""
        for name, btn in self._p10_indicator_buttons.items():
            is_active = name in self.p10_active_indicators
            btn.blockSignals(True)
            btn.setChecked(is_active)
            btn.blockSignals(False)
            self.set_theme_variant(btn, 'positive' if is_active else None)
            btn.setProperty('bt_checked', 'true' if is_active else 'false')
            self._repolish_widget(btn)

    def _p10_fib_is_active(self) -> bool:
        """Return whether the Fibonacci retracement indicator is enabled."""
        return P10_FIB_RETRACEMENT_LABEL in getattr(self, 'p10_active_indicators', [])

    def _p10_fib_manual_anchor(self, context_key: str | None=None) -> dict[str, Any] | None:
        """Return the saved manual Fibonacci anchor for one context."""
        key = context_key or self._p10_fib_context_key()
        anchor = getattr(self, 'p10_fib_manual_by_context', {}).get(key)
        return dict(anchor) if isinstance(anchor, dict) else None

    def _p10_update_fib_controls(self, status_text: str | None=None) -> None:
        """Synchronize Fibonacci controls with active indicator and mode state."""
        controls = getattr(self, 'p10_fib_controls_widget', None)
        if controls is None:
            return
        is_active = self._p10_fib_is_active()
        controls.setVisible(is_active)
        mode = self.p10_fib_mode if self.p10_fib_mode in ('auto', 'manual') else 'auto'
        for button, checked, variant in (
            (getattr(self, 'p10_fib_auto_btn', None), mode == 'auto', 'accent'),
            (getattr(self, 'p10_fib_manual_btn', None), mode == 'manual', 'positive'),
        ):
            if button is None:
                continue
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
            self.set_theme_variant(button, variant if checked and is_active else None)
            button.setEnabled(is_active)
            button.setProperty('bt_checked', 'true' if checked and is_active else 'false')
            self._repolish_widget(button)
        lookback_spin = getattr(self, 'p10_fib_lookback_spin', None)
        self._p10_sync_fib_lookback_controls()
        if lookback_spin is not None:
            lookback_spin.setEnabled(is_active and mode == 'auto')
        lookback_slider = getattr(self, 'p10_fib_lookback_slider', None)
        if lookback_slider is not None:
            lookback_slider.setEnabled(is_active and mode == 'auto')
        set_button = getattr(self, 'p10_fib_set_anchors_btn', None)
        if set_button is not None:
            set_button.setEnabled(is_active and mode == 'manual' and bool(self._p10_chart_rows))
            self.set_theme_variant(set_button, 'warning' if getattr(self, 'p10_fib_capture_active', False) else None)
            self._repolish_widget(set_button)
        reset_button = getattr(self, 'p10_fib_reset_auto_btn', None)
        if reset_button is not None:
            reset_button.setEnabled(is_active)
        label = getattr(self, 'p10_fib_status_label', None)
        if label is not None:
            label.setText(status_text if status_text is not None else self._p10_fib_status_text())

    def _p10_fib_status_text(self) -> str:
        """Return a compact status string for the Fibonacci control strip."""
        if not self._p10_fib_is_active():
            return ''
        if self.p10_fib_mode == 'manual':
            if self.p10_fib_capture_active:
                return 'Manual: click end anchor' if self.p10_fib_capture_start else 'Manual: click start anchor'
            if self._p10_fib_manual_anchor() is not None:
                return 'Manual: drag Start/End anchors'
            return 'Manual: set anchors'
        return f'Auto: last {int(self.p10_fib_lookback)} candles'

    def _p10_set_fib_mode(self, mode: Any) -> None:
        """Switch Fibonacci retracement between auto and manual modes."""
        text = str(mode or '').strip().lower()
        if text not in ('auto', 'manual'):
            text = 'auto'
        self.p10_fib_mode = text
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_update_fib_controls()
        self._p10_save_state()
        self._p10_refresh_fib_after_settings_change()

    def _p10_on_fib_lookback_changed(self, value: Any) -> None:
        """Persist and apply the auto Fibonacci lookback."""
        self._p10_set_fib_lookback(value)

    def _p10_on_fib_lookback_slider_changed(self, value: Any) -> None:
        """Persist and apply the auto Fibonacci lookback from the slider."""
        self._p10_set_fib_lookback(value)

    def _p10_sync_fib_lookback_controls(self) -> None:
        """Synchronize Fibonacci lookback spinbox and slider under a guard."""
        if getattr(self, '_p10_fib_lookback_sync', False):
            return
        self._p10_fib_lookback_sync = True
        try:
            value = int(getattr(self, 'p10_fib_lookback', P10_FIB_DEFAULT_LOOKBACK))
            for widget_name in ('p10_fib_lookback_spin', 'p10_fib_lookback_slider'):
                widget = getattr(self, widget_name, None)
                if widget is None:
                    continue
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        finally:
            self._p10_fib_lookback_sync = False

    def _p10_set_fib_lookback(self, value: Any, *, persist: bool=True, refresh: bool=True) -> None:
        """Clamp, store, and optionally apply the Fibonacci auto lookback."""
        if getattr(self, '_p10_fib_lookback_sync', False):
            return
        try:
            lookback = int(value)
        except (TypeError, ValueError):
            lookback = P10_FIB_DEFAULT_LOOKBACK
        self.p10_fib_lookback = max(P10_FIB_MIN_LOOKBACK, min(P10_FIB_MAX_LOOKBACK, lookback))
        self._p10_sync_fib_lookback_controls()
        self._p10_update_fib_controls()
        if persist:
            self._p10_save_state()
        if refresh:
            self._p10_refresh_fib_after_settings_change()

    def _p10_start_fib_anchor_capture(self) -> None:
        """Begin two-click manual Fibonacci anchor capture."""
        if not self._p10_chart_rows:
            self._p10_update_fib_controls('Manual: load candles first')
            return
        self.p10_fib_mode = 'manual'
        self.p10_fib_capture_active = True
        self.p10_fib_capture_start = None
        self._p10_clear_fib_handles()
        self._p10_update_fib_controls('Manual: click start anchor')
        self._p10_save_state()

    def _p10_reset_fib_auto(self) -> None:
        """Clear the current manual Fibonacci context and return to auto mode."""
        key = self._p10_fib_context_key()
        if key:
            self.p10_fib_manual_by_context.pop(key, None)
        self.p10_fib_mode = 'auto'
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_clear_fib_handles()
        self._p10_update_fib_controls()
        self._p10_save_state()
        self._p10_refresh_fib_after_settings_change()

    def _p10_refresh_fib_after_settings_change(self) -> None:
        """Refresh Fibonacci presentation after a settings-only change."""
        if not self._p10_chart_rows:
            self._p10_clear_fib_retracement()
            return
        if self._p10_playback_running or self._p10_playback_index < len(self._p10_chart_rows) - 1:
            self._p10_render_playback_frame()
            return
        current_range = self._p10_get_current_x_range()
        self._p10_refresh_chart_presentation()
        if self.p10_auto_follow:
            self._p10_apply_auto_x_range(current_range)
        else:
            self._p10_apply_auto_y_range(self._p10_get_current_x_range() or current_range or self._p10_manual_x_range)

    def _p10_toggle_indicator(self, name: Any, checked: Any=False) -> None:
        """Toggle an indicator panel without refetching chart data."""
        if checked:
            if name not in self.p10_active_indicators:
                self.p10_active_indicators.append(name)
        else:
            self.p10_active_indicators = [indicator for indicator in self.p10_active_indicators if indicator != name]
        self.p10_active_indicators = [indicator for indicator in P10_INDICATOR_ORDER if indicator in self.p10_active_indicators]
        self._p10_update_indicator_button_styles()
        self._p10_update_fib_controls()
        self._p10_save_state()
        if self._p10_chart_rows:
            if self._p10_playback_running or self._p10_playback_index < len(self._p10_chart_rows) - 1:
                self._p10_render_playback_frame()
                return
            current_range = self._p10_get_current_x_range()
            self._p10_refresh_chart_presentation()
            if self.p10_auto_follow:
                self._p10_apply_auto_x_range(current_range)
            else:
                self._p10_restore_manual_x_range()
                self._p10_apply_auto_y_range(self._p10_get_current_x_range() or current_range or self._p10_manual_x_range)
            self._p10_show_row_details(len(self._p10_chart_rows) - 1)
        else:
            self._p10_render_indicator_panels()
            self._p10_update_indicator_panel_labels()

    def _p10_set_timeframe(self, label: Any, *_: Any) -> None:
        """Switch the active chart timeframe and refresh."""
        if label not in self._p10_timeframe_map or label == self.p10_timeframe_label:
            self._p10_update_timeframe_button_styles()
            return
        self._p10_pause_playback()
        self.p10_timeframe_label = label
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_clear_fib_handles()
        self._p10_update_timeframe_button_styles()
        self._p10_update_fib_controls()
        self._p10_save_state()
        self._p10_chart_dirty = False
        self._p10_refresh_chart()

    def _p10_set_compare_interval(self, label: Any, *_: Any) -> None:
        """Switch the compare chart interval between day and week views."""
        if label not in self._p10_compare_interval_map or label == self.p10_compare_interval_label:
            self._p10_update_timeframe_button_styles()
            return
        self.p10_compare_interval_label = str(label)
        self._p10_compare_dirty = True
        self._p10_update_timeframe_button_styles()
        self._p10_save_state()
        self._p10_refresh_compare_preset_controls()
        if self._p10_active_subtab_key() == 'compare':
            self._p10_refresh_compare_view(force=True)

    def _p10_set_compare_range(self, label: Any, *_: Any) -> None:
        """Switch the compare chart lookback range."""
        text = str(label or '').strip().upper()
        if text not in self._p10_compare_range_map or text == self.p10_compare_range_label:
            self._p10_update_timeframe_button_styles()
            return
        self.p10_compare_range_label = text
        self._p10_compare_dirty = True
        self._p10_update_timeframe_button_styles()
        self._p10_save_state()
        self._p10_refresh_compare_preset_controls()
        if self._p10_active_subtab_key() == 'compare':
            self._p10_refresh_compare_view(force=True)

    def _p10_load_from_input(self) -> None:
        """Load the ticker from the input field."""
        symbol = self.p10_symbol_input.text().upper().strip()
        if not symbol:
            return
        self.p10_symbol = symbol
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_clear_fib_handles()
        self.p10_symbol_input.setText(symbol)
        self._p10_update_fib_controls()
        if hasattr(self, 'p10_multi_interval_symbol_input'):
            self.p10_multi_interval_symbol_input.setText(symbol)
        if self._p10_active_subtab_key() == 'multiintervals':
            self._p10_chart_dirty = True
            self._p10_refresh_multi_interval_views(force=True)
            return
        self._p10_refresh_chart()

    def _p10_add_watchlist_symbol(self) -> None:
        """Add a custom chart watchlist symbol."""
        symbol = self.p10_watchlist_input.text().upper().strip()
        if not symbol:
            return
        if symbol not in self.p10_custom_watchlist:
            self.p10_custom_watchlist.append(symbol)
            self.p10_custom_watchlist.sort()
            self._p10_save_state()
            self._p10_rebuild_watchlists()
        self.p10_watchlist_input.clear()

    def _p10_remove_watchlist_symbol(self) -> None:
        """Remove the selected custom chart watchlist symbol."""
        item = self.p10_watchlist.currentItem()
        if not item:
            return
        symbol = item.data(Qt.ItemDataRole.UserRole)
        if symbol in self.p10_custom_watchlist:
            self.p10_custom_watchlist.remove(symbol)
            self._p10_save_state()
            self._p10_rebuild_watchlists()

    def _p10_watchlist_clicked(self, item: Any) -> None:
        """Load a chart symbol from the watchlist."""
        symbol = item.data(Qt.ItemDataRole.UserRole)
        if symbol:
            self.p10_symbol_input.setText(symbol)
            self.p10_symbol = symbol
            self._p10_refresh_chart()

    def _p10_watchlist_selection_changed(self, current: Any, previous: Any=None) -> None:
        """Auto-load the selected symbol when the user moves through sidebar lists."""
        if self._p10_watchlist_sync_guard or current is None:
            return
        symbol = current.data(Qt.ItemDataRole.UserRole)
        if not symbol or symbol == self.p10_symbol:
            return
        self._p10_watchlist_clicked(current)

    def _p10_rebuild_watchlists(self) -> None:
        """Rebuild custom watchlist and portfolio list sections."""
        self._p10_watchlist_sync_guard = True
        try:
            watchlist_widget = getattr(self, 'p10_watchlist', None)
            portfolio_widget = getattr(self, 'p10_portfolio_list', None)
            if watchlist_widget is not None:
                watchlist_widget.clear()
            if portfolio_widget is None:
                return
            portfolio_widget.clear()
            portfolio_symbols = []
            for ticker in self.tickers:
                text = str(ticker or '').upper().strip()
                if text and text not in portfolio_symbols:
                    portfolio_symbols.append(text)
            portfolio_symbols = sorted(
                portfolio_symbols,
                key=lambda symbol: (
                    self._p10_portfolio_gain_pct(symbol) is None,
                    -(self._p10_portfolio_gain_pct(symbol) or 0.0),
                    symbol,
                ),
            )
            if watchlist_widget is not None:
                watchlist_row = 0
                for row, symbol in enumerate(self.p10_custom_watchlist):
                    item = QListWidgetItem(symbol)
                    item.setData(Qt.ItemDataRole.UserRole, symbol)
                    item.setForeground(self.theme_qcolor('text_secondary'))
                    watchlist_widget.addItem(item)
                    if symbol == self.p10_symbol:
                        watchlist_row = row
                if watchlist_widget.count():
                    watchlist_widget.setCurrentRow(watchlist_row)
            portfolio_row = 0
            for row, symbol in enumerate(portfolio_symbols):
                item = QListWidgetItem(self._p10_portfolio_list_label(symbol))
                item.setData(Qt.ItemDataRole.UserRole, symbol)
                item.setForeground(self.theme_qcolor('accent'))
                portfolio_widget.addItem(item)
                if symbol == self.p10_symbol:
                    portfolio_row = row
            if portfolio_widget.count():
                portfolio_widget.setCurrentRow(portfolio_row)
        finally:
            self._p10_watchlist_sync_guard = False
        if getattr(self, '_mc_initialized', False):
            self._mc_sync_grid(self._mc_get_active_symbols())
            if self._p10_active_subtab_key() == 'multicharts':
                self._mc_on_show()

    def _p10_refresh_chart(self, force_refresh: bool=False) -> None:
        """Refresh the dedicated chart page for the active symbol/timeframe."""
        self._p10_pause_playback()
        symbol = str(self.p10_symbol or self.p10_symbol_input.text() or 'SPY').upper().strip()
        if not symbol:
            symbol = 'SPY'
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
        self._p10_chart_dirty = False
        if self.p10_auto_follow:
            self._p10_pending_x_range = self._p10_get_current_x_range()
        else:
            self._p10_pending_x_range = self._p10_get_current_x_range() or self._p10_manual_x_range
        self._p10_request_seq += 1
        request_id = self._p10_request_seq
        self._p10_active_request = request_id
        self.p10_load_btn.setEnabled(False)
        self._p10_set_status(f'Loading {symbol} {self.p10_timeframe_label}...', 'info')

        def _run() -> None:
            """Fetch chart data in the background."""
            try:
                data = self._p10_fetch_chart_payload(symbol, self.p10_timeframe_label, force_refresh=bool(force_refresh))
                self._invoke_main.emit(lambda payload=data, req=request_id: self._p10_apply_chart_payload(req, payload))
            except Exception as exc:
                self._invoke_main.emit(lambda err=str(exc), req=request_id: self._p10_handle_chart_error(req, err))
        threading.Thread(target=_run, daemon=True).start()

    def _p10_refresh_compare_view(self, *, force: bool=False) -> None:
        """Refresh the compare chart for the saved symbol list."""
        compare_range_label, compare_period, compare_interval_label, default_interval = self._p10_get_compare_request_settings()
        if not self.p10_compare_symbols:
            self._p10_compare_request_seq += 1
            self._p10_compare_active_request = self._p10_compare_request_seq
            self._p10_compare_dirty = False
            self.p10_compare_df = None
            self.p10_compare_errors = []
            self.p10_compare_interval = default_interval
            self.p10_compare_empty_label.setText('Add one or more tickers to compare normalized performance.')
            self._p10_render_compare_chart(None, default_interval, force=True)
            self._p10_set_compare_status('Add symbols to compare.', 'muted')
            return
        if (not force) and (not self._p10_compare_dirty):
            self._p10_sync_active_status_to_status_bar()
            return
        compare_symbols = list(self.p10_compare_symbols)
        self._p10_compare_request_seq += 1
        request_id = self._p10_compare_request_seq
        self._p10_compare_active_request = request_id
        active_interval = default_interval
        cached_frame = self._p10_build_compare_frame(compare_symbols, compare_interval_label, compare_range_label)
        if force:
            refresh_symbols = list(compare_symbols)
        else:
            refresh_symbols = [
                symbol
                for symbol in compare_symbols
                if self._p10_compare_series_cache.get(self._p10_compare_cache_key(symbol, compare_interval_label, compare_range_label)) is None
                or getattr(self._p10_compare_series_cache.get(self._p10_compare_cache_key(symbol, compare_interval_label, compare_range_label)), 'empty', True)
            ]
        if isinstance(cached_frame, pd.DataFrame) and not cached_frame.empty:
            self.p10_compare_df = cached_frame.copy()
            self.p10_compare_interval = active_interval
            self.p10_compare_empty_label.setText('Add one or more tickers to compare normalized performance.')
            self._p10_render_compare_chart(self.p10_compare_df, active_interval, force=force)
        elif force or refresh_symbols:
            self.p10_compare_df = None
            self._p10_render_compare_chart(None, active_interval, force=True)
        if (not force) and (not refresh_symbols) and isinstance(cached_frame, pd.DataFrame) and list(cached_frame.columns) == compare_symbols:
            self._p10_compare_dirty = False
            self.p10_compare_errors = []
            self._p10_set_compare_status(
                f'Loaded {len(compare_symbols)} compare line(s) from memory cache for {compare_range_label} ({compare_interval_label}).',
                'positive',
            )
            return

        if isinstance(cached_frame, pd.DataFrame) and not cached_frame.empty:
            self._p10_set_compare_status(
                f'Showing cached compare data while refreshing {len(refresh_symbols or compare_symbols)} ticker(s)...',
                'info',
            )
        else:
            self._p10_set_compare_status(f'Loading compare data for {len(compare_symbols)} ticker(s)...', 'info')

        def _run() -> None:
            """Fetch comparison histories in the background."""
            series_map = {}
            errors = []
            pending_symbols = list(refresh_symbols)
            if (not force) and pending_symbols:
                uncached_symbols = []
                for symbol in pending_symbols:
                    try:
                        cached_symbol_frame = self._chart_load_cached_frame(symbol, period=compare_period, interval=active_interval)
                        if cached_symbol_frame is None or cached_symbol_frame.empty:
                            uncached_symbols.append(symbol)
                            continue
                        series_map[symbol] = self._p10_build_compare_series_from_frame(symbol, cached_symbol_frame)
                    except Exception:
                        uncached_symbols.append(symbol)
                pending_symbols = uncached_symbols
            if len(pending_symbols) >= 2:
                try:
                    batch_frames, batch_missing = self._p10_fetch_compare_frames_batch(pending_symbols, period=compare_period, interval=active_interval)
                    for symbol, batch_frame in batch_frames.items():
                        series_map[symbol] = self._p10_build_compare_series_from_frame(symbol, batch_frame)
                    pending_symbols = batch_missing
                except Exception as exc:
                    errors.append(f'Batch download: {exc}')
            for symbol in pending_symbols:
                try:
                    payload = self._p10_fetch_compare_payload(
                        symbol,
                        period=compare_period,
                        interval=active_interval,
                        interval_label=compare_interval_label,
                        range_label=compare_range_label,
                        force_refresh=True,
                    )
                    series_map[symbol] = self._p10_build_compare_series(symbol, payload)
                except Exception as exc:
                    errors.append(f'{symbol}: {exc}')
            result = {
                'symbols': compare_symbols,
                'interval': active_interval,
                'interval_label': compare_interval_label,
                'range_label': compare_range_label,
                'series_map': series_map,
                'errors': errors,
            }
            self._invoke_main.emit(lambda payload=result, req=request_id: self._p10_apply_compare_payload(req, payload))
        executor = getattr(self, '_p10_compare_executor', None)
        if executor is not None:
            executor.submit(_run)
            return
        threading.Thread(target=_run, daemon=True).start()

    def _p10_fetch_compare_payload(
        self,
        symbol: Any,
        *,
        period: Any,
        interval: Any,
        interval_label: Any,
        range_label: Any,
        force_refresh: bool=False,
    ) -> Any:
        """Fetch one comparison dataset without technical-indicator calculations."""
        return self._chart_fetch_payload(
            symbol,
            period=period,
            interval=interval,
            timeframe_label=f'{range_label} ({interval_label})',
            include_rsi=False,
            include_ma200=False,
            force_refresh=force_refresh,
        )

    def _p10_build_compare_series_from_frame(self, symbol: str, df: Any) -> pd.Series:
        """Normalize one close-price frame into percentage return from timeframe start."""
        if df is None or getattr(df, 'empty', True) or 'Close' not in df.columns:
            raise ValueError('No chart data returned.')
        close_series = pd.to_numeric(df['Close'], errors='coerce').dropna()
        if close_series.empty:
            raise ValueError('No close prices returned.')
        close_series.index = self._p10_normalize_datetime_index(close_series.index)
        close_series = close_series[~close_series.index.duplicated(keep='last')].sort_index()
        if close_series.empty:
            raise ValueError('No valid timestamps returned.')
        start_value = float(close_series.iloc[0])
        if not math.isfinite(start_value) or start_value == 0.0:
            raise ValueError('Invalid starting price.')
        normalized = ((close_series.astype(float) / start_value) - 1.0) * 100.0
        normalized.name = str(symbol or '').upper().strip()
        return normalized

    def _p10_build_compare_series(self, symbol: str, payload: Any) -> pd.Series:
        """Normalize one close-price history into percentage return from timeframe start."""
        df = payload.get('df') if isinstance(payload, dict) else None
        return self._p10_build_compare_series_from_frame(symbol, df)

    def _p10_apply_compare_payload(self, request_id: Any, payload: Any) -> None:
        """Render compare data if it belongs to the latest compare request."""
        if request_id != self._p10_compare_active_request:
            return
        errors = list(payload.get('errors', [])) if isinstance(payload, dict) else []
        symbols = list(payload.get('symbols', [])) if isinstance(payload, dict) else []
        if errors and hasattr(self, '_record_data_health_event'):
            self._record_data_health_event(
                'Compare charts',
                severity='warning',
                source='yfinance/cache',
                freshness='partial',
                reason=f'{len(errors)} compare ticker(s) failed.',
                symbols=symbols,
                errors=errors,
            )
        interval_label = str(payload.get('interval_label', self.p10_compare_interval_label) or self.p10_compare_interval_label) if isinstance(payload, dict) else self.p10_compare_interval_label
        range_label = str(payload.get('range_label', self.p10_compare_range_label) or self.p10_compare_range_label) if isinstance(payload, dict) else self.p10_compare_range_label
        series_map = dict(payload.get('series_map', {})) if isinstance(payload, dict) else {}
        interval = str(payload.get('interval', self.p10_compare_interval) or self.p10_compare_interval) if isinstance(payload, dict) else self.p10_compare_interval
        for symbol, series in series_map.items():
            if series is None or getattr(series, 'empty', True):
                continue
            normalized = pd.Series(series).copy()
            normalized.name = str(symbol or '').upper().strip()
            self._p10_compare_series_cache[self._p10_compare_cache_key(symbol, interval_label, range_label)] = normalized
        frame = self._p10_build_compare_frame(symbols, interval_label, range_label, fresh_series=series_map)
        self.p10_compare_errors = errors
        self.p10_compare_interval = interval
        self._p10_compare_dirty = False
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            self.p10_compare_df = frame.copy()
            self.p10_compare_empty_label.setText('Add one or more tickers to compare normalized performance.')
            self._p10_render_compare_chart(self.p10_compare_df, interval)
            status_text = f'Loaded {len(self.p10_compare_df.columns)} compare line(s) for {range_label} ({interval_label}).'
            status_type = 'positive'
            if errors:
                status_text = f'{status_text} {len(errors)} ticker(s) failed.'
                status_type = 'warning'
            self._p10_set_compare_status(status_text, status_type)
            return
        self.p10_compare_df = None
        if errors:
            self.p10_compare_empty_label.setText('No compare data could be loaded for the saved symbols.')
            self._p10_render_compare_chart(None, interval, force=True)
            self._p10_set_compare_status(f'Compare load failed for {len(errors)} ticker(s).', 'negative')
            return
        self.p10_compare_empty_label.setText('No compare data was available for the selected symbols.')
        self._p10_render_compare_chart(None, interval, force=True)
        self._p10_set_compare_status(f'No compare data loaded for {len(symbols)} ticker(s).', 'warning')

    def _p10_render_compare_chart(self, frame: Any, interval: Any, force: bool=False) -> None:
        """Render the multi-symbol normalized compare chart."""
        plot_item = self.p10_compare_plot.getPlotItem()
        plot_item.hideAxis('left')
        plot_item.showAxis('right')
        plot_item.showAxis('bottom')
        self.p10_compare_axis.set_dates([], interval)
        if self._p10_compare_zero_line is not None:
            self._p10_compare_zero_line.setPen(self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            self._p10_clear_compare_plot_items()
            self.p10_compare_empty_label.show()
            return
        render_signature = self._p10_build_compare_render_signature(frame, interval)
        if (not force) and render_signature == self._p10_compare_render_signature:
            self.p10_compare_empty_label.hide()
            if self._p10_compare_zero_line is not None:
                self._p10_compare_zero_line.show()
            return
        self._p10_compare_render_signature = render_signature
        self.p10_compare_empty_label.hide()
        ordered_frame = frame.sort_index().apply(pd.to_numeric, errors='coerce')
        dates = list(ordered_frame.index)
        x_values = list(range(len(dates)))
        self.p10_compare_axis.set_dates(dates, interval)
        active_symbols = [str(symbol) for symbol in ordered_frame.columns]
        if self._p10_compare_zero_line is not None:
            self._p10_compare_zero_line.show()
        for symbol in list(self._p10_compare_plot_items):
            if symbol not in active_symbols:
                self._p10_remove_compare_plot_symbol(symbol)
        right_padding = max(2.0, len(x_values) * 0.06) if x_values else 2.0
        global_min = ordered_frame.min(skipna=True).min(skipna=True)
        global_max = ordered_frame.max(skipna=True).max(skipna=True)
        label_positions: dict[str, float] = {}
        label_points: list[tuple[str, int, float]] = []
        label_lower_bound = None
        label_upper_bound = None
        if pd.notna(global_min) and pd.notna(global_max):
            min_value = float(global_min)
            max_value = float(global_max)
            span = max_value - min_value
            padding = max(1.0, span * 0.12) if span > 0 else max(abs(max_value) * 0.12, 1.0)
            label_lower_bound = min_value - padding
            label_upper_bound = max_value + padding
        self.p10_compare_plot.setUpdatesEnabled(False)
        try:
            for index, symbol in enumerate(active_symbols):
                color = self.theme_series_color(index)
                series = ordered_frame[symbol]
                plot_data_item = self._p10_compare_plot_items.get(symbol)
                if plot_data_item is None:
                    plot_data_item = self.p10_compare_plot.plot([], [], pen=pg.mkPen(color=color, width=2), antialias=False)
                    try:
                        plot_data_item.setClipToView(True)
                    except Exception:
                        pass
                    try:
                        plot_data_item.setDownsampling(auto=True, method='peak')
                    except Exception:
                        pass
                    self._p10_compare_plot_items[symbol] = plot_data_item
                else:
                    plot_data_item.setPen(pg.mkPen(color=color, width=2))
                plot_data_item.setData(x_values, series.to_list(), antialias=False, connect='finite')
                label_item = self._p10_compare_label_items.get(symbol)
                valid_series = series.dropna()
                if valid_series.empty:
                    if label_item is not None:
                        label_item.hide()
                    continue
                last_value = float(valid_series.iloc[-1])
                last_position = ordered_frame.index.get_loc(valid_series.index[-1])
                sign = '+' if last_value > 0 else ''
                if label_item is None:
                    label_item = pg.TextItem(anchor=(0.0, 0.5))
                    try:
                        label_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                    except Exception:
                        pass
                    self.p10_compare_plot.addItem(label_item, ignoreBounds=True)
                    self._p10_compare_label_items[symbol] = label_item
                label_item.setText(f'{symbol} {sign}{last_value:.1f}%', color=color)
                label_points.append((symbol, last_position, last_value))
            if label_points and label_lower_bound is not None and label_upper_bound is not None:
                label_positions = self._p10_layout_compare_label_positions(
                    [(symbol, value) for symbol, _, value in label_points],
                    label_lower_bound,
                    label_upper_bound,
                )
            for symbol, last_position, last_value in label_points:
                label_item = self._p10_compare_label_items.get(symbol)
                if label_item is None:
                    continue
                label_item.setPos(float(last_position) + 0.25, label_positions.get(symbol, last_value))
                label_item.show()
            if x_values:
                self.p10_compare_plot.setXRange(-0.5, float(len(x_values) - 1) + right_padding, padding=0)
            if pd.notna(global_min) and pd.notna(global_max):
                y_min = float(label_lower_bound if label_lower_bound is not None else global_min)
                y_max = float(label_upper_bound if label_upper_bound is not None else global_max)
                self.p10_compare_plot.setYRange(y_min, y_max, padding=0)
        finally:
            self.p10_compare_plot.setUpdatesEnabled(True)

    def _p10_layout_compare_label_positions(self, values: Any, lower_bound: Any, upper_bound: Any) -> dict[str, float]:
        """Stack compare end labels so dense symbol sets still show their latest percentages."""
        pairs = []
        for symbol, value in list(values or []):
            try:
                pairs.append((str(symbol), float(value)))
            except (TypeError, ValueError):
                continue
        if not pairs:
            return {}
        lower = float(lower_bound)
        upper = float(upper_bound)
        if upper < lower:
            lower, upper = upper, lower
        if len(pairs) == 1:
            symbol, value = pairs[0]
            return {symbol: min(max(value, lower), upper)}
        available_span = max(upper - lower, 1.0)
        pixel_height = 480.0
        try:
            plot_item = self.p10_compare_plot.getPlotItem()
            pixel_height = max(float(plot_item.vb.sceneBoundingRect().height()), 1.0)
        except Exception:
            pass
        min_gap = max(
            available_span * (P10_COMPARE_LABEL_MIN_PIXEL_GAP / pixel_height),
            available_span * 0.012,
        )
        min_gap = min(min_gap, available_span / float(len(pairs) - 1))
        placed: list[list[Any]] = []
        for symbol, value in sorted(pairs, key=lambda item: item[1]):
            target = value if not placed else max(value, float(placed[-1][1]) + min_gap)
            placed.append([symbol, target])
        overflow = float(placed[-1][1]) - upper
        if overflow > 0:
            for item in placed:
                item[1] = float(item[1]) - overflow
        underflow = lower - float(placed[0][1])
        if underflow > 0:
            for item in placed:
                item[1] = float(item[1]) + underflow
        return {str(symbol): float(position) for symbol, position in placed}

    def _chart_fetch_payload(self, symbol: Any, *, period: Any, interval: Any, timeframe_label: Any, include_rsi: bool=True, include_ma200: bool=True, force_refresh: bool=False) -> Any:
        """Fetch and normalize a single-chart dataset for any page."""
        df = self._chart_fetch_base_frame(symbol, period=period, interval=interval, force_refresh=force_refresh)
        base_payload = getattr(self, '_p10_last_chart_fetch_payload', {})
        ma200_series = self._p10_fetch_daily_ma200(symbol, df) if include_ma200 else None
        rsi_series = self._p10_calculate_rsi(df['Close']) if include_rsi else None
        rsi_ma_series = self._p10_calculate_rsi_ma(rsi_series) if include_rsi else None
        latest = df.iloc[-1]
        prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else float(latest['Close'])
        last_close = float(latest['Close'])
        change_value = last_close - prev_close
        change_pct = change_value / prev_close * 100 if prev_close else 0.0
        payload = {
            'symbol': symbol,
            'timeframe_label': timeframe_label,
            'period': period,
            'interval': interval,
            'df': df,
            'stats': {
                'open': float(latest['Open']),
                'high': float(latest['High']),
                'low': float(latest['Low']),
                'close': last_close,
                'volume': float(latest.get('Volume', 0.0) or 0.0),
                'change_value': change_value,
                'change_pct': change_pct,
            },
            'rsi': rsi_series,
            'rsi_ma': rsi_ma_series,
            'ma200': ma200_series,
        }
        return attach_market_data_result(
            payload,
            meta=market_data_meta(base_payload),
            errors=market_data_errors(base_payload),
        )

    def _p10_fetch_chart_payload(self, symbol: Any, timeframe_label: Any, *, force_refresh: bool=False) -> Any:
        """Fetch a single chart dataset plus summary stats."""
        period, interval = self._p10_timeframe_map.get(timeframe_label, self._p10_timeframe_map['1 Day'])
        return self._chart_fetch_payload(
            symbol,
            period=period,
            interval=interval,
            timeframe_label=timeframe_label,
            include_rsi=True,
            include_ma200=True,
            force_refresh=force_refresh,
        )

    def _p10_calculate_rsi(self, close_series: Any, period: Any=14) -> Any:
        """Calculate an RSI series from closing prices."""
        closes = pd.Series(close_series).astype(float)
        delta = closes.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - 100 / (1 + rs)
        return rsi.bfill().clip(lower=0, upper=100)

    def _p10_calculate_rsi_ma(self, rsi_series: Any, period: int=14) -> Any:
        """Calculate a simple moving average over an RSI series."""
        rsi = pd.Series(rsi_series).astype(float)
        if rsi.empty:
            return pd.Series(dtype=float)
        return rsi.rolling(period, min_periods=period).mean().bfill().clip(lower=0, upper=100)

    def _p10_calculate_mfi(self, df: Any, period: int=14) -> Any:
        """Calculate an MFI series from OHLCV data."""
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.Series(dtype=float)
        required = ('High', 'Low', 'Close', 'Volume')
        if any(column not in df.columns for column in required):
            return pd.Series(index=getattr(df, 'index', pd.Index([])), dtype=float)
        high = pd.Series(df['High'], index=df.index).astype(float)
        low = pd.Series(df['Low'], index=df.index).astype(float)
        close = pd.Series(df['Close'], index=df.index).astype(float)
        volume = pd.Series(df['Volume'], index=df.index).fillna(0.0).astype(float)
        typical_price = (high + low + close) / 3.0
        raw_money_flow = typical_price * volume
        price_delta = typical_price.diff()
        positive_flow = raw_money_flow.where(price_delta > 0, 0.0)
        negative_flow = raw_money_flow.where(price_delta < 0, 0.0).abs()
        positive_sum = positive_flow.rolling(period, min_periods=period).sum()
        negative_sum = negative_flow.rolling(period, min_periods=period).sum()
        money_ratio = positive_sum / negative_sum.replace(0.0, float('nan'))
        mfi = 100.0 - (100.0 / (1.0 + money_ratio))
        mfi = pd.Series(mfi, index=df.index, dtype=float)
        mfi = mfi.where(~((negative_sum == 0) & (positive_sum > 0)), 100.0)
        mfi = mfi.where(~((positive_sum == 0) & (negative_sum > 0)), 0.0)
        mfi = mfi.where(~((positive_sum == 0) & (negative_sum == 0)), 50.0)
        return mfi.clip(lower=0.0, upper=100.0)

    def _p10_calculate_macd(
        self,
        close_series: Any,
        fast_period: int=12,
        slow_period: int=26,
        signal_period: int=9,
    ) -> tuple[Any, Any, Any]:
        """Calculate MACD, signal, and histogram series from closes."""
        closes = pd.Series(close_series).astype(float)
        if closes.empty:
            empty = pd.Series(dtype=float)
            return empty, empty, empty
        fast_ema = closes.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
        slow_ema = closes.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _p10_fetch_daily_ma200(self, symbol: Any, source_df: Any) -> Any:
        """Build a 200-day moving average aligned to the active chart index."""
        payload = self._get_chart_data_service().fetch_daily_ma200_payload(symbol, source_df)
        return payload.get('series') if isinstance(payload, dict) else pd.Series(index=source_df.index, dtype=float)

    def _p10_portfolio_avg_price(self, symbol: Any) -> Any:
        """Return the user's tracked average purchase price for one symbol."""
        tracker = getattr(self, 'tracker_data', {})
        if not isinstance(tracker, dict):
            return None
        symbol_text = str(symbol or '').upper().strip()
        entry = tracker.get(symbol_text)
        if not isinstance(entry, dict):
            return None
        try:
            shares = float(entry.get('shares', 0) or 0)
            avg_price = float(entry.get('avg_price', 0) or 0)
        except Exception:
            return None
        if not math.isfinite(shares) or not math.isfinite(avg_price) or shares <= 0 or avg_price <= 0:
            return None
        return avg_price

    def _p10_portfolio_current_price(self, symbol: Any) -> Any:
        """Return the latest known price for one tracked portfolio symbol."""
        symbol_text = str(symbol or '').upper().strip()
        if not symbol_text:
            return None
        last_data = getattr(self, 'last_data', None)
        portfolio_quotes = last_data.get('portfolio', {}) if isinstance(last_data, dict) else {}
        quote = portfolio_quotes.get(symbol_text) if isinstance(portfolio_quotes, dict) else None
        if not isinstance(quote, dict):
            return None
        try:
            price = float(quote.get('price', 0) or 0)
        except Exception:
            return None
        if not math.isfinite(price) or price <= 0:
            return None
        return price

    def _p10_portfolio_gain_pct(self, symbol: Any) -> Any:
        """Return the current gain percentage for one tracked portfolio symbol."""
        avg_price = self._p10_portfolio_avg_price(symbol)
        current_price = self._p10_portfolio_current_price(symbol)
        if avg_price is None or current_price is None or avg_price <= 0:
            return None
        gain_pct = ((current_price / avg_price) - 1.0) * 100.0
        if not math.isfinite(gain_pct):
            return None
        return gain_pct

    def _p10_portfolio_list_label(self, symbol: Any) -> str:
        """Return one portfolio sidebar label."""
        return str(symbol or '').upper().strip()

    def _p10_refresh_avg_cost_line(self, symbol: Any, last_close: Any) -> None:
        """Render or remove the user's tracked average-cost line on the main chart."""
        if P10_AVG_PRICE_LABEL not in self.p10_active_indicators:
            self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_avg_cost_line', None))
            self.p10_avg_cost_line = None
            return
        avg_price = self._p10_portfolio_avg_price(symbol)
        if avg_price is None:
            self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_avg_cost_line', None))
            self.p10_avg_cost_line = None
            return
        color_key = 'accent_positive'
        try:
            if float(last_close) < float(avg_price):
                color_key = 'accent_negative'
        except Exception:
            pass
        avg_cost_line = getattr(self, 'p10_avg_cost_line', None)
        if avg_cost_line is None:
            avg_cost_line = pg.InfiniteLine(
                pos=float(avg_price),
                angle=0,
                pen=self.theme_pen(color_key, width=1.5, style=Qt.PenStyle.DashLine),
            )
            self.p10_main_plot.addItem(avg_cost_line)
            self.p10_avg_cost_line = avg_cost_line
        avg_cost_line.setPen(self.theme_pen(color_key, width=1.5, style=Qt.PenStyle.DashLine))
        avg_cost_line.setValue(float(avg_price))

    def _p10_apply_chart_payload(self, request_id: Any, payload: Any) -> None:
        """Render fetched chart payload if it is the latest request."""
        if request_id != self._p10_active_request:
            return
        self._p10_pause_playback()
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload(
                'Charts',
                payload,
                symbols=[payload.get('symbol')] if isinstance(payload, dict) else None,
            )
        df = payload['df']
        symbol = payload['symbol']
        interval = payload['interval']
        stats = payload['stats']
        self.p10_chart_stats = stats
        self.p10_active_interval = interval
        self.p10_chart_df = df
        self.p10_rsi_series = payload.get('rsi')
        self.p10_rsi_ma_series = payload.get('rsi_ma')
        self.p10_ma200_series = payload.get('ma200')
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
        self.p10_symbol_label.setText(symbol)
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_update_fib_controls()
        if hasattr(self, 'p10_multi_interval_symbol_input'):
            self.p10_multi_interval_symbol_input.setText(symbol)
        if hasattr(self, 'p10_multi_interval_symbol_label'):
            self.p10_multi_interval_symbol_label.setText(symbol)
        self._p10_chart_rows = list(df.itertuples())
        self._p10_render_main_chart(stats, interval, payload.get('rsi'), payload.get('rsi_ma'), payload.get('ma200'))
        if self.p10_auto_follow:
            self._p10_apply_auto_x_range(self._p10_pending_x_range)
        else:
            self._p10_restore_manual_x_range()
        self._p10_update_quote_header(stats)
        self._p10_show_row_details(len(self._p10_chart_rows) - 1)
        self.p10_load_btn.setEnabled(True)
        self._p10_save_state()
        self._p10_rebuild_watchlists()
        self._p10_pending_x_range = None
        self._p10_update_indicator_panel_labels()
        self._p10_configure_playback_controls()
        self._set_data_collection_info(data_sources_from_meta(payload, 'yfinance'))
        status_text, status_type = describe_market_data_status(payload, f'Loaded {symbol} {self.p10_timeframe_label}.')
        self._p10_set_status(status_text, status_type)

    def _p10_render_main_chart(
        self,
        stats: Any,
        interval: Any,
        rsi_series: Any=None,
        rsi_ma_series: Any=None,
        ma200_series: Any=None,
        row_limit: int | None=None,
    ) -> None:
        """Render the main candlestick chart and lower indicator panels."""
        if row_limit is None:
            visible_rows = list(self._p10_chart_rows)
        else:
            try:
                limit = int(row_limit)
            except (TypeError, ValueError):
                limit = len(self._p10_chart_rows)
            limit = max(1, min(limit, len(self._p10_chart_rows))) if self._p10_chart_rows else 0
            visible_rows = list(self._p10_chart_rows[:limit])
        visible_count = len(visible_rows)
        points = []
        volume_brushes = []
        volumes = []
        for idx, row in enumerate(visible_rows):
            open_value = float(getattr(row, 'Open'))
            close_value = float(getattr(row, 'Close'))
            low_value = float(getattr(row, 'Low'))
            high_value = float(getattr(row, 'High'))
            volume_value = float(getattr(row, 'Volume', 0.0) or 0.0)
            points.append((idx, open_value, close_value, low_value, high_value))
            volumes.append(volume_value)
            volume_brushes.append(self.theme_brush('chart_volume_up' if close_value >= open_value else 'chart_volume_down'))
        candle_item = CandlestickItem(
            points,
            up_color=self.theme_color('chart_up_candle'),
            down_color=self.theme_color('chart_down_candle'),
        )
        self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_candle_item', None))
        self.p10_candle_item = candle_item
        self.p10_main_plot.addItem(candle_item)
        if ma200_series is not None and row_limit is not None:
            try:
                ma200_series = ma200_series.iloc[:visible_count]
            except Exception:
                ma200_series = pd.Series(ma200_series).iloc[:visible_count]
        if ma200_series is not None:
            ma_line_item = getattr(self, 'p10_ma_line_item', None)
            if ma_line_item is None:
                ma_line_item = self.p10_main_plot.plot([], [], pen=self.theme_pen('chart_ma', width=2.0), antialias=True)
                self.p10_ma_line_item = ma_line_item
            ma_values = [float(value) if not pd.isna(value) else float('nan') for value in ma200_series]
            ma_line_item.setData(list(range(len(ma_values))), ma_values)
        else:
            self._p10_remove_chart_item(self.p10_main_plot, getattr(self, 'p10_ma_line_item', None))
            self.p10_ma_line_item = None
        last_close = float(stats.get('close', 0.0)) if isinstance(stats, dict) else 0.0
        last_price_line = getattr(self, 'p10_last_price_line', None)
        if last_price_line is None:
            last_price_line = pg.InfiniteLine(pos=last_close, angle=0, pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
            self.p10_main_plot.addItem(last_price_line)
            self.p10_last_price_line = last_price_line
        last_price_line.setValue(last_close)
        self._p10_refresh_avg_cost_line(getattr(self, 'p10_symbol', ''), last_close)
        dates = self.p10_chart_df.index.to_list()
        self.p10_chart_axis.set_dates(dates, interval)
        self.p10_volume_axis.set_dates(dates, interval)
        self.p10_rsi_axis.set_dates(dates, interval)
        if volumes:
            volume_item = getattr(self, 'p10_volume_item', None)
            if volume_item is None:
                volume_item = pg.BarGraphItem(x=list(range(len(volumes))), height=volumes, width=0.7, brushes=volume_brushes)
                self.p10_volume_plot.addItem(volume_item)
                self.p10_volume_item = volume_item
            else:
                volume_item.setOpts(x=list(range(len(volumes))), height=volumes, width=0.7, brushes=volume_brushes)
        else:
            self._p10_remove_chart_item(self.p10_volume_plot, getattr(self, 'p10_volume_item', None))
            self.p10_volume_item = None
        if rsi_series is not None and row_limit is not None:
            try:
                rsi_series = rsi_series.iloc[:visible_count]
            except Exception:
                rsi_series = pd.Series(rsi_series).iloc[:visible_count]
        if rsi_ma_series is not None and row_limit is not None:
            try:
                rsi_ma_series = rsi_ma_series.iloc[:visible_count]
            except Exception:
                rsi_ma_series = pd.Series(rsi_ma_series).iloc[:visible_count]
        if rsi_series is not None:
            x_values = list(range(len(rsi_series)))
            y_values = [float(value) if not pd.isna(value) else float('nan') for value in rsi_series]
            rsi_line_item = getattr(self, 'p10_rsi_line_item', None)
            if rsi_line_item is None:
                rsi_line_item = self.p10_rsi_plot.plot([], [], pen=self.theme_pen('chart_rsi', width=2.0), antialias=True)
                self.p10_rsi_line_item = rsi_line_item
            rsi_line_item.setData(x_values, y_values)
            if rsi_ma_series is not None:
                rsi_ma_values = [float(value) if not pd.isna(value) else float('nan') for value in rsi_ma_series]
                rsi_ma_line_item = getattr(self, 'p10_rsi_ma_line_item', None)
                if rsi_ma_line_item is None:
                    rsi_ma_line_item = self.p10_rsi_plot.plot([], [], pen=self.theme_pen('chart_reference', width=1.5, style=Qt.PenStyle.DashLine), antialias=True)
                    self.p10_rsi_ma_line_item = rsi_ma_line_item
                rsi_ma_line_item.setData(x_values, rsi_ma_values)
            else:
                self._p10_remove_chart_item(self.p10_rsi_plot, getattr(self, 'p10_rsi_ma_line_item', None))
                self.p10_rsi_ma_line_item = None
            rsi_upper_line = getattr(self, 'p10_rsi_upper_line', None)
            if rsi_upper_line is None:
                rsi_upper_line = pg.InfiniteLine(pos=70, angle=0, pen=self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine))
                self.p10_rsi_plot.addItem(rsi_upper_line)
                self.p10_rsi_upper_line = rsi_upper_line
            rsi_lower_line = getattr(self, 'p10_rsi_lower_line', None)
            if rsi_lower_line is None:
                rsi_lower_line = pg.InfiniteLine(pos=30, angle=0, pen=self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine))
                self.p10_rsi_plot.addItem(rsi_lower_line)
                self.p10_rsi_lower_line = rsi_lower_line
            self.p10_rsi_plot.setYRange(0, 100, padding=0.02)
        else:
            self._p10_remove_chart_item(self.p10_rsi_plot, getattr(self, 'p10_rsi_line_item', None))
            self._p10_remove_chart_item(self.p10_rsi_plot, getattr(self, 'p10_rsi_ma_line_item', None))
            self._p10_remove_chart_item(self.p10_rsi_plot, getattr(self, 'p10_rsi_upper_line', None))
            self._p10_remove_chart_item(self.p10_rsi_plot, getattr(self, 'p10_rsi_lower_line', None))
            self.p10_rsi_line_item = None
            self.p10_rsi_ma_line_item = None
            self.p10_rsi_upper_line = None
            self.p10_rsi_lower_line = None
        self._p10_refresh_support_resistance_lines(row_limit=row_limit)
        self._p10_refresh_fib_retracement(row_limit=row_limit)
        if row_limit is None:
            self._p10_refresh_chart_presentation()
        else:
            if self.p10_ma_line_item is not None:
                self.p10_ma_line_item.setVisible(ma200_series is not None and '200 MA' in self.p10_active_indicators)
            if self.p10_rsi_line_item is not None:
                self.p10_rsi_line_item.setVisible(rsi_series is not None and 'RSI' in self.p10_active_indicators)
            if self.p10_rsi_ma_line_item is not None:
                self.p10_rsi_ma_line_item.setVisible(rsi_ma_series is not None and 'RSI' in self.p10_active_indicators)
            self._p10_render_indicator_panels()
            self._p10_update_indicator_panel_labels()

    def _p10_render_indicator_panels(self) -> None:
        """Show or hide indicator panels based on active indicators."""
        show_volume = 'Volume' in self.p10_active_indicators
        show_rsi = 'RSI' in self.p10_active_indicators
        self.p10_volume_plot.setVisible(show_volume)
        self.p10_rsi_plot.setVisible(show_rsi)
        self.p10_panels.setStretchFactor(0, 6)
        self.p10_panels.setStretchFactor(1, 2 if show_volume else 0)
        self.p10_panels.setStretchFactor(2, 2 if show_rsi else 0)

    def _p10_handle_chart_error(self, request_id: Any, message: Any) -> None:
        """Show a chart fetch error if it belongs to the latest request."""
        if request_id != self._p10_active_request:
            return
        if hasattr(self, '_record_data_health_exception'):
            self._record_data_health_exception('Charts', message, symbols=[getattr(self, 'p10_symbol', '')])
        self._p10_pause_playback()
        self._p10_set_playback_enabled(False)
        self._p10_update_playback_label()
        self._p10_chart_dirty = True
        self.p10_load_btn.setEnabled(True)
        self._p10_set_status(f'Chart load failed: {message}', 'negative')

    def _p10_update_quote_header(self, stats: Any) -> None:
        """Update the quote and change header."""
        if not stats:
            self.p10_price_label.setText('--')
            self.p10_change_label.setText('--')
            self.p10_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {self.theme_color("text_muted")};')
            self.p10_position_label.setText('Avg --  Gain --')
            self.p10_position_label.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {self.theme_color("text_muted")};')
            return
        close_value = float(stats.get('close', 0.0))
        change_value = float(stats.get('change_value', 0.0))
        change_pct = float(stats.get('change_pct', 0.0))
        change_color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        sign = '+' if change_value >= 0 else ''
        self.p10_price_label.setText(f'${close_value:,.2f}')
        self.p10_change_label.setText(f'{sign}${change_value:,.2f} ({sign}{change_pct:.2f}%)')
        self.p10_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {change_color};')
        avg_price = self._p10_portfolio_avg_price(getattr(self, 'p10_symbol', ''))
        if avg_price is None:
            self.p10_position_label.setText('Avg --  Gain --')
            self.p10_position_label.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {self.theme_color("text_muted")};')
            return
        gain_pct = ((close_value / avg_price) - 1.0) * 100.0 if avg_price > 0 else 0.0
        gain_color = self.theme_color('accent_positive' if gain_pct >= 0 else 'accent_negative')
        gain_sign = '+' if gain_pct >= 0 else ''
        self.p10_position_label.setText(f'Avg ${avg_price:,.2f}  Gain {gain_sign}{gain_pct:.2f}%')
        self.p10_position_label.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {gain_color};')

    def _p10_set_overlay_text(self, key: Any, plot: Any, text: Any, color: Any) -> None:
        """Render a top-right overlay label inside a plot."""
        if not text:
            item = self._p10_overlay_items.pop(key, None)
            if item is not None:
                try:
                    plot.removeItem(item)
                except Exception:
                    pass
            return
        item = self._p10_overlay_items.get(key)
        if item is None:
            item = pg.TextItem(color=color, anchor=(1, 0))
            try:
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            except Exception:
                pass
            plot.addItem(item, ignoreBounds=True)
            self._p10_overlay_items[key] = item
        item.setText(str(text), color=color)

    def _p10_remove_legacy_overlay_item(self, key: Any) -> None:
        """Remove one legacy overlay item if it still exists."""
        item = self._p10_overlay_items.pop(key, None)
        if item is None:
            return
        for plot in (
            getattr(self, 'p10_main_plot', None),
            getattr(self, 'p10_volume_plot', None),
            getattr(self, 'p10_rsi_plot', None),
        ):
            if plot is None:
                continue
            try:
                plot.removeItem(item)
            except Exception:
                pass

    def _p10_line_label_item(
        self,
        item: Any,
        plot: Any,
        text: Any,
        color: Any,
        *,
        anchor: tuple[float, float]=(1, 0.5),
    ) -> Any:
        """Create, update, or remove one text label anchored to a horizontal chart line."""
        if not text:
            self._p10_remove_chart_item(plot, item)
            return None
        if item is None:
            fill = QColor(self.theme_color('chart_bg'))
            fill.setAlpha(230)
            item = pg.TextItem(color=color, anchor=anchor, fill=fill, border=color)
            try:
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            except Exception:
                pass
            plot.addItem(item, ignoreBounds=True)
        item.setText(str(text), color=color)
        try:
            item.setZValue(1000)
        except Exception:
            pass
        try:
            item.show()
        except Exception:
            pass
        return item

    def _p10_clear_indicator_value_overlays(self, keys: Any=None) -> None:
        """Remove legacy in-plot indicator value labels from the chart panels."""
        if keys is None:
            keys = ('ma200', 'avg_cost', 'volume', 'rsi', 'rsi_ma')
        for key in tuple(keys):
            self._p10_remove_legacy_overlay_item(key)

    def _p10_refresh_overlay_positions(self, *_: Any) -> None:
        """Clear legacy value overlays after plot range changes."""
        self._p10_clear_indicator_value_overlays()

    def _p10_series_value_at_row(self, series: Any, row_index: Any=None) -> float | None:
        """Return a finite indicator series value for one row, or the latest available value."""
        if series is None:
            return None
        try:
            values = list(series)
        except Exception:
            return None
        if not values:
            return None
        if row_index is None:
            indexes = list(range(len(values) - 1, -1, -1))
        else:
            try:
                index = int(row_index)
            except (TypeError, ValueError):
                index = len(values) - 1
            indexes = [max(0, min(index, len(values) - 1))]
        for index in indexes:
            value = values[index]
            if pd.isna(value):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                return numeric
        return None

    def _p10_row_close_at(self, row_index: Any=None) -> float:
        """Return the row close for indicator readouts, falling back to chart stats."""
        if self._p10_chart_rows:
            try:
                index = int(row_index) if row_index is not None else len(self._p10_chart_rows) - 1
            except (TypeError, ValueError):
                index = len(self._p10_chart_rows) - 1
            index = max(0, min(index, len(self._p10_chart_rows) - 1))
            try:
                close_value = float(getattr(self._p10_chart_rows[index], 'Close'))
                if math.isfinite(close_value):
                    return close_value
            except (TypeError, ValueError):
                pass
        return float(getattr(self, 'p10_chart_stats', {}).get('close', 0.0) or 0.0)

    def _p10_row_volume_at(self, row_index: Any=None) -> float | None:
        """Return row volume for indicator readouts."""
        if not self._p10_chart_rows:
            return None
        try:
            index = int(row_index) if row_index is not None else len(self._p10_chart_rows) - 1
        except (TypeError, ValueError):
            index = len(self._p10_chart_rows) - 1
        index = max(0, min(index, len(self._p10_chart_rows) - 1))
        try:
            volume_value = float(getattr(self._p10_chart_rows[index], 'Volume', 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        return volume_value if math.isfinite(volume_value) else None

    def _p10_indicator_value_parts(self, row_index: Any=None) -> list[str]:
        """Return compact active indicator values for the OHLC header."""
        parts: list[str] = []
        if P10_SUPPORT_RESISTANCE_LABEL in self.p10_active_indicators:
            levels = getattr(self, 'p10_support_resistance_levels', None)
            if levels is None and self._p10_chart_rows:
                levels = self._p10_calculate_support_resistance(self._p10_rows_for_sr(None))
            try:
                support, resistance = levels or (None, None)
            except (TypeError, ValueError):
                support, resistance = (None, None)
            for prefix, value in (('S', support), ('R', resistance)):
                if value is None:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(numeric):
                    parts.append(f'{prefix} ${numeric:,.2f}')
        if P10_FIB_RETRACEMENT_LABEL in self.p10_active_indicators:
            fib = getattr(self, 'p10_fib_levels', None)
            if not fib and self._p10_chart_rows:
                fib = self._p10_calculate_fib_retracement(None)
            for level in (fib or {}).get('levels', []):
                try:
                    price = float(level['price'])
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(price):
                    parts.append(f"Fib {level.get('label', '')} ${price:,.2f}")
        if '200 MA' in self.p10_active_indicators:
            latest_ma = self._p10_series_value_at_row(self.p10_ma200_series, row_index)
            parts.append(f'MA200 ${latest_ma:,.2f}' if latest_ma is not None else 'MA200 --')
        avg_price = self._p10_portfolio_avg_price(getattr(self, 'p10_symbol', ''))
        close_value = self._p10_row_close_at(row_index)
        if avg_price is not None and P10_AVG_PRICE_LABEL in self.p10_active_indicators:
            gain_pct = ((close_value / avg_price) - 1.0) * 100.0 if avg_price > 0 else 0.0
            gain_sign = '+' if gain_pct >= 0 else ''
            parts.append(f'Avg ${avg_price:,.2f} Gain {gain_sign}{gain_pct:.2f}%')
        if 'Volume' in self.p10_active_indicators:
            volume_value = self._p10_row_volume_at(row_index)
            parts.append(f'Vol {fmt_num(volume_value)}' if volume_value is not None else 'Vol --')
        if 'RSI' in self.p10_active_indicators:
            latest_rsi = self._p10_series_value_at_row(self.p10_rsi_series, row_index)
            latest_rsi_ma = self._p10_series_value_at_row(self.p10_rsi_ma_series, row_index)
            parts.append(f'RSI {latest_rsi:.2f}' if latest_rsi is not None else 'RSI --')
            parts.append(f'RSI MA {latest_rsi_ma:.2f}' if latest_rsi_ma is not None else 'RSI MA --')
        return parts

    def _p10_update_indicator_value_readout(self, row_index: Any=None) -> None:
        """Update the compact active indicator readout beside OHLC."""
        label = getattr(self, 'p10_indicator_values_label', None)
        if label is None:
            return
        readout = ' | '.join(self._p10_indicator_value_parts(row_index))
        label.setText(readout)
        label.setToolTip(readout)

    def _p10_update_indicator_panel_labels(self) -> None:
        """Update active indicator values in the OHLC header readout."""
        self._p10_clear_indicator_value_overlays()
        self._p10_update_indicator_value_readout()

    def _p10_remove_chart_item(self, plot: Any, item: Any) -> None:
        """Best-effort removal of a persisted charts-page plot item."""
        if item is None:
            return
        try:
            plot.removeItem(item)
        except Exception:
            pass

    def _p10_build_volume_brushes(self) -> list[Any]:
        """Return themed volume brushes for the current page-10 dataset."""
        brushes = []
        for row in self._p10_chart_rows:
            open_value = float(getattr(row, 'Open'))
            close_value = float(getattr(row, 'Close'))
            brushes.append(self.theme_brush('chart_volume_up' if close_value >= open_value else 'chart_volume_down'))
        return brushes

    def _p10_refresh_chart_presentation(self) -> None:
        """Refresh chart colors and indicator visibility without rebuilding datasets."""
        candle_item = getattr(self, 'p10_candle_item', None)
        if candle_item is not None:
            candle_item.set_colors(
                self.theme_color('chart_up_candle'),
                self.theme_color('chart_down_candle'),
            )
        ma_line_item = getattr(self, 'p10_ma_line_item', None)
        if ma_line_item is not None:
            ma_line_item.setPen(self.theme_pen('chart_ma', width=2.0))
            ma_line_item.setVisible(self.p10_ma200_series is not None and '200 MA' in self.p10_active_indicators)
        last_price_line = getattr(self, 'p10_last_price_line', None)
        if last_price_line is not None:
            last_price_line.setPen(self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
            last_price_line.setValue(float(getattr(self, 'p10_chart_stats', {}).get('close', 0.0)))
        self._p10_refresh_avg_cost_line(
            getattr(self, 'p10_symbol', ''),
            float(getattr(self, 'p10_chart_stats', {}).get('close', 0.0) or 0.0),
        )
        if self._p10_chart_rows and P10_SUPPORT_RESISTANCE_LABEL in self.p10_active_indicators:
            self._p10_refresh_support_resistance_lines()
        else:
            self._p10_clear_support_resistance_lines()
        if self._p10_chart_rows and P10_FIB_RETRACEMENT_LABEL in self.p10_active_indicators:
            self._p10_refresh_fib_retracement()
        else:
            self._p10_clear_fib_retracement()
        volume_item = getattr(self, 'p10_volume_item', None)
        if volume_item is not None and self._p10_chart_rows:
            try:
                volume_item.setOpts(brushes=self._p10_build_volume_brushes())
            except Exception:
                pass
        rsi_line_item = getattr(self, 'p10_rsi_line_item', None)
        if rsi_line_item is not None:
            rsi_line_item.setPen(self.theme_pen('chart_rsi', width=2.0))
            rsi_line_item.setVisible(self.p10_rsi_series is not None and 'RSI' in self.p10_active_indicators)
        rsi_ma_line_item = getattr(self, 'p10_rsi_ma_line_item', None)
        if rsi_ma_line_item is not None:
            rsi_ma_line_item.setPen(self.theme_pen('chart_reference', width=1.5, style=Qt.PenStyle.DashLine))
            rsi_ma_line_item.setVisible(self.p10_rsi_ma_series is not None and 'RSI' in self.p10_active_indicators)
        rsi_upper_line = getattr(self, 'p10_rsi_upper_line', None)
        if rsi_upper_line is not None:
            rsi_upper_line.setPen(self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine))
        rsi_lower_line = getattr(self, 'p10_rsi_lower_line', None)
        if rsi_lower_line is not None:
            rsi_lower_line.setPen(self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine))
        self._p10_render_indicator_panels()
        self._p10_update_indicator_panel_labels()

    def _apply_charts_page_theme(self) -> None:
        """Refresh charts-page theme-dependent widgets and plots."""
        self.style_plot_widget(self.p10_main_plot)
        self.style_plot_widget(self.p10_volume_plot, show_y_grid=False)
        self.style_plot_widget(self.p10_rsi_plot)
        self.style_plot_widget(self.p10_compare_plot)
        self._p10_apply_multi_interval_theme()
        if getattr(self, '_mc_initialized', False):
            self._mc_apply_theme()
        self.p10_symbol_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p10_price_label.setStyleSheet(f'font-size: 20px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p10_position_label.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {self.theme_color("text_secondary")};')
        self.p10_ohlc_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        if hasattr(self, 'p10_indicator_values_label'):
            self.p10_indicator_values_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        self._p10_set_status(self.p10_status_label.text(), self.p10_status_label.property('bt_status') or 'muted')
        self._p10_set_compare_status(
            self.p10_compare_status_label.text(),
            self.p10_compare_status_label.property('bt_status') or 'muted',
        )
        self._p10_update_quote_header(self.p10_chart_stats or {'close': 0.0, 'change_value': 0.0, 'change_pct': 0.0})
        self._p10_update_auto_button_style()
        self._p10_update_timeframe_button_styles()
        self._p10_update_indicator_button_styles()
        self._p10_update_fib_controls()
        if hasattr(self, 'p10_playback_btn'):
            self.p10_playback_btn.setText('Pause' if self._p10_playback_running else 'Play')
            self.set_theme_variant(self.p10_playback_btn, 'accent' if self._p10_playback_running else None)
            self.p10_playback_btn.setProperty('bt_checked', 'true' if self._p10_playback_running else 'false')
            self._repolish_widget(self.p10_playback_btn)
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        if self._p10_chart_rows:
            if self._p10_playback_index < len(self._p10_chart_rows) - 1:
                self._p10_render_playback_frame()
            else:
                self._p10_refresh_chart_presentation()
        if isinstance(self.p10_compare_df, pd.DataFrame) and not self.p10_compare_df.empty:
            self._p10_render_compare_chart(self.p10_compare_df, self.p10_compare_interval, force=True)
        else:
            self._p10_render_compare_chart(None, self.p10_compare_interval, force=True)
        self._p10_sync_active_status_to_status_bar()

    def _p10_show_row_details(self, row_index: Any) -> None:
        """Update the OHLC readout for a chart row."""
        if not self._p10_chart_rows:
            self.p10_ohlc_label.setText('O --  H --  L --  C --')
            self._p10_update_indicator_value_readout()
            return
        row_index = max(0, min(int(row_index), len(self._p10_chart_rows) - 1))
        row = self._p10_chart_rows[row_index]
        open_value = float(getattr(row, 'Open'))
        high_value = float(getattr(row, 'High'))
        low_value = float(getattr(row, 'Low'))
        close_value = float(getattr(row, 'Close'))
        details = f'O {open_value:,.2f}   H {high_value:,.2f}   L {low_value:,.2f}   C {close_value:,.2f}'
        self.p10_ohlc_label.setText(details)
        self._p10_update_indicator_value_readout(row_index)

    def _p10_on_mouse_moved(self, event: Any) -> None:
        """Track mouse movement to update the OHLC readout like a chart workspace."""
        if not self._p10_chart_rows:
            return
        pos = event[0]
        if not self.p10_main_plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.p10_main_plot.getPlotItem().vb.mapSceneToView(pos)
        index = int(round(mouse_point.x()))
        self._p10_show_row_details(index)

    def _p10_snap_fib_anchor(self, row_index: Any, y_value: Any) -> dict[str, Any] | None:
        """Snap one clicked chart point to the nearest high/low anchor on a candle."""
        if not self._p10_chart_rows:
            return None
        try:
            index = int(round(float(row_index)))
            clicked_price = float(y_value)
        except (TypeError, ValueError):
            return None
        index = max(0, min(index, len(self._p10_chart_rows) - 1))
        row = self._p10_chart_rows[index]
        high_value = self._p10_safe_row_price(row, 'High')
        low_value = self._p10_safe_row_price(row, 'Low')
        if high_value is None or low_value is None:
            return None
        if abs(clicked_price - high_value) <= abs(clicked_price - low_value):
            return {'index': index, 'price': high_value, 'role': 'high'}
        return {'index': index, 'price': low_value, 'role': 'low'}

    def _p10_on_chart_clicked(self, event: Any) -> None:
        """Capture manual Fibonacci anchors from two clicks on the main chart."""
        if not getattr(self, 'p10_fib_capture_active', False):
            return
        if not self._p10_chart_rows:
            self._p10_update_fib_controls('Manual: load candles first')
            return
        mouse_event = event[0] if isinstance(event, (list, tuple)) and event else event
        try:
            pos = mouse_event.scenePos()
        except Exception:
            return
        try:
            if mouse_event.button() != Qt.MouseButton.LeftButton:
                return
        except Exception:
            pass
        if not self.p10_main_plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.p10_main_plot.getPlotItem().vb.mapSceneToView(pos)
        anchor = self._p10_snap_fib_anchor(mouse_point.x(), mouse_point.y())
        if anchor is None:
            self._p10_update_fib_controls('Manual: invalid anchor')
            return
        if self.p10_fib_capture_start is None:
            self.p10_fib_capture_start = anchor
            self._p10_clear_fib_handles()
            self.p10_fib_pending_handle = self._p10_make_fib_handle(anchor, 'Start', 'accent_positive', movable=False)
            self._p10_update_fib_controls('Manual: click end anchor')
            return
        start = self.p10_fib_capture_start
        if int(start.get('index', -1)) == int(anchor.get('index', -1)) and abs(float(start.get('price', 0.0)) - float(anchor.get('price', 0.0))) <= 0.000001:
            self._p10_update_fib_controls('Manual: choose a different end anchor')
            return
        key = self._p10_fib_context_key()
        if not key:
            self._p10_update_fib_controls('Manual: missing chart context')
            return
        self.p10_fib_manual_by_context[key] = {
            'start_index': int(start['index']),
            'start_price': float(start['price']),
            'start_role': str(start['role']),
            'end_index': int(anchor['index']),
            'end_price': float(anchor['price']),
            'end_role': str(anchor['role']),
        }
        self.p10_fib_mode = 'manual'
        self.p10_fib_capture_active = False
        self.p10_fib_capture_start = None
        self._p10_clear_fib_handles()
        self._p10_update_fib_controls(f'Manual: {self.p10_symbol} {self.p10_timeframe_label} anchors saved')
        self._p10_save_state()
        self._p10_refresh_fib_after_settings_change()
