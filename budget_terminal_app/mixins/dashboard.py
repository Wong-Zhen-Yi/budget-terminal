from __future__ import annotations
import math
from typing import Any
from ..compat import *


P1_AUTO_ANCHOR = 0.85
P1_DEFAULT_STARTUP_SPAN = 80.0
P1_MIN_REUSABLE_SPAN = 10.0


class DashboardMixin:
    def _dashboard_fit_portfolio_table_height(self, max_rows: int=8) -> None:
        """Keep the portfolio table compact while preserving its current column layout."""
        if not hasattr(self, 'port_table'):
            return
        table = self.port_table
        header_height = table.horizontalHeader().height() if table.horizontalHeader() else 28
        row_height = table.verticalHeader().defaultSectionSize() or 24
        visible_rows = min(max(table.rowCount(), 1), max_rows)
        frame = table.frameWidth() * 2
        scrollbar_pad = 4
        target_height = header_height + (visible_rows * row_height) + frame + scrollbar_pad
        table.setMinimumHeight(target_height)
        table.setMaximumHeight(target_height)

    def _update_main_portfolio_entry(self) -> Any:
        """Persist the current app-wide portfolio fields into the main portfolio slot."""
        entry = self._get_portfolio_entry(self.main_portfolio_id)
        entry['portfolio'] = self.tickers
        entry['chart_slots'] = self.chart_slots
        entry['portfolio_tracker'] = self.tracker_data
        return entry

    def _dashboard_save_state(self) -> Any:
        """Persist the dashboard chart workstation state."""
        splitter_sizes = getattr(self, 'dashboard_chart_state', {}).get('splitter_sizes', [5, 2])
        if hasattr(self, 'dashboard_body_splitter'):
            current_sizes = [int(size) for size in self.dashboard_body_splitter.sizes() if int(size) > 0]
            if len(current_sizes) == 2:
                splitter_sizes = current_sizes
        state = normalize_dashboard_chart_settings({
            **getattr(self, 'dashboard_chart_state', {}),
            'symbol': getattr(self, 'dashboard_symbol', self.dashboard_chart_state.get('symbol', 'SPY')),
            'timeframe_label': getattr(self, 'dashboard_timeframe_label', self.dashboard_chart_state.get('timeframe_label', '1 Day')),
            'indicators': getattr(self, 'dashboard_active_indicators', self.dashboard_chart_state.get('indicators', ['Volume', '200 MA'])),
            'auto': getattr(self, 'dashboard_auto_follow', self.dashboard_chart_state.get('auto', True)),
            'splitter_sizes': splitter_sizes,
        })
        self.dashboard_chart_state = save_dashboard_chart_settings(state)
        return self.dashboard_chart_state

    def _dashboard_apply_splitter_sizes(self) -> None:
        """Restore the saved dashboard splitter sizes."""
        if not hasattr(self, 'dashboard_body_splitter'):
            return
        sizes = normalize_dashboard_chart_settings(getattr(self, 'dashboard_chart_state', {})).get('splitter_sizes', [5, 2])
        self.dashboard_body_splitter.setSizes([int(size) for size in sizes])

    def _dashboard_on_splitter_moved(self, *_: Any) -> None:
        """Persist the dashboard sidebar width after a user drag."""
        self._dashboard_save_state()

    def _dashboard_set_status(self, text: Any, status: Any='muted') -> None:
        """Set dashboard status text."""
        self.set_status_text(self.dashboard_status_label, text, status=str(status))
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _dashboard_update_auto_button_style(self) -> None:
        """Highlight the auto-follow toggle."""
        self.dashboard_auto_btn.blockSignals(True)
        self.dashboard_auto_btn.setChecked(self.dashboard_auto_follow)
        self.dashboard_auto_btn.blockSignals(False)
        self.set_theme_variant(self.dashboard_auto_btn, 'accent' if self.dashboard_auto_follow else None)
        self.dashboard_auto_btn.setProperty('bt_checked', 'true' if self.dashboard_auto_follow else 'false')
        self._repolish_widget(self.dashboard_auto_btn)

    def _dashboard_update_timeframe_button_styles(self) -> None:
        """Highlight the active dashboard timeframe."""
        self.update_checked_button_state(self.dashboard_timeframe_buttons, self.dashboard_timeframe_label)
        for label, btn in self.dashboard_timeframe_buttons.items():
            btn.setChecked(label == self.dashboard_timeframe_label)

    def _dashboard_update_indicator_button_styles(self) -> None:
        """Highlight active dashboard indicators."""
        for name, btn in self.dashboard_indicator_buttons.items():
            is_active = name in self.dashboard_active_indicators
            btn.blockSignals(True)
            btn.setChecked(is_active)
            btn.blockSignals(False)
            self.set_theme_variant(btn, 'positive' if is_active else None)
            btn.setProperty('bt_checked', 'true' if is_active else 'false')
            self._repolish_widget(btn)

    def _dashboard_toggle_auto_follow(self, checked: Any=False) -> None:
        """Switch between auto-follow and manual viewport modes."""
        self.dashboard_auto_follow = bool(checked)
        if not self.dashboard_auto_follow:
            self.dashboard_manual_x_range = self._dashboard_get_current_x_range()
        self._dashboard_update_auto_button_style()
        self._dashboard_save_state()
        if self.dashboard_auto_follow and self.dashboard_chart_rows:
            self._dashboard_apply_auto_x_range(self._dashboard_get_current_x_range())

    def _dashboard_toggle_indicator(self, name: Any, checked: Any=False) -> None:
        """Toggle a dashboard indicator panel without refetching chart data."""
        if checked:
            if name not in self.dashboard_active_indicators:
                self.dashboard_active_indicators.append(name)
        else:
            self.dashboard_active_indicators = [indicator for indicator in self.dashboard_active_indicators if indicator != name]
        ordered = []
        for indicator in ('Volume', 'RSI', '200 MA'):
            if indicator in self.dashboard_active_indicators and indicator not in ordered:
                ordered.append(indicator)
        if '200 MA' not in ordered:
            ordered.append('200 MA')
        self.dashboard_active_indicators = ordered
        self._dashboard_update_indicator_button_styles()
        self._dashboard_save_state()
        if self.dashboard_chart_rows:
            self._dashboard_render_main_chart(self.dashboard_chart_stats, self.dashboard_chart_interval, self.dashboard_rsi_series, self.dashboard_chart_ma200)
            if self.dashboard_auto_follow:
                self._dashboard_apply_auto_x_range(self._dashboard_get_current_x_range())
            else:
                self._dashboard_restore_manual_x_range()
            self._dashboard_show_row_details(len(self.dashboard_chart_rows) - 1)
        else:
            self._dashboard_render_indicator_panels()
        self._dashboard_update_indicator_panel_labels()

    def _dashboard_set_timeframe(self, label: Any, *_: Any) -> None:
        """Switch the active dashboard timeframe and refresh."""
        if label not in self.dashboard_timeframe_map or label == self.dashboard_timeframe_label:
            self._dashboard_update_timeframe_button_styles()
            return
        self.dashboard_timeframe_label = label
        self._dashboard_update_timeframe_button_styles()
        self._dashboard_save_state()
        self.refresh_data()

    def _dashboard_load_from_input(self) -> None:
        """Load the dashboard ticker from the input field."""
        symbol = self.dashboard_symbol_input.text().upper().strip()
        if not symbol:
            return
        self.dashboard_symbol = symbol
        self.dashboard_symbol_input.setText(symbol)
        self._dashboard_save_state()
        self.refresh_data()

    def _dashboard_get_current_x_range(self) -> Any:
        """Return the current x-range of the dashboard chart."""
        try:
            return tuple(self.dashboard_main_plot.getPlotItem().vb.viewRange()[0])
        except Exception:
            return None

    def _dashboard_set_x_range(self, x_range: Any) -> None:
        """Set the chart x-range without re-entering x-range handlers."""
        if not x_range:
            return
        left, right = x_range
        if right <= left:
            return
        self.dashboard_chart_view_guard = True
        try:
            self.dashboard_main_plot.setXRange(float(left), float(right), padding=0)
        finally:
            self.dashboard_chart_view_guard = False

    def _dashboard_is_reusable_x_range(self, x_range: Any) -> bool:
        """Return whether an x-range is meaningful enough to reuse."""
        if not x_range:
            return False
        try:
            left = float(x_range[0])
            right = float(x_range[1])
        except Exception:
            return False
        return right > left and (right - left) >= P1_MIN_REUSABLE_SPAN

    def _dashboard_normalize_x_range(self, x_range: Any) -> Any:
        """Clamp a proposed x-range to a valid span for the current dataset."""
        if not x_range or not self.dashboard_chart_rows:
            return None
        left, right = (float(x_range[0]), float(x_range[1]))
        span = max(2.0, right - left)
        latest_index = max(0.0, float(len(self.dashboard_chart_rows) - 1))
        center = max(0.0, min((left + right) / 2.0, latest_index))
        return (center - span / 2.0, center + span / 2.0)

    def _dashboard_apply_auto_x_range(self, source_range: Any=None) -> None:
        """Anchor the latest candle near the right side of the viewport."""
        if not self.dashboard_chart_rows:
            return
        latest_index = float(len(self.dashboard_chart_rows) - 1)
        if self._dashboard_is_reusable_x_range(source_range):
            span = max(P1_MIN_REUSABLE_SPAN, float(source_range[1]) - float(source_range[0]))
        else:
            span = max(20.0, min(P1_DEFAULT_STARTUP_SPAN, float(len(self.dashboard_chart_rows))))
        right_padding = span * (1.0 - P1_AUTO_ANCHOR)
        anchored = (latest_index - span * P1_AUTO_ANCHOR, latest_index + right_padding)
        self._dashboard_set_x_range(anchored)
        self._dashboard_apply_auto_y_range(anchored)

    def _dashboard_get_visible_rows(self, x_range: Any=None) -> Any:
        """Return the chart rows that fall inside the requested x-range."""
        if not self.dashboard_chart_rows:
            return []
        active_range = x_range or self._dashboard_get_current_x_range()
        if not active_range:
            return list(self.dashboard_chart_rows)
        left = max(0, int(math.floor(float(active_range[0]))))
        right = min(len(self.dashboard_chart_rows) - 1, int(math.ceil(float(active_range[1]))))
        if right < left:
            return []
        return self.dashboard_chart_rows[left:right + 1]

    def _dashboard_apply_auto_y_range(self, x_range: Any=None) -> None:
        """Fit the y-axis to the visible candles while auto mode is on."""
        visible_rows = self._dashboard_get_visible_rows(x_range)
        if not visible_rows:
            return
        lows = [float(getattr(row, 'Low')) for row in visible_rows]
        highs = [float(getattr(row, 'High')) for row in visible_rows]
        if self.dashboard_chart_ma200 is not None and '200 MA' in self.dashboard_active_indicators:
            active_range = x_range or self._dashboard_get_current_x_range()
            if active_range:
                left = max(0, int(math.floor(float(active_range[0]))))
                right = min(len(self.dashboard_chart_ma200) - 1, int(math.ceil(float(active_range[1]))))
                if right >= left:
                    ma_values = [float(value) for value in self.dashboard_chart_ma200.iloc[left:right + 1] if not pd.isna(value)]
                    if ma_values:
                        lows.append(min(ma_values))
                        highs.append(max(ma_values))
        low_value = min(lows)
        high_value = max(highs)
        span = high_value - low_value
        padding = max(0.5, span * 0.08) if span > 0 else max(abs(high_value) * 0.03, 1.0)
        self.dashboard_main_plot.setYRange(low_value - padding, high_value + padding, padding=0)

    def _dashboard_restore_manual_x_range(self) -> None:
        """Restore the user's manual x-range when auto-follow is off."""
        x_range = self.dashboard_pending_x_range or self.dashboard_manual_x_range
        normalized = self._dashboard_normalize_x_range(x_range)
        if normalized:
            self._dashboard_set_x_range(normalized)
            self.dashboard_manual_x_range = normalized

    def _dashboard_on_x_range_changed(self, *_: Any) -> None:
        """Track user viewport changes and enforce auto-follow centering."""
        if self.dashboard_chart_view_guard or not self.dashboard_chart_rows:
            return
        current_range = self._dashboard_get_current_x_range()
        if not current_range:
            return
        if self.dashboard_auto_follow:
            self._dashboard_apply_auto_x_range(current_range)
            self._dashboard_apply_auto_y_range(self._dashboard_get_current_x_range())
        else:
            self.dashboard_manual_x_range = current_range

    def _dashboard_update_quote_header(self, stats: Any) -> None:
        """Update the dashboard quote and change header."""
        if not stats:
            self.dashboard_price_label.setText('--')
            self.dashboard_change_label.setText('--')
            self.dashboard_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {self.theme_color("text_muted")};')
            return
        close_value = float(stats.get('close', 0.0))
        change_value = float(stats.get('change_value', 0.0))
        change_pct = float(stats.get('change_pct', 0.0))
        change_color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        sign = '+' if change_value >= 0 else ''
        self.dashboard_price_label.setText(f'${close_value:,.2f}')
        self.dashboard_change_label.setText(f'{sign}${change_value:,.2f} ({sign}{change_pct:.2f}%)')
        self.dashboard_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {change_color};')

    def _dashboard_set_overlay_text(self, key: Any, plot: Any, text: Any, color: Any) -> None:
        """Render a top-right overlay label inside a plot."""
        if not text:
            self.dashboard_overlay_items.pop(key, None)
            return
        item = self.dashboard_overlay_items.get(key)
        if item is None:
            item = pg.TextItem(color=color, anchor=(1, 0))
            try:
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            except Exception:
                pass
            plot.addItem(item, ignoreBounds=True)
            self.dashboard_overlay_items[key] = item
        item.setText(str(text), color=color)

    def _dashboard_refresh_overlay_positions(self, *_: Any) -> None:
        """Keep dashboard indicator overlay labels pinned near the top-right of each plot."""
        config = (
            ('ma200', self.dashboard_main_plot),
            ('volume', self.dashboard_volume_plot),
            ('rsi', self.dashboard_rsi_plot),
        )
        for key, plot in config:
            item = self.dashboard_overlay_items.get(key)
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

    def _dashboard_update_indicator_panel_labels(self) -> None:
        """Show latest indicator outputs inside their respective chart panels."""
        ma_text = ''
        if '200 MA' in self.dashboard_active_indicators:
            latest_ma = None
            if self.dashboard_chart_ma200 is not None and len(self.dashboard_chart_ma200):
                for value in reversed(list(self.dashboard_chart_ma200)):
                    if not pd.isna(value):
                        latest_ma = float(value)
                        break
            ma_text = f"MA200 ${latest_ma:,.2f}" if latest_ma is not None else 'MA200 --'
        volume_text = ''
        if 'Volume' in self.dashboard_active_indicators:
            if self.dashboard_chart_rows:
                latest_volume = float(getattr(self.dashboard_chart_rows[-1], 'Volume', 0.0) or 0.0)
                volume_text = f'Vol {fmt_num(latest_volume)}'
            else:
                volume_text = 'Vol --'
        rsi_text = ''
        if 'RSI' in self.dashboard_active_indicators:
            latest_rsi = None
            if self.dashboard_rsi_series is not None and len(self.dashboard_rsi_series):
                for value in reversed(list(self.dashboard_rsi_series)):
                    if not pd.isna(value):
                        latest_rsi = float(value)
                        break
            rsi_text = f"RSI(14) {latest_rsi:.2f}" if latest_rsi is not None else 'RSI(14) --'
        self._dashboard_set_overlay_text('ma200', self.dashboard_main_plot, ma_text, self.theme_color('chart_ma'))
        self._dashboard_set_overlay_text('volume', self.dashboard_volume_plot, volume_text, self.theme_color('chart_reference'))
        self._dashboard_set_overlay_text('rsi', self.dashboard_rsi_plot, rsi_text, self.theme_color('chart_rsi'))
        self._dashboard_refresh_overlay_positions()

    def _dashboard_render_indicator_panels(self) -> None:
        """Show or hide indicator panels based on active indicators."""
        show_volume = 'Volume' in self.dashboard_active_indicators
        show_rsi = 'RSI' in self.dashboard_active_indicators
        self.dashboard_volume_plot.setVisible(show_volume)
        self.dashboard_rsi_plot.setVisible(show_rsi)
        self.dashboard_panels.setStretchFactor(0, 6)
        self.dashboard_panels.setStretchFactor(1, 2 if show_volume else 0)
        self.dashboard_panels.setStretchFactor(2, 2 if show_rsi else 0)

    def _dashboard_show_row_details(self, row_index: Any) -> None:
        """Update the dashboard OHLC readout for a chart row."""
        if not self.dashboard_chart_rows:
            self.dashboard_ohlc_label.setText('O --  H --  L --  C --')
            return
        row_index = max(0, min(int(row_index), len(self.dashboard_chart_rows) - 1))
        row = self.dashboard_chart_rows[row_index]
        open_value = float(getattr(row, 'Open'))
        high_value = float(getattr(row, 'High'))
        low_value = float(getattr(row, 'Low'))
        close_value = float(getattr(row, 'Close'))
        volume_value = float(getattr(row, 'Volume', 0.0) or 0.0)
        details = f'O {open_value:,.2f}   H {high_value:,.2f}   L {low_value:,.2f}   C {close_value:,.2f}'
        if 'Volume' in self.dashboard_active_indicators:
            details += f'   Vol {fmt_num(volume_value)}'
        self.dashboard_ohlc_label.setText(details)

    def _dashboard_on_mouse_moved(self, event: Any) -> None:
        """Track mouse movement to update the dashboard OHLC readout."""
        if not self.dashboard_chart_rows:
            return
        pos = event[0]
        if not self.dashboard_main_plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.dashboard_main_plot.getPlotItem().vb.mapSceneToView(pos)
        index = int(round(mouse_point.x()))
        self._dashboard_show_row_details(index)

    def _dashboard_clear_chart(self, ticker: Any) -> None:
        """Clear dashboard chart content when no validated data is available."""
        self.dashboard_main_plot.clear()
        self.dashboard_volume_plot.clear()
        self.dashboard_rsi_plot.clear()
        self.dashboard_chart_rows = []
        self.dashboard_chart_df = None
        self.dashboard_chart_stats = {}
        self.dashboard_rsi_series = None
        self.dashboard_chart_ma200 = None
        self.dashboard_chart_interval = self.dashboard_timeframe_map.get(self.dashboard_timeframe_label, ('5y', '1d'))[1]
        self.dashboard_overlay_items = {}
        self.dashboard_chart_axis.set_dates([], self.dashboard_chart_interval)
        self.dashboard_volume_axis.set_dates([], self.dashboard_chart_interval)
        self.dashboard_rsi_axis.set_dates([], self.dashboard_chart_interval)
        self.dashboard_symbol_label.setText(str(ticker or 'Chart'))
        self._dashboard_update_quote_header(None)
        self._dashboard_show_row_details(0)
        self._dashboard_update_indicator_panel_labels()

    def _dashboard_render_main_chart(self, stats: Any, interval: Any, rsi_series: Any=None, ma200_series: Any=None) -> None:
        """Render the main dashboard candlestick chart and lower indicator panels."""
        self.dashboard_main_plot.clear()
        self.dashboard_volume_plot.clear()
        self.dashboard_rsi_plot.clear()
        self.dashboard_overlay_items = {}
        points = []
        volume_brushes = []
        volumes = []
        for idx, row in enumerate(self.dashboard_chart_rows):
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
        self.dashboard_main_plot.addItem(candle_item)
        if ma200_series is not None and '200 MA' in self.dashboard_active_indicators:
            ma_values = [float(value) if not pd.isna(value) else float('nan') for value in ma200_series]
            if ma_values:
                self.dashboard_main_plot.plot(list(range(len(ma_values))), ma_values, pen=self.theme_pen('chart_ma', width=2.0), antialias=True)
        last_close = float(stats.get('close', 0.0)) if isinstance(stats, dict) else 0.0
        last_price_line = pg.InfiniteLine(pos=last_close, angle=0, pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
        self.dashboard_main_plot.addItem(last_price_line)
        dates = self.dashboard_chart_df.index.to_list() if self.dashboard_chart_df is not None else []
        self.dashboard_chart_axis.set_dates(dates, interval)
        self.dashboard_volume_axis.set_dates(dates, interval)
        self.dashboard_rsi_axis.set_dates(dates, interval)
        if volumes:
            volume_item = pg.BarGraphItem(x=list(range(len(volumes))), height=volumes, width=0.7, brushes=volume_brushes)
            self.dashboard_volume_plot.addItem(volume_item)
        if rsi_series is not None:
            x_values = list(range(len(rsi_series)))
            y_values = [float(value) if not pd.isna(value) else float('nan') for value in rsi_series]
            self.dashboard_rsi_plot.plot(x_values, y_values, pen=self.theme_pen('chart_rsi', width=2.0), antialias=True)
            self.dashboard_rsi_plot.addItem(pg.InfiniteLine(pos=70, angle=0, pen=self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine)))
            self.dashboard_rsi_plot.addItem(pg.InfiniteLine(pos=30, angle=0, pen=self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine)))
            self.dashboard_rsi_plot.setYRange(0, 100, padding=0.02)
        self._dashboard_update_indicator_panel_labels()
        self._dashboard_render_indicator_panels()

    def add_ticker(self) -> None:
        """Add ticker."""
        t = self.ticker_input.text().upper().strip()
        if t:
            if t in self.tickers:
                logger.info('Ticker %s already in portfolio', t)
                self.ticker_input.clear()
                return
            self.tickers.append(t)
            self._update_main_portfolio_entry()
            self._persist_all_portfolios()
            self.ticker_input.clear()
            if self.active_portfolio_id == self.main_portfolio_id and hasattr(self, '_p4_refresh_portfolio_selector'):
                self._p4_refresh_portfolio_selector()
            self.refresh_data()

    def remove_ticker(self, t: Any) -> None:
        """Remove ticker."""
        if t in self.tickers:
            self.tickers.remove(t)
            if t in self.tracker_data:
                del self.tracker_data[t]
            self._update_main_portfolio_entry()
            self._persist_all_portfolios()
            if self.last_data and 'portfolio' in self.last_data:
                if t in self.last_data['portfolio']:
                    del self.last_data['portfolio'][t]
                self.last_data['targets'] = [item for item in self.last_data.get('targets', []) if item.get('ticker') != t]
                self.last_data['news'] = [item for item in self.last_data.get('news', []) if not (item.get('category') == 'portfolio' and item.get('ticker') == t)]
                self.update_ui(self.last_data)
            else:
                self.repopulate_portfolio()
                self.p4_table.setRowCount(len(getattr(self, 'active_tickers', self.tickers)))
            if self.active_portfolio_id == self.main_portfolio_id and getattr(self, 'last_data', None):
                self.update_page4(self.last_data)
            logger.info('Removed ticker %s', t)

    def refresh_data(self) -> None:
        """Refresh portfolio data plus the dashboard chart workstation."""
        self._news_auto_summarized = False
        if hasattr(self, 'p3_summary_status'):
            self.p3_summary_status.setText('Refreshing news...')
        if hasattr(self, 'p3_summary_text') and not self._p3_summarizing:
            self.p3_summary_text.setPlainText('Refreshing loaded headlines...')
        self.dashboard_symbol = str(self.dashboard_symbol_input.text() or self.dashboard_chart_state.get('symbol') or 'SPY').upper().strip()
        if not self.dashboard_symbol:
            self.dashboard_symbol = 'SPY'
        self.dashboard_symbol_input.setText(self.dashboard_symbol)
        if self.dashboard_timeframe_label not in self.dashboard_timeframe_map:
            self.dashboard_timeframe_label = self.dashboard_chart_state.get('timeframe_label', '1 Day')
        period, interval = self.dashboard_timeframe_map.get(self.dashboard_timeframe_label, self.dashboard_timeframe_map['1 Day'])
        self.chart_configs = [(self.dashboard_symbol, period, interval)]
        self._dashboard_save_state()
        self._dashboard_request_seq += 1
        request_id = self._dashboard_request_seq
        self._dashboard_latest_request_id = request_id
        self.dashboard_pending_x_range = self._dashboard_get_current_x_range() if self.dashboard_auto_follow else (self._dashboard_get_current_x_range() or self.dashboard_manual_x_range)
        chart_configs_snapshot = list(self.chart_configs)
        self.dashboard_load_btn.setEnabled(False)
        self.dashboard_refresh_btn.setEnabled(False)
        self._dashboard_set_status(f'Loading {self.dashboard_symbol} {self.dashboard_timeframe_label}...', 'info')
        self.worker_thread = threading.Thread(target=self.run_worker, args=(request_id, chart_configs_snapshot), daemon=True)
        self.worker_thread.start()

    def run_worker(self, request_id: int, chart_configs_snapshot: Any) -> None:
        """Run the shared market data worker."""
        worker = DataWorker(self._get_fetch_tickers(), chart_configs_snapshot, request_id=request_id)
        worker.finished.connect(self.update_ui)
        worker.error.connect(self.handle_error)
        worker.run()

    def handle_error(self, error_msg: Any) -> None:
        """Handle data refresh errors."""
        logger.error('UI received error: %s', error_msg)
        self.dashboard_load_btn.setEnabled(True)
        self.dashboard_refresh_btn.setEnabled(True)
        self._dashboard_set_status(f'Refresh failed: {error_msg}', 'negative')

    def open_news_link(self, item: Any) -> None:
        """Open news link."""
        row = item.row()
        headline_item = self.news_table.item(row, 0)
        url = headline_item.data(Qt.ItemDataRole.UserRole)
        if url:
            logger.info('Opening news link: %s', url)
            webbrowser.open(url)

    def repopulate_portfolio(self) -> Any:
        """Populate the main dashboard portfolio table."""
        if not self.last_data:
            return
        portfolio = {ticker: info for ticker, info in self.last_data.get('portfolio', {}).items() if ticker in self.tickers}
        if hasattr(self, '_p4_portfolio_name'):
            header_name = self._p4_portfolio_name(self.main_portfolio_index)
        else:
            header_name = 'My Portfolio'
        self.port_header_lbl.setText(f'{header_name} ({len(portfolio)})')
        tracker = getattr(self, 'tracker_data', {})

        def market_value(ticker: Any, info: Any) -> Any:
            shares = tracker.get(ticker, {}).get('shares', 0)
            return shares * info['price'] if shares else 0

        total_value = sum((market_value(ticker, info) for ticker, info in portfolio.items()))
        sorted_items = sorted(portfolio.items(), key=lambda item: market_value(item[0], item[1]), reverse=True)
        self.port_table.setRowCount(len(sorted_items))
        for i, (ticker, info) in enumerate(sorted_items):
            price = info['price']
            change_pct = info['change']
            shares = tracker.get(ticker, {}).get('shares', 0)
            avg_price = tracker.get(ticker, {}).get('avg_price', 0)
            market_val = shares * price if shares else 0
            weight_pct = market_val / total_value * 100 if total_value > 0 and shares else 0
            dollar_gain = (price - avg_price) * shares if shares else 0
            is_up = change_pct >= 0
            sign = '+' if is_up else ''
            text_color = self.theme_qcolor('accent_positive' if is_up else 'accent_negative')
            row_bg = self.theme_qcolor('accent_positive_bg' if is_up else 'accent_negative_bg')
            gain_color = self.theme_qcolor('accent_positive' if dollar_gain >= 0 else 'accent_negative')
            gain_sign = '+' if dollar_gain >= 0 else ''
            weight_str = f'{weight_pct:.1f}%' if shares else '--'
            gain_str = f'{gain_sign}${dollar_gain:,.0f}' if shares else '--'
            cols = [ticker, f'${price:.2f}', f'{sign}{change_pct:.2f}%', weight_str, gain_str]
            for col, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(row_bg)
                if col == 2:
                    item.setForeground(text_color)
                elif col == 4 and shares:
                    item.setForeground(gain_color)
                self.port_table.setItem(i, col, item)
            del_btn = QPushButton('x')
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            del_btn.setFixedWidth(24)
            del_btn.setFixedHeight(20)
            self.set_theme_variant(del_btn, 'danger')
            del_btn.clicked.connect(lambda checked, sym=ticker: self.remove_ticker(sym))
            self.port_table.setCellWidget(i, 5, del_btn)
        self._dashboard_fit_portfolio_table_height()

    def _dashboard_populate_option_tables(self, symbol: Any, data: Any) -> None:
        """Populate the dashboard options bucket tables."""
        raw_options = data.get('chart_options', {}).get(symbol, {})
        if isinstance(raw_options, list):
            raw_options = {'0_week': raw_options, '2_weeks': [], '4_weeks': []}
        elif isinstance(raw_options, dict) and '1_week' in raw_options and '0_week' not in raw_options:
            raw_options = {'0_week': raw_options.get('1_week', []), '2_weeks': raw_options.get('2_weeks', []), '4_weeks': raw_options.get('4_weeks', [])}
        expirations = data.get('chart_option_expirations', {}).get(symbol, {}) if isinstance(data.get('chart_option_expirations', {}), dict) else {}
        if isinstance(expirations, dict) and '1_week' in expirations and '0_week' not in expirations:
            expirations = {'0_week': expirations.get('1_week', ''), '2_weeks': expirations.get('2_weeks', ''), '4_weeks': expirations.get('4_weeks', '')}
        for bucket_key, table in self.dashboard_option_tables.items():
            table.setRowCount(0)
            records = raw_options.get(bucket_key, []) if isinstance(raw_options, dict) else []
            expiry_hint = str(expirations.get(bucket_key, '') or '')
            table.setToolTip(f'Using expiration {expiry_hint}' if expiry_hint else '')
            for opt in records:
                row = table.rowCount()
                table.insertRow(row)
                ticker_item = QTableWidgetItem(str(opt.get('ticker', symbol)))
                ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 0, ticker_item)
                type_item = QTableWidgetItem(str(opt.get('type', '')))
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if opt.get('type') == 'Call':
                    type_item.setForeground(self.theme_qcolor('accent_positive'))
                elif opt.get('type') == 'Put':
                    type_item.setForeground(self.theme_qcolor('accent_negative'))
                table.setItem(row, 1, type_item)
                strike = opt.get('strike')
                strike_item = QTableWidgetItem(f'{float(strike):.1f}' if strike is not None and not pd.isna(strike) else '')
                strike_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 2, strike_item)
                exp_item = QTableWidgetItem(str(opt.get('expiration', '')))
                exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 3, exp_item)
                last_price = opt.get('lastPrice')
                price_item = QTableWidgetItem(f'{float(last_price):.2f}' if last_price is not None and not pd.isna(last_price) else '')
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 4, price_item)
                volume = opt.get('volume', 0)
                vol_str = f'{int(volume):,}' if volume is not None and not pd.isna(volume) and float(volume) > 0 else '0'
                vol_item = QTableWidgetItem(vol_str)
                vol_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 5, vol_item)

    def update_ui(self, data: Any) -> Any:
        """Update the dashboard and shared pages with new data."""
        request_id = int(data.get('request_id', 0)) if isinstance(data, dict) else 0
        if request_id and request_id != getattr(self, '_dashboard_latest_request_id', 0):
            logger.info('Ignoring stale dashboard response %s; latest request is %s.', request_id, getattr(self, '_dashboard_latest_request_id', 0))
            return
        logger.info('Updating UI with new data')
        self.last_data = data
        self._set_data_collection_info(['yfinance'])
        self.repopulate_portfolio()
        for idx, info in data['market'].items():
            if idx in self.index_labels:
                price = info.get('price', 0)
                change = info.get('change', 0)
                sign = '+' if change >= 0 else ''
                self.index_labels[idx].setText(f'{idx}: {price:.2f} ({sign}{change:.2f}%)')
                color = self.theme_color('accent_positive' if change >= 0 else 'accent_negative')
                self.index_labels[idx].setStyleSheet(f'color: {color}; font-weight: bold; background: {self.theme_color("panel_background")}; border: 1px solid {self.theme_color("panel_border")}; border-radius: 4px; padding: 4px 8px;')
        main_targets = [item for item in data.get('targets', []) if item.get('ticker') in self.tickers]
        self.target_table.setRowCount(len(main_targets))
        for i, item in enumerate(main_targets):
            ticker_item = QTableWidgetItem(item['ticker'])
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 0, ticker_item)
            current = item['current']
            current_item = QTableWidgetItem(f'${current:.2f}' if isinstance(current, (int, float)) else str(current))
            current_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 1, current_item)
            target = item['target']
            target_item = QTableWidgetItem(f'${target:.2f}' if isinstance(target, (int, float)) else str(target))
            target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 2, target_item)
            try:
                upside = (float(target) - float(current)) / float(current) * 100
                upside_item = QTableWidgetItem(f'{upside:+.1f}%')
                upside_item.setForeground(self.theme_qcolor('accent_positive' if upside >= 0 else 'accent_negative'))
            except (TypeError, ValueError, ZeroDivisionError):
                upside_item = QTableWidgetItem('N/A')
            upside_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 3, upside_item)
        portfolio_news = self._sort_articles_by_newest([article for article in data.get('news', []) if article.get('category') != 'macro' and article.get('ticker') in self.tickers])
        self._populate_news_table(self.news_table, portfolio_news)
        self.update_page3(data)
        self.update_page4(data)
        self._p7_fetch_events()
        self._p6_update_total()

        symbol = self.dashboard_symbol
        self._dashboard_populate_option_tables(symbol, data)
        df = data.get('charts', {}).get(symbol)
        if df is None or df.empty:
            logger.warning('Dashboard chart has no validated data for %s.', symbol)
            self._dashboard_clear_chart(symbol)
            self.dashboard_load_btn.setEnabled(True)
            self.dashboard_refresh_btn.setEnabled(True)
            self._dashboard_set_status(f'Chart unavailable for {symbol}.', 'negative')
            return
        self.dashboard_chart_df = df
        self.dashboard_chart_interval = self.dashboard_timeframe_map.get(self.dashboard_timeframe_label, self.dashboard_timeframe_map['1 Day'])[1]
        close_value = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else close_value
        change_value = close_value - prev_close
        change_pct = change_value / prev_close * 100 if prev_close else 0.0
        self.dashboard_chart_stats = {
            'open': float(df['Open'].iloc[-1]),
            'high': float(df['High'].iloc[-1]),
            'low': float(df['Low'].iloc[-1]),
            'close': close_value,
            'change_value': change_value,
            'change_pct': change_pct,
        }
        previous_range = self._dashboard_get_current_x_range()
        self.dashboard_chart_rows = list(df.itertuples())
        self.dashboard_chart_ma200 = data.get('chart_ma200', {}).get(symbol)
        self.dashboard_rsi_series = self._p10_calculate_rsi(df['Close'])
        self.dashboard_symbol_label.setText(symbol)
        self._dashboard_render_main_chart(self.dashboard_chart_stats, self.dashboard_chart_interval, self.dashboard_rsi_series, self.dashboard_chart_ma200)
        if self.dashboard_auto_follow:
            self._dashboard_apply_auto_x_range(previous_range)
        else:
            self.dashboard_pending_x_range = previous_range
            self._dashboard_restore_manual_x_range()
        self._dashboard_update_quote_header(self.dashboard_chart_stats)
        self._dashboard_show_row_details(len(self.dashboard_chart_rows) - 1)
        self.dashboard_load_btn.setEnabled(True)
        self.dashboard_refresh_btn.setEnabled(True)
        self.dashboard_pending_x_range = None
        self._dashboard_update_indicator_panel_labels()
        self._dashboard_set_status(f'Loaded {symbol} {self.dashboard_timeframe_label}.', 'positive')

    def _apply_dashboard_theme(self) -> None:
        """Refresh dashboard colors after a theme change."""
        if hasattr(self, 'dashboard_main_plot'):
            self.style_plot_widget(self.dashboard_main_plot)
            self.style_plot_widget(self.dashboard_volume_plot, show_y_grid=False)
            self.style_plot_widget(self.dashboard_rsi_plot)
            self.dashboard_symbol_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
            self.dashboard_price_label.setStyleSheet(f'font-size: 20px; font-weight: bold; color: {self.theme_color("text_primary")};')
            self.dashboard_ohlc_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
            self._dashboard_set_status(self.dashboard_status_label.text(), self.dashboard_status_label.property('bt_status') or 'muted')
            self._dashboard_update_quote_header(getattr(self, 'dashboard_chart_stats', {}) or {'close': 0.0, 'change_value': 0.0, 'change_pct': 0.0})
            self._dashboard_update_auto_button_style()
            self._dashboard_update_timeframe_button_styles()
            self._dashboard_update_indicator_button_styles()
            if self.dashboard_chart_rows:
                self._dashboard_render_main_chart(self.dashboard_chart_stats, self.dashboard_chart_interval, self.dashboard_rsi_series, self.dashboard_chart_ma200)
        if getattr(self, 'last_data', None):
            self.repopulate_portfolio()
