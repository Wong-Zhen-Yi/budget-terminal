from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from ..dependencies import YF_LOCK, logger, math, pd, yf


GLOBAL_INTERVALS = ("1D", "5D", "30D", "YTD", "1Y", "5Y")


@dataclass(frozen=True)
class GlobalIndexConfig:
    region: str
    country: str
    name: str
    short_name: str
    symbol: str
    lat: float
    lon: float
    label_dx: int = 0
    label_dy: int = 0


GLOBAL_MARKET_INDEXES: tuple[GlobalIndexConfig, ...] = (
    GlobalIndexConfig("North America", "USA", "S&P 500", "S&P 500", "^GSPC", 39.5, -98.4, -94, -42),
    GlobalIndexConfig("North America", "Canada", "S&P/TSX Composite Index", "TSX", "^GSPTSE", 56.1, -106.3, -102, -18),
    GlobalIndexConfig("Europe", "UK", "FTSE 100", "FTSE", "^FTSE", 55.4, -3.4, -86, -44),
    GlobalIndexConfig("Europe", "Germany", "DAX 40", "DAX", "^GDAXI", 51.2, 10.5, 32, -44),
    GlobalIndexConfig("Europe", "France", "CAC 40", "CAC", "^FCHI", 46.2, 2.2, -92, 8),
    GlobalIndexConfig("Europe", "Italy", "FTSE MIB", "MIB", "FTSEMIB.MI", 42.8, 12.5, 32, 8),
    GlobalIndexConfig("Europe", "Spain", "IBEX 35", "IBEX", "^IBEX", 40.5, -3.7, -92, 34),
    GlobalIndexConfig("Asia-Pacific", "Japan", "Nikkei 225", "Nikkei", "^N225", 36.2, 138.3, 38, -42),
    GlobalIndexConfig("Asia-Pacific", "Hong Kong", "Hang Seng Index (HSI)", "HSI", "^HSI", 22.3, 114.2, 30, 28),
    GlobalIndexConfig("Asia-Pacific", "China", "CSI 300", "CSI 300", "000300.SS", 39.9, 116.4, 36, -8),
    GlobalIndexConfig("Asia-Pacific", "India", "Nifty 50", "Nifty", "^NSEI", 28.6, 77.2, -110, -18),
    GlobalIndexConfig("Asia-Pacific", "South Korea", "KOSPI", "KOSPI", "^KS11", 36.5, 127.9, 36, 20),
    GlobalIndexConfig("Asia-Pacific", "Singapore", "Straits Times Index (STI)", "STI", "^STI", 1.35, 103.8, 36, 52),
    GlobalIndexConfig("Asia-Pacific", "Australia", "S&P/ASX 200", "ASX 200", "^AXJO", -25.3, 133.8, 36, 18),
    GlobalIndexConfig("Latin America", "Brazil", "Bovespa (IBOV)", "IBOV", "^BVSP", -14.2, -51.9, 30, 22),
    GlobalIndexConfig("Latin America", "Mexico", "S&P/BMV IPC", "IPC", "^MXX", 23.6, -102.6, -100, 18),
)


def _normalize_symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def _coerce_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return ""
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _coerce_epoch_seconds(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    if isinstance(value, _dt.datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=_dt.timezone.utc)
        return int(parsed.timestamp())
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if math.isfinite(number) and number > 0:
        return int(number)
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return int(pd.Timestamp(parsed).timestamp())


def _datetime_from_epoch(epoch_seconds: Any, tzinfo: Any) -> _dt.datetime | None:
    epoch = _coerce_epoch_seconds(epoch_seconds)
    if epoch is None:
        return None
    try:
        return _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc).astimezone(tzinfo)
    except Exception:
        return None


def _format_market_time(target: _dt.datetime, now: _dt.datetime, *, use_12h: bool = False) -> str:
    if target.date() == now.date():
        return target.strftime("%I:%M %p" if use_12h else "%H:%M")
    return target.strftime("%b %d, %I:%M %p" if use_12h else "%b %d, %H:%M")


