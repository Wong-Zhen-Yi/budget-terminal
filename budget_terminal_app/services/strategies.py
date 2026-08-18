from __future__ import annotations

import hashlib
from typing import Any

from ..cache import CacheManager
from ..dependencies import YF_LOCK, logger, pd, yf
from .dashboard_payloads import extract_close_series


STRATEGY_INTERVALS = {
    "1d": {"label": "1 Day", "period": "1d", "interval": "5m"},
    "30d": {"label": "30D", "period": "1mo", "interval": "1d"},
    "1y": {"label": "1Y", "period": "1y", "interval": "1d"},
}

STRATEGY_CACHE_NAMESPACE = "strategy_performance"
STRATEGY_CACHE_TTL_SECONDS = {"1d": 300.0, "30d": 1800.0, "1y": 3600.0}
STRATEGY_CACHE_MAX_AGE_SECONDS = 7.0 * 24.0 * 3600.0


def normalize_interval_key(interval_key: Any) -> str:
    """Return one supported interval key, falling back to the 1Y default."""
    key = str(interval_key or "1y").strip().lower()
    return key if key in STRATEGY_INTERVALS else "1y"


def unique_upper_symbols(symbols: Any) -> list[str]:
    """Return uppercase tickers in their original order without duplicates."""
    ordered: list[str] = []
    for value in symbols or []:
        symbol = str(value or "").upper().strip()
        if symbol and symbol not in ordered:
            ordered.append(symbol)
    return ordered


def strategy_signature(
    symbols: Any,
    interval_key: Any,
    *,
    weighting: str = "equal",
    weights: dict[str, float] | None = None,
    shares: dict[str, float] | None = None,
    cash_balance: float = 0.0,
) -> tuple[Any, ...]:
    """Build the stable identity of one basket request, shared by the memory and disk caches."""
    def _pairs(values: Any) -> tuple[Any, ...]:
        if not isinstance(values, dict):
            return ()
        pairs = []
        for key, value in values.items():
            try:
                pairs.append((str(key), round(float(value), 8)))
            except (TypeError, ValueError):
                continue
        return tuple(sorted(pairs))

    try:
        cash = round(float(cash_balance or 0.0), 8)
    except (TypeError, ValueError):
        cash = 0.0
    return (
        tuple(sorted(unique_upper_symbols(symbols))),
        normalize_interval_key(interval_key),
        str(weighting or "equal").strip().lower(),
        _pairs(weights),
        _pairs(shares),
        cash,
    )


def strategy_cache_key(signature: tuple[Any, ...]) -> str:
    """Hash one basket signature into a short, stable sqlite cache key."""
    return hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()


