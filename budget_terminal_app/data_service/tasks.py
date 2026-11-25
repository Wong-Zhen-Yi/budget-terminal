from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable

from ..dependencies import logger
from .results import (
    FRESHNESS_FAILED,
    FRESHNESS_FRESH,
    FRESHNESS_PARTIAL,
    FRESHNESS_STALE,
    attach_market_data_result,
    make_market_data_error,
    make_market_data_meta,
    market_data_meta,
)


@dataclass
class MarketDataTaskResult:
    data: Any
    meta: dict[str, Any]
    errors: list[dict[str, Any]] = field(default_factory=list)

    def attach(self) -> Any:
        return attach_market_data_result(self.data, meta=self.meta, errors=self.errors)


class MarketDataTaskRunner:
    """Run market-data callables with consistent retry, timeout, fallback, and logs."""

    def __init__(self, default_timeout_seconds: float = 60.0, default_retries: int = 0) -> None:
        self.default_timeout_seconds = float(default_timeout_seconds)
        self.default_retries = max(int(default_retries), 0)

    def run(
        self,
        operation: str,
        fn: Callable[[], Any],
        *,
        source: str = "yfinance",
        timeout_seconds: float | None = None,
        retries: int | None = None,
        cache_fallback: Callable[[], Any] | None = None,
        cache_source: str = "cache",
        cache_age_seconds: float | None = None,
        partial: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        success_check: Callable[[Any], bool] | None = None,
        failure_reason: str = "Market data unavailable.",
    ) -> MarketDataTaskResult:
        """Execute one task and return data with normalized metadata."""
        timeout = self.default_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        attempts = (self.default_retries if retries is None else max(int(retries), 0)) + 1
        errors: list[dict[str, Any]] = []
        started = time.perf_counter()
        for attempt in range(1, attempts + 1):
            if self._is_cancelled(cancel_check):
                reason = "Market data request was cancelled."
                logger.info("%s cancelled before attempt %s.", operation, attempt)
                return self._failed_result(source, operation, reason, errors)
            try:
                data = self._call_with_timeout(fn, timeout)
                if self._is_cancelled(cancel_check):
                    reason = "Market data request was cancelled."
                    logger.info("%s cancelled after attempt %s.", operation, attempt)
                    return self._failed_result(source, operation, reason, errors)
                if success_check is not None and not success_check(data):
                    raise ValueError(failure_reason)
                freshness = FRESHNESS_PARTIAL if partial else FRESHNESS_FRESH
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                logger.info(
                    "%s loaded from %s in %.1f ms (attempt %s/%s, freshness=%s).",
                    operation,
                    source,
                    elapsed_ms,
                    attempt,
                    attempts,
                    freshness,
                )
                existing_meta = market_data_meta(data)
                if existing_meta.get("source") and existing_meta.get("source") != "unknown":
                    meta = existing_meta
                else:
                    meta = make_market_data_meta(
                        source=source,
                        freshness=freshness,
                        failure_reason=failure_reason if partial else "",
                    )
                return MarketDataTaskResult(data=data, meta=meta, errors=errors)
            except Exception as exc:
                retryable = attempt < attempts
                errors.append(
                    make_market_data_error(
                        source=source,
                        reason=str(exc) or failure_reason,
                        operation=operation,
                        exception=exc,
                        retryable=retryable,
                    )
                )
                logger.warning(
                    "%s failed from %s on attempt %s/%s: %s",
                    operation,
                    source,
                    attempt,
                    attempts,
                    exc,
                )
                if retryable:
                    time.sleep(min(0.25 * attempt, 1.0))

        fallback_result = self._load_cache_fallback(
            operation,
            cache_fallback,
            cache_source=cache_source,
            cache_age_seconds=cache_age_seconds,
            errors=errors,
            failure_reason=failure_reason,
        )
        if fallback_result is not None:
            return fallback_result
        return self._failed_result(source, operation, failure_reason, errors)

    def _call_with_timeout(self, fn: Callable[[], Any], timeout_seconds: float) -> Any:
        if timeout_seconds <= 0:
            return fn()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(fn)
            try:
                return future.result(timeout=timeout_seconds)
            except TimeoutError as exc:
                future.cancel()
                raise TimeoutError(f"timed out after {timeout_seconds:.1f}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _load_cache_fallback(
        self,
        operation: str,
        cache_fallback: Callable[[], Any] | None,
        *,
        cache_source: str,
        cache_age_seconds: float | None,
        errors: list[dict[str, Any]],
        failure_reason: str,
    ) -> MarketDataTaskResult | None:
        if cache_fallback is None:
            return None
        try:
            fallback = cache_fallback()
        except Exception as exc:
            logger.warning("%s cache fallback failed: %s", operation, exc)
            errors.append(
                make_market_data_error(
                    source=cache_source,
                    reason=str(exc) or "Cached market data unavailable.",
                    operation=operation,
                    exception=exc,
                )
            )
            return None
        if fallback is None or getattr(fallback, "empty", False):
            return None
        logger.info("%s using stale/partial cache fallback from %s.", operation, cache_source)
        return MarketDataTaskResult(
            data=fallback,
            meta=make_market_data_meta(
                source=cache_source,
                freshness=FRESHNESS_STALE,
                cache_age_seconds=cache_age_seconds,
                failure_reason=failure_reason,
            ),
            errors=errors,
        )

    def _failed_result(
        self,
        source: str,
        operation: str,
        failure_reason: str,
        errors: list[dict[str, Any]],
    ) -> MarketDataTaskResult:
        if not errors:
            errors = [
                make_market_data_error(
                    source=source,
                    reason=failure_reason,
                    operation=operation,
                )
            ]
        return MarketDataTaskResult(
            data={},
            meta=make_market_data_meta(
                source=source,
                freshness=FRESHNESS_FAILED,
                failure_reason=failure_reason,
            ),
            errors=errors,
        )

    def _is_cancelled(self, cancel_check: Callable[[], bool] | None) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False
