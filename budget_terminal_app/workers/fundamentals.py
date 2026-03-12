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

    def run(self) -> None:
        """Handle run."""
        try:
            t = yf.Ticker(self.ticker)
            info = t.info
            if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None and (info.get('previousClose') is None)):
                self.error.emit(f"No data found for '{self.ticker}'. Check the ticker symbol.")
                return
            financials = t.financials
            cashflow = t.cashflow
            quarterly_financials = t.quarterly_financials
            quarterly_cashflow = t.quarterly_cashflow
            balance_sheet = t.balance_sheet
            quarterly_balance_sheet = t.quarterly_balance_sheet
            try:
                earnings_dates = t.earnings_dates
            except Exception:
                earnings_dates = None
            self.finished.emit({'ticker': self.ticker, 'info': info, 'financials': financials, 'cashflow': cashflow, 'quarterly_financials': quarterly_financials, 'quarterly_cashflow': quarterly_cashflow, 'balance_sheet': balance_sheet, 'quarterly_balance_sheet': quarterly_balance_sheet, 'earnings_dates': earnings_dates, 'av_used': False})
        except Exception as e:
            self.error.emit(f'Error fetching data: {e}')