def _last_tick_epoch_from_frame(frame: Any, exchange_timezone: Any = None) -> int | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        last_index = frame.index[-1]
        timestamp = pd.Timestamp(last_index)
    except Exception:
        return None
    try:
        if timestamp.tzinfo is None:
            zone_name = str(exchange_timezone or "").strip()
            timestamp = timestamp.tz_localize(zone_name or "UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return int(timestamp.timestamp())
    except Exception:
        return None


def build_market_timing_payload(symbol: Any, metadata: Any = None, intraday_frame: Any = None) -> dict[str, Any]:
    """Normalize yfinance timing metadata into a small JSON-safe payload."""
    meta = metadata if isinstance(metadata, dict) else {}
    period = meta.get("currentTradingPeriod") if isinstance(meta.get("currentTradingPeriod"), dict) else {}
    regular = period.get("regular") if isinstance(period.get("regular"), dict) else {}
    exchange_timezone = str(meta.get("exchangeTimezoneName") or "").strip()
    regular_market_time = _coerce_epoch_seconds(meta.get("regularMarketTime"))
    last_tick_time = _last_tick_epoch_from_frame(intraday_frame, exchange_timezone) or regular_market_time
    payload = {
        "symbol": _normalize_symbol(symbol),
        "exchange_name": str(meta.get("fullExchangeName") or meta.get("exchangeName") or "").strip(),
        "exchange_timezone": exchange_timezone,
        "regular_start": _coerce_epoch_seconds(regular.get("start")),
        "regular_end": _coerce_epoch_seconds(regular.get("end")),
        "regular_market_time": regular_market_time,
        "last_tick_time": last_tick_time,
    }
    if not any(payload.get(key) for key in ("regular_start", "regular_end", "regular_market_time", "last_tick_time")):
        payload["source"] = "unavailable"
    else:
        payload["source"] = "yfinance metadata"
    return payload


def format_global_market_timing(
    market_timing: Any,
    clock_tzinfo: Any,
    *,
    now: _dt.datetime | None = None,
    use_12h: bool = False,
) -> dict[str, Any]:
    """Return a display-ready market session status in the selected clock timezone."""
    timing = market_timing if isinstance(market_timing, dict) else {}
    tzinfo = clock_tzinfo or _dt.datetime.now().astimezone().tzinfo or _dt.timezone.utc
    current = now or _dt.datetime.now(tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tzinfo)
    else:
        current = current.astimezone(tzinfo)
    start_dt = _datetime_from_epoch(timing.get("regular_start"), tzinfo)
    end_dt = _datetime_from_epoch(timing.get("regular_end"), tzinfo)
    last_tick_dt = _datetime_from_epoch(timing.get("last_tick_time") or timing.get("regular_market_time"), tzinfo)
    exchange_timezone = str(timing.get("exchange_timezone") or "").strip()
    clock_timezone = current.tzname() or str(tzinfo)
    base = {
        "state": "unknown",
        "market": "Unknown",
        "session": "Timing unavailable",
        "exchange_timezone": exchange_timezone or "--",
        "clock_timezone": clock_timezone,
    }
    if start_dt is not None and end_dt is not None:
        if start_dt <= current < end_dt:
            base.update(
                {
                    "state": "open",
                    "market": "Open",
                    "session": f"Open until {_format_market_time(end_dt, current, use_12h=use_12h)}",
                    "regular_start": start_dt.isoformat(),
                    "regular_end": end_dt.isoformat(),
                }
            )
        elif current < start_dt:
            base.update(
                {
                    "state": "closed",
                    "market": "Closed",
                    "session": f"Closed, opens {_format_market_time(start_dt, current, use_12h=use_12h)}",
                    "regular_start": start_dt.isoformat(),
                    "regular_end": end_dt.isoformat(),
                }
            )
        else:
            base.update(
                {
                    "state": "closed",
                    "market": "Closed",
                    "session": f"Closed since {_format_market_time(end_dt, current, use_12h=use_12h)}",
                    "regular_start": start_dt.isoformat(),
                    "regular_end": end_dt.isoformat(),
                }
            )
    elif last_tick_dt is not None:
        base.update(
            {
                "session": f"Unknown, last tick {_format_market_time(last_tick_dt, current, use_12h=use_12h)}",
                "last_tick_time": last_tick_dt.isoformat(),
            }
        )
    return base


def _extract_close_series(symbol: Any, raw_frame: Any) -> Any:
    """Extract a clean adjusted-close-or-close series for one yfinance symbol."""
    symbol_text = _normalize_symbol(symbol)
    if raw_frame is None or getattr(raw_frame, "empty", True):
        return pd.Series(dtype=float)
    frame = raw_frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = [str(value).upper().strip() for value in frame.columns.get_level_values(0)]
        level1 = [str(value).upper().strip() for value in frame.columns.get_level_values(1)]
        if symbol_text in level0:
            frame = frame.loc[:, [value == symbol_text for value in level0]].copy()
            frame.columns = frame.columns.get_level_values(1)
        elif symbol_text in level1:
            frame = frame.loc[:, [value == symbol_text for value in level1]].copy()
            frame.columns = frame.columns.get_level_values(0)
    for column in ("Adj Close", "Close", "adj close", "close"):
        if column in frame.columns:
            series = pd.Series(frame[column]).copy()
            break
    else:
        return pd.Series(dtype=float)
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return pd.Series(dtype=float)
    series.index = pd.DatetimeIndex(pd.to_datetime(series.index))
    if getattr(series.index, "tz", None) is not None:
        series.index = series.index.tz_localize(None)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series[series > 0.0]


def _interval_target(end_date: Any, interval_label: Any) -> Any:
    label = str(interval_label or "").upper().strip()
    end_ts = pd.Timestamp(end_date).normalize()
    if label == "1D":
        return end_ts - pd.Timedelta(days=1)
    if label == "5D":
        return end_ts - pd.Timedelta(days=5)
    if label == "30D":
        return end_ts - pd.Timedelta(days=30)
    if label == "1Y":
        return end_ts - pd.DateOffset(years=1)
    if label == "5Y":
        return end_ts - pd.DateOffset(years=5)
    if label == "YTD":
        return pd.Timestamp(year=end_ts.year, month=1, day=1)
    return end_ts - pd.Timedelta(days=1)


def calculate_interval_performance(close_series: Any, interval_label: Any) -> dict[str, Any]:
    """Calculate one interval return from the nearest usable trading close."""
    label = str(interval_label or "").upper().strip()
    if label not in GLOBAL_INTERVALS:
        label = "1D"
    series = pd.Series(close_series).dropna().sort_index()
    if len(series) < 2:
        return {"available": False, "interval": label, "reason": "Not enough price history."}
    end_date = pd.Timestamp(series.index[-1])
    end_close = float(series.iloc[-1])
    target = _interval_target(end_date, label)
    if label == "YTD":
        candidates = series[series.index >= target]
    else:
        candidates = series[series.index <= target]
    if candidates.empty:
        return {"available": False, "interval": label, "end_date": _coerce_date(end_date), "end_close": end_close, "reason": "No start close in range."}
    start_date = pd.Timestamp(candidates.index[0] if label == "YTD" else candidates.index[-1])
    if start_date == end_date:
        return {"available": False, "interval": label, "end_date": _coerce_date(end_date), "end_close": end_close, "reason": "No earlier start close."}
    start_close = float(candidates.iloc[0] if label == "YTD" else candidates.iloc[-1])
    if start_close <= 0.0 or not math.isfinite(start_close) or not math.isfinite(end_close):
        return {"available": False, "interval": label, "end_date": _coerce_date(end_date), "end_close": end_close, "reason": "Invalid close values."}
    return {
        "available": True,
        "interval": label,
        "start_date": _coerce_date(start_date),
        "end_date": _coerce_date(end_date),
        "start_close": start_close,
        "end_close": end_close,
        "change_pct": (end_close / start_close - 1.0) * 100.0,
    }


def build_global_market_row(config: GlobalIndexConfig, close_series: Any, market_timing: Any = None) -> dict[str, Any]:
    series = pd.Series(close_series).dropna().sort_index()
    intervals = {label: calculate_interval_performance(series, label) for label in GLOBAL_INTERVALS}
    last_close = None
    last_date = ""
    if not series.empty:
        last_close = float(series.iloc[-1])
        last_date = _coerce_date(series.index[-1])
    return {
        "region": config.region,
        "country": config.country,
        "index": config.name,
        "short_name": config.short_name,
        "symbol": config.symbol,
        "lat": config.lat,
        "lon": config.lon,
        "label_dx": config.label_dx,
        "label_dy": config.label_dy,
        "last_close": last_close,
        "last_date": last_date,
        "intervals": intervals,
        "market_timing": dict(market_timing or {}),
    }


class GlobalMarketsDataService:
    """Fetch global index history and calculate interval performance."""

    def __init__(self, indexes: tuple[GlobalIndexConfig, ...] = GLOBAL_MARKET_INDEXES) -> None:
        self.indexes = indexes

    def _fetch_market_timing(self, symbol: Any) -> dict[str, Any]:
        symbol_text = _normalize_symbol(symbol)
        intraday = pd.DataFrame()
        metadata: dict[str, Any] = {}
        try:
            with YF_LOCK:
                ticker = yf.Ticker(symbol_text)
                intraday = ticker.history(period="1d", interval="1m", prepost=True, auto_adjust=False)
                try:
                    metadata = ticker.get_history_metadata() or {}
                except Exception:
                    metadata = {}
        except Exception as exc:
            logger.warning("Global market timing fetch failed for %s: %s", symbol_text, exc)
        return build_market_timing_payload(symbol_text, metadata, intraday)

    def fetch(self) -> dict[str, Any]:
        symbols = [item.symbol for item in self.indexes]
        try:
            with YF_LOCK:
                raw = yf.download(
                    symbols,
                    period="6y",
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    auto_adjust=False,
                    threads=True,
                )
        except Exception as exc:
            logger.error("Global market index fetch failed: %s", exc)
            raw = pd.DataFrame()
        rows = []
        missing = []
        for config in self.indexes:
            series = _extract_close_series(config.symbol, raw)
            if series.empty:
                missing.append(config.symbol)
            rows.append(build_global_market_row(config, series, self._fetch_market_timing(config.symbol)))
        return {
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": "yfinance",
            "intervals": list(GLOBAL_INTERVALS),
            "rows": rows,
            "missing": missing,
        }
