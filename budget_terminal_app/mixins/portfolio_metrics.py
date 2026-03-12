from __future__ import annotations
from typing import Any
from ..compat import *

class PortfolioMetricsMixin:

    def _p4_returns_cache_key(self, timeframe_key: Any, portfolio_id: Any=None) -> Any:
        """Build the cache key for one portfolio/timeframe pair."""
        return (str(portfolio_id or self.active_portfolio_id), str(timeframe_key))

    def _p4_invalidate_returns_cache(self, portfolio_id: Any=None) -> None:
        """Drop cached return metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._return_metrics_cache = {
            key: value for key, value in self._return_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }
        self._return_metrics_fetching = {
            key: value for key, value in self._return_metrics_fetching.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }

    def _p4_active_tickers(self) -> Any:
        """Return tickers for the currently selected portfolio tab."""
        return getattr(self, 'active_tickers', self._get_portfolio_entry(self.active_portfolio_id).get('portfolio', []))

    def _p4_active_tracker_data(self) -> Any:
        """Return tracker data for the currently selected portfolio tab."""
        return getattr(self, 'active_tracker_data', self._get_portfolio_entry(self.active_portfolio_id).setdefault('portfolio_tracker', {}))

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
        if ticker not in tracker_data:
            tracker_data[ticker] = {}
        key = 'shares' if col == P4_PORTFOLIO_COL_SHARES else 'avg_price'
        tracker_data[ticker][key] = val
        self._persist_all_portfolios()
        if self.last_data:
            self._recalc_tracker_row(row, ticker, self.last_data.get('portfolio', {}))

    def _recalc_tracker_row(self, row: Any, ticker: Any, portfolio: Any) -> None:
        """Handle recalc tracker row."""
        tracker_data = self._p4_active_tracker_data()
        tickers = self._p4_active_tickers()
        td = tracker_data.get(ticker, {})
        shares = td.get('shares', 0)
        avg_price = td.get('avg_price', 0)
        price = portfolio.get(ticker, {}).get('price', 0)
        change = portfolio.get(ticker, {}).get('change', 0)
        cost = shares * avg_price
        mkt_val = shares * price
        total_market_value = sum((tracker_data.get(t, {}).get('shares', 0) * portfolio.get(t, {}).get('price', 0) for t in tickers))
        weight = mkt_val / total_market_value * 100 if total_market_value else 0
        dollar_gain = mkt_val - cost
        growth = dollar_gain / cost * 100 if cost else 0
        self.p4_table.blockSignals(True)
        self._set_tracker_row(row, ticker, shares, avg_price, price, change, cost, mkt_val, weight, dollar_gain, growth)
        self.p4_table.blockSignals(False)
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        weights = {}
        for t in tickers:
            td2 = tracker_data.get(t, {})
            s = td2.get('shares', 0)
            p = portfolio.get(t, {}).get('price', 0)
            mv = s * p
            weights[t] = mv / total_market_value * 100 if total_market_value else 0
        self._update_weight_chart(weights)

    def _set_tracker_row(self, row: Any, ticker: Any, shares: Any, avg_price: Any, price: Any, change: Any, cost: Any, mkt_val: Any, weight: Any, dollar_gain: Any, growth: Any) -> Any:
        """Handle set tracker row."""
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        ed_flags = ro_flags | Qt.ItemFlag.ItemIsEditable
        gain_color = QColor(CLR_UP) if dollar_gain >= 0 else QColor(CLR_DOWN)
        change_color = QColor(CLR_UP) if change >= 0 else QColor(CLR_DOWN)

        def _item(text: Any, flags: Any=ro_flags, color: Any=None) -> Any:
            """Handle item."""
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
        sign2 = '+' if dollar_gain >= 0 else ''
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_DOLLAR_GAIN, _item(f'{sign2}${dollar_gain:,.2f}', color=gain_color))
        sign3 = '+' if growth >= 0 else ''
        self.p4_table.setItem(row, P4_PORTFOLIO_COL_GROWTH, _item(f'{sign3}{growth:.1f}%', color=gain_color))
        del_btn = QPushButton('X')
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet('background-color: #770000; color: white; border-radius: 11px; font-weight: bold;')
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
        if ticker in tracker_data:
            del tracker_data[ticker]
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
        tickers = sorted([t for t in self._p4_active_tickers() if t in results], key=lambda t: results[t], reverse=config.get('sort_reverse', True))
        if not tickers:
            return
        values = [results[t] for t in tickers]
        for xi, (val, color) in enumerate(zip(values, [CLR_UP if v >= 0 else CLR_DOWN for v in values])):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[val], width=0.6, brush=pg.mkBrush(color), pen=pg.mkPen(color)))
            sign = '+' if val >= 0 else ''
            label = pg.TextItem(text=f'{sign}{val:.1f}%', color=color, anchor=(0.5, 1.0 if val >= 0 else 0.0))
            label.setPos(xi, val)
            pw.addItem(label)
        pw.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#555555', width=1)))
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, t) for i, t in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        max_v = max((abs(v) for v in values)) if values else 1
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
        colors = getattr(PieChartWidget, 'COLORS', ['#4fc3f7'])
        brushes = [pg.mkBrush(colors[i % len(colors)]) for i in range(len(tickers))]
        pens = [pg.mkPen(colors[i % len(colors)]) for i in range(len(tickers))]
        for xi, (ticker, val, brush, pen) in enumerate(zip(tickers, values, brushes, pens)):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[val], width=0.6, brush=brush, pen=pen))
            label = pg.TextItem(text=f'{val:.1f}%', color='white', anchor=(0.5, 0.0))
            label.setPos(xi, val)
            pw.addItem(label)
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, t) for i, t in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        pw.setYRange(0, max(values) * 1.25 if values else 1)
        pw.setXRange(-0.6, len(tickers) - 0.4)

    def _launch_worker(self, worker_obj: Any, finished_slot: Any, flag_attr: Any) -> Any:
        """Guard-and-launch helper for background workers.
        Returns False (and does nothing) if the worker is already running."""
        if getattr(self, flag_attr, False):
            return False
        setattr(self, flag_attr, True)
        worker_obj.finished.connect(finished_slot)
        threading.Thread(target=worker_obj.run, daemon=True).start()
        return True

    def _fetch_returns_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch returns for a specific timeframe."""
        cache_key = self._p4_returns_cache_key(timeframe_key)
        if self._return_metrics_fetching.get(cache_key, False):
            return
        config = self._get_return_timeframe_config(timeframe_key)
        self._return_metrics_fetching[cache_key] = True
        worker = MonthReturnWorker(
            self._p4_active_tickers(),
            period=config.get('period', '1mo'),
            interval=config.get('interval', '1d'),
            start=config.get('start'),
        )
        worker.finished.connect(lambda results, key=timeframe_key: self._on_returns_ready(key, results))
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_returns_ready(self, timeframe_key: Any, results: Any) -> None:
        """Handle return metrics ready."""
        cache_key = self._p4_returns_cache_key(timeframe_key)
        self._return_metrics_fetching[cache_key] = False
        self._return_metrics_cache[cache_key] = results
        if timeframe_key == self._active_return_timeframe:
            self._update_returns_chart(timeframe_key, results)

    def _on_returns_timeframe_changed(self, index: int) -> None:
        """Handle return timeframe tab changes."""
        if index < 0 or index >= len(self.p4_return_timeframes):
            return
        timeframe_key = self.p4_return_timeframes[index][0]
        self._active_return_timeframe = timeframe_key
        cached = self._return_metrics_cache.get(self._p4_returns_cache_key(timeframe_key))
        if cached:
            self._update_returns_chart(timeframe_key, cached)
            return
        self._fetch_returns_for_timeframe(timeframe_key)

    def _format_market_cap(self, mc: Any) -> Any:
        """Handle format market cap."""
        if mc is None:
            return '—'
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
            return '#888888'
        if mc >= 200000000000:
            return '#ffd700'
        if mc >= 10000000000:
            return '#4fc3f7'
        if mc >= 2000000000:
            return '#81c784'
        if mc >= 300000000:
            return '#ffb74d'
        return '#ef9a9a'

    def _update_mktcap_item(self, row: Any, ticker: Any, mc: Any) -> None:
        """Handle update mktcap item."""
        text = self._format_market_cap(mc)
        item = self.p4_table.item(row, P4_PORTFOLIO_COL_MARKET_CAP)
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if item is None:
            item = QTableWidgetItem(text)
            item.setFlags(ro_flags)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p4_table.blockSignals(True)
            self.p4_table.setItem(row, P4_PORTFOLIO_COL_MARKET_CAP, item)
            self.p4_table.blockSignals(False)
        else:
            self.p4_table.blockSignals(True)
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
        tracker_data = self._p4_active_tracker_data()
        self.p4_table.blockSignals(True)
        self.p4_table.setRowCount(len(tickers))
        total_market_value = sum((tracker_data.get(t, {}).get('shares', 0) * portfolio.get(t, {}).get('price', 0) for t in tickers))
        sorted_tickers = sorted(tickers, key=lambda t: tracker_data.get(t, {}).get('shares', 0) * portfolio.get(t, {}).get('price', 0), reverse=True)
        weights = {}
        for i, t in enumerate(sorted_tickers):
            td = tracker_data.get(t, {})
            shares = td.get('shares', 0)
            avg_price = td.get('avg_price', 0)
            price = portfolio.get(t, {}).get('price', 0)
            change = portfolio.get(t, {}).get('change', 0)
            cost = shares * avg_price
            mkt_val = shares * price
            weight = mkt_val / total_market_value * 100 if total_market_value else 0
            dollar_gain = mkt_val - cost
            growth = dollar_gain / cost * 100 if cost else 0
            weights[t] = weight
            self._set_tracker_row(i, t, shares, avg_price, price, change, cost, mkt_val, weight, dollar_gain, growth)
            if t in self._mktcap_cache:
                self._update_mktcap_item(i, t, self._mktcap_cache[t])
        self.p4_table.blockSignals(False)
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        self._update_weight_chart(weights)
        active_results = self._return_metrics_cache.get(self._p4_returns_cache_key(self._active_return_timeframe))
        if active_results:
            self._update_returns_chart(self._active_return_timeframe, active_results)
        else:
            self._fetch_returns_for_timeframe(self._active_return_timeframe)
        self._fetch_market_caps()
