from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterator
from typing import Any

from ..cache import CacheManager
from ..dependencies import YF_LOCK, datetime, logger, math, pd, yf


UP_DOWN_INTERVALS: tuple[tuple[str, str], ...] = (
    ("1d", "1D"),
    ("5d", "5D"),
    ("30d", "30D"),
    ("ytd", "YTD"),
    ("1y", "1Y"),
)
UP_DOWN_INTERVAL_LABELS = {key: label for key, label in UP_DOWN_INTERVALS}
UP_DOWN_TARGET_BATCH_SIZE = 12
UP_DOWN_TARGET_MAX_WORKERS = 8
UP_DOWN_PAYLOAD_CACHE_TTL_SECONDS = 15 * 60.0
UP_DOWN_HOLDINGS_CACHE_TTL_SECONDS = 24 * 60 * 60.0
UP_DOWN_TARGET_DISK_CACHE_TTL_SECONDS = 24 * 60 * 60.0
UP_DOWN_STALE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60.0
UP_DOWN_PAYLOAD_CACHE_NAMESPACE = "up_down_payload_v1"
UP_DOWN_HOLDINGS_CACHE_NAMESPACE = "up_down_holdings_v1"
UP_DOWN_TARGET_CACHE_NAMESPACE = "up_down_targets_v1"
UP_DOWN_TARGET_CACHE_KEY = "analyst_targets"


def normalize_up_down_symbols(values: Any) -> list[str]:
    """Return unique uppercase stock symbols from a string or iterable."""
    if isinstance(values, str):
        raw_values = values.replace(",", " ").replace(";", " ").split()
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = []
    symbols: list[str] = []
    seen = set()
    for value in raw_values:
        symbol = str(value or "").upper().strip()
        if not symbol or symbol == "CASH" or symbol in seen:
            continue
        if not any(ch.isalpha() for ch in symbol):
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


def interval_fetch_config(interval_key: Any, today: datetime.date | None = None) -> dict[str, Any]:
    """Return yfinance fetch kwargs for one Up/Down interval."""
    key = str(interval_key or "1d").strip().lower()
    today = today or datetime.date.today()
    if key in {"1d", "5d"}:
        return {"period": "10d", "interval": "1d"}
    if key == "30d":
        return {"period": "2mo", "interval": "1d"}
    if key == "ytd":
        return {"start": (today.replace(month=1, day=1) - datetime.timedelta(days=10)).isoformat(), "interval": "1d"}
    if key == "1y":
        return {"period": "13mo", "interval": "1d"}
    return {"period": "5d", "interval": "1d"}


def calculate_up_down_row(
    symbol: str,
    close: Any,
    interval_key: Any,
    *,
    name: str = "",
) -> dict[str, Any] | None:
    """Calculate days-up/days-down metrics from one daily close series."""
    series = _clean_close_series(close)
    if series is None or len(series) < 2:
        return None
    key = str(interval_key or "1d").strip().lower()
    changes = series.diff().dropna()
    returns = series.pct_change().dropna() * 100.0
    selected_changes = _select_interval_series(changes, key, latest_time=series.index[-1])
    selected_returns = returns.reindex(selected_changes.index).dropna()
    if selected_changes.empty:
        return None
    trading_days = int(len(selected_changes))
    days_up = int((selected_changes > 0).sum())
    days_down = int((selected_changes < 0).sum())
    interval_return = _interval_return(series, selected_changes.index)
    try:
        last_close = float(series.iloc[-1])
    except Exception:
        last_close = None
    return {
        "ticker": str(symbol or "").upper().strip(),
        "name": str(name or "").strip(),
        "last_close": last_close if isinstance(last_close, (int, float)) and math.isfinite(float(last_close)) else None,
        "interval_return": interval_return,
        "trading_days": trading_days,
        "days_up": days_up,
        "days_down": days_down,
        "flat_days": max(0, trading_days - days_up - days_down),
        "positive_return_days": int((selected_returns > 0).sum()) if not selected_returns.empty else days_up,
        "negative_return_days": int((selected_returns < 0).sum()) if not selected_returns.empty else days_down,
    }


