from __future__ import annotations
import math
from typing import Any
from ..compat import *


P10_TIMEFRAME_OPTIONS = [
    ('1 Minute', '7d', '1m'),
    ('5 Minutes', '60d', '5m'),
    ('15 Minutes', '60d', '15m'),
    ('1 Hour', '730d', '1h'),
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

    def _chart_required_span_days(self, period: Any) -> float | None:
        """Convert one yfinance period string into approximate calendar days."""
        text = str(period or '').strip().lower()
        if not text:
            return None
        if text == 'max':
            return None
        for suffix, multiplier in P10_CACHE_PERIOD_DAY_MAP.items():
            if text.endswith(suffix):
                number_text = text[:-len(suffix)].strip()
                try:
                    return float(number_text) * multiplier
                except Exception:
                    return None
        return None

    def _chart_cache_covers_period(self, df: Any, period: Any) -> bool:
        """Return whether one cached OHLCV frame is long enough for the requested period."""
        if df is None or getattr(df, 'empty', True):
            return False
        required_days = self._chart_required_span_days(period)
        if required_days is None:
            return True
        try:
            index = pd.DatetimeIndex(pd.to_datetime(df.index))
        except Exception:
            return False
        if len(index) < 2:
            return False
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        coverage_days = max(0.0, (index.max() - index.min()).total_seconds() / 86400.0)
        min_acceptable_days = max(required_days - 45.0, required_days * 0.85)
        return coverage_days >= min_acceptable_days

    def _p10_normalize_datetime_index(self, values: Any) -> Any:
        """Normalize chart timestamps for safe asof merges across pandas resolutions."""
        index = pd.DatetimeIndex(pd.to_datetime(values))
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        return pd.DatetimeIndex(index.astype('datetime64[ns]'))

    def _chart_extract_symbol_frame(self, symbol: Any, df: Any) -> Any:
        """Select one symbol frame from a single- or multi-ticker yfinance result."""
        if df is None or getattr(df, 'empty', True):
            return pd.DataFrame()
        frame = df.copy()
        symbol_text = str(symbol or '').upper().strip()
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame
        level0 = [str(value).upper().strip() for value in frame.columns.get_level_values(0)]
        level1 = [str(value).upper().strip() for value in frame.columns.get_level_values(1)]
        if symbol_text and symbol_text in level0:
            mask = [value == symbol_text for value in level0]
            frame = frame.loc[:, mask].copy()
            frame.columns = frame.columns.get_level_values(1)
            return frame
        if symbol_text and symbol_text in level1:
            mask = [value == symbol_text for value in level1]
            frame = frame.loc[:, mask].copy()
            frame.columns = frame.columns.get_level_values(0)
            return frame
        frame.columns = frame.columns.get_level_values(0)
        return frame

    def _chart_normalize_frame(self, symbol: Any, df: Any) -> Any:
        """Normalize raw yfinance OHLCV data into one chart-ready frame."""
        frame = self._chart_extract_symbol_frame(symbol, df)
        if frame is None or getattr(frame, 'empty', True):
            return pd.DataFrame()
        rename_map = {}
        for column in list(frame.columns):
            text = str(column).strip().lower()
            if text == 'open':
                rename_map[column] = 'Open'
            elif text == 'high':
                rename_map[column] = 'High'
            elif text == 'low':
                rename_map[column] = 'Low'
            elif text == 'close':
                rename_map[column] = 'Close'
            elif text == 'volume':
                rename_map[column] = 'Volume'
        if rename_map:
            frame = frame.rename(columns=rename_map)
        if not {'Open', 'High', 'Low', 'Close'}.issubset(frame.columns):
            return pd.DataFrame()
        if 'Volume' not in frame.columns:
            frame['Volume'] = 0.0
        frame = frame.loc[:, [column for column in ('Open', 'High', 'Low', 'Close', 'Volume') if column in frame.columns]].copy()
        frame.index = self._p10_normalize_datetime_index(frame.index)
        frame = frame[~frame.index.duplicated(keep='last')].sort_index()
        frame = frame.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        return frame

    def _chart_load_cached_frame(self, symbol: Any, *, period: Any, interval: Any) -> Any:
        """Return one normalized cached frame when it is present and long enough."""
        cache = self._get_cache_manager()
        frame = self._chart_normalize_frame(symbol, cache.get_data(symbol, interval))
        if frame is None or frame.empty:
            return None
        if interval in ('1d', '1wk', '1mo') and (not self._chart_cache_covers_period(frame, period)):
            return None
        return frame

    def _chart_fetch_base_frame(self, symbol: Any, *, period: Any, interval: Any, force_refresh: bool=False) -> Any:
        """Fetch one normalized OHLCV frame, optionally bypassing cache."""
        symbol_text = str(symbol or '').upper().strip()
        cache = self._get_cache_manager()
        frame = None if force_refresh else self._chart_load_cached_frame(symbol_text, period=period, interval=interval)
        if frame is None or frame.empty:
            raw_df = yf.download(symbol_text, period=period, interval=interval, progress=False, auto_adjust=False)
            frame = self._chart_normalize_frame(symbol_text, raw_df)
            if frame is not None and not frame.empty and interval in ('1d', '1wk', '1mo'):
                cache.save_data(symbol_text, interval, frame)
        if frame is None or frame.empty:
            raise ValueError(f'No chart data returned for {symbol_text}.')
        return frame

    def _p10_on_show(self) -> None:
        """Refresh sidebar state when the Charts page is shown."""
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        self._p10_update_auto_button_style()
        self._p10_update_indicator_button_styles()
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
        self.p10_active_indicators = list(state.get('indicators', ['Volume', '200 MA']))
        if '200 MA' not in self.p10_active_indicators:
            self.p10_active_indicators.append('200 MA')
        self.p10_auto_follow = bool(state.get('auto', True))
        self.p10_chart_df = None
        self.p10_compare_df = None
        self.p10_compare_interval = '1d'
        self.p10_compare_errors = []
        self._p10_chart_rows = []
        self.p10_chart_stats = {}
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
        self._p10_timeframe_group = QButtonGroup(self)
        self._p10_timeframe_group.setExclusive(True)
        self._p10_compare_timeframe_group = QButtonGroup(self)
        self._p10_compare_timeframe_group.setExclusive(True)
        self._p10_timeframe_map = {label: (period, interval) for label, period, interval in P10_TIMEFRAME_OPTIONS}
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
        self._p10_update_multi_interval_button_styles()
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        self._p10_render_indicator_panels()
        self.p10_crosshair_proxy = pg.SignalProxy(self.p10_main_plot.scene().sigMouseMoved, rateLimit=30, slot=self._p10_on_mouse_moved)
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
        for label, _, _ in P10_TIMEFRAME_OPTIONS:
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
        for name in ('Volume', 'RSI', '200 MA'):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.clicked.connect(partial(self._p10_toggle_indicator, name))
            self._p10_indicator_buttons[name] = btn
            indicator_row.addWidget(btn)
        indicator_row.addStretch()
        layout.addLayout(indicator_row)

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
        self.p10_ohlc_label.setStyleSheet('font-size: 12px;')
        self.p10_status_label = QLabel('Ready')
        self.set_theme_role(self.p10_status_label, 'status_muted')
        info_strip.addWidget(self.p10_symbol_label)
        info_strip.addSpacing(16)
        info_strip.addWidget(self.p10_price_label)
        info_strip.addWidget(self.p10_change_label)
        info_strip.addWidget(self.p10_position_label)
        info_strip.addSpacing(20)
        info_strip.addWidget(self.p10_ohlc_label, 1)
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
        for label, _, _ in P10_TIMEFRAME_OPTIONS:
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
        })
        self.p10_compare_presets = list(self.chart_page_state.get('compare_presets', self.p10_compare_presets))

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
        batch_symbols = [str(symbol or '').upper().strip() for symbol in list(symbols or []) if str(symbol or '').upper().strip()]
        if not batch_symbols:
            return {}, []
        raw_batch = yf.download(
            batch_symbols,
            period=period,
            interval=interval,
            group_by='ticker',
            progress=False,
            auto_adjust=False,
            threads=True,
        )
        frame_map = {}
        missing = []
        cache = self._get_cache_manager()
        for symbol in batch_symbols:
            frame = self._chart_normalize_frame(symbol, raw_batch)
            if frame is None or frame.empty:
                missing.append(symbol)
                continue
            frame_map[symbol] = frame
            if interval in ('1d', '1wk', '1mo'):
                cache.save_data(symbol, interval, frame)
        return frame_map, missing

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
        low_value = min(lows)
        high_value = max(highs)
        span = high_value - low_value
        padding = max(0.5, span * 0.08) if span > 0 else max(abs(high_value) * 0.03, 1.0)
        self.p10_main_plot.setYRange(low_value - padding, high_value + padding, padding=0)

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
        valid_labels = {label for label, _, _ in P10_TIMEFRAME_OPTIONS}
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
        return [label for label, _, _ in P10_TIMEFRAME_OPTIONS]

    def _p10_update_multi_interval_button_styles(self) -> None:
        """Refresh checked-state styling for the multi-interval selector buttons."""
        self.p10_multi_interval_labels = self._p10_normalize_multi_interval_labels(self.p10_multi_interval_labels)
        all_labels = [label for label, _, _ in P10_TIMEFRAME_OPTIONS]
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
        all_labels = [label for label, _, _ in P10_TIMEFRAME_OPTIONS]
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
        if text not in self._p10_timeframe_map:
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
        period, interval = self._p10_timeframe_map.get(label, ('', ''))
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
        period, interval = self._p10_timeframe_map.get(label, self._p10_timeframe_map['1 Day'])
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

    def _p10_toggle_indicator(self, name: Any, checked: Any=False) -> None:
        """Toggle an indicator panel without refetching chart data."""
        if checked:
            if name not in self.p10_active_indicators:
                self.p10_active_indicators.append(name)
        else:
            self.p10_active_indicators = [indicator for indicator in self.p10_active_indicators if indicator != name]
        self.p10_active_indicators = [indicator for indicator in ('Volume', 'RSI', '200 MA') if indicator in self.p10_active_indicators]
        self._p10_update_indicator_button_styles()
        self._p10_save_state()
        if self._p10_chart_rows:
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
        self.p10_timeframe_label = label
        self._p10_update_timeframe_button_styles()
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
        self.p10_symbol_input.setText(symbol)
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
        ma200_series = self._p10_fetch_daily_ma200(symbol, df) if include_ma200 else None
        rsi_series = self._p10_calculate_rsi(df['Close']) if include_rsi else None
        rsi_ma_series = self._p10_calculate_rsi_ma(rsi_series) if include_rsi else None
        latest = df.iloc[-1]
        prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else float(latest['Close'])
        last_close = float(latest['Close'])
        change_value = last_close - prev_close
        change_pct = change_value / prev_close * 100 if prev_close else 0.0
        return {
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
        cache = self._get_cache_manager()
        daily_df = cache.get_data(symbol, '1d')
        if daily_df is None or daily_df.empty:
            daily_df = yf.download(symbol, period='5y', interval='1d', progress=False, auto_adjust=False)
            if daily_df is not None and not daily_df.empty:
                cache.save_data(symbol, '1d', daily_df)
        if daily_df is None or daily_df.empty:
            return pd.Series(index=source_df.index, dtype=float)
        if isinstance(daily_df.columns, pd.MultiIndex):
            daily_df.columns = daily_df.columns.get_level_values(0)
        rename_map = {}
        for column in list(daily_df.columns):
            if str(column).strip().lower() == 'close':
                rename_map[column] = 'Close'
        if rename_map:
            daily_df = daily_df.rename(columns=rename_map)
        daily_df = daily_df.dropna(subset=['Close']).copy()
        if daily_df.empty:
            return pd.Series(index=source_df.index, dtype=float)
        daily_ma = pd.Series(daily_df['Close']).astype(float).rolling(200, min_periods=200).mean().dropna()
        if daily_ma.empty:
            return pd.Series(index=source_df.index, dtype=float)
        source_index = self._p10_normalize_datetime_index(source_df.index)
        daily_index = self._p10_normalize_datetime_index(daily_ma.index)
        source_frame = pd.DataFrame(index=source_index).sort_index()
        daily_frame = pd.DataFrame({'ma200': list(daily_ma.values)}, index=daily_index).sort_index()
        aligned = pd.merge_asof(source_frame, daily_frame, left_index=True, right_index=True, direction='backward')['ma200']
        aligned.index = source_df.index
        return aligned

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
        df = payload['df']
        symbol = payload['symbol']
        interval = payload['interval']
        stats = payload['stats']
        self.p10_chart_stats = stats
        self.p10_chart_df = df
        self.p10_rsi_series = payload.get('rsi')
        self.p10_rsi_ma_series = payload.get('rsi_ma')
        self.p10_ma200_series = payload.get('ma200')
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
        self.p10_symbol_label.setText(symbol)
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
        self._set_data_collection_info(['yfinance'])
        self._p10_set_status(f'Loaded {symbol} {self.p10_timeframe_label}.', 'positive')

    def _p10_render_main_chart(self, stats: Any, interval: Any, rsi_series: Any=None, rsi_ma_series: Any=None, ma200_series: Any=None) -> None:
        """Render the main candlestick chart and lower indicator panels."""
        points = []
        volume_brushes = []
        volumes = []
        for idx, row in enumerate(self._p10_chart_rows):
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
        self._p10_refresh_chart_presentation()

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

    def _p10_refresh_overlay_positions(self, *_: Any) -> None:
        """Keep indicator overlay labels pinned near the top-right of each plot."""
        config = (
            (self.p10_main_plot, ('ma200', 'avg_cost')),
            (self.p10_volume_plot, ('volume',)),
            (self.p10_rsi_plot, ('rsi', 'rsi_ma')),
        )
        for plot, keys in config:
            try:
                x_range, y_range = plot.getPlotItem().vb.viewRange()
            except Exception:
                continue
            x_left, x_right = x_range
            y_bottom, y_top = y_range
            x_pos = float(x_right) - (float(x_right) - float(x_left)) * 0.02
            visible_keys = [key for key in keys if self._p10_overlay_items.get(key) is not None]
            for index, key in enumerate(visible_keys):
                item = self._p10_overlay_items.get(key)
                if item is None:
                    continue
                y_pos = float(y_top) - (float(y_top) - float(y_bottom)) * (0.04 + (index * 0.08))
                item.setPos(x_pos, y_pos)

    def _p10_update_indicator_panel_labels(self) -> None:
        """Show latest indicator outputs inside their respective chart panels."""
        ma_text = ''
        if '200 MA' in self.p10_active_indicators:
            latest_ma = None
            if self.p10_ma200_series is not None and len(self.p10_ma200_series):
                for value in reversed(list(self.p10_ma200_series)):
                    if not pd.isna(value):
                        latest_ma = float(value)
                        break
            ma_text = f"MA200 ${latest_ma:,.2f}" if latest_ma is not None else 'MA200 --'
        avg_text = ''
        avg_price = self._p10_portfolio_avg_price(getattr(self, 'p10_symbol', ''))
        close_value = float(getattr(self, 'p10_chart_stats', {}).get('close', 0.0) or 0.0)
        if avg_price is not None:
            gain_pct = ((close_value / avg_price) - 1.0) * 100.0 if avg_price > 0 else 0.0
            gain_sign = '+' if gain_pct >= 0 else ''
            avg_text = f'Avg ${avg_price:,.2f} | Gain {gain_sign}{gain_pct:.2f}%'
        volume_text = ''
        if 'Volume' in self.p10_active_indicators:
            if self._p10_chart_rows:
                latest_volume = float(getattr(self._p10_chart_rows[-1], 'Volume', 0.0) or 0.0)
                volume_text = f'Vol {fmt_num(latest_volume)}'
            else:
                volume_text = 'Vol --'
        rsi_text = ''
        if 'RSI' in self.p10_active_indicators:
            latest_rsi = None
            if self.p10_rsi_series is not None and len(self.p10_rsi_series):
                for value in reversed(list(self.p10_rsi_series)):
                    if not pd.isna(value):
                        latest_rsi = float(value)
                        break
            rsi_text = f"RSI(14) {latest_rsi:.2f}" if latest_rsi is not None else 'RSI(14) --'
        rsi_ma_text = ''
        if 'RSI' in self.p10_active_indicators:
            latest_rsi_ma = None
            if self.p10_rsi_ma_series is not None and len(self.p10_rsi_ma_series):
                for value in reversed(list(self.p10_rsi_ma_series)):
                    if not pd.isna(value):
                        latest_rsi_ma = float(value)
                        break
            rsi_ma_text = f"RSI MA(14) {latest_rsi_ma:.2f}" if latest_rsi_ma is not None else 'RSI MA(14) --'
        self._p10_set_overlay_text('ma200', self.p10_main_plot, ma_text, self.theme_color('chart_ma'))
        self._p10_set_overlay_text(
            'avg_cost',
            self.p10_main_plot,
            avg_text,
            self.theme_color('accent_positive' if avg_price is not None and close_value >= avg_price else 'accent_negative'),
        )
        self._p10_set_overlay_text('volume', self.p10_volume_plot, volume_text, self.theme_color('chart_reference'))
        self._p10_set_overlay_text('rsi', self.p10_rsi_plot, rsi_text, self.theme_color('chart_rsi'))
        self._p10_set_overlay_text('rsi_ma', self.p10_rsi_plot, rsi_ma_text, self.theme_color('chart_reference'))
        self._p10_refresh_overlay_positions()

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
        self._p10_set_status(self.p10_status_label.text(), self.p10_status_label.property('bt_status') or 'muted')
        self._p10_set_compare_status(
            self.p10_compare_status_label.text(),
            self.p10_compare_status_label.property('bt_status') or 'muted',
        )
        self._p10_update_quote_header(self.p10_chart_stats or {'close': 0.0, 'change_value': 0.0, 'change_pct': 0.0})
        self._p10_update_auto_button_style()
        self._p10_update_timeframe_button_styles()
        self._p10_update_indicator_button_styles()
        self._p10_rebuild_watchlists()
        self._p10_refresh_compare_symbol_list()
        if self._p10_chart_rows:
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
            return
        row_index = max(0, min(int(row_index), len(self._p10_chart_rows) - 1))
        row = self._p10_chart_rows[row_index]
        open_value = float(getattr(row, 'Open'))
        high_value = float(getattr(row, 'High'))
        low_value = float(getattr(row, 'Low'))
        close_value = float(getattr(row, 'Close'))
        volume_value = float(getattr(row, 'Volume', 0.0) or 0.0)
        details = f'O {open_value:,.2f}   H {high_value:,.2f}   L {low_value:,.2f}   C {close_value:,.2f}'
        if 'Volume' in self.p10_active_indicators:
            details += f'   Vol {fmt_num(volume_value)}'
        self.p10_ohlc_label.setText(details)

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
