from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - older Python / missing tzdata fallback
    ZoneInfo = None

from ..data_service.results import make_market_data_error
from ..dependencies import datetime, logger, pd, requests, yf
from ..paths import user_data_path


MASSIVE_BASE_URL = "https://api.massive.com"
MASSIVE_DOCS_STOCKS_URL = "https://massive.com/docs/rest/stocks/overview"
MASSIVE_STOCK_NEWS_URL = "https://massive.com/docs/rest/stocks/news"
MASSIVE_IPO_URL = "https://massive.com/docs/rest/stocks/corporate-actions/ipos"
MASSIVE_API_KEY_ENV_VARS = ("MASSIVE_API_KEY", "POLYGON_API_KEY")
MARKET_DATA_PROVIDER_MODE = "massive_free_safe"
MASSIVE_FREE_REQUESTS_PER_MINUTE = 5
MASSIVE_REQUEST_TIMEOUT_SECONDS = 12
_SECRET_FILE = user_data_path("secrets", "market_data_provider.json")
_GROUPED_CACHE_DIR = user_data_path("massive_cache", "grouped_daily")


class MassiveProviderError(RuntimeError):
    """Raised when a Massive endpoint is unavailable or denied."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        operation: str = "",
        symbol: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation
        self.symbol = symbol
        self.retryable = retryable


@dataclass
class ProviderFetchResult:
    data: Any = None
    source: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)
    used_provider: bool = False

    def has_data(self) -> bool:
        data = self.data
        if data is None:
            return False
        if isinstance(data, dict):
            return bool(data)
        return not bool(getattr(data, "empty", False))


class FreeTierRateLimiter:
    """Non-blocking local limiter for Massive Basic Free REST calls."""

    def __init__(self, max_requests: int = MASSIVE_FREE_REQUESTS_PER_MINUTE, window_seconds: float = 60.0) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = float(window_seconds)
        self._timestamps: list[float] = []

    def allow(self, now: float | None = None) -> tuple[bool, float]:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        self._timestamps = [stamp for stamp in self._timestamps if stamp > cutoff]
        if len(self._timestamps) >= self.max_requests:
            oldest = min(self._timestamps)
            retry_after = max(0.0, self.window_seconds - (current - oldest))
            return False, retry_after
        self._timestamps.append(current)
        return True, 0.0


def sanitize_api_text(text: Any, api_key: str = "") -> str:
    """Remove API-key material from text that may be logged or surfaced."""
    clean = str(text or "")
    key = str(api_key or "").strip()
    if key:
        clean = clean.replace(key, "HIDDEN")
    return clean


def load_market_data_provider_secret_key(secret_file: Path | None = None) -> str:
    path = Path(secret_file or _SECRET_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except Exception as exc:
        logger.warning("Unable to read market-data provider secret file: %s", exc)
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("massive_api_key") or "").strip()


def save_market_data_provider_secret_key(api_key: Any, secret_file: Path | None = None) -> None:
    key = str(api_key or "").strip()
    path = Path(secret_file or _SECRET_FILE)
    if not key:
        clear_market_data_provider_secret_key(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
    temp_path.write_text(json.dumps({"massive_api_key": key}, indent=2), encoding="utf-8")
    os.replace(str(temp_path), str(path))


def clear_market_data_provider_secret_key(secret_file: Path | None = None) -> None:
    path = Path(secret_file or _SECRET_FILE)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("Unable to clear market-data provider secret file: %s", exc)


def resolve_massive_api_key(
    settings: Any = None,
    *,
    secret_key: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return the active Massive/Polygon API key and its source label."""
    saved_key = str(load_market_data_provider_secret_key() if secret_key is None else secret_key or "").strip()
    if saved_key:
        return saved_key, "settings"
    environ = os.environ if env is None else env
    for name in MASSIVE_API_KEY_ENV_VARS:
        key = str(environ.get(name, "") or "").strip()
        if key:
            return key, "env"
    return "", "missing"


