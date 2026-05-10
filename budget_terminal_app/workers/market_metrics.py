from __future__ import annotations
from typing import Any
from ..dependencies import QObject, ThreadPoolExecutor, YF_LOCK, is_yahoo_unauthorized_error, logger, math, pd, pyqtSignal, yf


def _worker_count(tickers: Any, upper_bound: int = 8) -> int:
    """Keep worker pools proportional to the actual request size."""
    size = len(tickers) if isinstance(tickers, (list, tuple)) else 0
    return max(1, min(size, upper_bound))


class MonthReturnWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any, period: str='1mo', interval: str='1d', start: Any=None) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.period = period
        self.interval = interval
        self.start = start

    def fetch(self) -> dict[str, Any]:
        """Return month/period returns synchronously."""
        try:
            results = {}

            def fetch_return(t: Any) -> Any:
                """Fetch return."""
                try:
                    history_kwargs = {'interval': self.interval}
                    if self.start is not None:
                        history_kwargs['start'] = self.start
                    else:
                        history_kwargs['period'] = self.period
                    df = yf.Ticker(t).history(**history_kwargs)
                    if df is not None and (not df.empty):
                        closes = df['Close'].dropna()
                        if len(closes) >= 2:
                            ret = (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0]) * 100
                            return (t, ret)
                except Exception as ex:
                    logger.warning(f'Return fetch error {t}: {ex}')
                return (t, None)
            with ThreadPoolExecutor(max_workers=_worker_count(self.tickers)) as executor:
                res_list = list(executor.map(fetch_return, self.tickers))
            for t, ret in res_list:
                if ret is not None:
                    results[t] = ret
            return results
        except Exception as ex:
            logger.error(f'MonthReturnWorker unhandled error: {ex}')
            return {}

    def run(self) -> Any:
        """Handle run."""
        self.finished.emit(self.fetch())

def _normalize_cash_amount(value: Any) -> float:
    """Return a non-negative finite cash amount."""
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    return max(amount, 0.0)


def _synthetic_business_index(*, start: Any=None, period: str='1mo') -> Any:
    """Build a simple business-day index for flat cash-only histories."""
    today = pd.Timestamp.today().normalize()
    if start is not None:
        try:
            start_ts = pd.Timestamp(start).normalize()
        except Exception:
            start_ts = today - pd.tseries.offsets.BDay(22)
        index = pd.bdate_range(start=start_ts, end=today)
    else:
        period_key = str(period or '1mo').strip().lower()
        periods = {
            '1d': 2,
            '5d': 5,
            '1mo': 23,
            '3mo': 64,
            '6mo': 127,
            'ytd': max(len(pd.bdate_range(start=pd.Timestamp(today.year, 1, 1), end=today)), 2),
            '1y': 253,
            '2y': 505,
            '3y': 757,
            '5y': 1261,
            'max': 1261,
        }.get(period_key, 23)
        index = pd.bdate_range(end=today, periods=max(int(periods), 2))
    if len(index) < 2:
        index = pd.bdate_range(end=today, periods=2)
    return index


class PortfolioMomentumWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any, shares_map: Any, period: str='1mo', interval: str='1d', start: Any=None, cash_amount: Any=0.0) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.shares_map = shares_map
        self.period = period
        self.interval = interval
        self.start = start
        self.cash_amount = _normalize_cash_amount(cash_amount)

    def _empty_payload(self, reason: str, *, included: Any=None, excluded: Any=None) -> dict[str, Any]:
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

    def fetch(self) -> dict[str, Any]:
        """Return portfolio momentum synchronously."""
        try:
            ordered_tickers = []
            seen = set()
            for ticker in self.tickers if isinstance(self.tickers, (list, tuple)) else []:
                symbol = str(ticker or '').strip().upper()
                if symbol and symbol not in seen:
                    ordered_tickers.append(symbol)
                    seen.add(symbol)
            normalized_shares = {}
            raw_shares = self.shares_map if isinstance(self.shares_map, dict) else {}
            positive_positions = []
            excluded_tickers = []
            for ticker in ordered_tickers:
                try:
                    shares = float(raw_shares.get(ticker, 0) or 0)
                except (TypeError, ValueError):
                    shares = 0.0
                normalized_shares[ticker] = shares
                if shares > 0:
                    positive_positions.append((ticker, shares))
                else:
                    excluded_tickers.append(ticker)
            if not positive_positions and self.cash_amount <= 0.0:
                return self._empty_payload('No positive-share positions', excluded=excluded_tickers)

            def cash_payload() -> dict[str, Any]:
                """Build a flat momentum payload for cash-only portfolios."""
                cash_index = _synthetic_business_index(start=self.start, period=self.period)
                dates = [pd.Timestamp(ts).date() for ts in cash_index]
                return {
                    'dates': dates,
                    'returns': [0.0 for _ts in cash_index],
                    'start_value': self.cash_amount,
                    'end_value': self.cash_amount,
                    'included_tickers': ['CASH'],
                    'excluded_tickers': excluded_tickers,
                    'start_date': dates[0].isoformat() if dates else None,
                    'reason': '',
                }

            def fetch_position_series(position: Any) -> Any:
                """Fetch one adjusted price series and convert it to position value."""
                ticker, shares = position
                try:
                    history_kwargs = {'interval': self.interval, 'auto_adjust': False, 'actions': False}
                    if self.start is not None:
                        history_kwargs['start'] = self.start
                    else:
                        history_kwargs['period'] = self.period
                    df = yf.Ticker(ticker).history(**history_kwargs)
                    if df is None or df.empty:
                        return (ticker, None)
                    if 'Adj Close' in df.columns:
                        series = pd.to_numeric(df['Adj Close'], errors='coerce').dropna()
                    else:
                        series = pd.Series(dtype='float64')
                    if series.empty and 'Close' in df.columns:
                        series = pd.to_numeric(df['Close'], errors='coerce').dropna()
                    if series.empty or len(series) < 2:
                        return (ticker, None)
                    series = series.astype(float).copy()
                    try:
                        series.index = pd.to_datetime(series.index).tz_localize(None)
                    except (TypeError, AttributeError):
                        series.index = pd.to_datetime(series.index)
                    series = series[~series.index.duplicated(keep='last')].sort_index()
                    if len(series) < 2:
                        return (ticker, None)
                    return (ticker, series * float(shares))
                except Exception as ex:
                    logger.warning(f'Portfolio momentum fetch error {ticker}: {ex}')
                    return (ticker, None)

            with ThreadPoolExecutor(max_workers=_worker_count(positive_positions)) as executor:
                results = list(executor.map(fetch_position_series, positive_positions))

            position_series = {}
            for ticker, series in results:
                if series is None:
                    excluded_tickers.append(ticker)
                    continue
                position_series[ticker] = series
            included_tickers = [ticker for ticker, _shares in positive_positions if ticker in position_series]
            if not included_tickers:
                if self.cash_amount > 0.0:
                    return cash_payload()
                return self._empty_payload('No historical data available', included=included_tickers, excluded=excluded_tickers)

            common_index = None
            for ticker in included_tickers:
                idx = pd.Index(position_series[ticker].index)
                common_index = idx if common_index is None else common_index.intersection(idx)
            if common_index is None or len(common_index) < 2:
                return self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
            common_index = common_index.sort_values()
            aligned = pd.concat(
                [position_series[ticker].reindex(common_index) for ticker in included_tickers],
                axis=1,
            )
            aligned = aligned.dropna(how='any')
            if aligned.empty or len(aligned.index) < 2:
                return self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
            total_series = aligned.sum(axis=1)
            total_series = pd.to_numeric(total_series, errors='coerce').dropna()
            if total_series.empty or len(total_series.index) < 2:
                return self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
            if self.cash_amount > 0.0:
                total_series = total_series + self.cash_amount
                included_tickers = [*included_tickers, 'CASH']
            start_value = float(total_series.iloc[0])
            if start_value <= 0:
                return self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
            returns = ((total_series / start_value) - 1.0) * 100.0
            dates = [pd.Timestamp(ts).date() for ts in returns.index]
            payload = {
                'dates': dates,
                'returns': [float(value) for value in returns.tolist()],
                'start_value': start_value,
                'end_value': float(total_series.iloc[-1]),
                'included_tickers': included_tickers,
                'excluded_tickers': excluded_tickers,
                'start_date': dates[0].isoformat() if dates else None,
                'reason': '',
            }
            return payload
        except Exception as ex:
            logger.error(f'PortfolioMomentumWorker unhandled error: {ex}')
            return self._empty_payload('Unable to load momentum data')

    def run(self) -> Any:
        """Handle run."""
        self.finished.emit(self.fetch())


