from __future__ import annotations
import math
from typing import Any
from ..compat import *

P1_DEFAULT_STARTUP_SPAN = 80.0
P1_MIN_REUSABLE_SPAN = 10.0
P1_RIGHT_PAD = 0.75

class DashboardMixin:

    def _update_main_portfolio_entry(self) -> Any:
        """Persist the current app-wide portfolio fields into the main portfolio slot."""
        entry = self._get_portfolio_entry(self.main_portfolio_id)
        entry['portfolio'] = self.tickers
        entry['chart_slots'] = self.chart_slots
        entry['portfolio_tracker'] = self.tracker_data
        return entry

    def _dashboard_get_x_range(self, slot_index: Any) -> Any:
        """Return the current x-range for a dashboard chart."""
        try:
            return tuple(self.charts[slot_index].getPlotItem().vb.viewRange()[0])
        except Exception:
            return None

    def _dashboard_set_x_range(self, slot_index: Any, x_range: Any) -> None:
        """Set the x-range for a dashboard chart without re-entering handlers."""
        if not x_range:
            return
        left, right = x_range
        if right <= left:
            return
        self.dashboard_chart_view_guards[slot_index] = True
        try:
            self.charts[slot_index].setXRange(float(left), float(right), padding=0)
        finally:
            self.dashboard_chart_view_guards[slot_index] = False

    def _dashboard_is_reusable_x_range(self, x_range: Any) -> bool:
        """Return whether a dashboard chart x-range is meaningful enough to reuse."""
        if not x_range:
            return False
        try:
            left = float(x_range[0])
            right = float(x_range[1])
        except Exception:
            return False
        return right > left and (right - left) >= P1_MIN_REUSABLE_SPAN

    def _dashboard_normalize_x_range(self, slot_index: Any, x_range: Any) -> Any:
        """Clamp dashboard x-ranges so the newest candle stays visible without a large trailing gap."""
        rows = self.dashboard_chart_rows[slot_index]
        if not x_range or not rows:
            return None
        left, right = (float(x_range[0]), float(x_range[1]))
        span = max(2.0, right - left)
        latest_index = float(len(rows) - 1)
        max_right = latest_index + P1_RIGHT_PAD
        max_left = max(0.0, max_right - span)
        normalized_right = min(right, max_right)
        normalized_left = max(0.0, min(left, max_left))
        if normalized_right - normalized_left < span:
            normalized_left = max(0.0, normalized_right - span)
            normalized_right = min(max_right, normalized_left + span)
        if normalized_right <= normalized_left:
            normalized_right = min(max_right, normalized_left + max(2.0, min(span, latest_index + P1_RIGHT_PAD + 1.0)))
        return (normalized_left, normalized_right)

    def _dashboard_get_visible_rows(self, slot_index: Any, x_range: Any=None) -> Any:
        """Return visible chart rows for the requested dashboard slot."""
        rows = self.dashboard_chart_rows[slot_index]
        if not rows:
            return []
        active_range = x_range or self._dashboard_get_x_range(slot_index)
        if not active_range:
            return list(rows)
        left = max(0, int(math.floor(float(active_range[0]))))
        right = min(len(rows) - 1, int(math.ceil(float(active_range[1]))))
        if right < left:
            return []
        return rows[left:right + 1]

    def _dashboard_apply_auto_y_range(self, slot_index: Any, x_range: Any=None) -> None:
        """Fit the dashboard chart y-axis to visible candles and the visible 200 MA."""
        visible_rows = self._dashboard_get_visible_rows(slot_index, x_range)
        if not visible_rows:
            return
        lows = [float(getattr(row, 'Low')) for row in visible_rows]
        highs = [float(getattr(row, 'High')) for row in visible_rows]
        ma200_series = self.dashboard_chart_ma200[slot_index]
        if slot_index == 2 and ma200_series is not None:
            active_range = x_range or self._dashboard_get_x_range(slot_index)
            if active_range:
                left = max(0, int(math.floor(float(active_range[0]))))
                right = min(len(ma200_series) - 1, int(math.ceil(float(active_range[1]))))
                if right >= left:
                    ma_values = [float(value) for value in ma200_series.iloc[left:right + 1] if not pd.isna(value)]
                    if ma_values:
                        lows.append(min(ma_values))
                        highs.append(max(ma_values))
        low_value = min(lows)
        high_value = max(highs)
        span = high_value - low_value
        padding = max(0.5, span * 0.08) if span > 0 else max(abs(high_value) * 0.03, 1.0)
        self.charts[slot_index].setYRange(low_value - padding, high_value + padding, padding=0)

    def _dashboard_apply_auto_view(self, slot_index: Any, source_range: Any=None) -> None:
        """Anchor the latest candle near the right side of the dashboard chart."""
        rows = self.dashboard_chart_rows[slot_index]
        if not rows:
            return
        latest_index = float(len(rows) - 1)
        if self._dashboard_is_reusable_x_range(source_range):
            span = max(P1_MIN_REUSABLE_SPAN, float(source_range[1]) - float(source_range[0]))
        else:
            span = max(20.0, min(P1_DEFAULT_STARTUP_SPAN, float(len(rows))))
        anchored = self._dashboard_normalize_x_range(slot_index, (latest_index - span + P1_RIGHT_PAD, latest_index + P1_RIGHT_PAD))
        if not anchored:
            return
        self._dashboard_set_x_range(slot_index, anchored)
        self._dashboard_apply_auto_y_range(slot_index, anchored)

    def _dashboard_on_x_range_changed(self, slot_index: Any, *_: Any) -> None:
        """Keep dashboard charts in auto-follow mode when the user zooms."""
        if self.dashboard_chart_view_guards[slot_index] or not self.dashboard_chart_rows[slot_index]:
            return
        current_range = self._dashboard_get_x_range(slot_index)
        if not current_range:
            return
        self._dashboard_apply_auto_view(slot_index, current_range)

    def add_ticker(self) -> None:
        """Add ticker."""
        t = self.ticker_input.text().upper().strip()
        if t:
            if t in self.tickers:
                logger.info(f'Ticker {t} already in portfolio')
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
            logger.info(f'Removed ticker {t}')

    def refresh_data(self) -> None:
        """Handle refresh data."""
        self._news_auto_summarized = False
        if hasattr(self, 'p3_summary_status'):
            self.p3_summary_status.setText('Refreshing news...')
        if hasattr(self, 'p3_summary_text') and not self._p3_summarizing:
            self.p3_summary_text.setPlainText('Refreshing loaded headlines...')
        new_slots = [inp.text().upper() for inp in self.chart_inputs]
        if new_slots != self.chart_slots:
            self.chart_slots = new_slots
            self._update_main_portfolio_entry()
            self._persist_all_portfolios()
        self.chart_configs = []
        for i in range(3):
            ticker = self.chart_inputs[i].text().upper()
            period, interval = self.timeframe_combos[i].currentData()
            self.chart_configs.append((ticker, period, interval))
        self.worker_thread = threading.Thread(target=self.run_worker, daemon=True)
        self.worker_thread.start()

    def run_worker(self) -> None:
        """Handle run worker."""
        worker = DataWorker(self._get_fetch_tickers(), self.chart_configs)
        worker.finished.connect(self.update_ui)
        worker.error.connect(self.handle_error)
        worker.run()

    def handle_error(self, error_msg: Any) -> None:
        """Handle handle error."""
        logger.error(f'UI received error: {error_msg}')

    def open_news_link(self, item: Any) -> None:
        """Open news link."""
        row = item.row()
        headline_item = self.news_table.item(row, 0)
        url = headline_item.data(Qt.ItemDataRole.UserRole)
        if url:
            logger.info(f'Opening news link: {url}')
            webbrowser.open(url)

    def repopulate_portfolio(self) -> Any:
        """Handle repopulate portfolio."""
        if not self.last_data:
            return
        portfolio = {ticker: info for ticker, info in self.last_data.get('portfolio', {}).items() if ticker in self.tickers}
        if hasattr(self, '_p4_portfolio_name'):
            header_name = self._p4_portfolio_name(self.main_portfolio_index)
        else:
            header_name = 'My Portfolio'
        self.port_header_lbl.setText(f'{header_name} ({len(portfolio)})')
        tracker = getattr(self, 'tracker_data', {})

        def market_value(t: Any, info: Any) -> Any:
            """Handle market value."""
            shares = tracker.get(t, {}).get('shares', 0)
            return shares * info['price'] if shares else 0
        total_value = sum((market_value(t, info) for t, info in portfolio.items()))
        sorted_items = sorted(portfolio.items(), key=lambda x: market_value(x[0], x[1]), reverse=True)
        self.port_table.setRowCount(len(sorted_items))
        for i, (t, info) in enumerate(sorted_items):
            price = info['price']
            change_pct = info['change']
            shares = tracker.get(t, {}).get('shares', 0)
            avg_price = tracker.get(t, {}).get('avg_price', 0)
            mv = shares * price if shares else 0
            weight_pct = mv / total_value * 100 if total_value > 0 and shares else 0
            dollar_gain = (price - avg_price) * shares if shares else 0
            is_up = change_pct >= 0
            sign = '+' if is_up else ''
            text_color = self.theme_qcolor('accent_positive' if is_up else 'accent_negative')
            row_bg = self.theme_qcolor('accent_positive_bg' if is_up else 'accent_negative_bg')
            gain_color = self.theme_qcolor('accent_positive' if dollar_gain >= 0 else 'accent_negative')
            gain_sign = '+' if dollar_gain >= 0 else ''
            weight_str = f'{weight_pct:.1f}%' if shares else '—'
            gain_str = f'{gain_sign}${dollar_gain:,.0f}' if shares else '—'
            cols = [t, f'${price:.2f}', f'{sign}{change_pct:.2f}%', weight_str, gain_str]
            for col, val in enumerate(cols):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(row_bg)
                if col == 2:
                    item.setForeground(text_color)
                elif col == 4 and shares:
                    item.setForeground(gain_color)
                self.port_table.setItem(i, col, item)
            del_btn = QPushButton('×')
            del_btn.setFixedSize(20, 20)
            del_btn.setStyleSheet(f'background-color: {self.theme_color("accent_negative_bg")}; color: {self.theme_color("text_primary")}; border-radius: 10px; font-weight: bold; border: 1px solid {self.theme_color("accent_negative")};')
            del_btn.clicked.connect(lambda checked, sym=t: self.remove_ticker(sym))
            self.port_table.setCellWidget(i, 5, del_btn)

    def update_ui(self, data: Any) -> Any:
        """Update ui."""
        logger.info('Updating UI with new data')
        self.last_data = data
        self._set_data_collection_info(['yfinance'])
        self.repopulate_portfolio()
        for idx, info in data['market'].items():
            if idx in self.index_labels:
                price = info['price']
                change = info['change']
                sign = '+' if change >= 0 else ''
                color = self.theme_color('accent_positive' if change >= 0 else 'accent_negative')
                self.index_labels[idx].setText(f'{idx}: {price:.2f} ({sign}{change:.2f}%)')
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
                upside_str = f'{upside:+.1f}%'
                upside_item = QTableWidgetItem(upside_str)
                upside_item.setForeground(self.theme_qcolor('accent_positive' if upside >= 0 else 'accent_negative'))
            except (TypeError, ValueError, ZeroDivisionError):
                upside_item = QTableWidgetItem('N/A')
            upside_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.target_table.setItem(i, 3, upside_item)
        portfolio_news = self._sort_articles_by_newest([a for a in data.get('news', []) if a.get('category') != 'macro' and a.get('ticker') in self.tickers])
        self._populate_news_table(self.news_table, portfolio_news)
        self.update_page3(data)
        self.update_page4(data)
        self._p7_fetch_events()
        self._p6_update_total()
        for i, (t, p, interval) in enumerate(self.chart_configs):
            table = self.option_tables[i]
            table.setRowCount(0)
            opts = data.get('chart_options', {}).get(t, [])
            for opt in opts:
                row = table.rowCount()
                table.insertRow(row)
                ticker_item = QTableWidgetItem(str(opt['ticker']))
                ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 0, ticker_item)
                type_item = QTableWidgetItem(str(opt['type']))
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if opt['type'] == 'Call':
                    type_item.setForeground(self.theme_qcolor('accent_positive'))
                else:
                    type_item.setForeground(self.theme_qcolor('accent_negative'))
                table.setItem(row, 1, type_item)
                strike_item = QTableWidgetItem(f"{opt['strike']:.1f}")
                strike_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 2, strike_item)
                exp_item = QTableWidgetItem(str(opt.get('expiration', '')))
                exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 3, exp_item)
                price_item = QTableWidgetItem(f"{opt['lastPrice']:.2f}")
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 4, price_item)
                vol = opt.get('volume', 0)
                vol_str = f'{int(vol):,}' if not pd.isna(vol) and vol > 0 else '0'
                vol_item = QTableWidgetItem(vol_str)
                vol_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 5, vol_item)
            if t in data['charts']:
                df = data['charts'][t]
                previous_range = self._dashboard_get_x_range(i)
                self.charts[i].clear()
                self.dashboard_chart_rows[i] = []
                self.dashboard_chart_ma200[i] = data.get('chart_ma200', {}).get(t)
                if not df.empty:

                    def normalize_col(c: Any) -> Any:
                        """Handle normalize col."""
                        if isinstance(c, tuple):
                            return c[0].lower()
                        return str(c).lower()
                    cols = {normalize_col(c): c for c in df.columns}

                    def get_attr_name(c: Any) -> Any:
                        """Handle get attr name."""
                        if isinstance(c, tuple):
                            return c[0]
                        return str(c)
                    o_col = get_attr_name(cols.get('open', 'Open'))
                    c_col = get_attr_name(cols.get('close', 'Close'))
                    l_col = get_attr_name(cols.get('low', 'Low'))
                    h_col = get_attr_name(cols.get('high', 'High'))
                    points = []
                    last_price = 0
                    for idx, r in enumerate(df.itertuples()):
                        try:
                            o = getattr(r, o_col)
                            c = getattr(r, c_col)
                            l = getattr(r, l_col)
                            h = getattr(r, h_col)
                            points.append((idx, o, c, l, h))
                            last_price = c
                        except AttributeError:
                            points.append((idx, r[1], r[4], r[3], r[2]))
                            last_price = r[4]
                    self.dashboard_chart_rows[i] = list(df.itertuples())
                    item = CandlestickItem(
                        points,
                        up_color=self.theme_color('chart_up_candle'),
                        down_color=self.theme_color('chart_down_candle'),
                    )
                    self.charts[i].addItem(item)
                    ma200_series = self.dashboard_chart_ma200[i]
                    if i == 2 and ma200_series is not None:
                        ma_values = [float(value) if not pd.isna(value) else float('nan') for value in ma200_series]
                        if ma_values:
                            self.charts[i].plot(list(range(len(ma_values))), ma_values, pen=self.theme_pen('chart_ma', width=1.8))
                    price_line = pg.InfiniteLine(pos=last_price, angle=0, pen=self.theme_pen('chart_reference', style=Qt.PenStyle.DashLine))
                    self.charts[i].addItem(price_line)
                    dates = df.index.to_list()
                    self.date_axes[i].set_dates(dates, interval)
                    self._dashboard_apply_auto_view(i, previous_range)
                    self.charts[i].setTitle(f'{t} - Current: ${last_price:.2f}')

    def _apply_dashboard_theme(self) -> None:
        """Refresh dashboard colors after a theme change."""
        if getattr(self, 'last_data', None):
            self.update_ui(self.last_data)
