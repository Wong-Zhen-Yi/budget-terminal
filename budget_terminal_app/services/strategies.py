from __future__ import annotations

from typing import Any

from ..dependencies import YF_LOCK, pd, yf
from .dashboard_payloads import extract_close_series


STRATEGY_INTERVALS = {
    "1d": {"label": "1 Day", "period": "1d", "interval": "5m"},
    "30d": {"label": "30D", "period": "1mo", "interval": "1d"},
    "1y": {"label": "1Y", "period": "1y", "interval": "1d"},
}


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
    """Fetch compact equal-weight performance series for strategy cards."""

    def fetch(
        self,
        symbols: list[str],
        interval_key: Any,
        *,
        weighting: str = "equal",
        weights: dict[str, float] | None = None,
        shares: dict[str, float] | None = None,
        cash_balance: float = 0.0,
    ) -> dict[str, Any]:
        unique_symbols = []
        for value in symbols:
            symbol = str(value or "").upper().strip()
            if symbol and symbol not in unique_symbols:
                unique_symbols.append(symbol)
        if not unique_symbols:
            raise ValueError("This basket has no tickers.")
        key = str(interval_key or "1y").strip().lower()
        config = STRATEGY_INTERVALS.get(key, STRATEGY_INTERVALS["1y"])
        with YF_LOCK:
            frame = yf.download(
                unique_symbols,
                period=config["period"],
                interval=config["interval"],
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
            )
        close_by_symbol = {}
        for symbol in unique_symbols:
            series = extract_close_series(frame, unique_symbols, symbol)
            if series is not None and not getattr(series, "empty", True):
                close_by_symbol[symbol] = series
        payload = weighted_performance(
            close_by_symbol,
            weighting=weighting,
            weights=weights,
            shares=shares,
            cash_balance=cash_balance,
        )
        payload.update({
            "interval_key": key,
            "requested_symbols": unique_symbols,
            "missing_symbols": [symbol for symbol in unique_symbols if symbol not in payload["included_symbols"]],
            "source": "Yahoo Finance",
        })
        return payload
