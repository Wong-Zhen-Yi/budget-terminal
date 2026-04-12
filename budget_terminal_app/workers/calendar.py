from __future__ import annotations
import re
from typing import Any
from ..dependencies import *
from ..paths import user_data_path

_MARKET_CALENDAR_IMPORT_WARNING_SHOWN = False
_ECONOMIC_EVENTS_CACHE_DIR = 'economic_calendar_cache'
_ECONOMIC_EVENTS_CACHE_TTL_SECONDS = 6 * 60 * 60
_ECONOMIC_EVENTS_MEMORY_CACHE: dict[int, tuple[float, list[tuple[datetime.date, str, str]]]] = {}
_ECONOMIC_EVENTS_CACHE_LOCK = threading.Lock()
_MARKET_HOLIDAY_CACHE_DIR = 'market_holiday_cache'
_MARKET_HOLIDAY_MEMORY_CACHE: dict[int, list[dict[str, Any]]] = {}
_MARKET_HOLIDAY_CACHE_LOCK = threading.Lock()
_HTTP_TIMEOUT_SECONDS = 20
_FED_FOMC_CALENDAR_URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
_BEA_SCHEDULE_URL = 'https://www.bea.gov/news/schedule/full'
_DISABLED_ECONOMIC_EVENT_NAMES = {'NFP Jobs Report', 'CPI Release'}
_HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}
_MONTH_NAME_TO_NUMBER = {
    'January': 1,
    'February': 2,
    'March': 3,
    'April': 4,
    'May': 5,
    'June': 6,
    'July': 7,
    'August': 8,
    'September': 9,
    'October': 10,
    'November': 11,
    'December': 12,
}
_MONTH_DAY_RE = re.compile(
    r'^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})$'
)
_FOMC_RANGE_RE = re.compile(r'^(\d{1,2})(?:-(\d{1,2}))\*?$')
_MARKET_HOLIDAY_NAME_OVERRIDES = {
    'New Years Day': "New Year's Day",
    'Dr. Martin Luther King Jr. Day': 'Martin Luther King Jr. Day',
    'Presidents Day': "Presidents Day",
    'Washingtons Birthday': "Washington's Birthday",
    'Good Friday 1908+': 'Good Friday',
    'Good Friday Before 1898': 'Good Friday',
    'Good Friday 1899 to 1905': 'Good Friday',
    'July 4th': 'Independence Day',
    'Christmas': 'Christmas Day',
    'Juneteenth Starting at 2022': 'Juneteenth',
    'Mondays, Tuesdays, and Thursdays Before Independence Day': 'Independence Day Eve',
    'Wednesdays Before Independence Day including and after 2013': 'Independence Day Eve',
    'Fridays after Independence Day prior to 2013': 'Independence Day Adjacent Friday',
    'Mondays, Tuesdays, Wednesdays, and Thursdays Before Christmas': 'Christmas Eve',
}
_MARKET_HOLIDAY_CELL_LABELS = {
    "New Year's Day": 'New Year',
    'Martin Luther King Jr. Day': 'MLK Day',
    'Presidents Day': 'Presidents',
    "Washington's Birthday": 'Washington',
    'Good Friday': 'Good Friday',
    'Memorial Day': 'Memorial',
    'Independence Day': 'Independence',
    'Independence Day (observed)': 'Independence',
    'Juneteenth': 'Juneteenth',
    'Juneteenth (observed)': 'Juneteenth',
    'Labor Day': 'Labor Day',
    'Thanksgiving': 'Thanksgiving',
    'Christmas Day': 'Christmas',
    'Christmas Day (observed)': 'Christmas',
    'Christmas Eve': 'Xmas Eve',
    'Black Friday': 'Black Friday',
    'Special Market Closure': 'Closed',
    'Special Early Close': 'Early Close',
}

def _economic_cache_path_for_year(year: Any) -> Any:
    """Return the on-disk cache path for one economic calendar year."""
    return user_data_path(_ECONOMIC_EVENTS_CACHE_DIR, f'{int(year)}.json')

