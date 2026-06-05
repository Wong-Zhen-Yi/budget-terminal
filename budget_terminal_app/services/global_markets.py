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


def build_global_market_row(config: GlobalIndexConfig, close_series: Any) -> dict[str, Any]:
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
    }


class GlobalMarketsDataService:
    """Fetch global index history and calculate interval performance."""

    def __init__(self, indexes: tuple[GlobalIndexConfig, ...] = GLOBAL_MARKET_INDEXES) -> None:
        self.indexes = indexes

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
            rows.append(build_global_market_row(config, series))
        return {
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": "yfinance",
            "intervals": list(GLOBAL_INTERVALS),
            "rows": rows,
            "missing": missing,
        }
