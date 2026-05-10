from __future__ import annotations
from copy import deepcopy
import re
import time

from typing import Any

from ..cache import CacheManager
from ..constants import SECTOR_DATA
from ..data_service.results import attach_market_data_result, make_market_data_error, make_market_data_meta
from .news_sources import fetch_keyless_trader_news
from ..dependencies import (
    QObject,
    ThreadPoolExecutor,
    datetime,
    is_yahoo_unauthorized_error,
    logger,
    pd,
    pyqtSignal,
    threading,
    yf,
)

DEFAULT_BATCH_SYMBOLS = ['SPY', 'DX-Y.NYB', '^VIX', 'GLD', 'CL=F']
MACRO_TICKERS = ['SPY', 'QQQ', 'GLD', 'CL=F', '^VIX', '^TNX', 'DX-Y.NYB']
OTHER_NEWS_QUERIES = ['market movers', 'earnings movers', 'sector rotation', 'analyst upgrades']
OTHER_NEWS_SECTOR_TICKERS = ['XLK', 'XLF', 'XLE', 'XLV', 'XLY', 'XLI', 'XLP', 'XLU', 'XLB', 'XLRE']
OTHER_NEWS_FOCUS_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'AVGO', 'AMD', 'ORCL',
    'JPM', 'BAC', 'GS', 'MS',
    'LLY', 'UNH', 'JNJ', 'MRK',
    'AMZN', 'TSLA', 'HD', 'MCD',
    'XOM', 'CVX', 'COP', 'SLB',
    'GOOGL', 'META', 'NFLX', 'DIS',
    'GE', 'CAT', 'BA', 'RTX',
    'WMT', 'COST', 'PG', 'KO',
    'NEE', 'DUK', 'PLD', 'AMT',
    'LIN', 'FCX', 'NEM',
    'COIN', 'MSTR',
]
OTHER_NEWS_LIMIT = 36
OTHER_NEWS_CANDIDATE_LIMIT = 80
OTHER_NEWS_SEARCH_LIMIT = 8
OTHER_NEWS_PER_SECTOR_LIMIT = 2
OTHER_NEWS_PER_FOCUS_TICKER_LIMIT = 2
OPTION_BUCKET_TEMPLATE = {'0_week': [], '2_weeks': [], '4_weeks': []}
OPTION_BUCKET_OFFSETS = (('0_week', 0), ('2_weeks', 14), ('4_weeks', 28))
CHART_CACHE_PERIOD_DAY_MAP = {
    'd': 1.0,
    'wk': 7.0,
    'mo': 30.0,
    'y': 365.0,
}


class DataWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    _DETAILS_CACHE_TTL_SECONDS = 900.0
    _NON_CHART_SNAPSHOT_TTL_SECONDS = 30.0
    _stock_details_cache: dict[str, tuple[float, dict[str, Any]]] = {}
    _macro_news_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    _other_news_cache: tuple[float, list[dict[str, Any]]] | None = None
    _non_chart_snapshot_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
    _details_cache_lock = threading.Lock()
    _non_chart_snapshot_lock = threading.Lock()

    def __init__(
        self,
        tickers: Any,
        chart_configs: Any,
        request_id: int = 0,
        cancel_check: Any = None,
        cache_manager: Any = None,
        refresh_reason: str = 'full',
        allow_non_chart_reuse: bool = False,
    ) -> None:
        super().__init__()
        self.tickers = list(tickers) if isinstance(tickers, (list, tuple)) else []
        self.chart_configs = chart_configs
        self.request_id = int(request_id)
        self.cancel_check = cancel_check
        self._ticker_cache: dict[str, Any] = {}
        self._cache_manager = cache_manager if cache_manager is not None else CacheManager()
        self.refresh_reason = str(refresh_reason or 'full')
        self.allow_non_chart_reuse = bool(allow_non_chart_reuse)

    def _is_cancelled(self) -> bool:
        """Return whether the parent request no longer needs this worker result."""
        try:
            return bool(self.cancel_check and self.cancel_check())
        except Exception:
            return False

    def _ticker(self, symbol: Any) -> Any:
        key = str(symbol or '').strip()
        ticker_obj = self._ticker_cache.get(key)
        if ticker_obj is None:
            ticker_obj = yf.Ticker(key)
            self._ticker_cache[key] = ticker_obj
        return ticker_obj

    def _normalize_chart_configs(self) -> list[tuple[str, Any, Any]]:
        configs = []
        if isinstance(self.chart_configs, (list, tuple)):
            for config in self.chart_configs:
                if isinstance(config, (list, tuple)) and len(config) >= 3:
                    symbol = str(config[0] or '').strip()
                    if symbol:
                        configs.append((symbol, config[1], config[2]))
        elif isinstance(self.chart_configs, dict):
            symbol = str(self.chart_configs.get('symbol') or '').strip()
            period = self.chart_configs.get('period')
            interval = self.chart_configs.get('interval')
            if symbol and period and interval:
                configs.append((symbol, period, interval))
        return configs

    def _dedupe_symbols(self, *groups: Any) -> list[str]:
        seen = set()
        ordered = []
        for group in groups:
            if not isinstance(group, (list, tuple)):
                continue
            for symbol in group:
                text = str(symbol or '').strip()
                if text and text not in seen:
                    seen.add(text)
                    ordered.append(text)
        return ordered

    def _fetch_ticker_signature(self) -> tuple[str, ...]:
        """Return a normalized cache signature for the current non-chart ticker universe."""
        seen = set()
        normalized = []
        for symbol in self.tickers:
            text = str(symbol or '').upper().strip()
            if text and text not in seen:
                seen.add(text)
                normalized.append(text)
        return tuple(sorted(normalized))

    def _load_cached_non_chart_snapshot(self, signature: tuple[str, ...]) -> tuple[dict[str, Any] | None, float]:
        """Return a deep-copied cached non-chart snapshot when it is still fresh."""
        now = time.time()
        with self._non_chart_snapshot_lock:
            cached = self._non_chart_snapshot_cache.get(signature)
            if not cached:
                return None, 0.0
            cached_at, payload = cached
            age_seconds = now - cached_at
            if age_seconds >= self._NON_CHART_SNAPSHOT_TTL_SECONDS:
                self._non_chart_snapshot_cache.pop(signature, None)
                return None, age_seconds
            return deepcopy(payload), age_seconds

    def _save_cached_non_chart_snapshot(self, signature: tuple[str, ...], payload: dict[str, Any]) -> None:
        """Store a deep-copied non-chart snapshot for short-lived row-click reuse."""
        with self._non_chart_snapshot_lock:
            self._non_chart_snapshot_cache[signature] = (time.time(), deepcopy(payload))

    def _download_batch_data(self, symbols: list[str]) -> Any:
        if not symbols:
            return pd.DataFrame()
        logger.debug('Downloading batch data for: %s', symbols)
        return yf.download(
            symbols,
            period='5d',
            interval='1d',
            group_by='ticker',
            progress=False,
            prepost=True,
        )

    def _extract_close_series(self, batch_data: Any, all_symbols: list[str], symbol: str) -> Any:
        if batch_data is None or batch_data.empty:
            return None
        if isinstance(batch_data.columns, pd.MultiIndex):
            level_zero = batch_data.columns.get_level_values(0)
            level_one = batch_data.columns.get_level_values(1)
            if symbol in level_zero:
                symbol_frame = batch_data[symbol]
            elif symbol in level_one:
                symbol_frame = batch_data.xs(symbol, axis=1, level=1)
            else:
                return None
            if 'Close' not in symbol_frame.columns:
                return None
            return symbol_frame['Close'].dropna()
        if symbol in batch_data.columns:
            return batch_data[symbol].dropna()
        if len(all_symbols) == 1 and 'Close' in batch_data.columns and all_symbols[0] == symbol:
            return batch_data['Close'].dropna()
        return None

    def _load_close_series(self, symbol: str, batch_data: Any, all_symbols: list[str]) -> Any:
        close = self._extract_close_series(batch_data, all_symbols, symbol)
        if close is not None and not close.empty:
            return close
        history = self._ticker(symbol).history(period='5d', interval='1d')
        if history is None or history.empty or 'Close' not in history.columns:
            return None
        return history['Close'].dropna()

    def _build_price_payload(self, close: Any) -> Any:
        if close is None or close.empty:
            return None
        current = float(close.iloc[-1])
        if len(close) >= 2:
            previous = float(close.iloc[-2])
            abs_change = current - previous
            change = abs_change / previous * 100 if previous else 0.0
            return {'price': current, 'change': change, 'abs_change': abs_change}
        return {'price': current, 'change': 0.0, 'abs_change': 0.0}

    def _build_market_payload(self, close: Any) -> Any:
        payload = self._build_price_payload(close)
        if payload is None:
            return None
        return {'price': payload['price'], 'change': payload['change']}

    def _download_symbol_frame(self, symbol: str, period: Any, interval: Any, *, auto_adjust: bool = False) -> Any:
        """Fetch one symbol's OHLCV frame with a history fallback for brittle assets like ETFs."""
        try:
            frame = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=auto_adjust)
        except Exception as exc:
            logger.info('Primary download failed for %s period=%s interval=%s: %s', symbol, period, interval, exc)
            frame = None
        normalized = self._normalize_chart_frame(symbol, frame)
        if normalized is not None:
            return normalized
        try:
            history = self._ticker(symbol).history(period=period, interval=interval, auto_adjust=auto_adjust)
        except Exception as exc:
            logger.info('History fallback failed for %s period=%s interval=%s: %s', symbol, period, interval, exc)
            history = None
        return self._normalize_chart_frame(symbol, history)

    def _collect_portfolio_quotes(self, batch_data: Any, all_symbols: list[str]) -> dict[str, dict[str, float]]:
        portfolio_info = {}
        for symbol in self.tickers:
            try:
                payload = self._build_price_payload(self._load_close_series(symbol, batch_data, all_symbols))
            except Exception:
                continue
            if payload is not None:
                portfolio_info[symbol] = payload
        return portfolio_info

    def _collect_market_quotes(self, batch_data: Any, all_symbols: list[str]) -> dict[str, dict[str, float]]:
        market_data = {}
        idx_map = {'SPY': 'SPY', 'DX-Y.NYB': 'DXY', '^VIX': 'VIX', 'GLD': 'GLD', 'CL=F': 'WTI'}
        for symbol, display_name in idx_map.items():
            try:
                payload = self._build_market_payload(self._load_close_series(symbol, batch_data, all_symbols))
            except Exception:
                payload = None
            if payload is not None:
                market_data[display_name] = payload
        return market_data

    def _collect_non_chart_payload(self) -> dict[str, Any] | None:
        """Fetch the shared non-chart dashboard payload."""
        all_symbols = self._dedupe_symbols(self.tickers, DEFAULT_BATCH_SYMBOLS)
        batch_data = self._download_batch_data(all_symbols)
        if self._is_cancelled():
            return None
        portfolio_info = self._collect_portfolio_quotes(batch_data, all_symbols)
        market_data = self._collect_market_quotes(batch_data, all_symbols)
        targets, news_list = self._collect_targets_and_news(portfolio_info)
        if self._is_cancelled():
            return None
        return {
            'portfolio': portfolio_info,
            'market': market_data,
            'targets': targets,
            'news': news_list,
        }

    def _parse_news_item(self, item: Any, ticker: str, category: str) -> dict[str, Any]:
        content = item.get('content') or {}
        title = content.get('title') or item.get('title', 'N/A')
        source = content.get('provider', {}).get('displayName') or item.get('publisher', 'N/A')
        pub_date = content.get('pubDate') or item.get('providerPublishTime', '')
        time_text = '--:--'
        ts = 0
        if isinstance(pub_date, (int, float)):
            ts = pub_date
            try:
                time_text = datetime.datetime.fromtimestamp(pub_date).strftime('%H:%M')
            except Exception:
                pass
        elif pub_date:
            try:
                parsed = datetime.datetime.fromisoformat(str(pub_date).replace('Z', '+00:00'))
                time_text = parsed.strftime('%H:%M')
                ts = parsed.timestamp()
            except Exception:
                time_text = str(pub_date)[:10]
        url_data = content.get('canonicalUrl') or content.get('clickThroughUrl') or item.get('link', '')
        url = url_data.get('url', '') if isinstance(url_data, dict) else str(url_data)
        return {
            'ticker': ticker,
            'title': title,
            'source': source,
            'time': time_text,
            'url': url,
            'category': category,
            '_ts': ts,
        }

    def _read_news_items(self, ticker_obj: Any, ticker: str, category: str) -> list[dict[str, Any]]:
        articles = []
        try:
            news_items = getattr(ticker_obj, 'news', [])[:5]
        except Exception:
            return articles
        for item in news_items:
            try:
                articles.append(self._parse_news_item(item, ticker, category))
            except Exception:
                continue
        return articles

    def _article_dedupe_key(self, article: dict[str, Any]) -> str:
        """Return a stable key for cross-section news dedupe."""
        url = str(article.get('url') or '').strip().lower()
        if url:
            return f'url:{url}'
        title = str(article.get('title') or '').strip().lower()
        return f'title:{title}' if title else ''

    def _dedupe_news(self, articles: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop articles already present in earlier-priority news sections."""
        seen = {key for key in (self._article_dedupe_key(article) for article in existing) if key}
        unique = []
        for article in articles:
            key = self._article_dedupe_key(article)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            unique.append(article)
        return unique

    def _article_related_tickers(self, item: Any) -> list[str]:
        related = []
        if isinstance(item, dict):
            related_raw = item.get('relatedTickers') or []
            if isinstance(related_raw, (list, tuple)):
                related = [str(ticker or '').strip().upper() for ticker in related_raw if str(ticker or '').strip()]
        return related

    def _parse_other_news_item(self, item: Any, fallback_ticker: str = 'OTHER') -> dict[str, Any]:
        related = self._article_related_tickers(item)
        ticker = ', '.join(related[:3]) if related else 'OTHER'
        if ticker == 'OTHER':
            ticker = fallback_ticker
        return self._parse_news_item(item, ticker, 'other')

    def _article_mentions_blocked_ticker(self, article: dict[str, Any], blocked_tickers: set[str]) -> bool:
        article_tickers = self._article_ticker_set(article)
        if article_tickers & blocked_tickers:
            return True
        title = str(article.get('title') or '').upper()
        for ticker in blocked_tickers:
            if len(ticker) < 2 or any(ch in ticker for ch in ('^', '=', '-', '.')):
                continue
            if re.search(rf'(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])', title):
                return True
        return False

    def _article_ticker_set(self, article: dict[str, Any]) -> set[str]:
        """Return normalized ticker symbols attached to a news article."""
        ticker_text = str(article.get('ticker') or '').upper()
        return {
            text.strip()
            for text in ticker_text.split(',')
            if text.strip() and text.strip() != 'OTHER'
        }

    def _news_ticker_set(self, articles: list[dict[str, Any]]) -> set[str]:
        """Return every normalized ticker already represented by a news section."""
        tickers: set[str] = set()
        for article in articles:
            tickers.update(self._article_ticker_set(article))
        return tickers

    def _other_focus_tickers(self) -> list[str]:
        """Return the broad ticker universe used to source the Other news panel."""
        sector_symbols = []
        for symbols in SECTOR_DATA.values():
            sector_symbols.extend(list(symbols)[:3])
        return self._dedupe_symbols(OTHER_NEWS_FOCUS_TICKERS, sector_symbols, OTHER_NEWS_SECTOR_TICKERS)

    def _select_diverse_other_news(self, articles: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pick trader-ranked All News articles without over-concentrating one ticker/source."""
        candidates = self._dedupe_news(articles, existing)
        ticker_buckets: dict[str, list[dict[str, Any]]] = {}
        for article in sorted(candidates, key=lambda item: (item.get('_trader_score', 0), item.get('_ts', 0)), reverse=True):
            tickers = sorted(self._article_ticker_set(article))
            bucket_key = tickers[0] if tickers else str(article.get('source') or 'OTHER')
            ticker_buckets.setdefault(bucket_key, []).append(article)
        selected = []
        while len(selected) < OTHER_NEWS_LIMIT and ticker_buckets:
            for key in list(ticker_buckets.keys()):
                if len(selected) >= OTHER_NEWS_LIMIT:
                    break
                bucket = ticker_buckets.get(key, [])
                if not bucket:
                    ticker_buckets.pop(key, None)
                    continue
                selected.append(bucket.pop(0))
                if not bucket:
                    ticker_buckets.pop(key, None)
        return selected

    def _target_payload(self, ticker: str, current_price: Any, info: Any) -> dict[str, Any]:
        return {
            'ticker': ticker,
            'current': current_price,
            'target': info.get('targetMeanPrice', 'N/A') if isinstance(info, dict) else 'N/A',
        }

    def _fetch_stock_details(self, ticker: str, portfolio_info: dict[str, Any]) -> Any:
        now = time.time()
        with self._details_cache_lock:
            cached = self._stock_details_cache.get(ticker)
            if cached and (now - cached[0]) < self._DETAILS_CACHE_TTL_SECONDS:
                return {
                    'targets': dict(cached[1]['targets']),
                    'news': [dict(item) for item in cached[1]['news']],
                }
        try:
            ticker_obj = self._ticker(ticker)
        except Exception as exc:
            logger.info('Unable to create yfinance ticker for %s: %s', ticker, exc)
            return None
        info = {}
        try:
            info = ticker_obj.info
            if not isinstance(info, dict):
                info = {}
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional target metadata for %s; continuing with N/A target.', ticker)
            else:
                logger.info('Target metadata fetch failed for %s: %s', ticker, exc)
        payload = {
            'targets': self._target_payload(ticker, portfolio_info.get(ticker, {}).get('price', 0), info),
            'news': self._read_news_items(ticker_obj, ticker, 'portfolio'),
        }
        with self._details_cache_lock:
            self._stock_details_cache[ticker] = (
                now,
                {
                    'targets': dict(payload['targets']),
                    'news': [dict(item) for item in payload['news']],
                },
            )
        return payload

    def _fetch_macro_news(self, ticker: str) -> list[dict[str, Any]]:
        now = time.time()
        with self._details_cache_lock:
            cached = self._macro_news_cache.get(ticker)
            if cached and (now - cached[0]) < self._DETAILS_CACHE_TTL_SECONDS:
                return [dict(item) for item in cached[1]]
        try:
            articles = self._read_news_items(self._ticker(ticker), ticker, 'macro')
            with self._details_cache_lock:
                self._macro_news_cache[ticker] = (now, [dict(item) for item in articles])
            return articles
        except Exception:
            return []

    def _fetch_other_news(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._details_cache_lock:
            cached = self._other_news_cache
            if cached and (now - cached[0]) < self._DETAILS_CACHE_TTL_SECONDS:
                return [dict(item) for item in cached[1]]
        articles = fetch_keyless_trader_news(
            self._other_focus_tickers(),
            limit=OTHER_NEWS_CANDIDATE_LIMIT,
            candidate_limit=OTHER_NEWS_CANDIDATE_LIMIT,
            cancel_check=self._is_cancelled,
        )
        articles = self._dedupe_news(articles, [])[:OTHER_NEWS_CANDIDATE_LIMIT]
        with self._details_cache_lock:
            self.__class__._other_news_cache = (now, [dict(item) for item in articles])
        return articles

    def _filter_other_news(self, articles: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._select_diverse_other_news(articles, existing)

    def _executor_workers(self, size: int, upper_bound: int = 8) -> int:
        return max(1, min(size, upper_bound))

    def _collect_targets_and_news(self, portfolio_info: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        targets = []
        news_list = []
        if self.tickers:
            with ThreadPoolExecutor(max_workers=self._executor_workers(len(self.tickers))) as executor:
                for result in executor.map(lambda ticker: self._fetch_stock_details(ticker, portfolio_info), self.tickers):
                    if self._is_cancelled():
                        return [], []
                    if result:
                        targets.append(result['targets'])
                        news_list.extend(result['news'])
        with ThreadPoolExecutor(max_workers=self._executor_workers(len(MACRO_TICKERS))) as executor:
            for articles in executor.map(self._fetch_macro_news, MACRO_TICKERS):
                if self._is_cancelled():
                    return [], []
                news_list.extend(articles)
        if self._is_cancelled():
            return [], []
        other_news = self._filter_other_news(self._fetch_other_news(), news_list)
        news_list.extend(other_news)
        return targets, news_list

    def _normalize_chart_frame(self, symbol: str, df: Any) -> Any:
        if df is None or df.empty:
            return None
        frame = df.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            symbol_text = str(symbol or '').upper().strip()
            level_zero_raw = list(frame.columns.get_level_values(0))
            level_one_raw = list(frame.columns.get_level_values(1))
            level_zero = [str(value).upper().strip() for value in level_zero_raw]
            level_one = [str(value).upper().strip() for value in level_one_raw]
            field_names = {'OPEN', 'HIGH', 'LOW', 'CLOSE', 'ADJ CLOSE', 'VOLUME'}

            if symbol_text and symbol_text in level_zero:
                frame = frame.xs(level_zero_raw[level_zero.index(symbol_text)], axis=1, level=0, drop_level=True).copy()
            elif symbol_text and symbol_text in level_one:
                frame = frame.xs(level_one_raw[level_one.index(symbol_text)], axis=1, level=1, drop_level=True).copy()
            elif len(set(level_one)) == 1 and any(name in field_names for name in level_zero):
                frame.columns = frame.columns.get_level_values(0)
            elif len(set(level_zero)) == 1 and any(name in field_names for name in level_one):
                frame.columns = frame.columns.get_level_values(1)
            else:
                logger.warning('Dashboard chart %s rejected ambiguous MultiIndex columns: %s', symbol, list(frame.columns))
                return None
        rename_map = {}
        for column in list(frame.columns):
            lowered = str(column).strip().lower()
            if lowered == 'open':
                rename_map[column] = 'Open'
            elif lowered == 'high':
                rename_map[column] = 'High'
            elif lowered == 'low':
                rename_map[column] = 'Low'
            elif lowered == 'close':
                rename_map[column] = 'Close'
            elif lowered == 'volume':
                rename_map[column] = 'Volume'
        if rename_map:
            frame = frame.rename(columns=rename_map)
        required_columns = ['Open', 'High', 'Low', 'Close']
        missing_columns = [column for column in required_columns if column not in frame.columns]
        if missing_columns:
            logger.warning(
                'Dashboard chart %s rejected frame missing columns %s. Columns=%s',
                symbol,
                missing_columns,
                list(frame.columns),
            )
            return None
        try:
            frame.index = pd.to_datetime(frame.index)
        except Exception:
            logger.warning('Dashboard chart %s rejected non-datetime index.', symbol)
            return None
        frame = frame.sort_index().dropna(subset=required_columns).copy()
        if frame.empty:
            logger.warning('Dashboard chart %s rejected empty OHLC frame after normalization.', symbol)
            return None
        ordered_columns = required_columns + [column for column in frame.columns if column not in required_columns]
        return frame.loc[:, ordered_columns]

    def _chart_required_span_days(self, period: Any) -> float | None:
        """Convert one yfinance period string into approximate calendar days."""
        text = str(period or '').strip().lower()
        if not text or text == 'max':
            return None
        for suffix, multiplier in CHART_CACHE_PERIOD_DAY_MAP.items():
            if text.endswith(suffix):
                number_text = text[:-len(suffix)].strip()
                try:
                    return float(number_text) * multiplier
                except Exception:
                    return None
        return None

    def _chart_cache_covers_period(self, df: Any, period: Any) -> bool:
        """Return whether one cached OHLCV frame is long enough for the requested period."""
        if df is None or getattr(df, 'empty', True):
            return False
        required_days = self._chart_required_span_days(period)
        if required_days is None:
            return True
        try:
            index = pd.DatetimeIndex(pd.to_datetime(df.index))
        except Exception:
            return False
        if len(index) < 2:
            return False
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        coverage_days = max(0.0, (index.max() - index.min()).total_seconds() / 86400.0)
        min_acceptable_days = max(required_days - 45.0, required_days * 0.85)
        return coverage_days >= min_acceptable_days

    def _chart_frame_coverage_days(self, df: Any) -> float:
        """Return the calendar-day span covered by one OHLCV frame."""
        if df is None or getattr(df, 'empty', True):
            return 0.0
        try:
            index = pd.DatetimeIndex(pd.to_datetime(df.index))
        except Exception:
            return 0.0
        if len(index) < 2:
            return 0.0
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        return max(0.0, (index.max() - index.min()).total_seconds() / 86400.0)

    def _merge_chart_frames(self, existing_df: Any, new_df: Any) -> Any:
        """Merge cached and freshly fetched OHLCV rows without dropping older history."""
        frames = [frame for frame in (existing_df, new_df) if frame is not None and not getattr(frame, 'empty', True)]
        if not frames:
            return None
        if len(frames) == 1:
            frame = frames[0].copy()
            frame.index.name = 'Date'
            return frame
        merged = pd.concat(frames, axis=0, sort=False)
        try:
            merged.index = pd.to_datetime(merged.index)
        except Exception:
            frame = new_df.copy()
            frame.index.name = 'Date'
            return frame
        merged = merged[~merged.index.duplicated(keep='last')].sort_index().copy()
        merged.index.name = 'Date'
        return merged

    def _save_chart_frame(self, cache: CacheManager, symbol: str, interval: Any, df: Any) -> None:
        """Save chart data while preserving any longer history already cached for the interval."""
        if df is None or getattr(df, 'empty', True) or interval not in ('1d', '1wk', '1mo'):
            return
        existing_df = self._normalize_chart_frame(
            symbol,
            cache.get_data(symbol, interval, max_age_hours=24.0 * 365.0 * 20.0),
        )
        merged_df = self._merge_chart_frames(existing_df, df)
        if merged_df is not None and not merged_df.empty:
            cache.save_data(symbol, interval, merged_df)

    def _load_cached_chart_frame(
        self,
        symbol: str,
        period: Any,
        interval: Any,
        *,
        max_age_hours: float = 24.0,
        require_coverage: bool = True,
    ) -> Any:
        """Return one normalized cached chart frame when it is still usable for the request."""
        raw_df = self._cache_manager.get_data(symbol, interval, max_age_hours=max_age_hours)
        df = self._normalize_chart_frame(symbol, raw_df)
        if df is None or df.empty:
            return None
        if require_coverage and interval in ('1d', '1wk', '1mo') and not self._chart_cache_covers_period(df, period):
            logger.info(
                'Dashboard chart %s cache for interval %s does not cover requested period %s.',
                symbol,
                interval,
                period,
            )
            return None
        return df

    def _normalize_datetime_index_ns(self, values: Any) -> Any:
        """Normalize incoming timestamps to a tz-naive nanosecond index for stable merges."""
        index = pd.DatetimeIndex(pd.to_datetime(values))
        if getattr(index, 'tz', None) is not None:
            index = index.tz_localize(None)
        # `merge_asof` rejects mixed datetime resolutions like ms vs us, so force ns.
        return pd.DatetimeIndex(index.astype('datetime64[ns]'))

    def _build_daily_ma200(self, symbol: str, source_df: Any, cache: CacheManager) -> Any:
        daily_df = None
        if source_df is not None and not source_df.empty and self._chart_cache_covers_period(source_df, '1y'):
            try:
                source_index = pd.DatetimeIndex(pd.to_datetime(source_df.index))
                if getattr(source_index, 'tz', None) is not None:
                    source_index = source_index.tz_localize(None)
                if len(source_index) >= 2:
                    median_gap_days = pd.Series(source_index).diff().dropna().dt.total_seconds().median() / 86400.0
                    if 0.5 <= float(median_gap_days or 0.0) <= 3.5:
                        daily_df = self._normalize_chart_frame(symbol, source_df)
            except Exception:
                daily_df = None
        if daily_df is None or daily_df.empty:
            daily_df = self._load_cached_chart_frame(symbol, '5y', '1d')
        if daily_df is None or daily_df.empty:
            daily_df = self._download_symbol_frame(symbol, '5y', '1d', auto_adjust=False)
            if daily_df is not None and not daily_df.empty:
                self._save_chart_frame(cache, symbol, '1d', daily_df)
        if daily_df is None or daily_df.empty or 'Close' not in daily_df.columns:
            return pd.Series(index=source_df.index, dtype=float)
        daily_ma = daily_df['Close'].astype(float).rolling(200, min_periods=200).mean().dropna()
        if daily_ma.empty:
            return pd.Series(index=source_df.index, dtype=float)
        source_index = self._normalize_datetime_index_ns(source_df.index)
        daily_index = self._normalize_datetime_index_ns(daily_ma.index)
        source_frame = pd.DataFrame(index=source_index).sort_index()
        daily_frame = pd.DataFrame({'ma200': list(daily_ma.values)}, index=daily_index).sort_index()
        aligned = pd.merge_asof(source_frame, daily_frame, left_index=True, right_index=True, direction='backward')['ma200']
        aligned.index = source_df.index
        return aligned

    def _load_options_chain(self, cache: CacheManager, ticker: str, expiry: str, ticker_obj: Any = None) -> Any:
        options_df = cache.get_options_chain(ticker, expiry)
        if options_df is None:
            ticker_obj = ticker_obj or self._ticker(ticker)
            chain = ticker_obj.option_chain(expiry)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            calls['ticker'], calls['type'] = (ticker, 'Call')
            puts['ticker'], puts['type'] = (ticker, 'Put')
            options_df = pd.concat([calls, puts], ignore_index=True)
            options_df['expiration'] = expiry
            cache.save_options_chain(ticker, expiry, options_df)
        else:
            options_df = options_df.copy()
        if 'ticker' not in options_df.columns:
            options_df['ticker'] = ticker
        if 'type' not in options_df.columns:
            options_df['type'] = ''
        if 'expiration' not in options_df.columns:
            options_df['expiration'] = expiry
        return options_df

    def _select_option_expiry_buckets(self, expirations: Any) -> dict[str, str]:
        if not expirations:
            return {}
        today = datetime.date.today()
        parsed = []
        for expiry in expirations:
            try:
                expiry_text = str(expiry)
                parsed.append((expiry_text, datetime.date.fromisoformat(expiry_text)))
            except Exception:
                continue
        if not parsed:
            return {}
        parsed.sort(key=lambda item: item[1])
        buckets = {}
        for bucket_name, days_out in OPTION_BUCKET_OFFSETS:
            target_date = today + datetime.timedelta(days=days_out)
            selected = next((expiry_text for expiry_text, expiry_date in parsed if expiry_date >= target_date), None)
            buckets[bucket_name] = selected or parsed[-1][0]
        return buckets

    @staticmethod
    def _calculate_rsi(close_series: Any, period: int = 14) -> Any:
        """Calculate an RSI series from closing prices."""
        closes = pd.Series(close_series).astype(float)
        delta = closes.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - 100 / (1 + rs)
        return rsi.bfill().clip(lower=0, upper=100)

    def _fetch_chart_payload(self, config: tuple[str, Any, Any]) -> Any:
        symbol, period, interval = config
        cache = self._cache_manager
        source_label = 'download'
        df = self._download_symbol_frame(symbol, period, interval)
        if df is not None and not df.empty and interval in ('1d', '1wk', '1mo') and not self._chart_cache_covers_period(df, period):
            max_df = self._download_symbol_frame(symbol, 'max', interval)
            if max_df is not None and not max_df.empty and self._chart_frame_coverage_days(max_df) > self._chart_frame_coverage_days(df):
                df = max_df
                source_label = 'download-max'
        if df is not None and not df.empty and interval in ('1d', '1wk', '1mo'):
            self._save_chart_frame(cache, symbol, interval, df)
        if df is None:
            source_label = 'cache'
            df = self._load_cached_chart_frame(symbol, period, interval)
            if df is None:
                df = self._load_cached_chart_frame(symbol, period, interval, require_coverage=False)
                if df is not None and not df.empty:
                    source_label = 'partial cache'
        if df is None:
            logger.warning(
                'Dashboard chart %s unavailable after %s for period=%s interval=%s.',
                symbol,
                source_label,
                period,
                interval,
            )
            return (
                symbol,
                None,
                dict(OPTION_BUCKET_TEMPLATE),
                {},
                None,
                None,
            )
        logger.info(
            'Dashboard chart %s loaded from %s with %s rows. Columns=%s last_close=%.2f',
            symbol,
            source_label,
            len(df),
            list(df.columns),
            float(df['Close'].iloc[-1]),
        )
        option_buckets = {key: [] for key in OPTION_BUCKET_TEMPLATE}
        option_expirations = {}
        ma200_series = self._build_daily_ma200(symbol, df, cache)
        rsi_series = self._calculate_rsi(df['Close'])
        try:
            expirations = cache.get_options_expiries(symbol)
            ticker_obj = None
            if expirations is None:
                ticker_obj = self._ticker(symbol)
                expirations = ticker_obj.options
                cache.save_options_expiries(symbol, expirations)
            bucket_map = self._select_option_expiry_buckets(expirations)
            with ThreadPoolExecutor(max_workers=max(1, len(bucket_map))) as pool:
                futures = {}
                for bucket_name, expiry in bucket_map.items():
                    if not expiry:
                        continue
                    option_expirations[bucket_name] = expiry
                    futures[bucket_name] = pool.submit(self._load_options_chain, cache, symbol, expiry, ticker_obj)
                for bucket_name, fut in futures.items():
                    try:
                        options_df = fut.result()
                        if options_df is None or options_df.empty or 'volume' not in options_df.columns:
                            continue
                        top_options = options_df.sort_values(by='volume', ascending=False).head(10)
                        option_buckets[bucket_name] = top_options.to_dict('records')
                    except Exception:
                        continue
        except Exception as exc:
            logger.info('Dashboard options unavailable for %s: %s', symbol, exc)
        return symbol, df, option_buckets, option_expirations, ma200_series, rsi_series

    def _collect_chart_data(self, dashboard_chart_config: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        charts = {}
        chart_options = {}
        chart_option_expirations = {}
        chart_ma200 = {}
        chart_rsi = {}
        if not dashboard_chart_config:
            return charts, chart_options, chart_option_expirations, chart_ma200, chart_rsi
        result = self._fetch_chart_payload(dashboard_chart_config)
        if result:
            symbol, df, options_payload, expiration_payload, ma200_series, rsi_series = result
            charts[symbol] = df
            chart_options[symbol] = options_payload
            chart_option_expirations[symbol] = expiration_payload
            chart_ma200[symbol] = ma200_series
            chart_rsi[symbol] = rsi_series
        return charts, chart_options, chart_option_expirations, chart_ma200, chart_rsi

    def fetch(self) -> dict[str, Any] | None:
        """Return the dashboard payload synchronously without emitting Qt signals."""
        logger.info('Worker starting. Tickers: %s, Charts: %s', self.tickers, self.chart_configs)
        total_started = time.perf_counter()
        dashboard_chart_configs = self._normalize_chart_configs()
        dashboard_chart_config = dashboard_chart_configs[0] if dashboard_chart_configs else None
        fetch_ticker_signature = self._fetch_ticker_signature()
        non_chart_reused = False
        cache_age_seconds = 0.0
        non_chart_started = time.perf_counter()
        non_chart_payload = None
        skip_chart_refresh = self.refresh_reason == 'portfolio_membership_change'
        if self.allow_non_chart_reuse:
            non_chart_payload, cache_age_seconds = self._load_cached_non_chart_snapshot(fetch_ticker_signature)
            if non_chart_payload is not None:
                non_chart_reused = True
                logger.info(
                    'Worker %s reused dashboard non-chart snapshot for %s (age %.1fs, reason=%s).',
                    self.request_id,
                    list(fetch_ticker_signature),
                    cache_age_seconds,
                    self.refresh_reason,
                )
        if skip_chart_refresh:
            if not non_chart_reused:
                non_chart_payload = self._collect_non_chart_payload()
            non_chart_ms = (time.perf_counter() - non_chart_started) * 1000.0
            charts, chart_options, chart_option_expirations, chart_ma200, chart_rsi = ({}, {}, {}, {}, {})
            chart_ms = 0.0
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_non_chart = None if non_chart_reused else pool.submit(self._collect_non_chart_payload)
                chart_started = time.perf_counter()
                fut_chart = pool.submit(self._collect_chart_data, dashboard_chart_config)
                if fut_non_chart is not None:
                    non_chart_payload = fut_non_chart.result()
                non_chart_ms = (time.perf_counter() - non_chart_started) * 1000.0
                charts, chart_options, chart_option_expirations, chart_ma200, chart_rsi = fut_chart.result()
                chart_ms = (time.perf_counter() - chart_started) * 1000.0
        if non_chart_payload is None and self._is_cancelled():
            logger.info('Worker %s cancelled during non-chart fetch.', self.request_id)
            return None
        if not non_chart_reused and non_chart_payload is not None:
            self._save_cached_non_chart_snapshot(fetch_ticker_signature, non_chart_payload)
            logger.info(
                'Worker %s fetched fresh dashboard non-chart payload for %s in %.1f ms (reason=%s).',
                self.request_id,
                list(fetch_ticker_signature),
                non_chart_ms,
                self.refresh_reason,
            )
        if self._is_cancelled():
            logger.info('Worker %s cancelled after parallel fetch.', self.request_id)
            return None
        chart_symbol = dashboard_chart_config[0] if dashboard_chart_config else ''
        chart_frame = charts.get(chart_symbol) if chart_symbol else None
        chart_missing = bool(
            chart_symbol
            and (
                chart_frame is None
                or (hasattr(chart_frame, 'empty') and bool(chart_frame.empty))
            )
        )
        errors = []
        if non_chart_payload is None:
            errors.append(
                make_market_data_error(
                    source='yfinance',
                    reason='Dashboard quote, market, targets, and news data were unavailable.',
                    operation='dashboard_non_chart',
                )
            )
        if chart_missing and not skip_chart_refresh:
            errors.append(
                make_market_data_error(
                    source='yfinance/cache',
                    reason=f'Dashboard chart data was unavailable for {chart_symbol}.',
                    operation='dashboard_chart',
                    symbol=chart_symbol,
                )
            )
        if non_chart_payload is None and (not charts or chart_missing):
            freshness = 'failed'
            failure_reason = 'Dashboard market data could not be loaded.'
        elif errors:
            freshness = 'partial'
            failure_reason = '; '.join(error.get('reason', '') for error in errors if error.get('reason'))
        else:
            freshness = 'fresh'
            failure_reason = ''
        source_parts = ['yfinance', 'keyless news feeds']
        if non_chart_reused:
            source_parts.append('memory cache')
        payload = {
            'request_id': self.request_id,
            'chart_configs': list(dashboard_chart_configs),
            'portfolio': dict((non_chart_payload or {}).get('portfolio', {})),
            'market': dict((non_chart_payload or {}).get('market', {})),
            'targets': list((non_chart_payload or {}).get('targets', [])),
            'news': list((non_chart_payload or {}).get('news', [])),
            'charts': charts,
            'chart_options': chart_options,
            'chart_option_expirations': chart_option_expirations,
            'chart_ma200': chart_ma200,
            'chart_rsi': chart_rsi,
            '_dashboard_refresh_meta': {
                'refresh_reason': self.refresh_reason,
                'non_chart_reused': non_chart_reused,
                'chart_symbol': chart_symbol,
                'fetch_ticker_signature': list(fetch_ticker_signature),
                'non_chart_cache_age_seconds': float(cache_age_seconds),
                'worker_timings_ms': {
                    'non_chart': round(non_chart_ms, 1),
                    'chart': round(chart_ms, 1),
                    'total': round((time.perf_counter() - total_started) * 1000.0, 1),
                },
            },
        }
        return attach_market_data_result(
            payload,
            meta=make_market_data_meta(
                source=', '.join(source_parts),
                freshness=freshness,
                cache_age_seconds=float(cache_age_seconds) if non_chart_reused else None,
                failure_reason=failure_reason,
            ),
            errors=errors,
        )

    def run(self) -> Any:
        try:
            data = self.fetch()
            if data is not None:
                self.finished.emit(data)
        except Exception as exc:
            logger.error('Worker error: %s', exc)
            self.error.emit(str(exc))