def weighted_performance(
    close_by_symbol: dict[str, Any],
    *,
    weighting: str = "equal",
    weights: dict[str, float] | None = None,
    shares: dict[str, float] | None = None,
    cash_balance: float = 0.0,
) -> dict[str, Any]:
    """Build a fixed-weight cumulative-return series from equal, custom, or position weights."""
    normalized_by_symbol = {}
    latest_prices = {}
    for symbol, raw_series in close_by_symbol.items():
        try:
            series = pd.Series(raw_series).astype(float).replace([float("inf"), float("-inf")], float("nan")).dropna()
        except Exception:
            continue
        series = series[series > 0.0]
        if len(series) < 2:
            continue
        series = series[~series.index.duplicated(keep="last")].sort_index()
        normalized_by_symbol[symbol] = series.rename(symbol) / float(series.iloc[0]) - 1.0
        latest_prices[symbol] = float(series.iloc[-1])
    included = list(normalized_by_symbol)
    if not included:
        raise ValueError("No usable price history was returned for this basket.")

    requested_mode = str(weighting or "equal").strip().lower()
    raw_weights = {}
    resolved_mode = requested_mode
    if requested_mode == "custom":
        source_weights = weights if isinstance(weights, dict) else {}
        for symbol in included:
            try:
                value = float(source_weights.get(symbol, 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0.0:
                raw_weights[symbol] = value
    elif requested_mode == "portfolio":
        source_shares = shares if isinstance(shares, dict) else {}
        for symbol in included:
            try:
                share_count = float(source_shares.get(symbol, 0.0) or 0.0)
            except (TypeError, ValueError):
                share_count = 0.0
            market_value = share_count * latest_prices.get(symbol, 0.0)
            if market_value > 0.0:
                raw_weights[symbol] = market_value
        if raw_weights:
            try:
                cash_value = float(cash_balance or 0.0)
            except (TypeError, ValueError):
                cash_value = 0.0
            if cash_value > 0.0:
                raw_weights["CASH"] = cash_value
        if not raw_weights:
            resolved_mode = "equal_fallback"
    else:
        resolved_mode = "equal"
    if not raw_weights:
        raw_weights = {symbol: 1.0 for symbol in included}
        if resolved_mode not in {"equal_fallback"}:
            resolved_mode = "equal"
    total_weight = sum(raw_weights.values())
    resolved_weights = {symbol: value / total_weight for symbol, value in raw_weights.items()}

    frame = pd.concat(list(normalized_by_symbol.values()), axis=1).sort_index().ffill()
    weighted_columns = []
    for symbol, weight in resolved_weights.items():
        if symbol in frame.columns:
            weighted_columns.append(frame[symbol] * weight)
    basket = pd.concat(weighted_columns, axis=1).sum(axis=1, min_count=1).dropna() * 100.0
    if len(basket) < 2:
        raise ValueError("Not enough price history was returned for this basket.")
    weighting_labels = {
        "equal": "Equal weight",
        "custom": "Custom weights",
        "portfolio": "Actual portfolio weights",
        "equal_fallback": "Equal weight fallback",
    }
    return {
        "values": [float(value) for value in basket.tolist()],
        "return_pct": float(basket.iloc[-1]),
        "points": int(len(basket)),
        "included_symbols": included,
        "weights": {symbol: weight * 100.0 for symbol, weight in resolved_weights.items()},
        "weighting": resolved_mode,
        "weighting_label": weighting_labels.get(resolved_mode, "Equal weight"),
    }


def equal_weight_performance(close_by_symbol: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible equal-weight performance helper."""
    return weighted_performance(close_by_symbol, weighting="equal")


class StrategyPerformanceService:
    """Fetch weighted performance series for strategy cards in one batched download per interval."""

    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        self.cache_manager = cache_manager or CacheManager()

    def _normalize_request(self, request: dict[str, Any], interval_key: str) -> dict[str, Any]:
        symbols = unique_upper_symbols(request.get("symbols", []))
        weighting = str(request.get("weighting", "equal") or "equal")
        weights = dict(request.get("weights", {}) or {})
        shares = dict(request.get("shares", {}) or {})
        try:
            cash_balance = float(request.get("cash_balance", 0.0) or 0.0)
        except (TypeError, ValueError):
            cash_balance = 0.0
        signature = strategy_signature(
            symbols,
            interval_key,
            weighting=weighting,
            weights=weights,
            shares=shares,
            cash_balance=cash_balance,
        )
        return {
            "key": request.get("key"),
            "symbols": symbols,
            "weighting": weighting,
            "weights": weights,
            "shares": shares,
            "cash_balance": cash_balance,
            "cache_key": strategy_cache_key(signature),
        }

    def _read_cache(self, cache_key: str, interval_key: str, *, allow_stale: bool) -> tuple[dict[str, Any] | None, bool]:
        """Return one cached payload plus whether it is still inside its interval TTL."""
        manager = self.cache_manager
        if manager is None:
            return None, False
        ttl = STRATEGY_CACHE_TTL_SECONDS.get(interval_key, 3600.0)
        max_age = STRATEGY_CACHE_MAX_AGE_SECONDS if allow_stale else ttl
        try:
            result = manager.get_json_payload(
                STRATEGY_CACHE_NAMESPACE,
                cache_key,
                max_age_seconds=max_age,
                return_metadata=True,
            )
        except Exception as exc:
            logger.debug("Strategy cache read failed for %s: %s", cache_key, exc)
            return None, False
        if not result:
            return None, False
        payload, metadata = result
        if not isinstance(payload, dict):
            return None, False
        try:
            age = float(metadata.get("cache_age_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            age = 0.0
        return payload, age < ttl

    def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        manager = self.cache_manager
        if manager is None:
            return
        try:
            manager.save_json_payload(STRATEGY_CACHE_NAMESPACE, cache_key, payload)
        except Exception as exc:
            logger.debug("Strategy cache write failed for %s: %s", cache_key, exc)

    def cached_payload(
        self,
        symbols: list[str],
        interval_key: Any,
        *,
        weighting: str = "equal",
        weights: dict[str, float] | None = None,
        shares: dict[str, float] | None = None,
        cash_balance: float = 0.0,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Return (payload, is_fresh) from disk without touching the network."""
        key = normalize_interval_key(interval_key)
        entry = self._normalize_request(
            {
                "symbols": symbols,
                "weighting": weighting,
                "weights": weights or {},
                "shares": shares or {},
                "cash_balance": cash_balance,
            },
            key,
        )
        if not entry["symbols"]:
            return None, False
        return self._read_cache(entry["cache_key"], key, allow_stale=True)

    def _download(self, symbols: list[str], config: dict[str, Any]) -> Any:
        with YF_LOCK:
            return yf.download(
                symbols,
                period=config["period"],
                interval=config["interval"],
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
            )

    def fetch_many(
        self,
        requests: list[dict[str, Any]],
        interval_key: Any,
        *,
        force: bool = False,
    ) -> dict[Any, dict[str, Any] | Exception]:
        """Resolve several baskets sharing one interval with a single upstream download.

        Each request carries a caller-supplied ``key`` plus ``symbols`` and the weighting
        inputs. The result maps every key to one payload or one exception, so a single bad
        basket never fails its neighbours.
        """
        key = normalize_interval_key(interval_key)
        config = STRATEGY_INTERVALS[key]
        results: dict[Any, dict[str, Any] | Exception] = {}
        pending: list[dict[str, Any]] = []
        for request in requests:
            entry = self._normalize_request(request, key)
            if not entry["symbols"]:
                results[entry["key"]] = ValueError("This basket has no tickers.")
                continue
            if not force:
                cached, is_fresh = self._read_cache(entry["cache_key"], key, allow_stale=False)
                if cached is not None and is_fresh:
                    results[entry["key"]] = cached
                    continue
            pending.append(entry)
        if not pending:
            return results

        union: list[str] = []
        for entry in pending:
            for symbol in entry["symbols"]:
                if symbol not in union:
                    union.append(symbol)
        try:
            frame = self._download(union, config)
        except Exception as exc:
            for entry in pending:
                results[entry["key"]] = exc
            return results

        close_by_symbol = {}
        for symbol in union:
            series = extract_close_series(frame, union, symbol)
            if series is not None and not getattr(series, "empty", True):
                close_by_symbol[symbol] = series

        for entry in pending:
            try:
                payload = weighted_performance(
                    {symbol: close_by_symbol[symbol] for symbol in entry["symbols"] if symbol in close_by_symbol},
                    weighting=entry["weighting"],
                    weights=entry["weights"],
                    shares=entry["shares"],
                    cash_balance=entry["cash_balance"],
                )
            except Exception as exc:
                results[entry["key"]] = exc
                continue
            payload.update({
                "interval_key": key,
                "requested_symbols": list(entry["symbols"]),
                "missing_symbols": [
                    symbol for symbol in entry["symbols"] if symbol not in payload["included_symbols"]
                ],
                "source": "Yahoo Finance",
            })
            self._write_cache(entry["cache_key"], payload)
            results[entry["key"]] = payload
        return results

    def fetch(
        self,
        symbols: list[str],
        interval_key: Any,
        *,
        weighting: str = "equal",
        weights: dict[str, float] | None = None,
        shares: dict[str, float] | None = None,
        cash_balance: float = 0.0,
        force: bool = False,
    ) -> dict[str, Any]:
        """Resolve one basket through the same batched path used by the page."""
        outcome = self.fetch_many(
            [{
                "key": "single",
                "symbols": symbols,
                "weighting": weighting,
                "weights": weights or {},
                "shares": shares or {},
                "cash_balance": cash_balance,
            }],
            interval_key,
            force=force,
        ).get("single")
        if isinstance(outcome, Exception):
            raise outcome
        if not isinstance(outcome, dict):
            raise ValueError("This basket has no tickers.")
        return outcome
