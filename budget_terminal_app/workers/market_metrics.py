from __future__ import annotations
from typing import Any
from ..dependencies import *


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

    def run(self) -> Any:
        """Handle run."""
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
            self.finished.emit(results)
        except Exception as ex:
            logger.error(f'MonthReturnWorker unhandled error: {ex}')
            self.finished.emit({})

class PortfolioMomentumWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any, shares_map: Any, period: str='1mo', interval: str='1d', start: Any=None) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.shares_map = shares_map
        self.period = period
        self.interval = interval
        self.start = start

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

    def run(self) -> Any:
        """Handle run."""
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
            if not positive_positions:
                self.finished.emit(self._empty_payload('No positive-share positions', excluded=excluded_tickers))
                return

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
                self.finished.emit(
                    self._empty_payload('No historical data available', included=included_tickers, excluded=excluded_tickers)
                )
                return

            common_index = None
            for ticker in included_tickers:
                idx = pd.Index(position_series[ticker].index)
                common_index = idx if common_index is None else common_index.intersection(idx)
            if common_index is None or len(common_index) < 2:
                self.finished.emit(
                    self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
                )
                return
            common_index = common_index.sort_values()
            aligned = pd.concat(
                [position_series[ticker].reindex(common_index) for ticker in included_tickers],
                axis=1,
            )
            aligned = aligned.dropna(how='any')
            if aligned.empty or len(aligned.index) < 2:
                self.finished.emit(
                    self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
                )
                return
            total_series = aligned.sum(axis=1)
            total_series = pd.to_numeric(total_series, errors='coerce').dropna()
            if total_series.empty or len(total_series.index) < 2:
                self.finished.emit(
                    self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
                )
                return
            start_value = float(total_series.iloc[0])
            if start_value <= 0:
                self.finished.emit(
                    self._empty_payload('No common historical window', included=included_tickers, excluded=excluded_tickers)
                )
                return
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
            self.finished.emit(payload)
        except Exception as ex:
            logger.error(f'PortfolioMomentumWorker unhandled error: {ex}')
            self.finished.emit(self._empty_payload('Unable to load momentum data'))

class MarketCapWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers

    def run(self) -> Any:
        """Handle run."""
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
                        info = ticker.info
                    return (t, info.get('marketCap'))
                except Exception as ex:
                    logger.warning(f'MarketCap fetch error {t}: {ex}')
                    return (t, None)
            with ThreadPoolExecutor(max_workers=_worker_count(self.tickers, upper_bound=3)) as executor:
                res_list = list(executor.map(fetch_mktcap, self.tickers))
            for t, mc in res_list:
                results[t] = mc
            self.finished.emit(results)
        except Exception as ex:
            logger.error(f'MarketCapWorker unhandled error: {ex}')
            self.finished.emit({})
