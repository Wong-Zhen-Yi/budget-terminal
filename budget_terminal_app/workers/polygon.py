from __future__ import annotations
from typing import Any
from ..dependencies import *

def _safe_get_year(col: Any) -> Any:
    """Safely extract year from a column header (Timestamp, datetime, or string)."""
    if col is None:
        return None
    try:
        if hasattr(col, 'year'):
            return col.year
        import pandas as pd
        ts = pd.to_datetime(str(col))
        if hasattr(ts, 'year'):
            return ts.year
    except:
        pass
    import re
    m = re.search('(20\\d{2})', str(col))
    if m:
        return int(m.group(1))
    return None

def _get_fiscal_year(col: Any, fy_end_month: Any) -> Any:
    """Map a report date to its fiscal year based on fiscal year end month.

    Example: If fy_end_month=1 (January), a report from Apr 2024 belongs to FY 2025
    because the fiscal year ending Jan 2025 covers Feb 2024 - Jan 2025.
    """
    if fy_end_month is None or fy_end_month == 12:
        return _safe_get_year(col)
    month, year = (None, None)
    if hasattr(col, 'month') and hasattr(col, 'year'):
        month, year = (col.month, col.year)
    else:
        try:
            ts = pd.to_datetime(str(col))
            month, year = (ts.month, ts.year)
        except:
            return _safe_get_year(col)
    if month is None or year is None:
        return _safe_get_year(col)
    if month > fy_end_month:
        return year + 1
    return year

class P9PolygonWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ticker: Any, api_key: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.ticker = ticker
        self.api_key = api_key
        self.base_url = 'https://api.massive.com'

    def run(self) -> Any:
        """Handle run."""
        try:
            if not self.api_key:
                raise ValueError('API Key is required for Massive/Polygon data.')
            logger.info(f'P9: Starting fetch for {self.ticker} using {self.base_url}')
            details_url = f'{self.base_url}/v3/reference/tickers/{self.ticker}?apiKey={self.api_key}'
            logger.info(f"P9: Requesting details from {details_url.replace(self.api_key, 'HIDDEN')}")
            details_res = requests.get(details_url, timeout=10)
            logger.info(f'P9: Details status: {details_res.status_code}')
            if details_res.status_code != 200:
                try:
                    err_data = details_res.json()
                    msg = err_data.get('message', err_data.get('error', 'Unknown Error'))
                except:
                    msg = details_res.text[:100]
                if details_res.status_code == 403:
                    msg = 'Invalid API Key or Unauthorized (403)'
                elif details_res.status_code == 404:
                    msg = f'Ticker {self.ticker} not found (404)'
                raise ValueError(f'Massive API Error: {msg}')
            details_data = details_res.json()
            results = details_data.get('results', {})
            info = {'longName': results.get('name', self.ticker), 'sector': results.get('sic_description', 'N/A'), 'industry': results.get('sic_code', 'N/A'), 'currency': results.get('currency_name', 'USD').upper(), 'exchange': results.get('primary_exchange', 'N/A'), 'website': results.get('homepage_url', '')}

            def fetch_financials(timeframe: Any) -> Any:
                """Fetch financials."""
                url = f'{self.base_url}/vX/reference/financials?ticker={self.ticker}&timeframe={timeframe}&limit=20&apiKey={self.api_key}'
                logger.info(f'P9: Requesting {timeframe} financials...')
                res = requests.get(url, timeout=10)
                if res.status_code != 200:
                    logger.warning(f'P9: {timeframe} financials failed with {res.status_code}')
                    return []
                return res.json().get('results', [])
            q_reports = fetch_financials('quarterly')
            a_reports = fetch_financials('annual')
            logger.info(f'P9: Successfully fetched {len(q_reports)}Q and {len(a_reports)}A reports.')
            self.finished.emit({'ticker': self.ticker, 'info': info, 'polygon_quarterly': q_reports, 'polygon_annual': a_reports, 'source': 'Massive/Polygon'})
        except Exception as e:
            logger.error(f'P9 Error: {str(e)}')
            self.error.emit(str(e))
