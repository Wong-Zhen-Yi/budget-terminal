from __future__ import annotations

import datetime as dt
import math
from dataclasses import replace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from budget_terminal_app.dependencies import YF_LOCK, yf

from .models import PaperQuote, parse_timestamp


class YahooPaperQuoteService:
    """Load execution-grade stock and ETF quote fields directly from yfinance."""

    HISTORICAL_WINDOW_MINUTES = 15

    def __init__(
        self,
        fetch_info: Callable[[str], dict[str, Any]] | None = None,
        fetch_history: Callable[[str, dt.date, dt.date], Any] | None = None,
    ) -> None:
        self._fetch_info = fetch_info or self._yahoo_info
        self._fetch_history = fetch_history or self._yahoo_history

    def fetch(self, symbol: str) -> PaperQuote:
        clean_symbol = str(symbol or "").upper().strip()
        if not clean_symbol:
            raise ValueError("A symbol is required.")
        info = self._fetch_info(clean_symbol)
        if not isinstance(info, dict):
            raise RuntimeError(f"Yahoo returned no quote for {clean_symbol}.")
        return self._quote_from_info(clean_symbol, info)

    def fetch_historical(self, symbol: str, scheduled_for: dt.datetime) -> PaperQuote:
        """Load the first extended-hours minute quote at or shortly after a scheduled time."""
        clean_symbol = str(symbol or "").upper().strip()
        if not clean_symbol:
            raise ValueError("A symbol is required.")
        target = scheduled_for
        if target.tzinfo is None:
            target = target.replace(tzinfo=dt.timezone.utc)
        target = target.astimezone(dt.timezone.utc)
        market_target = target.astimezone(ZoneInfo("America/New_York"))
        start_date = market_target.date()
        end_date = start_date + dt.timedelta(days=1)
        info = self._fetch_info(clean_symbol)
        if not isinstance(info, dict):
            raise RuntimeError(f"Yahoo returned no metadata for {clean_symbol}.")
        history = self._fetch_history(clean_symbol, start_date, end_date)
        if history is None or getattr(history, "empty", True):
            raise RuntimeError(
                f"Yahoo returned no one-minute extended-hours history for {clean_symbol} "
                f"on {start_date.isoformat()}."
            )
        try:
            rows = history.sort_index()
        except Exception as exc:
            raise RuntimeError(f"Yahoo returned invalid historical data for {clean_symbol}.") from exc
        deadline = target + dt.timedelta(minutes=self.HISTORICAL_WINDOW_MINUTES)
        selected_timestamp: dt.datetime | None = None
        selected_price: float | None = None
        for index, row in rows.iterrows():
            timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
            if not isinstance(timestamp, dt.datetime):
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo("America/New_York"))
            timestamp = timestamp.astimezone(dt.timezone.utc)
            if timestamp < target:
                continue
            if timestamp > deadline:
                break
            try:
                price = _positive_number(row.get("Open"))
            except AttributeError:
                price = None
            if price is not None:
                selected_timestamp = timestamp
                selected_price = price
                break
        if selected_timestamp is None or selected_price is None:
            raise RuntimeError(
                f"Yahoo returned no usable {clean_symbol} candle within "
                f"{self.HISTORICAL_WINDOW_MINUTES} minutes of {target.isoformat()}."
            )

        quote = self._quote_from_info(clean_symbol, info)
        market_time = selected_timestamp.astimezone(ZoneInfo("America/New_York")).time()
        is_premarket = market_time < dt.time(9, 30)
        return replace(
            quote,
            bid=selected_price,
            ask=selected_price,
            last_price=selected_price,
            market_state="PRE" if is_premarket else "REGULAR",
            source_timestamp=selected_timestamp,
            fetched_at=dt.datetime.now(dt.timezone.utc),
            source="Yahoo Finance historical 1m",
            mark_price=selected_price if is_premarket else None,
            mark_timestamp=selected_timestamp if is_premarket else None,
            mark_session="PRE" if is_premarket else "",
        )

    @staticmethod
    def _quote_from_info(clean_symbol: str, info: dict[str, Any]) -> PaperQuote:
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

    @staticmethod
    def _yahoo_history(symbol: str, start_date: dt.date, end_date: dt.date) -> Any:
        with YF_LOCK:
            return yf.Ticker(symbol).history(
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                interval="1m",
                prepost=True,
                auto_adjust=False,
            )


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
