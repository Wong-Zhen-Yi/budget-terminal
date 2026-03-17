from __future__ import annotations

from typing import Any

from ..compat import *


class PortfolioMetricsMixin:
    def _p4_returns_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio/timeframe pair."""
        return (str(portfolio_id or self.active_portfolio_id), str(timeframe_key))

    def _p4_invalidate_returns_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached return metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._return_metrics_cache = {
            key: value
            for key, value in self._return_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }
        self._return_metrics_fetching = {
            key: value
            for key, value in self._return_metrics_fetching.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }

    def _p4_active_tickers(self) -> Any:
        """Return tickers for the currently selected portfolio tab."""
        return getattr(self, 'active_tickers', self._get_portfolio_entry(self.active_portfolio_id).get('portfolio', []))

    def _p4_active_tracker_data(self) -> Any:
        """Return tracker data for the currently selected portfolio tab."""
        return getattr(
            self,
            'active_tracker_data',
            self._get_portfolio_entry(self.active_portfolio_id).setdefault('portfolio_tracker', {}),
        )

    def _get_return_timeframe_config(self, timeframe_key: Any) -> Any:
        """Return fetch/render config for the requested timeframe."""
        current_year = datetime.date.today().year
        configs = {
            'dip_finder': {'period': '1mo', 'interval': '1d', 'sort_reverse': True},
            'ytd': {'start': f'{current_year}-01-01', 'interval': '1d', 'sort_reverse': True},
            '1y': {'period': '1y', 'interval': '1d', 'sort_reverse': True},
        }
        return configs.get(timeframe_key, configs['dip_finder'])

    def _on_tracker_cell_changed(self, item: Any) -> None:
        """Handle tracker cell changed."""
        col = item.column()
        if col not in (P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_AVG_PRICE):
            return
        row = item.row()
        sym_item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
        if not sym_item:
            return
        ticker = sym_item.text()
        try:
            val = float(item.text().replace('$', '').replace(',', ''))
        except ValueError:
            return
        tracker_data = self._p4_active_tracker_data()
        tracker_entry = tracker_data.setdefault(ticker, {})
        tracker_entry['shares' if col == P4_PORTFOLIO_COL_SHARES else 'avg_price'] = val
        self._persist_all_portfolios()
        if self.last_data:
            self._recalc_tracker_row(row, ticker, self.last_data.get('portfolio', {}))

    def _p4_build_tracker_metrics_map(self, portfolio: Any) -> Any:
        """Precompute derived tracker metrics for the active portfolio."""
        tracker_data = self._p4_active_tracker_data()
        tickers = self._p4_active_tickers()
        metrics_map = {}
        total_market_value = 0.0
        for ticker in tickers:
            tracker_entry = tracker_data.get(ticker, {})
            shares = tracker_entry.get('shares', 0)
            avg_price = tracker_entry.get('avg_price', 0)
            price = portfolio.get(ticker, {}).get('price', 0)
            change = portfolio.get(ticker, {}).get('change', 0)
            cost = shares * avg_price
            market_value = shares * price
            dollar_gain = market_value - cost
            metrics_map[ticker] = {
                'shares': shares,
                'avg_price': avg_price,
                'price': price,
                'change': change,
                'cost': cost,
                'market_value': market_value,
                'dollar_gain': dollar_gain,
            }
            total_market_value += market_value
        for item in metrics_map.values():
            cost = item['cost']
            market_value = item['market_value']
            item['weight'] = market_value / total_market_value * 100 if total_market_value else 0
            item['growth'] = item['dollar_gain'] / cost * 100 if cost else 0
        return metrics_map, total_market_value

    def _recalc_tracker_row(self, row: Any, ticker: Any, portfolio: Any) -> None:
        """Handle recalc tracker row."""
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        metrics = metrics_map.get(ticker)
        if metrics is None:
            return
        self.p4_table.blockSignals(True)
        self._set_tracker_row(
            row,
            ticker,
            metrics['shares'],
            metrics['avg_price'],
            metrics['price'],
            metrics['change'],
            metrics['cost'],
            metrics['market_value'],
            metrics['weight'],
            metrics['dollar_gain'],
            metrics['growth'],
        )
        self.p4_table.blockSignals(False)
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        self._update_weight_chart({symbol: item['weight'] for symbol, item in metrics_map.items()})

    def _set_tracker_row(
        self,
        row: Any,
        ticker: Any,
        shares: Any,
        avg_price: Any,
        price: Any,
        change: Any,
        cost: Any,
        mkt_val: Any,
        weight: Any,
        dollar_gain: Any,
        growth: Any,
    ) -> Any:
        """Handle set tracker row."""
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        ed_flags = ro_flags | Qt.ItemFlag.ItemIsEditable
        gain_color = self.theme_qcolor('accent_positive' if dollar_gain >= 0 else 'accent_negative')
        change_color = self.theme_qcolor('accent_positive' if change >= 0 else 'accent_negative')

        def _item(text: Any, flags: Any = ro_flags, color: Any = None) -> Any:
            it = QTableWidgetItem(text)
            it.setFlags(flags)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                it.setForeground(color)
            return it

        self.p4_table.setItem(row, P4_PORTFOLIO_COL_SYMBOL, _item(ticker))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_SHARES, _item(f'{shares:g}', ed_flags))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_AVG_PRICE, _item(f'{avg_price:.2f}', ed_flags))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_COST, _item(f'${cost:,.2f}'))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_PRICE, _item(f'${price:.2f}'))
        sign = '+' if change >= 0 else ''
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_DAY_CHANGE, _item(f'{sign}{change:.2f}%', color=change_color))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_MARKET_VALUE, _item(f'${mkt_val:,.2f}'))
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_WEIGHT, _item(f'{weight:.1f}%'))
        gain_sign = '+' if dollar_gain >= 0 else ''
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_DOLLAR_GAIN, _item(f'{gain_sign}${dollar_gain:,.2f}', color=gain_color))
        growth_sign = '+' if growth >= 0 else ''
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_GROWTH, _item(f'{growth_sign}{growth:.1f}%', color=gain_color))
        del_btn = QPushButton('X')
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            f'background-color: {self.theme_color("accent_negative_bg")}; '
            f'color: {self.theme_color("text_primary")}; '
            f'border-radius: 11px; font-weight: bold; '
            f'border: 1px solid {self.theme_color("accent_negative")};'
        )
        if self.active_portfolio_id == self.main_portfolio_id:
            del_btn.clicked.connect(lambda checked=False, sym=ticker: self.remove_ticker(sym))
        else:
            del_btn.clicked.connect(lambda checked=False, sym=ticker: self._p4_remove_active_ticker(sym))
        self.p4_table.setCellWidget(row, P4_PORTFOLIO_COL_ACTION, del_btn)

    def _p4_remove_active_ticker(self, ticker: Any) -> None:
        """Remove a ticker from the currently selected page-4 portfolio."""
        tickers = self._p4_active_tickers()
        if ticker not in tickers:
            return
        tickers.remove(ticker)
        tracker_data = self._p4_active_tracker_data()
        tracker_data.pop(ticker, None)
        self._p4_invalidate_returns_cache()
        self._persist_all_portfolios()
        if self.last_data and self.active_portfolio_id == self.main_portfolio_id and 'portfolio' in self.last_data:
            self.last_data['portfolio'].pop(ticker, None)
        if self.last_data:
            self.update_page4(self.last_data)
        else:
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)

    def _update_returns_chart(self, timeframe_key: Any, results: Any) -> None:
        """Handle update returns chart."""
        pw = self.p4_returns_charts.get(timeframe_key)
        if pw is None:
            return
        pw.clear()
        config = self._get_return_timeframe_config(timeframe_key)
        tickers = sorted(
            [ticker for ticker in self._p4_active_tickers() if ticker in results],
            key=lambda ticker: results[ticker],
            reverse=config.get('sort_reverse', True),
        )
        if not tickers:
            return
        values = [results[ticker] for ticker in tickers]
        colors = [self.theme_color('accent_positive' if value >= 0 else 'accent_negative') for value in values]
        for xi, (value, color) in enumerate(zip(values, colors)):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=pg.mkBrush(color), pen=pg.mkPen(color)))
            sign = '+' if value >= 0 else ''
            label = pg.TextItem(text=f'{sign}{value:.1f}%', color=color, anchor=(0.5, 1.0 if value >= 0 else 0.0))
            label.setPos(xi, value)
            pw.addItem(label)
        pw.addItem(pg.InfiniteLine(pos=0, angle=0, pen=self.theme_pen('chart_reference', width=1)))
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        max_v = max((abs(value) for value in values)) if values else 1
        pw.setYRange(-max_v * 1.6, max_v * 1.6)
        pw.setXRange(-0.6, len(tickers) - 0.4)

    def _update_weight_chart(self, weights: Any) -> None:
        """Render portfolio weights as a descending bar chart."""
        pw = self.p4_weight_chart
        pw.clear()
        tickers = [ticker for ticker, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True) if weight > 0]
        if not tickers:
            pw.getPlotItem().hideAxis('bottom')
            pw.getPlotItem().hideAxis('left')
            return
        values = [weights[ticker] for ticker in tickers]
        colors = list(self.theme_pie_palette())
        brushes = [pg.mkBrush(colors[i % len(colors)]) for i in range(len(tickers))]
        pens = [pg.mkPen(colors[i % len(colors)]) for i in range(len(tickers))]
        max_value = max(values) if values else 1
        label_offset = max(max_value * 0.04, 0.6)
        for xi, (ticker, value, brush, pen) in enumerate(zip(tickers, values, brushes, pens)):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=brush, pen=pen))
            label = pg.TextItem(text=f'{value:.1f}%', color=self.theme_color('text_primary'), anchor=(0.5, 1.0))
            label.setPos(xi, value + label_offset)
            pw.addItem(label)
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        pw.setYRange(0, max_value + label_offset + max(max_value * 0.15, 0.5))
        pw.setXRange(-0.6, len(tickers) - 0.4)

    def _launch_worker(self, worker_obj: Any, finished_slot: Any, flag_attr: Any) -> Any:
        """Guard-and-launch helper for background workers."""
        if getattr(self, flag_attr, False):
            return False
        setattr(self, flag_attr, True)
        worker_obj.finished.connect(finished_slot)
        threading.Thread(target=worker_obj.run, daemon=True).start()
        return True

    def _fetch_returns_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch returns for a specific timeframe."""
        portfolio_id = str(self.active_portfolio_id)
        cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        if self._return_metrics_fetching.get(cache_key, False):
            return
        tickers = list(self._p4_active_tickers())
        if not tickers:
            self._return_metrics_cache[cache_key] = {}
            self._return_metrics_fetching[cache_key] = False
            if portfolio_id == str(self.active_portfolio_id) and timeframe_key == self._active_return_timeframe:
                self._update_returns_chart(timeframe_key, {})
            return
        config = self._get_return_timeframe_config(timeframe_key)
        self._return_metrics_fetching[cache_key] = True
        worker = MonthReturnWorker(
            tickers,
            period=config.get('period', '1mo'),
            interval=config.get('interval', '1d'),
            start=config.get('start'),
        )
        worker.finished.connect(
            lambda results, key=timeframe_key, pid=portfolio_id: self._on_returns_ready(key, pid, results)
        )
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_returns_ready(self, timeframe_key: Any, portfolio_id: Any, results: Any) -> None:
        """Handle return metrics ready."""
        cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        self._return_metrics_fetching[cache_key] = False
        self._return_metrics_cache[cache_key] = results
        if str(portfolio_id) == str(self.active_portfolio_id) and timeframe_key == self._active_return_timeframe:
            self._update_returns_chart(timeframe_key, results)

    def _on_returns_timeframe_changed(self, index: int) -> None:
        """Handle return timeframe tab changes."""
        if index < 0 or index >= len(self.p4_return_timeframes):
            return
        timeframe_key = self.p4_return_timeframes[index][0]
        self._active_return_timeframe = timeframe_key
        cache_key = self._p4_returns_cache_key(timeframe_key)
        if cache_key in self._return_metrics_cache:
            self._update_returns_chart(timeframe_key, self._return_metrics_cache.get(cache_key, {}))
            return
        self._fetch_returns_for_timeframe(timeframe_key)

    def _format_market_cap(self, mc: Any) -> Any:
        """Handle format market cap."""
        if mc is None:
            return '-'
        if mc >= 200000000000:
            return f'Mega  ${mc / 1000000000000.0:.2f}T'
        if mc >= 10000000000:
            return f'Large  ${mc / 1000000000.0:.1f}B'
        if mc >= 2000000000:
            return f'Mid  ${mc / 1000000000.0:.1f}B'
        if mc >= 300000000:
            return f'Small  ${mc / 1000000.0:.0f}M'
        return f'Micro  ${mc / 1000000.0:.0f}M'

    def _mktcap_color(self, mc: Any) -> Any:
        """Handle mktcap color."""
        if mc is None:
            return self.theme_color('text_muted')
        if mc >= 200000000000:
            return self.theme_color('warning')
        if mc >= 10000000000:
            return self.theme_series_color(0)
        if mc >= 2000000000:
            return self.theme_color('accent_positive')
        if mc >= 300000000:
            return self.theme_series_color(3)
        return self.theme_color('accent_negative')

    def _update_mktcap_item(self, row: Any, ticker: Any, mc: Any) -> None:
        """Handle update mktcap item."""
        text = self._format_market_cap(mc)
        item = self.p4_table.item(row, P4_PORTFOLIO_COL_MARKET_CAP)
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self.p4_table.blockSignals(True)
        if item is None:
            item = QTableWidgetItem(text)
            item.setFlags(ro_flags)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p4_table.setItem(row, P4_PORTFOLIO_COL_MARKET_CAP, item)
        else:
            item.setText(text)
        self.p4_table.blockSignals(False)
        item.setForeground(QColor(self._mktcap_color(mc)))

    def _fetch_market_caps(self) -> None:
        """Fetch market caps."""
        self._launch_worker(MarketCapWorker(list(self._p4_active_tickers())), self._on_market_caps_ready, '_mktcap_fetching')

    def _on_market_caps_ready(self, results: Any) -> None:
        """Handle market caps ready."""
        self._mktcap_fetching = False
        self._mktcap_cache.update(results)
        for row in range(self.p4_table.rowCount()):
            item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
            if item and item.text() in results:
                self._update_mktcap_item(row, item.text(), results[item.text()])

    def update_page4(self, data: Any) -> None:
        """Update page4."""
        portfolio = data.get('portfolio', {})
        tickers = self._p4_active_tickers()
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        self.p4_table.blockSignals(True)
        self.p4_table.setRowCount(len(tickers))
        sorted_tickers = sorted(tickers, key=lambda ticker: metrics_map.get(ticker, {}).get('market_value', 0), reverse=True)
        weights = {}
        for i, ticker in enumerate(sorted_tickers):
            metrics = metrics_map.get(ticker, {})
            weights[ticker] = metrics.get('weight', 0)
            self._set_tracker_row(
                i,
                ticker,
                metrics.get('shares', 0),
                metrics.get('avg_price', 0),
                metrics.get('price', 0),
                metrics.get('change', 0),
                metrics.get('cost', 0),
                metrics.get('market_value', 0),
                metrics.get('weight', 0),
                metrics.get('dollar_gain', 0),
                metrics.get('growth', 0),
            )
            if ticker in self._mktcap_cache:
                self._update_mktcap_item(i, ticker, self._mktcap_cache[ticker])
        self.p4_table.blockSignals(False)
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        self._update_weight_chart(weights)
        active_cache_key = self._p4_returns_cache_key(self._active_return_timeframe)
        if not tickers:
            self._return_metrics_cache[active_cache_key] = {}
            self._return_metrics_fetching[active_cache_key] = False
            self._update_returns_chart(self._active_return_timeframe, {})
        elif active_cache_key in self._return_metrics_cache:
            self._update_returns_chart(
                self._active_return_timeframe,
                self._return_metrics_cache.get(active_cache_key, {}),
            )
        else:
            self._fetch_returns_for_timeframe(self._active_return_timeframe)
        self._fetch_market_caps()