def sort_up_down_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows by the Up/Down page default ranking."""
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("days_up") or 0),
            int(row.get("days_down") or 0),
            str(row.get("ticker") or ""),
        ),
    )


class UpDownDataService:
    """Fetch daily closes and calculate Up/Down page rows."""

    _price_target_cache: dict[str, tuple[float, float | None]] = {}
    _price_target_cache_lock = threading.Lock()

    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        self.cache_manager = cache_manager
        self._price_target_cache = {}
        self._price_target_cache_lock = threading.Lock()
        self._persistent_targets_loaded = False

    @staticmethod
    def _payload_cache_key(source_key: Any, interval_key: Any) -> str:
        source = str(source_key or "portfolio").strip().lower()
        interval = str(interval_key or "1d").strip().lower()
        return f"{source}:{interval}"

    def load_cached_payload(self, source_key: Any, interval_key: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self.cache_manager is None:
            return None
        cached = self.cache_manager.get_json_payload(
            UP_DOWN_PAYLOAD_CACHE_NAMESPACE,
            self._payload_cache_key(source_key, interval_key),
            max_age_seconds=UP_DOWN_PAYLOAD_CACHE_TTL_SECONDS,
            allow_stale=True,
            return_metadata=True,
        )
        if cached is None:
            return None
        payload, metadata = cached
        age_seconds = float((metadata or {}).get("cache_age_seconds", 0.0) or 0.0)
        if not isinstance(payload, dict) or age_seconds > UP_DOWN_STALE_CACHE_TTL_SECONDS:
            return None
        return payload, {
            "cache_age_seconds": age_seconds,
            "fresh": age_seconds < UP_DOWN_PAYLOAD_CACHE_TTL_SECONDS,
        }

    def save_cached_payload(self, source_key: Any, interval_key: Any, payload: Any) -> None:
        if self.cache_manager is None or not isinstance(payload, dict):
            return
        self.cache_manager.save_json_payload(
            UP_DOWN_PAYLOAD_CACHE_NAMESPACE,
            self._payload_cache_key(source_key, interval_key),
            payload,
        )

    def load_cached_holdings(self, etf_symbol: Any, *, fresh_only: bool) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self.cache_manager is None:
            return None
        symbol = str(etf_symbol or "").upper().strip()
        cached = self.cache_manager.get_json_payload(
            UP_DOWN_HOLDINGS_CACHE_NAMESPACE,
            symbol,
            max_age_seconds=UP_DOWN_HOLDINGS_CACHE_TTL_SECONDS,
            allow_stale=not fresh_only,
            return_metadata=True,
        )
        if cached is None:
            return None
        payload, metadata = cached
        age_seconds = float((metadata or {}).get("cache_age_seconds", 0.0) or 0.0)
        if not isinstance(payload, dict) or age_seconds > UP_DOWN_STALE_CACHE_TTL_SECONDS:
            return None
        return payload, {
            "cache_age_seconds": age_seconds,
            "fresh": age_seconds < UP_DOWN_HOLDINGS_CACHE_TTL_SECONDS,
        }

    def save_cached_holdings(self, etf_symbol: Any, symbols: list[str], names: dict[str, str]) -> None:
        if self.cache_manager is None:
            return
        symbol = str(etf_symbol or "").upper().strip()
        self.cache_manager.save_json_payload(
            UP_DOWN_HOLDINGS_CACHE_NAMESPACE,
            symbol,
            {"symbols": normalize_up_down_symbols(symbols), "names": dict(names or {})},
        )

    def fetch(self, symbols: list[str], interval_key: Any, *, names: dict[str, str] | None = None) -> dict[str, Any]:
        clean_symbols = normalize_up_down_symbols(symbols)
        if not clean_symbols:
            return {
                "rows": [],
                "missing": [],
                "as_of": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Yahoo Finance",
            }
        names = {str(key or "").upper().strip(): str(value or "").strip() for key, value in (names or {}).items()}
        yahoo_symbols = [self._yahoo_symbol(symbol) for symbol in clean_symbols]
        yahoo_to_original = {self._yahoo_symbol(symbol): symbol for symbol in clean_symbols}
        config = interval_fetch_config(interval_key)
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        try:
            with YF_LOCK:
                history = yf.download(
                    yahoo_symbols,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                    **config,
                )
        except Exception as exc:
            logger.info("Up/Down history fetch failed for %s symbol(s): %s", len(clean_symbols), exc)
            history = None
        for yahoo_symbol in yahoo_symbols:
            original = yahoo_to_original.get(yahoo_symbol, yahoo_symbol)
            frame = self._history_frame_for_symbol(history, yahoo_symbol, len(yahoo_symbols))
            close = self._close_series(frame)
            row = calculate_up_down_row(original, close, interval_key, name=names.get(original, ""))
            if row is None:
                missing.append(original)
                continue
            rows.append(row)
        return {
            "rows": sort_up_down_rows(rows),
            "missing": missing,
            "as_of": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo Finance",
        }

    def iter_price_target_batches(
        self,
        symbols: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
        force_refresh: bool = False,
    ) -> Iterator[dict[str, float | None]]:
        """Yield cached and newly fetched mean analyst targets in bounded batches."""
        self._load_persistent_targets()
        clean_symbols = normalize_up_down_symbols(symbols)
        should_cancel = cancel_check or (lambda: False)
        cached_batch: dict[str, float | None] = {}
        pending: list[str] = []
        for symbol in clean_symbols:
            cached, target = self._cached_price_target(symbol) if not force_refresh else (False, None)
            if cached:
                cached_batch[symbol] = target
                if len(cached_batch) >= UP_DOWN_TARGET_BATCH_SIZE:
                    if should_cancel():
                        return
                    yield cached_batch
                    cached_batch = {}
            else:
                pending.append(symbol)
        if cached_batch:
            if should_cancel():
                return
            yield cached_batch
        if not pending or should_cancel():
            return

        executor = ThreadPoolExecutor(max_workers=min(len(pending), UP_DOWN_TARGET_MAX_WORKERS))
        cancelled = False
        try:
            futures = {
                executor.submit(self._fetch_price_target, symbol, force_refresh=force_refresh): symbol
                for symbol in pending
            }
            batch: dict[str, float | None] = {}
            for future in as_completed(futures):
                if should_cancel():
                    cancelled = True
                    return
                symbol = futures[future]
                try:
                    batch[symbol] = future.result()
                except Exception as exc:
                    logger.info("Up/Down analyst target fetch failed for %s: %s", symbol, exc)
                    batch[symbol] = None
                if len(batch) >= UP_DOWN_TARGET_BATCH_SIZE:
                    yield batch
                    batch = {}
            if batch and not should_cancel():
                yield batch
        finally:
            cancelled = cancelled or should_cancel()
            executor.shutdown(wait=not cancelled, cancel_futures=True)
            self._save_persistent_targets()

    def _load_persistent_targets(self) -> None:
        if getattr(self, "_persistent_targets_loaded", False):
            return
        self._persistent_targets_loaded = True
        if getattr(self, "cache_manager", None) is None:
            return
        cached = self.cache_manager.get_json_payload(
            UP_DOWN_TARGET_CACHE_NAMESPACE,
            UP_DOWN_TARGET_CACHE_KEY,
            max_age_seconds=UP_DOWN_STALE_CACHE_TTL_SECONDS,
            allow_stale=True,
        )
        entries = cached.get("targets", {}) if isinstance(cached, dict) else {}
        now = time.time()
        with self._price_target_cache_lock:
            for symbol, entry in (entries.items() if isinstance(entries, dict) else ()):
                if not isinstance(entry, dict):
                    continue
                try:
                    fetched_at = float(entry.get("fetched_at"))
                except (TypeError, ValueError):
                    continue
                if now - fetched_at > UP_DOWN_STALE_CACHE_TTL_SECONDS:
                    continue
                target = entry.get("target")
                try:
                    target = float(target) if target is not None else None
                except (TypeError, ValueError):
                    target = None
                self._price_target_cache[str(symbol).upper().strip()] = (fetched_at, target)

    def _save_persistent_targets(self) -> None:
        if getattr(self, "cache_manager", None) is None:
            return
        cutoff = time.time() - UP_DOWN_STALE_CACHE_TTL_SECONDS
        with self._price_target_cache_lock:
            targets = {
                symbol: {"fetched_at": fetched_at, "target": target}
                for symbol, (fetched_at, target) in self._price_target_cache.items()
                if fetched_at >= cutoff
            }
        self.cache_manager.save_json_payload(
            UP_DOWN_TARGET_CACHE_NAMESPACE,
            UP_DOWN_TARGET_CACHE_KEY,
            {"targets": targets},
        )

    def _cached_price_target(self, symbol: str) -> tuple[bool, float | None]:
        now = time.time()
        with self._price_target_cache_lock:
            cached = self._price_target_cache.get(symbol)
            if cached and now - cached[0] <= UP_DOWN_TARGET_DISK_CACHE_TTL_SECONDS:
                return True, cached[1]
            if cached:
                self._price_target_cache.pop(symbol, None)
        return False, None

    def _fetch_price_target(self, symbol: str, *, force_refresh: bool = False) -> float | None:
        if not force_refresh:
            cached, target = self._cached_price_target(symbol)
            if cached:
                return target
        target = self._load_price_target(symbol)
        with self._price_target_cache_lock:
            self._price_target_cache[symbol] = (time.time(), target)
        return target

    def _load_price_target(self, symbol: str) -> float | None:
        try:
            payload = yf.Ticker(self._yahoo_symbol(symbol)).get_analyst_price_targets()
        except Exception as exc:
            logger.info("Up/Down analyst target metadata unavailable for %s: %s", symbol, exc)
            return None
        value = payload.get("mean") if isinstance(payload, dict) else None
        try:
            target = float(value)
        except (TypeError, ValueError):
            return None
        return target if math.isfinite(target) and target > 0 else None

    @staticmethod
    def _yahoo_symbol(symbol: Any) -> str:
        return str(symbol or "").upper().strip().replace(".", "-")

    def _history_frame_for_symbol(self, history: Any, symbol: str, symbol_count: int) -> Any:
        if history is None or getattr(history, "empty", True):
            return None
        try:
            columns = history.columns
        except Exception:
            return None
        try:
            if isinstance(columns, pd.MultiIndex):
                if symbol in columns.get_level_values(0):
                    return history[symbol]
                if symbol in columns.get_level_values(1):
                    return history.xs(symbol, axis=1, level=1)
            if symbol_count == 1:
                return history
        except Exception:
            return None
        return None

    @staticmethod
    def _close_series(frame: Any) -> Any:
        if frame is None or getattr(frame, "empty", True):
            return None
        for column in ("Close", "Adj Close"):
            try:
                if column in frame.columns:
                    return frame[column]
            except Exception:
                continue
        return None


def _clean_close_series(close: Any) -> Any:
    if close is None or getattr(close, "empty", True):
        return None
    try:
        series = pd.to_numeric(close, errors="coerce").dropna().astype(float)
        series.index = pd.DatetimeIndex(pd.to_datetime(series.index, errors="coerce")).tz_localize(None)
        series = series[pd.notna(series.index)]
        series = series[series > 0].sort_index()
    except Exception:
        return None
    return series if len(series) >= 2 else None


def _select_interval_series(values: Any, interval_key: str, *, latest_time: Any) -> Any:
    key = str(interval_key or "1d").strip().lower()
    if key == "1d":
        return values.tail(1)
    if key == "5d":
        return values.tail(5)
    if key == "30d":
        return values.tail(30)
    if key == "ytd":
        start = pd.Timestamp(year=int(latest_time.year), month=1, day=1)
        return values[values.index >= start]
    if key == "1y":
        start = pd.Timestamp(latest_time) - pd.DateOffset(years=1)
        return values[values.index >= start]
    return values.tail(1)


def _interval_return(series: Any, selected_index: Any) -> float | None:
    if series is None or getattr(series, "empty", True) or len(selected_index) <= 0:
        return None
    try:
        first_end = selected_index[0]
        end_position = int(series.index.get_indexer([first_end])[0])
        base_position = max(0, end_position - 1)
        base = float(series.iloc[base_position])
        latest = float(series.iloc[-1])
    except Exception:
        return None
    if not base or not math.isfinite(base) or not math.isfinite(latest):
        return None
    return (latest - base) / base * 100.0
