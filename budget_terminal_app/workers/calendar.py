from __future__ import annotations
from typing import Any
from ..dependencies import *

class CalendarWorker(QObject):
    """Fetches earnings dates, ex-dividend dates, and analyst ratings for portfolio tickers."""
    finished = pyqtSignal(dict)

    def __init__(self, tickers: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers

    def run(self) -> Any:
        """Handle run."""
        try:
            results = {}

            def fetch_calendar(t: Any) -> Any:
                """Fetch calendar."""
                info = {}
                try:
                    ticker_obj = yf.Ticker(t)
                    cal = ticker_obj.calendar
                    if cal:
                        ed = cal.get('Earnings Date')
                        if ed is not None:
                            ed_list = list(ed) if hasattr(ed, '__iter__') and (not isinstance(ed, str)) else [ed]
                            if ed_list:
                                info['earnings'] = pd.Timestamp(ed_list[0]).date()
                        xd = cal.get('Ex-Dividend Date')
                        if xd is not None:
                            info['exdiv'] = pd.Timestamp(xd).date()
                except Exception as ex:
                    logger.warning(f'Calendar fetch error {t}: {ex}')
                try:
                    ud = yf.Ticker(t).upgrades_downgrades
                    if ud is not None and (not ud.empty):
                        latest = ud.iloc[0]
                        action = str(latest.get('Action', '')).lower()
                        grade = str(latest.get('ToGrade', ''))
                        arrow = '↑' if action in ('up', 'init', 'reit') else '↓' if action == 'down' else '→'
                        info['analyst'] = f'{arrow} {grade}'
                except Exception as ex:
                    logger.warning(f'Calendar analyst error {t}: {ex}')
                return (t, info)
            with ThreadPoolExecutor(max_workers=30) as executor:
                res_list = list(executor.map(fetch_calendar, self.tickers))
            for t, info in res_list:
                results[t] = info
            self.finished.emit(results)
        except Exception as ex:
            logger.error(f'CalendarWorker error: {ex}')
            self.finished.emit({})

def _get_economic_events(year: Any, month: Any) -> Any:
    """Return economic events for a given month as a list of (date, name, importance) tuples.
    Combines official FOMC schedule with auto-generated recurring releases."""
    import calendar as _cal
    _FOMC = {(2025, 1, 29), (2025, 3, 19), (2025, 5, 7), (2025, 6, 18), (2025, 7, 30), (2025, 9, 17), (2025, 10, 29), (2025, 12, 17), (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17), (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 16)}
    _CPI = {(2025, 1, 15), (2025, 2, 12), (2025, 3, 12), (2025, 4, 10), (2025, 5, 13), (2025, 6, 11), (2025, 7, 11), (2025, 8, 12), (2025, 9, 10), (2025, 10, 14), (2025, 11, 12), (2025, 12, 10), (2026, 1, 14), (2026, 2, 11), (2026, 3, 11), (2026, 4, 14), (2026, 5, 12), (2026, 6, 10), (2026, 7, 14), (2026, 8, 12), (2026, 9, 11), (2026, 10, 13), (2026, 11, 10), (2026, 12, 10)}
    _PCE = {(2025, 1, 31), (2025, 2, 28), (2025, 3, 28), (2025, 4, 30), (2025, 5, 30), (2025, 6, 27), (2025, 7, 31), (2025, 8, 29), (2025, 9, 26), (2025, 10, 31), (2025, 11, 26), (2025, 12, 23), (2026, 1, 30), (2026, 2, 27), (2026, 3, 27), (2026, 4, 30), (2026, 5, 29), (2026, 6, 26), (2026, 7, 31), (2026, 8, 28), (2026, 9, 25), (2026, 10, 30), (2026, 11, 25), (2026, 12, 23)}
    _GDP = {(2025, 1, 30), (2025, 4, 30), (2025, 7, 30), (2025, 10, 29), (2026, 1, 29), (2026, 4, 29), (2026, 7, 30), (2026, 10, 29)}
    events = []
    c = _cal.Calendar(firstweekday=0)
    for d in c.itermonthdates(year, month):
        if d.month == month and d.weekday() == 4:
            events.append((d, 'NFP Jobs Report', 'high'))
            break
    for y, m, d in _FOMC:
        if y == year and m == month:
            events.append((datetime.date(y, m, d), 'FOMC Decision', 'high'))
    for y, m, d in _CPI:
        if y == year and m == month:
            events.append((datetime.date(y, m, d), 'CPI Release', 'high'))
    for y, m, d in _PCE:
        if y == year and m == month:
            events.append((datetime.date(y, m, d), 'PCE Inflation', 'medium'))
    for y, m, d in _GDP:
        if y == year and m == month:
            events.append((datetime.date(y, m, d), 'GDP Report', 'high'))
    return events
