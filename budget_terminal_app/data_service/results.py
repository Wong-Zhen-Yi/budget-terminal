from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any


MARKET_DATA_META_KEY = "_market_data_meta"
MARKET_DATA_ERRORS_KEY = "_market_data_errors"
FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_PARTIAL = "partial"
FRESHNESS_FAILED = "failed"
FRESHNESS_VALUES = {FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_PARTIAL, FRESHNESS_FAILED}


def utc_now_iso() -> str:
    """Return a stable UTC timestamp for market-data metadata."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class MarketDataError:
    source: str
    reason: str
    operation: str = ""
    symbol: str = ""
    exception_type: str = ""
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source": str(self.source or "unknown"),
            "reason": str(self.reason or "Market data unavailable."),
            "operation": str(self.operation or ""),
            "symbol": str(self.symbol or ""),
            "exception_type": str(self.exception_type or ""),
            "retryable": bool(self.retryable),
        }
        return {key: value for key, value in payload.items() if value not in ("", None)}


@dataclass
class MarketDataMeta:
    source: str = "unknown"
    fetched_at: str = field(default_factory=utc_now_iso)
    cache_age_seconds: float | None = None
    freshness: str = FRESHNESS_FRESH
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        freshness = str(self.freshness or FRESHNESS_FRESH).strip().lower()
        if freshness not in FRESHNESS_VALUES:
            freshness = FRESHNESS_FRESH
        cache_age = _finite_float(self.cache_age_seconds)
        return {
            "source": str(self.source or "unknown"),
            "fetched_at": str(self.fetched_at or utc_now_iso()),
            "cache_age_seconds": cache_age,
            "freshness": freshness,
            "is_stale": freshness == FRESHNESS_STALE,
            "is_partial": freshness == FRESHNESS_PARTIAL,
            "failure_reason": str(self.failure_reason or ""),
        }


def make_market_data_meta(
    *,
    source: Any = "unknown",
    fetched_at: Any = None,
    cache_age_seconds: Any = None,
    freshness: Any = FRESHNESS_FRESH,
    failure_reason: Any = "",
) -> dict[str, Any]:
    """Build one normalized market-data metadata dictionary."""
    return MarketDataMeta(
        source=str(source or "unknown"),
        fetched_at=str(fetched_at or utc_now_iso()),
        cache_age_seconds=cache_age_seconds,
        freshness=str(freshness or FRESHNESS_FRESH),
        failure_reason=str(failure_reason or ""),
    ).to_dict()


def make_market_data_error(
    *,
    source: Any = "unknown",
    reason: Any = "Market data unavailable.",
    operation: Any = "",
    symbol: Any = "",
    exception: BaseException | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build one normalized structured market-data error."""
    return MarketDataError(
        source=str(source or "unknown"),
        reason=str(reason or "Market data unavailable."),
        operation=str(operation or ""),
        symbol=str(symbol or ""),
        exception_type=type(exception).__name__ if exception is not None else "",
        retryable=bool(retryable),
    ).to_dict()


def normalize_market_data_errors(errors: Any) -> list[dict[str, Any]]:
    """Return a normalized list of market-data error dictionaries."""
    if errors is None:
        return []
    if isinstance(errors, dict):
        errors = [errors]
    normalized = []
    for item in list(errors or []):
        if isinstance(item, MarketDataError):
            normalized.append(item.to_dict())
        elif isinstance(item, dict):
            reason = str(item.get("reason") or item.get("message") or "").strip()
            if reason:
                normalized.append(
                    make_market_data_error(
                        source=item.get("source", "unknown"),
                        reason=reason,
                        operation=item.get("operation", ""),
                        symbol=item.get("symbol", ""),
                        retryable=bool(item.get("retryable", False)),
                    )
                )
        else:
            text = str(item or "").strip()
            if text:
                normalized.append(make_market_data_error(reason=text))
    return normalized


def market_data_meta(payload: Any) -> dict[str, Any]:
    """Extract market-data metadata from dictionaries or objects."""
    raw = {}
    if isinstance(payload, dict):
        raw = payload.get(MARKET_DATA_META_KEY, {})
    else:
        raw = getattr(payload, MARKET_DATA_META_KEY, {})
    if not isinstance(raw, dict):
        return make_market_data_meta()
    return make_market_data_meta(
        source=raw.get("source", "unknown"),
        fetched_at=raw.get("fetched_at"),
        cache_age_seconds=raw.get("cache_age_seconds"),
        freshness=raw.get("freshness", FRESHNESS_FRESH),
        failure_reason=raw.get("failure_reason", ""),
    )


def market_data_errors(payload: Any) -> list[dict[str, Any]]:
    """Extract market-data errors from dictionaries or objects."""
    if isinstance(payload, dict):
        return normalize_market_data_errors(payload.get(MARKET_DATA_ERRORS_KEY, []))
    return normalize_market_data_errors(getattr(payload, MARKET_DATA_ERRORS_KEY, []))


def attach_market_data_result(
    payload: Any,
    *,
    meta: dict[str, Any] | None = None,
    errors: Any = None,
) -> Any:
    """Attach compatibility metadata/errors to a dict or object payload."""
    normalized_meta = market_data_meta({MARKET_DATA_META_KEY: meta or {}})
    normalized_errors = normalize_market_data_errors(errors)
    if isinstance(payload, dict):
        existing_errors = normalize_market_data_errors(payload.get(MARKET_DATA_ERRORS_KEY, []))
        payload[MARKET_DATA_META_KEY] = normalized_meta
        payload[MARKET_DATA_ERRORS_KEY] = [*existing_errors, *normalized_errors]
        return payload
    try:
        existing_errors = normalize_market_data_errors(getattr(payload, MARKET_DATA_ERRORS_KEY, []))
        setattr(payload, MARKET_DATA_META_KEY, normalized_meta)
        setattr(payload, MARKET_DATA_ERRORS_KEY, [*existing_errors, *normalized_errors])
    except Exception:
        pass
    return payload


def strip_market_data_keys(payload: Any) -> Any:
    """Return a shallow copy of a dict without reserved metadata keys."""
    if not isinstance(payload, dict):
        return payload
    return {
        key: value
        for key, value in payload.items()
        if key not in {MARKET_DATA_META_KEY, MARKET_DATA_ERRORS_KEY}
    }


def data_sources_from_meta(payload: Any, default: str = "unknown") -> list[str]:
    """Return a user-readable source list from market-data metadata."""
    source = str(market_data_meta(payload).get("source") or default or "unknown").strip()
    if not source:
        return [default or "unknown"]
    parts = []
    for piece in source.replace("+", ",").split(","):
        text = piece.strip()
        if text and text not in parts:
            parts.append(text)
    return parts or [default or "unknown"]


def describe_market_data_status(payload: Any, success_text: str = "Market data loaded.") -> tuple[str, str]:
    """Return status text and status level for a payload's metadata."""
    meta = market_data_meta(payload)
    freshness = str(meta.get("freshness") or FRESHNESS_FRESH).lower()
    failure_reason = str(meta.get("failure_reason") or "").strip()
    source = str(meta.get("source") or "unknown").strip()
    if freshness == FRESHNESS_FAILED:
        return failure_reason or "Market data unavailable.", "negative"
    if freshness == FRESHNESS_STALE:
        base = failure_reason or "Showing cached market data."
        return f"{base} Source: {source}.", "warning"
    if freshness == FRESHNESS_PARTIAL:
        base = failure_reason or "Some market data was unavailable."
        return f"{base} Source: {source}.", "warning"
    return success_text, "positive"
