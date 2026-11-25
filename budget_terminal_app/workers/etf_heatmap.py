from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from ..data_service.results import attach_market_data_result, make_market_data_error, make_market_data_meta
from ..dependencies import ThreadPoolExecutor, YF_LOCK, logger, pd, requests, yf
from ..etf_holdings import EtfHoldingsService


@dataclass
class EtfHeatmapHolding:
    symbol: str
    name: str = ""
    sector: str = ""
    weight: float | None = None
    price: float | None = None
    change_pct: float | None = None
    changes: dict[str, float] = field(default_factory=dict)


@dataclass
class EtfHeatmapIntervalSummary:
    quote_coverage: int = 0
    weighted_move: float | None = None
    strongest: EtfHeatmapHolding | None = None
    weakest: EtfHeatmapHolding | None = None


@dataclass
class EtfHeatmapResult:
    ticker: str
    fund_name: str = ""
    issuer: str = ""
    as_of_date: str = ""
    source_url: str = ""
    holdings: list[EtfHeatmapHolding] = field(default_factory=list)
    holdings_loaded: int = 0
    quote_coverage: int = 0
    weighted_day_move: float | None = None
    strongest: EtfHeatmapHolding | None = None
    weakest: EtfHeatmapHolding | None = None
    interval_summaries: dict[str, EtfHeatmapIntervalSummary] = field(default_factory=dict)