def _market_holiday_cache_path_for_year(year: Any) -> Any:
    """Return the on-disk cache path for one market-holiday year."""
    return user_data_path(_MARKET_HOLIDAY_CACHE_DIR, f'{int(year)}.json')

def _extract_text_lines(raw_text: Any) -> list[str]:
    """Return normalized non-empty text lines from HTML or plain text."""
    lines = []
    for raw_line in str(raw_text or '').replace('\xa0', ' ').splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if line:
            lines.append(line)
    return lines

def _serialize_economic_events(events: list[tuple[datetime.date, str, str]]) -> list[dict[str, str]]:
    """Convert cached economic events into JSON-safe dicts."""
    payload = []
    for event_date, name, importance in events:
        payload.append(
            {
                'date': event_date.isoformat(),
                'name': str(name or ''),
                'importance': str(importance or ''),
            }
        )
    return payload

def _deserialize_economic_events(raw_events: Any) -> list[tuple[datetime.date, str, str]]:
    """Convert cached JSON rows into normalized economic event tuples."""
    events = []
    if not isinstance(raw_events, list):
        return events
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        try:
            event_date = datetime.date.fromisoformat(str(raw_event.get('date', '') or ''))
        except ValueError:
            continue
        name = str(raw_event.get('name', '') or '').strip()
        importance = str(raw_event.get('importance', '') or '').strip() or 'medium'
        if not name:
            continue
        events.append((event_date, name, importance))
    return _filter_disabled_economic_events(events)

def _now_timestamp() -> float:
    """Return the current UTC timestamp in seconds."""
    return datetime.datetime.now(datetime.timezone.utc).timestamp()

def _load_economic_events_cache(year: Any) -> tuple[list[tuple[datetime.date, str, str]], float] | None:
    """Load one year's cached economic events from disk."""
    path = _economic_cache_path_for_year(year)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception as ex:
        logger.warning('Economic events cache read error for %s: %s', year, ex)
        return None
    if not isinstance(payload, dict):
        return None
    fetched_at = float(payload.get('fetched_at', 0) or 0)
    events = _deserialize_economic_events(payload.get('events', []))
    return (events, fetched_at)

def _save_economic_events_cache(year: Any, events: list[tuple[datetime.date, str, str]]) -> None:
    """Persist one year's economic events to disk."""
    payload = {
        'year': int(year),
        'fetched_at': _now_timestamp(),
        'events': _serialize_economic_events(events),
    }
    try:
        _economic_cache_path_for_year(year).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    except Exception as ex:
        logger.warning('Economic events cache write error for %s: %s', year, ex)

def _serialize_market_holiday_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert cached market-holiday events into JSON-safe dicts."""
    payload = []
    for event in list(events or []):
        if not isinstance(event, dict):
            continue
        event_date = event.get('date')
        if not isinstance(event_date, datetime.date):
            continue
        payload.append(
            {
                'date': event_date.isoformat(),
                'market': str(event.get('market', 'US Equities') or 'US Equities'),
                'event': str(event.get('event', 'Holiday') or 'Holiday'),
                'detail': str(event.get('detail', '') or ''),
                'cell_label': str(event.get('cell_label', '') or ''),
                'color': str(event.get('color', '#26c6da') or '#26c6da'),
            }
        )
    return payload

def _deserialize_market_holiday_events(raw_events: Any) -> list[dict[str, Any]]:
    """Convert cached JSON rows into normalized market-holiday dicts."""
    events = []
    if not isinstance(raw_events, list):
        return events
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        try:
            event_date = datetime.date.fromisoformat(str(raw_event.get('date', '') or ''))
        except ValueError:
            continue
        events.append(
            {
                'date': event_date,
                'market': str(raw_event.get('market', 'US Equities') or 'US Equities'),
                'event': str(raw_event.get('event', 'Holiday') or 'Holiday'),
                'detail': str(raw_event.get('detail', '') or ''),
                'cell_label': str(raw_event.get('cell_label', '') or ''),
                'color': str(raw_event.get('color', '#26c6da') or '#26c6da'),
            }
        )
    events.sort(key=lambda item: (item.get('date'), item.get('event', ''), item.get('market', '')))
    return events

def _load_market_holiday_cache(year: Any) -> list[dict[str, Any]] | None:
    """Load one year's cached market holidays from disk."""
    path = _market_holiday_cache_path_for_year(year)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception as ex:
        logger.warning('Market holiday cache read error for %s: %s', year, ex)
        return None
    if not isinstance(payload, dict):
        return None
    return _deserialize_market_holiday_events(payload.get('events', []))

