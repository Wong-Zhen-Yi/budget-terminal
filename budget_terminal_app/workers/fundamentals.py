from __future__ import annotations
from typing import Any
from ..constants import *
from ..dependencies import *
from ..services.sec_edgar import fetch_company_bundle, merge_sec_frames

class FundamentalsWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, ticker: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.ticker = ticker

    def _fallback_info_from_history(self, ticker_obj: Any) -> dict[str, Any]:
        try:
            history = ticker_obj.history(period='5d', interval='1d')
        except Exception:
            return {}
        if history is None or history.empty or 'Close' not in history.columns:
            return {}
        closes = history['Close'].dropna()
        if closes.empty:
            return {}
        info = {
            'symbol': self.ticker,
            'shortName': self.ticker,
            'regularMarketPrice': float(closes.iloc[-1]),
            'currentPrice': float(closes.iloc[-1]),
        }
        if len(closes) >= 2:
            info['previousClose'] = float(closes.iloc[-2])
        return info

    def _optional_yahoo_value(self, label: str, getter: Any) -> Any:
        try:
            return getter()
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional fundamentals %s for %s.', label, self.ticker)
            else:
                logger.info('Optional fundamentals %s fetch failed for %s: %s', label, self.ticker, exc)
            return None

    def _fetch_yahoo_payload(self) -> dict[str, Any]:
        """Fetch the existing Yahoo payload without coupling it to SEC availability."""
        t = yf.Ticker(self.ticker)
        try:
            info = t.info
            if not isinstance(info, dict):
                info = {}
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional fundamentals metadata for %s; using price-history fallback.', self.ticker)
            else:
                logger.info('Fundamentals metadata fetch failed for %s: %s', self.ticker, exc)
            info = self._fallback_info_from_history(t)
        has_price = any(info.get(key) is not None for key in ('regularMarketPrice', 'currentPrice', 'previousClose'))
        if not info or not has_price:
            fallback_info = self._fallback_info_from_history(t)
            for key, value in fallback_info.items():
                if info.get(key) is None:
                    info[key] = value
        return {
            'ticker': self.ticker,
            'info': info,
            'financials': self._optional_yahoo_value('financials', lambda: t.financials),
            'cashflow': self._optional_yahoo_value('cashflow', lambda: t.cashflow),
            'quarterly_financials': self._optional_yahoo_value('quarterly financials', lambda: t.quarterly_financials),
            'quarterly_cashflow': self._optional_yahoo_value('quarterly cashflow', lambda: t.quarterly_cashflow),
            'balance_sheet': self._optional_yahoo_value('balance sheet', lambda: t.balance_sheet),
            'quarterly_balance_sheet': self._optional_yahoo_value('quarterly balance sheet', lambda: t.quarterly_balance_sheet),
            'earnings_dates': self._optional_yahoo_value('earnings dates', lambda: t.earnings_dates),
            'av_used': False,
        }

    def run(self) -> None:
        """Fetch Yahoo and SEC independently, then emit the best partial result."""
        yahoo_payload: dict[str, Any] = {}
        sec_bundle: dict[str, Any] = {}
        failures = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='BudgetTerminalFundamentals') as executor:
            yahoo_future = executor.submit(self._fetch_yahoo_payload)
            sec_future = executor.submit(fetch_company_bundle, self.ticker)
            try:
                yahoo_payload = yahoo_future.result()
            except Exception as exc:
                failures.append(f'Yahoo: {exc}')
                logger.info('Fundamentals Yahoo fetch failed for %s: %s', self.ticker, exc)
            try:
                sec_bundle = sec_future.result()
            except Exception as exc:
                failures.append(f'SEC: {exc}')
                logger.info('Fundamentals SEC fetch failed for %s: %s', self.ticker, exc)

        if not yahoo_payload:
            yahoo_payload = {
                'ticker': self.ticker,
                'info': {'symbol': self.ticker, 'shortName': self.ticker},
                'financials': None,
                'cashflow': None,
                'quarterly_financials': None,
                'quarterly_cashflow': None,
                'balance_sheet': None,
                'quarterly_balance_sheet': None,
                'earnings_dates': None,
                'av_used': False,
            }
        if sec_bundle.get('statements_available'):
            yahoo_payload = merge_sec_frames(yahoo_payload, sec_bundle)
        sec_payload = {key: value for key, value in sec_bundle.items() if key != 'frames'}
        yahoo_payload['sec'] = sec_payload
        yahoo_payload['statement_sources'] = {
            'primary': 'SEC EDGAR' if sec_bundle.get('statements_available') else 'yfinance',
            'fallback': 'yfinance',
        }
        yahoo_payload['warnings'] = [*sec_payload.get('warnings', []), *failures]

        has_price = any(yahoo_payload.get('info', {}).get(key) is not None for key in ('regularMarketPrice', 'currentPrice', 'previousClose'))
        has_statements = any(
            frame is not None and not getattr(frame, 'empty', True)
            for key, frame in yahoo_payload.items()
            if key in {'financials', 'cashflow', 'balance_sheet', 'quarterly_financials', 'quarterly_cashflow', 'quarterly_balance_sheet'}
        )
        if not has_price and not has_statements:
            self.error.emit(f"No data found for '{self.ticker}'. Check the ticker symbol.")
            return
        self.finished.emit(yahoo_payload)
