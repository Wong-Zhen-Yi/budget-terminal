from __future__ import annotations

import csv
import io
import re
from typing import Any

from ..dependencies import *
from ..paths import user_data_path

EARNINGS_CALENDAR_CACHE_DIR = 'earnings_calendar_cache'
EARNINGS_CALENDAR_CACHE_TTL_SECONDS = 12 * 60 * 60
EARNINGS_CALENDAR_SOURCE_NAME = 'yfinance Earnings Calendar'
EARNINGS_CALENDAR_SOURCE_URL = 'https://finance.yahoo.com/calendar/earnings'
EARNINGS_SYMBOL_UNIVERSE_SOURCE_NAME = 'NASDAQ Trader Symbol Directory'
EARNINGS_SYMBOL_UNIVERSE_SOURCE_URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
EARNINGS_DEFAULT_RANGE_KEY = 'rolling_12m'

_CACHE_VERSION = 1
_YFINANCE_EARNINGS_PAGE_SIZE = 100
_YFINANCE_EARNINGS_MAX_PAGES = 120
_SYMBOL_UNIVERSE_TTL_SECONDS = 7 * 24 * 60 * 60
_HTTP_TIMEOUT_SECONDS = 20
_HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BudgetTerminal/1.0',
    'Accept': 'text/plain,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
_EARNINGS_MEMORY_CACHE: dict[str, dict[str, Any]] = {}
_EARNINGS_MEMORY_CACHE_LOCK = threading.Lock()
_SYMBOL_UNIVERSE_MEMORY_CACHE: tuple[float, set[str], dict[str, Any]] | None = None
_SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK = threading.Lock()
_EXCLUDED_SECURITY_NAME_RE = re.compile(
    r'\b('
    r'etf|etn|exchange[- ]traded|fund|closed[- ]end|warrant|right|unit|'
    r'preferred|preference|senior note|subordinated note|baby bond|'
    r'notes due|depositary share'
    r')s?\b',
    re.IGNORECASE,
)
_INCLUDED_COMPANY_NAME_RE = re.compile(
    r'\b(common stock|ordinary share|ordinary shares|american depositary|ads|class [a-z] ordinary|shares)\b',
    re.IGNORECASE,
)


def earnings_calendar_cache_path(cache_key: Any) -> Path:
    """Return the cache path for one earnings calendar request."""
    safe_key = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(cache_key or EARNINGS_DEFAULT_RANGE_KEY)).strip('_')
    return user_data_path(EARNINGS_CALENDAR_CACHE_DIR, f'{safe_key or EARNINGS_DEFAULT_RANGE_KEY}.json')


def earnings_symbol_universe_cache_path() -> Path:
    """Return the local cache path for the US-listed company symbol universe."""
    return user_data_path(EARNINGS_CALENDAR_CACHE_DIR, 'us_company_symbols.json')


