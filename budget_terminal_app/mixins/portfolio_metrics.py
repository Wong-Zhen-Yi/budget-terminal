from __future__ import annotations

from typing import Any

from ..compat import *

_P4_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0


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

    def _p4_momentum_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio momentum timeframe pair."""
        return (str(portfolio_id or self.active_portfolio_id), str(timeframe_key))

    def _p4_invalidate_momentum_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached momentum metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._momentum_metrics_cache = {
            key: value
            for key, value in self._momentum_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }
        self._momentum_metrics_fetching = {
            key: value
            for key, value in self._momentum_metrics_fetching.items()
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

    def _p4_export_for_llm(self) -> None:
        """Export the active portfolio's stock and options data to clipboard for LLM analysis."""
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        tickers = self._p4_active_tickers()
        tracker_data = self._p4_active_tracker_data()
        options_data = getattr(self, 'active_options_data', getattr(self, 'options_data', []))
        active_index = self._p4_get_active_portfolio_index()
        portfolio_name = self._p4_portfolio_name(active_index)
        lines = []
        lines.append(f'=== PORTFOLIO EXPORT: {portfolio_name} ===')
        lines.append('')
        lines.append('--- STOCK POSITIONS ---')
        lines.append('')
        if not tickers:
            lines.append('(no stock positions)')
            lines.append('')
        else:
            metrics_map, total_mv = self._p4_build_tracker_metrics_map(portfolio)
            sorted_tickers = sorted(tickers, key=lambda t: metrics_map.get(t, {}).get('market_value', 0), reverse=True)
            for ticker in sorted_tickers:
                m = metrics_map.get(ticker, {})
                shares = m.get('shares', 0)
                avg_price = m.get('avg_price', 0)
                price = m.get('price', 0)
                change = m.get('change', 0)
                cost = m.get('cost', 0)
                mv = m.get('market_value', 0)
                weight = m.get('weight', 0)
                gain = m.get('dollar_gain', 0)
                growth = m.get('growth', 0)
                mc = self._mktcap_cache.get(ticker)
                mc_str = self._format_market_cap(mc) if mc is not None else 'N/A'
                sign = '+' if change >= 0 else ''
                gain_sign = '+' if gain >= 0 else ''
                growth_sign = '+' if growth >= 0 else ''
                lines.append(f'{ticker}')
                lines.append(f'  Shares: {shares:g} | Avg Price: ${avg_price:.2f} | Cost Basis: ${cost:,.2f}')
                lines.append(f'  Current Price: ${price:.2f} | Day Change: {sign}{change:.2f}%')
                lines.append(f'  Market Value: ${mv:,.2f} | Weight: {weight:.1f}%')
                lines.append(f'  P&L: {gain_sign}${gain:,.2f} | Growth: {growth_sign}{growth:.1f}%')
                lines.append(f'  Market Cap: {mc_str}')
                lines.append('')
            lines.append(f'Total Portfolio Value: ${total_mv:,.2f}')
            lines.append('')
        lines.append('--- OPTIONS POSITIONS ---')
        lines.append('')
        if not options_data:
            lines.append('(no options positions)')
            lines.append('')
        else:
            for pos in options_data:
                ticker = pos.get('ticker', '?')
                strategy = pos.get('strategy', 'Calls')
                expiry = pos.get('expiry', 'N/A')
                strike = pos.get('strike', 0)
                contracts = pos.get('contracts', 1)
                premium = pos.get('premium', 0)
                current = pos.get('current_price', 0)
                iv = pos.get('iv', 0)
                delta = pos.get('delta', 0)
                theta = pos.get('theta', 0)
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                if is_seller:
                    pl = (premium - current) * contracts * 100
                else:
                    pl = (current - premium) * contracts * 100
                pl_sign = '+' if pl >= 0 else ''
                lines.append(f'{ticker} | {strategy} | Strike: ${strike:.2f} | Expiry: {expiry}')
                lines.append(f'  Contracts: {contracts} | Premium: ${premium:.2f} | Current: ${current:.2f}')
                lines.append(f'  IV: {iv:.1f}% | Delta: {delta:.3f} | Theta: {theta:.3f}')
                lines.append(f'  P&L: {pl_sign}${pl:,.2f}')
                lines.append('')
        text = '\n'.join(lines)
        total_items = len(tickers) + len(options_data)
        QApplication.clipboard().setText(text)
        self.set_status_text(self.status_bar, f'Exported {portfolio_name} ({total_items} positions) to clipboard', status='positive')

    def _get_return_timeframe_config(self, timeframe_key: Any) -> Any:
        """Return fetch/render config for the requested timeframe."""
        current_year = datetime.date.today().year
        configs = {
            'dip_finder': {'period': '1mo', 'interval': '1d', 'sort_reverse': True},
            '1mo': {'period': '1mo', 'interval': '1d', 'sort_reverse': True},
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
        if col == P4_PORTFOLIO_COL_SHARES:
            self._p4_invalidate_momentum_cache()
            self._p4_refresh_active_momentum_view()

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

    def _p4_on_tracker_delete_clicked(self) -> None:
        """Remove the ticker assigned to a reused page-4 action button."""
        sender = self.sender()
        if not isinstance(sender, QPushButton):
            return
        ticker = str(sender.property('portfolio_ticker') or '').strip().upper()
        if not ticker:
            return
        if bool(sender.property('remove_from_main_portfolio')):
            self.remove_ticker(ticker)
        else:
            self._p4_remove_active_ticker(ticker)

    def _p4_ensure_tracker_item(self, row: Any, col: Any, flags: Any) -> Any:
        """Return an existing tracker cell item or create it once."""
        item = self.p4_table.item(row, col)
        if item is None:
            item = QTableWidgetItem('')
            self.p4_table.setItem(row, col, item)
        item.setFlags(flags)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _p4_clear_mktcap_item(self, row: Any) -> None:
        """Clear stale market-cap text when a reused row has no cached value yet."""
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        item = self._p4_ensure_tracker_item(row, P4_PORTFOLIO_COL_MARKET_CAP, ro_flags)
        item.setText('')
        item.setForeground(self.theme_qcolor('text_muted'))

    def _p4_ensure_tracker_delete_button(self, row: Any) -> Any:
        """Return an existing per-row action button or create it once."""
        widget = self.p4_table.cellWidget(row, P4_PORTFOLIO_COL_ACTION)
        if isinstance(widget, QPushButton):
            return widget
        del_btn = QPushButton('X')
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_btn.clicked.connect(self._p4_on_tracker_delete_clicked)
        self.p4_table.setCellWidget(row, P4_PORTFOLIO_COL_ACTION, del_btn)
        return del_btn

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
        default_text_color = self.theme_qcolor('text_primary')
        gain_color = self.theme_qcolor('accent_positive' if dollar_gain >= 0 else 'accent_negative')
        change_color = self.theme_qcolor('accent_positive' if change >= 0 else 'accent_negative')

        def _update_item(col: Any, text: Any, flags: Any = ro_flags, color: Any = None) -> None:
            item = self._p4_ensure_tracker_item(row, col, flags)
            item.setText(text)
            item.setForeground(color if color is not None else default_text_color)

        _update_item(P4_PORTFOLIO_COL_SYMBOL, ticker)
        _update_item(P4_PORTFOLIO_COL_SHARES, f'{shares:g}', ed_flags)
        _update_item(P4_PORTFOLIO_COL_AVG_PRICE, f'{avg_price:.2f}', ed_flags)
        _update_item(P4_PORTFOLIO_COL_COST, f'${cost:,.2f}')
        _update_item(P4_PORTFOLIO_COL_PRICE, f'${price:.2f}')
        sign = '+' if change >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_DAY_CHANGE, f'{sign}{change:.2f}%', color=change_color)
        _update_item(P4_PORTFOLIO_COL_MARKET_VALUE, f'${mkt_val:,.2f}')
        _update_item(P4_PORTFOLIO_COL_WEIGHT, f'{weight:.1f}%')
        gain_sign = '+' if dollar_gain >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_DOLLAR_GAIN, f'{gain_sign}${dollar_gain:,.2f}', color=gain_color)
        growth_sign = '+' if growth >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_GROWTH, f'{growth_sign}{growth:.1f}%', color=gain_color)
        del_btn = self._p4_ensure_tracker_delete_button(row)
        del_btn.setStyleSheet(
            f'background-color: {self.theme_color("accent_negative_bg")}; '
            f'color: {self.theme_color("text_primary")}; '
            f'border-radius: 11px; font-weight: bold; '
            f'border: 1px solid {self.theme_color("accent_negative")};'
        )
        del_btn.setProperty('portfolio_ticker', ticker)
        del_btn.setProperty('remove_from_main_portfolio', self.active_portfolio_id == self.main_portfolio_id)

    def _p4_remove_active_ticker(self, ticker: Any) -> None:
        """Remove a ticker from the currently selected page-4 portfolio."""
        tickers = self._p4_active_tickers()
        if ticker not in tickers:
            return
        tickers.remove(ticker)
        tracker_data = self._p4_active_tracker_data()
        tracker_data.pop(ticker, None)
        self._p4_invalidate_returns_cache()
        self._p4_invalidate_momentum_cache()
        self._persist_all_portfolios()
        if self.last_data and self.active_portfolio_id == self.main_portfolio_id and 'portfolio' in self.last_data:
            self.last_data['portfolio'].pop(ticker, None)
        if self.last_data:
            self.update_page4(self.last_data)
        else:
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)
            self._p4_refresh_active_momentum_view()

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

    def _p4_empty_momentum_payload(self, reason: str, *, included: Any=None, excluded: Any=None) -> dict[str, Any]:
        """Build a normalized empty momentum payload."""
        return {
            'dates': [],
            'returns': [],
            'start_value': None,
            'end_value': None,
            'included_tickers': list(included or []),
            'excluded_tickers': list(excluded or []),
            'start_date': None,
            'reason': str(reason or '').strip(),
        }

    def _p4_momentum_ema_period(self, timeframe_key: Any) -> int:
        """Return the EMA period used for one momentum timeframe."""
        return {
            '1mo': 10,
            'ytd': 20,
            '1y': 50,
        }.get(str(timeframe_key or '').strip().lower(), 20)

    def _p4_set_momentum_summary(self, timeframe_key: Any, payload: Any, *, ema_last: Any=None) -> None:
        """Update the momentum summary label for the active timeframe."""
        if not hasattr(self, 'p4_momentum_summary_label'):
            return
        if not isinstance(payload, dict):
            payload = self._p4_empty_momentum_payload('No momentum data available')
        reason = str(payload.get('reason', '') or '').strip()
        returns = payload.get('returns', [])
        included = list(payload.get('included_tickers', []) or [])
        excluded = list(payload.get('excluded_tickers', []) or [])
        if reason or not returns:
            self.p4_momentum_summary_label.setText(reason or 'No momentum data available')
            return
        total_return = float(returns[-1]) if returns else 0.0
        sign = '+' if total_return >= 0 else ''
        start_date = str(payload.get('start_date') or '--')
        parts = [
            f'Since {start_date}',
            f'Portfolio {sign}{total_return:.1f}%',
            f'{len(included)} holding{"s" if len(included) != 1 else ""}',
        ]
        if ema_last is not None:
            relation = 'Above' if total_return >= float(ema_last) else 'Below'
            parts.append(f'{relation} {self._p4_momentum_ema_period(timeframe_key)}-day EMA')
        if excluded:
            parts.append(f'{len(excluded)} excluded')
        self.p4_momentum_summary_label.setText(' | '.join(parts))

    def _update_momentum_chart(self, timeframe_key: Any, payload: Any) -> None:
        """Render one timeframe of portfolio momentum."""
        pw = getattr(self, 'p4_momentum_charts', {}).get(timeframe_key)
        axis = getattr(self, 'p4_momentum_axes', {}).get(timeframe_key)
        if pw is None:
            return
        pw.clear()
        if axis is not None:
            axis.set_dates([], '1d')
        if not isinstance(payload, dict):
            payload = self._p4_empty_momentum_payload('No momentum data available')
        dates = list(payload.get('dates', []) or [])
        returns = [float(value) for value in list(payload.get('returns', []) or [])]
        if len(dates) != len(returns) or len(returns) < 2:
            self._p4_set_momentum_summary(timeframe_key, payload)
            return
        xs = list(range(len(dates)))
        if axis is not None:
            axis.set_dates(dates, '1d')
        returns_series = pd.Series(returns, dtype='float64')
        ema_period = self._p4_momentum_ema_period(timeframe_key)
        ema_values = returns_series.ewm(span=ema_period, adjust=False).mean().tolist()
        line_color = self.theme_color('accent')
        pw.plot(xs, returns, pen=pg.mkPen(line_color, width=2), antialias=True)
        pw.plot(
            xs,
            ema_values,
            pen=pg.mkPen(self.theme_color('warning'), width=2, style=Qt.PenStyle.DashLine),
            antialias=True,
        )
        pw.addItem(
            pg.InfiniteLine(
                pos=0,
                angle=0,
                pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine),
            )
        )
        last_value = float(returns[-1])
        last_color = self.theme_color('accent_positive' if last_value >= 0 else 'accent_negative')
        last_sign = '+' if last_value >= 0 else ''
        anchor = (1.0, 0.0 if last_value >= 0 else 1.0)
        last_label = pg.TextItem(text=f'{last_sign}{last_value:.1f}%', color=last_color, anchor=anchor)
        last_label.setPos(xs[-1], last_value)
        pw.addItem(last_label)
        plot_item = pw.getPlotItem()
        plot_item.hideAxis('left')
        plot_item.showAxis('right')
        plot_item.showAxis('bottom')
        try:
            plot_item.getAxis('right').setLabel('Return %')
        except Exception:
            pass
        min_value = min(min(returns), min(ema_values), 0.0)
        max_value = max(max(returns), max(ema_values), 0.0)
        y_pad = max((max_value - min_value) * 0.15, 1.0)
        pw.setYRange(min_value - y_pad, max_value + y_pad)
        pw.setXRange(-0.4, len(xs) - 0.6)
        self._p4_set_momentum_summary(timeframe_key, payload, ema_last=ema_values[-1] if ema_values else None)

    def _p4_active_momentum_shares_map(self) -> dict[str, float]:
        """Return normalized current-share counts for the active portfolio."""
        shares_map = {}
        for ticker, tracker_entry in (self._p4_active_tracker_data() or {}).items():
            symbol = str(ticker or '').strip().upper()
            if not symbol:
                continue
            try:
                shares_map[symbol] = float((tracker_entry or {}).get('shares', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                shares_map[symbol] = 0.0
        return shares_map

    def _fetch_momentum_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch portfolio momentum for a specific timeframe."""
        portfolio_id = str(self.active_portfolio_id)
        cache_key = self._p4_momentum_cache_key(timeframe_key, portfolio_id)
        if self._momentum_metrics_fetching.get(cache_key, False):
            return
        tickers = list(self._p4_active_tickers())
        shares_map = self._p4_active_momentum_shares_map()
        if not tickers:
            payload = self._p4_empty_momentum_payload('No portfolio holdings available')
            self._momentum_metrics_cache[cache_key] = payload
            self._momentum_metrics_fetching[cache_key] = False
            if portfolio_id == str(self.active_portfolio_id) and timeframe_key == self._active_momentum_timeframe:
                self._update_momentum_chart(timeframe_key, payload)
            return
        config = self._get_return_timeframe_config(timeframe_key)
        self._momentum_metrics_fetching[cache_key] = True
        worker = PortfolioMomentumWorker(
            tickers,
            shares_map,
            period=config.get('period', '1mo'),
            interval=config.get('interval', '1d'),
            start=config.get('start'),
        )
        worker.finished.connect(
            lambda payload, key=timeframe_key, pid=portfolio_id: self._on_momentum_ready(key, pid, payload)
        )
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_momentum_ready(self, timeframe_key: Any, portfolio_id: Any, payload: Any) -> None:
        """Handle portfolio momentum data becoming ready."""
        cache_key = self._p4_momentum_cache_key(timeframe_key, portfolio_id)
        self._momentum_metrics_fetching[cache_key] = False
        self._momentum_metrics_cache[cache_key] = payload
        if str(portfolio_id) == str(self.active_portfolio_id) and timeframe_key == self._active_momentum_timeframe:
            self._update_momentum_chart(timeframe_key, payload)

    def _on_momentum_timeframe_changed(self, index: int) -> None:
        """Handle momentum timeframe tab changes."""
        if index < 0 or index >= len(getattr(self, 'p4_momentum_timeframes', ())):
            return
        timeframe_key = self.p4_momentum_timeframes[index][0]
        self._active_momentum_timeframe = timeframe_key
        cache_key = self._p4_momentum_cache_key(timeframe_key)
        if cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(timeframe_key, self._momentum_metrics_cache.get(cache_key, {}))
            return
        self._fetch_momentum_for_timeframe(timeframe_key)

    def _p4_refresh_active_momentum_view(self) -> None:
        """Refresh the visible momentum chart from cache or fetch it."""
        timeframe_key = str(getattr(self, '_active_momentum_timeframe', '1mo') or '1mo')
        cache_key = self._p4_momentum_cache_key(timeframe_key)
        if cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(timeframe_key, self._momentum_metrics_cache.get(cache_key, {}))
            return
        self._fetch_momentum_for_timeframe(timeframe_key)

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

    def _p4_mktcap_cache_ttl_seconds(self) -> float:
        """Return the reuse window for cached market-cap values."""
        return float(getattr(self, '_mktcap_cache_ttl_seconds', _P4_MKTCAP_CACHE_TTL_SECONDS))

    def _p4_mktcap_cache_now(self) -> float:
        """Return the current UTC timestamp for market-cap freshness checks."""
        return datetime.datetime.now(datetime.timezone.utc).timestamp()

    def _p4_has_fresh_mktcap(self, ticker: Any) -> bool:
        """Return whether one cached market-cap entry is still fresh."""
        symbol = str(ticker or '').strip().upper()
        if not symbol:
            return False
        cache_ts = getattr(self, '_mktcap_cache_ts', {})
        fetched_at = cache_ts.get(symbol)
        if fetched_at is None:
            return False
        return (self._p4_mktcap_cache_now() - float(fetched_at)) < self._p4_mktcap_cache_ttl_seconds()

    def _p4_get_mktcap_refresh_candidates(self, tickers: Any = None) -> list[str]:
        """Return missing or stale tickers that still need a market-cap refresh."""
        candidates = []
        inflight = set(getattr(self, '_mktcap_inflight_tickers', set()))
        queued = set(getattr(self, '_mktcap_queued_tickers', set()))
        for ticker in tickers if tickers is not None else self._p4_active_tickers():
            symbol = str(ticker or '').strip().upper()
            if not symbol or symbol in inflight or symbol in queued:
                continue
            if (symbol not in self._mktcap_cache) or (not self._p4_has_fresh_mktcap(symbol)):
                candidates.append(symbol)
        return candidates

    def _p4_start_market_cap_fetch(self, tickers: Any) -> bool:
        """Launch one page-4 market-cap worker for the provided tickers."""
        symbols = [str(ticker or '').strip().upper() for ticker in tickers]
        symbols = [symbol for symbol in symbols if symbol]
        if not symbols:
            return False
        worker = MarketCapWorker(symbols)
        self._mktcap_fetching = True
        self._mktcap_inflight_tickers = set(symbols)
        worker.finished.connect(self._on_market_caps_ready)
        threading.Thread(target=worker.run, daemon=True).start()
        return True

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

    def _fetch_market_caps(self, tickers: Any = None) -> None:
        """Fetch market caps."""
        needed = self._p4_get_mktcap_refresh_candidates(tickers)
        if not needed:
            return
        if getattr(self, '_mktcap_fetching', False):
            queued = set(getattr(self, '_mktcap_queued_tickers', set()))
            queued.update(needed)
            self._mktcap_queued_tickers = queued
            return
        self._p4_start_market_cap_fetch(needed)

    def _on_market_caps_ready(self, results: Any) -> None:
        """Handle market caps ready."""
        self._mktcap_fetching = False
        request_tickers = set(getattr(self, '_mktcap_inflight_tickers', set()))
        self._mktcap_inflight_tickers = set()
        if isinstance(results, dict) and results:
            fetched_at = self._p4_mktcap_cache_now()
            for ticker, mc in results.items():
                symbol = str(ticker or '').strip().upper()
                if not symbol:
                    continue
                self._mktcap_cache[symbol] = mc
                self._mktcap_cache_ts[symbol] = fetched_at
        for row in range(self.p4_table.rowCount()):
            item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
            if item and item.text() in results:
                self._update_mktcap_item(row, item.text(), results[item.text()])
        queued = list(getattr(self, '_mktcap_queued_tickers', set()))
        self._mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if ticker not in request_tickers]
            self._fetch_market_caps(remaining)

    def update_page4(self, data: Any) -> None:
        """Update page4."""
        portfolio = data.get('portfolio', {})
        tickers = self._p4_active_tickers()
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        weights = {}
        self.p4_table.blockSignals(True)
        self.p4_table.setUpdatesEnabled(False)
        try:
            self.p4_table.setRowCount(len(tickers))
            sorted_tickers = sorted(
                tickers,
                key=lambda ticker: metrics_map.get(ticker, {}).get('market_value', 0),
                reverse=True,
            )
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
                else:
                    self._p4_clear_mktcap_item(i)
        finally:
            self.p4_table.setUpdatesEnabled(True)
            self.p4_table.blockSignals(False)
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('stock')
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
        active_momentum_cache_key = self._p4_momentum_cache_key(self._active_momentum_timeframe)
        if not tickers:
            payload = self._p4_empty_momentum_payload('No portfolio holdings available')
            self._momentum_metrics_cache[active_momentum_cache_key] = payload
            self._momentum_metrics_fetching[active_momentum_cache_key] = False
            self._update_momentum_chart(self._active_momentum_timeframe, payload)
        elif active_momentum_cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(
                self._active_momentum_timeframe,
                self._momentum_metrics_cache.get(active_momentum_cache_key, {}),
            )
        else:
            self._fetch_momentum_for_timeframe(self._active_momentum_timeframe)
        self._fetch_market_caps(sorted_tickers)
