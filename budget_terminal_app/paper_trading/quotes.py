from __future__ import annotations

import datetime as dt
import math
from typing import Any, Callable

from budget_terminal_app.dependencies import YF_LOCK, yf

from .models import PaperQuote, parse_timestamp


class YahooPaperQuoteService:
    """Load execution-grade stock and ETF quote fields directly from yfinance."""

    def __init__(self, fetch_info: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._fetch_info = fetch_info or self._yahoo_info

    def fetch(self, symbol: str) -> PaperQuote:
        clean_symbol = str(symbol or "").upper().strip()
        if not clean_symbol:
            raise ValueError("A symbol is required.")
        info = self._fetch_info(clean_symbol)
        if not isinstance(info, dict):
            raise RuntimeError(f"Yahoo returned no quote for {clean_symbol}.")
        market_state = str(info.get("marketState") or "").upper().strip()
        premarket_price = _positive_number(info.get("preMarketPrice")) if market_state == "PRE" else None
        premarket_timestamp = parse_timestamp(info.get("preMarketTime")) if premarket_price is not None else None
        return PaperQuote(
            symbol=clean_symbol,
            bid=_positive_number(info.get("bid")),
            ask=_positive_number(info.get("ask")),
            bid_size=_nonnegative_int(info.get("bidSize")),
            ask_size=_nonnegative_int(info.get("askSize")),
            last_price=_positive_number(
                info.get("regularMarketPrice"),
                info.get("currentPrice"),
                info.get("previousClose"),
            ),
            exchange=str(info.get("exchange") or "").upper().strip(),
            currency=str(info.get("currency") or "USD").upper().strip(),
            quote_type=str(info.get("quoteType") or "").upper().strip(),
            market_state=market_state,
            source_timestamp=parse_timestamp(info.get("regularMarketTime")),
            fetched_at=dt.datetime.now(dt.timezone.utc),
            mark_price=premarket_price,
            mark_timestamp=premarket_timestamp,
            mark_session="PRE" if premarket_price is not None else "",
        )

    @staticmethod
    def _yahoo_info(symbol: str) -> dict[str, Any]:
        with YF_LOCK:
            payload = yf.Ticker(symbol).get_info()
        return dict(payload) if isinstance(payload, dict) else {}


def _positive_number(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _nonnegative_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(number, 0)
