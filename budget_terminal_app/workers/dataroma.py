from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from ..dependencies import *
from ..paths import user_data_path


DATAROMA_BASE_URL = 'https://www.dataroma.com'
DATAROMA_MOBILE_BASE_URL = f'{DATAROMA_BASE_URL}/m'
DATAROMA_SOURCE_NAME = 'DATAROMA'
DATAROMA_CACHE_DIR = 'dataroma_cache'
DATAROMA_OVERVIEW_CACHE_TTL_SECONDS = 4 * 60 * 60
DATAROMA_DETAIL_CACHE_TTL_SECONDS = 6 * 60 * 60
DATAROMA_INSIDER_CACHE_TTL_SECONDS = 30 * 60
_HTTP_TIMEOUT_SECONDS = 24
_HTTP_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
}
_TIMEFRAME_VALUES = {'d', 'w', 'm', 'q', 'h', 'y', 'y2'}


def _clean_text(value: Any) -> str:
    text = str(value or '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def _cache_path(name: str) -> Path:
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(name or '').strip()) or 'payload'
    return user_data_path(DATAROMA_CACHE_DIR, f'{safe}.json')


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec='seconds')


def _cache_age_seconds(fetched_at: Any) -> float | None:
    try:
        parsed = datetime.datetime.fromisoformat(str(fetched_at or ''))
    except Exception:
        return None
    return max((datetime.datetime.now() - parsed).total_seconds(), 0.0)


def _manager_id_from_href(href: Any) -> str:
    query = parse_qs(urlparse(str(href or '')).query)
    return str((query.get('m') or [''])[0] or '').strip()


def _symbol_from_href(href: Any) -> str:
    query = parse_qs(urlparse(str(href or '')).query)
    return str((query.get('sym') or [''])[0] or '').upper().strip()


def _absolute_url(href: Any) -> str:
    return urljoin(DATAROMA_BASE_URL, str(href or '').strip())


def _split_symbol_name(value: Any) -> tuple[str, str]:
    text = _clean_text(value)
    if ' - ' in text:
        symbol, name = text.split(' - ', 1)
        return symbol.strip().upper(), name.strip()
    parts = text.split(' ', 1)
    if parts and re.fullmatch(r'[A-Z0-9.:-]+', parts[0] or ''):
        return parts[0].strip().upper(), (parts[1].strip() if len(parts) > 1 else '')
    return '', text


def _row_cells(row: Any) -> list[str]:
    return [_clean_text(cell.get_text(' ', strip=True)) for cell in row.find_all(['td', 'th'])]


