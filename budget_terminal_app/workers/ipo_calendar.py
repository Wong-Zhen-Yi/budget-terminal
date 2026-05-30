from __future__ import annotations

from bs4 import BeautifulSoup

from ..dependencies import *
from ..paths import user_data_path

IPO_CALENDAR_CACHE_TTL_SECONDS = 24 * 60 * 60
IPO_CALENDAR_SOURCE_NAME = 'StockAnalysis IPO Calendar'
IPO_CALENDAR_SOURCE_URL = 'https://stockanalysis.com/ipos/calendar/'
IPO_YFINANCE_SOURCE_NAME = 'yfinance IPO Calendar'
IPO_YFINANCE_SOURCE_URL = 'https://finance.yahoo.com/calendar/ipo'
IPO_COMPLETED_SOURCE_NAME = 'StockAnalysis Completed IPOs'
IPO_CALENDAR_CACHE_DIR = 'ipo_calendar_cache'
IPO_CALENDAR_CACHE_FILE = 'upcoming_us.json'
_HTTP_TIMEOUT_SECONDS = 20
_YFINANCE_IPO_PAGE_SIZE = 100
_YFINANCE_IPO_MAX_PAGES = 20
_HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BudgetTerminal/1.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


def ipo_calendar_cache_path() -> Path:
    """Return the local cache file used for upcoming IPO rows."""
    return user_data_path(IPO_CALENDAR_CACHE_DIR, IPO_CALENDAR_CACHE_FILE)


def completed_ipo_source_url(year: int | None = None) -> str:
    """Return the StockAnalysis current-year completed IPO source URL."""
    target_year = int(year or datetime.date.today().year)
    return f'https://stockanalysis.com/ipos/{target_year}/'


def completed_ipo_cache_path(year: int | None = None) -> Path:
    """Return the local cache file used for completed IPO rows."""
    target_year = int(year or datetime.date.today().year)
    return user_data_path(IPO_CALENDAR_CACHE_DIR, f'completed_us_{target_year}.json')


