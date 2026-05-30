from __future__ import annotations

import math
from typing import Any

from budget_terminal_app.table_cells import TableCell, TableRow

DASHBOARD_MISSING_NUMERIC_SORT_VALUE = float("-inf")


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError, OverflowError):
        return False


def format_dashboard_currency(value: Any, *, decimals: int = 2) -> str:
    return f"${coerce_float(value):,.{decimals}f}"


def optional_float(value: Any) -> float | None:
    if is_missing_value(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def dashboard_portfolio_market_value(ticker: Any, info: Any, tracker: dict[str, Any]) -> float:
    tracker_entry = tracker.get(ticker, {}) if isinstance(tracker, dict) else {}
    shares = coerce_float(tracker_entry.get("shares", 0) if isinstance(tracker_entry, dict) else 0)
    price = coerce_float(info.get("price", 0) if isinstance(info, dict) else 0)
    return shares * price if shares else 0.0


def dashboard_portfolio_dollar_gain_sort_value(ticker: Any, info: Any, tracker: dict[str, Any]) -> float:
    tracker_entry = tracker.get(ticker, {}) if isinstance(tracker, dict) else {}
    shares = coerce_float(tracker_entry.get("shares", 0) if isinstance(tracker_entry, dict) else 0)
    avg_price = coerce_float(tracker_entry.get("avg_price", 0) if isinstance(tracker_entry, dict) else 0)
    price = coerce_float(info.get("price", 0) if isinstance(info, dict) else 0)
    return (price - avg_price) * shares if shares else 0.0


def build_dashboard_portfolio_rows(
    tickers: list[Any],
    quote_map: dict[str, Any],
    tracker: dict[str, Any],
    *,
    default_color: str,
    positive_color: str,
    negative_color: str,
    positive_bg: str,
    negative_bg: str,
    no_quote_bg: str,
) -> list[tuple[str, TableRow]]:
    """Return sorted Dashboard portfolio table rows and their ticker ids."""
    portfolio = {}
    for ticker in tickers:
        info = quote_map.get(ticker, {}) if isinstance(quote_map, dict) else {}
        portfolio[ticker] = info if isinstance(info, dict) else {}
    total_value = sum(dashboard_portfolio_market_value(ticker, info, tracker) for ticker, info in portfolio.items())
    sorted_items = sorted(
        portfolio.items(),
        key=lambda item: dashboard_portfolio_dollar_gain_sort_value(item[0], item[1], tracker),
        reverse=True,
    )
    rows: list[tuple[str, TableRow]] = []
    for ticker, info in sorted_items:
        tracker_entry = tracker.get(ticker, {}) if isinstance(tracker, dict) else {}
        has_quote = isinstance(info, dict) and ("price" in info or "change" in info)
        price = coerce_float(info.get("price", 0) if isinstance(info, dict) else 0)
        change_pct = coerce_float(info.get("change", 0) if isinstance(info, dict) else 0)
        shares = coerce_float(tracker_entry.get("shares", 0) if isinstance(tracker_entry, dict) else 0)
        avg_price = coerce_float(tracker_entry.get("avg_price", 0) if isinstance(tracker_entry, dict) else 0)
        market_value = shares * price if shares else 0.0
        weight_pct = market_value / total_value * 100 if total_value > 0 and shares and has_quote else 0.0
        dollar_gain = (price - avg_price) * shares if shares and has_quote else 0.0
        is_up = change_pct >= 0
        change_sign = "+" if is_up else ""
        gain_sign = "+" if dollar_gain >= 0 else ""
        row_bg = positive_bg if is_up else negative_bg
        change_color = positive_color if is_up else negative_color
        gain_color = positive_color if dollar_gain >= 0 else negative_color
        price_text = f"${price:.2f}"
        change_text = f"{change_sign}{change_pct:.2f}%"
        weight_text = f"{weight_pct:.1f}%" if shares and has_quote else "--"
        gain_text = f"{gain_sign}${dollar_gain:,.0f}" if shares and has_quote else "--"
        price_sort = price
        change_sort = change_pct
        weight_sort = weight_pct if shares and has_quote else DASHBOARD_MISSING_NUMERIC_SORT_VALUE
        gain_sort = dollar_gain if shares and has_quote else DASHBOARD_MISSING_NUMERIC_SORT_VALUE
        if not has_quote:
            row_bg = no_quote_bg
            change_color = default_color
            gain_color = default_color
            price_text = "--"
            change_text = "--"
            price_sort = DASHBOARD_MISSING_NUMERIC_SORT_VALUE
            change_sort = DASHBOARD_MISSING_NUMERIC_SORT_VALUE
        rows.append(
            (
                str(ticker or ""),
                (
                    TableCell(str(ticker or ""), foreground=default_color, background=row_bg),
                    TableCell(price_text, foreground=default_color, background=row_bg, sort_value=price_sort),
                    TableCell(change_text, foreground=change_color, background=row_bg, sort_value=change_sort),
                    TableCell(weight_text, foreground=default_color, background=row_bg, sort_value=weight_sort),
                    TableCell(gain_text, foreground=gain_color if shares else default_color, background=row_bg, sort_value=gain_sort),
                ),
            )
        )
    return rows


def build_dashboard_target_rows(
    targets: list[dict[str, Any]],
    *,
    positive_color: str,
    negative_color: str,
) -> list[TableRow]:
    """Return Dashboard analyst target table rows."""
    rows: list[TableRow] = []
    for item in targets:
        current = item.get("current")
        target = item.get("target")
        current_text = f"${current:.2f}" if isinstance(current, (int, float)) else str(current)
        target_text = f"${target:.2f}" if isinstance(target, (int, float)) else str(target)
        try:
            upside = (float(target) - float(current)) / float(current) * 100
            upside_text = f"{upside:+.1f}%"
            upside_color = positive_color if upside >= 0 else negative_color
            upside_sort = upside
        except (TypeError, ValueError, ZeroDivisionError):
            upside_text = "N/A"
            upside_color = None
            upside_sort = DASHBOARD_MISSING_NUMERIC_SORT_VALUE
        rows.append(
            (
                TableCell(str(item.get("ticker", ""))),
                TableCell(current_text, sort_value=coerce_float(current, DASHBOARD_MISSING_NUMERIC_SORT_VALUE)),
                TableCell(target_text, sort_value=coerce_float(target, DASHBOARD_MISSING_NUMERIC_SORT_VALUE)),
                TableCell(upside_text, foreground=upside_color, sort_value=upside_sort),
            )
        )
    return rows


def build_dashboard_option_rows(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    positive_color: str,
    negative_color: str,
) -> list[TableRow]:
    """Return Dashboard top-options table rows."""
    rows: list[TableRow] = []
    for opt in records:
        option_type = str(opt.get("type", "") or "")
        type_color = None
        if option_type == "Call":
            type_color = positive_color
        elif option_type == "Put":
            type_color = negative_color
        strike = opt.get("strike")
        last_price = opt.get("lastPrice")
        volume = opt.get("volume", 0)
        strike_value = optional_float(strike)
        price_value = optional_float(last_price)
        strike_text = f"{strike_value:.1f}" if strike_value is not None else ""
        price_text = f"{price_value:.2f}" if price_value is not None else ""
        try:
            volume_float = float(volume)
        except (TypeError, ValueError):
            volume_float = 0.0
        volume_text = f"{int(volume_float):,}" if math.isfinite(volume_float) and volume_float > 0 else "0"
        rows.append(
            (
                TableCell(str(opt.get("ticker", symbol) or symbol)),
                TableCell(option_type, foreground=type_color),
                TableCell(strike_text, sort_value=strike_value if strike_value is not None else DASHBOARD_MISSING_NUMERIC_SORT_VALUE),
                TableCell(str(opt.get("expiration", "") or "")),
                TableCell(price_text, sort_value=price_value if price_value is not None else DASHBOARD_MISSING_NUMERIC_SORT_VALUE),
                TableCell(volume_text, sort_value=volume_float if math.isfinite(volume_float) else DASHBOARD_MISSING_NUMERIC_SORT_VALUE),
            )
        )
    return rows