class EtfHeatmapWorker:
    """Build a quote-enriched ETF holdings payload for heatmap rendering."""

    INTERVALS: tuple[str, ...] = ("live", "1d", "1w", "1m", "3m", "ytd", "1y")
    _SP500_SECTOR_CACHE: tuple[float, dict[str, str]] | None = None
    _SP500_SECTOR_TTL_SECONDS = 24 * 60 * 60.0

    def __init__(self, holdings_service: EtfHoldingsService | None = None) -> None:
        self._holdings_service = holdings_service or EtfHoldingsService()

    def fetch(self, ticker: str) -> EtfHeatmapResult:
        """Load ETF holdings and enrich them with latest daily quote changes."""
        symbol = str(ticker or "").upper().strip()
        result = self._holdings_service.load(symbol)
        sector_map = self._load_sp500_sector_map() if symbol == "SPY" else {}
        holdings = []
        for holding in list(getattr(result, "holdings", []) or []):
            holding_symbol = str(getattr(holding, "symbol", "") or "").upper().strip()
            if not self._is_usable_symbol(holding_symbol):
                continue
            if symbol == "SPY" and sector_map and holding_symbol not in sector_map and holding_symbol.replace("-", ".") not in sector_map:
                continue
            holdings.append(
                EtfHeatmapHolding(
                    symbol=holding_symbol,
                    name=str(getattr(holding, "name", "") or "").strip(),
                    sector=self._resolve_sector(holding_symbol, getattr(holding, "sector", ""), sector_map),
                    weight=self._positive_float(getattr(holding, "weight", None)),
                )
            )
        holdings = [holding for holding in holdings if holding.weight]
        quotes = self._fetch_quotes([holding.symbol for holding in holdings])
        for holding in holdings:
            quote = quotes.get(holding.symbol) or {}
            holding.price = quote.get("price")
            holding.change_pct = quote.get("change_pct")
            holding.changes = dict(quote.get("changes") or {})
            if "live" not in holding.changes and isinstance(holding.change_pct, (int, float)):
                holding.changes["live"] = float(holding.change_pct)

        interval_summaries = {key: self._interval_summary(holdings, key) for key in self.INTERVALS}
        live_summary = interval_summaries.get("live") or EtfHeatmapIntervalSummary()
        payload = EtfHeatmapResult(
            ticker=symbol,
            fund_name=str(getattr(result, "fund_name", "") or "").strip(),
            issuer=str(getattr(result, "issuer", "") or "").strip(),
            as_of_date=str(getattr(result, "as_of_date", "") or "").strip(),
            source_url=str(getattr(result, "source_url", "") or "").strip(),
            holdings=holdings,
            holdings_loaded=len(holdings),
            quote_coverage=live_summary.quote_coverage,
            weighted_day_move=live_summary.weighted_move,
            strongest=live_summary.strongest,
            weakest=live_summary.weakest,
            interval_summaries=interval_summaries,
        )
        errors = []
        if payload.holdings_loaded <= 0:
            freshness = "failed"
            failure_reason = f"No holdings were loaded for {symbol}."
            errors.append(make_market_data_error(source=payload.source_url or "ETF holdings source", reason=failure_reason, operation="etf_holdings", symbol=symbol))
        elif payload.quote_coverage < payload.holdings_loaded:
            freshness = "partial"
            missing = payload.holdings_loaded - payload.quote_coverage
            failure_reason = f"{missing} holding quote(s) were unavailable."
            errors.append(make_market_data_error(source="yfinance", reason=failure_reason, operation="etf_heatmap_quotes", symbol=symbol))
        else:
            freshness = "fresh"
            failure_reason = ""
        source_parts = [payload.issuer or payload.source_url or "ETF holdings source", "Yahoo Finance quotes"]
        return attach_market_data_result(
            payload,
            meta=make_market_data_meta(
                source=", ".join(part for part in source_parts if part),
                freshness=freshness,
                failure_reason=failure_reason,
            ),
            errors=errors,
        )

    def _resolve_sector(self, symbol: str, value: Any, sector_map: dict[str, str]) -> str:
        sector = self._normalize_sector(value)
        if sector:
            return sector
        lookup_symbol = symbol.replace("-", ".")
        return sector_map.get(symbol) or sector_map.get(lookup_symbol) or "Unclassified"

    @staticmethod
    def _normalize_sector(value: Any) -> str:
        text = str(value or "").strip()
        if text.casefold() in {"", "-", "--", "n/a", "na", "none", "null"}:
            return ""
        return text

    @staticmethod
    def _is_usable_symbol(value: Any) -> bool:
        text = str(value or "").upper().strip()
        if text in {"", "-", "--"}:
            return False
        return any(ch.isalpha() for ch in text)

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number

    def _fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, float]]:
        symbol_pairs: list[tuple[str, str]] = []
        seen = set()
        for symbol in symbols:
            text = str(symbol or "").upper().strip()
            if text and text not in seen:
                seen.add(text)
                symbol_pairs.append((text, self._yahoo_symbol(text)))
        if not symbol_pairs:
            return {}
        quotes: dict[str, dict[str, float]] = {}
        yahoo_symbols = sorted({yahoo_symbol for _symbol, yahoo_symbol in symbol_pairs})
        yahoo_to_originals: dict[str, list[str]] = {}
        for original, yahoo_symbol in symbol_pairs:
            yahoo_to_originals.setdefault(yahoo_symbol, []).append(original)
        try:
            with YF_LOCK:
                batch = yf.download(
                    yahoo_symbols,
                    period="2y",
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    auto_adjust=False,
                    threads=True,
                )
            yahoo_quotes = self._quotes_from_batch(batch, yahoo_symbols)
            for yahoo_symbol, payload in yahoo_quotes.items():
                for original in yahoo_to_originals.get(yahoo_symbol, []):
                    quotes[original] = payload
        except Exception as exc:
            logger.info("ETF heatmap batch quote fetch failed for %s symbols: %s", len(yahoo_symbols), exc)
        missing = [(original, yahoo_symbol) for original, yahoo_symbol in symbol_pairs if original not in quotes]
        if missing:
            with ThreadPoolExecutor(max_workers=min(10, max(1, len(missing)))) as executor:
                for symbol, payload in executor.map(lambda pair: self._fetch_quote_fallback(pair[0], pair[1]), missing):
                    if payload:
                        quotes[symbol] = payload
        return quotes

    def _quotes_from_batch(self, batch: Any, symbols: list[str]) -> dict[str, dict[str, float]]:
        quotes: dict[str, dict[str, float]] = {}
        if batch is None or getattr(batch, "empty", True):
            return quotes
        is_multi = isinstance(batch.columns, pd.MultiIndex)
        for symbol in symbols:
            try:
                if is_multi and symbol in batch.columns.get_level_values(0):
                    frame = batch[symbol]
                    close = frame["Close"].dropna() if "Close" in frame.columns else pd.Series(dtype=float)
                elif not is_multi and len(symbols) == 1 and "Close" in batch.columns:
                    close = batch["Close"].dropna()
                else:
                    close = pd.Series(dtype=float)
                payload = self._quote_from_close(close)
                if payload:
                    quotes[symbol] = payload
            except Exception:
                continue
        return quotes

    def _fetch_quote_fallback(self, symbol: str, yahoo_symbol: str) -> tuple[str, dict[str, float] | None]:
        try:
            with YF_LOCK:
                history = yf.Ticker(yahoo_symbol).history(period="2y", interval="1d")
            close = history.get("Close") if history is not None else None
            payload = self._quote_from_close(close.dropna() if close is not None else None)
            if payload:
                return symbol, payload
        except Exception:
            pass
        try:
            with YF_LOCK:
                fast_info = getattr(yf.Ticker(yahoo_symbol), "fast_info", {}) or {}
            price = self._positive_float(fast_info.get("lastPrice"))
            previous = self._positive_float(fast_info.get("previousClose"))
            if price is not None:
                change_pct = ((price - previous) / previous * 100.0) if previous else 0.0
                return symbol, {"price": price, "change_pct": change_pct, "changes": {"live": change_pct, "1d": change_pct}}
        except Exception:
            pass
        return symbol, None

    @staticmethod
    def _yahoo_symbol(symbol: str) -> str:
        return str(symbol or "").upper().strip().replace(".", "-")

    def _quote_from_close(self, close: Any) -> dict[str, float] | None:
        if close is None or getattr(close, "empty", True):
            return None
        try:
            series = close.dropna().astype(float)
            series.index = pd.to_datetime(series.index)
            series = series.sort_index()
            price = float(series.iloc[-1])
        except Exception:
            return None
        changes = self._changes_from_close(series)
        return {"price": price, "change_pct": changes.get("live"), "changes": changes}

    def _changes_from_close(self, close: Any) -> dict[str, float]:
        changes: dict[str, float] = {}
        if close is None or getattr(close, "empty", True):
            return changes
        try:
            series = close.dropna().astype(float).sort_index()
            latest = float(series.iloc[-1])
            latest_time = series.index[-1]
        except Exception:
            return changes
        if len(series) >= 2:
            previous = self._positive_float(series.iloc[-2])
            if previous:
                day_change = (latest - previous) / previous * 100.0
                changes["live"] = day_change
                changes["1d"] = day_change
        else:
            changes["live"] = 0.0
            changes["1d"] = 0.0
        try:
            changes["1w"] = self._return_since(series, latest, latest_time - pd.Timedelta(days=7))
            changes["1m"] = self._return_since(series, latest, latest_time - pd.DateOffset(months=1))
            changes["3m"] = self._return_since(series, latest, latest_time - pd.DateOffset(months=3))
            changes["1y"] = self._return_since(series, latest, latest_time - pd.DateOffset(years=1))
            ytd_start = pd.Timestamp(year=int(latest_time.year), month=1, day=1, tz=getattr(latest_time, "tz", None))
            before_year = series[series.index < ytd_start]
            if not before_year.empty:
                changes["ytd"] = self._return_from_base(latest, before_year.iloc[-1])
            else:
                changes["ytd"] = self._return_from_base(latest, series.iloc[0])
        except Exception:
            pass
        return {key: value for key, value in changes.items() if isinstance(value, (int, float)) and math.isfinite(float(value))}

    def _return_since(self, close: Any, latest: float, target: Any) -> float:
        eligible = close[close.index <= target]
        base = eligible.iloc[-1] if not eligible.empty else close.iloc[0]
        return self._return_from_base(latest, base)

    @staticmethod
    def _return_from_base(latest: float, base: Any) -> float:
        previous = float(base)
        return (float(latest) - previous) / previous * 100.0 if previous else 0.0

    def _interval_summary(self, holdings: list[EtfHeatmapHolding], interval: str) -> EtfHeatmapIntervalSummary:
        quoted = [
            holding
            for holding in holdings
            if isinstance((holding.changes or {}).get(interval), (int, float))
        ]
        return EtfHeatmapIntervalSummary(
            quote_coverage=len(quoted),
            weighted_move=self._weighted_move(holdings, interval),
            strongest=max(quoted, key=lambda item: float(item.changes[interval])) if quoted else None,
            weakest=min(quoted, key=lambda item: float(item.changes[interval])) if quoted else None,
        )

    @staticmethod
    def _weighted_move(holdings: list[EtfHeatmapHolding], interval: str = "live") -> float | None:
        numerator = 0.0
        denominator = 0.0
        for holding in holdings:
            change = (holding.changes or {}).get(interval, holding.change_pct if interval == "live" else None)
            if not isinstance(holding.weight, (int, float)) or not isinstance(change, (int, float)):
                continue
            numerator += float(holding.weight) * float(change)
            denominator += float(holding.weight)
        if denominator <= 0:
            return None
        return numerator / denominator

    def _load_sp500_sector_map(self) -> dict[str, str]:
        cached = self.__class__._SP500_SECTOR_CACHE
        now = time.time()
        if cached and now - cached[0] < self._SP500_SECTOR_TTL_SECONDS:
            return dict(cached[1])
        try:
            response = requests.get(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers={"User-Agent": "BudgetTerminal/1.0"},
                timeout=15,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", id="constituents")
            if table is None:
                return {}
            headers = [cell.get_text(" ", strip=True).casefold() for cell in table.find_all("th")]
            symbol_idx = headers.index("symbol")
            sector_idx = headers.index("gics sector")
            mapping: dict[str, str] = {}
            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if len(cells) <= max(symbol_idx, sector_idx):
                    continue
                symbol = cells[symbol_idx].upper().strip()
                sector = cells[sector_idx].strip()
                if not symbol or not sector:
                    continue
                mapping[symbol] = sector
                mapping[symbol.replace(".", "-")] = sector
            self.__class__._SP500_SECTOR_CACHE = (now, dict(mapping))
            return mapping
        except Exception as exc:
            logger.info("Unable to load S&P 500 sector fallback map: %s", exc)
            return {}
