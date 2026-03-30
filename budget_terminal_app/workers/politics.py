from __future__ import annotations
import json
import re
import time
from typing import Any
from ..dependencies import *
from ..paths import user_data_path

CAPITOL_TRADES_URL = 'https://www.capitoltrades.com/trades'
CACHE_DIR = 'politics_cache'
CACHE_TTL = 4 * 3600
PAGE_SIZE = 100


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
        next_push = html.find('self.__next_f.push', idx)
        if next_push < 0:
            next_push = len(html)
        chunk = html[push_start:next_push]

        m = re.search(r'push\(\[1,"(.*)', chunk, re.DOTALL)
        if not m:
            return [], 0

        unesc = m.group(1).replace('\\"', '"')
        data_idx = unesc.find('"data":[{')
        if data_idx < 0:
            return [], 0

        arr_start = unesc.index('[', data_idx)
        depth = 0
        arr_end = arr_start
        for i in range(arr_start, len(unesc)):
            if unesc[i] == '[':
                depth += 1
            elif unesc[i] == ']':
                depth -= 1
            if depth == 0:
                arr_end = i + 1
                break

        try:
            raw_trades = json.loads(unesc[arr_start:arr_end])
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

            rows.append({
                'politician': name,
                'chamber': rec.get('chamber', '').title(),
                'party': self._parse_party(pol.get('party', '')),
                'ticker': ticker.upper() if ticker else '',
                'asset_description': iss.get('issuerName', ''),
                'trade_type': self._normalize_type(rec.get('txType', '')),
                'amount': self._format_value(rec.get('value')),
                'transaction_date': (rec.get('txDate') or '')[:10],
                'disclosure_date': (rec.get('pubDate') or '')[:10],
            })
        return rows, len(raw_trades)

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
        if 'sale' in v and 'partial' in v:
            return 'Sale (Partial)'
        if 'sale' in v:
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
