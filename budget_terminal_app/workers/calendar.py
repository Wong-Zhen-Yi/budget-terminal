from __future__ import annotations
import re
from typing import Any
from ..dependencies import *
from ..paths import user_data_path

_MARKET_CALENDAR_IMPORT_WARNING_SHOWN = False
_ECONOMIC_EVENTS_CACHE_DIR = 'economic_calendar_cache'
_ECONOMIC_EVENTS_CACHE_VERSION = 3
_ECONOMIC_EVENTS_CACHE_TTL_SECONDS = 6 * 60 * 60
_ECONOMIC_EVENTS_MEMORY_CACHE: dict[int, tuple[float, list[tuple[datetime.date, str, str]]]] = {}
_ECONOMIC_EVENTS_CACHE_LOCK = threading.Lock()
_MARKET_HOLIDAY_CACHE_DIR = 'market_holiday_cache'
_MARKET_HOLIDAY_CACHE_VERSION = 2
_MARKET_HOLIDAY_MEMORY_CACHE: dict[int, list[dict[str, Any]]] = {}
_MARKET_HOLIDAY_CACHE_LOCK = threading.Lock()
_HTTP_TIMEOUT_SECONDS = 20
_FED_FOMC_CALENDAR_URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
_BEA_SCHEDULE_URL = 'https://www.bea.gov/news/schedule/full'
_BLS_SCHEDULE_URL_TEMPLATE = 'https://www.bls.gov/schedule/{year}/home.htm'
_FRED_RELEASE_CALENDAR_URL_TEMPLATE = 'https://fred.stlouisfed.org/releases/calendar?rid={release_id}&y={year}'
_CENSUS_SCHEDULE_URL_TEMPLATE = 'https://www.census.gov/economic-indicators/calendar-listview-{year}.html'
_CENSUS_CURRENT_SCHEDULE_URL = 'https://www.census.gov/economic-indicators/calendar-listview.html'
_FRED_BLS_RELEASE_SPECS = (
    (10, 'Consumer Price Index', 'CPI Release', 'high'),
    (46, 'Producer Price Index', 'PPI Release', 'medium'),
    (50, 'Employment Situation', 'Jobs Report', 'high'),
    (192, 'Job Openings and Labor Turnover Survey', 'JOLTS Report', 'medium'),
)
#: Identify the client honestly. Do NOT put a browser user-agent here: bls.gov answers a spoofed
#: Chrome string with 403, and fred.stlouisfed.org tarpits it to roughly 18s against the 20s
#: timeout below. A plain product token gets 200 from both in under a second. The federalreserve,
#: bea and census hosts return identical bytes either way, so none of them needs one.
_HTTP_HEADERS = {
    'User-Agent': 'BudgetTerminal/1.0 (personal finance research tool)',
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
_FULL_DATE_RE = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+'
    r'(\d{1,2}),\s+(\d{4})$'
)
_FRED_FULL_DATE_RE = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+'
    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+'
    r'(\d{1,2}),\s+(\d{4})(?:\s+Updated)?$'
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
    if int(payload.get('calendar_version', 0) or 0) < _ECONOMIC_EVENTS_CACHE_VERSION:
        return None
    fetched_at = float(payload.get('fetched_at', 0) or 0)
    events = _deserialize_economic_events(payload.get('events', []))
    return (events, fetched_at)