class PortfolioAnalyticsWorker(QObject):
    finished = pyqtSignal(dict)

    _ANNUALIZATION_DAYS = 252.0
    _LOOKBACK_PERIODS = {
        '1y': '1y',
        '3y': '3y',
        '5y': '5y',
        'max': 'max',
    }

    def __init__(
        self,
        tickers: Any,
        shares_map: Any,
        prices_map: Any=None,
        benchmark_symbol: str='SPY',
        lookback_key: str='1y',
        cash_amount: Any=0.0,
    ) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.shares_map = shares_map
        self.prices_map = prices_map if isinstance(prices_map, dict) else {}
        self.benchmark_symbol = str(benchmark_symbol or 'SPY').upper().strip() or 'SPY'
        self.lookback_key = str(lookback_key or '1y').strip().lower()
        self.cash_amount = _normalize_cash_amount(cash_amount)

    def _empty_exposure(self, *, holdings_count: int=0) -> dict[str, Any]:
        """Build a normalized empty exposure payload."""
        holdings_total = int(holdings_count)
        return {
            'holdings_count': holdings_total,
            'valued_holdings_count': 0,
            'unvalued_holdings_count': holdings_total,
            'coverage_pct': (0.0 if holdings_total > 0 else None),
            'invested_value': 0.0,
            'largest_position_ticker': None,
            'largest_position_value': None,
            'top_position_weight': None,
            'top_3_weight': None,
            'top_5_weight': None,
            'concentration_score': None,
            'effective_holdings': None,
            'top_positions': [],
            'weights': {},
        }

    def _empty_metrics(self) -> dict[str, Any]:
        """Build a normalized empty portfolio-metrics payload."""
        return {
            'beta': None,
            'alpha': None,
            'volatility': None,
            'max_drawdown': None,
            'sharpe': None,
            'sortino': None,
            'cagr': None,
            'skewness': None,
            'tail_risk': None,
        }

    def _empty_payload(
        self,
        reason: str,
        *,
        exposure: Any=None,
        included: Any=None,
        excluded: Any=None,
        note: str='',
    ) -> dict[str, Any]:
        """Build a normalized empty analytics payload."""
        return {
            'metrics': self._empty_metrics(),
            'exposure': exposure if isinstance(exposure, dict) else self._empty_exposure(),
            'benchmark_symbol': self.benchmark_symbol,
            'lookback_key': self.lookback_key,
            'included_tickers': list(included or []),
            'excluded_tickers': list(excluded or []),
            'start_date': None,
            'end_date': None,
            'history_points': 0,
            'reason': str(reason or '').strip(),
            'note': str(note or '').strip(),
        }

    def _history_period(self) -> str:
        """Return the yfinance period string for the selected lookback."""
        return self._LOOKBACK_PERIODS.get(self.lookback_key, self._LOOKBACK_PERIODS['1y'])

    def _cash_history_index(self, benchmark_series: Any=None) -> Any:
        """Return an index for a flat cash-only analytics series."""
        if benchmark_series is not None:
            try:
                index = pd.Index(benchmark_series.index).sort_values()
                if len(index) >= 2:
                    return index
            except Exception:
                pass
        return _synthetic_business_index(period=self._history_period())

    def _fetch_price_series(self, symbol: str) -> Any:
        """Fetch one normalized adjusted-close history series."""
        clean_symbol = str(symbol or '').upper().strip()
        if not clean_symbol:
            return None
        try:
            df = yf.Ticker(clean_symbol).history(
                period=self._history_period(),
                interval='1d',
                auto_adjust=False,
                actions=False,
            )
            if df is None or df.empty:
                return None
            if 'Adj Close' in df.columns:
                series = pd.to_numeric(df['Adj Close'], errors='coerce').dropna()
            else:
                series = pd.Series(dtype='float64')
            if series.empty and 'Close' in df.columns:
                series = pd.to_numeric(df['Close'], errors='coerce').dropna()
            if series.empty or len(series) < 2:
                return None
            series = series.astype(float).copy()
            try:
                series.index = pd.to_datetime(series.index).tz_localize(None)
            except (TypeError, AttributeError):
                series.index = pd.to_datetime(series.index)
            series = series[~series.index.duplicated(keep='last')].sort_index()
            return series if len(series) >= 2 else None
        except Exception as ex:
            logger.warning(f'Portfolio analytics fetch error {clean_symbol}: {ex}')
            return None

    def _compute_exposure(
        self,
        positive_positions: list[tuple[str, float]],
        current_values: dict[str, float],
    ) -> dict[str, Any]:
        """Compute current-value concentration metrics for the active portfolio."""
        holdings_count = len(positive_positions)
        priced_values = {
            ticker: float(value)
            for ticker, value in current_values.items()
            if float(value or 0.0) > 0.0
        }
        valued_holdings_count = len(priced_values)
        unvalued_holdings_count = max(holdings_count - valued_holdings_count, 0)
        total_value = float(sum(priced_values.values()))
        if total_value <= 0.0:
            return self._empty_exposure(holdings_count=holdings_count)
        weights = {ticker: value / total_value for ticker, value in priced_values.items()}
        sorted_weights = sorted(weights.values(), reverse=True)
        sorted_positions = sorted(priced_values.items(), key=lambda item: item[1], reverse=True)
        concentration_score = float(sum(weight * weight for weight in weights.values()))
        effective_holdings = (1.0 / concentration_score) if concentration_score > 0 else None
        largest_position_ticker = sorted_positions[0][0] if sorted_positions else None
        largest_position_value = float(sorted_positions[0][1]) if sorted_positions else None
        top_positions = [
            {
                'ticker': ticker,
                'value': float(value),
                'weight_pct': float(weights.get(ticker, 0.0) * 100.0),
            }
            for ticker, value in sorted_positions[:5]
        ]
        return {
            'holdings_count': holdings_count,
            'valued_holdings_count': valued_holdings_count,
            'unvalued_holdings_count': unvalued_holdings_count,
            'coverage_pct': float((valued_holdings_count / holdings_count) * 100.0) if holdings_count > 0 else None,
            'invested_value': total_value,
            'largest_position_ticker': largest_position_ticker,
            'largest_position_value': largest_position_value,
            'top_position_weight': float(sorted_weights[0] * 100.0) if sorted_weights else None,
            'top_3_weight': float(sum(sorted_weights[:3]) * 100.0) if sorted_weights else None,
            'top_5_weight': float(sum(sorted_weights[:5]) * 100.0) if sorted_weights else None,
            'concentration_score': concentration_score,
            'effective_holdings': float(effective_holdings) if effective_holdings is not None else None,
            'top_positions': top_positions,
            'weights': {ticker: float(weight * 100.0) for ticker, weight in weights.items()},
        }

    def fetch(self) -> dict[str, Any]:
        """Fetch portfolio history and compute analytics synchronously."""
        try:
            ordered_tickers = []
            seen = set()
            for ticker in self.tickers if isinstance(self.tickers, (list, tuple)) else []:
                symbol = str(ticker or '').upper().strip()
                if symbol and symbol not in seen:
                    ordered_tickers.append(symbol)
                    seen.add(symbol)
            raw_shares = self.shares_map if isinstance(self.shares_map, dict) else {}
            raw_prices = self.prices_map if isinstance(self.prices_map, dict) else {}
            positive_positions = []
            for ticker in ordered_tickers:
                try:
                    shares = float(raw_shares.get(ticker, 0) or 0)
                except (TypeError, ValueError):
                    shares = 0.0
                if shares > 0:
                    positive_positions.append((ticker, shares))
            if not positive_positions and self.cash_amount <= 0.0:
                return self._empty_payload('No positive-share holdings')

            def fetch_position_series(position: Any) -> Any:
                """Fetch one holding's adjusted series and scale it by current shares."""
                ticker, shares = position
                series = self._fetch_price_series(ticker)
                if series is None:
                    return (ticker, None)
                return (ticker, series * float(shares))

            with ThreadPoolExecutor(max_workers=_worker_count(positive_positions)) as executor:
                results = list(executor.map(fetch_position_series, positive_positions))

            position_series = {}
            current_values = {}
            excluded_tickers = []
            for ticker, shares in positive_positions:
                raw_price = raw_prices.get(ticker)
                try:
                    current_price = float(raw_price)
                except (TypeError, ValueError):
                    current_price = None
                if current_price is not None and current_price > 0:
                    current_values[ticker] = float(shares * current_price)
            for ticker, series in results:
                if series is None:
                    excluded_tickers.append(ticker)
                    continue
                position_series[ticker] = series
                if ticker not in current_values:
                    current_values[ticker] = float(series.iloc[-1])
            exposure_positions = list(positive_positions)
            if self.cash_amount > 0.0:
                current_values['CASH'] = self.cash_amount
                exposure_positions.append(('CASH', 1.0))
            exposure = self._compute_exposure(exposure_positions, current_values)

            included_tickers = [ticker for ticker, _shares in positive_positions if ticker in position_series]
            if not included_tickers:
                if self.cash_amount <= 0.0:
                    return self._empty_payload(
                        'No historical data available',
                        exposure=exposure,
                        included=included_tickers,
                        excluded=excluded_tickers,
                    )
                benchmark_series = self._fetch_price_series(self.benchmark_symbol)
                cash_index = self._cash_history_index(benchmark_series)
                total_series = pd.Series([self.cash_amount for _ts in cash_index], index=cash_index, dtype='float64')
                included_tickers = ['CASH']
            else:
                common_index = None
                for ticker in included_tickers:
                    idx = pd.Index(position_series[ticker].index)
                    common_index = idx if common_index is None else common_index.intersection(idx)
                if common_index is None or len(common_index) < 2:
                    return self._empty_payload(
                        'No common historical window',
                        exposure=exposure,
                        included=included_tickers,
                        excluded=excluded_tickers,
                    )
                common_index = common_index.sort_values()
                aligned_positions = pd.concat(
                    [position_series[ticker].reindex(common_index) for ticker in included_tickers],
                    axis=1,
                ).dropna(how='any')
                if aligned_positions.empty or len(aligned_positions.index) < 2:
                    return self._empty_payload(
                        'No common historical window',
                        exposure=exposure,
                        included=included_tickers,
                        excluded=excluded_tickers,
                    )

                total_series = pd.to_numeric(aligned_positions.sum(axis=1), errors='coerce').dropna()
                if self.cash_amount > 0.0:
                    total_series = total_series + self.cash_amount
                    included_tickers = [*included_tickers, 'CASH']
            if total_series.empty or len(total_series.index) < 2:
                return self._empty_payload(
                    'No common historical window',
                    exposure=exposure,
                    included=included_tickers,
                    excluded=excluded_tickers,
                )
            start_value = float(total_series.iloc[0])
            if start_value <= 0.0:
                return self._empty_payload(
                    'No common historical window',
                    exposure=exposure,
                    included=included_tickers,
                    excluded=excluded_tickers,
                )

            metrics = self._empty_metrics()
            portfolio_returns = total_series.pct_change().dropna()
            if len(portfolio_returns.index) >= 2:
                mean_return = float(portfolio_returns.mean())
                std_return = float(portfolio_returns.std(ddof=1))
                if std_return > 0:
                    metrics['volatility'] = std_return * math.sqrt(self._ANNUALIZATION_DAYS) * 100.0
                    metrics['sharpe'] = (mean_return / std_return) * math.sqrt(self._ANNUALIZATION_DAYS)
                else:
                    metrics['volatility'] = 0.0
                downside_returns = portfolio_returns.clip(upper=0.0)
                downside_deviation = math.sqrt(float(downside_returns.pow(2).mean())) if not downside_returns.empty else 0.0
                if downside_deviation > 0:
                    metrics['sortino'] = (mean_return / downside_deviation) * math.sqrt(self._ANNUALIZATION_DAYS)
                if len(portfolio_returns.index) >= 3:
                    try:
                        metrics['skewness'] = float(portfolio_returns.skew())
                    except Exception:
                        metrics['skewness'] = None
                    if metrics['skewness'] is not None and not math.isfinite(metrics['skewness']):
                        metrics['skewness'] = 0.0
                try:
                    var_cutoff = float(portfolio_returns.quantile(0.05))
                    cvar_tail = portfolio_returns[portfolio_returns <= var_cutoff]
                    if not cvar_tail.empty:
                        metrics['tail_risk'] = float(cvar_tail.mean()) * 100.0
                except Exception:
                    metrics['tail_risk'] = None

            drawdowns = (total_series / total_series.cummax()) - 1.0
            if not drawdowns.empty:
                metrics['max_drawdown'] = float(drawdowns.min()) * 100.0

            end_value = float(total_series.iloc[-1])
            start_ts = pd.Timestamp(total_series.index[0])
            end_ts = pd.Timestamp(total_series.index[-1])
            elapsed_years = (end_ts - start_ts).total_seconds() / (365.25 * 24.0 * 60.0 * 60.0)
            if elapsed_years <= 0.0 and len(total_series.index) >= 2:
                elapsed_years = float(len(total_series.index) - 1) / self._ANNUALIZATION_DAYS
            if elapsed_years > 0.0 and start_value > 0.0 and end_value > 0.0:
                try:
                    metrics['cagr'] = (((end_value / start_value) ** (1.0 / elapsed_years)) - 1.0) * 100.0
                except Exception:
                    metrics['cagr'] = None

            note = ''
            benchmark_series = benchmark_series if 'benchmark_series' in locals() else self._fetch_price_series(self.benchmark_symbol)
            if benchmark_series is None:
                note = f'Benchmark {self.benchmark_symbol} unavailable; alpha and beta omitted.'
            else:
                aligned_benchmark = pd.concat(
                    [total_series.rename('portfolio_value'), benchmark_series.rename('benchmark_price')],
                    axis=1,
                    join='inner',
                ).dropna(how='any')
                if len(aligned_benchmark.index) >= 2:
                    return_frame = aligned_benchmark.pct_change().dropna(how='any')
                    if len(return_frame.index) >= 2:
                        benchmark_var = float(return_frame['benchmark_price'].var(ddof=1))
                        if benchmark_var > 0:
                            covariance = float(return_frame['portfolio_value'].cov(return_frame['benchmark_price']))
                            beta = covariance / benchmark_var
                            alpha = (
                                float(return_frame['portfolio_value'].mean())
                                - (beta * float(return_frame['benchmark_price'].mean()))
                            ) * self._ANNUALIZATION_DAYS
                            metrics['beta'] = beta
                            metrics['alpha'] = alpha * 100.0
                        else:
                            note = f'Benchmark {self.benchmark_symbol} had zero variance; alpha and beta omitted.'
                    else:
                        note = f'Benchmark {self.benchmark_symbol} did not overlap enough with portfolio history.'
                else:
                    note = f'Benchmark {self.benchmark_symbol} did not overlap enough with portfolio history.'

            payload = {
                'metrics': metrics,
                'exposure': exposure,
                'benchmark_symbol': self.benchmark_symbol,
                'lookback_key': self.lookback_key,
                'included_tickers': included_tickers,
                'excluded_tickers': excluded_tickers,
                'start_date': start_ts.date().isoformat(),
                'end_date': end_ts.date().isoformat(),
                'history_points': int(len(total_series.index)),
                'reason': '',
                'note': note,
            }
            return payload
        except Exception as ex:
            logger.error(f'PortfolioAnalyticsWorker unhandled error: {ex}')
            return self._empty_payload('Unable to load portfolio metrics')

    def run(self) -> Any:
        """Fetch portfolio history and compute analytics off the UI thread."""
        self.finished.emit(self.fetch())


class MarketCapWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers

    def fetch(self) -> dict[str, Any]:
        """Return market caps synchronously."""
        try:
            results = {}

            def fetch_mktcap(t: Any) -> Any:
                """Fetch mktcap."""
                try:
                    ticker = yf.Ticker(t)
                    with YF_LOCK:
                        mc = ticker.fast_info.get('marketCap')
                    if mc:
                        return (t, mc)
                    with YF_LOCK:
                        try:
                            info = ticker.info
                        except Exception as exc:
                            if is_yahoo_unauthorized_error(exc):
                                logger.info('Yahoo refused optional market-cap metadata for %s.', t)
                            else:
                                logger.warning(f'MarketCap info fallback error {t}: {exc}')
                            info = {}
                    return (t, info.get('marketCap'))
                except Exception as ex:
                    logger.warning(f'MarketCap fetch error {t}: {ex}')
                    return (t, None)
            with ThreadPoolExecutor(max_workers=_worker_count(self.tickers, upper_bound=3)) as executor:
                res_list = list(executor.map(fetch_mktcap, self.tickers))
            for t, mc in res_list:
                results[t] = mc
            return results
        except Exception as ex:
            logger.error(f'MarketCapWorker unhandled error: {ex}')
            return {}

    def run(self) -> Any:
        """Handle run."""
        self.finished.emit(self.fetch())
