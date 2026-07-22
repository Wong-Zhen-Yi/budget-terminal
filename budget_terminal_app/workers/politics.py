from __future__ import annotations
import json
import re
import time
from typing import Any
from ..constants import SECTOR_DATA, _SECTOR_KEYWORDS
from ..dependencies import *
from ..paths import user_data_path

CAPITOL_TRADES_URL = 'https://www.capitoltrades.com/trades'
CACHE_DIR = 'politics_cache'
CACHE_TTL = 4 * 3600
PAGE_SIZE = 100
_THEME_BY_TICKER = {
    str(ticker).upper(): sector
    for sector, tickers in SECTOR_DATA.items()
    for ticker in tickers
}


class PoliticsWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, page: int = 1, force_refresh: bool = False) -> None:
        super().__init__()
        self.page = page
        self.force_refresh = force_refresh

    def run(self) -> None:
        try:
            cache_path = user_data_path(CACHE_DIR, f'page_{self.page}.json')
            if not self.force_refresh and cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding='utf-8'))
                    cached = self._normalize_cached_result(cached)
                    if time.time() - cached.get('fetched_at', 0) < CACHE_TTL:
                        self.finished.emit(cached)
                        return
                except Exception:
                    pass

            trades, raw_count = self._fetch_page(self.page)
            trades.sort(key=lambda t: t.get('transaction_date', ''), reverse=True)

            top_tickers = self._top_counts(trades, 'ticker', 15)
            top_politicians = self._top_counts(trades, 'politician', 15)

            result = {
                'page': self.page,
                'trades': trades,
                'raw_count': raw_count,
                'top_tickers': top_tickers,
                'top_politicians': top_politicians,
                'fetched_at': time.time(),
            }
            try:
                cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            except Exception as ex:
                logger.warning(f'Politics cache write error: {ex}')

            self.finished.emit(result)
        except Exception as ex:
            logger.error(f'PoliticsWorker error: {ex}')
            self.error.emit(str(ex))

    def _fetch_page(self, page: int) -> tuple[list[dict], int]:
        try:
            url = f'{CAPITOL_TRADES_URL}?page={page}&pageSize={PAGE_SIZE}'
            resp = requests.get(url, timeout=30,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            resp.raise_for_status()
            return self._parse_rsc_trades(resp.text)
        except Exception as ex:
            logger.warning(f'Capitol Trades page {page} fetch error: {ex}')
            return [], 0

    def _parse_rsc_trades(self, html: str) -> tuple[list[dict], int]:
        idx = html.find('_txId')
        if idx < 0:
            return [], 0
        push_start = html.rfind('self.__next_f.push', 0, idx)
        if push_start < 0:
            return [], 0

        payload = self._extract_next_push_payload(html, push_start)
        if not payload:
            return [], 0

        data_idx = payload.find('"data":[{')
        if data_idx < 0:
            return [], 0

        arr_start = payload.index('[', data_idx)
        depth = 0
        arr_end = arr_start
        for i in range(arr_start, len(payload)):
            if payload[i] == '[':
                depth += 1
            elif payload[i] == ']':
                depth -= 1
            if depth == 0:
                arr_end = i + 1
                break

        try:
            raw_trades = json.loads(payload[arr_start:arr_end])
        except json.JSONDecodeError:
            return [], 0

        rows = []
        for rec in raw_trades:
            pol = rec.get('politician', {})
            iss = rec.get('issuer', {})
            raw_ticker = iss.get('issuerTicker', '')
            ticker = raw_ticker.split(':')[0].strip() if raw_ticker else ''
            if not ticker:
                continue

            first = pol.get('firstName', '')
            last = pol.get('lastName', '')
            name = f'{first} {last}'.strip() or 'Unknown'
            asset_description = iss.get('issuerName', '')
            amount_value = self._parse_value(rec.get('value')) or 0

            rows.append({
                'politician': name,
                'chamber': rec.get('chamber', '').title(),
                'party': self._parse_party(pol.get('party', '')),
                'ticker': ticker.upper() if ticker else '',
                'asset_description': asset_description,
                'theme': self._infer_theme(ticker, asset_description),
                'trade_type': self._normalize_type(rec.get('txType', '')),
                'amount': self._format_value(rec.get('value')),
                'amount_value': amount_value,
                'transaction_date': (rec.get('txDate') or '')[:10],
                'disclosure_date': (rec.get('pubDate') or '')[:10],
            })
        return rows, len(raw_trades)

    def _normalize_cached_result(self, cached: dict[str, Any]) -> dict[str, Any]:
        trades = [self._normalize_trade(trade) for trade in cached.get('trades', [])]
        cached['trades'] = trades
        cached['top_tickers'] = self._top_counts(trades, 'ticker', 15)
        cached['top_politicians'] = self._top_counts(trades, 'politician', 15)
        return cached

    def _normalize_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(trade)
        ticker = str(normalized.get('ticker', '') or '').upper().strip()
        asset_description = str(normalized.get('asset_description', '') or '')
        amount_value = self._parse_value(normalized.get('amount_value'))
        if amount_value is None:
            amount_value = self._parse_value(normalized.get('amount'))
        normalized['ticker'] = ticker
        normalized['asset_description'] = asset_description
        normalized['amount_value'] = amount_value or 0
        normalized['trade_type'] = self._normalize_type(str(normalized.get('trade_type', '') or ''))
        normalized['theme'] = str(normalized.get('theme', '') or '').strip() or self._infer_theme(ticker, asset_description)
        return normalized

    @staticmethod
    def _extract_next_push_payload(html: str, push_start: int) -> str:
        chunk = html[push_start:]
        args_start = chunk.find('push(')
        if args_start < 0:
            return ''

        text = chunk[args_start + 5:]
        depth = 0
        in_string = False
        escaped = False
        end = None
        for i, ch in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == '(':
                    depth += 1
                elif ch == ')':
                    if depth == 0:
                        end = i
                        break
                    depth -= 1

        if end is None:
            return ''

        try:
            payload = json.loads(text[:end])
        except json.JSONDecodeError:
            return ''

        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], str):
            return ''
        return payload[1]

    @staticmethod
    def _parse_party(value: str) -> str:
        v = value.strip().lower()
        if v.startswith('d'):
            return 'Democrat'
        if v.startswith('r'):
            return 'Republican'
        if v.startswith('i'):
            return 'Independent'
        return 'Unknown'

    @staticmethod
    def _normalize_type(value: str) -> str:
        v = value.strip().lower()
        if 'purchase' in v or 'buy' in v:
            return 'Purchase'
        if 'partial' in v and ('sale' in v or 'sell' in v):
            return 'Sale (Partial)'
        if 'sale' in v or 'sell' in v:
            return 'Sale (Full)'
        if 'exchange' in v:
            return 'Exchange'
        return value.strip().title() if value.strip() else 'Unknown'

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return ''
        try:
            v = int(value)
            if v >= 1_000_000:
                return f'${v / 1_000_000:.1f}M'
            if v >= 1_000:
                return f'${v / 1_000:.0f}K'
            return f'${v:,}'
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _parse_value(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip().upper()
        if not text:
            return None
        text = text.replace('$', '').replace(',', '')
        multiplier = 1
        if text.endswith('B'):
            multiplier = 1_000_000_000
            text = text[:-1]
        elif text.endswith('M'):
            multiplier = 1_000_000
            text = text[:-1]
        elif text.endswith('K'):
            multiplier = 1_000
            text = text[:-1]
        match = re.search(r'-?\d+(?:\.\d+)?', text)
        if not match:
            return None
        try:
            return int(float(match.group(0)) * multiplier)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _infer_theme(ticker: str, asset_description: str) -> str:
        ticker_key = str(ticker or '').upper().strip()
        if ticker_key in _THEME_BY_TICKER:
            return _THEME_BY_TICKER[ticker_key]
        words = set(re.findall(r'[A-Z0-9]+', str(asset_description or '').upper()))
        theme_hits = []
        for theme, keywords in _SECTOR_KEYWORDS.items():
            hits = len({str(word).upper() for word in keywords} & words)
            if hits > 0:
                theme_hits.append((hits, theme))
        if theme_hits:
            theme_hits.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return theme_hits[0][1]
        return 'Other'

    @staticmethod
    def _top_counts(trades: list[dict], key: str, limit: int) -> list[list]:
        counts: dict[str, int] = {}
        for t in trades:
            val = t.get(key, '')
            if val and val != 'Unknown':
                counts[val] = counts.get(val, 0) + 1
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [[name, count] for name, count in sorted_items[:limit]]


class PoliticsExportWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, pages: int = 5) -> None:
        super().__init__()
        self.pages = pages
        self._worker = PoliticsWorker()

    def run(self) -> None:
        try:
            all_trades: list[dict] = []
            for p in range(1, self.pages + 1):
                self.progress.emit(p)
                trades, _ = self._worker._fetch_page(p)
                if not trades:
                    break
                all_trades.extend(trades)
            all_trades.sort(key=lambda t: t.get('transaction_date', ''), reverse=True)
            self.finished.emit(all_trades)
        except Exception as ex:
            logger.error(f'PoliticsExportWorker error: {ex}')
            self.error.emit(str(ex))