class IpoCalendarWorker(QObject):
    """Fetch and cache upcoming US IPO calendar rows."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, *, force: bool = False) -> None:
        super().__init__()
        self.force = bool(force)

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch(force=self.force))
        except Exception as ex:
            logger.error('IpoCalendarWorker error: %s', ex)
            self.error.emit(str(ex))

    @classmethod
    def load_cached_payload(cls, *, allow_stale: bool = True) -> dict[str, Any] | None:
        path = ipo_calendar_cache_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('IPO calendar cache read error: %s', exc)
            return None
        if not isinstance(payload, dict):
            return None
        fetched_at = str(payload.get('fetched_at') or '').strip()
        rows = cls._normalize_cached_rows(payload.get('rows'))
        if not fetched_at and not rows:
            return None
        age_seconds = cls._cache_age_seconds(fetched_at)
        if not allow_stale and age_seconds is not None and age_seconds > IPO_CALENDAR_CACHE_TTL_SECONDS:
            return None
        return {
            'rows': rows,
            'source': str(payload.get('source') or IPO_CALENDAR_SOURCE_NAME),
            'source_url': str(payload.get('source_url') or IPO_CALENDAR_SOURCE_URL),
            'fetched_at': fetched_at,
            'from_cache': True,
            'cache_age_seconds': age_seconds,
            'estimated_dates': True,
        }

    @classmethod
    def save_cached_payload(cls, payload: dict[str, Any]) -> None:
        cache_payload = {
            'source': str(payload.get('source') or IPO_CALENDAR_SOURCE_NAME),
            'source_url': str(payload.get('source_url') or IPO_CALENDAR_SOURCE_URL),
            'fetched_at': str(payload.get('fetched_at') or datetime.datetime.now().isoformat(timespec='seconds')),
            'rows': cls._normalize_cached_rows(payload.get('rows')),
        }
        path = ipo_calendar_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            logger.warning('IPO calendar cache write error: %s', exc)

    @classmethod
    def fetch(cls, *, force: bool = False) -> dict[str, Any]:
        if not force:
            cached = cls.load_cached_payload(allow_stale=False)
            if cached is not None:
                return cached
        try:
            live_payload = cls.fetch_live_payload()
        except Exception as exc:
            cached = cls.load_cached_payload(allow_stale=True)
            if cached is not None and cached.get('rows'):
                cached['stale'] = True
                cached['warning'] = str(exc)
                return cached
            raise
        payload = {
            'rows': live_payload.get('rows') or [],
            'source': str(live_payload.get('source') or IPO_CALENDAR_SOURCE_NAME),
            'source_url': str(live_payload.get('source_url') or IPO_CALENDAR_SOURCE_URL),
            'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'from_cache': False,
            'cache_age_seconds': 0.0,
            'estimated_dates': True,
        }
        cls.save_cached_payload(payload)
        return payload

    @classmethod
    def fetch_live_rows(cls) -> list[dict[str, Any]]:
        return list(cls.fetch_live_payload().get('rows') or [])

    @classmethod
    def fetch_live_payload(cls) -> dict[str, Any]:
        try:
            return {
                'rows': cls._fetch_stockanalysis_rows(),
                'source': IPO_CALENDAR_SOURCE_NAME,
                'source_url': IPO_CALENDAR_SOURCE_URL,
            }
        except Exception as exc:
            logger.info('StockAnalysis IPO calendar fetch failed; trying yfinance fallback: %s', exc)
        today = datetime.date.today()
        return {
            'rows': cls._fetch_yfinance_rows(today, cls._upcoming_end_date(today), completed=False),
            'source': IPO_YFINANCE_SOURCE_NAME,
            'source_url': IPO_YFINANCE_SOURCE_URL,
        }

    @classmethod
    def _fetch_stockanalysis_rows(cls) -> list[dict[str, Any]]:
        response = requests.get(
            IPO_CALENDAR_SOURCE_URL,
            headers=_HTTP_HEADERS,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return cls.parse_html(response.text, today=datetime.date.today())

    @classmethod
    def _fetch_yfinance_rows(
        cls,
        start_date: datetime.date,
        end_date: datetime.date,
        *,
        completed: bool,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_pages: set[tuple[tuple[str, str, str], ...]] = set()
        calendar = yf.Calendars(start=start_date, end=end_date)
        for page in range(_YFINANCE_IPO_MAX_PAGES):
            offset = page * _YFINANCE_IPO_PAGE_SIZE
            frame = calendar.get_ipo_info_calendar(
                limit=_YFINANCE_IPO_PAGE_SIZE,
                offset=offset,
                force=page > 0,
            )
            page_rows = cls.parse_yfinance_frame(
                frame,
                start_date=start_date,
                end_date=end_date,
                completed=completed,
            )
            page_key = tuple(
                (
                    str(row.get('date') or ''),
                    str(row.get('symbol') or ''),
                    str(row.get('company') or ''),
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
            if row_count < _YFINANCE_IPO_PAGE_SIZE:
                break
        if completed:
            return CompletedIpoWorker._dedupe_rows(rows)
        return cls._dedupe_rows(rows)

    @classmethod
    def parse_yfinance_frame(
        cls,
        frame: Any,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        completed: bool = False,
    ) -> list[dict[str, Any]]:
        if frame is None or not hasattr(frame, 'iterrows'):
            return []
        rows: list[dict[str, Any]] = []
        for index, raw_row in frame.iterrows():
            symbol = cls._clean_yfinance_symbol(index)
            row_get = raw_row.get if hasattr(raw_row, 'get') else lambda key, default=None: default
            ipo_date = cls._parse_date(row_get('Date'))
            if ipo_date is None or ipo_date < start_date or ipo_date > end_date:
                continue
            company = cls._clean_yfinance_value(row_get('Company'))
            if not symbol and not company:
                continue
            price_text = cls._format_yfinance_price_range(raw_row)
            base_row = {
                'date': ipo_date.isoformat(),
                'date_display': cls._format_date(ipo_date),
                'symbol': symbol or '--',
                'company': company or '--',
            }
            if completed:
                rows.append({
                    **base_row,
                    'ipo_price': price_text,
                    'current_price': '--',
                    'return': '--',
                })
                continue
            rows.append({
                **base_row,
                'exchange': cls._clean_yfinance_value(row_get('Exchange')) or '--',
                'price_range': price_text,
                'shares_offered': cls._format_yfinance_quantity(row_get('Shares')),
                'deal_size': '--',
                'market_cap': '--',
                'revenue': '--',
            })
        if completed:
            return CompletedIpoWorker._dedupe_rows(rows)
        return cls._dedupe_rows(rows)

    @classmethod
    def parse_html(cls, html: Any, *, today: datetime.date | None = None) -> list[dict[str, Any]]:
        today = today or datetime.date.today()
        end_date = cls._upcoming_end_date(today)
        soup = BeautifulSoup(str(html or ''), 'html.parser')
        rows: list[dict[str, Any]] = []
        for table in soup.find_all('table'):
            headers = [cls._clean_text(cell.get_text(' ', strip=True)) for cell in table.find_all('th')]
            if not headers or 'IPO Date' not in headers or 'Symbol' not in headers:
                continue
            for tr in table.find_all('tr'):
                cells = tr.find_all('td')
                if not cells:
                    continue
                row = cls._row_from_cells(headers, cells)
                if not row:
                    continue
                ipo_date = cls._parse_date(row.get('date_display'))
                if ipo_date is None or ipo_date < today or ipo_date > end_date:
                    continue
                row['date'] = ipo_date.isoformat()
                rows.append(row)
        return cls._dedupe_rows(rows)

    @classmethod
    def _row_from_cells(cls, headers: list[str], cells: list[Any]) -> dict[str, Any] | None:
        values = [cls._clean_text(cell.get_text(' ', strip=True)) for cell in cells]
        by_header = {headers[index]: values[index] for index in range(min(len(headers), len(values)))}
        date_display = by_header.get('IPO Date', '')
        symbol = by_header.get('Symbol', '').upper().strip()
        company = by_header.get('Company Name', '').strip()
        if not date_display or not (symbol or company):
            return None
        return {
            'date': '',
            'date_display': date_display,
            'symbol': symbol or '--',
            'company': company or '--',
            'exchange': by_header.get('Exchange', '').strip() or '--',
            'price_range': by_header.get('Price Range', '').strip() or '--',
            'shares_offered': by_header.get('Shares Offered', '').strip() or '--',
            'deal_size': by_header.get('Deal Size', '').strip() or '--',
            'market_cap': by_header.get('Market Cap', '').strip() or '--',
            'revenue': by_header.get('Revenue', '').strip() or '--',
        }

    @classmethod
    def _dedupe_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in sorted(rows, key=lambda item: (str(item.get('date') or ''), str(item.get('symbol') or ''), str(item.get('company') or ''))):
            key = (
                str(row.get('date') or ''),
                str(row.get('symbol') or '').upper(),
                str(row.get('company') or '').casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    @classmethod
    def _normalize_cached_rows(cls, raw_rows: Any) -> list[dict[str, Any]]:
        rows = []
        if not isinstance(raw_rows, list):
            return rows
        fields = (
            'date',
            'date_display',
            'symbol',
            'company',
            'exchange',
            'price_range',
            'shares_offered',
            'deal_size',
            'market_cap',
            'revenue',
        )
        today = datetime.date.today()
        end_date = cls._upcoming_end_date(today)
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            row = {field: str(raw_row.get(field) or '').strip() for field in fields}
            ipo_date = cls._parse_date(row.get('date') or row.get('date_display'))
            if ipo_date is None or ipo_date < today or ipo_date > end_date:
                continue
            row['date'] = ipo_date.isoformat()
            row['date_display'] = row.get('date_display') or cls._format_date(ipo_date)
            row['symbol'] = row.get('symbol', '').upper().strip() or '--'
            row['company'] = row.get('company') or '--'
            for field in fields[4:]:
                row[field] = row.get(field) or '--'
            rows.append(row)
        return cls._dedupe_rows(rows)

    @staticmethod
    def _upcoming_end_date(today: datetime.date) -> datetime.date:
        return datetime.date(today.year, 12, 31)

    @classmethod
    def _format_yfinance_price_range(cls, row: Any) -> str:
        row_get = row.get if hasattr(row, 'get') else lambda key, default=None: default
        low = cls._clean_yfinance_value(row_get('Price From'))
        high = cls._clean_yfinance_value(row_get('Price To'))
        if low or high:
            return cls._format_price_range(low, high)
        price = cls._clean_yfinance_value(row_get('Price'))
        if not price:
            return '--'
        numeric = cls._to_float(str(price).replace('$', '').replace(',', ''))
        return cls._format_price(numeric) if numeric is not None else price

    @classmethod
    def _format_yfinance_quantity(cls, value: Any) -> str:
        if cls._is_missing_value(value):
            return '--'
        numeric = cls._to_float(value)
        if numeric is not None:
            return f'{numeric:,.0f}'
        text = cls._clean_yfinance_value(value)
        return text or '--'

    @classmethod
    def _clean_yfinance_value(cls, value: Any) -> str:
        if cls._is_missing_value(value):
            return ''
        return cls._clean_text(value)

    @classmethod
    def _clean_yfinance_symbol(cls, value: Any) -> str:
        if isinstance(value, tuple):
            value = value[0] if value else ''
        return cls._clean_yfinance_value(value).upper()

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
    def _parse_date(value: Any) -> datetime.date | None:
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            pass
        for fmt in ('%b %d, %Y', '%B %d, %Y', '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _format_date(value: datetime.date) -> str:
        return value.strftime('%b %d, %Y')

    @classmethod
    def _format_price_range(cls, low: Any, high: Any) -> str:
        low_value = cls._to_float(low)
        high_value = cls._to_float(high)
        if low_value is None and high_value is None:
            return '--'
        if low_value is None:
            return cls._format_price(high_value)
        if high_value is None or abs(high_value - low_value) < 0.005:
            return cls._format_price(low_value)
        return f'{cls._format_price(low_value)} - {cls._format_price(high_value)}'

    @staticmethod
    def _format_price(value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return '--'
        if not math.isfinite(numeric) or numeric <= 0:
            return '--'
        return f'${numeric:,.2f}'

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            numeric = float(value)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) and numeric > 0 else None

    @staticmethod
    def _clean_text(value: Any) -> str:
        return ' '.join(str(value or '').replace('\xa0', ' ').split()).strip()


class CompletedIpoWorker(QObject):
    """Fetch and cache completed US IPO rows for the current year."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, *, force: bool = False, year: int | None = None) -> None:
        super().__init__()
        self.force = bool(force)
        self.year = int(year or datetime.date.today().year)

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch(force=self.force, year=self.year))
        except Exception as ex:
            logger.error('CompletedIpoWorker error: %s', ex)
            self.error.emit(str(ex))

    @classmethod
    def load_cached_payload(cls, *, year: int | None = None, allow_stale: bool = True) -> dict[str, Any] | None:
        target_year = int(year or datetime.date.today().year)
        path = completed_ipo_cache_path(target_year)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('Completed IPO cache read error: %s', exc)
            return None
        if not isinstance(payload, dict):
            return None
        fetched_at = str(payload.get('fetched_at') or '').strip()
        rows = cls._normalize_cached_rows(payload.get('rows'), year=target_year)
        if not fetched_at and not rows:
            return None
        age_seconds = IpoCalendarWorker._cache_age_seconds(fetched_at)
        if not allow_stale and age_seconds is not None and age_seconds > IPO_CALENDAR_CACHE_TTL_SECONDS:
            return None
        source_url = str(payload.get('source_url') or completed_ipo_source_url(target_year))
        return {
            'rows': rows,
            'source': str(payload.get('source') or IPO_COMPLETED_SOURCE_NAME),
            'source_url': source_url,
            'fetched_at': fetched_at,
            'from_cache': True,
            'cache_age_seconds': age_seconds,
            'year': target_year,
        }

    @classmethod
    def save_cached_payload(cls, payload: dict[str, Any], *, year: int | None = None) -> None:
        target_year = int(year or payload.get('year') or datetime.date.today().year)
        source_url = str(payload.get('source_url') or completed_ipo_source_url(target_year))
        cache_payload = {
            'source': str(payload.get('source') or IPO_COMPLETED_SOURCE_NAME),
            'source_url': source_url,
            'fetched_at': str(payload.get('fetched_at') or datetime.datetime.now().isoformat(timespec='seconds')),
            'year': target_year,
            'rows': cls._normalize_cached_rows(payload.get('rows'), year=target_year),
        }
        path = completed_ipo_cache_path(target_year)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            logger.warning('Completed IPO cache write error: %s', exc)

    @classmethod
    def fetch(cls, *, force: bool = False, year: int | None = None) -> dict[str, Any]:
        target_year = int(year or datetime.date.today().year)
        if not force:
            cached = cls.load_cached_payload(year=target_year, allow_stale=False)
            if cached is not None:
                return cached
        try:
            live_payload = cls.fetch_live_payload(year=target_year)
        except Exception as exc:
            cached = cls.load_cached_payload(year=target_year, allow_stale=True)
            if cached is not None:
                cached['stale'] = True
                cached['warning'] = str(exc)
                return cached
            raise
        payload = {
            'rows': live_payload.get('rows') or [],
            'source': str(live_payload.get('source') or IPO_COMPLETED_SOURCE_NAME),
            'source_url': str(live_payload.get('source_url') or completed_ipo_source_url(target_year)),
            'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'from_cache': False,
            'cache_age_seconds': 0.0,
            'year': target_year,
        }
        cls.save_cached_payload(payload, year=target_year)
        return payload

    @classmethod
    def fetch_live_payload(cls, *, year: int | None = None) -> dict[str, Any]:
        target_year = int(year or datetime.date.today().year)
        try:
            return {
                'rows': cls._fetch_stockanalysis_rows(target_year),
                'source': IPO_COMPLETED_SOURCE_NAME,
                'source_url': completed_ipo_source_url(target_year),
                'year': target_year,
            }
        except Exception as exc:
            logger.info('StockAnalysis completed IPO fetch failed; trying yfinance fallback: %s', exc)
        start_date = datetime.date(target_year, 1, 1)
        end_date = datetime.date.today() if target_year == datetime.date.today().year else datetime.date(target_year, 12, 31)
        return {
            'rows': IpoCalendarWorker._fetch_yfinance_rows(start_date, end_date, completed=True),
            'source': IPO_YFINANCE_SOURCE_NAME,
            'source_url': IPO_YFINANCE_SOURCE_URL,
            'year': target_year,
        }

    @classmethod
    def _fetch_stockanalysis_rows(cls, year: int) -> list[dict[str, Any]]:
        response = requests.get(
            completed_ipo_source_url(year),
            headers=_HTTP_HEADERS,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return cls.parse_html(response.text, today=datetime.date.today(), year=year)

    @classmethod
    def parse_html(
        cls,
        html: Any,
        *,
        today: datetime.date | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        today = today or datetime.date.today()
        target_year = int(year or today.year)
        start_date = datetime.date(target_year, 1, 1)
        end_date = today if target_year == today.year else datetime.date(target_year, 12, 31)
        soup = BeautifulSoup(str(html or ''), 'html.parser')
        rows: list[dict[str, Any]] = []
        for table in soup.find_all('table'):
            headers = [IpoCalendarWorker._clean_text(cell.get_text(' ', strip=True)) for cell in table.find_all('th')]
            if not headers or 'IPO Date' not in headers or 'Symbol' not in headers or 'IPO Price' not in headers:
                continue
            for tr in table.find_all('tr'):
                cells = tr.find_all('td')
                if not cells:
                    continue
                row = cls._row_from_cells(headers, cells)
                if not row:
                    continue
                ipo_date = IpoCalendarWorker._parse_date(row.get('date_display'))
                if ipo_date is None or ipo_date < start_date or ipo_date > end_date:
                    continue
                row['date'] = ipo_date.isoformat()
                rows.append(row)
        return cls._dedupe_rows(rows)

    @classmethod
    def _row_from_cells(cls, headers: list[str], cells: list[Any]) -> dict[str, Any] | None:
        values = [IpoCalendarWorker._clean_text(cell.get_text(' ', strip=True)) for cell in cells]
        by_header = {headers[index]: values[index] for index in range(min(len(headers), len(values)))}
        date_display = by_header.get('IPO Date', '')
        symbol = by_header.get('Symbol', '').upper().strip()
        company = by_header.get('Company Name', by_header.get('Company', '')).strip()
        if not date_display or not (symbol or company):
            return None
        return {
            'date': '',
            'date_display': date_display,
            'symbol': symbol or '--',
            'company': company or '--',
            'ipo_price': by_header.get('IPO Price', '').strip() or '--',
            'current_price': by_header.get('Current', '').strip() or '--',
            'return': by_header.get('Return', '').strip() or '--',
        }

    @classmethod
    def _dedupe_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in sorted(
            rows,
            key=lambda item: (str(item.get('date') or ''), str(item.get('symbol') or ''), str(item.get('company') or '')),
            reverse=True,
        ):
            key = (
                str(row.get('date') or ''),
                str(row.get('symbol') or '').upper(),
                str(row.get('company') or '').casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    @classmethod
    def _normalize_cached_rows(cls, raw_rows: Any, *, year: int | None = None) -> list[dict[str, Any]]:
        rows = []
        if not isinstance(raw_rows, list):
            return rows
        target_year = int(year or datetime.date.today().year)
        start_date = datetime.date(target_year, 1, 1)
        today = datetime.date.today()
        end_date = today if target_year == today.year else datetime.date(target_year, 12, 31)
        fields = (
            'date',
            'date_display',
            'symbol',
            'company',
            'ipo_price',
            'current_price',
            'return',
        )
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            row = {field: str(raw_row.get(field) or '').strip() for field in fields}
            ipo_date = IpoCalendarWorker._parse_date(row.get('date') or row.get('date_display'))
            if ipo_date is None or ipo_date < start_date or ipo_date > end_date:
                continue
            row['date'] = ipo_date.isoformat()
            row['date_display'] = row.get('date_display') or IpoCalendarWorker._format_date(ipo_date)
            row['symbol'] = row.get('symbol', '').upper().strip() or '--'
            row['company'] = row.get('company') or '--'
            for field in fields[4:]:
                row[field] = row.get(field) or '--'
            rows.append(row)
        return cls._dedupe_rows(rows)
