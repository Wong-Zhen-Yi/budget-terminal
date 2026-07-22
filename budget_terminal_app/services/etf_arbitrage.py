from __future__ import annotations

import datetime
import math
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(value: Any) -> str:
    return _text(value).upper()


def _field(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quote_move_pct(quote: Any) -> float | None:
    payload = quote if isinstance(quote, dict) else {}
    changes = payload.get("changes") if isinstance(payload.get("changes"), dict) else {}
    for key in ("live", "1d"):
        value = _finite_float(changes.get(key))
        if value is not None:
            return value
    return _finite_float(payload.get("change_pct"))


def quote_price(quote: Any) -> float | None:
    payload = quote if isinstance(quote, dict) else {}
    return _positive_float(payload.get("price"))


def holding_symbols(holdings: Any) -> list[str]:
    """Return unique positive-weight symbols from an ETF holdings list."""
    symbols: list[str] = []
    seen: set[str] = set()
    for holding in list(holdings or []):
        symbol = _symbol(_field(holding, "symbol", ""))
        weight = _positive_float(_field(holding, "weight"))
        if not symbol or weight is None or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def build_etf_arbitrage_snapshot(etf_symbol: Any, holdings: Any, quotes: Any) -> dict[str, Any]:
    """Build the raw return-gap snapshot for an ETF against its weighted basket."""
    ticker = _symbol(etf_symbol)
    quote_map = quotes if isinstance(quotes, dict) else {}
    total_holdings = 0
    loaded_weight = 0.0
    quoted_rows: list[dict[str, Any]] = []

    for holding in list(holdings or []):
        symbol = _symbol(_field(holding, "symbol", ""))
        name = _text(_field(holding, "name", ""))
        weight = _positive_float(_field(holding, "weight"))
        if not symbol or weight is None:
            continue
        total_holdings += 1
        loaded_weight += weight
        quote = quote_map.get(symbol) or {}
        price = quote_price(quote)
        move_pct = _quote_move_pct(quote)
        if price is None or move_pct is None:
            continue
        quoted_rows.append(
            {
                "symbol": symbol,
                "name": name,
                "weight": weight,
                "price": price,
                "move_pct": move_pct,
            }
        )

    quoted_weight = sum(float(row["weight"]) for row in quoted_rows)
    basket_move_pct = None
    if quoted_weight > 0.0:
        basket_move_pct = 0.0
        for row in quoted_rows:
            normalized_weight = float(row["weight"]) / quoted_weight
            contribution = normalized_weight * float(row["move_pct"])
            row["normalized_weight"] = normalized_weight
            row["contribution_pct"] = contribution
            basket_move_pct += contribution

    etf_quote = quote_map.get(ticker) or {}
    etf_price = quote_price(etf_quote)
    etf_move_pct = _quote_move_pct(etf_quote)
    gap_pct_points = None
    gap_bps = None
    signal = "--"
    if etf_move_pct is not None and basket_move_pct is not None:
        gap_pct_points = float(etf_move_pct) - float(basket_move_pct)
        gap_bps = gap_pct_points * 100.0
        if abs(gap_pct_points) < 1e-9:
            signal = "No gap"
        elif gap_pct_points > 0:
            signal = "ETF rich vs basket"
        else:
            signal = "ETF cheap vs basket"

    return {
        "ticker": ticker,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "etf_price": etf_price,
        "etf_move_pct": etf_move_pct,
        "basket_move_pct": basket_move_pct,
        "gap_pct_points": gap_pct_points,
        "gap_bps": gap_bps,
        "signal": signal,
        "quote_coverage": len(quoted_rows),
        "total_holdings": total_holdings,
        "quoted_weight": quoted_weight,
        "loaded_weight": loaded_weight,
        "rows": quoted_rows,
    }


class EtfArbitrageDataService:
    """Fetch quotes and compare an ETF move against its loaded holdings basket."""

    def fetch(self, holdings_result: Any) -> dict[str, Any]:
        ticker = _symbol(_field(holdings_result, "ticker", ""))
        holdings = list(_field(holdings_result, "holdings", []) or [])
        if not ticker:
            raise ValueError("Load an ETF before refreshing arbitrage.")
        symbols = [ticker]
        symbols.extend(symbol for symbol in holding_symbols(holdings) if symbol != ticker)
        from budget_terminal_app.workers.etf_heatmap import EtfHeatmapWorker

        quotes = EtfHeatmapWorker()._fetch_quotes(symbols)
        return build_etf_arbitrage_snapshot(ticker, holdings, quotes)