def describe_market_data_provider_key_status(settings: Any = None) -> dict[str, str]:
    key, source = resolve_massive_api_key(settings)
    if source == "settings":
        message = "Massive API key is saved locally."
    elif source == "env":
        message = "Massive API key is available from environment variables."
    else:
        message = "No Massive API key is configured."
    return {"api_key_source": source, "message": message, "has_key": "true" if bool(key) else "false"}


def _market_timezone() -> datetime.tzinfo | None:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except Exception:
            pass
    return None


def _date_to_iso(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value or "").strip()


def _previous_business_day(day: datetime.date) -> datetime.date:
    current = day - datetime.timedelta(days=1)
    while current.weekday() >= 5:
        current -= datetime.timedelta(days=1)
    return current


def latest_completed_us_business_day(now: datetime.datetime | None = None) -> datetime.date:
    tz = _market_timezone()
    current = now.astimezone(tz) if now is not None and tz is not None else (datetime.datetime.now(tz) if tz else datetime.datetime.now())
    day = current.date()
    if day.weekday() >= 5:
        while day.weekday() >= 5:
            day -= datetime.timedelta(days=1)
        return day
    if current.time() < datetime.time(18, 0):
        return _previous_business_day(day)
    return day


def parse_period_days(period: Any) -> float | None:
    text = str(period or "").strip().lower()
    if not text or text == "max":
        return None
    if text == "ytd":
        today = datetime.date.today()
        return max(1.0, float((today - datetime.date(today.year, 1, 1)).days + 1))
    suffix_days = {
        "d": 1.0,
        "wk": 7.0,
        "mo": 30.0,
        "y": 365.0,
    }
    for suffix, days in suffix_days.items():
        if text.endswith(suffix):
            try:
                return float(text[: -len(suffix)]) * days
            except (TypeError, ValueError):
                return None
    return None


def is_massive_stock_symbol(symbol: Any) -> bool:
    text = str(symbol or "").upper().strip()
    if not text or len(text) > 16:
        return False
    if any(marker in text for marker in ("^", "=", "/", "-USD", "-")):
        return False
    return all(ch.isalnum() or ch == "." for ch in text)


def is_massive_ohlcv_eligible(symbol: Any, period: Any, interval: Any) -> bool:
    if not is_massive_stock_symbol(symbol):
        return False
    interval_text = str(interval or "").strip().lower()
    if interval_text not in {"1d", "1wk", "1mo"}:
        return False
    days = parse_period_days(period)
    return days is not None and 0 < days <= 730


def _period_start_date(period: Any, end_date: datetime.date) -> datetime.date:
    days = parse_period_days(period)
    if days is None or days <= 0:
        days = 730.0
    return end_date - datetime.timedelta(days=int(math.ceil(days)))


