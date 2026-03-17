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
P10_AUTO_ANCHOR = 0.85
P10_DEFAULT_STARTUP_SPAN = 80.0
P10_MIN_REUSABLE_SPAN = 10.0


class ChartsPageMixin:

    def _p10_normalize_datetime_index(self, values: Any) -> Any:
        """Normalize chart timestamps for safe asof merges across pandas resolutions."""
        index = pd.DatetimeIndex(pd.to_datetime(values))
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        return pd.DatetimeIndex(index.astype('datetime64[ns]'))

    def _p10_on_show(self) -> None:
        """Refresh sidebar state when the Charts page is shown."""
        self._p10_rebuild_watchlists()
        self._p10_update_auto_button_style()
        self._p10_update_indicator_button_styles()
        self._p10_render_indicator_panels()
        if self.p10_chart_df is None:
            self._p10_refresh_chart()

    def init_page10(self) -> None:
        """Build the dedicated chart workstation page."""
        state = getattr(self, 'chart_page_state', load_chart_page_settings())
        self.p10_symbol = str(state.get('symbol', 'SPY') or 'SPY').upper()
        self.p10_timeframe_label = str(state.get('timeframe_label', '1 Day') or '1 Day')
        self.p10_custom_watchlist = list(state.get('watchlist', []))
        self.p10_active_indicators = list(state.get('indicators', ['Volume', '200 MA']))
        if '200 MA' not in self.p10_active_indicators:
            self.p10_active_indicators.append('200 MA')
        self.p10_auto_follow = True
        self.p10_chart_df = None
        self._p10_chart_rows = []
        self.p10_chart_stats = {}
        self.p10_rsi_series = None
        self.p10_ma200_series = None
        self.p10_crosshair_proxy = None
        self._p10_request_seq = 0
        self._p10_active_request = 0
        self._p10_timeframe_buttons = {}
        self._p10_indicator_buttons = {}
        self._p10_view_change_guard = False
        self._p10_watchlist_sync_guard = False
        self._p10_manual_x_range = None
        self._p10_pending_x_range = None
        self._p10_overlay_items = {}
        self._p10_timeframe_group = QButtonGroup(self)
        self._p10_timeframe_group.setExclusive(True)
        self._p10_timeframe_map = {label: (period, interval) for label, period, interval in P10_TIMEFRAME_OPTIONS}
        if self.p10_timeframe_label not in self._p10_timeframe_map:
            self.p10_timeframe_label = '1 Day'
        layout = QVBoxLayout(self.page10)
        layout.setContentsMargins(10, 10, 10, 10)
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
        self.p10_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p10_refresh_btn, 'accent')
        self.p10_refresh_btn.clicked.connect(self._p10_refresh_chart)
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
        toolbar.addWidget(self.p10_refresh_btn)
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
        self.p10_ohlc_label = QLabel('O --  H --  L --  C --')
        self.p10_ohlc_label.setStyleSheet('font-size: 12px;')
        self.p10_status_label = QLabel('Ready')
        self.set_theme_role(self.p10_status_label, 'status_muted')
        info_strip.addWidget(self.p10_symbol_label)
        info_strip.addSpacing(16)
        info_strip.addWidget(self.p10_price_label)
        info_strip.addWidget(self.p10_change_label)
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
        watchlist_title = QLabel('Watchlist')
        self.set_theme_role(watchlist_title, 'section_title')
        watchlist_help = QLabel('Your custom chart symbols.')
        self.set_theme_role(watchlist_help, 'muted')
        watchlist_help.setWordWrap(True)
        add_row = QHBoxLayout()
        self.p10_watchlist_input = QLineEdit()
        self.p10_watchlist_input.setPlaceholderText('Add symbol')
        self.p10_watchlist_input.returnPressed.connect(self._p10_add_watchlist_symbol)
        add_btn = QPushButton('+')
        add_btn.setFixedWidth(32)
        add_btn.clicked.connect(self._p10_add_watchlist_symbol)
        rm_btn = QPushButton('Remove')
        self.set_theme_variant(rm_btn, 'danger')
        rm_btn.clicked.connect(self._p10_remove_watchlist_symbol)
        add_row.addWidget(self.p10_watchlist_input, 1)
        add_row.addWidget(add_btn)
        add_row.addWidget(rm_btn)
        self.p10_watchlist = QListWidget()
        self.p10_watchlist.currentItemChanged.connect(self._p10_watchlist_selection_changed)
        portfolio_title = QLabel('Portfolio')
        self.set_theme_role(portfolio_title, 'section_title')
        portfolio_help = QLabel('Read-only symbols from your Portfolio page.')
        self.set_theme_role(portfolio_help, 'muted')
        portfolio_help.setWordWrap(True)
        self.p10_portfolio_list = QListWidget()
        self.p10_portfolio_list.currentItemChanged.connect(self._p10_watchlist_selection_changed)
        sidebar_layout.addWidget(watchlist_title)
        sidebar_layout.addWidget(watchlist_help)
        sidebar_layout.addLayout(add_row)
        sidebar_layout.addWidget(self.p10_watchlist, 1)
        sidebar_layout.addWidget(portfolio_title)
        sidebar_layout.addWidget(portfolio_help)
        sidebar_layout.addWidget(self.p10_portfolio_list, 1)
        body_splitter.addWidget(sidebar)
        body_splitter.setStretchFactor(0, 5)
        body_splitter.setStretchFactor(1, 2)
        layout.addWidget(body_splitter, 1)
        self._p10_update_timeframe_button_styles()
        self._p10_update_auto_button_style()
        self._p10_update_indicator_button_styles()
        self._p10_rebuild_watchlists()
        self._p10_render_indicator_panels()
        self.p10_crosshair_proxy = pg.SignalProxy(self.p10_main_plot.scene().sigMouseMoved, rateLimit=30, slot=self._p10_on_mouse_moved)
        self._apply_charts_page_theme()

    def _p10_set_status(self, text: Any, status: Any='muted') -> None:
        """Set charts page status text."""
        self.set_status_text(self.p10_status_label, text, status=str(status))
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _p10_save_state(self) -> None:
        """Persist charts page settings."""
        self.chart_page_state = save_chart_page_settings({
            'symbol': self.p10_symbol,
            'timeframe_label': self.p10_timeframe_label,
            'watchlist': self.p10_custom_watchlist,
            'indicators': self.p10_active_indicators,
            'auto': self.p10_auto_follow,
        })

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
        ordered = []
        for indicator in ('Volume', 'RSI', '200 MA'):
            if indicator in self.p10_active_indicators and indicator not in ordered:
                ordered.append(indicator)
        self.p10_active_indicators = ordered
        self._p10_update_indicator_button_styles()
        self._p10_save_state()
        if self._p10_chart_rows:
            interval = self._p10_timeframe_map.get(self.p10_timeframe_label, self._p10_timeframe_map['1 Day'])[1]
            self._p10_render_main_chart(self.p10_chart_stats, interval, self.p10_rsi_series, self.p10_ma200_series)
            if self.p10_auto_follow:
                self._p10_apply_auto_x_range(self._p10_get_current_x_range())
            else:
                self._p10_restore_manual_x_range()
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
        self._p10_refresh_chart()

    def _p10_load_from_input(self) -> None:
        """Load the ticker from the input field."""
        symbol = self.p10_symbol_input.text().upper().strip()
        if not symbol:
            return
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
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
            self.p10_watchlist.clear()
            self.p10_portfolio_list.clear()
            portfolio_symbols = []
            for ticker in self.tickers:
                text = str(ticker or '').upper().strip()
                if text and text not in portfolio_symbols:
                    portfolio_symbols.append(text)
            watchlist_row = 0
            for row, symbol in enumerate(self.p10_custom_watchlist):
                item = QListWidgetItem(symbol)
                item.setData(Qt.ItemDataRole.UserRole, symbol)
                item.setForeground(self.theme_qcolor('text_secondary'))
                self.p10_watchlist.addItem(item)
                if symbol == self.p10_symbol:
                    watchlist_row = row
            if self.p10_watchlist.count():
                self.p10_watchlist.setCurrentRow(watchlist_row)
            portfolio_row = 0
            for row, symbol in enumerate(portfolio_symbols):
                item = QListWidgetItem(symbol)
                item.setData(Qt.ItemDataRole.UserRole, symbol)
                item.setForeground(self.theme_qcolor('accent'))
                self.p10_portfolio_list.addItem(item)
                if symbol == self.p10_symbol:
                    portfolio_row = row
            if self.p10_portfolio_list.count():
                self.p10_portfolio_list.setCurrentRow(portfolio_row)
        finally:
            self._p10_watchlist_sync_guard = False

    def _p10_refresh_chart(self) -> None:
        """Refresh the dedicated chart page for the active symbol/timeframe."""
        symbol = str(self.p10_symbol or self.p10_symbol_input.text() or 'SPY').upper().strip()
        if not symbol:
            symbol = 'SPY'
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
        if self.p10_auto_follow:
            self._p10_pending_x_range = self._p10_get_current_x_range()
        else:
            self._p10_pending_x_range = self._p10_get_current_x_range() or self._p10_manual_x_range
        self._p10_request_seq += 1
        request_id = self._p10_request_seq
        self._p10_active_request = request_id
        self.p10_load_btn.setEnabled(False)
        self.p10_refresh_btn.setEnabled(False)
        self._p10_set_status(f'Loading {symbol} {self.p10_timeframe_label}...', 'info')

        def _run() -> None:
            """Fetch chart data in the background."""
            try:
                data = self._p10_fetch_chart_payload(symbol, self.p10_timeframe_label)
                self._invoke_main.emit(lambda payload=data, req=request_id: self._p10_apply_chart_payload(req, payload))
            except Exception as exc:
                self._invoke_main.emit(lambda err=str(exc), req=request_id: self._p10_handle_chart_error(req, err))
        threading.Thread(target=_run, daemon=True).start()

    def _p10_fetch_chart_payload(self, symbol: Any, timeframe_label: Any) -> Any:
        """Fetch a single chart dataset plus summary stats."""
        period, interval = self._p10_timeframe_map.get(timeframe_label, self._p10_timeframe_map['1 Day'])
        cache = CacheManager()
        df = cache.get_data(symbol, interval)
        if df is None or df.empty:
            df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
            if df is not None and not df.empty and interval in ('1d', '1wk', '1mo'):
                cache.save_data(symbol, interval, df)
        if df is None or df.empty:
            raise ValueError(f'No chart data returned for {symbol}.')
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        rename_map = {}
        for column in list(df.columns):
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
            df = df.rename(columns=rename_map)
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        if df.empty:
            raise ValueError(f'Incomplete chart data returned for {symbol}.')
        ma200_series = self._p10_fetch_daily_ma200(symbol, df)
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
                'change_value': change_value,
                'change_pct': change_pct,
            },
            'rsi': self._p10_calculate_rsi(df['Close']),
            'ma200': ma200_series,
        }

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

    def _p10_fetch_daily_ma200(self, symbol: Any, source_df: Any) -> Any:
        """Build a 200-day moving average aligned to the active chart index."""
        cache = CacheManager()
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
        self.p10_ma200_series = payload.get('ma200')
        self.p10_symbol = symbol
        self.p10_symbol_input.setText(symbol)
        self.p10_symbol_label.setText(symbol)
        self._p10_chart_rows = list(df.itertuples())
        self._p10_render_main_chart(stats, interval, payload.get('rsi'), payload.get('ma200'))
        if self.p10_auto_follow:
            self._p10_apply_auto_x_range(self._p10_pending_x_range)
        else:
            self._p10_restore_manual_x_range()
        self._p10_update_quote_header(stats)
        self._p10_show_row_details(len(self._p10_chart_rows) - 1)
        self.p10_load_btn.setEnabled(True)
        self.p10_refresh_btn.setEnabled(True)
        self._p10_save_state()
        self._p10_rebuild_watchlists()
        self._p10_pending_x_range = None
        self._p10_update_indicator_panel_labels()
        self._set_data_collection_info(['yfinance'])
        self._p10_set_status(f'Loaded {symbol} {self.p10_timeframe_label}.', 'positive')

    def _p10_render_main_chart(self, stats: Any, interval: Any, rsi_series: Any=None, ma200_series: Any=None) -> None:
        """Render the main candlestick chart and lower indicator panels."""
        self.p10_main_plot.clear()
        self.p10_volume_plot.clear()
        self.p10_rsi_plot.clear()
        self._p10_overlay_items = {}
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
        self.p10_main_plot.addItem(candle_item)
        if ma200_series is not None and '200 MA' in self.p10_active_indicators:
            ma_values = [float(value) if not pd.isna(value) else float('nan') for value in ma200_series]
            if ma_values:
                self.p10_main_plot.plot(list(range(len(ma_values))), ma_values, pen=self.theme_pen('chart_ma', width=2.0), antialias=True)
        last_close = float(stats.get('close', 0.0)) if isinstance(stats, dict) else 0.0
        last_price_line = pg.InfiniteLine(pos=last_close, angle=0, pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
        self.p10_main_plot.addItem(last_price_line)
        dates = self.p10_chart_df.index.to_list()
        self.p10_chart_axis.set_dates(dates, interval)
        self.p10_volume_axis.set_dates(dates, interval)
        self.p10_rsi_axis.set_dates(dates, interval)
        if volumes:
            volume_item = pg.BarGraphItem(x=list(range(len(volumes))), height=volumes, width=0.7, brushes=volume_brushes)
            self.p10_volume_plot.addItem(volume_item)
        if rsi_series is not None:
            x_values = list(range(len(rsi_series)))
            y_values = [float(value) if not pd.isna(value) else float('nan') for value in rsi_series]
            self.p10_rsi_plot.plot(x_values, y_values, pen=self.theme_pen('chart_rsi', width=2.0), antialias=True)
            self.p10_rsi_plot.addItem(pg.InfiniteLine(pos=70, angle=0, pen=self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine)))
            self.p10_rsi_plot.addItem(pg.InfiniteLine(pos=30, angle=0, pen=self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine)))
            self.p10_rsi_plot.setYRange(0, 100, padding=0.02)
        self._p10_update_indicator_panel_labels()
        self._p10_render_indicator_panels()

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
        self.p10_load_btn.setEnabled(True)
        self.p10_refresh_btn.setEnabled(True)
        self._p10_set_status(f'Chart load failed: {message}', 'negative')

    def _p10_update_quote_header(self, stats: Any) -> None:
        """Update the quote and change header."""
        if not stats:
            self.p10_price_label.setText('--')
            self.p10_change_label.setText('--')
            self.p10_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {self.theme_color("text_muted")};')
            return
        close_value = float(stats.get('close', 0.0))
        change_value = float(stats.get('change_value', 0.0))
        change_pct = float(stats.get('change_pct', 0.0))
        change_color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        sign = '+' if change_value >= 0 else ''
        self.p10_price_label.setText(f'${close_value:,.2f}')
        self.p10_change_label.setText(f'{sign}${change_value:,.2f} ({sign}{change_pct:.2f}%)')
        self.p10_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {change_color};')

    def _p10_set_overlay_text(self, key: Any, plot: Any, text: Any, color: Any) -> None:
        """Render a top-right overlay label inside a plot."""
        if not text:
            self._p10_overlay_items.pop(key, None)
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
            ('ma200', self.p10_main_plot),
            ('volume', self.p10_volume_plot),
            ('rsi', self.p10_rsi_plot),
        )
        for key, plot in config:
            item = self._p10_overlay_items.get(key)
            if item is None:
                continue
            try:
                x_range, y_range = plot.getPlotItem().vb.viewRange()
            except Exception:
                continue
            x_left, x_right = x_range
            y_bottom, y_top = y_range
            x_pos = float(x_right) - (float(x_right) - float(x_left)) * 0.02
            y_pos = float(y_top) - (float(y_top) - float(y_bottom)) * 0.04
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
        self._p10_set_overlay_text('ma200', self.p10_main_plot, ma_text, self.theme_color('chart_ma'))
        self._p10_set_overlay_text('volume', self.p10_volume_plot, volume_text, self.theme_color('chart_reference'))
        self._p10_set_overlay_text('rsi', self.p10_rsi_plot, rsi_text, self.theme_color('chart_rsi'))
        self._p10_refresh_overlay_positions()

    def _apply_charts_page_theme(self) -> None:
        """Refresh charts-page theme-dependent widgets and plots."""
        self.style_plot_widget(self.p10_main_plot)
        self.style_plot_widget(self.p10_volume_plot, show_y_grid=False)
        self.style_plot_widget(self.p10_rsi_plot)
        self.p10_symbol_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p10_price_label.setStyleSheet(f'font-size: 20px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p10_ohlc_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        self._p10_set_status(self.p10_status_label.text(), self.p10_status_label.property('bt_status') or 'muted')
        self._p10_update_quote_header(self.p10_chart_stats or {'close': 0.0, 'change_value': 0.0, 'change_pct': 0.0})
        self._p10_update_auto_button_style()
        self._p10_update_timeframe_button_styles()
        self._p10_update_indicator_button_styles()
        self._p10_rebuild_watchlists()
        if self._p10_chart_rows:
            interval = self._p10_timeframe_map.get(self.p10_timeframe_label, self._p10_timeframe_map['1 Day'])[1]
            self._p10_render_main_chart(self.p10_chart_stats, interval, self.p10_rsi_series, self.p10_ma200_series)

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
