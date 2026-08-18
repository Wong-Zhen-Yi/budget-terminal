from __future__ import annotations

import math
from typing import Any, Iterable


def _positive_amount(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(number, 0.0)


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
    margin_debt: Any = 0.0,
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
    try:
        cash = max(float(cash_balance or 0.0), 0.0)
    except (TypeError, ValueError):
        cash = 0.0
    try:
        margin = max(float(margin_debt or 0.0), 0.0)
    except (TypeError, ValueError):
        margin = 0.0
    return {
        "checked_stock_value": stock_value,
        "checked_stock_pnl": stock_pnl,
        "filtered_total": stock_value + cash - margin,
    }


def settle_trade(cash_balance: Any, margin_debt: Any, cost_delta: Any) -> tuple[float, float]:
    """Settle a cost-basis change against cash first, then margin.

    A positive ``cost_delta`` (a buy) draws down cash and borrows the shortfall on margin.
    A negative ``cost_delta`` (a sell) repays margin debt first and credits the rest to cash.
    """
    cash = _positive_amount(cash_balance)
    margin = _positive_amount(margin_debt)
    try:
        delta = float(cost_delta or 0.0)
    except (TypeError, ValueError):
        delta = 0.0
    if not math.isfinite(delta) or delta == 0.0:
        return cash, margin
    if delta > 0.0:
        from_cash = min(cash, delta)
        return cash - from_cash, margin + (delta - from_cash)
    proceeds = -delta
    repaid = min(margin, proceeds)
    return cash + (proceeds - repaid), margin - repaid


def margin_utilization(stock_market_value: Any, cash_balance: Any, margin_debt: Any) -> float | None:
    """Return margin debt as a percent of gross assets, or None when there is nothing to report."""
    margin = _positive_amount(margin_debt)
    if margin <= 0.0:
        return None
    gross_assets = _positive_amount(stock_market_value) + _positive_amount(cash_balance)
    if gross_assets <= 0.0:
        return None
    return margin / gross_assets * 100.0