def _interval_to_massive(interval: Any) -> tuple[int, str]:
    interval_text = str(interval or "").strip().lower()
    if interval_text == "1wk":
        return 1, "week"
    if interval_text == "1mo":
        return 1, "month"
    return 1, "day"


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class MassiveMarketDataProvider:
    """Free-safe Massive/Polygon facade with yfinance fallbacks."""

    def __init__(
        self,
        settings: Any = None,
        *,
        api_key: str | None = None,
        api_key_source: str | None = None,
        session: Any = None,
        yf_module: Any = None,
        rate_limiter: FreeTierRateLimiter | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.settings = settings if isinstance(settings, dict) else {}
        resolved_key, resolved_source = resolve_massive_api_key(settings, secret_key=api_key)
        self.api_key = resolved_key
        self.api_key_source = api_key_source or resolved_source
        self.session = session or requests
        self.yf = yf_module or yf
        self.rate_limiter = rate_limiter or _SHARED_RATE_LIMITER
        self.cache_dir = Path(cache_dir or _GROUPED_CACHE_DIR)

    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", True)) and bool(self.api_key)

    def _error(self, exc: Exception, *, source: str, operation: str, symbol: Any = "") -> dict[str, Any]:
        retryable = bool(getattr(exc, "retryable", False))
        return make_market_data_error(
            source=source,
            reason=sanitize_api_text(str(exc), self.api_key),
            operation=operation,
            symbol=str(symbol or ""),
            exception=exc,
            retryable=retryable,
        )

    def _request_json(self, path: str, *, params: dict[str, Any] | None = None, operation: str = "", symbol: Any = "") -> dict[str, Any]:
        if not self.enabled():
            raise MassiveProviderError("Massive provider is disabled or missing an API key.", operation=operation, symbol=str(symbol or ""))
        allowed, retry_after = self.rate_limiter.allow()
        if not allowed:
            raise MassiveProviderError(
                f"Massive free-tier local rate limit reached; retry after {retry_after:.0f}s.",
                operation=operation,
                symbol=str(symbol or ""),
                retryable=True,
            )
        query = dict(params or {})
        query["apiKey"] = self.api_key
        url = f"{MASSIVE_BASE_URL}{path}"
        try:
            response = self.session.get(url, params=query, timeout=MASSIVE_REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise MassiveProviderError(str(exc) or "Massive request failed.", operation=operation, symbol=str(symbol or ""), retryable=True) from exc
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code != 200:
            message = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("message") or payload.get("error") or "")
            except Exception:
                message = str(getattr(response, "text", "") or "")[:160]
            if not message:
                message = f"Massive HTTP {status_code}"
            raise MassiveProviderError(
                message,
                status_code=status_code,
                operation=operation,
                symbol=str(symbol or ""),
                retryable=status_code in {408, 425, 429, 500, 502, 503, 504},
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise MassiveProviderError("Massive returned invalid JSON.", operation=operation, symbol=str(symbol or "")) from exc
        if not isinstance(payload, dict):
            raise MassiveProviderError("Massive returned an unexpected response shape.", operation=operation, symbol=str(symbol or ""))
        return payload

    def _grouped_cache_path(self, date_value: datetime.date) -> Path:
        return self.cache_dir / f"stocks_grouped_{date_value.isoformat()}.json"

    def _load_grouped_summary_cache(self, date_value: datetime.date) -> list[dict[str, Any]] | None:
        path = self._grouped_cache_path(date_value)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Massive grouped cache read failed for %s: %s", date_value, exc)
            return None
        rows = payload.get("results") if isinstance(payload, dict) else None
        return list(rows) if isinstance(rows, list) else None

    def _save_grouped_summary_cache(self, date_value: datetime.date, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._grouped_cache_path(date_value).write_text(
                json.dumps({"date": date_value.isoformat(), "results": rows}),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Massive grouped cache write failed for %s: %s", date_value, exc)

    def _fetch_grouped_summary(self, date_value: datetime.date) -> list[dict[str, Any]]:
        cached = self._load_grouped_summary_cache(date_value)
        if cached is not None:
            return cached
        payload = self._request_json(
            f"/v2/aggs/grouped/locale/us/market/stocks/{date_value.isoformat()}",
            params={"adjusted": "false", "include_otc": "false"},
            operation="massive_grouped_daily",
        )
        rows = payload.get("results")
        if not isinstance(rows, list) or not rows:
            raise MassiveProviderError(f"Massive returned no grouped daily stock data for {date_value}.", operation="massive_grouped_daily")
        clean_rows = [row for row in rows if isinstance(row, dict)]
        self._save_grouped_summary_cache(date_value, clean_rows)
        return clean_rows

    def _grouped_map(self, date_value: datetime.date) -> dict[str, dict[str, Any]]:
        rows = self._fetch_grouped_summary(date_value)
        mapped = {}
        for row in rows:
            symbol = str(row.get("T") or "").upper().strip()
            if symbol:
                mapped[symbol] = row
        return mapped

    def get_stock_prices(self, symbols: Any) -> ProviderFetchResult:
        requested = []
        seen = set()
        for value in list(symbols or []):
            symbol = str(value or "").upper().strip()
            if symbol and symbol not in seen:
                requested.append(symbol)
                seen.add(symbol)
        if not requested:
            return ProviderFetchResult(data={}, source="input")

        errors: list[dict[str, Any]] = []
        prices: dict[str, dict[str, float]] = {}
        source_parts: list[str] = []
        eligible = [symbol for symbol in requested if is_massive_stock_symbol(symbol)]
        if self.enabled() and eligible:
            try:
                latest_date = latest_completed_us_business_day()
                previous_date = _previous_business_day(latest_date)
                latest = self._grouped_map(latest_date)
                previous = self._grouped_map(previous_date)
                for symbol in eligible:
                    row = latest.get(symbol)
                    close = _finite_float(row.get("c") if row else None)
                    if close is None:
                        continue
                    prev_close = _finite_float((previous.get(symbol) or {}).get("c"))
                    abs_change = close - prev_close if prev_close is not None else 0.0
                    change_pct = (abs_change / prev_close * 100.0) if prev_close else 0.0
                    prices[symbol] = {"price": close, "change": change_pct, "abs_change": abs_change}
                if prices:
                    source_parts.append("Massive EOD")
            except Exception as exc:
                errors.append(self._error(exc, source="Massive EOD", operation="stock_prices"))

        missing = [symbol for symbol in requested if symbol not in prices]
        if missing:
            fallback = self._fetch_yfinance_prices(missing)
            if fallback.data:
                prices.update(fallback.data)
            errors.extend(fallback.errors)
            if fallback.data:
                source_parts.append("yfinance fallback")
        return ProviderFetchResult(
            data=prices,
            source=", ".join(dict.fromkeys(source_parts)) or "yfinance fallback",
            errors=errors,
            used_provider=any(part.startswith("Massive") for part in source_parts),
        )

    def _fetch_yfinance_prices(self, symbols: list[str]) -> ProviderFetchResult:
        try:
            raw = self.yf.download(
                symbols,
                period="5d",
                interval="1d",
                group_by="ticker",
                progress=False,
                prepost=True,
            )
        except Exception as exc:
            return ProviderFetchResult(
                data={},
                source="yfinance fallback",
                errors=[make_market_data_error(source="yfinance fallback", reason=str(exc), operation="stock_prices", exception=exc)],
            )
        prices = {}
        for symbol in symbols:
            close = self._extract_close_series(raw, symbols, symbol)
            payload = self._price_payload_from_close(close)
            if payload is not None:
                prices[symbol] = payload
        return ProviderFetchResult(data=prices, source="yfinance fallback")

    def _extract_close_series(self, frame: Any, symbols: list[str], symbol: str) -> Any:
        if frame is None or getattr(frame, "empty", True):
            return None
        if isinstance(frame.columns, pd.MultiIndex):
            level_zero = [str(value).upper().strip() for value in frame.columns.get_level_values(0)]
            level_one = [str(value).upper().strip() for value in frame.columns.get_level_values(1)]
            symbol_text = str(symbol or "").upper().strip()
            if symbol_text in level_zero:
                symbol_frame = frame.iloc[:, [idx for idx, value in enumerate(level_zero) if value == symbol_text]]
                symbol_frame.columns = symbol_frame.columns.get_level_values(1)
            elif symbol_text in level_one:
                symbol_frame = frame.iloc[:, [idx for idx, value in enumerate(level_one) if value == symbol_text]]
                symbol_frame.columns = symbol_frame.columns.get_level_values(0)
            else:
                return None
            return pd.to_numeric(symbol_frame.get("Close"), errors="coerce").dropna() if "Close" in symbol_frame.columns else None
        if symbol in frame.columns:
            return pd.to_numeric(frame[symbol], errors="coerce").dropna()
        if len(symbols) == 1 and "Close" in frame.columns:
            return pd.to_numeric(frame["Close"], errors="coerce").dropna()
        return None

    def _price_payload_from_close(self, close: Any) -> dict[str, float] | None:
        if close is None or getattr(close, "empty", True):
            return None
        current = _finite_float(close.iloc[-1])
        if current is None:
            return None
        if len(close) >= 2:
            previous = _finite_float(close.iloc[-2]) or current
            abs_change = current - previous
            change_pct = abs_change / previous * 100.0 if previous else 0.0
            return {"price": current, "change": change_pct, "abs_change": abs_change}
        return {"price": current, "change": 0.0, "abs_change": 0.0}

    def get_ohlcv(
        self,
        symbol: Any,
        *,
        period: Any,
        interval: Any,
        auto_adjust: bool = False,
    ) -> ProviderFetchResult:
        symbol_text = str(symbol or "").upper().strip()
        errors: list[dict[str, Any]] = []
        if self.enabled() and is_massive_ohlcv_eligible(symbol_text, period, interval):
            try:
                end_date = latest_completed_us_business_day()
                start_date = _period_start_date(period, end_date)
                multiplier, timespan = _interval_to_massive(interval)
                payload = self._request_json(
                    f"/v2/aggs/ticker/{symbol_text}/range/{multiplier}/{timespan}/{start_date.isoformat()}/{end_date.isoformat()}",
                    params={"adjusted": "true" if auto_adjust else "false", "sort": "asc", "limit": 50000},
                    operation="ohlcv",
                    symbol=symbol_text,
                )
                frame = self._massive_aggs_to_frame(payload.get("results"))
                if frame is not None and not frame.empty:
                    return ProviderFetchResult(data=frame, source="Massive EOD", used_provider=True)
                raise MassiveProviderError(f"Massive returned no OHLCV data for {symbol_text}.", operation="ohlcv", symbol=symbol_text)
            except Exception as exc:
                errors.append(self._error(exc, source="Massive EOD", operation="ohlcv", symbol=symbol_text))
        fallback = self._fetch_yfinance_ohlcv(symbol_text, period=period, interval=interval, auto_adjust=auto_adjust)
        fallback.errors = [*errors, *fallback.errors]
        return fallback

    def _massive_aggs_to_frame(self, rows: Any) -> Any:
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame()
        records = []
        index = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = _finite_float(row.get("t"))
            open_price = _finite_float(row.get("o"))
            high = _finite_float(row.get("h"))
            low = _finite_float(row.get("l"))
            close = _finite_float(row.get("c"))
            if timestamp is None or open_price is None or high is None or low is None or close is None:
                continue
            index.append(pd.to_datetime(int(timestamp), unit="ms").tz_localize(None))
            records.append(
                {
                    "Open": open_price,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Volume": _finite_float(row.get("v")) or 0.0,
                }
            )
        if not records:
            return pd.DataFrame()
        frame = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="Date")).sort_index()
        return frame[~frame.index.duplicated(keep="last")]

    def _fetch_yfinance_ohlcv(self, symbol: str, *, period: Any, interval: Any, auto_adjust: bool) -> ProviderFetchResult:
        try:
            frame = self.yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=auto_adjust)
            if frame is None or getattr(frame, "empty", True):
                ticker_obj = self.yf.Ticker(symbol)
                frame = ticker_obj.history(period=period, interval=interval, auto_adjust=auto_adjust)
            if frame is None or getattr(frame, "empty", True):
                raise ValueError(f"No chart data returned for {symbol}.")
            return ProviderFetchResult(data=frame, source="yfinance fallback")
        except Exception as exc:
            return ProviderFetchResult(
                data=pd.DataFrame(),
                source="yfinance fallback",
                errors=[make_market_data_error(source="yfinance fallback", reason=str(exc), operation="ohlcv", symbol=symbol, exception=exc)],
            )

    def get_company_overview(self, symbol: Any) -> ProviderFetchResult:
        symbol_text = str(symbol or "").upper().strip()
        if not self.enabled() or not is_massive_stock_symbol(symbol_text):
            return ProviderFetchResult(data={}, source="Massive reference")
        try:
            payload = self._request_json(f"/v3/reference/tickers/{symbol_text}", operation="company_overview", symbol=symbol_text)
            result = payload.get("results")
            if not isinstance(result, dict) or not result:
                raise MassiveProviderError(f"Massive returned no company overview for {symbol_text}.", operation="company_overview", symbol=symbol_text)
            info = self._normalize_company_overview(symbol_text, result)
            return ProviderFetchResult(data=info, source="Massive reference", used_provider=bool(info))
        except Exception as exc:
            return ProviderFetchResult(data={}, source="Massive reference", errors=[self._error(exc, source="Massive reference", operation="company_overview", symbol=symbol_text)])

    def _normalize_company_overview(self, symbol: str, result: dict[str, Any]) -> dict[str, Any]:
        name = str(result.get("name") or symbol).strip()
        market_cap = _finite_float(result.get("market_cap"))
        shares = _finite_float(result.get("share_class_shares_outstanding") or result.get("weighted_shares_outstanding"))
        description = str(result.get("description") or "").strip()
        sic_description = str(result.get("sic_description") or "").strip()
        payload = {
            "symbol": symbol,
            "shortName": name,
            "longName": name,
            "exchange": str(result.get("primary_exchange") or "").strip(),
            "currency": str(result.get("currency_name") or "USD").upper().strip(),
            "marketCap": market_cap,
            "sharesOutstanding": shares,
            "sector": sic_description,
            "industry": sic_description,
            "website": str(result.get("homepage_url") or "").strip(),
            "longBusinessSummary": description,
            "description": description,
        }
        return {key: value for key, value in payload.items() if value not in (None, "")}

    def get_stock_news(self, symbol: Any, *, limit: int = 5, category: str = "portfolio") -> ProviderFetchResult:
        symbol_text = str(symbol or "").upper().strip()
        if not self.enabled() or not is_massive_stock_symbol(symbol_text):
            return ProviderFetchResult(data=[], source="Massive news")
        try:
            payload = self._request_json(
                "/v2/reference/news",
                params={"ticker": symbol_text, "limit": max(1, min(int(limit or 5), 50)), "order": "desc", "sort": "published_utc"},
                operation="stock_news",
                symbol=symbol_text,
            )
            rows = payload.get("results")
            if not isinstance(rows, list) or not rows:
                raise MassiveProviderError(f"Massive returned no news for {symbol_text}.", operation="stock_news", symbol=symbol_text)
            articles = [article for article in (self._normalize_news_item(item, symbol_text, category) for item in rows) if article]
            return ProviderFetchResult(data=articles, source="Massive news", used_provider=bool(articles))
        except Exception as exc:
            return ProviderFetchResult(data=[], source="Massive news", errors=[self._error(exc, source="Massive news", operation="stock_news", symbol=symbol_text)])

    def _normalize_news_item(self, item: Any, symbol: str, category: str) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        url = str(item.get("article_url") or item.get("url") or "").strip()
        if not title and not url:
            return None
        publisher = item.get("publisher") if isinstance(item.get("publisher"), dict) else {}
        published = str(item.get("published_utc") or "").strip()
        ts = 0.0
        time_text = "--:--"
        if published:
            try:
                parsed = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
                ts = parsed.timestamp()
                time_text = parsed.strftime("%H:%M")
            except Exception:
                time_text = published[:10]
        tickers = item.get("tickers")
        if isinstance(tickers, list) and tickers:
            ticker_text = ", ".join(str(ticker or "").upper().strip() for ticker in tickers[:3] if str(ticker or "").strip())
        else:
            ticker_text = symbol
        return {
            "ticker": ticker_text or symbol,
            "title": title or "N/A",
            "source": str(publisher.get("name") or item.get("author") or "Massive").strip() or "Massive",
            "time": time_text,
            "url": url,
            "category": category,
            "_ts": ts,
        }

    def get_ipos(self, start_date: Any, end_date: Any, *, completed: bool = False) -> ProviderFetchResult:
        start_text = _date_to_iso(start_date)
        end_text = _date_to_iso(end_date)
        if not self.enabled():
            return ProviderFetchResult(data=[], source="Massive IPOs")
        try:
            payload = self._request_json(
                "/vX/reference/ipos",
                params={
                    "listing_date.gte": start_text,
                    "listing_date.lte": end_text,
                    "limit": 1000,
                    "sort": "listing_date",
                    "order": "desc" if completed else "asc",
                },
                operation="ipos",
            )
            rows = payload.get("results")
            if not isinstance(rows, list) or not rows:
                raise MassiveProviderError("Massive returned no IPO rows.", operation="ipos")
            normalized = [row for row in (self._normalize_ipo_item(item, completed=completed) for item in rows) if row]
            return ProviderFetchResult(data=normalized, source="Massive IPOs", used_provider=bool(normalized))
        except Exception as exc:
            return ProviderFetchResult(data=[], source="Massive IPOs", errors=[self._error(exc, source="Massive IPOs", operation="ipos")])

    def _normalize_ipo_item(self, item: Any, *, completed: bool) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        date_text = str(
            item.get("listing_date")
            or item.get("ipo_date")
            or item.get("announced_date")
            or ""
        ).strip()[:10]
        if not date_text:
            return None
        try:
            ipo_date = datetime.date.fromisoformat(date_text)
        except ValueError:
            return None
        symbol = str(item.get("ticker") or item.get("symbol") or item.get("us_code") or "--").upper().strip() or "--"
        company = str(item.get("issuer_name") or item.get("company_name") or item.get("name") or "--").strip() or "--"
        price_low = _finite_float(item.get("expected_price_low") or item.get("price_low") or item.get("low_price"))
        price_high = _finite_float(item.get("expected_price_high") or item.get("price_high") or item.get("high_price"))
        ipo_price = _finite_float(item.get("ipo_price") or item.get("issue_price") or item.get("final_issue_price"))
        price_text = self._format_ipo_price(price_low, price_high, ipo_price)
        base = {
            "date": ipo_date.isoformat(),
            "date_display": ipo_date.strftime("%b %d, %Y"),
            "symbol": symbol,
            "company": company,
        }
        if completed:
            return {
                **base,
                "ipo_price": price_text,
                "current_price": "--",
                "return": "--",
            }
        return {
            **base,
            "exchange": str(item.get("exchange") or item.get("primary_exchange") or "--").strip() or "--",
            "price_range": price_text,
            "shares_offered": self._format_quantity(item.get("shares_offered") or item.get("shares")),
            "deal_size": self._format_money(item.get("offer_amount") or item.get("total_offer_size") or item.get("deal_size")),
            "market_cap": self._format_money(item.get("market_cap") or item.get("valuation")),
            "revenue": "--",
        }

    def _format_ipo_price(self, low: float | None, high: float | None, price: float | None) -> str:
        if low is not None and high is not None and low != high:
            return f"${low:,.2f} - ${high:,.2f}"
        value = price if price is not None else low if low is not None else high
        return f"${value:,.2f}" if value is not None else "--"

    def _format_quantity(self, value: Any) -> str:
        number = _finite_float(value)
        return f"{number:,.0f}" if number is not None else "--"

    def _format_money(self, value: Any) -> str:
        number = _finite_float(value)
        if number is None:
            return "--"
        if abs(number) >= 1_000_000_000:
            return f"${number / 1_000_000_000:.2f}B"
        if abs(number) >= 1_000_000:
            return f"${number / 1_000_000:.2f}M"
        return f"${number:,.0f}"


_SHARED_RATE_LIMITER = FreeTierRateLimiter()
_SHARED_PROVIDER: MassiveMarketDataProvider | None = None


def get_market_data_provider(settings: Any = None, *, refresh: bool = False) -> MassiveMarketDataProvider:
    """Return the process-wide Massive/yfinance provider facade."""
    global _SHARED_PROVIDER
    if _SHARED_PROVIDER is None or refresh or settings is not None:
        if settings is None:
            try:
                from ..persistence import load_market_data_provider_settings

                settings = load_market_data_provider_settings()
            except Exception:
                settings = {"enabled": True, "mode": MARKET_DATA_PROVIDER_MODE}
        _SHARED_PROVIDER = MassiveMarketDataProvider(settings=settings, rate_limiter=_SHARED_RATE_LIMITER)
    return _SHARED_PROVIDER