def _save_market_holiday_cache(year: Any, events: list[dict[str, Any]]) -> None:
    """Persist one year's market holidays to disk."""
    payload = {
        'year': int(year),
        'generated_at': _now_timestamp(),
        'events': _serialize_market_holiday_events(events),
    }
    try:
        _market_holiday_cache_path_for_year(year).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    except Exception as ex:
        logger.warning('Market holiday cache write error for %s: %s', year, ex)

def _dedupe_economic_events(events: list[tuple[datetime.date, str, str]]) -> list[tuple[datetime.date, str, str]]:
    """Drop duplicate event tuples while preserving sorted output."""
    deduped = []
    seen = set()
    for item in sorted(events, key=lambda row: (row[0], row[1], row[2])):
        key = (item[0], item[1])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def _filter_disabled_economic_events(
    events: list[tuple[datetime.date, str, str]],
) -> list[tuple[datetime.date, str, str]]:
    """Remove economic event categories whose source has been disabled."""
    filtered = [item for item in events if str(item[1] or '').strip() not in _DISABLED_ECONOMIC_EVENT_NAMES]
    filtered.sort(key=lambda item: (item[0], item[1], item[2]))
    return filtered

def _merge_missing_economic_categories(
    fresh_events: list[tuple[datetime.date, str, str]],
    stale_events: list[tuple[datetime.date, str, str]],
) -> list[tuple[datetime.date, str, str]]:
    """Keep stale categories when one official source temporarily returns nothing."""
    fresh_events = _filter_disabled_economic_events(fresh_events)
    stale_events = _filter_disabled_economic_events(stale_events)
    if not fresh_events:
        return list(stale_events)
    if not stale_events:
        return list(fresh_events)
    fresh_names = {name for _event_date, name, _importance in fresh_events}
    merged = list(fresh_events)
    for item in stale_events:
        if item[1] not in fresh_names:
            merged.append(item)
    return _dedupe_economic_events(merged)

