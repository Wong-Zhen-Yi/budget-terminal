from __future__ import annotations

import math
from typing import Any

from budget_terminal_app.constants import (
    P4_PORTFOLIO_COL_ANALYST_PT,
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_COST,
    P4_PORTFOLIO_COL_DAY_CHANGE,
    P4_PORTFOLIO_COL_DOLLAR_GAIN,
    P4_PORTFOLIO_COL_GROWTH,
    P4_PORTFOLIO_COL_MARKET_CAP,
    P4_PORTFOLIO_COL_MARKET_VALUE,
    P4_PORTFOLIO_COL_PRICE,
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_SYMBOL,
    P4_PORTFOLIO_COL_WEIGHT,
)
from budget_terminal_app.table_cells import TableCell, TableRow

P4_MISSING_NUMERIC_SORT_VALUE = float("-inf")
P4_TRACKER_NUMERIC_COLUMNS = {
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_COST,
    P4_PORTFOLIO_COL_PRICE,
    P4_PORTFOLIO_COL_DAY_CHANGE,
    P4_PORTFOLIO_COL_MARKET_VALUE,
    P4_PORTFOLIO_COL_WEIGHT,
    P4_PORTFOLIO_COL_DOLLAR_GAIN,
    P4_PORTFOLIO_COL_GROWTH,
    P4_PORTFOLIO_COL_MARKET_CAP,
    P4_PORTFOLIO_COL_ANALYST_PT,
}


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def market_cap_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def format_market_cap_value(value: float) -> str:
    if value >= 1000000000000.0:
        return f"{value / 1000000000000.0:.2f}T"
    if value >= 1000000000.0:
        return f"{value / 1000000000.0:.2f}B"
    if value >= 1000000.0:
        return f"{value / 1000000.0:.2f}M"
    if value >= 1000.0:
        return f"{value / 1000.0:.1f}K"
    return f"{value:.2f}"


def format_market_cap(value: Any) -> str:
    number = market_cap_value(value)
    if number is None:
        return "--"
    if number >= 200000000000:
        bucket = "Mega"
    elif number >= 10000000000:
        bucket = "Large"
    elif number >= 2000000000:
        bucket = "Mid"
    elif number >= 300000000:
        bucket = "Small"
    else:
        bucket = "Micro"
    return f"{bucket} ${format_market_cap_value(number)}"


def market_cap_sort_value(value: Any) -> float:
    number = market_cap_value(value)
    return number if number is not None else P4_MISSING_NUMERIC_SORT_VALUE


def market_cap_color_token(value: Any) -> str:
    number = market_cap_value(value)
    if number is None:
        return "text_muted"
    if number >= 200000000000:
        return "warning"
    if number >= 10000000000:
        return "series_0"
    if number >= 2000000000:
        return "accent_positive"
    if number >= 300000000:
        return "series_3"
    return "accent_negative"


def analyst_target_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _format_compact_money(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"${round(value):,.0f}"
    return f"${value:,.2f}"


def _format_compact_signed_percent(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return f"{value:+.0f}%"
    return f"{value:+.1f}%"


def analyst_target_cell_text_and_sort(current_price: Any, analyst_target: Any) -> tuple[str, float]:
    current = analyst_target_value(current_price)
    target = analyst_target_value(analyst_target)
    if current is None or target is None:
        return "--", P4_MISSING_NUMERIC_SORT_VALUE
    upside = (target - current) / current * 100.0
    return f"{_format_compact_money(target)} ({_format_compact_signed_percent(upside)})", upside


def build_portfolio_stock_row(
    ticker: Any,
    metrics: dict[str, Any],
    *,
    default_color: str,
    gain_color: str,
    change_color: str,
    market_cap: Any = None,
    market_cap_color: str | None = None,
    analyst_target: Any = None,
    analyst_positive_color: str | None = None,
    analyst_negative_color: str | None = None,
    weight_included: bool = True,
) -> TableRow:
    """Return display cells for one Portfolio stock position row."""
    shares = coerce_float(metrics.get("shares"))
    avg_price = coerce_float(metrics.get("avg_price"))
    price = coerce_float(metrics.get("price"))
    change = coerce_float(metrics.get("change"))
    cost = coerce_float(metrics.get("cost"))
    market_value = coerce_float(metrics.get("market_value"))
    weight = coerce_float(metrics.get("weight"))
    dollar_gain = coerce_float(metrics.get("dollar_gain"))
    growth = coerce_float(metrics.get("growth"))
    sign = "+" if change >= 0 else ""
    gain_sign = "+" if dollar_gain >= 0 else ""
    growth_sign = "+" if growth >= 0 else ""
    analyst_text, analyst_sort = analyst_target_cell_text_and_sort(price, analyst_target)
    analyst_color = None
    if analyst_sort != P4_MISSING_NUMERIC_SORT_VALUE:
        analyst_color = analyst_positive_color if analyst_sort >= 0 else analyst_negative_color
    return (
        TableCell(str(ticker or ""), foreground=default_color),
        TableCell(f"{shares:g}", foreground=default_color, editable=True, sort_value=shares),
        TableCell(f"{avg_price:.2f}", foreground=default_color, editable=True, sort_value=avg_price),
        TableCell(f"${cost:,.2f}", foreground=default_color, sort_value=cost),
        TableCell(f"${price:.2f}", foreground=default_color, sort_value=price),
        TableCell(f"{sign}{change:.2f}%", foreground=change_color, sort_value=change),
        TableCell(f"${market_value:,.2f}", foreground=default_color, sort_value=market_value),
        TableCell(
            f"{weight:.1f}%" if weight_included else "--",
            foreground=default_color,
            sort_value=weight if weight_included else P4_MISSING_NUMERIC_SORT_VALUE,
        ),
        TableCell(f"{gain_sign}${dollar_gain:,.2f}", foreground=gain_color, sort_value=dollar_gain),
        TableCell(f"{growth_sign}{growth:.1f}%", foreground=gain_color, sort_value=growth),
        TableCell(
            format_market_cap(market_cap),
            foreground=market_cap_color,
            sort_value=market_cap_sort_value(market_cap),
        ),
        TableCell(
            analyst_text,
            foreground=analyst_color,
            sort_value=analyst_sort,
        ),
    )