class EarningsCalendarWorker(QObject):
    """Background wrapper for all-market US-listed company earnings rows."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        cache_key: str = EARNINGS_DEFAULT_RANGE_KEY,
        force: bool = False,
    ) -> None:
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.cache_key = str(cache_key or EARNINGS_DEFAULT_RANGE_KEY)
        self.force = bool(force)

    def run(self) -> None:
        try:
            self.finished.emit(
                EarningsCalendarService.fetch(
                    start_date=self.start_date,
                    end_date=self.end_date,
                    cache_key=self.cache_key,
                    force=self.force,
                )
            )
        except Exception as ex:
            logger.error('EarningsCalendarWorker error: %s', ex)
            self.error.emit(str(ex))


class EarningsCalendarService:
    """Fetch, normalize, merge, and cache all-market US-listed company earnings rows."""

    @classmethod
    def default_date_range(cls, today: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
        today = today or datetime.date.today()
        return today, today + datetime.timedelta(days=365)

    @staticmethod
    def year_date_range(year: Any) -> tuple[datetime.date, datetime.date]:
        year_value = int(year)
        return datetime.date(year_value, 1, 1), datetime.date(year_value, 12, 31)

    @classmethod
    def fetch(
        cls,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        cache_key: str = EARNINGS_DEFAULT_RANGE_KEY,
        force: bool = False,
    ) -> dict[str, Any]:
        start_date, end_date = cls._normalize_date_range(start_date, end_date)
        today = datetime.date.today()
        cache_key = str(cache_key or cls._range_cache_key(start_date, end_date))
        cached = cls.load_cached_payload(
            start_date=start_date,
            end_date=end_date,
            cache_key=cache_key,
            allow_stale=True,
        )
        if cached is not None and (not force) and cls._cache_is_fresh_enough(cached, today=today):
            return cached
        try:
            live_payload = cls.fetch_live_payload(start_date=start_date, end_date=end_date)
        except Exception as exc:
            if cached is not None:
                cached['stale'] = True
                cached['warning'] = str(exc)
                return cached
            raise
        previous_rows = cached.get('rows') if isinstance(cached, dict) else []
        previous_changes = cached.get('date_changes') if isinstance(cached, dict) else []
        merged_rows, date_changes = cls.merge_with_cached_rows(
            fresh_rows=live_payload.get('rows') or [],
            cached_rows=previous_rows,
            prior_changes=previous_changes,
            today=today,
        )
        payload = {
            'cache_version': _CACHE_VERSION,
            'source': str(live_payload.get('source') or EARNINGS_CALENDAR_SOURCE_NAME),
            'source_url': str(live_payload.get('source_url') or EARNINGS_CALENDAR_SOURCE_URL),
            'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'from_cache': False,
            'cache_age_seconds': 0.0,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'range_key': cache_key,
            'rows': cls._normalize_cached_rows(merged_rows, start_date=start_date, end_date=end_date),
            'date_changes': date_changes,
            'symbol_universe': dict(live_payload.get('symbol_universe') or {}),
        }
        cls.save_cached_payload(payload, cache_key=cache_key)
        return payload

    @classmethod
    def load_cached_payload(
        cls,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        cache_key: str = EARNINGS_DEFAULT_RANGE_KEY,
        allow_stale: bool = True,
    ) -> dict[str, Any] | None:
        start_date, end_date = cls._normalize_date_range(start_date, end_date)
        with _EARNINGS_MEMORY_CACHE_LOCK:
            memory_payload = _EARNINGS_MEMORY_CACHE.get(str(cache_key))
        if isinstance(memory_payload, dict):
            payload = dict(memory_payload)
        else:
            path = earnings_calendar_cache_path(cache_key)
            if not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except Exception as exc:
                logger.warning('Earnings calendar cache read error: %s', exc)
                return None
            if isinstance(payload, dict):
                with _EARNINGS_MEMORY_CACHE_LOCK:
                    _EARNINGS_MEMORY_CACHE[str(cache_key)] = dict(payload)
            else:
                return None
        fetched_at = str(payload.get('fetched_at') or '').strip()
        rows = cls._normalize_cached_rows(payload.get('rows'), start_date=start_date, end_date=end_date)
        date_changes = cls._normalize_change_history(payload.get('date_changes'))
        if not fetched_at and not rows:
            return None
        age_seconds = cls._cache_age_seconds(fetched_at)
        today = datetime.date.today()
        if (
            (not allow_stale)
            and age_seconds is not None
            and age_seconds > EARNINGS_CALENDAR_CACHE_TTL_SECONDS
            and any(cls._row_date(row) >= today for row in rows if cls._row_date(row) is not None)
        ):
            return None
        return {
            'cache_version': int(payload.get('cache_version') or 0),
            'source': str(payload.get('source') or EARNINGS_CALENDAR_SOURCE_NAME),
            'source_url': str(payload.get('source_url') or EARNINGS_CALENDAR_SOURCE_URL),
            'fetched_at': fetched_at,
            'from_cache': True,
            'cache_age_seconds': age_seconds,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'range_key': str(payload.get('range_key') or cache_key),
            'rows': rows,
            'date_changes': date_changes,
            'symbol_universe': dict(payload.get('symbol_universe') or {}),
        }

    @classmethod
    def save_cached_payload(cls, payload: dict[str, Any], *, cache_key: str = EARNINGS_DEFAULT_RANGE_KEY) -> None:
        start_date = cls._parse_date(payload.get('start_date')) or datetime.date.today()
        end_date = cls._parse_date(payload.get('end_date')) or start_date
        cache_payload = {
            'cache_version': _CACHE_VERSION,
            'source': str(payload.get('source') or EARNINGS_CALENDAR_SOURCE_NAME),
            'source_url': str(payload.get('source_url') or EARNINGS_CALENDAR_SOURCE_URL),
            'fetched_at': str(payload.get('fetched_at') or datetime.datetime.now().isoformat(timespec='seconds')),
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'range_key': str(payload.get('range_key') or cache_key),
            'rows': cls._normalize_cached_rows(payload.get('rows'), start_date=start_date, end_date=end_date),
            'date_changes': cls._normalize_change_history(payload.get('date_changes')),
            'symbol_universe': dict(payload.get('symbol_universe') or {}),
        }
        path = earnings_calendar_cache_path(cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding='utf-8')
            with _EARNINGS_MEMORY_CACHE_LOCK:
                _EARNINGS_MEMORY_CACHE[str(cache_key)] = dict(cache_payload)
        except Exception as exc:
            logger.warning('Earnings calendar cache write error: %s', exc)

    @classmethod
    def fetch_live_payload(
        cls,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> dict[str, Any]:
        symbols, universe_meta = cls.fetch_us_company_symbol_universe()
        return {
            'rows': cls._fetch_yfinance_rows(start_date, end_date, allowed_symbols=symbols),
            'source': EARNINGS_CALENDAR_SOURCE_NAME,
            'source_url': EARNINGS_CALENDAR_SOURCE_URL,
            'symbol_universe': universe_meta,
        }

    @classmethod
    def fetch_us_company_symbol_universe(cls, *, force: bool = False) -> tuple[set[str], dict[str, Any]]:
        global _SYMBOL_UNIVERSE_MEMORY_CACHE
        now_ts = cls._now_timestamp()
        with _SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK:
            cached_memory = _SYMBOL_UNIVERSE_MEMORY_CACHE
        if (
            (not force)
            and cached_memory is not None
            and now_ts - float(cached_memory[0]) <= _SYMBOL_UNIVERSE_TTL_SECONDS
        ):
            return set(cached_memory[1]), dict(cached_memory[2])
        cached_disk = cls._load_symbol_universe_cache()
        if (
            (not force)
            and cached_disk is not None
            and now_ts - float(cached_disk.get('fetched_at_ts') or 0.0) <= _SYMBOL_UNIVERSE_TTL_SECONDS
        ):
            symbols = {str(item).upper() for item in cached_disk.get('symbols', []) if str(item or '').strip()}
            meta = dict(cached_disk.get('meta') or {})
            with _SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK:
                _SYMBOL_UNIVERSE_MEMORY_CACHE = (float(cached_disk.get('fetched_at_ts') or now_ts), symbols, meta)
            return symbols, meta
        try:
            response = requests.get(
                EARNINGS_SYMBOL_UNIVERSE_SOURCE_URL,
                headers=dict(_HTTP_HEADERS),
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            symbols = cls.parse_nasdaq_traded_symbols(response.text)
            if not symbols:
                raise ValueError('NASDAQ Trader symbol universe returned no company symbols')
            fetched_at = datetime.datetime.now().isoformat(timespec='seconds')
            meta = {
                'source': EARNINGS_SYMBOL_UNIVERSE_SOURCE_NAME,
                'source_url': EARNINGS_SYMBOL_UNIVERSE_SOURCE_URL,
                'fetched_at': fetched_at,
                'count': len(symbols),
            }
            cls._save_symbol_universe_cache(symbols, meta=meta)
            with _SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK:
                _SYMBOL_UNIVERSE_MEMORY_CACHE = (now_ts, set(symbols), dict(meta))
            return set(symbols), meta
        except Exception:
            if cached_disk is not None:
                symbols = {str(item).upper() for item in cached_disk.get('symbols', []) if str(item or '').strip()}
                meta = dict(cached_disk.get('meta') or {})
                meta['stale'] = True
                return symbols, meta
            raise

    @classmethod
    def parse_nasdaq_traded_symbols(cls, text: Any) -> set[str]:
        symbols: set[str] = set()
        reader = csv.DictReader(io.StringIO(str(text or '')), delimiter='|')
        for row in reader:
            symbol = str(row.get('Symbol') or '').upper().strip()
            if not symbol or symbol.startswith('File Creation Time'):
                continue
            if not cls._is_company_symbol_row(row):
                continue
            symbols.add(symbol)
        return symbols

    @classmethod
    def parse_yfinance_frame(
        cls,
        frame: Any,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        allowed_symbols: set[str] | None = None,
        today: datetime.date | None = None,
    ) -> list[dict[str, Any]]:
        if frame is None or not hasattr(frame, 'iterrows'):
            return []
        today = today or datetime.date.today()
        allowed = {str(item).upper().strip() for item in allowed_symbols or set() if str(item or '').strip()}
        rows: list[dict[str, Any]] = []
        for index, raw_row in frame.iterrows():
            symbol = cls._clean_symbol(index)
            if not symbol or (allowed and symbol not in allowed):
                continue
            row_get = raw_row.get if hasattr(raw_row, 'get') else lambda key, default=None: default
            event_dt = cls._parse_datetime(row_get('Event Start Date'))
            event_date = event_dt.date() if isinstance(event_dt, datetime.datetime) else None
            if event_date is None or event_date < start_date or event_date > end_date:
                continue
            company = cls._clean_value(row_get('Company'))
            event_name = cls._clean_value(row_get('Event Name'))
            timing = cls._clean_value(row_get('Timing')).upper() or '--'
            market_cap_value = cls._to_float(row_get('Marketcap'))
            eps_estimate_value = cls._to_float(row_get('EPS Estimate'))
            reported_eps_value = cls._to_float(row_get('Reported EPS'))
            surprise_pct_value = cls._to_float(row_get('Surprise(%)'))
            row = {
                'date': event_date.isoformat(),
                'date_display': cls._format_date(event_date),
                'datetime_utc': cls._format_datetime_utc(event_dt),
                'time_display': cls._format_time_display(event_dt),
                'symbol': symbol,
                'company': company or '--',
                'event_name': event_name or '--',
                'timing': timing,
                'eps_estimate': cls._format_number(eps_estimate_value),
                'eps_estimate_value': eps_estimate_value,
                'reported_eps': cls._format_number(reported_eps_value),
                'reported_eps_value': reported_eps_value,
                'surprise_pct': cls._format_percent(surprise_pct_value),
                'surprise_pct_value': surprise_pct_value,
                'market_cap': cls._format_market_cap(market_cap_value),
                'market_cap_value': market_cap_value,
                'status': cls._status_for_row(event_date, reported_eps_value=reported_eps_value, today=today),
                'previous_date': '',
                'previous_datetime_utc': '',
                'changed_date': False,
            }
            row['event_key'] = cls.event_identity_key(row)
            rows.append(row)
        return cls._dedupe_rows(rows)

    @classmethod
    def merge_with_cached_rows(
        cls,
        *,
        fresh_rows: Any,
        cached_rows: Any,
        prior_changes: Any = None,
        today: datetime.date | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        today = today or datetime.date.today()
        normalized_fresh = cls._normalize_cached_rows(fresh_rows, start_date=datetime.date.min, end_date=datetime.date.max)
        normalized_cached = cls._normalize_cached_rows(cached_rows, start_date=datetime.date.min, end_date=datetime.date.max)
        changes = cls._normalize_change_history(prior_changes)
        change_keys = {
            (
                str(item.get('event_key') or ''),
                str(item.get('previous_datetime_utc') or ''),
                str(item.get('new_datetime_utc') or ''),
            )
            for item in changes
            if isinstance(item, dict)
        }
        cached_by_key = {cls.event_identity_key(row): row for row in normalized_cached}
        merged: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        detected_at = datetime.datetime.now().isoformat(timespec='seconds')
        for fresh_row in normalized_fresh:
            row = dict(fresh_row)
            key = cls.event_identity_key(row)
            row['event_key'] = key
            previous = cached_by_key.get(key)
            if previous is not None:
                previous_datetime = str(previous.get('datetime_utc') or '').strip()
                current_datetime = str(row.get('datetime_utc') or '').strip()
                previous_timing = str(previous.get('timing') or '').strip()
                current_timing = str(row.get('timing') or '').strip()
                if (previous_datetime and current_datetime and previous_datetime != current_datetime) or (
                    previous_timing and current_timing and previous_timing != current_timing
                ):
                    row['changed_date'] = True
                    row['previous_datetime_utc'] = previous_datetime
                    row['previous_date'] = previous.get('date_display') or previous.get('date') or ''
                    change = {
                        'event_key': key,
                        'symbol': str(row.get('symbol') or ''),
                        'company': str(row.get('company') or ''),
                        'event_name': str(row.get('event_name') or ''),
                        'previous_date': str(previous.get('date') or ''),
                        'new_date': str(row.get('date') or ''),
                        'previous_datetime_utc': previous_datetime,
                        'new_datetime_utc': current_datetime,
                        'previous_timing': previous_timing,
                        'new_timing': current_timing,
                        'detected_at': detected_at,
                    }
                    change_key = (key, previous_datetime, current_datetime)
                    if change_key not in change_keys:
                        changes.append(change)
                        change_keys.add(change_key)
                else:
                    row['changed_date'] = bool(previous.get('changed_date'))
                    row['previous_date'] = str(previous.get('previous_date') or '')
                    row['previous_datetime_utc'] = str(previous.get('previous_datetime_utc') or '')
            merged.append(row)
            seen_keys.add(key)
        for cached_row in normalized_cached:
            key = cls.event_identity_key(cached_row)
            if key in seen_keys:
                continue
            row_date = cls._row_date(cached_row)
            if row_date is not None and row_date < today:
                merged.append(cached_row)
                seen_keys.add(key)
        return cls._dedupe_rows(merged), changes

    @classmethod
    def event_identity_key(cls, row: dict[str, Any]) -> str:
        symbol = str(row.get('symbol') or '').upper().strip()
        event_name = str(row.get('event_name') or '').strip()
        if event_name and event_name != '--' and event_name.casefold() != 'none':
            normalized_name = re.sub(r'\s+', ' ', event_name.casefold()).strip()
            return f'{symbol}|{normalized_name}'
        row_date = cls._row_date(row)
        if row_date is None:
            return f'{symbol}|unknown'
        quarter = ((row_date.month - 1) // 3) + 1
        return f'{symbol}|{row_date.year}Q{quarter}'

    @classmethod
    def _fetch_yfinance_rows(
        cls,
        start_date: datetime.date,
        end_date: datetime.date,
        *,
        allowed_symbols: set[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_pages: set[tuple[tuple[str, str, str], ...]] = set()
        calendar = yf.Calendars(start=start_date, end=end_date)
        for page in range(_YFINANCE_EARNINGS_MAX_PAGES):
            offset = page * _YFINANCE_EARNINGS_PAGE_SIZE
            frame = calendar.get_earnings_calendar(
                filter_most_active=False,
                limit=_YFINANCE_EARNINGS_PAGE_SIZE,
                offset=offset,
                force=page > 0,
            )
            page_rows = cls.parse_yfinance_frame(
                frame,
                start_date=start_date,
                end_date=end_date,
                allowed_symbols=allowed_symbols,
            )
            page_key = tuple(
                (
                    str(row.get('datetime_utc') or ''),
                    str(row.get('symbol') or ''),
                    str(row.get('event_key') or ''),
                )
                for row in page_rows
            )
            if not page_rows or page_key in seen_pages:
                break
            seen_pages.add(page_key)
            rows.extend(page_rows)
            try:
                row_count = int(len(frame))
            except Exception:
                row_count = len(page_rows)
            if row_count < _YFINANCE_EARNINGS_PAGE_SIZE:
                break
        return cls._dedupe_rows(rows)

    @classmethod
    def _cache_is_fresh_enough(cls, payload: dict[str, Any], *, today: datetime.date) -> bool:
        rows = [dict(row) for row in list(payload.get('rows') or []) if isinstance(row, dict)]
        age_seconds = payload.get('cache_age_seconds')
        has_today_or_future = any(cls._row_date(row) is not None and cls._row_date(row) >= today for row in rows)
        if not has_today_or_future:
            return True
        try:
            return float(age_seconds) <= EARNINGS_CALENDAR_CACHE_TTL_SECONDS
        except Exception:
            return False

    @staticmethod
    def _range_cache_key(start_date: datetime.date, end_date: datetime.date) -> str:
        return f'range_{start_date.isoformat()}_{end_date.isoformat()}'

    @classmethod
    def _normalize_cached_rows(
        cls,
        raw_rows: Any,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not isinstance(raw_rows, list):
            return rows
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            row = cls._normalize_row(raw_row)
            row_date = cls._row_date(row)
            if row_date is None or row_date < start_date or row_date > end_date:
                continue
            rows.append(row)
        return cls._dedupe_rows(rows)

    @classmethod
    def _normalize_row(cls, raw_row: dict[str, Any]) -> dict[str, Any]:
        row_date = cls._parse_date(raw_row.get('date') or raw_row.get('date_display'))
        date_text = row_date.isoformat() if row_date is not None else ''
        datetime_utc = str(raw_row.get('datetime_utc') or '').strip()
        event_dt = cls._parse_datetime(datetime_utc) if datetime_utc else None
        if not datetime_utc and event_dt is not None:
            datetime_utc = cls._format_datetime_utc(event_dt)
        normalized = {
            'date': date_text,
            'date_display': str(raw_row.get('date_display') or (cls._format_date(row_date) if row_date else '')).strip(),
            'datetime_utc': datetime_utc,
            'time_display': str(raw_row.get('time_display') or (cls._format_time_display(event_dt) if event_dt else '')).strip(),
            'symbol': str(raw_row.get('symbol') or '').upper().strip(),
            'company': str(raw_row.get('company') or '--').strip() or '--',
            'event_name': str(raw_row.get('event_name') or '--').strip() or '--',
            'timing': str(raw_row.get('timing') or '--').upper().strip() or '--',
            'eps_estimate': str(raw_row.get('eps_estimate') or cls._format_number(raw_row.get('eps_estimate_value'))).strip() or '--',
            'eps_estimate_value': cls._to_float(raw_row.get('eps_estimate_value')),
            'reported_eps': str(raw_row.get('reported_eps') or cls._format_number(raw_row.get('reported_eps_value'))).strip() or '--',
            'reported_eps_value': cls._to_float(raw_row.get('reported_eps_value')),
            'surprise_pct': str(raw_row.get('surprise_pct') or cls._format_percent(raw_row.get('surprise_pct_value'))).strip() or '--',
            'surprise_pct_value': cls._to_float(raw_row.get('surprise_pct_value')),
            'market_cap': str(raw_row.get('market_cap') or cls._format_market_cap(raw_row.get('market_cap_value'))).strip() or '--',
            'market_cap_value': cls._to_float(raw_row.get('market_cap_value')),
            'status': str(raw_row.get('status') or '').strip(),
            'previous_date': str(raw_row.get('previous_date') or '').strip(),
            'previous_datetime_utc': str(raw_row.get('previous_datetime_utc') or '').strip(),
            'changed_date': bool(raw_row.get('changed_date')),
        }
        if not normalized['status']:
            normalized['status'] = cls._status_for_row(
                row_date,
                reported_eps_value=normalized['reported_eps_value'],
                today=datetime.date.today(),
            )
        normalized['event_key'] = str(raw_row.get('event_key') or cls.event_identity_key(normalized)).strip()
        return normalized

    @staticmethod
    def _normalize_change_history(raw_changes: Any) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        if not isinstance(raw_changes, list):
            return changes
        fields = (
            'event_key',
            'symbol',
            'company',
            'event_name',
            'previous_date',
            'new_date',
            'previous_datetime_utc',
            'new_datetime_utc',
            'previous_timing',
            'new_timing',
            'detected_at',
        )
        for raw_change in raw_changes:
            if not isinstance(raw_change, dict):
                continue
            change = {field: str(raw_change.get(field) or '').strip() for field in fields}
            if change.get('event_key') and (change.get('previous_datetime_utc') or change.get('new_datetime_utc')):
                changes.append(change)
        return changes

    @classmethod
    def _dedupe_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in sorted(rows, key=lambda item: (str(item.get('date') or ''), str(item.get('time_display') or ''), str(item.get('symbol') or ''))):
            key = (cls.event_identity_key(row), str(row.get('datetime_utc') or row.get('date') or ''))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    @classmethod
    def _is_company_symbol_row(cls, row: dict[str, Any]) -> bool:
        if str(row.get('Nasdaq Traded') or '').upper().strip() != 'Y':
            return False
        if str(row.get('Test Issue') or '').upper().strip() == 'Y':
            return False
        if str(row.get('ETF') or '').upper().strip() == 'Y':
            return False
        symbol = str(row.get('Symbol') or '').upper().strip()
        name = str(row.get('Security Name') or '').strip()
        if not symbol or '$' in symbol or '^' in symbol:
            return False
        name_for_exclusions = re.sub(r'\bAmerican Depositary Shares?\b', 'American Depositary', name, flags=re.IGNORECASE)
        if _EXCLUDED_SECURITY_NAME_RE.search(name_for_exclusions):
            return False
        return bool(_INCLUDED_COMPANY_NAME_RE.search(name))

    @classmethod
    def _load_symbol_universe_cache(cls) -> dict[str, Any] | None:
        path = earnings_symbol_universe_cache_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('Earnings symbol universe cache read error: %s', exc)
            return None
        if not isinstance(payload, dict):
            return None
        symbols = [str(item).upper().strip() for item in list(payload.get('symbols') or []) if str(item or '').strip()]
        if not symbols:
            return None
        fetched_at = str(payload.get('fetched_at') or '').strip()
        return {
            'symbols': symbols,
            'fetched_at_ts': cls._timestamp_from_iso(fetched_at),
            'meta': {
                'source': str(payload.get('source') or EARNINGS_SYMBOL_UNIVERSE_SOURCE_NAME),
                'source_url': str(payload.get('source_url') or EARNINGS_SYMBOL_UNIVERSE_SOURCE_URL),
                'fetched_at': fetched_at,
                'count': len(symbols),
            },
        }

    @classmethod
    def _save_symbol_universe_cache(cls, symbols: set[str], *, meta: dict[str, Any]) -> None:
        payload = {
            'source': str(meta.get('source') or EARNINGS_SYMBOL_UNIVERSE_SOURCE_NAME),
            'source_url': str(meta.get('source_url') or EARNINGS_SYMBOL_UNIVERSE_SOURCE_URL),
            'fetched_at': str(meta.get('fetched_at') or datetime.datetime.now().isoformat(timespec='seconds')),
            'symbols': sorted(symbols),
        }
        try:
            path = earnings_symbol_universe_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            logger.warning('Earnings symbol universe cache write error: %s', exc)

    @staticmethod
    def _normalize_date_range(start_date: Any, end_date: Any) -> tuple[datetime.date, datetime.date]:
        start = start_date if isinstance(start_date, datetime.date) else datetime.date.fromisoformat(str(start_date)[:10])
        end = end_date if isinstance(end_date, datetime.date) else datetime.date.fromisoformat(str(end_date)[:10])
        if end < start:
            start, end = end, start
        return start, end

    @staticmethod
    def _row_date(row: dict[str, Any]) -> datetime.date | None:
        return EarningsCalendarService._parse_date(row.get('date') or row.get('date_display'))

    @staticmethod
    def _parse_date(value: Any) -> datetime.date | None:
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            pass
        for fmt in ('%b %d, %Y', '%B %d, %Y', '%m/%d/%Y', '%m/%d/%y'):
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime.datetime | None:
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time.min)
        try:
            parsed = pd.Timestamp(value)
        except Exception:
            return None
        try:
            if pd.isna(parsed):
                return None
        except Exception:
            pass
        try:
            if parsed.tzinfo is not None:
                parsed = parsed.tz_convert('UTC')
            else:
                parsed = parsed.tz_localize('UTC')
            return parsed.to_pydatetime()
        except Exception:
            try:
                return parsed.to_pydatetime()
            except Exception:
                return None

    @staticmethod
    def _format_datetime_utc(value: datetime.datetime | None) -> str:
        if value is None:
            return ''
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def _format_time_display(value: datetime.datetime | None) -> str:
        if value is None:
            return '--'
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc).strftime('%H:%M UTC')

    @staticmethod
    def _format_date(value: datetime.date | None) -> str:
        if value is None:
            return '--'
        return value.strftime('%b %d, %Y')

    @staticmethod
    def _clean_symbol(value: Any) -> str:
        if isinstance(value, tuple):
            value = value[0] if value else ''
        return EarningsCalendarService._clean_value(value).upper()

    @staticmethod
    def _clean_value(value: Any) -> str:
        if EarningsCalendarService._is_missing_value(value):
            return ''
        return ' '.join(str(value or '').replace('\xa0', ' ').split()).strip()

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        if value is None:
            return True
        try:
            if pd.isna(value):
                return True
        except Exception:
            pass
        text = str(value).strip()
        return not text or text in {'--', '-', 'nan', 'NaN', 'NaT', 'None'}

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if EarningsCalendarService._is_missing_value(value):
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None

    @staticmethod
    def _format_number(value: Any) -> str:
        numeric = EarningsCalendarService._to_float(value)
        if numeric is None:
            return '--'
        return f'{numeric:,.2f}'

    @staticmethod
    def _format_percent(value: Any) -> str:
        numeric = EarningsCalendarService._to_float(value)
        if numeric is None:
            return '--'
        return f'{numeric:,.2f}%'

    @staticmethod
    def _format_market_cap(value: Any) -> str:
        numeric = EarningsCalendarService._to_float(value)
        if numeric is None or numeric <= 0:
            return '--'
        for suffix, divisor in (('T', 1_000_000_000_000), ('B', 1_000_000_000), ('M', 1_000_000)):
            if numeric >= divisor:
                return f'${numeric / divisor:,.2f}{suffix}'
        return f'${numeric:,.0f}'

    @staticmethod
    def _status_for_row(
        event_date: datetime.date | None,
        *,
        reported_eps_value: float | None,
        today: datetime.date,
    ) -> str:
        if event_date is None:
            return '--'
        if reported_eps_value is not None:
            return 'Reported'
        if event_date < today:
            return 'Completed'
        if event_date == today:
            return 'Today'
        return 'Upcoming'

    @staticmethod
    def _cache_age_seconds(fetched_at: str) -> float | None:
        try:
            timestamp = datetime.datetime.fromisoformat(str(fetched_at or ''))
        except ValueError:
            return None
        if timestamp.tzinfo is not None:
            now = datetime.datetime.now(timestamp.tzinfo)
        else:
            now = datetime.datetime.now()
        return max((now - timestamp).total_seconds(), 0.0)

    @staticmethod
    def _timestamp_from_iso(value: Any) -> float:
        try:
            timestamp = datetime.datetime.fromisoformat(str(value or ''))
        except ValueError:
            return 0.0
        return timestamp.timestamp()

    @staticmethod
    def _now_timestamp() -> float:
        return datetime.datetime.now(datetime.timezone.utc).timestamp()