class DataromaWorker(QObject):
    """Fetch and cache DATAROMA page payloads for the desktop DATAROMA page."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, facet: str, *, force: bool = False, **params: Any) -> None:
        super().__init__()
        self.facet = str(facet or '').strip().lower()
        self.force = bool(force)
        self.params = dict(params)

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch(self.facet, force=self.force, **self.params))
        except Exception as ex:
            logger.error('DataromaWorker error: %s', ex)
            self.error.emit(str(ex))

    @classmethod
    def fetch(cls, facet: str, *, force: bool = False, **params: Any) -> dict[str, Any]:
        facet_key = str(facet or '').strip().lower()
        if facet_key == 'overview':
            return cls.fetch_overview(force=force)
        if facet_key == 'ticker':
            return cls.fetch_ticker(str(params.get('symbol') or ''), force=force)
        if facet_key == 'manager':
            return cls.fetch_manager(str(params.get('manager_id') or ''), force=force)
        if facet_key == 'insider':
            return cls.fetch_insider(
                timeframe=str(params.get('timeframe') or 'd'),
                trade_type=str(params.get('trade_type') or ''),
                min_amount=params.get('min_amount'),
                symbols=str(params.get('symbols') or ''),
                ten_percent=bool(params.get('ten_percent')),
                preferred=bool(params.get('preferred')),
                force=force,
            )
        raise ValueError(f'Unsupported DATAROMA facet: {facet}')

    @classmethod
    def fetch_overview(cls, *, force: bool = False) -> dict[str, Any]:
        return cls._fetch_with_cache(
            'overview',
            DATAROMA_OVERVIEW_CACHE_TTL_SECONDS,
            force,
            lambda: cls._fetch_overview_live(),
        )

    @classmethod
    def fetch_ticker(cls, symbol: str, *, force: bool = False) -> dict[str, Any]:
        clean_symbol = re.sub(r'[^A-Za-z0-9.-]+', '', str(symbol or '').upper().strip())
        if not clean_symbol:
            raise ValueError('Enter a ticker symbol.')
        return cls._fetch_with_cache(
            f'ticker_{clean_symbol}',
            DATAROMA_DETAIL_CACHE_TTL_SECONDS,
            force,
            lambda: cls._fetch_ticker_live(clean_symbol),
        )

    @classmethod
    def fetch_manager(cls, manager_id: str, *, force: bool = False) -> dict[str, Any]:
        clean_id = re.sub(r'[^A-Za-z0-9_.-]+', '', str(manager_id or '').strip())
        if not clean_id:
            raise ValueError('Choose a DATAROMA superinvestor.')
        return cls._fetch_with_cache(
            f'manager_{clean_id}',
            DATAROMA_DETAIL_CACHE_TTL_SECONDS,
            force,
            lambda: cls._fetch_manager_live(clean_id),
        )

    @classmethod
    def fetch_insider(
        cls,
        *,
        timeframe: str = 'd',
        trade_type: str = '',
        min_amount: Any = None,
        symbols: str = '',
        ten_percent: bool = False,
        preferred: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        clean_timeframe = str(timeframe or 'd').strip().lower()
        if clean_timeframe not in _TIMEFRAME_VALUES:
            clean_timeframe = 'd'
        clean_type = str(trade_type or '').strip().lower()
        clean_symbols = ','.join(
            token.strip().upper()
            for token in re.split(r'[\s,;]+', str(symbols or ''))
            if token.strip()
        )[:120]
        try:
            amount_value = int(float(str(min_amount or 0).replace(',', '').replace('$', '').strip() or 0))
        except Exception:
            amount_value = 0
        amount_value = max(amount_value, 0)
        cache_key = (
            f'insider_{clean_timeframe}_{clean_type or "all"}_{amount_value}_'
            f'{clean_symbols or "all"}_{"10p" if ten_percent else "allowners"}_'
            f'{"preferred" if preferred else "common"}'
        )
        return cls._fetch_with_cache(
            cache_key,
            DATAROMA_INSIDER_CACHE_TTL_SECONDS,
            force,
            lambda: cls._fetch_insider_live(
                timeframe=clean_timeframe,
                trade_type=clean_type,
                min_amount=amount_value,
                symbols=clean_symbols,
                ten_percent=ten_percent,
                preferred=preferred,
            ),
        )

    @classmethod
    def load_cached_payload(cls, cache_key: str, *, allow_stale: bool = True, ttl_seconds: int | None = None) -> dict[str, Any] | None:
        path = _cache_path(cache_key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('DATAROMA cache read error for %s: %s', cache_key, exc)
            return None
        if not isinstance(payload, dict):
            return None
        age_seconds = _cache_age_seconds(payload.get('fetched_at'))
        if not allow_stale and ttl_seconds is not None and age_seconds is not None and age_seconds > ttl_seconds:
            return None
        result = dict(payload)
        result['from_cache'] = True
        result['cache_age_seconds'] = age_seconds
        return result

    @classmethod
    def save_cached_payload(cls, cache_key: str, payload: dict[str, Any]) -> None:
        data = dict(payload)
        data.setdefault('fetched_at', _now_iso())
        try:
            path = _cache_path(cache_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            logger.warning('DATAROMA cache write error for %s: %s', cache_key, exc)

    @classmethod
    def _fetch_with_cache(cls, cache_key: str, ttl_seconds: int, force: bool, live_loader: Any) -> dict[str, Any]:
        if not force:
            cached = cls.load_cached_payload(cache_key, allow_stale=False, ttl_seconds=ttl_seconds)
            if cached is not None:
                return cached
        try:
            payload = live_loader()
        except Exception as exc:
            cached = cls.load_cached_payload(cache_key, allow_stale=True, ttl_seconds=ttl_seconds)
            if cached is not None:
                cached['stale'] = True
                cached['warning'] = str(exc)
                warnings = list(cached.get('warnings') or [])
                warnings.append(f'Live DATAROMA refresh failed; showing cached data. {exc}')
                cached['warnings'] = warnings
                return cached
            raise
        payload = dict(payload)
        payload.setdefault('source', DATAROMA_SOURCE_NAME)
        payload.setdefault('fetched_at', _now_iso())
        payload['from_cache'] = False
        payload['cache_age_seconds'] = 0.0
        cls.save_cached_payload(cache_key, payload)
        return payload

    @classmethod
    def _get_soup(cls, path: str, params: dict[str, Any] | None = None) -> BeautifulSoup:
        url = _absolute_url(path)
        response = requests.get(url, params=params or None, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        text = response.text or ''
        if 'Not Acceptable' in text and 'Mod_Security' in text:
            raise RuntimeError('DATAROMA rejected the request.')
        return BeautifulSoup(text, 'html.parser')

    @classmethod
    def _fetch_overview_live(cls) -> dict[str, Any]:
        warnings: list[str] = []
        home_soup = cls._get_soup('/m/home.php')
        managers_soup = cls._get_soup('/m/managers.php')
        try:
            grand_soup = cls._get_soup('/m/g/portfolio.php')
            grand_summary, grand_rows = cls._parse_grand_portfolio(grand_soup)
        except Exception as exc:
            warnings.append(f'Grand Portfolio fetch failed: {exc}')
            grand_summary, grand_rows = {}, []
        return {
            'facet': 'overview',
            'updates': cls._parse_home_updates(home_soup),
            'latest_insider_buys': cls._parse_home_insider_buys(home_soup),
            'managers': cls._parse_managers(managers_soup),
            'grand_summary': grand_summary,
            'grand_rows': grand_rows,
            'source_urls': {
                'home': f'{DATAROMA_MOBILE_BASE_URL}/home.php',
                'superinvestors': f'{DATAROMA_MOBILE_BASE_URL}/managers.php',
                'grand_portfolio': f'{DATAROMA_MOBILE_BASE_URL}/g/portfolio.php',
                'help_notes': f'{DATAROMA_MOBILE_BASE_URL}/inc/help_notes.php',
                'terms': f'{DATAROMA_MOBILE_BASE_URL}/inc/tos.php',
            },
            'warnings': warnings,
            'fetched_at': _now_iso(),
        }

    @classmethod
    def _fetch_ticker_live(cls, symbol: str) -> dict[str, Any]:
        source_url = f'{DATAROMA_MOBILE_BASE_URL}/stock.php?{urlencode({"sym": symbol})}'
        soup = cls._get_soup('/m/stock.php', {'sym': symbol})
        company, parsed_symbol = cls._parse_stock_title(soup, symbol)
        stats, sector = cls._parse_stock_stats(soup)
        ownership_rows = cls._parse_stock_ownership_rows(soup)
        return {
            'facet': 'ticker',
            'symbol': parsed_symbol or symbol,
            'company': company,
            'sector': sector,
            'stats': stats,
            'ownership_rows': ownership_rows,
            'insider_summary': cls._parse_stock_insider_summary(soup),
            'source_urls': cls._parse_menu_source_urls(soup, fallback={'ownership': source_url}),
            'warnings': [],
            'fetched_at': _now_iso(),
        }

    @classmethod
    def _fetch_manager_live(cls, manager_id: str) -> dict[str, Any]:
        source_url = f'{DATAROMA_MOBILE_BASE_URL}/holdings.php?{urlencode({"m": manager_id})}'
        soup = cls._get_soup('/m/holdings.php', {'m': manager_id})
        meta = cls._parse_manager_meta(soup)
        return {
            'facet': 'manager',
            'manager_id': manager_id,
            'manager_name': meta.get('manager_name') or manager_id,
            'period': meta.get('period', ''),
            'portfolio_date': meta.get('portfolio_date', ''),
            'portfolio_value': meta.get('portfolio_value', ''),
            'stock_count': meta.get('stock_count', ''),
            'holdings': cls._parse_manager_holdings(soup),
            'sector_rows': cls._parse_manager_sector_rows(soup),
            'articles': cls._parse_manager_articles(soup),
            'source_urls': cls._parse_menu_source_urls(soup, fallback={'holdings': source_url}),
            'warnings': [],
            'fetched_at': _now_iso(),
        }

    @classmethod
    def _fetch_insider_live(
        cls,
        *,
        timeframe: str,
        trade_type: str,
        min_amount: int,
        symbols: str,
        ten_percent: bool,
        preferred: bool,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            't': timeframe,
            'am': str(int(min_amount or 0)),
            'sym': symbols,
            'o': 'fd',
            'd': 'd',
        }
        if trade_type == 'purchases':
            params['po'] = '1'
        elif trade_type == 'sales':
            params['so'] = '1'
        if ten_percent:
            params['tp'] = '1'
        if preferred:
            params['s'] = 'p'
        soup = cls._get_soup('/m/ins/ins.php', params)
        source_url = f'{DATAROMA_MOBILE_BASE_URL}/ins/ins.php?{urlencode(params)}'
        summary, transactions = cls._parse_insider_page(soup)
        return {
            'facet': 'insider',
            'timeframe': timeframe,
            'filters': {
                'trade_type': trade_type or 'all',
                'min_amount': int(min_amount or 0),
                'symbols': symbols,
                'ten_percent': bool(ten_percent),
                'preferred': bool(preferred),
            },
            'summary': summary,
            'transactions': transactions,
            'source_urls': {'insider': source_url},
            'warnings': [],
            'fetched_at': _now_iso(),
        }

    @staticmethod
    def _parse_home_updates(soup: BeautifulSoup) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all('a', href=True):
            href = str(link.get('href') or '')
            if 'holdings.php?m=' not in href:
                continue
            text = _clean_text(link.get_text(' ', strip=True))
            if 'Updated' not in text:
                continue
            match = re.match(r'(.+?)\s+Updated\s+(.+)$', text)
            manager = _clean_text(match.group(1) if match else text)
            updated = _clean_text(match.group(2) if match else '')
            manager_id = _manager_id_from_href(href)
            key = manager_id or manager
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({
                'manager': manager,
                'manager_id': manager_id,
                'updated': updated,
                'source_url': _absolute_url(href),
            })
            if len(rows) >= 80:
                break
        return rows

    @staticmethod
    def _parse_home_insider_buys(soup: BeautifulSoup) -> list[dict[str, str]]:
        table = soup.find('table')
        rows: list[dict[str, str]] = []
        if table is None:
            return rows
        for tr in table.find_all('tr')[1:61]:
            cells = _row_cells(tr)
            if len(cells) < 4:
                continue
            symbol, company = _split_symbol_name(cells[1])
            link = tr.find('a', href=True)
            rows.append({
                'date_filed': cells[0],
                'symbol': symbol,
                'company': company,
                'total_value': cells[2],
                'price': cells[3],
                'source_url': _absolute_url(link.get('href')) if link else '',
            })
        return rows

    @staticmethod
    def _parse_managers(soup: BeautifulSoup) -> list[dict[str, Any]]:
        table = soup.select_one('table#grid')
        rows: list[dict[str, Any]] = []
        if table is None:
            return rows
        for tr in table.find_all('tr')[1:]:
            cells = _row_cells(tr)
            links = tr.find_all('a', href=True)
            manager_link = next((link for link in links if 'holdings.php?m=' in str(link.get('href') or '')), None)
            if manager_link is None or len(cells) < 3:
                continue
            top_holdings = []
            for link in links:
                href = str(link.get('href') or '')
                if 'stock.php?sym=' not in href:
                    continue
                symbol = _symbol_from_href(href) or _clean_text(link.get_text(' ', strip=True)).upper()
                if symbol:
                    top_holdings.append(symbol)
            rows.append({
                'manager': _clean_text(manager_link.get_text(' ', strip=True)),
                'manager_id': _manager_id_from_href(manager_link.get('href')),
                'portfolio_value': cells[1] if len(cells) > 1 else '',
                'stock_count': cells[2] if len(cells) > 2 else '',
                'top_holdings': top_holdings[:10],
                'source_url': _absolute_url(manager_link.get('href')),
            })
        return rows

    @staticmethod
    def _parse_grand_portfolio(soup: BeautifulSoup) -> tuple[dict[str, str], list[dict[str, str]]]:
        text = soup.get_text(' ', strip=True)
        summary = {}
        total_match = re.search(r'Total number of stocks:\s*([0-9,]+)', text)
        value_match = re.search(r'Portfolio value:\s*([$0-9.,]+\s*[A-Za-z]*)', text)
        if total_match:
            summary['total_stocks'] = total_match.group(1)
        if value_match:
            summary['portfolio_value'] = value_match.group(1).strip()
        table = soup.select_one('table#grid')
        rows: list[dict[str, str]] = []
        if table is None:
            return summary, rows
        for tr in table.find_all('tr')[1:101]:
            cells = _row_cells(tr)
            if len(cells) < 10:
                continue
            link = tr.find('a', href=True)
            rows.append({
                'symbol': cells[0],
                'stock': cells[1],
                'portfolio_pct': cells[2],
                'ownership_count': cells[3],
                'hold_price': cells[4],
                'max_pct': cells[5],
                'current_price': cells[6],
                'week_52_low': cells[7],
                'above_52_low_pct': cells[8],
                'week_52_high': cells[9],
                'source_url': _absolute_url(link.get('href')) if link else '',
            })
        return summary, rows

    @staticmethod
    def _parse_stock_title(soup: BeautifulSoup, fallback_symbol: str) -> tuple[str, str]:
        tag = soup.select_one('p.st_name') or soup.find('h1')
        title = _clean_text(tag.get_text(' ', strip=True) if tag else '')
        match = re.match(r'(.+?)\s+\(([A-Z0-9.:-]+)\)', title)
        if match:
            return _clean_text(match.group(1)), match.group(2).upper()
        return title, str(fallback_symbol or '').upper()

    @staticmethod
    def _parse_stock_stats(soup: BeautifulSoup) -> tuple[dict[str, str], str]:
        stats: dict[str, str] = {}
        sector = ''
        for tr in soup.find_all('tr')[:30]:
            cells = _row_cells(tr)
            if len(cells) < 2:
                continue
            key = cells[0].replace('*', '').strip(' :')
            value = cells[1]
            if key.lower() == 'sector':
                sector = value
            elif key and value and key.lower() not in {'super investor stats'}:
                stats[key] = value
        return stats, sector

    @staticmethod
    def _parse_stock_insider_summary(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
        summary: dict[str, dict[str, str]] = {}
        for tr in soup.find_all('tr'):
            cells = _row_cells(tr)
            if len(cells) >= 3 and cells[0] in {'Buys', 'Sells'}:
                summary[cells[0].lower()] = {
                    'transactions': cells[1],
                    'total': cells[2],
                }
        return summary

    @staticmethod
    def _parse_stock_ownership_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for tr in soup.find_all('tr'):
            cells = _row_cells(tr)
            if len(cells) < 6 or cells[1] == 'Portfolio Manager':
                continue
            if cells[0] not in {'≡', ''}:
                continue
            links = tr.find_all('a', href=True)
            manager_link = next((link for link in links if 'holdings.php?m=' in str(link.get('href') or '')), None)
            if manager_link is None:
                continue
            rows.append({
                'manager': cells[1],
                'manager_id': _manager_id_from_href(manager_link.get('href')),
                'portfolio_pct': cells[2],
                'activity': cells[3],
                'shares': cells[4],
                'value': cells[5],
                'source_url': _absolute_url(manager_link.get('href')),
            })
        return rows

    @staticmethod
    def _parse_manager_meta(soup: BeautifulSoup) -> dict[str, str]:
        name_tag = soup.select_one('div.f_name')
        meta_tag = soup.select_one('p.p2')
        name = _clean_text(name_tag.get_text(' ', strip=True) if name_tag else '')
        text = _clean_text(meta_tag.get_text(' ', strip=True) if meta_tag else '')
        meta = {'manager_name': name}
        for key, pattern in (
            ('period', r'Period:\s*(.+?)\s+Portfolio date:'),
            ('portfolio_date', r'Portfolio date:\s*(.+?)\s+No\. of stocks:'),
            ('stock_count', r'No\. of stocks:\s*([0-9,]+)'),
            ('portfolio_value', r'Portfolio value:\s*([^|]+)$'),
        ):
            match = re.search(pattern, text)
            if match:
                meta[key] = _clean_text(match.group(1))
        return meta

    @staticmethod
    def _parse_manager_holdings(soup: BeautifulSoup) -> list[dict[str, str]]:
        table = soup.select_one('table#grid')
        rows: list[dict[str, str]] = []
        if table is None:
            return rows
        for tr in table.find_all('tr')[1:]:
            cells = _row_cells(tr)
            if len(cells) < 11:
                continue
            symbol, company = _split_symbol_name(cells[1])
            link = next((link for link in tr.find_all('a', href=True) if 'stock.php?sym=' in str(link.get('href') or '')), None)
            rows.append({
                'symbol': symbol,
                'company': company,
                'portfolio_pct': cells[2],
                'activity': cells[3],
                'shares': cells[4],
                'reported_price': cells[5],
                'value': cells[6],
                'current_price': cells[8] if len(cells) > 8 else '',
                'reported_price_change': cells[9] if len(cells) > 9 else '',
                'week_52_low': cells[10] if len(cells) > 10 else '',
                'week_52_high': cells[11] if len(cells) > 11 else '',
                'source_url': _absolute_url(link.get('href')) if link else '',
            })
        return rows

    @staticmethod
    def _parse_manager_sector_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
        section = soup.select_one('div#sect')
        rows: list[dict[str, str]] = []
        if section is None:
            return rows
        for tr in section.find_all('tr'):
            cells = _row_cells(tr)
            if len(cells) >= 2:
                rows.append({'sector': cells[0], 'portfolio_pct': cells[1]})
        return rows

    @staticmethod
    def _parse_manager_articles(soup: BeautifulSoup) -> list[dict[str, str]]:
        section = soup.select_one('div#rpt')
        rows: list[dict[str, str]] = []
        if section is None:
            return rows
        for div in section.select('div.par')[:50]:
            date = _clean_text((div.find('span') or '').get_text(' ', strip=True))
            link = div.find('a', href=True)
            title = _clean_text(link.get_text(' ', strip=True) if link else div.get_text(' ', strip=True))
            if date and title.startswith(date):
                title = _clean_text(title[len(date):])
            rows.append({
                'date': date,
                'title': title,
                'source_url': _absolute_url(link.get('href')) if link else '',
            })
        return rows

    @staticmethod
    def _parse_menu_source_urls(soup: BeautifulSoup, *, fallback: dict[str, str]) -> dict[str, str]:
        urls = dict(fallback)
        labels = {
            'holdings': 'holdings',
            'ownership': 'ownership',
            'activity': 'activity',
            'buys': 'buys',
            'sells': 'sells',
            'insider': 'insider',
            'sector stats': 'sector_stats',
        }
        for link in soup.find_all('a', href=True):
            label = _clean_text(link.get_text(' ', strip=True)).lower()
            key = labels.get(label)
            if key:
                urls[key] = _absolute_url(link.get('href'))
        return urls

    @staticmethod
    def _parse_insider_page(soup: BeautifulSoup) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
        summary: dict[str, dict[str, str]] = {}
        transactions: list[dict[str, str]] = []
        for tr in soup.find_all('tr'):
            cells = _row_cells(tr)
            if len(cells) >= 3 and cells[0] in {'Buys', 'Sells'}:
                summary[cells[0].lower()] = {
                    'transactions': cells[1],
                    'amount': cells[2],
                }
                continue
            if len(cells) < 11 or cells[0].startswith('Filing'):
                continue
            sec_link = tr.find('a', href=True)
            stock_link = next((link for link in tr.find_all('a', href=True) if 'stock.php?sym=' in str(link.get('href') or '')), None)
            transactions.append({
                'filing': cells[0],
                'symbol': cells[1],
                'security': cells[2],
                'reporting_name': cells[3],
                'relationship': cells[4],
                'transaction_date': cells[5],
                'trade_type': cells[6],
                'shares': cells[7],
                'price': cells[8],
                'amount': cells[9],
                'direct_indirect': cells[10],
                'sec_url': _absolute_url(sec_link.get('href')) if sec_link else '',
                'source_url': _absolute_url(stock_link.get('href')) if stock_link else '',
            })
        return summary, transactions
