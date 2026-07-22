from __future__ import annotations
from typing import Any
from ..constants import *
from ..dependencies import *

class FundamentalsWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

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

    def run(self) -> None:
        """Handle run."""
        try:
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
            has_price = (
                info.get('regularMarketPrice') is not None
                or info.get('currentPrice') is not None
                or info.get('previousClose') is not None
            )
            if not info or not has_price:
                fallback_info = self._fallback_info_from_history(t)
                for key, value in fallback_info.items():
                    if info.get(key) is None:
                        info[key] = value
            if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None and (info.get('previousClose') is None)):
                self.error.emit(f"No data found for '{self.ticker}'. Check the ticker symbol.")
                return
            financials = self._optional_yahoo_value('financials', lambda: t.financials)
            cashflow = self._optional_yahoo_value('cashflow', lambda: t.cashflow)
            quarterly_financials = self._optional_yahoo_value('quarterly financials', lambda: t.quarterly_financials)
            quarterly_cashflow = self._optional_yahoo_value('quarterly cashflow', lambda: t.quarterly_cashflow)
            balance_sheet = self._optional_yahoo_value('balance sheet', lambda: t.balance_sheet)
            quarterly_balance_sheet = self._optional_yahoo_value('quarterly balance sheet', lambda: t.quarterly_balance_sheet)
            earnings_dates = self._optional_yahoo_value('earnings dates', lambda: t.earnings_dates)
            self.finished.emit({'ticker': self.ticker, 'info': info, 'financials': financials, 'cashflow': cashflow, 'quarterly_financials': quarterly_financials, 'quarterly_cashflow': quarterly_cashflow, 'balance_sheet': balance_sheet, 'quarterly_balance_sheet': quarterly_balance_sheet, 'earnings_dates': earnings_dates, 'av_used': False})
        except Exception as e:
            self.error.emit(f'Error fetching data: {e}')
