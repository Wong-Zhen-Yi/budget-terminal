from __future__ import annotations

from typing import Any, Iterable


def returns_cache_key(portfolio_id: Any, timeframe_key: Any, symbols: Iterable[Any]) -> tuple[Any, ...]:
    normalized = tuple(sorted(str(symbol or "").upper().strip() for symbol in symbols if str(symbol or "").strip()))
    return str(portfolio_id), str(timeframe_key), normalized


def filtered_weights(
    metrics_map: Any,
    included_tickers: Iterable[Any],
    cash_balance: Any,
) -> tuple[dict[Any, float], float]:
    metrics = metrics_map if isinstance(metrics_map, dict) else {}
    included = list(included_tickers)
    cash = max(float(cash_balance or 0.0), 0.0)
    stock_value = sum(
        max(float((metrics.get(ticker, {}) or {}).get("market_value", 0.0) or 0.0), 0.0)
        for ticker in included
    )
    denominator = stock_value + cash
    weights = {
        ticker: (
            max(float((metrics.get(ticker, {}) or {}).get("market_value", 0.0) or 0.0), 0.0)
            / denominator
            * 100.0
            if denominator > 0.0
            else 0.0
        )
        for ticker in included
    }
    if cash > 0.0 and denominator > 0.0:
        weights["CASH"] = cash / denominator * 100.0
    return weights, denominator


def filtered_summary(
    metrics_map: Any,
    included_tickers: Iterable[Any],
    cash_balance: Any,
) -> dict[str, float]:
    metrics = metrics_map if isinstance(metrics_map, dict) else {}
    stock_value = 0.0
    stock_pnl = 0.0
    for ticker in included_tickers:
        row = metrics.get(ticker, {}) or {}
        try:
            stock_value += float(row.get("market_value", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            stock_pnl += float(row.get("dollar_gain", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
    cash = float(cash_balance or 0.0)
    return {
        "checked_stock_value": stock_value,
        "checked_stock_pnl": stock_pnl,
        "filtered_total": stock_value + cash,
    }