def _http_get_text(url: str) -> str:
    """Fetch one official schedule page."""
    response = requests.get(url, headers=dict(_HTTP_HEADERS), timeout=_HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text

def _fetch_fomc_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch the official FOMC meeting schedule for one year."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_http_get_text(_FED_FOMC_CALENDAR_URL), 'html.parser')
    except Exception as ex:
        logger.warning('FOMC schedule fetch error for %s: %s', year, ex)
        return []
    lines = _extract_text_lines(soup.get_text('\n'))
    marker = f'{int(year)} FOMC Meetings'
    if marker not in lines:
        return []
    start_index = lines.index(marker) + 1
    section = []
    for line in lines[start_index:]:
        if line.endswith('FOMC Meetings') and line != marker:
            break
        section.append(line)
    events = []
    index = 0
    while index < len(section) - 1:
        month_name = section[index]
        month_number = _MONTH_NAME_TO_NUMBER.get(month_name)
        if month_number is None:
            index += 1
            continue
        date_match = _FOMC_RANGE_RE.match(section[index + 1])
        if not date_match:
            index += 1
            continue
        day_value = int(date_match.group(2) or date_match.group(1))
        try:
            event_date = datetime.date(int(year), month_number, day_value)
        except ValueError:
            index += 2
            continue
        events.append((event_date, 'FOMC Decision', 'high'))
        index += 2
    return events

def _parse_bea_schedule_events(html_text: str, year: Any) -> list[tuple[datetime.date, str, str]]:
    """Parse GDP and Personal Income and Outlays dates from the BEA release schedule."""
    from bs4 import BeautifulSoup

    lines = _extract_text_lines(BeautifulSoup(html_text, 'html.parser').get_text('\n'))
    marker = f'Year {int(year)}'
    start_index = lines.index(marker) + 1 if marker in lines else 0
    current_date = None
    events = []
    for line in lines[start_index:]:
        if line.startswith('Year ') and line != marker:
            break
        date_match = _MONTH_DAY_RE.match(line)
        if date_match:
            month_number = _MONTH_NAME_TO_NUMBER.get(date_match.group(1))
            current_date = None
            if month_number is None:
                continue
            try:
                current_date = datetime.date(int(year), month_number, int(date_match.group(2)))
            except ValueError:
                current_date = None
            continue
        if current_date is None:
            continue
        if line.startswith('Personal Income and Outlays,'):
            events.append((current_date, 'PCE Inflation', 'medium'))
        elif line.startswith('GDP (Advance Estimate)'):
            events.append((current_date, 'GDP Report', 'high'))
    return events

def _fetch_bea_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch GDP and Personal Income and Outlays dates from BEA."""
    try:
        html_text = _http_get_text(_BEA_SCHEDULE_URL)
    except Exception as ex:
        logger.warning('BEA schedule fetch error for %s: %s', year, ex)
        return []
    return _parse_bea_schedule_events(html_text, year)

def _fetch_official_economic_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch one year's official economic events from Fed and BEA."""
    events: list[tuple[datetime.date, str, str]] = []
    events.extend(_fetch_fomc_events_for_year(year))
    events.extend(_fetch_bea_events_for_year(year))
    return _filter_disabled_economic_events(_dedupe_economic_events(events))

def _get_economic_events_for_year(year: Any, *, force_refresh: bool = False) -> list[tuple[datetime.date, str, str]]:
    """Return one year's economic events, using cache with official-source refreshes."""
    year_value = int(year)
    now_ts = _now_timestamp()
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        cached = _ECONOMIC_EVENTS_MEMORY_CACHE.get(year_value)
    if (not force_refresh) and cached and (now_ts - float(cached[0])) < _ECONOMIC_EVENTS_CACHE_TTL_SECONDS:
        return _filter_disabled_economic_events(list(cached[1]))
    disk_cache = _load_economic_events_cache(year_value)
    stale_events = _filter_disabled_economic_events(disk_cache[0] if disk_cache is not None else [])
    stale_fetched_at = float(disk_cache[1]) if disk_cache is not None else 0.0
    if (not force_refresh) and disk_cache and (now_ts - stale_fetched_at) < _ECONOMIC_EVENTS_CACHE_TTL_SECONDS:
        with _ECONOMIC_EVENTS_CACHE_LOCK:
            _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (stale_fetched_at, list(stale_events))
        return list(stale_events)
    fresh_events = _fetch_official_economic_events_for_year(year_value)
    if fresh_events:
        fresh_events = _merge_missing_economic_categories(fresh_events, stale_events)
        save_ts = _now_timestamp()
        with _ECONOMIC_EVENTS_CACHE_LOCK:
            _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (save_ts, list(fresh_events))
        _save_economic_events_cache(year_value, fresh_events)
        return list(fresh_events)
    if stale_events:
        with _ECONOMIC_EVENTS_CACHE_LOCK:
            _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (stale_fetched_at or now_ts, list(stale_events))
        return list(stale_events)
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (now_ts, [])
    return []

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

class MarketHolidayWarmupWorker(QObject):
    """Warm one or more cached market-holiday years without blocking the UI thread."""

    finished = pyqtSignal(dict)

    def __init__(self, years: Any, force_refresh: bool = False) -> None:
        super().__init__()
        cleaned = []
        for value in list(years or []):
            try:
                year_value = int(value)
            except (TypeError, ValueError):
                continue
            if year_value not in cleaned:
                cleaned.append(year_value)
        self.years = cleaned
        self.force_refresh = bool(force_refresh)

    def run(self) -> Any:
        """Warm cache entries for the requested market-holiday years."""
        results = {}
        for year in self.years:
            results[year] = _get_market_holiday_events_for_year(year, force_refresh=self.force_refresh, blocking=True)
        self.finished.emit(results)

def _get_economic_events(year: Any, month: Any) -> Any:
    """Return one month's official economic events as (date, name, importance) tuples."""
    return [
        item
        for item in _get_economic_events_for_year(year)
        if item[0].year == int(year) and item[0].month == int(month)
    ]

def _format_market_holiday_name(raw_name: Any, event_date: Any, event_type: str) -> str:
    """Return a user-friendly market holiday name."""
    name = _MARKET_HOLIDAY_NAME_OVERRIDES.get(str(raw_name or '').strip(), str(raw_name or '').strip())
    if not name:
        return 'Special Early Close' if event_type == 'Early Close' else 'Special Market Closure'
    if name == 'Independence Day' and isinstance(event_date, datetime.date) and (event_date.month, event_date.day) != (7, 4):
        return 'Independence Day (observed)'
    if name == 'Christmas Day' and isinstance(event_date, datetime.date) and (event_date.month, event_date.day) != (12, 25):
        return 'Christmas Day (observed)'
    if name == "New Year's Day" and isinstance(event_date, datetime.date) and (event_date.month, event_date.day) != (1, 1):
        return "New Year's Day (observed)"
    if name == 'Juneteenth' and isinstance(event_date, datetime.date) and (event_date.month, event_date.day) != (6, 19):
        return 'Juneteenth (observed)'
    return name

def _market_holiday_cell_label(name: str, event_type: str) -> str:
    """Return a compact grid label for a named market holiday."""
    if event_type == 'Early Close':
        if name == 'Black Friday':
            return 'Black Fri'
        if name == 'Christmas Eve':
            return 'Xmas Eve'
        if name.startswith('Independence Day'):
            return 'July 3 Close'
    return _MARKET_HOLIDAY_CELL_LABELS.get(name, name[:12].strip() or ('Early Close' if event_type == 'Early Close' else 'Holiday'))

def _market_holiday_name_lookup(nyse: Any, start_date: Any, end_date: Any) -> tuple[dict[datetime.date, str], dict[datetime.date, str]]:
    """Return date-to-name lookups for holidays and early closes."""
    holiday_names: dict[datetime.date, str] = {}
    early_close_names: dict[datetime.date, str] = {}
    try:
        regular_holidays = nyse.regular_holidays.holidays(start=start_date.isoformat(), end=end_date.isoformat(), return_name=True)
        for ts, raw_name in regular_holidays.items():
            event_date = pd.Timestamp(ts).date()
            holiday_names[event_date] = _format_market_holiday_name(raw_name, event_date, 'Holiday')
    except Exception as ex:
        logger.warning(f'Market holiday name lookup error {start_date} to {end_date}: {ex}')
    for close_time, holiday_calendar in getattr(nyse, 'special_closes', []):
        try:
            close_names = holiday_calendar.holidays(start=start_date.isoformat(), end=end_date.isoformat(), return_name=True)
        except TypeError:
            close_names = holiday_calendar.holidays(start_date.isoformat(), end_date.isoformat(), return_name=True)
        except Exception as ex:
            logger.warning(f'Market early-close name lookup error {start_date} to {end_date}: {ex}')
            continue
        for ts, raw_name in close_names.items():
            event_date = pd.Timestamp(ts).date()
            early_close_names.setdefault(event_date, _format_market_holiday_name(raw_name, event_date, 'Early Close'))
    return holiday_names, early_close_names

def _fetch_market_holiday_events_for_year(year: Any) -> list[dict[str, Any]]:
    """Fetch one year's US-equity holidays and early closes from the exchange calendar."""
    global _MARKET_CALENDAR_IMPORT_WARNING_SHOWN
    try:
        import pandas_market_calendars as mcal
    except ImportError:
        if not _MARKET_CALENDAR_IMPORT_WARNING_SHOWN:
            logger.warning('pandas_market_calendars is unavailable; market holidays disabled')
            _MARKET_CALENDAR_IMPORT_WARNING_SHOWN = True
        return []
    first_day = datetime.date(int(year), 1, 1)
    last_day = datetime.date(int(year), 12, 31)
    try:
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=first_day.isoformat(), end_date=last_day.isoformat())
        early_closes = nyse.early_closes(schedule=schedule)
    except Exception as ex:
        logger.warning(f'Market holiday fetch error {year}: {ex}')
        return []
    holiday_names, early_close_names = _market_holiday_name_lookup(nyse, first_day, last_day)
    trading_days = {pd.Timestamp(idx).date() for idx in schedule.index}
    early_close_days = {pd.Timestamp(idx).date() for idx in early_closes.index}
    events = []
    day = first_day
    while day <= last_day:
        if day.weekday() >= 5:
            day += datetime.timedelta(days=1)
            continue
        if day not in trading_days:
            holiday_name = holiday_names.get(day, 'Special Market Closure')
            events.append(
                {
                    'date': day,
                    'market': 'US Equities',
                    'event': holiday_name,
                    'detail': 'Closed all day',
                    'cell_label': _market_holiday_cell_label(holiday_name, 'Holiday'),
                    'color': '#26c6da',
                }
            )
        day += datetime.timedelta(days=1)
    for day in sorted(early_close_days):
        holiday_name = early_close_names.get(day, 'Special Early Close')
        events.append(
            {
                'date': day,
                'market': 'US Equities',
                'event': holiday_name,
                'detail': '1:00 PM ET close',
                'cell_label': _market_holiday_cell_label(holiday_name, 'Early Close'),
                'color': '#8bc34a',
            }
        )
    events.sort(key=lambda item: (item.get('date'), item.get('event', ''), item.get('market', '')))
    return events

