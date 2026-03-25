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
