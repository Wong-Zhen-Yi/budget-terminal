from __future__ import annotations

import copy
import datetime
import hashlib
import random
import time
from concurrent.futures import FIRST_COMPLETED, wait as wait_futures
from typing import Any

from ..dependencies import *


class _RandomStockCancelled(RuntimeError):
    pass


class RandomStockWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(dict)
    partial = pyqtSignal(dict)
    cancelled = pyqtSignal()

    _MIN_MARKET_CAP = 1_000_000_000
    _MIN_AVG_VOLUME = 1_000_000
    _MAX_OPTION_EXPIRIES = 4
    _POOL_FETCH_SIZE = 80
    _CANDIDATE_LIMIT = 30
    _PATTERN_CANDIDATE_LIMIT = 120
    _PATTERN_HISTORY_PERIOD = '1y'
    _ROLL_TOP_COUNT = 12
    _SCAN_CACHE_TTL_SECONDS = 600.0
    _HISTORY_CACHE_TTL_SECONDS = 600.0
    _EVALUATION_CACHE_TTL_SECONDS = 600.0
    _OPTION_EXPIRY_CACHE_TTL_SECONDS = 900.0
    _OPTION_CHAIN_CACHE_TTL_SECONDS = 300.0
    _OPTION_CHAIN_STALE_TTL_SECONDS = 3600.0
    _CACHE_LOCK = threading.RLock()
    _screening_cache: dict[str, tuple[float, dict[str, Any]]] = {}
    _history_cache: dict[str, tuple[float, Any]] = {}
    _evaluation_cache: dict[tuple[str, str, tuple[Any, ...]], tuple[float, tuple[bool, float, list[str], dict[str, Any]]]] = {}
    _option_expiry_cache: dict[str, tuple[float, list[str]]] = {}
    _option_chain_cache: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}
    _nyse_close_cache: dict[str, datetime.time | None] = {}

    def __init__(
        self,
        exclude_symbols: Any = None,
        history_symbols: Any = None,
        target_symbol: Any = '',
        pattern_modes: Any = None,
        request_id: int = 0,
    ) -> None:
        super().__init__()
        self.exclude_symbols = self._normalize_symbol_set(exclude_symbols)
        self.history_symbols = self._normalize_symbol_set(history_symbols)
        self.target_symbol = str(target_symbol or '').upper().strip()
        self.pattern_modes = self._normalize_pattern_modes(pattern_modes)
        self.request_id = int(request_id or 0)
        self._cancel_event = threading.Event()
        self._history_frames: dict[str, Any] = {}
        self._pattern_contexts: dict[int, tuple[tuple[Any, ...], dict[str, Any]]] = {}
        self._active_pattern_signatures: dict[int, tuple[Any, ...]] = {}
        self._fetch_meta: dict[str, Any] = {
            'screen_cache_hit': False,
            'history_cache_hits': 0,
            'history_downloaded': 0,
            'history_retry_count': 0,
            'evaluation_cache_hits': 0,
            'option_expiry_cache_hit': False,
            'option_chain_cache_hits': 0,
        }

    @classmethod
    def clear_caches(cls) -> None:
        """Clear Roll's process-local caches (primarily useful for focused tests)."""
        with cls._CACHE_LOCK:
            cls._screening_cache.clear()
            cls._history_cache.clear()
            cls._evaluation_cache.clear()
            cls._option_expiry_cache.clear()
            cls._option_chain_cache.clear()
            cls._nyse_close_cache.clear()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _raise_if_cancelled(self) -> None:
        if self._is_cancelled():
            raise _RandomStockCancelled()

    def _emit_progress(
        self,
        stage: str,
        message: str,
        *,
        current: int = 0,
        total: int = 0,
    ) -> None:
        self.progress.emit({
            'stage': str(stage),
            'message': str(message),
            'current': max(0, int(current or 0)),
            'total': max(0, int(total or 0)),
            'request_id': self.request_id,
        })

    def _emit_partial(self, section: str, payload: dict[str, Any], *, stage: str) -> None:
        self.partial.emit({
            'section': str(section),
            'payload': copy.deepcopy(dict(payload or {})),
            'stage': str(stage),
            'request_id': self.request_id,
        })

    def _iter_completed_futures(self, futures: Any) -> Any:
        """Yield completed futures while polling cooperative cancellation."""
        pending = set(futures)
        while pending:
            self._raise_if_cancelled()
            completed, pending = wait_futures(
                pending,
                timeout=0.05,
                return_when=FIRST_COMPLETED,
            )
            for future in completed:
                yield future

    def _interruptible_call(self, loader: Any, *, label: str='Yahoo request') -> Any:
        """Run blocking provider work off the Qt worker and poll cancellation."""
        self._raise_if_cancelled()
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def _run() -> None:
            try:
                outcome['value'] = loader()
            except Exception as exc:
                outcome['error'] = exc
            finally:
                completed.set()

        thread = threading.Thread(
            target=_run,
            name=f'roll-provider-{str(label or "request").casefold().replace(" ", "-")}',
            daemon=True,
        )
        thread.start()
        while not completed.wait(0.05):
            self._raise_if_cancelled()
        self._raise_if_cancelled()
        if 'error' in outcome:
            raise outcome['error']
        return outcome.get('value')

    @classmethod
    def _cache_retention(cls, cache: dict[Any, tuple[float, Any]]) -> tuple[float, int]:
        if cache is cls._screening_cache:
            return cls._SCAN_CACHE_TTL_SECONDS, 8
        if cache is cls._history_cache:
            return cls._HISTORY_CACHE_TTL_SECONDS, 1_500
        if cache is cls._evaluation_cache:
            return cls._EVALUATION_CACHE_TTL_SECONDS, 5_000
        if cache is cls._option_expiry_cache:
            return cls._OPTION_EXPIRY_CACHE_TTL_SECONDS, 500
        if cache is cls._option_chain_cache:
            return cls._OPTION_CHAIN_STALE_TTL_SECONDS, 2_000
        return cls._SCAN_CACHE_TTL_SECONDS, 1_000

    @classmethod
    def _prune_cache_locked(cls, cache: dict[Any, tuple[float, Any]], now: float) -> None:
        retention, max_entries = cls._cache_retention(cache)
        expired = [key for key, (created_at, _value) in cache.items() if now - created_at > retention]
        for expired_key in expired:
            cache.pop(expired_key, None)
        overflow = len(cache) - max_entries
        if overflow > 0:
            oldest = sorted(cache.items(), key=lambda item: item[1][0])[:overflow]
            for old_key, _entry in oldest:
                cache.pop(old_key, None)

    @classmethod
    def _cache_get(cls, cache: dict[Any, tuple[float, Any]], key: Any, ttl: float) -> Any:
        now = time.monotonic()
        with cls._CACHE_LOCK:
            entry = cache.get(key)
            if entry is None:
                return None
            created_at, value = entry
            if now - created_at > ttl:
                retention, _max_entries = cls._cache_retention(cache)
                if now - created_at > retention:
                    cache.pop(key, None)
                return None
            return copy.deepcopy(value)

    @classmethod
    def _cache_get_stale(
        cls,
        cache: dict[Any, tuple[float, Any]],
        key: Any,
        *,
        max_age: float | None = None,
    ) -> Any:
        now = time.monotonic()
        with cls._CACHE_LOCK:
            entry = cache.get(key)
            if entry is None:
                return None
            created_at, value = entry
            if max_age is not None and now - created_at > max_age:
                cache.pop(key, None)
                return None
            return copy.deepcopy(value)

    @classmethod
    def _cache_put(cls, cache: dict[Any, tuple[float, Any]], key: Any, value: Any) -> None:
        now = time.monotonic()
        with cls._CACHE_LOCK:
            cls._prune_cache_locked(cache, now)
            cache[key] = (now, copy.deepcopy(value))
            cls._prune_cache_locked(cache, now)

    def _normalize_symbol_set(self, values: Any) -> set[str]:
        if not isinstance(values, (list, tuple, set)):
            return set()
        return {str(value or '').upper().strip() for value in values if str(value or '').strip()}

    def _to_float(self, value: Any) -> float | None:
        try:
            numeric = float(value)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None

    def _normalize_pattern_modes(self, values: Any) -> set[str]:
        if isinstance(values, str):
            raw_values = [values]
        elif isinstance(values, (list, tuple, set)):
            raw_values = list(values)
        else:
            raw_values = []
        allowed = {
            'breakout',
            'consolidation',
            'downtrend',
            'double_bottom',
            'bullish_flag',
            'bullish_rsi_divergence',
        }
        return {str(value or '').strip().casefold() for value in raw_values if str(value or '').strip().casefold() in allowed}

    def _query(self) -> Any:
        return yf.EquityQuery('and', [
            yf.EquityQuery('eq', ['region', 'us']),
            yf.EquityQuery('gt', ['intradaymarketcap', self._MIN_MARKET_CAP]),
            yf.EquityQuery('gt', ['avgdailyvol3m', self._MIN_AVG_VOLUME]),
        ])

    def _screen_total(self, query: Any) -> int:
        response = yf.screen(query, size=1, offset=0, sortField='ticker', sortAsc=True)
        if not isinstance(response, dict):
            return 0
        try:
            return max(int(response.get('total', 0) or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _screen_quotes(self, query: Any, total: int, *, offset: int = 0, size: int = 1, sort_field: str = 'ticker', sort_asc: bool = True) -> list[dict[str, Any]]:
        if total <= 0:
            return []
        offset = max(0, min(int(offset), max(total - 1, 0)))
        response = yf.screen(query, size=max(1, int(size)), offset=offset, sortField=sort_field, sortAsc=sort_asc)
        if not isinstance(response, dict):
            return []
        quotes = response.get('quotes') or []
        if not isinstance(quotes, list):
            return []
        return [dict(quote) for quote in quotes if isinstance(quote, dict)]

    def _screen_quote(self, query: Any, total: int) -> dict[str, Any]:
        quotes = self._screen_quotes(
            query,
            total,
            offset=random.randint(0, max(total - 1, 0)),
            size=1,
            sort_field='ticker',
            sort_asc=True,
        )
        return quotes[0] if quotes else {}

    def _fallback_quote_from_info(self, symbol: str, info: dict[str, Any]) -> dict[str, Any]:
        return {
            'symbol': symbol,
            'shortName': info.get('shortName') or info.get('longName') or symbol,
            'longName': info.get('longName') or info.get('shortName') or symbol,
            'regularMarketPrice': info.get('regularMarketPrice') or info.get('currentPrice'),
            'regularMarketPreviousClose': info.get('previousClose') or info.get('regularMarketPreviousClose'),
            'regularMarketChange': info.get('regularMarketChange'),
            'regularMarketChangePercent': info.get('regularMarketChangePercent'),
            'marketCap': info.get('marketCap'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE'),
            'beta': info.get('beta'),
            'dividendYield': info.get('dividendYield'),
            'averageDailyVolume3Month': info.get('averageVolume'),
            'fiftyTwoWeekLow': info.get('fiftyTwoWeekLow'),
            'fiftyTwoWeekHigh': info.get('fiftyTwoWeekHigh'),
            'fiftyTwoWeekChangePercent': info.get('52WeekChange'),
            'exchange': info.get('exchange') or info.get('fullExchangeName'),
            'fullExchangeName': info.get('fullExchangeName') or info.get('exchange'),
            'currency': info.get('currency'),
            'quoteType': info.get('quoteType'),
        }

    def _fetch_screen_buckets(self, query: Any, total: int) -> dict[str, list[dict[str, Any]]]:
        """Fetch each unique screener slice once, using no more than four workers."""
        offsets = {0}
        if total > self._POOL_FETCH_SIZE:
            max_offset = max(total - self._POOL_FETCH_SIZE, 0)
            offsets.update(random.randint(0, max_offset) for _ in range(3))
        requests = [
            ('liquidity', 'intradaymarketcap', False, 0),
            ('liquidity', 'avgdailyvol3m', False, 0),
            ('momentum', 'percentchange', False, 0),
            ('momentum', 'fiftytwowkpercentchange', False, 0),
            ('loser', 'percentchange', True, 0),
            ('loser', 'fiftytwowkpercentchange', True, 0),
        ]
        for offset in sorted(offsets):
            requests.append(('random', 'ticker', True, offset))

        unique_requests = []
        seen_requests = set()
        for bucket, sort_field, sort_asc, offset in requests:
            request_key = (sort_field, bool(sort_asc), int(offset))
            if request_key in seen_requests:
                continue
            seen_requests.add(request_key)
            unique_requests.append((bucket, sort_field, sort_asc, offset))

        def _load(request: tuple[str, str, bool, int]) -> tuple[str, list[dict[str, Any]]]:
            bucket, sort_field, sort_asc, offset = request
            self._raise_if_cancelled()
            quotes = self._interruptible_call(
                lambda: self._screen_quotes(
                    query,
                    total,
                    offset=offset,
                    size=self._POOL_FETCH_SIZE,
                    sort_field=sort_field,
                    sort_asc=sort_asc,
                ),
                label=f'screen {sort_field}',
            )
            return bucket, quotes

        ordered_results: dict[int, tuple[str, list[dict[str, Any]]]] = {}
        worker_count = min(4, max(1, len(unique_requests)))
        executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix='roll-screen')
        try:
            future_indexes = {
                executor.submit(_load, request): index
                for index, request in enumerate(unique_requests)
            }
            for future in self._iter_completed_futures(future_indexes):
                self._raise_if_cancelled()
                index = future_indexes[future]
                request = unique_requests[index]
                try:
                    ordered_results[index] = future.result()
                except _RandomStockCancelled:
                    raise
                except Exception as exc:
                    logger.info('Roll candidate screen failed for %s: %s', request[1], exc)
        finally:
            cancelled = self._is_cancelled()
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

        buckets: dict[str, list[dict[str, Any]]] = {
            'liquidity': [],
            'momentum': [],
            'loser': [],
            'random': [],
        }
        bucket_slices: dict[str, list[list[dict[str, Any]]]] = {name: [] for name in buckets}
        for index in sorted(ordered_results):
            bucket, quotes = ordered_results[index]
            bucket_slices[bucket].append(quotes)
        for bucket, slices in bucket_slices.items():
            positions = [0] * len(slices)
            seen_symbols = set()
            while slices:
                added = False
                for slice_index, quotes in enumerate(slices):
                    while positions[slice_index] < len(quotes):
                        quote = quotes[positions[slice_index]]
                        positions[slice_index] += 1
                        symbol = str(quote.get('symbol') or '').upper().strip()
                        if not symbol or symbol in seen_symbols or not self._quote_is_screenable(quote):
                            continue
                        seen_symbols.add(symbol)
                        buckets[bucket].append(dict(quote))
                        added = True
                        break
                if not added:
                    break
        return buckets

    def _screening_snapshot(self, query: Any) -> tuple[int, dict[str, list[dict[str, Any]]]]:
        cache_key = 'liquid-us-equities-v2'
        cached = self._cache_get(self._screening_cache, cache_key, self._SCAN_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and int(cached.get('total') or 0) > 0:
            self._fetch_meta['screen_cache_hit'] = True
            return int(cached['total']), dict(cached.get('buckets') or {})
        total = self._interruptible_call(
            lambda: self._screen_total(query),
            label='screen total',
        )
        if total <= 0:
            return 0, {}
        buckets = self._fetch_screen_buckets(query, total)
        if any(list(quotes or []) for quotes in buckets.values()):
            self._cache_put(self._screening_cache, cache_key, {'total': total, 'buckets': buckets})
        return total, buckets

    def _round_robin_screen_quotes(
        self,
        buckets: dict[str, list[dict[str, Any]]],
        limit: int,
    ) -> list[dict[str, Any]]:
        bucket_names = ('liquidity', 'momentum', 'loser', 'random')
        positions = {name: 0 for name in bucket_names}
        selected = []
        seen_symbols = set()
        while len(selected) < limit:
            added = False
            for name in bucket_names:
                quotes = list(buckets.get(name) or [])
                while positions[name] < len(quotes):
                    quote = quotes[positions[name]]
                    positions[name] += 1
                    symbol = str(quote.get('symbol') or '').upper().strip()
                    if not symbol or symbol in seen_symbols:
                        continue
                    seen_symbols.add(symbol)
                    selected.append(quote)
                    added = True
                    break
                if len(selected) >= limit:
                    break
            if not added:
                break
        return selected

    def _build_candidate_pool(
        self,
        query: Any,
        total: int,
        buckets: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        screen_buckets = buckets if isinstance(buckets, dict) else self._fetch_screen_buckets(query, total)
        limit = self._PATTERN_CANDIDATE_LIMIT if self.pattern_modes else self._CANDIDATE_LIMIT
        if self.pattern_modes:
            quotes = self._round_robin_screen_quotes(screen_buckets, limit)
        else:
            by_symbol: dict[str, dict[str, Any]] = {}
            for bucket_name in ('liquidity', 'momentum', 'loser', 'random'):
                for quote in list(screen_buckets.get(bucket_name) or []):
                    symbol = str(quote.get('symbol') or '').upper().strip()
                    if symbol and symbol not in by_symbol:
                        by_symbol[symbol] = quote
            quotes = list(by_symbol.values())

        candidates = [self._candidate_from_quote(quote) for quote in quotes]
        candidates = [candidate for candidate in candidates if candidate]
        if not self.pattern_modes:
            candidates.sort(key=lambda item: item.get('score', 0.0), reverse=True)
        for index, candidate in enumerate(candidates, start=1):
            candidate['rank'] = index
        return candidates[:limit]

    def _quote_is_screenable(self, quote: dict[str, Any]) -> bool:
        symbol = str(quote.get('symbol') or '').upper().strip()
        quote_type = str(quote.get('quoteType') or '').upper().strip()
        price = self._to_float(quote.get('regularMarketPrice') or quote.get('regularMarketPreviousClose'))
        market_cap = self._to_float(quote.get('marketCap'))
        avg_volume = self._to_float(quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'))
        name = quote.get('longName') or quote.get('shortName') or quote.get('displayName')
        return bool(
            symbol
            and quote_type in ('EQUITY', '')
            and name
            and price is not None
            and market_cap is not None
            and avg_volume is not None
        )

    def _candidate_from_quote(self, quote: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(quote.get('symbol') or '').upper().strip()
        if not symbol:
            return None
        score, reasons = self._score_quote(symbol, quote)
        return {
            'symbol': symbol,
            'name': str(quote.get('longName') or quote.get('shortName') or quote.get('displayName') or symbol),
            'sector': str(quote.get('sector') or quote.get('sectorDisp') or 'N/A'),
            'score': round(score, 1),
            'reasons': reasons,
            'day_change_pct': quote.get('regularMarketChangePercent'),
            'fifty_two_week_change_pct': quote.get('fiftyTwoWeekChangePercent'),
            'average_volume': quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'),
            'market_cap': quote.get('marketCap'),
            'quote': quote,
        }

    def _score_quote(self, symbol: str, quote: dict[str, Any]) -> tuple[float, list[str]]:
        score = 0.0
        reasons = []

        market_cap = self._to_float(quote.get('marketCap'))
        if market_cap is not None:
            if market_cap >= 200_000_000_000:
                score += 16
                reasons.append('mega cap')
            elif market_cap >= 10_000_000_000:
                score += 14
                reasons.append('large cap')
            elif market_cap >= 2_000_000_000:
                score += 11
                reasons.append('mid cap')
            else:
                score += 8

        avg_volume = self._to_float(quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'))
        if avg_volume is not None:
            if avg_volume >= 10_000_000:
                score += 18
                reasons.append('very liquid')
            elif avg_volume >= 3_000_000:
                score += 15
                reasons.append('liquid')
            else:
                score += 10

        day_change = self._to_float(quote.get('regularMarketChangePercent'))
        if day_change is not None:
            if day_change >= 3:
                score += 9
                reasons.append('strong day move')
            elif day_change > 0:
                score += 7
                reasons.append('green today')
            elif day_change > -2:
                score += 4
            else:
                score += 1

        year_change = self._to_float(quote.get('fiftyTwoWeekChangePercent'))
        if year_change is not None:
            if year_change >= 40:
                score += 15
                reasons.append('strong 1Y momentum')
            elif year_change >= 10:
                score += 12
                reasons.append('positive 1Y trend')
            elif year_change >= 0:
                score += 8
            elif year_change > -20:
                score += 4

        analyst_rating = str(quote.get('averageAnalystRating') or '').strip()
        if analyst_rating:
            score += 10
            reasons.append(analyst_rating.split(' - ')[-1].lower())
        elif quote.get('epsForward') not in (None, '', 'N/A') or quote.get('forwardPE') not in (None, '', 'N/A'):
            score += 5

        metadata_fields = (
            'longName',
            'shortName',
            'fullExchangeName',
            'currency',
            'trailingPE',
            'forwardPE',
            'fiftyTwoWeekHigh',
            'fiftyTwoWeekLow',
        )
        metadata_count = sum(1 for field in metadata_fields if quote.get(field) not in (None, '', 'N/A'))
        score += min(14, metadata_count * 1.75)
        if metadata_count >= 6:
            reasons.append('complete quote')

        if symbol in self.exclude_symbols:
            score -= 14
        elif symbol in self.history_symbols:
            score -= 7
        else:
            score += 8
            reasons.append('fresh idea')

        return max(0.0, min(100.0, score)), reasons[:4]

    def _select_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {}
        if self.target_symbol:
            target = next((candidate for candidate in candidates if candidate.get('symbol') == self.target_symbol), None)
            if target:
                return target
        fresh_candidates = [candidate for candidate in candidates if candidate.get('symbol') not in self.exclude_symbols and candidate.get('symbol') not in self.history_symbols]
        choice_pool = fresh_candidates or [candidate for candidate in candidates if candidate.get('symbol') not in self.exclude_symbols] or candidates
        top_pool = choice_pool[:self._ROLL_TOP_COUNT]
        if len(top_pool) <= 1:
            return top_pool[0]
        if self.pattern_modes:
            weights = [
                max(1.0, float(candidate.get('pattern_score', 0.0) or 0.0) + float(candidate.get('score', 0.0) or 0.0) * 0.25)
                for candidate in top_pool
            ]
        else:
            weights = [max(1.0, float(candidate.get('score', 0.0) or 0.0)) for candidate in top_pool]
        try:
            return random.choices(top_pool, weights=weights, k=1)[0]
        except Exception:
            return random.choice(top_pool)

    def _candidate_for_target(self, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        candidate = self._candidate_from_quote(quote)
        if candidate is None:
            candidate = {
                'symbol': symbol,
                'name': str(quote.get('longName') or quote.get('shortName') or symbol),
                'sector': 'N/A',
                'score': 0.0,
                'reasons': ['selected candidate'],
                'quote': quote,
            }
        candidate.setdefault('rank', 0)
        return candidate

    def _candidate_reason_text(self, candidate: dict[str, Any]) -> str:
        reasons = [str(reason or '').strip() for reason in list(candidate.get('reasons') or []) if str(reason or '').strip()]
        return ', '.join(reasons) if reasons else 'scored candidate'

    def _download_pattern_history(self, symbols: list[str]) -> Any:
        if not symbols:
            return None
        self._raise_if_cancelled()
        try:
            return yf.download(
                symbols,
                period=self._PATTERN_HISTORY_PERIOD,
                interval='1d',
                group_by='ticker',
                progress=False,
                auto_adjust=False,
                actions=False,
                threads=True,
            )
        except Exception as exc:
            logger.info('Roll pattern history batch failed: %s', exc)
            return None

    def _symbol_history_from_batch(self, batch_data: Any, symbols: list[str], symbol: str) -> Any:
        if batch_data is None or getattr(batch_data, 'empty', True):
            return None
        try:
            if isinstance(batch_data.columns, pd.MultiIndex):
                level_zero = batch_data.columns.get_level_values(0)
                level_one = batch_data.columns.get_level_values(1)
                if symbol in level_zero:
                    return batch_data[symbol].dropna(how='all')
                if symbol in level_one:
                    return batch_data.xs(symbol, axis=1, level=1).dropna(how='all')
                return None
            if len(symbols) == 1:
                return batch_data.dropna(how='all')
        except Exception:
            return None
        return None

    def _normalize_history_frame(self, frame: Any, *, now: Any = None) -> Any:
        """Return canonical adjusted daily OHLCV data for Roll analysis and charts."""
        if frame is None or getattr(frame, 'empty', True):
            return None
        try:
            normalized = frame.copy()
        except Exception:
            return None
        if isinstance(getattr(normalized, 'columns', None), pd.MultiIndex):
            return None
        required = {'Open', 'High', 'Low', 'Close', 'Volume'}
        if not required.issubset(set(normalized.columns)):
            return None
        try:
            normalized = normalized.loc[~normalized.index.duplicated(keep='last')].sort_index()
        except Exception:
            return None
        numeric_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        if 'Adj Close' in normalized.columns:
            numeric_columns.append('Adj Close')
        for column in numeric_columns:
            normalized[column] = pd.to_numeric(normalized[column], errors='coerce')
        if 'Adj Close' in normalized.columns:
            raw_close = normalized['Close'].where(normalized['Close'] != 0)
            adjustment = normalized['Adj Close'] / raw_close
            adjustment = adjustment.where(adjustment > 0, 1.0).replace([math.inf, -math.inf], 1.0).fillna(1.0)
            for column in ('Open', 'High', 'Low', 'Close'):
                normalized[column] = normalized[column] * adjustment
        normalized = normalized[['Open', 'High', 'Low', 'Close', 'Volume']]
        normalized = normalized.replace([math.inf, -math.inf], float('nan')).dropna(how='any')
        if normalized.empty:
            return None

        try:
            now_value = now or datetime.datetime.now(ZoneInfo('America/New_York'))
            if getattr(now_value, 'tzinfo', None) is None:
                now_et = now_value.replace(tzinfo=ZoneInfo('America/New_York'))
            else:
                now_et = now_value.astimezone(ZoneInfo('America/New_York'))
            last_timestamp = pd.Timestamp(normalized.index[-1])
            if last_timestamp.tzinfo is not None:
                last_timestamp = last_timestamp.tz_convert('America/New_York')
            if last_timestamp.date() == now_et.date():
                close_time = self._nyse_close_time(now_et.date())
                if (
                    close_time is not None
                    and now_et.time().replace(tzinfo=None) < close_time
                ):
                    normalized = normalized.iloc[:-1]
        except Exception:
            pass
        return normalized if not normalized.empty else None

    @classmethod
    def _nyse_close_time(cls, session_date: datetime.date) -> datetime.time | None:
        """Return the scheduled NYSE close, including early-close sessions."""
        cache_key = session_date.isoformat()
        with cls._CACHE_LOCK:
            if cache_key in cls._nyse_close_cache:
                return cls._nyse_close_cache[cache_key]
        close_time: datetime.time | None
        try:
            import pandas_market_calendars as mcal

            schedule = mcal.get_calendar('NYSE').schedule(
                start_date=cache_key,
                end_date=cache_key,
            )
            if schedule.empty:
                close_time = None
            else:
                close_timestamp = pd.Timestamp(schedule.iloc[0]['market_close'])
                if close_timestamp.tzinfo is None:
                    close_timestamp = close_timestamp.tz_localize('UTC')
                close_timestamp = close_timestamp.tz_convert('America/New_York')
                close_time = datetime.time(
                    close_timestamp.hour,
                    close_timestamp.minute,
                    close_timestamp.second,
                )
        except Exception:
            close_time = datetime.time(16, 0) if session_date.weekday() < 5 else None
        with cls._CACHE_LOCK:
            cls._nyse_close_cache[cache_key] = close_time
        return close_time

    def _load_pattern_history(self, symbol: str, batch_data: Any, symbols: list[str]) -> Any:
        symbol = str(symbol or '').upper().strip()
        if not symbol:
            return None
        cached = self._cache_get(self._history_cache, symbol, self._HISTORY_CACHE_TTL_SECONDS)
        if cached is not None and not getattr(cached, 'empty', True):
            self._fetch_meta['history_cache_hits'] += 1
            self._history_frames[symbol] = cached
            return cached
        frame = self._symbol_history_from_batch(batch_data, symbols, symbol)
        normalized = self._normalize_history_frame(frame)
        if normalized is not None and not getattr(normalized, 'empty', True):
            self._cache_put(self._history_cache, symbol, normalized)
            self._history_frames[symbol] = normalized
        return normalized

    def _prepare_pattern_histories(self, symbols: list[str]) -> dict[str, Any]:
        """Load canonical histories with one bounded retry batch for missing symbols."""
        ordered_symbols = list(dict.fromkeys(
            str(symbol or '').upper().strip()
            for symbol in symbols
            if str(symbol or '').strip()
        ))
        histories: dict[str, Any] = {}
        missing = []
        for symbol in ordered_symbols:
            cached = self._cache_get(self._history_cache, symbol, self._HISTORY_CACHE_TTL_SECONDS)
            if cached is None or getattr(cached, 'empty', True):
                missing.append(symbol)
                continue
            histories[symbol] = cached
            self._history_frames[symbol] = cached
            self._fetch_meta['history_cache_hits'] += 1

        for attempt in range(2):
            self._raise_if_cancelled()
            if not missing:
                break
            if attempt:
                self._fetch_meta['history_retry_count'] += 1
            requested = list(missing)
            batch_data = self._interruptible_call(
                lambda requested=requested: self._download_pattern_history(requested),
                label='history batch',
            )
            still_missing = []
            for symbol in requested:
                self._raise_if_cancelled()
                frame = self._symbol_history_from_batch(batch_data, requested, symbol)
                normalized = self._normalize_history_frame(frame)
                if normalized is None or getattr(normalized, 'empty', True):
                    still_missing.append(symbol)
                    continue
                histories[symbol] = normalized
                self._history_frames[symbol] = normalized
                self._cache_put(self._history_cache, symbol, normalized)
                self._fetch_meta['history_downloaded'] += 1
            missing = still_missing
        return histories

    def _load_exact_symbol_history(self, symbol: str) -> Any:
        symbol = str(symbol or '').upper().strip()
        if not symbol:
            return None
        cached = self._cache_get(self._history_cache, symbol, self._HISTORY_CACHE_TTL_SECONDS)
        if cached is not None and not getattr(cached, 'empty', True):
            self._fetch_meta['history_cache_hits'] += 1
            self._history_frames[symbol] = cached
            return cached
        self._raise_if_cancelled()
        try:
            frame = self._interruptible_call(
                lambda: yf.Ticker(symbol).history(
                    period=self._PATTERN_HISTORY_PERIOD,
                    interval='1d',
                    auto_adjust=False,
                    actions=False,
                ),
                label=f'{symbol} history',
            )
        except Exception as exc:
            logger.info('Roll exact-symbol history failed for %s: %s', symbol, exc)
            return None
        normalized = self._normalize_history_frame(frame)
        if normalized is not None and not getattr(normalized, 'empty', True):
            self._history_frames[symbol] = normalized
            self._cache_put(self._history_cache, symbol, normalized)
            self._fetch_meta['history_downloaded'] += 1
        return normalized

    def _pattern_snapshot_value(self, value: Any, decimals: int = 2) -> Any:
        numeric = self._to_float(value)
        if numeric is None:
            return None
        return round(numeric, decimals)

    def _latest_series_value(self, series: Any, offset: int = 0) -> float | None:
        try:
            clean = series.dropna()
        except Exception:
            return None
        if clean.empty or len(clean) <= offset:
            return None
        return self._to_float(clean.iloc[-1 - offset])

    def _series_change(self, series: Any, periods: int) -> float | None:
        current = self._latest_series_value(series)
        prior = self._latest_series_value(series, periods)
        if current is None or prior is None:
            return None
        return current - prior

    def _calculate_rsi(self, close: Any, period: int = 14) -> Any:
        delta = close.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.where(avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(avg_loss != 0, 100.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return rsi.fillna(50.0).clip(lower=0, upper=100)

    def _calculate_macd(self, close: Any) -> tuple[Any, Any, Any]:
        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
        histogram = macd_line - signal
        return macd_line, signal, histogram

    def _shared_pattern_context(self, frame: Any) -> dict[str, Any]:
        """Calculate indicators shared by selected pattern evaluators once per frame."""
        if frame is None or getattr(frame, 'empty', True):
            return {}
        cache_key = id(frame)
        signature = self._active_pattern_signatures.get(cache_key) or self._history_signature(frame)
        cached = self._pattern_contexts.get(cache_key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        required = {'High', 'Low', 'Close', 'Volume'}
        if not required.issubset(set(frame.columns)):
            return {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        open_series = pd.to_numeric(frame['Open'], errors='coerce') if 'Open' in frame.columns else close.shift(1)
        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        rsi = self._calculate_rsi(close)
        macd_line, macd_signal, macd_histogram = self._calculate_macd(close)
        swing_low_indexes = []
        swing_high_indexes = []
        for index in range(3, max(3, len(close) - 3)):
            low_value = self._to_float(low.iloc[index])
            high_value = self._to_float(high.iloc[index])
            low_window = low.iloc[index - 3:index + 4].dropna()
            high_window = high.iloc[index - 3:index + 4].dropna()
            if low_value is not None and low_value > 0 and len(low_window) >= 5:
                window_min = self._to_float(low_window.min())
                if window_min is not None and low_value <= window_min * 1.003:
                    swing_low_indexes.append(index)
            if high_value is not None and high_value > 0 and len(high_window) >= 5:
                window_max = self._to_float(high_window.max())
                if window_max is not None and high_value >= window_max * 0.997:
                    swing_high_indexes.append(index)
        context = {
            'open': open_series,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'sma20': close.rolling(20, min_periods=20).mean(),
            'sma50': close.rolling(50, min_periods=50).mean(),
            'sma200': close.rolling(200, min_periods=180).mean(),
            'ema8': close.ewm(span=8, adjust=False, min_periods=8).mean(),
            'ema21': close.ewm(span=21, adjust=False, min_periods=21).mean(),
            'volume20': volume.rolling(20, min_periods=10).mean(),
            'volume50': volume.rolling(50, min_periods=20).mean(),
            'volume60': volume.rolling(60, min_periods=30).mean(),
            'volume120': volume.rolling(120, min_periods=60).mean(),
            'rsi': rsi,
            'rsi_ma10': rsi.rolling(10, min_periods=5).mean(),
            'macd_line': macd_line,
            'macd_signal': macd_signal,
            'macd_histogram': macd_histogram,
            'true_range': true_range,
            'atr20': true_range.rolling(20, min_periods=15).mean(),
            'atr60': true_range.rolling(60, min_periods=40).mean(),
            'swing_high_mask': high.eq(high.rolling(7, center=True, min_periods=4).max()),
            'swing_low_mask': low.eq(low.rolling(7, center=True, min_periods=4).min()),
            'swing_high_indexes': swing_high_indexes,
            'swing_low_indexes': swing_low_indexes,
        }
        self._pattern_contexts[cache_key] = (signature, context)
        return context

    def _distinct_trough_indexes(
        self,
        indexes: Any,
        low: Any,
        *,
        max_adjacent_gap: int = 4,
    ) -> list[int]:
        """Collapse adjacent swing-low marks into distinct trough zones."""
        raw_indexes = list(indexes) if indexes is not None else []
        ordered = sorted({int(index) for index in raw_indexes if int(index) >= 0})
        if not ordered:
            return []
        zones: list[list[int]] = [[ordered[0]]]
        for index in ordered[1:]:
            if index - zones[-1][-1] <= max_adjacent_gap:
                zones[-1].append(index)
            else:
                zones.append([index])

        representatives = []
        for zone in zones:
            valid = [
                (index, self._to_float(low.iloc[index]))
                for index in zone
                if index < len(low)
            ]
            valid = [(index, value) for index, value in valid if value is not None and value > 0]
            if not valid:
                continue
            minimum = min(value for _index, value in valid)
            near_minimum = [index for index, value in valid if value <= minimum * 1.001]
            representatives.append(near_minimum[len(near_minimum) // 2])
        return representatives

    def _evaluate_breakout_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        close = context['close']
        volume = context['volume']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        resistance_window = high.iloc[:-5].tail(55) if len(high) > 60 else high.shift(1).tail(55)
        prior_high = self._to_float(resistance_window.max())
        sma20_series = context['sma20']
        sma50_series = context['sma50']
        sma200_series = context['sma200']
        ema8_series = context['ema8']
        ema21_series = context['ema21']
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema8 = self._latest_series_value(ema8_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = context['volume20']
        vol50_series = context['volume50']
        vol120_series = context['volume120']
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)
        rsi_series = context['rsi']
        rsi_ma_series = context['rsi_ma10']
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        macd_line_series = context['macd_line']
        macd_signal_series = context['macd_signal']
        macd_hist_series = context['macd_histogram']
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        if None in (last_close, prior_high, sma20, sma50, ema21) or not prior_high:
            return False, 0.0, [], {}

        distance_to_resistance = (last_close - prior_high) / prior_high
        recent_closes = close.tail(10)
        breakout_closes_5 = int((close.tail(5) > prior_high * 1.002).sum())
        breakout_closes_10 = int((recent_closes > prior_high * 1.002).sum())
        recent_high = self._to_float(high.tail(10).max())
        pre_breakout = -0.05 <= distance_to_resistance <= 0.002
        fresh_breakout = 0.002 < distance_to_resistance <= 0.012 and breakout_closes_5 <= 2 and breakout_closes_10 <= 4
        late_breakout = distance_to_resistance > 0.012 or breakout_closes_5 > 2 or breakout_closes_10 > 4

        above_daily_support = last_close >= min(sma20, ema21) * 0.995
        ma_stack_aligned = sma20 >= sma50 * 0.98
        if sma200 is not None:
            ma_stack_aligned = ma_stack_aligned and sma50 >= sma200 * 0.97
        fast_ma_aligned = ema8 is not None and ema8 >= ema21 * 0.995
        distance_to_sma20 = (last_close - sma20) / sma20 if sma20 else 1.0
        distance_to_ema21 = (last_close - ema21) / ema21 if ema21 else 1.0
        not_overextended = (
            distance_to_sma20 <= 0.06
            and distance_to_ema21 <= 0.08
            and (recent_high is None or recent_high <= prior_high * 1.05)
        )

        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_ma_change_10 = self._series_change(rsi_ma_series, 10)
        rsi_change_30 = self._series_change(rsi_series, 30)
        rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
        rsi_healthy = rsi is not None and 45 <= rsi <= 74
        rsi_short_ok = rsi_above_ma and (rsi_change_5 is None or rsi_change_5 >= -1.5)
        rsi_intermediate_ok = rsi is not None and rsi >= 50 and (rsi_ma_change_10 is None or rsi_ma_change_10 >= -1.0)
        rsi_long_ok = rsi is not None and rsi >= 45 and (rsi_change_30 is None or rsi_change_30 >= -6.0)
        rsi_ok = bool(rsi_above_ma and rsi_healthy and (rsi_short_ok or rsi_intermediate_ok))

        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)
        macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
        macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
        macd_short_ok = bool(macd_turning_up and (macd_hist is None or macd_hist > -abs(last_close) * 0.004))
        macd_intermediate_ok = bool(macd_above_signal or (macd_hist is not None and macd_hist > 0))
        macd_long_ok = bool(macd_line is not None and (macd_line >= 0 or (macd_line_change_20 is not None and macd_line_change_20 > 0)))
        macd_ok = bool(macd_short_ok and (macd_intermediate_ok or macd_long_ok))

        volume_ok = None
        if vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0:
            volume_ok = vol20 >= vol50 * 0.85
        if latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0:
            latest_volume_ok = vol20 * 0.9 <= latest_volume <= vol20 * 2.8
            volume_ok = latest_volume_ok if volume_ok is None else (volume_ok or latest_volume_ok)
            if latest_volume > vol20 * 2.8:
                volume_ok = False
        volume_short_available = latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0
        volume_intermediate_available = vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0
        volume_long_available = vol50 is not None and vol50 > 0 and vol120 is not None and vol120 > 0
        volume_short_not_adverse = not volume_short_available or latest_volume >= vol20 * 0.75
        volume_intermediate_not_adverse = not volume_intermediate_available or vol20 >= vol50 * 0.85
        volume_long_not_adverse = not volume_long_available or vol50 >= vol120 * 0.75
        volume_accumulation = bool(
            (vol20 is not None and vol50 is not None and vol50 > 0 and vol20 >= vol50 * 0.95)
            or (latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 1.05)
        )

        short_timeframe_ok = bool((rsi_short_ok or macd_short_ok) and volume_short_not_adverse)
        intermediate_timeframe_ok = bool((rsi_intermediate_ok or macd_intermediate_ok) and volume_intermediate_not_adverse)
        long_timeframe_ok = bool((rsi_long_ok or macd_long_ok) and volume_long_not_adverse)
        timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
        indicator_confirmations = sum(
            1
            for value in (
                rsi_ok,
                macd_ok,
                volume_ok is True,
                timeframe_agreement_count >= 2,
                ma_stack_aligned and fast_ma_aligned,
            )
            if value
        )

        timing_ok = pre_breakout or fresh_breakout
        if pre_breakout:
            setup_stage = 'Pre-Breakout'
        elif fresh_breakout:
            setup_stage = 'Fresh Breakout'
        else:
            setup_stage = 'Late Breakout' if late_breakout else 'No Breakout'

        score = 0.0
        reasons = []
        if pre_breakout:
            score += 28
            reasons.append('near resistance' if distance_to_resistance >= -0.02 else 'coiling below resistance')
        elif fresh_breakout:
            score += 20
            reasons.append('fresh breakout')
        if breakout_closes_5 <= 2 and breakout_closes_10 <= 4:
            score += 6
            reasons.append('few breakout closes')
        if above_daily_support:
            score += 8
            reasons.append('above daily support')
        if ma_stack_aligned and fast_ma_aligned:
            score += 14
            reasons.append('daily MA stack aligned')
        elif ma_stack_aligned or fast_ma_aligned:
            score += 8
            reasons.append('daily MAs improving')
        if not_overextended:
            score += 10
            reasons.append('not overextended')
        if rsi_above_ma:
            score += 8
            reasons.append('RSI above RSI MA')
        if rsi_healthy:
            score += 5
            reasons.append('RSI constructive')
        if macd_turning_up:
            score += 8
            reasons.append('MACD turning up')
        if macd_above_signal:
            score += 5
            reasons.append('MACD above signal')
        if volume_accumulation:
            score += 8
            reasons.append('volume accumulation')
        if volume_ok is True:
            score += 4
            reasons.append('volume controlled')
        if timeframe_agreement_count >= 2:
            score += 10
            reasons.append('multi-timeframe confirmation')
        elif timeframe_agreement_count == 1:
            score += 4

        if late_breakout:
            score -= 18
        if not not_overextended:
            score -= 12
        if rsi is not None and rsi > 76:
            score -= 8
        if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 2.8:
            score -= 10

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'setup_stage': setup_stage,
            'resistance_55d': self._pattern_snapshot_value(prior_high),
            'distance_to_resistance_pct': self._pattern_snapshot_value(distance_to_resistance * 100.0),
            'breakout_closes_5d': breakout_closes_5,
            'breakout_closes_10d': breakout_closes_10,
            'sma20': self._pattern_snapshot_value(sma20),
            'sma50': self._pattern_snapshot_value(sma50),
            'sma200': self._pattern_snapshot_value(sma200),
            'ema8': self._pattern_snapshot_value(ema8),
            'ema21': self._pattern_snapshot_value(ema21),
            'distance_to_sma20_pct': self._pattern_snapshot_value(distance_to_sma20 * 100.0),
            'daily_ma_stack': 'aligned' if ma_stack_aligned and fast_ma_aligned else ('improving' if ma_stack_aligned or fast_ma_aligned else 'mixed'),
            'rsi14': self._pattern_snapshot_value(rsi),
            'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
            'rsi_state': 'above RSI MA' if rsi_above_ma else 'below RSI MA',
            'macd_line': self._pattern_snapshot_value(macd_line),
            'macd_signal': self._pattern_snapshot_value(macd_signal),
            'macd_histogram': self._pattern_snapshot_value(macd_hist),
            'macd_state': 'turning up' if macd_turning_up else ('above signal' if macd_above_signal else 'mixed'),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume50': self._pattern_snapshot_value(vol50, 0),
            'volume120': self._pattern_snapshot_value(vol120, 0),
            'volume_state': 'accumulation' if volume_accumulation else ('controlled' if volume_ok is True else ('weak or disorderly' if volume_ok is False else 'unavailable')),
            'short_timeframe_confirmed': short_timeframe_ok,
            'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
            'long_timeframe_confirmed': long_timeframe_ok,
            'timeframe_agreement': f'{timeframe_agreement_count}/3',
        }
        matched = bool(
            timing_ok
            and not late_breakout
            and above_daily_support
            and not_overextended
            and indicator_confirmations >= 2
            and timeframe_agreement_count >= 2
            and score >= 58
        )
        return matched, max(0.0, min(100.0, score)), reasons[:8], snapshot

    def _evaluate_downtrend_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        low = context['low']
        close = context['close']
        volume = context['volume']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        sma20_series = context['sma20']
        sma50_series = context['sma50']
        sma200_series = context['sma200']
        ema8_series = context['ema8']
        ema21_series = context['ema21']
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema8 = self._latest_series_value(ema8_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = context['volume20']
        vol50_series = context['volume50']
        vol120_series = context['volume120']
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)
        if None in (last_close, sma20, sma50, ema21) or not last_close:
            return False, 0.0, [], {}

        rsi_series = context['rsi']
        rsi_ma_series = context['rsi_ma10']
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_ma_change_10 = self._series_change(rsi_ma_series, 10)
        rsi_change_30 = self._series_change(rsi_series, 30)
        macd_line_series = context['macd_line']
        macd_signal_series = context['macd_signal']
        macd_hist_series = context['macd_histogram']
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        prior_20_close = self._latest_series_value(close, 20)
        prior_60_close = self._latest_series_value(close, 60)
        decline_20 = (last_close - prior_20_close) / prior_20_close if prior_20_close else 0.0
        decline_60 = (last_close - prior_60_close) / prior_60_close if prior_60_close else 0.0
        negative_trend_evidence = decline_20 <= -0.015 or decline_60 <= -0.03
        recent_20_high = self._to_float(high.tail(20).max())
        previous_20_high = self._to_float(high.iloc[-40:-20].max()) if len(high) >= 40 else None
        recent_20_low = self._to_float(low.tail(20).min())
        previous_20_low = self._to_float(low.iloc[-40:-20].min()) if len(low) >= 40 else None
        lower_highs = previous_20_high is not None and recent_20_high is not None and recent_20_high <= previous_20_high * 0.995
        lower_lows = previous_20_low is not None and recent_20_low is not None and recent_20_low <= previous_20_low * 0.995
        below_daily_mas = last_close <= min(sma20, ema21) * 1.01 and last_close <= sma50 * 1.02
        bearish_stack = sma20 <= sma50 * 1.02 and (ema8 is None or ema8 <= ema21 * 1.01)
        if sma200 is not None:
            bearish_stack = bearish_stack and sma50 <= sma200 * 1.03
        distance_to_sma20 = (last_close - sma20) / sma20 if sma20 else 0.0
        distance_to_sma50 = (last_close - sma50) / sma50 if sma50 else 0.0
        controlled_decline = distance_to_sma20 >= -0.18 and (rsi is None or rsi >= 24)

        rsi_below_ma = rsi is not None and rsi_ma is not None and rsi <= rsi_ma
        rsi_bearish = rsi is not None and 26 <= rsi <= 52
        rsi_short_ok = bool(rsi_below_ma and (rsi_change_5 is None or rsi_change_5 <= 2.0))
        rsi_intermediate_ok = bool(rsi is not None and rsi <= 50 and (rsi_ma_change_10 is None or rsi_ma_change_10 <= 1.0))
        rsi_long_ok = bool(rsi is not None and rsi <= 55 and (rsi_change_30 is None or rsi_change_30 <= 6.0))
        rsi_ok = bool(rsi_below_ma and rsi_bearish and (rsi_short_ok or rsi_intermediate_ok))

        macd_below_signal = macd_line is not None and macd_signal is not None and macd_line <= macd_signal
        macd_negative = macd_line is not None and macd_line <= 0
        macd_weakening = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 < 0)
        macd_short_ok = bool(macd_below_signal or macd_weakening)
        macd_intermediate_ok = bool(macd_negative or (macd_hist is not None and macd_hist < 0))
        macd_long_ok = bool(macd_line is not None and (macd_line <= 0 or (macd_line_change_20 is not None and macd_line_change_20 < 0)))
        macd_ok = bool(macd_short_ok and (macd_intermediate_ok or macd_long_ok))

        recent_frame = frame.tail(20).copy()
        down_volume_avg = None
        up_volume_avg = None
        try:
            recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
            recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
            recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
            down_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
            up_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
        except Exception:
            pass
        latest_open = self._latest_series_value(context['open'])
        latest_down_bar = latest_open is not None and last_close < latest_open
        downside_volume = bool(
            (down_volume_avg is not None and down_volume_avg > 0 and up_volume_avg is not None and up_volume_avg > 0 and down_volume_avg >= up_volume_avg * 0.9)
            or (
                latest_down_bar
                and latest_volume is not None
                and latest_volume > 0
                and vol20 is not None
                and vol20 > 0
                and latest_volume >= vol20 * 0.85
            )
        )
        volume_controlled = None
        if latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0:
            volume_controlled = latest_volume <= vol20 * 3.2
        volume_short_available = latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0
        volume_intermediate_available = vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0
        volume_long_available = vol50 is not None and vol50 > 0 and vol120 is not None and vol120 > 0
        volume_short_not_adverse = not volume_short_available or latest_volume >= vol20 * 0.75
        volume_intermediate_not_adverse = not volume_intermediate_available or vol20 >= vol50 * 0.75
        volume_long_not_adverse = not volume_long_available or vol50 >= vol120 * 0.65

        price_short_ok = bool(last_close <= sma20 * 1.01 or decline_20 <= -0.02)
        price_intermediate_ok = bool(last_close <= sma50 * 1.02 or decline_60 <= -0.04)
        price_long_ok = bool((sma200 is not None and last_close <= sma200 * 1.03) or decline_60 <= -0.06)
        short_timeframe_ok = bool((price_short_ok or rsi_short_ok or macd_short_ok) and volume_short_not_adverse)
        intermediate_timeframe_ok = bool((price_intermediate_ok or rsi_intermediate_ok or macd_intermediate_ok) and volume_intermediate_not_adverse)
        long_timeframe_ok = bool((price_long_ok or rsi_long_ok or macd_long_ok) and volume_long_not_adverse)
        timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
        indicator_confirmations = sum(
            1
            for value in (
                rsi_ok,
                macd_ok,
                downside_volume,
                timeframe_agreement_count >= 2,
                negative_trend_evidence and (bearish_stack or lower_highs or lower_lows),
            )
            if value
        )

        score = 0.0
        reasons = []
        if below_daily_mas:
            score += 18
            reasons.append('below daily MAs')
        if bearish_stack:
            score += 16
            reasons.append('bearish MA stack')
        if lower_highs:
            score += 12
            reasons.append('lower highs')
        if lower_lows:
            score += 10
            reasons.append('lower lows')
        if decline_20 <= -0.03 or decline_60 <= -0.06:
            score += 10
            reasons.append('negative price trend')
        if rsi_below_ma:
            score += 8
            reasons.append('RSI below RSI MA')
        if rsi_bearish:
            score += 6
            reasons.append('RSI bearish')
        if macd_below_signal:
            score += 8
            reasons.append('MACD below signal')
        if macd_negative or macd_weakening:
            score += 6
            reasons.append('MACD weakening')
        if downside_volume:
            score += 8
            reasons.append('downside volume')
        if volume_controlled is True:
            score += 4
            reasons.append('volume controlled')
        if timeframe_agreement_count >= 2:
            score += 10
            reasons.append('multi-timeframe downtrend')
        elif timeframe_agreement_count == 1:
            score += 4
        if not controlled_decline:
            score -= 12
        if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 3.2:
            score -= 8

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'setup_stage': 'Downtrend',
            'decline_20d_pct': self._pattern_snapshot_value(decline_20 * 100.0),
            'decline_60d_pct': self._pattern_snapshot_value(decline_60 * 100.0),
            'negative_trend_evidence': negative_trend_evidence,
            'distance_to_sma20_pct': self._pattern_snapshot_value(distance_to_sma20 * 100.0),
            'distance_to_sma50_pct': self._pattern_snapshot_value(distance_to_sma50 * 100.0),
            'sma20': self._pattern_snapshot_value(sma20),
            'sma50': self._pattern_snapshot_value(sma50),
            'sma200': self._pattern_snapshot_value(sma200),
            'ema8': self._pattern_snapshot_value(ema8),
            'ema21': self._pattern_snapshot_value(ema21),
            'daily_ma_stack': 'bearish' if bearish_stack else ('below MAs' if below_daily_mas else 'mixed'),
            'lower_highs': lower_highs,
            'lower_lows': lower_lows,
            'rsi14': self._pattern_snapshot_value(rsi),
            'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
            'rsi_state': 'below RSI MA' if rsi_below_ma else 'above RSI MA',
            'macd_line': self._pattern_snapshot_value(macd_line),
            'macd_signal': self._pattern_snapshot_value(macd_signal),
            'macd_histogram': self._pattern_snapshot_value(macd_hist),
            'macd_state': 'below signal' if macd_below_signal else ('weakening' if macd_weakening else 'mixed'),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume50': self._pattern_snapshot_value(vol50, 0),
            'volume120': self._pattern_snapshot_value(vol120, 0),
            'volume_state': 'downside participation' if downside_volume else ('controlled' if volume_controlled is True else ('disorderly' if volume_controlled is False else 'unavailable')),
            'short_timeframe_confirmed': short_timeframe_ok,
            'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
            'long_timeframe_confirmed': long_timeframe_ok,
            'timeframe_agreement': f'{timeframe_agreement_count}/3',
            'near_eligible': negative_trend_evidence,
        }
        matched = bool(
            negative_trend_evidence
            and below_daily_mas
            and (bearish_stack or lower_highs or lower_lows)
            and controlled_decline
            and indicator_confirmations >= 2
            and timeframe_agreement_count >= 2
            and score >= 58
        )
        return matched, max(0.0, min(100.0, score)), reasons[:8], snapshot

    def _evaluate_consolidation_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        low = context['low']
        close = context['close']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        range_high = self._to_float(high.tail(20).max())
        range_low = self._to_float(low.tail(20).min())
        atr20 = self._latest_series_value(context['atr20'])
        atr60 = self._latest_series_value(context['atr60'])
        vol20 = self._latest_series_value(context['volume20'])
        vol60 = self._latest_series_value(context['volume60'])
        if None in (last_close, range_high, range_low, atr20, atr60) or not last_close or not atr60:
            return False, 0.0, [], {}

        range_pct = (range_high - range_low) / last_close if last_close else 1.0
        atr_contracting = atr20 <= atr60 * 0.85
        tight_range = range_pct <= 0.14
        inside_range = range_low * 1.01 <= last_close <= range_high * 0.99
        recent_closes = close.tail(20).dropna()
        net_drift = 1.0
        directional_efficiency = 1.0
        if len(recent_closes) >= 10:
            first_close = self._to_float(recent_closes.iloc[0])
            last_recent_close = self._to_float(recent_closes.iloc[-1])
            path_length = self._to_float(recent_closes.diff().abs().sum())
            if first_close is not None and first_close > 0 and last_recent_close is not None:
                net_change = last_recent_close - first_close
                net_drift = abs(net_change) / first_close
                directional_efficiency = abs(net_change) / path_length if path_length and path_length > 0 else 0.0
        low_directional_drift = net_drift <= 0.04 and directional_efficiency <= 0.35
        orderly_volume = None
        if vol20 is not None and vol20 > 0 and vol60 is not None and vol60 > 0:
            orderly_volume = vol20 <= vol60 * 1.25
        volume_disorderly = orderly_volume is False

        score = 0.0
        reasons = []
        if tight_range:
            score += 30
            reasons.append('tight 20D range')
        if atr_contracting:
            score += 25
            reasons.append('volatility contracted')
        if low_directional_drift:
            score += 25
            reasons.append('low directional drift')
        if inside_range:
            score += 10
            reasons.append('inside range')
        if orderly_volume is True:
            score += 10
            reasons.append('orderly volume')

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'setup_stage': 'Consolidation',
            'range_20d_high': self._pattern_snapshot_value(range_high),
            'range_20d_low': self._pattern_snapshot_value(range_low),
            'range_pct': self._pattern_snapshot_value(range_pct * 100.0),
            'net_drift_pct': self._pattern_snapshot_value(net_drift * 100.0),
            'directional_efficiency': self._pattern_snapshot_value(directional_efficiency, 3),
            'atr20': self._pattern_snapshot_value(atr20),
            'atr60': self._pattern_snapshot_value(atr60),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume60': self._pattern_snapshot_value(vol60, 0),
            'volume_state': 'orderly' if orderly_volume is True else ('disorderly' if volume_disorderly else 'unavailable'),
            'near_eligible': bool(low_directional_drift and not volume_disorderly),
        }
        matched = bool(tight_range and atr_contracting and inside_range and low_directional_drift and not volume_disorderly)
        return matched, min(100.0, score), reasons, snapshot

    def _evaluate_double_bottom_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        low = context['low']
        close = context['close']
        volume = context['volume']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = context['sma20']
        sma50_series = context['sma50']
        sma200_series = context['sma200']
        ema21_series = context['ema21']
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = context['volume20']
        vol50_series = context['volume50']
        vol120_series = context['volume120']
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = context['rsi']
        rsi_ma_series = context['rsi_ma10']
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_change_20 = self._series_change(rsi_series, 20)
        macd_line_series = context['macd_line']
        macd_signal_series = context['macd_signal']
        macd_hist_series = context['macd_histogram']
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        lookback_start = max(0, len(low) - 120)
        raw_swing_lows = [index for index in context['swing_low_indexes'] if index >= lookback_start]
        swing_lows = self._distinct_trough_indexes(raw_swing_lows, low)
        trough_zone_count = len(swing_lows)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for first_index in swing_lows:
            for second_index in swing_lows:
                if second_index <= first_index:
                    continue
                separation = second_index - first_index
                days_since_second = len(low) - 1 - second_index
                if separation < 15 or separation > 80 or days_since_second < 3 or days_since_second > 45:
                    continue
                first_bottom = self._to_float(low.iloc[first_index])
                second_bottom = self._to_float(low.iloc[second_index])
                if first_bottom is None or second_bottom is None or first_bottom <= 0 or second_bottom <= 0:
                    continue
                average_bottom = (first_bottom + second_bottom) / 2.0
                bottom_gap = abs(first_bottom - second_bottom) / average_bottom if average_bottom else 1.0
                if bottom_gap > 0.05:
                    continue
                neckline = self._to_float(high.iloc[first_index:second_index + 1].max())
                if neckline is None or neckline <= 0:
                    continue
                neckline_height = (neckline - average_bottom) / average_bottom if average_bottom else 0.0
                if neckline_height < 0.06:
                    continue
                post_second_low = self._to_float(low.iloc[second_index + 1:].min()) if second_index + 1 < len(low) else None
                if post_second_low is not None and post_second_low < min(first_bottom, second_bottom) * 0.985:
                    continue

                prior_high = self._to_float(high.iloc[max(0, first_index - 45):first_index].max()) if first_index > 0 else None
                first_close = self._to_float(close.iloc[first_index])
                prior_close = self._to_float(close.iloc[first_index - 30]) if first_index >= 30 else None
                prior_decline = None
                prior_weakness = False
                if prior_high is not None and prior_high > 0:
                    prior_decline = (average_bottom - prior_high) / prior_high
                    prior_weakness = prior_decline <= -0.08
                if not prior_weakness and prior_close is not None and prior_close > 0 and first_close is not None:
                    prior_decline = (first_close - prior_close) / prior_close
                    prior_weakness = prior_decline <= -0.06
                if not prior_weakness:
                    continue

                distance_to_neckline = (last_close - neckline) / neckline
                rebound_from_second = (last_close - second_bottom) / second_bottom
                if distance_to_neckline < -0.08 or distance_to_neckline > 0.06 or rebound_from_second < 0.04:
                    continue

                recent_frame = frame.iloc[second_index:].copy()
                up_volume_avg = None
                down_volume_avg = None
                try:
                    recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
                    recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
                    recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
                    up_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
                    down_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
                except Exception:
                    pass
                latest_open = self._latest_series_value(context['open'])
                latest_up_bar = latest_open is not None and last_close >= latest_open
                constructive_volume = bool(
                    (up_volume_avg is not None and down_volume_avg is not None and down_volume_avg > 0 and up_volume_avg >= down_volume_avg * 0.9)
                    or (
                        latest_up_bar
                        and latest_volume is not None
                        and latest_volume > 0
                        and vol20 is not None
                        and vol20 > 0
                        and latest_volume >= vol20 * 0.85
                    )
                )
                volume_controlled = None
                if latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0:
                    volume_controlled = latest_volume <= vol20 * 3.0
                volume_short_ok = bool(latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 0.65)
                volume_intermediate_ok = bool(vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0 and vol20 >= vol50 * 0.70)
                volume_long_ok = bool(vol50 is not None and vol50 > 0 and vol120 is not None and vol120 > 0 and vol50 >= vol120 * 0.60)
                volume_ok = bool(constructive_volume and volume_controlled is not False)

                rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
                rsi_recovering = bool(
                    rsi is not None
                    and 38 <= rsi <= 70
                    and (
                        rsi_above_ma
                        or (rsi_change_5 is not None and rsi_change_5 >= 0)
                        or (rsi_change_20 is not None and rsi_change_20 >= 4)
                    )
                )
                rsi_short_ok = bool(rsi_above_ma or (rsi_change_5 is not None and rsi_change_5 >= -1.0))
                rsi_intermediate_ok = bool(rsi is not None and rsi >= 42 and (rsi_change_20 is None or rsi_change_20 >= -2.0))
                rsi_long_ok = bool(rsi is not None and rsi >= 38)

                macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
                macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
                macd_recovering = macd_line_change_20 is not None and macd_line_change_20 > 0
                macd_ok = bool((macd_above_signal or macd_turning_up) and (macd_recovering or macd_hist is None or macd_hist > -abs(last_close) * 0.004))
                macd_short_ok = bool(macd_above_signal or macd_turning_up)
                macd_intermediate_ok = bool(macd_recovering or (macd_hist is not None and macd_hist >= 0))
                macd_long_ok = bool(macd_line is None or macd_line_change_20 is None or macd_line_change_20 >= -abs(last_close) * 0.002)

                price_short_ok = bool(rebound_from_second >= 0.06 and distance_to_neckline >= -0.08)
                price_intermediate_ok = bool(distance_to_neckline >= -0.06 or (sma20 is not None and last_close >= sma20 * 0.97))
                price_long_ok = bool(sma50 is None or last_close >= sma50 * 0.90 or distance_to_neckline >= -0.04)
                short_timeframe_ok = bool(price_short_ok and (rsi_short_ok or macd_short_ok or volume_short_ok))
                intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_intermediate_ok or macd_intermediate_ok or volume_intermediate_ok))
                long_timeframe_ok = bool(price_long_ok and (rsi_long_ok or macd_long_ok or volume_long_ok))
                timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
                indicator_confirmations = sum(1 for value in (rsi_recovering, macd_ok, volume_ok, timeframe_agreement_count >= 2) if value)

                neckline_breakout = last_close >= neckline * 1.002
                setup_stage = 'Double Bottom Breakout' if neckline_breakout else 'Double Bottom Rebound'
                score = 0.0
                reasons = []
                if bottom_gap <= 0.03:
                    score += 18
                    reasons.append('similar bottoms')
                else:
                    score += 12
                    reasons.append('bottoms within 5%')
                if neckline_height >= 0.10:
                    score += 18
                    reasons.append('clear neckline')
                else:
                    score += 12
                    reasons.append('meaningful neckline')
                if neckline_breakout:
                    score += 20
                    reasons.append('neckline breakout')
                else:
                    score += 16
                    reasons.append('rebounding toward neckline')
                if rebound_from_second >= 0.08:
                    score += 8
                    reasons.append('strong second-bottom rebound')
                else:
                    score += 4
                    reasons.append('second-bottom rebound')
                if prior_weakness:
                    score += 10
                    reasons.append('prior downtrend')
                if days_since_second <= 25:
                    score += 8
                    reasons.append('recent second bottom')
                else:
                    score += 4
                if rsi_recovering:
                    score += 10
                    reasons.append('RSI recovering')
                elif rsi is not None and rsi >= 38:
                    score += 4
                if macd_ok:
                    score += 10
                    reasons.append('MACD improving')
                elif macd_turning_up:
                    score += 5
                    reasons.append('MACD turning up')
                if constructive_volume:
                    score += 8
                    reasons.append('constructive volume')
                if volume_controlled is True:
                    score += 4
                    reasons.append('volume controlled')
                if timeframe_agreement_count >= 2:
                    score += 10
                    reasons.append('multi-timeframe confirmation')
                elif timeframe_agreement_count == 1:
                    score += 4
                if distance_to_neckline > 0.04:
                    score -= 6
                if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 3.0:
                    score -= 8

                snapshot = {
                    'close': self._pattern_snapshot_value(last_close),
                    'setup_stage': setup_stage,
                    'first_bottom': self._pattern_snapshot_value(first_bottom),
                    'second_bottom': self._pattern_snapshot_value(second_bottom),
                    'neckline': self._pattern_snapshot_value(neckline),
                    'bottom_gap_pct': self._pattern_snapshot_value(bottom_gap * 100.0),
                    'neckline_height_pct': self._pattern_snapshot_value(neckline_height * 100.0),
                    'distance_to_neckline_pct': self._pattern_snapshot_value(distance_to_neckline * 100.0),
                    'rebound_from_second_pct': self._pattern_snapshot_value(rebound_from_second * 100.0),
                    'prior_decline_pct': self._pattern_snapshot_value(prior_decline * 100.0) if prior_decline is not None else None,
                    'days_between_bottoms': separation,
                    'days_since_second_bottom': days_since_second,
                    'trough_zone_count': trough_zone_count,
                    'sma20': self._pattern_snapshot_value(sma20),
                    'sma50': self._pattern_snapshot_value(sma50),
                    'sma200': self._pattern_snapshot_value(sma200),
                    'ema21': self._pattern_snapshot_value(ema21),
                    'rsi14': self._pattern_snapshot_value(rsi),
                    'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                    'rsi_state': 'recovering' if rsi_recovering else ('above RSI MA' if rsi_above_ma else 'mixed'),
                    'macd_line': self._pattern_snapshot_value(macd_line),
                    'macd_signal': self._pattern_snapshot_value(macd_signal),
                    'macd_histogram': self._pattern_snapshot_value(macd_hist),
                    'macd_state': 'improving' if macd_ok else ('turning up' if macd_turning_up else 'mixed'),
                    'volume20': self._pattern_snapshot_value(vol20, 0),
                    'volume50': self._pattern_snapshot_value(vol50, 0),
                    'volume120': self._pattern_snapshot_value(vol120, 0),
                    'volume_state': 'constructive' if constructive_volume else ('controlled' if volume_controlled is True else ('disorderly' if volume_controlled is False else 'unavailable')),
                    'short_timeframe_confirmed': short_timeframe_ok,
                    'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                    'long_timeframe_confirmed': long_timeframe_ok,
                    'timeframe_agreement': f'{timeframe_agreement_count}/3',
                    'near_eligible': trough_zone_count >= 2,
                }
                matched = bool(
                    indicator_confirmations >= 2
                    and timeframe_agreement_count >= 2
                    and score >= 62
                )
                bounded_score = max(0.0, min(100.0, score))
                if (
                    (matched and (not best_matched or bounded_score > best_score))
                    or (not best_matched and not matched and bounded_score > best_score)
                ):
                    best_score = bounded_score
                    best_reasons = reasons[:8]
                    best_snapshot = snapshot
                    best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _evaluate_bullish_flag_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        low = context['low']
        close = context['close']
        volume = context['volume']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = context['sma20']
        sma50_series = context['sma50']
        sma200_series = context['sma200']
        ema21_series = context['ema21']
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = context['volume20']
        vol50_series = context['volume50']
        vol120_series = context['volume120']
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = context['rsi']
        rsi_ma_series = context['rsi_ma10']
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_change_20 = self._series_change(rsi_series, 20)
        macd_line_series = context['macd_line']
        macd_signal_series = context['macd_signal']
        macd_hist_series = context['macd_histogram']
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for pole_high_index in range(max(35, len(high) - 26), max(35, len(high) - 5)):
            flag_days = len(high) - 1 - pole_high_index
            if flag_days < 5 or flag_days > 25:
                continue
            pole_high = self._to_float(high.iloc[pole_high_index])
            local_peak_window = high.iloc[max(0, pole_high_index - 3):min(len(high), pole_high_index + 4)].dropna()
            local_peak = self._to_float(local_peak_window.max()) if not local_peak_window.empty else None
            if pole_high is None or local_peak is None or pole_high < local_peak * 0.997:
                continue
            pole_window_start = max(0, pole_high_index - 32)
            pole_window_end = max(pole_window_start, pole_high_index - 4)
            pole_low_window = low.iloc[pole_window_start:pole_window_end].dropna()
            pole_low = self._to_float(pole_low_window.min()) if not pole_low_window.empty else None
            if pole_high is None or pole_low is None or pole_high <= 0 or pole_low <= 0:
                continue
            try:
                pole_low_index = int(low.index.get_loc(pole_low_window.idxmin()))
            except Exception:
                continue
            pole_days = pole_high_index - pole_low_index
            if pole_days < 5 or pole_days > 32:
                continue
            flagpole_gain = (pole_high - pole_low) / pole_low
            if flagpole_gain < 0.12:
                continue
            recent_impulse_index = max(pole_low_index, pole_high_index - 15)
            recent_impulse_base = self._to_float(close.iloc[recent_impulse_index])
            recent_impulse_gain = (
                (pole_high - recent_impulse_base) / recent_impulse_base
                if recent_impulse_base is not None and recent_impulse_base > 0
                else 0.0
            )
            pole_daily_gain = flagpole_gain / max(pole_days, 1)
            impulse_confirmed = pole_daily_gain >= 0.005 or recent_impulse_gain >= 0.08
            if not impulse_confirmed:
                continue

            flag_high = high.iloc[pole_high_index + 1:-1]
            flag_low_series = low.iloc[pole_high_index + 1:]
            if len(flag_high.dropna()) < 4 or len(flag_low_series.dropna()) < 4:
                continue
            flag_resistance = self._to_float(flag_high.max())
            flag_low = self._to_float(flag_low_series.min())
            if flag_resistance is None or flag_low is None or flag_resistance <= 0 or flag_low <= 0:
                continue
            pullback = (pole_high - flag_low) / pole_high
            if pullback < 0.03 or pullback > 0.18:
                continue
            if flag_low < pole_low + (pole_high - pole_low) * 0.35:
                continue
            if flag_resistance > pole_high * 1.025:
                continue

            distance_to_flag_resistance = (last_close - flag_resistance) / flag_resistance
            if distance_to_flag_resistance < -0.05 or distance_to_flag_resistance > 0.04:
                continue
            breakout = last_close >= flag_resistance * 1.002
            flag_close = close.iloc[pole_high_index + 1:]
            flag_volume = volume.iloc[pole_high_index + 1:-1]
            flag_vol_avg = self._to_float(flag_volume.mean())
            pole_vol_avg = self._to_float(volume.iloc[pole_low_index:pole_high_index + 1].mean())
            orderly_volume = None
            if flag_vol_avg is not None and flag_vol_avg > 0 and pole_vol_avg is not None and pole_vol_avg > 0:
                orderly_volume = flag_vol_avg <= pole_vol_avg * 1.25
            volume_controlled = None
            if latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0:
                volume_controlled = latest_volume <= vol20 * 2.7
            volume_short_ok = bool(latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 0.60)
            volume_intermediate_ok = bool(vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0 and vol20 >= vol50 * 0.70)
            volume_long_ok = bool(vol50 is not None and vol50 > 0 and vol120 is not None and vol120 > 0 and vol50 >= vol120 * 0.65)
            volume_ok = bool(orderly_volume is True and volume_controlled is not False)

            first_flag_high = self._to_float(flag_high.head(max(2, len(flag_high) // 2)).max())
            second_flag_high = self._to_float(flag_high.tail(max(2, len(flag_high) // 2)).max())
            controlled_flag = bool(first_flag_high is None or second_flag_high is None or second_flag_high <= first_flag_high * 1.025)
            flag_close_low = self._to_float(flag_close.min())
            still_supported = bool(
                flag_close_low is None
                or sma50 is None
                or flag_close_low >= sma50 * 0.94
                or flag_close_low >= pole_high * 0.82
            )

            uptrend_stack = bool(sma20 is not None and sma50 is not None and sma20 >= sma50 * 0.98)
            if sma200 is not None and sma50 is not None:
                uptrend_stack = uptrend_stack and sma50 >= sma200 * 0.95
            price_above_support = bool(
                (sma20 is None or last_close >= sma20 * 0.96)
                and (ema21 is None or last_close >= ema21 * 0.96)
                and (sma50 is None or last_close >= sma50 * 0.94)
            )

            rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
            rsi_constructive = bool(
                rsi is not None
                and 44 <= rsi <= 74
                and (rsi_above_ma or rsi_change_5 is None or rsi_change_5 >= -2.0)
            )
            rsi_short_ok = bool(rsi_constructive or (rsi_change_5 is not None and rsi_change_5 >= -1.5))
            rsi_intermediate_ok = bool(rsi is not None and rsi >= 45 and (rsi_change_20 is None or rsi_change_20 >= -5.0))
            rsi_long_ok = bool(rsi is not None and rsi >= 42)

            macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
            macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 >= -abs(last_close) * 0.001)
            macd_recovering = macd_line_change_20 is not None and macd_line_change_20 >= -abs(last_close) * 0.001
            macd_ok = bool(macd_above_signal or (macd_turning_up and macd_recovering))
            macd_short_ok = bool(macd_above_signal or macd_turning_up)
            macd_intermediate_ok = bool(macd_ok or (macd_hist is not None and macd_hist >= -abs(last_close) * 0.003))
            macd_long_ok = bool(macd_line is None or macd_line >= -abs(last_close) * 0.02 or macd_recovering)

            price_short_ok = bool(distance_to_flag_resistance >= -0.05)
            price_intermediate_ok = bool(price_above_support and still_supported)
            price_long_ok = bool(uptrend_stack or flagpole_gain >= 0.18)
            short_timeframe_ok = bool(price_short_ok and (rsi_short_ok or macd_short_ok or volume_short_ok))
            intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_intermediate_ok or macd_intermediate_ok or volume_intermediate_ok))
            long_timeframe_ok = bool(price_long_ok and (rsi_long_ok or macd_long_ok or volume_long_ok))
            timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
            indicator_confirmations = sum(1 for value in (rsi_constructive, macd_ok, volume_ok, timeframe_agreement_count >= 2) if value)

            setup_stage = 'Bullish Flag Breakout' if breakout else 'Bullish Flag Setup'
            score = 0.0
            reasons = []
            if flagpole_gain >= 0.20:
                score += 20
                reasons.append('strong flagpole')
            else:
                score += 14
                reasons.append('bullish flagpole')
            if 0.05 <= pullback <= 0.14:
                score += 18
                reasons.append('controlled pullback')
            else:
                score += 10
                reasons.append('acceptable pullback')
            if controlled_flag and still_supported:
                score += 14
                reasons.append('orderly flag')
            elif controlled_flag or still_supported:
                score += 8
            if breakout:
                score += 18
                reasons.append('flag breakout')
            else:
                score += 14
                reasons.append('near flag resistance')
            if uptrend_stack:
                score += 10
                reasons.append('uptrend MA structure')
            if rsi_constructive:
                score += 8
                reasons.append('RSI constructive')
            if macd_ok:
                score += 8
                reasons.append('MACD supportive')
            if orderly_volume is True:
                score += 6
                reasons.append('orderly volume')
            if volume_controlled is True:
                score += 4
                reasons.append('volume controlled')
            if timeframe_agreement_count >= 2:
                score += 10
                reasons.append('multi-timeframe confirmation')
            elif timeframe_agreement_count == 1:
                score += 4
            if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 2.7:
                score -= 8
            if rsi is not None and rsi > 76:
                score -= 8

            snapshot = {
                'close': self._pattern_snapshot_value(last_close),
                'setup_stage': setup_stage,
                'flagpole_gain_pct': self._pattern_snapshot_value(flagpole_gain * 100.0),
                'pullback_pct': self._pattern_snapshot_value(pullback * 100.0),
                'distance_to_flag_resistance_pct': self._pattern_snapshot_value(distance_to_flag_resistance * 100.0),
                'flag_resistance': self._pattern_snapshot_value(flag_resistance),
                'flag_days': flag_days,
                'pole_days': pole_days,
                'pole_daily_gain_pct': self._pattern_snapshot_value(pole_daily_gain * 100.0, 3),
                'recent_impulse_gain_pct': self._pattern_snapshot_value(recent_impulse_gain * 100.0),
                'impulse_confirmed': impulse_confirmed,
                'sma20': self._pattern_snapshot_value(sma20),
                'sma50': self._pattern_snapshot_value(sma50),
                'sma200': self._pattern_snapshot_value(sma200),
                'ema21': self._pattern_snapshot_value(ema21),
                'rsi14': self._pattern_snapshot_value(rsi),
                'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                'rsi_state': 'constructive' if rsi_constructive else ('above RSI MA' if rsi_above_ma else 'mixed'),
                'macd_line': self._pattern_snapshot_value(macd_line),
                'macd_signal': self._pattern_snapshot_value(macd_signal),
                'macd_histogram': self._pattern_snapshot_value(macd_hist),
                'macd_state': 'supportive' if macd_ok else ('turning up' if macd_turning_up else 'mixed'),
                'volume20': self._pattern_snapshot_value(vol20, 0),
                'volume50': self._pattern_snapshot_value(vol50, 0),
                'volume120': self._pattern_snapshot_value(vol120, 0),
                'volume_state': 'orderly' if orderly_volume is True else ('controlled' if volume_controlled is True else ('disorderly' if orderly_volume is False or volume_controlled is False else 'unavailable')),
                'short_timeframe_confirmed': short_timeframe_ok,
                'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                'long_timeframe_confirmed': long_timeframe_ok,
                'timeframe_agreement': f'{timeframe_agreement_count}/3',
                'near_eligible': bool(impulse_confirmed and controlled_flag and still_supported),
            }
            matched = bool(
                price_short_ok
                and price_intermediate_ok
                and indicator_confirmations >= 2
                and timeframe_agreement_count >= 2
                and score >= 62
            )
            bounded_score = max(0.0, min(100.0, score))
            if (
                (matched and (not best_matched or bounded_score > best_score))
                or (not best_matched and not matched and bounded_score > best_score)
            ):
                best_score = bounded_score
                best_reasons = reasons[:8]
                best_snapshot = snapshot
                best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _evaluate_bullish_rsi_divergence_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        context = self._shared_pattern_context(frame)
        high = context['high']
        low = context['low']
        close = context['close']
        volume = context['volume']
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = context['sma20']
        sma50_series = context['sma50']
        sma200_series = context['sma200']
        ema21_series = context['ema21']
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = context['volume20']
        vol50_series = context['volume50']
        vol120_series = context['volume120']
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = context['rsi']
        rsi_ma_series = context['rsi_ma10']
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        macd_line_series = context['macd_line']
        macd_signal_series = context['macd_signal']
        macd_hist_series = context['macd_histogram']
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        lookback_start = max(0, len(low) - 110)
        raw_swing_lows = [index for index in context['swing_low_indexes'] if index >= lookback_start]
        swing_lows = self._distinct_trough_indexes(raw_swing_lows, low)
        trough_zone_count = len(swing_lows)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for first_index in swing_lows:
            for second_index in swing_lows:
                if second_index <= first_index:
                    continue
                separation = second_index - first_index
                days_since_second = len(low) - 1 - second_index
                if separation < 10 or separation > 70 or days_since_second < 3 or days_since_second > 40:
                    continue
                first_low = self._to_float(low.iloc[first_index])
                second_low = self._to_float(low.iloc[second_index])
                first_rsi = self._to_float(rsi_series.iloc[first_index])
                second_rsi = self._to_float(rsi_series.iloc[second_index])
                if None in (first_low, second_low, first_rsi, second_rsi) or not first_low or not second_low:
                    continue
                price_low_change = (second_low - first_low) / first_low
                rsi_divergence_points = second_rsi - first_rsi
                if price_low_change > -0.005 or price_low_change < -0.18 or rsi_divergence_points < 4.0:
                    continue
                post_second_low = self._to_float(low.iloc[second_index + 1:].min()) if second_index + 1 < len(low) else None
                if post_second_low is not None and post_second_low < second_low * 0.985:
                    continue
                rebound_from_second = (last_close - second_low) / second_low
                if rebound_from_second < 0.035:
                    continue

                trigger_candidates = []
                for value in (sma20, ema21):
                    if value is not None and value > 0:
                        trigger_candidates.append(value)
                recent_trigger = self._to_float(high.iloc[second_index + 1:].tail(12).max()) if second_index + 1 < len(high) else None
                if recent_trigger is not None and recent_trigger > 0:
                    trigger_candidates.append(recent_trigger)
                if not trigger_candidates:
                    continue
                trigger = min(trigger_candidates, key=lambda value: abs((last_close - value) / value))
                trigger_distance = (last_close - trigger) / trigger
                if trigger_distance < -0.045 or trigger_distance > 0.09:
                    continue

                recent_frame = frame.iloc[second_index:].copy()
                downside_volume_avg = None
                upside_volume_avg = None
                try:
                    recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
                    recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
                    recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
                    downside_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
                    upside_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
                except Exception:
                    pass
                volume_controlled = None
                if latest_volume is not None and latest_volume > 0 and vol20 is not None and vol20 > 0:
                    volume_controlled = latest_volume <= vol20 * 3.0
                selloff_disorderly = bool(
                    latest_volume is not None
                    and vol20 is not None
                    and vol20 > 0
                    and latest_volume > vol20 * 3.0
                    and last_close < close.iloc[-2]
                )
                constructive_volume = bool(
                    (upside_volume_avg is not None and downside_volume_avg is not None and downside_volume_avg > 0 and upside_volume_avg >= downside_volume_avg * 0.8)
                )
                volume_short_ok = bool(volume_controlled is True)
                volume_intermediate_ok = bool(vol20 is not None and vol20 > 0 and vol50 is not None and vol50 > 0 and vol20 >= vol50 * 0.60)
                volume_long_ok = bool(vol50 is not None and vol50 > 0 and vol120 is not None and vol120 > 0 and vol50 >= vol120 * 0.55)

                rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
                rsi_turning = bool(
                    rsi is not None
                    and 34 <= rsi <= 68
                    and (rsi_above_ma or rsi_change_5 is None or rsi_change_5 >= 0)
                )
                macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
                macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
                macd_recovering = macd_line_change_20 is not None and macd_line_change_20 > 0
                macd_ok = bool(macd_above_signal or macd_turning_up or macd_recovering)

                price_short_ok = bool(rebound_from_second >= 0.05 and trigger_distance >= -0.045)
                price_intermediate_ok = bool(trigger_distance >= -0.03 or (sma20 is not None and last_close >= sma20 * 0.97))
                price_long_ok = bool(sma50 is None or last_close >= sma50 * 0.85 or trigger_distance >= 0)
                short_timeframe_ok = bool(price_short_ok and (rsi_turning or macd_turning_up or volume_short_ok))
                intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_above_ma or macd_ok or volume_intermediate_ok))
                long_timeframe_ok = bool(price_long_ok and (rsi is None or rsi >= 34 or macd_recovering or volume_long_ok))
                timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
                indicator_confirmations = sum(1 for value in (rsi_turning, macd_ok, constructive_volume, timeframe_agreement_count >= 2) if value)

                trigger_reclaimed = trigger_distance >= 0
                setup_stage = 'Bullish RSI Divergence Triggered' if trigger_reclaimed else 'Bullish RSI Divergence'
                score = 0.0
                reasons = []
                if price_low_change <= 0:
                    score += 18
                    reasons.append('lower price low')
                else:
                    score += 12
                    reasons.append('similar price low')
                if rsi_divergence_points >= 7.5:
                    score += 20
                    reasons.append('strong RSI divergence')
                else:
                    score += 14
                    reasons.append('RSI higher low')
                if trigger_reclaimed:
                    score += 18
                    reasons.append('trigger reclaimed')
                else:
                    score += 12
                    reasons.append('near trigger')
                if rebound_from_second >= 0.07:
                    score += 10
                    reasons.append('price rebound')
                else:
                    score += 5
                if days_since_second <= 25:
                    score += 8
                    reasons.append('fresh divergence')
                elif days_since_second <= 35:
                    score += 6
                    reasons.append('recent divergence')
                else:
                    score += 4
                if rsi_turning:
                    score += 10
                    reasons.append('RSI turning up')
                if macd_ok:
                    score += 8
                    reasons.append('MACD improving')
                if constructive_volume:
                    score += 6
                    reasons.append('volume stabilizing')
                if volume_controlled is True:
                    score += 4
                    reasons.append('volume controlled')
                if timeframe_agreement_count >= 2:
                    score += 10
                    reasons.append('multi-timeframe confirmation')
                elif timeframe_agreement_count == 1:
                    score += 4
                if selloff_disorderly:
                    score -= 14

                snapshot = {
                    'close': self._pattern_snapshot_value(last_close),
                    'setup_stage': setup_stage,
                    'first_low': self._pattern_snapshot_value(first_low),
                    'second_low': self._pattern_snapshot_value(second_low),
                    'price_low_change_pct': self._pattern_snapshot_value(price_low_change * 100.0),
                    'first_rsi': self._pattern_snapshot_value(first_rsi),
                    'second_rsi': self._pattern_snapshot_value(second_rsi),
                    'rsi_divergence_points': self._pattern_snapshot_value(rsi_divergence_points),
                    'trigger': self._pattern_snapshot_value(trigger),
                    'trigger_distance_pct': self._pattern_snapshot_value(trigger_distance * 100.0),
                    'rebound_from_second_pct': self._pattern_snapshot_value(rebound_from_second * 100.0),
                    'days_between_lows': separation,
                    'days_since_second_low': days_since_second,
                    'trough_zone_count': trough_zone_count,
                    'sma20': self._pattern_snapshot_value(sma20),
                    'sma50': self._pattern_snapshot_value(sma50),
                    'sma200': self._pattern_snapshot_value(sma200),
                    'ema21': self._pattern_snapshot_value(ema21),
                    'rsi14': self._pattern_snapshot_value(rsi),
                    'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                    'rsi_state': 'turning up' if rsi_turning else ('above RSI MA' if rsi_above_ma else 'mixed'),
                    'macd_line': self._pattern_snapshot_value(macd_line),
                    'macd_signal': self._pattern_snapshot_value(macd_signal),
                    'macd_histogram': self._pattern_snapshot_value(macd_hist),
                    'macd_state': 'improving' if macd_ok else 'mixed',
                    'volume20': self._pattern_snapshot_value(vol20, 0),
                    'volume50': self._pattern_snapshot_value(vol50, 0),
                    'volume120': self._pattern_snapshot_value(vol120, 0),
                    'volume_state': 'stabilizing' if constructive_volume else ('controlled' if volume_controlled is True else ('disorderly' if volume_controlled is False else 'unavailable')),
                    'short_timeframe_confirmed': short_timeframe_ok,
                    'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                    'long_timeframe_confirmed': long_timeframe_ok,
                    'timeframe_agreement': f'{timeframe_agreement_count}/3',
                    'near_eligible': trough_zone_count >= 2 and price_low_change <= -0.005,
                }
                matched = bool(
                    not selloff_disorderly
                    and indicator_confirmations >= 2
                    and timeframe_agreement_count >= 2
                    and score >= 62
                )
                bounded_score = max(0.0, min(100.0, score))
                if (
                    (matched and (not best_matched or bounded_score > best_score))
                    or (not best_matched and not matched and bounded_score > best_score)
                ):
                    best_score = bounded_score
                    best_reasons = reasons[:8]
                    best_snapshot = snapshot
                    best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _history_signature(self, frame: Any) -> tuple[Any, ...]:
        if frame is None or getattr(frame, 'empty', True):
            return ('unavailable',)
        try:
            columns = [column for column in ('Open', 'High', 'Low', 'Close', 'Volume') if column in frame.columns]
            if not columns:
                return ('unavailable',)
            values = frame.loc[:, columns].apply(pd.to_numeric, errors='coerce')
            row_hashes = pd.util.hash_pandas_object(values, index=True).values.tobytes()
            digest = hashlib.blake2b(row_hashes, digest_size=12).hexdigest()
            return (
                len(frame),
                tuple(columns),
                str(frame.index[0]),
                str(frame.index[-1]),
                digest,
            )
        except Exception:
            return (len(frame),)

    def _evaluate_selected_patterns(
        self,
        symbol: str,
        frame: Any,
    ) -> dict[str, tuple[bool, float, list[str], dict[str, Any]]]:
        """Dispatch only selected evaluators and reuse fresh per-mode results."""
        evaluators = {
            'breakout': self._evaluate_breakout_pattern,
            'consolidation': self._evaluate_consolidation_pattern,
            'downtrend': self._evaluate_downtrend_pattern,
            'double_bottom': self._evaluate_double_bottom_pattern,
            'bullish_flag': self._evaluate_bullish_flag_pattern,
            'bullish_rsi_divergence': self._evaluate_bullish_rsi_divergence_pattern,
        }
        signature = self._history_signature(frame)
        results = {}
        frame_key = id(frame)
        self._active_pattern_signatures[frame_key] = signature
        try:
            for mode in sorted(self.pattern_modes):
                self._raise_if_cancelled()
                evaluator = evaluators.get(mode)
                if evaluator is None:
                    continue
                cache_key = (str(symbol or '').upper().strip(), mode, signature)
                cached = self._cache_get(self._evaluation_cache, cache_key, self._EVALUATION_CACHE_TTL_SECONDS)
                if cached is not None:
                    self._fetch_meta['evaluation_cache_hits'] += 1
                    results[mode] = cached
                    continue
                result = evaluator(frame)
                normalized_result = (
                    bool(result[0]),
                    float(result[1] or 0.0),
                    list(result[2] or []),
                    dict(result[3] or {}),
                )
                self._cache_put(self._evaluation_cache, cache_key, normalized_result)
                results[mode] = normalized_result
        finally:
            self._active_pattern_signatures.pop(frame_key, None)
        return results

    def _pattern_label(self, mode: str, snapshot: dict[str, Any], *, near: bool = False) -> str:
        defaults = {
            'breakout': 'Breakout Setup',
            'consolidation': 'Consolidation',
            'downtrend': 'Downtrend',
            'double_bottom': 'Double Bottom',
            'bullish_flag': 'Bullish Flag',
            'bullish_rsi_divergence': 'Bullish RSI Divergence',
        }
        label = str(snapshot.get('setup_stage') or defaults.get(mode, mode.replace('_', ' ').title()))
        return f'Near {label}' if near else label

    def _near_pattern_result(
        self,
        mode: str,
        result: tuple[bool, float, list[str], dict[str, Any]],
    ) -> bool:
        matched, score, _reasons, snapshot = result
        if matched or not snapshot:
            return False
        if snapshot.get('near_eligible') is False:
            return False
        threshold = 50.0 if mode == 'breakout' else 55.0
        if float(score or 0.0) < threshold:
            return False
        if mode == 'breakout' and str(snapshot.get('setup_stage') or '') in {'Late Breakout', 'No Breakout'}:
            return False
        return True

    def _primary_pattern_mode(
        self,
        modes: list[str],
        results: dict[str, tuple[bool, float, list[str], dict[str, Any]]],
    ) -> str:
        """Choose a deterministic primary mode without letting weak shapes outrank clear generic setups."""
        eligible = [mode for mode in modes if mode in results]
        if not eligible:
            return ''
        deterministic_order = {
            'bullish_flag': 6,
            'double_bottom': 5,
            'bullish_rsi_divergence': 4,
            'breakout': 3,
            'consolidation': 2,
            'downtrend': 1,
        }
        top_score = max(float(results[mode][1] or 0.0) for mode in eligible)
        structural_modes = {'bullish_flag', 'double_bottom', 'bullish_rsi_divergence'}
        close_structural = [
            mode
            for mode in eligible
            if mode in structural_modes and float(results[mode][1] or 0.0) >= top_score - 6.0
        ]
        choice_pool = close_structural or eligible
        return max(
            choice_pool,
            key=lambda mode: (
                float(results[mode][1] or 0.0),
                deterministic_order.get(mode, 0),
            ),
        )

    def _apply_pattern_analysis(self, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.pattern_modes or not candidates:
            return candidates, {'active': False, 'fallback_reason': ''}
        symbols = [
            str(candidate.get('symbol') or '').upper().strip()
            for candidate in candidates
            if str(candidate.get('symbol') or '').strip()
        ]
        histories = self._prepare_pattern_histories(symbols)
        required_rows = {
            'breakout': 70,
            'consolidation': 70,
            'downtrend': 70,
            'double_bottom': 90,
            'bullish_flag': 90,
            'bullish_rsi_divergence': 90,
        }
        analyzed = []
        history_success_count = 0
        for candidate in candidates:
            self._raise_if_cancelled()
            symbol = str(candidate.get('symbol') or '').upper().strip()
            frame = histories.get(symbol)
            available_modes = [
                mode for mode in self.pattern_modes
                if frame is not None and len(frame) >= required_rows.get(mode, 70)
            ]
            if available_modes:
                history_success_count += 1
            results = self._evaluate_selected_patterns(symbol, frame)
            strict_modes = [mode for mode, result in results.items() if result[0]]
            near_modes = [mode for mode, result in results.items() if self._near_pattern_result(mode, result)]
            tier = 'strict' if strict_modes else ('near' if near_modes else ('fallback' if available_modes else 'unavailable'))
            fallback_modes = [
                mode
                for mode in available_modes
                if mode in results and results[mode][3] and float(results[mode][1] or 0.0) > 0
            ]
            eligible_modes = strict_modes or near_modes or fallback_modes
            best_mode = self._primary_pattern_mode(eligible_modes, results)
            if best_mode:
                _matched, pattern_score, pattern_reasons, best_snapshot = results[best_mode]
                pattern_type = self._pattern_label(best_mode, best_snapshot, near=tier == 'near')
            else:
                pattern_score, pattern_reasons, pattern_type = 0.0, [], 'None'
            snapshot_modes = strict_modes or near_modes or ([best_mode] if best_mode else [])
            technical_snapshot = {
                mode: dict(results[mode][3] or {})
                for mode in snapshot_modes
                if results[mode][3]
            }
            analyzed.append({
                **candidate,
                'match_tier': tier,
                'matched_modes': sorted(strict_modes),
                'primary_pattern_mode': best_mode,
                'pattern_match': tier == 'strict',
                'pattern_type': pattern_type,
                'pattern_score': round(float(pattern_score or 0.0), 1),
                'pattern_reasons': list(pattern_reasons or []),
                'technical_snapshot': technical_snapshot,
            })

        strict = [candidate for candidate in analyzed if candidate.get('match_tier') == 'strict']
        near = [candidate for candidate in analyzed if candidate.get('match_tier') == 'near']
        if strict:
            selected_pool = strict
            fallback_reason = ''
        elif near:
            selected_pool = near
            fallback_reason = 'No strict setup matched; loaded closest technical candidates.'
        else:
            selected_pool = analyzed
            fallback_reason = (
                'Technical pattern history was unavailable; showing balanced scored candidates.'
                if history_success_count <= 0
                else 'No strong technical setup found; showing balanced scored candidates.'
            )
        tier_order = {'strict': 0, 'near': 1, 'fallback': 2, 'unavailable': 3}
        selected_pool.sort(key=lambda item: (
            tier_order.get(str(item.get('match_tier') or 'unavailable'), 4),
            -float(item.get('pattern_score') or 0.0),
            -float(item.get('score') or 0.0),
        ))
        for index, candidate in enumerate(selected_pool, start=1):
            candidate['rank'] = index
            if fallback_reason:
                candidate['pattern_fallback_reason'] = fallback_reason
        return selected_pool, {
            'active': True,
            'fallback_reason': fallback_reason,
            'history_success_count': history_success_count,
        }

    def _compact_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        rendered_fields = (
            'rank',
            'symbol',
            'name',
            'sector',
            'score',
            'reasons',
            'day_change_pct',
            'fifty_two_week_change_pct',
            'average_volume',
            'market_cap',
            'match_tier',
            'matched_modes',
            'primary_pattern_mode',
            'pattern_match',
            'pattern_type',
            'pattern_score',
            'pattern_reasons',
            'pattern_fallback_reason',
        )
        compact = {key: copy.deepcopy(candidate.get(key)) for key in rendered_fields if key in candidate}
        compact.setdefault('match_tier', 'fallback')
        compact.setdefault('matched_modes', [])
        compact.setdefault('pattern_match', False)
        compact.setdefault('pattern_type', 'None')
        compact.setdefault('pattern_score', 0.0)
        return compact

    def _metadata_patch(self, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        ticker_obj = yf.Ticker(symbol)
        info, warning = self._load_info(ticker_obj, symbol, quote)
        fresh_quote = dict(quote)
        for key, value in self._fallback_quote_from_info(symbol, info).items():
            if value not in (None, '', 'N/A'):
                fresh_quote[key] = value
        website = str(info.get('website') or '').strip()
        ir_url = str(info.get('irWebsite') or '').strip()
        if not ir_url:
            ir_url = f'https://www.google.com/search?q={symbol}+investor+relations'
        patch = {'info': info, 'quote': fresh_quote, 'website': website, 'ir_url': ir_url}
        if warning:
            patch['warnings'] = [warning]
        return patch

    def _news_patch(self, symbol: str) -> dict[str, Any]:
        articles, warning = self._load_news(yf.Ticker(symbol), symbol)
        patch = {'news': articles}
        if warning:
            patch.update({'news_status': warning, 'warnings': [warning]})
        return patch

    def _chart_patch(self, symbol: str) -> dict[str, Any]:
        frame = self._history_frames.get(symbol)
        if frame is None or getattr(frame, 'empty', True):
            frame = self._load_exact_symbol_history(symbol)
        return {'chart_history': self._chart_payload_from_frame(frame)}

    def _options_patch(self, symbol: str) -> dict[str, Any]:
        top_options, top_options_status = self._load_top_options(yf.Ticker(symbol), symbol)
        return {'top_options': top_options, 'top_options_status': top_options_status}

    def _load_payload_for_candidate(
        self,
        candidate: dict[str, Any],
        *,
        candidate_pool: list[dict[str, Any]],
        total: int,
        screening_summary: str,
    ) -> dict[str, Any] | None:
        symbol = str(candidate.get('symbol') or '').upper().strip()
        if not symbol:
            return None
        quote = dict(candidate.get('quote') or {})
        preloaded_metadata = None
        if not self._valid_candidate(symbol, {}, quote):
            preloaded_metadata = self._interruptible_call(
                lambda: self._metadata_patch(symbol, quote),
                label=f'{symbol} metadata',
            )
            quote = dict(preloaded_metadata.get('quote') or {})
            refreshed_candidate = self._candidate_for_target(symbol, quote)
            original_rank = candidate.get('rank', refreshed_candidate.get('rank'))
            candidate = {**candidate, **refreshed_candidate, 'rank': original_rank}
            for index, pool_candidate in enumerate(candidate_pool):
                if pool_candidate.get('symbol') == symbol:
                    candidate_pool[index] = {
                        **candidate,
                        'rank': pool_candidate.get('rank', candidate.get('rank')),
                    }
                    candidate = candidate_pool[index]
                    break
        if not self._valid_candidate(symbol, dict((preloaded_metadata or {}).get('info') or {}), quote):
            return None

        compact_pool = [self._compact_candidate(item) for item in candidate_pool]
        payload = {
            'symbol': symbol,
            'quote': quote,
            'info': {},
            'news': [],
            'chart_history': {'dates': [], 'closes': []},
            'top_options': [],
            'top_options_status': 'Loading top options...',
            'website': '',
            'ir_url': f'https://www.google.com/search?q={symbol}+investor+relations',
            'source': 'yfinance',
            'universe_total': total,
            'candidate_score': candidate.get('score'),
            'candidate_reasons': list(candidate.get('reasons') or []),
            'candidate_rank': candidate.get('rank'),
            'candidate_pool': compact_pool,
            'screening_summary': screening_summary,
            'pattern_modes': sorted(self.pattern_modes),
            'match_tier': candidate.get('match_tier') or ('fallback' if self.pattern_modes else 'fallback'),
            'matched_modes': list(candidate.get('matched_modes') or []),
            'primary_pattern_mode': candidate.get('primary_pattern_mode') or '',
            'pattern_match': bool(candidate.get('pattern_match')),
            'pattern_type': candidate.get('pattern_type') or 'None',
            'pattern_score': candidate.get('pattern_score') or 0.0,
            'pattern_reasons': list(candidate.get('pattern_reasons') or []),
            'technical_snapshot': dict(candidate.get('technical_snapshot') or {}),
            'pattern_fallback_reason': candidate.get('pattern_fallback_reason') or '',
            'warnings': [],
            'fetch_meta': copy.deepcopy(self._fetch_meta),
        }
        if preloaded_metadata:
            payload.update(preloaded_metadata)
        self._emit_progress('core', f'Loaded core quote for {symbol}.', current=1, total=1)
        self._emit_partial('core', payload, stage='core')

        def _load_chart() -> dict[str, Any]:
            if not self.pattern_modes and not self.target_symbol:
                symbols = [
                    str(item.get('symbol') or '').upper().strip()
                    for item in candidate_pool
                    if str(item.get('symbol') or '').strip()
                ]
                histories = self._prepare_pattern_histories(symbols)
                return {'chart_history': self._chart_payload_from_frame(histories.get(symbol))}
            return self._chart_patch(symbol)

        enrichment_tasks = {
            'chart': _load_chart,
            'news': lambda: self._news_patch(symbol),
            'options': lambda: self._options_patch(symbol),
        }
        if preloaded_metadata is None:
            enrichment_tasks['metadata'] = lambda: self._metadata_patch(symbol, quote)
        else:
            self._emit_partial('metadata', preloaded_metadata, stage='enrichment')

        completed_count = 0
        task_count = len(enrichment_tasks)
        self._emit_progress('enrichment', f'Loading research for {symbol}...', current=0, total=task_count)
        executor = ThreadPoolExecutor(max_workers=min(4, max(1, task_count)), thread_name_prefix='roll-enrich')
        try:
            futures = {
                executor.submit(
                    self._interruptible_call,
                    loader,
                    label=f'{symbol} {section}',
                ): section
                for section, loader in enrichment_tasks.items()
            }
            for future in self._iter_completed_futures(futures):
                self._raise_if_cancelled()
                section = futures[future]
                try:
                    patch = dict(future.result() or {})
                except _RandomStockCancelled:
                    raise
                except Exception as exc:
                    logger.info('Roll %s enrichment failed for %s: %s', section, symbol, exc)
                    warning = f'{section.title()} data could not be loaded.'
                    payload['warnings'].append(warning)
                    patch = {'warnings': list(payload['warnings'])}
                patch_warnings = [
                    str(value or '').strip()
                    for value in list(patch.pop('warnings', []) or [])
                    if str(value or '').strip()
                ]
                payload['warnings'].extend(patch_warnings)
                payload.update(patch)
                if section == 'chart' and not list((patch.get('chart_history') or {}).get('dates') or []):
                    payload['warnings'].append('Chart history could not be loaded.')
                if section == 'options' and str(patch.get('top_options_status') or '').startswith('Top options unavailable'):
                    payload['warnings'].append(str(patch.get('top_options_status')))
                payload['warnings'] = list(dict.fromkeys(payload['warnings']))
                patch['warnings'] = list(payload['warnings'])
                patch['fetch_meta'] = copy.deepcopy(self._fetch_meta)
                self._emit_partial(section, patch, stage='enrichment')
                completed_count += 1
                self._emit_progress(
                    'enrichment',
                    f'Loaded {section} for {symbol}.',
                    current=completed_count,
                    total=task_count,
                )
        finally:
            cancelled = self._is_cancelled()
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)
        payload['fetch_meta'] = copy.deepcopy(self._fetch_meta)
        return payload

    def _fallback_info_from_quote(self, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        return {
            'symbol': symbol,
            'shortName': quote.get('shortName') or quote.get('displayName') or symbol,
            'longName': quote.get('longName') or quote.get('shortName') or symbol,
            'regularMarketPrice': quote.get('regularMarketPrice'),
            'currentPrice': quote.get('regularMarketPrice'),
            'previousClose': quote.get('regularMarketPreviousClose'),
            'marketCap': quote.get('marketCap'),
            'trailingPE': quote.get('trailingPE'),
            'forwardPE': quote.get('forwardPE'),
            'beta': quote.get('beta'),
            'dividendYield': quote.get('dividendYield'),
            'averageVolume': quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'),
            'fiftyTwoWeekLow': quote.get('fiftyTwoWeekLow'),
            'fiftyTwoWeekHigh': quote.get('fiftyTwoWeekHigh'),
            'exchange': quote.get('exchange') or quote.get('fullExchangeName'),
            'currency': quote.get('currency'),
            'targetMeanPrice': quote.get('targetMeanPrice'),
        }

    def _load_info(
        self,
        ticker_obj: Any,
        symbol: str,
        quote: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        warning = ''
        try:
            info = ticker_obj.info
            if not isinstance(info, dict):
                info = {}
                warning = f'Metadata refresh returned no usable data for {symbol}; using screener quote data.'
            elif not any(value not in (None, '', 'N/A') for value in info.values()):
                warning = f'Metadata refresh returned no usable data for {symbol}; using screener quote data.'
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused random roll metadata for %s; using screener quote fallback.', symbol)
            else:
                logger.info('Random roll metadata fetch failed for %s: %s', symbol, exc)
            info = {}
            warning = f'Metadata refresh failed for {symbol}; using screener quote data.'
        fallback = self._fallback_info_from_quote(symbol, quote)
        for key, value in fallback.items():
            if info.get(key) in (None, '', 'N/A') and value not in (None, '', 'N/A'):
                info[key] = value
        return info, warning

    def _valid_candidate(self, symbol: str, info: dict[str, Any], quote: dict[str, Any]) -> bool:
        if not symbol:
            return False
        name = info.get('longName') or info.get('shortName') or quote.get('longName') or quote.get('shortName')
        price = (
            info.get('regularMarketPrice')
            or info.get('currentPrice')
            or quote.get('regularMarketPrice')
            or quote.get('regularMarketPreviousClose')
        )
        return bool(name and price not in (None, '', 'N/A'))

    def _parse_news_item(self, item: Any, symbol: str) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        content = item.get('content') or {}
        title = str(content.get('title') or item.get('title') or '').strip()
        if not title:
            return None
        source = str(content.get('provider', {}).get('displayName') or item.get('publisher') or 'N/A').strip() or 'N/A'
        pub_date = content.get('pubDate') or item.get('providerPublishTime') or ''
        time_text = '--:--'
        timestamp = 0.0
        if isinstance(pub_date, (int, float)) and not isinstance(pub_date, bool):
            timestamp = float(pub_date)
            try:
                time_text = datetime.datetime.fromtimestamp(float(pub_date)).strftime('%H:%M')
            except Exception:
                pass
        elif pub_date:
            try:
                parsed = datetime.datetime.fromisoformat(str(pub_date).replace('Z', '+00:00'))
                time_text = parsed.strftime('%H:%M')
                timestamp = parsed.timestamp()
            except Exception:
                time_text = str(pub_date)[:10]
        url_data = content.get('canonicalUrl') or content.get('clickThroughUrl') or item.get('link') or ''
        url = url_data.get('url', '') if isinstance(url_data, dict) else str(url_data or '')
        return {
            'ticker': symbol,
            'title': title,
            'source': source,
            'time': time_text,
            'url': url,
            'category': 'stock',
            '_ts': timestamp,
        }

    def _load_news(self, ticker_obj: Any, symbol: str) -> tuple[list[dict[str, Any]], str]:
        try:
            raw_items = list(getattr(ticker_obj, 'news', []) or [])[:12]
        except Exception as exc:
            logger.info('Roll news fetch failed for %s: %s', symbol, exc)
            return [], f'Recent headlines could not be loaded for {symbol}.'
        articles = []
        for item in raw_items:
            article = self._parse_news_item(item, symbol)
            if article is not None:
                articles.append(article)
        return articles, ''

    def _load_chart_history(self, ticker_obj: Any) -> dict[str, Any]:
        try:
            history = ticker_obj.history(period='1y', interval='1d', auto_adjust=False, actions=False)
        except Exception:
            return {'dates': [], 'closes': []}
        normalized = self._normalize_history_frame(history)
        return self._chart_payload_from_frame(normalized)

    def _chart_payload_from_frame(self, history: Any) -> dict[str, Any]:
        if history is None or getattr(history, 'empty', True) or 'Close' not in history.columns:
            return {'dates': [], 'closes': []}
        required = {'Open', 'High', 'Low', 'Close'}
        has_ohlc = required.issubset(set(history.columns))
        closes = history['Close'].dropna()
        if closes.empty:
            return {'dates': [], 'closes': []}
        dates = []
        opens = []
        highs = []
        lows = []
        close_values = []
        volumes = []
        for index_value, row in history.iterrows():
            close_value = row.get('Close')
            try:
                close_numeric = float(close_value)
            except Exception:
                continue
            if not math.isfinite(close_numeric):
                continue
            try:
                date_text = pd.Timestamp(index_value).strftime('%Y-%m-%d')
            except Exception:
                date_text = str(index_value)[:10]
            dates.append(date_text)
            close_values.append(close_numeric)
            if has_ohlc:
                for source, target in (
                    ('Open', opens),
                    ('High', highs),
                    ('Low', lows),
                ):
                    try:
                        value = float(row.get(source))
                    except Exception:
                        value = close_numeric
                    target.append(value if math.isfinite(value) else close_numeric)
            volume_value = 0.0
            if 'Volume' in history.columns:
                try:
                    volume_value = float(row.get('Volume') or 0.0)
                except Exception:
                    volume_value = 0.0
            volumes.append(volume_value if math.isfinite(volume_value) else 0.0)
        payload = {'dates': dates, 'closes': close_values, 'volumes': volumes}
        if has_ohlc and len(opens) == len(close_values) and len(highs) == len(close_values) and len(lows) == len(close_values):
            payload.update({'opens': opens, 'highs': highs, 'lows': lows})
        return payload

    def _load_top_option_for_expiry(
        self,
        ticker_obj: Any,
        symbol: str,
        expiry: str,
        *,
        allow_stale: bool = False,
    ) -> dict[str, Any] | None:
        cache_key = (str(symbol or '').upper().strip(), str(expiry or '').strip())
        stale_wrapper = (
            self._cache_get_stale(
                self._option_chain_cache,
                cache_key,
                max_age=self._OPTION_CHAIN_STALE_TTL_SECONDS,
            )
            if allow_stale
            else None
        )
        cached_wrapper = self._cache_get(
            self._option_chain_cache,
            cache_key,
            self._OPTION_CHAIN_CACHE_TTL_SECONDS,
        )
        if isinstance(cached_wrapper, dict) and 'record' in cached_wrapper:
            self._fetch_meta['option_chain_cache_hits'] += 1
            return cached_wrapper.get('record')
        try:
            with YF_LOCK:
                chain = ticker_obj.option_chain(expiry)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
        except Exception as exc:
            logger.info('Roll top options fetch failed for %s %s: %s', symbol, expiry, exc)
            if isinstance(stale_wrapper, dict) and stale_wrapper.get('record') is not None:
                if not hasattr(self, '_option_stale_expiries'):
                    self._option_stale_expiries = set()
                self._option_stale_expiries.add(expiry)
                return stale_wrapper['record']
            return None
        frames = []
        if calls is not None and not calls.empty:
            calls['type'] = 'Call'
            frames.append(calls)
        if puts is not None and not puts.empty:
            puts['type'] = 'Put'
            frames.append(puts)
        if not frames:
            self._cache_put(self._option_chain_cache, cache_key, {'record': None})
            return None
        options_df = pd.concat(frames, ignore_index=True)
        if options_df is None or options_df.empty:
            self._cache_put(self._option_chain_cache, cache_key, {'record': None})
            return None
        options_df['ticker'] = symbol
        options_df['expiration'] = expiry
        for column in ('strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility'):
            if column not in options_df.columns:
                options_df[column] = 0.0
            options_df[column] = pd.to_numeric(options_df[column], errors='coerce')
        options_df['volume'] = options_df['volume'].fillna(0.0)
        options_df['openInterest'] = options_df['openInterest'].fillna(0.0)
        if 'type' not in options_df.columns:
            options_df['type'] = ''
        top_row = options_df.sort_values(by=['volume', 'openInterest'], ascending=False, na_position='last').head(1)
        if top_row.empty:
            self._cache_put(self._option_chain_cache, cache_key, {'record': None})
            return None
        row = top_row.iloc[0]
        record = {
            'ticker': symbol,
            'type': str(row.get('type', '') or ''),
            'expiration': expiry,
            'strike': row.get('strike'),
            'lastPrice': row.get('lastPrice'),
            'volume': row.get('volume'),
            'openInterest': row.get('openInterest'),
            'impliedVolatility': row.get('impliedVolatility'),
        }
        self._cache_put(self._option_chain_cache, cache_key, {'record': record})
        return record

    def _load_top_options(self, ticker_obj: Any, symbol: str) -> tuple[list[dict[str, Any]], str]:
        symbol = str(symbol or '').upper().strip()
        cached_expiries = self._cache_get(
            self._option_expiry_cache,
            symbol,
            self._OPTION_EXPIRY_CACHE_TTL_SECONDS,
        )
        if isinstance(cached_expiries, list):
            expiries = cached_expiries
            self._fetch_meta['option_expiry_cache_hit'] = True
        else:
            try:
                with YF_LOCK:
                    expiries = [str(expiry or '').strip() for expiry in list(ticker_obj.options or []) if str(expiry or '').strip()]
            except Exception as exc:
                logger.info('Roll top options expirations unavailable for %s: %s', symbol, exc)
                return [], 'Top options unavailable: expirations could not be loaded.'
            self._cache_put(self._option_expiry_cache, symbol, expiries)
        if not expiries:
            return [], 'No options expirations were available for this ticker.'

        records_by_expiry = {}
        failed_count = 0
        self._option_stale_expiries = set()
        scanned_expiries = expiries[:self._MAX_OPTION_EXPIRIES]
        for expiry in scanned_expiries:
            self._raise_if_cancelled()
            record = self._load_top_option_for_expiry(
                ticker_obj,
                symbol,
                expiry,
                allow_stale=True,
            )
            if record is None:
                failed_count += 1
                continue
            records_by_expiry[expiry] = record

        records = [records_by_expiry[expiry] for expiry in scanned_expiries if expiry in records_by_expiry]
        if not records:
            return [], 'Top options unavailable: near-term option-chain loads failed.'
        status = ''
        if self._option_stale_expiries:
            stale_text = ', '.join(sorted(self._option_stale_expiries))
            status = f'Top options include stale cached chains for {stale_text}; expirations were revalidated.'
        elif failed_count:
            status = f'Top options loaded for {len(records)} of {len(scanned_expiries)} near-term expirations.'
        return records, status

    def fetch(self) -> dict[str, Any]:
        self._raise_if_cancelled()
        if self.target_symbol:
            total = 0
            self._emit_progress('screening', f'Loading exact symbol {self.target_symbol}.', current=1, total=1)
            candidate_pool = [{
                'symbol': self.target_symbol,
                'name': self.target_symbol,
                'sector': 'N/A',
                'score': 0.0,
                'reasons': ['selected candidate'],
                'rank': 0,
                'quote': {},
            }]
        else:
            query = self._query()
            self._emit_progress('screening', 'Loading liquid US equity screening buckets...', current=0, total=1)
            total, buckets = self._screening_snapshot(query)
            if total <= 0:
                raise RuntimeError('No liquid US equity candidates were returned by yfinance.')
            candidate_pool = self._build_candidate_pool(query, total, buckets)
            if not candidate_pool:
                raise RuntimeError('Could not find a scored candidate with usable quote data.')
            self._emit_progress('screening', f'Loaded {len(candidate_pool)} candidate quotes.', current=1, total=1)

        pattern_status = {'active': False, 'fallback_reason': ''}
        if self.pattern_modes:
            self._emit_progress(
                'history',
                f'Loading one-year daily history for {len(candidate_pool)} candidates...',
                current=0,
                total=len(candidate_pool),
            )
            pattern_pool, pattern_status = self._apply_pattern_analysis(candidate_pool)
            if pattern_pool:
                candidate_pool = pattern_pool
            elif pattern_status.get('fallback_reason'):
                for candidate in candidate_pool:
                    candidate['pattern_fallback_reason'] = str(pattern_status.get('fallback_reason') or '')
            self._emit_progress(
                'history',
                f'Analyzed {len(candidate_pool)} technical candidates.',
                current=len(candidate_pool),
                total=len(candidate_pool),
            )
        screening_summary = (
            f'Loaded exact-symbol research for {self.target_symbol}.'
            if self.target_symbol
            else (
                f'Sampled and scored {len(candidate_pool)} candidates from a universe of {total:,} yfinance-screened US equities '
                f'with market cap above $1B and 3-month average volume above 1M.'
            )
        )
        if self.pattern_modes:
            mode_labels = {
                'breakout': 'breakout',
                'consolidation': 'consolidation',
                'downtrend': 'downtrend',
                'double_bottom': 'double bottom',
                'bullish_flag': 'bullish flag',
                'bullish_rsi_divergence': 'bullish RSI divergence',
            }
            mode_text = ' or '.join(mode_labels.get(mode, mode) for mode in sorted(self.pattern_modes))
            screening_summary = f'{screening_summary} Searched for {mode_text} setups using one-year daily history.'
        if pattern_status.get('fallback_reason'):
            for candidate in candidate_pool:
                candidate['pattern_fallback_reason'] = pattern_status.get('fallback_reason')
        compact_pool = [self._compact_candidate(candidate) for candidate in candidate_pool]
        candidates_patch = {
            'candidate_pool': compact_pool,
            'universe_total': total,
            'screening_summary': screening_summary,
            'pattern_modes': sorted(self.pattern_modes),
            'warnings': [],
            'fetch_meta': copy.deepcopy(self._fetch_meta),
        }
        self._emit_progress(
            'candidates',
            f'Ranked {len(compact_pool)} candidates.',
            current=len(compact_pool),
            total=len(compact_pool),
        )
        self._emit_partial('candidates', candidates_patch, stage='candidates')
        self._raise_if_cancelled()
        selected = self._select_candidate(candidate_pool)
        payload = self._load_payload_for_candidate(
            selected,
            candidate_pool=candidate_pool,
            total=total,
            screening_summary=screening_summary,
        )
        if payload is not None:
            return payload
        raise RuntimeError('Could not find a scored candidate with usable company and price data.')

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch())
        except _RandomStockCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.error.emit(f'Random roll failed: {exc}')