def _save_economic_events_cache(year: Any, events: list[tuple[datetime.date, str, str]]) -> None:
    """Persist one year's economic events to disk."""
    payload = {
        'year': int(year),
        'calendar_version': _ECONOMIC_EVENTS_CACHE_VERSION,
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
    if int(payload.get('calendar_version', 0) or 0) < _MARKET_HOLIDAY_CACHE_VERSION:
        return None
    events = _deserialize_market_holiday_events(payload.get('events', []))
    if not events:
        return None
    return events

def _save_market_holiday_cache(year: Any, events: list[dict[str, Any]]) -> None:
    """Persist one year's market holidays to disk."""
    payload = {
        'year': int(year),
        'calendar_version': _MARKET_HOLIDAY_CACHE_VERSION,
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
    """Normalize economic events retained by the market-moving calendar."""
    filtered = [item for item in events if str(item[1] or '').strip()]
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


def _http_get_fred_text(url: str) -> str:
    """Fetch a FRED calendar page without the browser headers that its edge rejects."""
    response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
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
        elif (
            line.startswith('GDP (Advance Estimate)')
            or line.startswith('GDP (Second Estimate)')
            or line.startswith('GDP (Third Estimate)')
            or (
                line.startswith('Gross Domestic Product,')
                and 'by State' not in line
            )
        ):
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

def _parse_bls_schedule_events(html_text: str, year: Any) -> list[tuple[datetime.date, str, str]]:
    """Parse market-moving national releases from the official BLS annual schedule."""
    from bs4 import BeautifulSoup

    lines = _extract_text_lines(BeautifulSoup(html_text, 'html.parser').get_text('\n'))
    events = []
    current_date = None
    for line in lines:
        date_match = _FULL_DATE_RE.match(line)
        if date_match:
            month_number = _MONTH_NAME_TO_NUMBER[date_match.group(1)]
            try:
                current_date = datetime.date(int(date_match.group(3)), month_number, int(date_match.group(2)))
            except (TypeError, ValueError):
                current_date = None
            continue
        if current_date is None or current_date.year != int(year):
            continue
        lowered = line.casefold()
        if lowered.startswith('employment situation for '):
            events.append((current_date, 'Jobs Report', 'high'))
        elif lowered.startswith('consumer price index for '):
            events.append((current_date, 'CPI Release', 'high'))
        elif lowered.startswith('producer price index for '):
            events.append((current_date, 'PPI Release', 'medium'))
        elif lowered.startswith('job openings and labor turnover survey for '):
            events.append((current_date, 'JOLTS Report', 'medium'))
    return _dedupe_economic_events(events)

def _fetch_bls_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch the selected official BLS releases for one year."""
    try:
        html_text = _http_get_text(_BLS_SCHEDULE_URL_TEMPLATE.format(year=int(year)))
        return _parse_bls_schedule_events(html_text, year)
    except Exception as ex:
        if '403' in str(ex):
            logger.info('BLS schedule unavailable for %s; using cached or alternate calendar sources.', year)
        else:
            logger.warning('BLS schedule fetch error for %s: %s', year, ex)
        return []

def _parse_fred_release_calendar_events(
    html_text: str,
    year: Any,
    *,
    source_name: str,
    event_name: str,
    importance: str,
) -> list[tuple[datetime.date, str, str]]:
    """Parse one release-specific FRED calendar page into normalized Calendar events."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, 'html.parser')
    expected_source = str(source_name or '').casefold().strip()
    events = []
    current_date = None
    for row in soup.select('table.table-standard-theme tbody tr'):
        row_text = re.sub(r'\s+', ' ', row.get_text(' ', strip=True)).strip()
        date_match = _FRED_FULL_DATE_RE.match(row_text)
        if date_match:
            month_number = _MONTH_NAME_TO_NUMBER[date_match.group(1)]
            try:
                current_date = datetime.date(int(date_match.group(3)), month_number, int(date_match.group(2)))
            except (TypeError, ValueError):
                current_date = None
            continue
        if current_date is None or current_date.year != int(year):
            continue
        release_link = row.find('a', href=re.compile(r'^/release\?rid=\d+'))
        release_text = re.sub(r'\s+', ' ', release_link.get_text(' ', strip=True)).casefold() if release_link else ''
        if release_text != expected_source:
            continue
        events.append((current_date, event_name, importance))
        current_date = None
    return _dedupe_economic_events(events)


def _fetch_fred_release_events_for_year(
    year: Any,
    release_id: int,
    source_name: str,
    event_name: str,
    importance: str,
) -> list[tuple[datetime.date, str, str]]:
    """Fetch one BLS-derived release schedule from the no-key FRED calendar."""
    url = _FRED_RELEASE_CALENDAR_URL_TEMPLATE.format(release_id=int(release_id), year=int(year))
    try:
        html_text = _http_get_fred_text(url)
        events = _parse_fred_release_calendar_events(
            html_text,
            year,
            source_name=source_name,
            event_name=event_name,
            importance=importance,
        )
        if not events:
            logger.warning('FRED fallback calendar returned no %s dates for %s.', event_name, year)
        return events
    except Exception as ex:
        logger.warning('FRED fallback calendar fetch error for %s (%s): %s', event_name, year, ex)
        return []


def _fetch_fred_bls_fallback_events_for_year(
    year: Any,
    missing_event_names: set[str],
) -> list[tuple[datetime.date, str, str]]:
    """Fetch missing BLS categories concurrently from release-specific FRED calendars."""
    specs = [spec for spec in _FRED_BLS_RELEASE_SPECS if spec[2] in missing_event_names]
    if not specs:
        return []
    events = []
    with ThreadPoolExecutor(max_workers=len(specs)) as executor:
        futures = [executor.submit(_fetch_fred_release_events_for_year, year, *spec) for spec in specs]
        for future in futures:
            events.extend(future.result())
    return _dedupe_economic_events(events)


def _fetch_bls_events_with_fred_fallback(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Prefer BLS dates and fill only missing core categories from FRED."""
    bls_events = _fetch_bls_events_for_year(year)
    present_names = {event_name for _event_date, event_name, _importance in bls_events}
    required_names = {spec[2] for spec in _FRED_BLS_RELEASE_SPECS}
    fallback_events = _fetch_fred_bls_fallback_events_for_year(year, required_names - present_names)
    return _dedupe_economic_events([*bls_events, *fallback_events])


def _parse_census_schedule_events(html_text: str, year: Any) -> list[tuple[datetime.date, str, str]]:
    """Parse market-moving releases from the official Census indicator schedule."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, 'html.parser')
    events = []
    for row in soup.find_all('tr'):
        cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
        if len(cells) < 2:
            continue
        release_name = cells[0]
        try:
            event_date = datetime.datetime.strptime(cells[1], '%B %d, %Y').date()
        except (TypeError, ValueError):
            continue
        if event_date.year != int(year):
            continue
        normalized_name = release_name.casefold()
        if normalized_name.startswith('advance monthly sales for retail and food services'):
            events.append((event_date, 'Retail Sales', 'high'))
        elif normalized_name.startswith('advance report on durable goods'):
            events.append((event_date, 'Durable Goods Report', 'medium'))
        elif normalized_name.startswith('new residential construction'):
            events.append((event_date, 'Housing Starts & Permits', 'medium'))
        elif normalized_name.startswith('new residential sales'):
            events.append((event_date, 'New Home Sales', 'medium'))
    return _dedupe_economic_events(events)

def _fetch_census_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch the selected official Census releases for one year."""
    urls = [
        _CENSUS_SCHEDULE_URL_TEMPLATE.format(year=int(year)),
        _CENSUS_CURRENT_SCHEDULE_URL,
    ]
    errors = []
    for url in dict.fromkeys(urls):
        try:
            events = _parse_census_schedule_events(_http_get_text(url), year)
        except Exception as ex:
            errors.append(ex)
            continue
        if events:
            return events
    if errors:
        logger.warning('Census schedule fetch error for %s: %s', year, errors[-1])
    return []

def _fetch_official_economic_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Fetch one year's market-moving US events from official agency schedules."""
    events: list[tuple[datetime.date, str, str]] = []
    events.extend(_fetch_fomc_events_for_year(year))
    events.extend(_fetch_bls_events_with_fred_fallback(year))
    events.extend(_fetch_bea_events_for_year(year))
    events.extend(_fetch_census_events_for_year(year))
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


def _get_cached_economic_events_for_year(year: Any) -> list[tuple[datetime.date, str, str]]:
    """Return cached events without ever contacting an external source."""
    year_value = int(year)
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        cached = _ECONOMIC_EVENTS_MEMORY_CACHE.get(year_value)
    if cached is not None:
        return _filter_disabled_economic_events(list(cached[1]))
    disk_cache = _load_economic_events_cache(year_value)
    if disk_cache is None:
        return []
    events, fetched_at = disk_cache
    normalized = _filter_disabled_economic_events(list(events))
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (float(fetched_at), list(normalized))
    return normalized


def _economic_events_cached_for_year(year: Any, *, fresh_only: bool = True) -> bool:
    """Return whether a usable economic-event cache exists for one year."""
    year_value = int(year)
    now_ts = _now_timestamp()
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        cached = _ECONOMIC_EVENTS_MEMORY_CACHE.get(year_value)
    if cached is not None:
        return (not fresh_only) or (now_ts - float(cached[0])) < _ECONOMIC_EVENTS_CACHE_TTL_SECONDS
    disk_cache = _load_economic_events_cache(year_value)
    if disk_cache is None:
        return False
    events, fetched_at = disk_cache
    normalized = _filter_disabled_economic_events(list(events))
    with _ECONOMIC_EVENTS_CACHE_LOCK:
        _ECONOMIC_EVENTS_MEMORY_CACHE[year_value] = (float(fetched_at), list(normalized))
    return (not fresh_only) or (now_ts - float(fetched_at)) < _ECONOMIC_EVENTS_CACHE_TTL_SECONDS

class CalendarWorker(QObject):
    """Fetches earnings dates, ex-dividend dates, and analyst ratings for portfolio tickers."""
    finished = Signal(int, object, object)

    def __init__(self, tickers: Any, *, generation: int = 0, signature: Any = None) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = list(tickers or [])
        self.generation = int(generation)
        self.signature = tuple(signature if signature is not None else self.tickers)

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
            max_workers = min(8, max(1, len(self.tickers)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                res_list = list(executor.map(fetch_calendar, self.tickers))
            for t, info in res_list:
                results[t] = info
            self.finished.emit(self.generation, self.signature, results)
        except Exception as ex:
            logger.error(f'CalendarWorker error: {ex}')
            self.finished.emit(self.generation, self.signature, {})

class MarketHolidayWarmupWorker(QObject):
    """Warm one or more cached market-holiday years without blocking the UI thread."""

    finished = Signal(object)

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
            try:
                results[year] = _get_market_holiday_events_for_year(
                    year,
                    force_refresh=self.force_refresh,
                    blocking=True,
                )
            except Exception as ex:
                logger.warning('Market-holiday warmup failed for %s: %s', year, ex)
                results[year] = []
        self.finished.emit(results)


class EconomicCalendarWarmupWorker(QObject):
    """Refresh official economic-calendar cache entries outside the UI thread."""

    finished = Signal(int, object)

    def __init__(self, years: Any, *, generation: int, force_refresh: bool = False) -> None:
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
        self.generation = int(generation)
        self.force_refresh = bool(force_refresh)

    def run(self) -> Any:
        """Refresh the requested years and emit their cached result payloads."""
        results = {}
        for year in self.years:
            try:
                results[year] = _get_economic_events_for_year(year, force_refresh=self.force_refresh)
            except Exception as ex:
                logger.warning('Economic-calendar warmup failed for %s: %s', year, ex)
                results[year] = _get_cached_economic_events_for_year(year)
        self.finished.emit(self.generation, results)


def _get_economic_events(year: Any, month: Any, *, allow_network: bool = True) -> Any:
    """Return one month's official economic events as (date, name, importance) tuples."""
    year_events = (
        _get_economic_events_for_year(year)
        if allow_network
        else _get_cached_economic_events_for_year(year)
    )
    return [
        item
        for item in year_events
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

def _observed_fixed_market_holiday(year: int, month: int, day: int) -> datetime.date:
    """Return the NYSE observed date for a fixed-date holiday."""
    event_date = datetime.date(year, month, day)
    if event_date.weekday() == 5:
        return event_date - datetime.timedelta(days=1)
    if event_date.weekday() == 6:
        return event_date + datetime.timedelta(days=1)
    return event_date

def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> datetime.date:
    """Return the nth weekday in a month, where Monday is 0."""
    day = datetime.date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + datetime.timedelta(days=offset + ((occurrence - 1) * 7))

def _last_weekday(year: int, month: int, weekday: int) -> datetime.date:
    """Return the last weekday in a month, where Monday is 0."""
    if month == 12:
        day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return day - datetime.timedelta(days=(day.weekday() - weekday) % 7)

def _easter_sunday(year: int) -> datetime.date:
    """Return Gregorian Easter Sunday for a year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = ((h + correction - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)

def _fallback_us_equity_market_holiday_events_for_year(year: Any) -> list[dict[str, Any]]:
    """Build a deterministic NYSE holiday/early-close set when the calendar package is unavailable."""
    year_value = int(year)
    first_day = datetime.date(year_value, 1, 1)
    last_day = datetime.date(year_value, 12, 31)
    holidays: list[tuple[datetime.date, str]] = [
        (_observed_fixed_market_holiday(year_value, 1, 1), "New Year's Day"),
        (_nth_weekday(year_value, 1, 0, 3), 'Martin Luther King Jr. Day'),
        (_nth_weekday(year_value, 2, 0, 3), 'Presidents Day'),
        (_easter_sunday(year_value) - datetime.timedelta(days=2), 'Good Friday'),
        (_last_weekday(year_value, 5, 0), 'Memorial Day'),
        (_observed_fixed_market_holiday(year_value, 7, 4), 'Independence Day'),
        (_nth_weekday(year_value, 9, 0, 1), 'Labor Day'),
        (_nth_weekday(year_value, 11, 3, 4), 'Thanksgiving'),
        (_observed_fixed_market_holiday(year_value, 12, 25), 'Christmas Day'),
    ]
    if year_value >= 2022:
        holidays.append((_observed_fixed_market_holiday(year_value, 6, 19), 'Juneteenth'))
    next_new_year_observed = _observed_fixed_market_holiday(year_value + 1, 1, 1)
    if next_new_year_observed.year == year_value:
        holidays.append((next_new_year_observed, "New Year's Day"))
    holiday_by_date = {
        day: _format_market_holiday_name(name, day, 'Holiday')
        for day, name in holidays
        if first_day <= day <= last_day and day.weekday() < 5
    }
    early_close_by_date: dict[datetime.date, str] = {}
    black_friday = _nth_weekday(year_value, 11, 3, 4) + datetime.timedelta(days=1)
    early_close_by_date[black_friday] = 'Black Friday'
    christmas_eve = datetime.date(year_value, 12, 24)
    early_close_by_date[christmas_eve] = 'Christmas Eve'
    july_4 = datetime.date(year_value, 7, 4)
    independence_eve = july_4 - datetime.timedelta(days=1)
    early_close_by_date[independence_eve] = 'Independence Day Eve'

    events = []
    for day, name in sorted(holiday_by_date.items()):
        events.append(
            {
                'date': day,
                'market': 'US Equities',
                'event': name,
                'detail': 'Closed all day',
                'cell_label': _market_holiday_cell_label(name, 'Holiday'),
                'color': '#26c6da',
            }
        )
    for day, name in sorted(early_close_by_date.items()):
        if day.weekday() >= 5 or day in holiday_by_date or not (first_day <= day <= last_day):
            continue
        display_name = _format_market_holiday_name(name, day, 'Early Close')
        events.append(
            {
                'date': day,
                'market': 'US Equities',
                'event': display_name,
                'detail': '1:00 PM ET close',
                'cell_label': _market_holiday_cell_label(display_name, 'Early Close'),
                'color': '#8bc34a',
            }
        )
    events.sort(key=lambda item: (item.get('date'), item.get('event', ''), item.get('market', '')))
    return events

def _fetch_market_holiday_events_for_year(year: Any) -> list[dict[str, Any]]:
    """Fetch one year's US-equity holidays and early closes from the exchange calendar."""
    global _MARKET_CALENDAR_IMPORT_WARNING_SHOWN
    try:
        import pandas_market_calendars as mcal
    except ImportError:
        if not _MARKET_CALENDAR_IMPORT_WARNING_SHOWN:
            logger.info('pandas_market_calendars is unavailable; using built-in US market holiday fallback.')
            _MARKET_CALENDAR_IMPORT_WARNING_SHOWN = True
        return _fallback_us_equity_market_holiday_events_for_year(year)
    first_day = datetime.date(int(year), 1, 1)
    last_day = datetime.date(int(year), 12, 31)
    try:
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=first_day.isoformat(), end_date=last_day.isoformat())
        early_closes = nyse.early_closes(schedule=schedule)
    except Exception as ex:
        logger.warning(f'Market holiday fetch error {year}: {ex}')
        return _fallback_us_equity_market_holiday_events_for_year(year)
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
    return events or _fallback_us_equity_market_holiday_events_for_year(year)

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
