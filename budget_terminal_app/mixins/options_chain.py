from __future__ import annotations
from typing import Any
from ..compat import *


class OptionsChainMixin:
    _P5_CHAIN_COLUMNS = [
        ('Strike', 'strike', '{:.1f}'),
        ('Last', 'lastPrice', '{:.2f}'),
        ('Bid', 'bid', '{:.2f}'),
        ('Ask', 'ask', '{:.2f}'),
        ('Chg', 'change', '{:+.2f}'),
        ('Vol', 'volume', '{:,.0f}'),
        ('OI', 'openInterest', '{:,.0f}'),
        ('IV', 'iv_percent', '{:.1f}%'),
        ('Delta', 'delta_calc', '{:.3f}'),
        ('Gamma', 'gamma_calc', '{:.3f}'),
        ('Theta', 'theta_calc', '{:.3f}'),
        ('Vega', 'vega_calc', '{:.3f}'),
        ('Rho', 'rho_calc', '{:.3f}'),
    ]
    _P5_STRATEGIES = ('None', 'Covered Call', 'Cash Secured Put')
    def init_page5(self) -> None:
        """Build the Options Chain page UI."""
        layout = QVBoxLayout(self.page5)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        controls = QHBoxLayout()
        self.p5_ticker_input = QLineEdit()
        self.p5_ticker_input.setPlaceholderText('Enter Ticker (e.g. AAPL)')
        self.p5_ticker_input.setMinimumWidth(100)
        self.p5_ticker_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_ticker_input.returnPressed.connect(self._p5_load_expiries)
        load_btn = QPushButton('Load Chain')
        load_btn.clicked.connect(self._p5_load_expiries)
        self.p5_expiry_combo = QComboBox()
        self.p5_expiry_combo.setMinimumWidth(140)
        self.p5_expiry_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_expiry_combo.currentIndexChanged.connect(self._p5_load_chain)
        self.p5_strategy_combo = QComboBox()
        self.p5_strategy_combo.setMinimumWidth(120)
        self.p5_strategy_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_strategy_combo.addItems(list(self._P5_STRATEGIES))
        self.p5_strategy_combo.currentIndexChanged.connect(self._p5_refresh_strategy_view)
        self.p5_status_lbl = QLabel('Enter a ticker to view the full options chain.')
        self.set_theme_role(self.p5_status_lbl, 'status_muted')
        self.p5_price_lbl = QLabel('')
        self.p5_price_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {self.theme_color('accent_positive')}; margin-left: 10px;")
        self._p5_chain_df = pd.DataFrame()
        self._p5_chain_spot_price = 0.0
        self._p5_chain_expiry = ''
        self._p5_chain_rate = 0.0
        self._p5_chain_dividend_yield = 0.0
        self._p5_chain_rate_source = 'default'
        self._p5_chain_dividend_source = 'default'
        controls.addWidget(QLabel('<b>Ticker:</b>'))
        controls.addWidget(self.p5_ticker_input)
        controls.addWidget(load_btn)
        controls.addSpacing(10)
        controls.addWidget(self.p5_price_lbl)
        controls.addSpacing(20)
        controls.addWidget(QLabel('<b>Expiry:</b>'))
        controls.addWidget(self.p5_expiry_combo)
        controls.addSpacing(14)
        controls.addWidget(QLabel('<b>Strategy:</b>'))
        controls.addWidget(self.p5_strategy_combo)
        controls.addSpacing(20)
        controls.addWidget(self.p5_status_lbl)
        controls.addStretch()
        layout.addLayout(controls, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        calls_widget = QWidget()
        calls_layout = QVBoxLayout(calls_widget)
        calls_layout.setContentsMargins(0, 0, 0, 0)
        calls_layout.addWidget(QLabel('<b>CALLS</b>'))
        self.p5_calls_table = self._make_chain_table()
        calls_layout.addWidget(self.p5_calls_table)
        puts_widget = QWidget()
        puts_layout = QVBoxLayout(puts_widget)
        puts_layout.setContentsMargins(0, 0, 0, 0)
        puts_layout.addWidget(QLabel('<b>PUTS</b>'))
        self.p5_puts_table = self._make_chain_table()
        puts_layout.addWidget(self.p5_puts_table)
        splitter.addWidget(calls_widget)
        splitter.addWidget(puts_widget)
        layout.addWidget(splitter, 1)

    def _make_chain_table(self) -> Any:
        """Create a shared options chain table."""
        t = QTableWidget(0, len(self._P5_CHAIN_COLUMNS))
        t.setHorizontalHeaderLabels([label for label, _, _ in self._P5_CHAIN_COLUMNS])
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        return t

    def _p5_load_expiries(self) -> None:
        """Fetch available expiry dates for the entered ticker."""
        ticker = self.p5_ticker_input.text().upper().strip()
        if not ticker:
            return
        self.set_status_text(self.p5_status_lbl, f'Fetching expiries for {ticker}...', status='warning')
        self.p5_expiry_combo.blockSignals(True)
        self.p5_expiry_combo.clear()
        self.p5_expiry_combo.blockSignals(False)

        def _run() -> None:
            """Fetch expiries and current spot."""
            try:
                cache = CacheManager()
                price = None
                try:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        price = float(t_obj.fast_info['lastPrice'])
                except Exception as pe:
                    logger.warning(f'Failed to fetch price for {ticker}: {pe}')
                exps = cache.get_options_expiries(ticker)
                if exps is None:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        exps = t_obj.options
                    if exps:
                        cache.save_options_expiries(ticker, exps)

                def _update_ui() -> None:
                    """Populate expiry combo and spot label."""
                    self._p5_chain_spot_price = price or 0.0
                    self._p5_populate_expiries(exps)
                    if price:
                        self.p5_price_lbl.setText(f'${price:.2f}')
                    else:
                        self.p5_price_lbl.setText('')
                self._invoke_main.emit(_update_ui)
            except Exception as e:
                logger.error(f'P5 expiry fetch failed for {ticker}: {e}')
                self._invoke_main.emit(lambda: self.set_status_text(self.p5_status_lbl, f'Error: {e}', status='negative'))
        threading.Thread(target=_run, daemon=True).start()

    def _p5_populate_expiries(self, exps: Any) -> None:
        """Populate the expiry selector."""
        if not exps:
            self.set_status_text(self.p5_status_lbl, 'No options found.', status='muted')
            return
        self.p5_expiry_combo.blockSignals(True)
        self.p5_expiry_combo.clear()
        today = datetime.date.today()
        for exp in exps:
            try:
                ed = datetime.datetime.strptime(exp, '%Y-%m-%d').date()
                dte = (ed - today).days
                self.p5_expiry_combo.addItem(f'{exp} ({dte}d)', exp)
            except Exception:
                self.p5_expiry_combo.addItem(exp, exp)
        self.p5_expiry_combo.blockSignals(False)
        self.set_status_text(self.p5_status_lbl, 'Expiries loaded.', status='positive')
        self._p5_load_chain()

    def _p5_load_chain(self) -> None:
        """Load and render the selected options chain."""
        ticker = self.p5_ticker_input.text().upper().strip()
        expiry = self.p5_expiry_combo.currentData()
        if not ticker or not expiry:
            return
        self.set_status_text(self.p5_status_lbl, f'Loading {ticker} {expiry} chain...', status='warning')
        spot_price = float(getattr(self, '_p5_chain_spot_price', 0.0) or 0.0)

        def _run() -> None:
            """Load raw chain, enrich it, and update the UI."""
            try:
                cache = CacheManager()
                current_spot = spot_price
                if current_spot <= 0:
                    try:
                        with YF_LOCK:
                            current_spot = float(yf.Ticker(ticker).fast_info['lastPrice'])
                    except Exception as pe:
                        logger.warning(f'Failed to refresh spot price for {ticker}: {pe}')
                df = cache.get_options_chain(ticker, expiry)
                if df is None:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        chain = t_obj.option_chain(expiry)
                    if chain.calls.empty and chain.puts.empty:
                        raise ValueError('Received empty options chain from API')
                    c = chain.calls.copy()
                    p = chain.puts.copy()
                    c['type'] = 'Call'
                    p['type'] = 'Put'
                    df = pd.concat([c, p], ignore_index=True)
                    cache.save_options_chain(ticker, expiry, df)
                greek_inputs = self._p5_resolve_greek_inputs(ticker, current_spot)
                current_spot = float(greek_inputs.get('spot_price', current_spot) or current_spot or 0.0)
                enriched = self._p5_enrich_chain(
                    df,
                    expiry,
                    current_spot,
                    float(greek_inputs.get('risk_free_rate', 0.0) or 0.0),
                    float(greek_inputs.get('dividend_yield', 0.0) or 0.0),
                )
                self._invoke_main.emit(lambda: self._p5_update_chain_view(enriched, expiry, current_spot, greek_inputs))
            except Exception as e:
                logger.error(f'P5 chain load failed for {ticker} {expiry}: {e}')
                self._invoke_main.emit(lambda: self.set_status_text(self.p5_status_lbl, f'Error: {e}', status='negative'))
        threading.Thread(target=_run, daemon=True).start()

    def _p5_enrich_chain(self, df: Any, expiry: str, spot_price: float, risk_free_rate: float, dividend_yield: float) -> Any:
        """Add UI-ready market and Greek columns to the raw chain data."""
        if df is None:
            return pd.DataFrame()
        enriched = df.copy()
        if 'type' not in enriched.columns:
            enriched['type'] = ''
        enriched['type'] = enriched['type'].fillna('')
        enriched['iv_percent'] = pd.to_numeric(enriched.get('impliedVolatility', 0), errors='coerce').fillna(0.0) * 100.0
        market_cols = ['strike', 'lastPrice', 'bid', 'ask', 'change', 'volume', 'openInterest', 'impliedVolatility']
        for col in market_cols:
            if col not in enriched.columns:
                enriched[col] = 0.0
            enriched[col] = pd.to_numeric(enriched[col], errors='coerce')
        # Fill missing IVs from option prices (e.g. when market is closed and yfinance returns 0)
        iv_col = enriched['impliedVolatility']
        needs_iv = iv_col.isna() | (iv_col <= 0)
        if needs_iv.any() and spot_price > 0:
            for idx in enriched.index[needs_iv]:
                row = enriched.loc[idx]
                bid = float(row.get('bid', 0) or 0)
                ask = float(row.get('ask', 0) or 0)
                last = float(row.get('lastPrice', 0) or 0)
                price = ((bid + ask) / 2) if (bid > 0 and ask > 0) else last
                computed_iv = self._p5_implied_vol(
                    spot_price,
                    float(row.get('strike', 0) or 0),
                    expiry,
                    risk_free_rate,
                    dividend_yield,
                    price,
                    str(row.get('type', '')).strip().lower(),
                )
                if computed_iv > 0:
                    enriched.at[idx, 'impliedVolatility'] = computed_iv
            enriched['iv_percent'] = pd.to_numeric(enriched['impliedVolatility'], errors='coerce').fillna(0.0) * 100.0
        greeks = enriched.apply(
            lambda row: pd.Series(
                self._p5_calc_greeks(
                    spot_price,
                    float(row.get('strike', 0.0) or 0.0),
                    expiry,
                    float(row.get('impliedVolatility', 0.0) or 0.0),
                    str(row.get('type', '')).strip().lower(),
                    risk_free_rate,
                    dividend_yield,
                )
            ),
            axis=1,
        )
        for col in ('delta_calc', 'gamma_calc', 'theta_calc', 'vega_calc', 'rho_calc', 'greeks_valid'):
            enriched[col] = greeks[col] if col in greeks else None
        return enriched

    def _p5_update_chain_view(self, df: Any, expiry: str, spot_price: float, greek_inputs: dict[str, Any]) -> None:
        """Store the latest spot value and redraw the chain tables."""
        self._p5_chain_spot_price = spot_price or 0.0
        self._p5_chain_rate = float(greek_inputs.get('risk_free_rate', 0.0) or 0.0)
        self._p5_chain_dividend_yield = float(greek_inputs.get('dividend_yield', 0.0) or 0.0)
        self._p5_chain_rate_source = str(greek_inputs.get('rate_source', 'default') or 'default')
        self._p5_chain_dividend_source = str(greek_inputs.get('dividend_source', 'default') or 'default')
        if spot_price:
            self.p5_price_lbl.setText(f'${spot_price:.2f}')
        self._p5_populate_tables(df, expiry)

    def _p5_implied_vol(self, spot: float, strike: float, expiry: str, risk_free_rate: float, dividend_yield: float, market_price: float, option_type: str) -> float:
        """Newton-Raphson solver to back out implied volatility from an option price."""
        if market_price <= 0 or spot <= 0 or strike <= 0 or option_type not in ('call', 'put'):
            return 0.0
        try:
            exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        except ValueError:
            return 0.0
        dte_days = max((exp_date - datetime.date.today()).days, 0)
        t = max(dte_days / 365.0, 1.0 / 365.0)
        rate = min(max(float(risk_free_rate), 0.0), 1.0)
        dividend = min(max(float(dividend_yield), 0.0), 1.0)
        normal = NormalDist()
        exp_neg_qt = math.exp(-dividend * t)
        exp_neg_rt = math.exp(-rate * t)
        sqrt_t = math.sqrt(t)
        sigma = 0.3
        for _ in range(30):
            denom = sigma * sqrt_t
            if denom <= 0:
                return 0.0
            d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * t) / denom
            d2 = d1 - denom
            pdf_d1 = normal.pdf(d1)
            if option_type == 'call':
                bs_price = spot * exp_neg_qt * normal.cdf(d1) - strike * exp_neg_rt * normal.cdf(d2)
            else:
                bs_price = strike * exp_neg_rt * normal.cdf(-d2) - spot * exp_neg_qt * normal.cdf(-d1)
            vega = spot * exp_neg_qt * pdf_d1 * sqrt_t
            if vega < 1e-12:
                break
            sigma -= (bs_price - market_price) / vega
            sigma = max(0.001, min(sigma, 10.0))
            if abs(bs_price - market_price) < 0.001:
                return sigma
        return 0.0

    def _p5_calc_greeks(self, spot: float, strike: float, expiry: str, iv: float, option_type: str, risk_free_rate: float, dividend_yield: float) -> dict[str, Any]:
        """Compute Black-Scholes Greeks for one option row."""
        if spot <= 0 or strike <= 0 or iv <= 0 or option_type not in ('call', 'put'):
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        try:
            exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        except ValueError:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        dte_days = max((exp_date - datetime.date.today()).days, 0)
        t = max(dte_days / 365.0, 1.0 / 365.0)
        sigma = float(iv)
        if sigma <= 0:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        sqrt_t = math.sqrt(t)
        denom = sigma * sqrt_t
        if denom <= 0:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        normal = NormalDist()
        rate = min(max(float(risk_free_rate), 0.0), 1.0)
        dividend = min(max(float(dividend_yield), 0.0), 1.0)
        exp_neg_qt = math.exp(-dividend * t)
        exp_neg_rt = math.exp(-rate * t)
        d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * t) / denom
        d2 = d1 - denom
        pdf_d1 = normal.pdf(d1)
        if option_type == 'call':
            delta = exp_neg_qt * normal.cdf(d1)
            theta_year = (-(spot * exp_neg_qt * pdf_d1 * sigma) / (2 * sqrt_t)) - (rate * strike * exp_neg_rt * normal.cdf(d2)) + (dividend * spot * exp_neg_qt * normal.cdf(d1))
            rho = (strike * t * exp_neg_rt * normal.cdf(d2)) / 100.0
        else:
            delta = exp_neg_qt * (normal.cdf(d1) - 1.0)
            theta_year = (-(spot * exp_neg_qt * pdf_d1 * sigma) / (2 * sqrt_t)) + (rate * strike * exp_neg_rt * normal.cdf(-d2)) - (dividend * spot * exp_neg_qt * normal.cdf(-d1))
            rho = (-strike * t * exp_neg_rt * normal.cdf(-d2)) / 100.0
        gamma = (exp_neg_qt * pdf_d1) / (spot * denom)
        vega = (spot * exp_neg_qt * pdf_d1 * sqrt_t) / 100.0
        theta = theta_year / 365.0
        return {
            'delta_calc': delta,
            'gamma_calc': gamma,
            'theta_calc': theta,
            'vega_calc': vega,
            'rho_calc': rho,
            'greeks_valid': True,
        }

    def _p5_resolve_greek_inputs(self, ticker: str, spot_price: float) -> dict[str, Any]:
        """Resolve market inputs used by the options-chain Greek calculations."""
        settings = load_options_chain_settings()
        fallback_rate = float(settings.get('default_risk_free_rate', 0.04) or 0.04)
        resolved_spot = float(spot_price or 0.0)
        rate = fallback_rate
        rate_source = 'config'
        dividend_yield = 0.0
        dividend_source = 'default'
        info: dict[str, Any] = {}
        try:
            with YF_LOCK:
                ticker_obj = yf.Ticker(ticker)
                if resolved_spot <= 0:
                    try:
                        resolved_spot = float(ticker_obj.fast_info['lastPrice'])
                    except Exception:
                        resolved_spot = float(resolved_spot or 0.0)
                try:
                    info = ticker_obj.info or {}
                except Exception:
                    info = {}
            market_rate = self._p5_fetch_market_rate()
            if market_rate is not None:
                rate = market_rate
                rate_source = 'market'
                save_options_chain_settings({'default_risk_free_rate': market_rate})
        except Exception as exc:
            logger.warning(f'Failed to resolve market inputs for {ticker}: {exc}')
        extracted_dividend = self._p5_extract_dividend_yield(info)
        if extracted_dividend is not None:
            dividend_yield = extracted_dividend
            dividend_source = 'ticker'
        return {
            'spot_price': resolved_spot,
            'risk_free_rate': rate,
            'rate_source': rate_source,
            'dividend_yield': dividend_yield,
            'dividend_source': dividend_source,
        }

    def _p5_fetch_market_rate(self) -> float | None:
        """Use the 13-week Treasury yield index as a simple risk-free proxy."""
        try:
            with YF_LOCK:
                rate_ticker = yf.Ticker('^IRX')
                fast_info = getattr(rate_ticker, 'fast_info', {}) or {}
                raw_value = fast_info.get('lastPrice')
                if raw_value in (None, 0):
                    info = rate_ticker.info or {}
                    raw_value = info.get('regularMarketPrice') or info.get('previousClose') or info.get('currentPrice')
        except Exception as exc:
            logger.warning(f'Failed to fetch ^IRX risk-free proxy: {exc}')
            return None
        try:
            rate_value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if rate_value <= 0:
            return None
        if rate_value > 1.0:
            rate_value /= 100.0
        return min(max(rate_value, 0.0), 1.0)

    def _p5_extract_dividend_yield(self, info: Any) -> float | None:
        """Extract dividend yield from the ticker quote payload when present."""
        if not isinstance(info, dict):
            return None
        for key in ('dividendYield', 'trailingAnnualDividendYield'):
            raw_value = info.get(key)
            try:
                yield_value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if yield_value < 0:
                continue
            if yield_value > 1.0:
                yield_value /= 100.0
            return min(max(yield_value, 0.0), 1.0)
        return None

    def _p5_refresh_strategy_view(self) -> None:
        """Reapply recommendation styling for the current strategy."""
        if not getattr(self, '_p5_chain_df', pd.DataFrame()).empty:
            self._p5_populate_tables(self._p5_chain_df, self._p5_chain_expiry)

    def _p5_populate_tables(self, df: Any, expiry: str) -> Any:
        """Render calls and puts tables, including strategy highlights."""
        self._p5_chain_df = df.copy() if df is not None else pd.DataFrame()
        self._p5_chain_expiry = expiry
        self.p5_calls_table.setRowCount(0)
        self.p5_puts_table.setRowCount(0)
        if df is None or df.empty:
            self.set_status_text(self.p5_status_lbl, 'No chain data available.', status='muted')
            return
        calls = df[df['type'] == 'Call'].sort_values('strike').reset_index(drop=True)
        puts = df[df['type'] == 'Put'].sort_values('strike').reset_index(drop=True)
        strategy = self.p5_strategy_combo.currentText()
        call_ranks = self._p5_rank_strategy_rows(calls, strategy)
        put_ranks = self._p5_rank_strategy_rows(puts, strategy)
        self._p5_fill_chain_table(self.p5_calls_table, calls, call_ranks)
        self._p5_fill_chain_table(self.p5_puts_table, puts, put_ranks)
        status_text = f"Chain updated at {datetime.datetime.now().strftime('%H:%M:%S')}"
        status_text += f" | r {self._p5_chain_rate * 100:.2f}% ({self._p5_chain_rate_source}) | q {self._p5_chain_dividend_yield * 100:.2f}% ({self._p5_chain_dividend_source})"
        strategy_count = len(call_ranks if strategy == 'Covered Call' else put_ranks if strategy == 'Cash Secured Put' else {})
        if strategy != 'None' and strategy_count:
            side = 'call' if strategy == 'Covered Call' else 'put'
            status_text += f' | {strategy}: highlighted top {strategy_count} {side} candidates'
        self.set_status_text(self.p5_status_lbl, status_text, status='positive')

    def _p5_fill_chain_table(self, table: Any, data: Any, ranks: dict[int, int]) -> None:
        """Populate a single chain table with optional recommendation styling."""
        table.setRowCount(len(data))
        for i, (_, row) in enumerate(data.iterrows()):
            rank = ranks.get(i)
            for col_idx, (label, key, fmt) in enumerate(self._P5_CHAIN_COLUMNS):
                color = None
                bg_color = self._p5_strategy_bg(rank)
                value = row.get(key)
                if label == 'Chg':
                    try:
                        color = self.theme_color('accent_positive' if float(row.get('change', 0) or 0) >= 0 else 'accent_negative')
                    except Exception:
                        color = None
                elif label == 'IV':
                    color = self.theme_color('text_muted')
                if label == 'Strike' and rank:
                    try:
                        strike_txt = fmt.format(float(row.get('strike', 0.0) or 0.0))
                    except Exception:
                        strike_txt = str(row.get('strike', ''))
                    display = f'{strike_txt}  #{rank}'
                else:
                    display = self._p5_format_chain_value(value, fmt)
                item = QTableWidgetItem(display)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if color:
                    item.setForeground(QColor(color))
                if bg_color:
                    item.setBackground(QColor(bg_color))
                table.setItem(i, col_idx, item)

    def _p5_strategy_bg(self, rank: int | None) -> str | None:
        """Resolve recommendation highlight backgrounds from theme tokens."""
        if not rank:
            return None
        return {
            1: self.theme_color('accent_positive_bg'),
            2: self.theme_color('info_bg'),
            3: self.theme_color('accent_soft'),
        }.get(rank, self.theme_color('background_secondary'))

    def _apply_options_chain_theme(self) -> None:
        """Refresh options-chain page styling after a theme change."""
        if hasattr(self, 'p5_price_lbl'):
            self.p5_price_lbl.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {self.theme_color('accent_positive')}; margin-left: 10px;"
            )
        if hasattr(self, 'p5_status_lbl'):
            self.set_status_text(self.p5_status_lbl, self.p5_status_lbl.text(), status=self.p5_status_lbl.property('bt_status') or 'muted')
        if not getattr(self, '_p5_chain_df', pd.DataFrame()).empty:
            self._p5_populate_tables(self._p5_chain_df, self._p5_chain_expiry)

    def _p5_format_chain_value(self, value: Any, fmt: str) -> str:
        """Format a chain cell value for display."""
        if value is None:
            return ''
        try:
            fval = float(value)
            if pd.isna(fval):
                return ''
            return fmt.format(fval)
        except Exception:
            txt = str(value)
            return '' if txt.lower() == 'nan' else txt

    def _p5_rank_strategy_rows(self, data: Any, strategy: str) -> dict[int, int]:
        """Score and rank the top strategy candidates for one table."""
        if data is None or data.empty or strategy == 'None':
            return {}
        if strategy == 'Covered Call' and str(data.iloc[0].get('type', '')).strip() != 'Call':
            return {}
        if strategy == 'Cash Secured Put' and str(data.iloc[0].get('type', '')).strip() != 'Put':
            return {}
        candidates: list[tuple[float, int]] = []
        spot = float(getattr(self, '_p5_chain_spot_price', 0.0) or 0.0)
        for idx, row in data.iterrows():
            score = self._p5_strategy_score(row, strategy, spot)
            if score is not None:
                candidates.append((score, idx))
        candidates.sort(key=lambda item: item[0], reverse=True)
        ranks: dict[int, int] = {}
        for rank, (_, idx) in enumerate(candidates[:3], start=1):
            ranks[int(idx)] = rank
        return ranks

    def _p5_strategy_score(self, row: Any, strategy: str, spot: float) -> float | None:
        """Return a recommendation score for one row or None if it is ineligible."""
        strike = float(row.get('strike', 0.0) or 0.0)
        bid = float(row.get('bid', 0.0) or 0.0)
        ask = float(row.get('ask', 0.0) or 0.0)
        last = float(row.get('lastPrice', 0.0) or 0.0)
        oi = float(row.get('openInterest', 0.0) or 0.0)
        vol = float(row.get('volume', 0.0) or 0.0)
        iv = float(row.get('impliedVolatility', 0.0) or 0.0)
        delta = row.get('delta_calc')
        gamma = row.get('gamma_calc')
        theta = row.get('theta_calc')
        vega = row.get('vega_calc')
        if not row.get('greeks_valid') or strike <= 0 or spot <= 0:
            return None
        if any(v is None or pd.isna(v) for v in (delta, gamma, theta, vega)):
            return None
        if bid <= 0 and ask <= 0 and last <= 0:
            return None
        premium = (bid + ask) / 2.0 if bid > 0 and ask > 0 else last
        if premium <= 0 or iv <= 0:
            return None
        width_penalty = 0.0
        if bid <= 0 or ask <= 0:
            width_penalty += 8.0
        elif premium > 0:
            width_penalty += min(20.0, ((ask - bid) / premium) * 100.0)
        liq_score = min(15.0, math.log1p(max(oi, 0.0)) * 2.2) + min(10.0, math.log1p(max(vol, 0.0)) * 2.0)
        gamma_penalty = min(8.0, abs(float(gamma)) * 200.0)
        vega_penalty = min(6.0, abs(float(vega)) * 10.0)
        if strategy == 'Covered Call':
            if strike < spot:
                return None
            delta_val = abs(float(delta))
            delta_target = 0.275
            delta_score = max(0.0, 45.0 - abs(delta_val - delta_target) * 130.0)
            yield_score = min(30.0, (premium / spot) * 1000.0)
            distance_penalty = min(18.0, max(0.0, (spot - strike) / max(spot, 1.0)) * 200.0)
            itm_penalty = 12.0 if strike <= spot else 0.0
            return delta_score + yield_score + liq_score - width_penalty - gamma_penalty - vega_penalty - distance_penalty - itm_penalty
        if strategy == 'Cash Secured Put':
            if strike > spot:
                return None
            delta_val = abs(float(delta))
            delta_target = 0.225
            delta_score = max(0.0, 45.0 - abs(delta_val - delta_target) * 140.0)
            yield_score = min(32.0, (premium / strike) * 1000.0)
            itm_penalty = 14.0 if strike >= spot else 0.0
            distance_penalty = min(12.0, max(0.0, (strike - spot) / max(spot, 1.0)) * 200.0)
            return delta_score + yield_score + liq_score - width_penalty - gamma_penalty - vega_penalty - distance_penalty - itm_penalty
        return None
