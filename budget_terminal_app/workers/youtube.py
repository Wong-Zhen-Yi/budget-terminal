from __future__ import annotations

import json
import re
import time
from concurrent.futures import as_completed
from typing import Any

from ..dependencies import *
from ..paths import user_data_path

YOUTUBE_CACHE_DIR = 'youtube_cache'
YOUTUBE_CACHE_TTL = 30 * 60
YOUTUBE_MIN_VIEW_COUNT = 1000
YOUTUBE_MAX_AGE_DAYS = 90
YOUTUBE_RESULTS_PER_TICKER = 3
YOUTUBE_SEARCH_POOL = 10
YOUTUBE_FETCH_MAX_WORKERS = 4


class YouTubeWorker(QObject):
    item_ready = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, tickers: Any, force_refresh: bool = False) -> None:
        super().__init__()
        self.tickers = []
        seen = set()
        for value in list(tickers or []):
            ticker = str(value or '').upper().strip()
            if ticker and ticker not in seen:
                seen.add(ticker)
                self.tickers.append(ticker)
        self.force_refresh = bool(force_refresh)

    def run(self) -> None:
        try:
            yt_dlp = self._load_yt_dlp()
            if not self.tickers:
                self.finished.emit({
                    'items': [],
                    'warnings': ['No saved portfolio tickers are available yet.'],
                    'fetched_at': time.time(),
                    'from_cache_count': 0,
                    'fetched_count': 0,
                    'tickers_total': 0,
                })
                return

            items_by_ticker: dict[str, list[dict[str, Any]]] = {}
            warnings_by_ticker: dict[str, str] = {}
            cached_count = 0
            fetched_count = 0
            total = len(self.tickers)
            pending_tickers: list[str] = []

            for ticker in self.tickers:
                cached = None if self.force_refresh else self._load_cache_entry(ticker)
                if cached is not None and time.time() - float(cached.get('fetched_at', 0) or 0) < YOUTUBE_CACHE_TTL:
                    cached_count += 1
                    self.status.emit(f'[{cached_count}/{total}] Using cached YouTube data for {ticker}...')
                    items = cached.get('items')
                    warning = str(cached.get('warning', '') or '').strip()
                    if isinstance(items, list):
                        item_copies = [dict(item) for item in items if isinstance(item, dict)]
                        if item_copies:
                            items_by_ticker[ticker] = item_copies
                            for item_copy in item_copies:
                                self.item_ready.emit(dict(item_copy))
                    if warning:
                        warnings_by_ticker[ticker] = warning
                    continue
                pending_tickers.append(ticker)

            if pending_tickers:
                worker_count = min(YOUTUBE_FETCH_MAX_WORKERS, len(pending_tickers))
                self.status.emit(
                    f'Fetching {len(pending_tickers)} uncached/stale YouTube ticker(s) in parallel ({worker_count} worker(s))...'
                )
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    futures = {pool.submit(self._fetch_ticker_safe, yt_dlp, ticker): ticker for ticker in pending_tickers}
                    completed_count = 0
                    for future in as_completed(futures):
                        ticker = futures[future]
                        completed_count += 1
                        items, warning = future.result()
                        fetched_count += 1
                        self._save_cache_entry(ticker, items=items, warning=warning)
                        if isinstance(items, list):
                            item_copies = [dict(item) for item in items if isinstance(item, dict)]
                            if item_copies:
                                items_by_ticker[ticker] = item_copies
                                for item_copy in item_copies:
                                    self.item_ready.emit(dict(item_copy))
                        if warning:
                            warnings_by_ticker[ticker] = warning
                        self.status.emit(
                            f'[{cached_count + completed_count}/{total}] Processed YouTube data for {ticker}...'
                        )

            items = []
            for ticker in self.tickers:
                for item in items_by_ticker.get(ticker, []):
                    items.append(dict(item))
            warnings = [warnings_by_ticker[ticker] for ticker in self.tickers if ticker in warnings_by_ticker]

            self.finished.emit({
                'items': items,
                'warnings': warnings,
                'fetched_at': time.time(),
                'from_cache_count': cached_count,
                'fetched_count': fetched_count,
                'tickers_total': total,
            })
        except Exception as exc:
            logger.exception('YouTubeWorker error.')
            self.error.emit(str(exc))

    @staticmethod
    def _load_yt_dlp() -> Any:
        try:
            import yt_dlp
        except Exception as exc:
            raise RuntimeError('yt-dlp is not installed. Install requirements.txt to enable the YouTube tab.') from exc
        return yt_dlp

    def _fetch_ticker(self, yt_dlp: Any, ticker: str) -> tuple[list[dict[str, Any]], str]:
        options = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'socket_timeout': 20,
            'playlistend': YOUTUBE_SEARCH_POOL,
        }
        query = f'ytsearch{YOUTUBE_SEARCH_POOL}:{ticker} stock'
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(query, download=False)
        entries = result.get('entries', []) if isinstance(result, dict) else []
        candidates = [candidate for candidate in entries if isinstance(candidate, dict)]
        if not candidates:
            return ([], f'{ticker}: no matching YouTube videos found.')
        matches: list[dict[str, Any]] = []
        for entry in candidates:
            normalized = self._normalize_entry(ticker, entry)
            if not normalized.get('url'):
                continue
            if self._matches_filters(normalized):
                matches.append(normalized)
                if len(matches) >= YOUTUBE_RESULTS_PER_TICKER:
                    break
        if matches:
            return (matches, '')
        return (
            [],
            f'{ticker}: no YouTube videos met the filter (>= {YOUTUBE_MIN_VIEW_COUNT:,} views and <= {YOUTUBE_MAX_AGE_DAYS} days old).',
        )

    def _fetch_ticker_safe(self, yt_dlp: Any, ticker: str) -> tuple[list[dict[str, Any]], str]:
        try:
            return self._fetch_ticker(yt_dlp, ticker)
        except Exception as exc:
            logger.warning('YouTube search failed for %s: %s', ticker, exc)
            return ([], f'{ticker}: {exc}')

    def _normalize_entry(self, ticker: str, entry: dict[str, Any]) -> dict[str, Any]:
        video_id = str(entry.get('id', '') or '').strip()
        url = str(entry.get('webpage_url', '') or entry.get('original_url', '') or '').strip()
        if not url:
            raw_url = str(entry.get('url', '') or '').strip()
            if raw_url.startswith('http'):
                url = raw_url
            elif video_id:
                url = f'https://www.youtube.com/watch?v={video_id}'
        description = re.sub(r'\s+', ' ', str(entry.get('description', '') or '').strip())
        if len(description) > 220:
            description = f'{description[:217].rstrip()}...'
        view_count = self._normalize_view_count(entry.get('view_count'))
        published_text = self._format_published_text(entry)
        published_days = self._days_since_published(published_text)
        return {
            'ticker': ticker,
            'title': str(entry.get('title', '') or 'Untitled').strip() or 'Untitled',
            'channel': str(entry.get('channel', '') or entry.get('uploader', '') or 'Unknown').strip() or 'Unknown',
            'view_count': view_count,
            'view_count_text': self._format_view_count(view_count),
            'published_text': published_text,
            'published_days': published_days,
            'published_days_text': self._format_published_days(published_days),
            'duration_text': self._format_duration(entry.get('duration')),
            'url': url,
            'thumbnail_url': str(entry.get('thumbnail', '') or '').strip(),
            'description_snippet': description,
        }

    @staticmethod
    def _format_published_text(entry: dict[str, Any]) -> str:
        upload_date = str(entry.get('upload_date', '') or '').strip()
        if len(upload_date) == 8 and upload_date.isdigit():
            return f'{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}'
        timestamp = entry.get('timestamp')
        try:
            return datetime.datetime.fromtimestamp(float(timestamp), tz=datetime.timezone.utc).strftime('%Y-%m-%d')
        except Exception:
            return 'N/A'

    @staticmethod
    def _format_duration(value: Any) -> str:
        try:
            total_seconds = int(value)
        except (TypeError, ValueError):
            return 'N/A'
        if total_seconds < 0:
            return 'N/A'
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        return f'{minutes}:{seconds:02d}'

    @staticmethod
    def _normalize_view_count(value: Any) -> int | None:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return None
        return count if count >= 0 else None

    @staticmethod
    def _format_view_count(value: Any) -> str:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return 'N/A'
        if count < 0:
            return 'N/A'
        if count < 1000:
            return f'{count:,}'
        units = (
            (1_000_000_000_000, 'T'),
            (1_000_000_000, 'B'),
            (1_000_000, 'M'),
            (1000, 'K'),
        )
        for threshold, suffix in units:
            if count >= threshold:
                compact = f'{count / threshold:.1f}'.rstrip('0').rstrip('.')
                return f'{compact}{suffix}'
        return f'{count:,}'

    @staticmethod
    def _days_since_published(published_text: Any) -> int | None:
        text = str(published_text or '').strip()
        if not text or text == 'N/A':
            return None
        try:
            published_date = datetime.datetime.strptime(text, '%Y-%m-%d').date()
        except ValueError:
            return None
        today = datetime.datetime.now(datetime.timezone.utc).date()
        delta = (today - published_date).days
        return delta if delta >= 0 else 0

    @staticmethod
    def _format_published_days(value: Any) -> str:
        try:
            days = int(value)
        except (TypeError, ValueError):
            return 'N/A'
        return str(days) if days >= 0 else 'N/A'

    @staticmethod
    def _matches_filters(item: dict[str, Any]) -> bool:
        view_count = item.get('view_count')
        published_days = item.get('published_days')
        if not isinstance(view_count, int) or view_count < YOUTUBE_MIN_VIEW_COUNT:
            return False
        if not isinstance(published_days, int) or published_days > YOUTUBE_MAX_AGE_DAYS:
            return False
        return True

    @staticmethod
    def _cache_key_for_ticker(ticker: str) -> str:
        return re.sub(r'[^A-Z0-9._-]+', '_', str(ticker or '').upper().strip()) or 'UNKNOWN'

    @classmethod
    def _cache_path_for_ticker(cls, ticker: str) -> Path:
        return user_data_path(YOUTUBE_CACHE_DIR, f'{cls._cache_key_for_ticker(ticker)}.json')

    @classmethod
    def _load_cache_entry(cls, ticker: str) -> dict[str, Any] | None:
        path = cls._cache_path_for_ticker(ticker)
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return None
        if not isinstance(cached, dict):
            return None
        normalized = dict(cached)
        warning = str(normalized.get('warning', '') or '').strip()
        normalized_items = cls._extract_cached_items(normalized)
        if normalized_items is None:
            return None
        if not normalized_items and not warning:
            return None
        normalized['items'] = normalized_items
        normalized.pop('item', None)
        return normalized

    @classmethod
    def _save_cache_entry(cls, ticker: str, *, items: list[dict[str, Any]] | None, warning: str = '') -> None:
        payload = {
            'ticker': ticker,
            'items': [dict(item) for item in list(items or []) if isinstance(item, dict)][:YOUTUBE_RESULTS_PER_TICKER],
            'warning': str(warning or '').strip(),
            'fetched_at': time.time(),
        }
        try:
            cls._cache_path_for_ticker(ticker).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            logger.warning('YouTube cache write error for %s: %s', ticker, exc)

    @classmethod
    def _extract_cached_items(cls, cached: dict[str, Any]) -> list[dict[str, Any]] | None:
        if 'items' in cached:
            raw_items = cached.get('items')
            if raw_items is None:
                return []
            if not isinstance(raw_items, list):
                return None
            return cls._normalize_cached_items(raw_items)
        if 'item' not in cached:
            return None
        raw_item = cached.get('item')
        if raw_item is None:
            return []
        if not isinstance(raw_item, dict):
            return None
        normalized_item = cls._normalize_cached_item(raw_item)
        if normalized_item is None:
            return None
        return [normalized_item]

    @classmethod
    def _normalize_cached_items(cls, items: list[Any]) -> list[dict[str, Any]]:
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized_item = cls._normalize_cached_item(item)
            if normalized_item is None:
                continue
            normalized_items.append(normalized_item)
            if len(normalized_items) >= YOUTUBE_RESULTS_PER_TICKER:
                break
        return normalized_items

    @classmethod
    def _normalize_cached_item(cls, item: dict[str, Any]) -> dict[str, Any] | None:
        if 'view_count' not in item:
            return None
        normalized = dict(item)
        view_count = cls._normalize_view_count(normalized.get('view_count'))
        normalized['view_count'] = view_count
        normalized['view_count_text'] = cls._format_view_count(view_count)
        published_text = str(normalized.get('published_text', '') or 'N/A')
        normalized['published_text'] = published_text
        published_days = cls._days_since_published(published_text)
        normalized['published_days'] = published_days
        normalized['published_days_text'] = cls._format_published_days(published_days)
        if not normalized.get('url'):
            return None
        if not cls._matches_filters(normalized):
            return None
        return normalized