def _market_holidays_cached_for_year(year: Any) -> bool:
    """Return whether one market-holiday year is already available in memory or on disk."""
    year_value = int(year)
    with _MARKET_HOLIDAY_CACHE_LOCK:
        if year_value in _MARKET_HOLIDAY_MEMORY_CACHE:
            return True
    return _market_holiday_cache_path_for_year(year_value).exists()

def _get_market_holiday_events_for_year(
    year: Any,
    *,
    force_refresh: bool = False,
    blocking: bool = True,
) -> list[dict[str, Any]]:
    """Return one year's market holidays, optionally avoiding blocking generation on the UI thread."""
    year_value = int(year)
    if not force_refresh:
        with _MARKET_HOLIDAY_CACHE_LOCK:
            cached = _MARKET_HOLIDAY_MEMORY_CACHE.get(year_value)
        if cached is not None:
            return [dict(item) for item in cached]
        disk_cache = _load_market_holiday_cache(year_value)
        if disk_cache is not None:
            with _MARKET_HOLIDAY_CACHE_LOCK:
                _MARKET_HOLIDAY_MEMORY_CACHE[year_value] = [dict(item) for item in disk_cache]
            return [dict(item) for item in disk_cache]
    if not blocking:
        return []
    events = _fetch_market_holiday_events_for_year(year_value)
    with _MARKET_HOLIDAY_CACHE_LOCK:
        _MARKET_HOLIDAY_MEMORY_CACHE[year_value] = [dict(item) for item in events]
    _save_market_holiday_cache(year_value, events)
    return [dict(item) for item in events]

def _get_market_holiday_events(
    year: Any,
    month: Any,
    *,
    force_refresh: bool = False,
    blocking: bool = True,
) -> Any:
    """Return US-equity holidays and early closes for a month."""
    return [
        item
        for item in _get_market_holiday_events_for_year(year, force_refresh=force_refresh, blocking=blocking)
        if item.get('date') is not None
        and item['date'].year == int(year)
        and item['date'].month == int(month)
    ]
