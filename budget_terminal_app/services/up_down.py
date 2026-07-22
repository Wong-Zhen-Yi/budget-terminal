from __future__ import annotations

from typing import Any

from ..dependencies import YF_LOCK, datetime, logger, math, pd, yf


UP_DOWN_INTERVALS: tuple[tuple[str, str], ...] = (
    ("1d", "1D"),
    ("5d", "5D"),
    ("30d", "30D"),
    ("ytd", "YTD"),
    ("1y", "1Y"),
)
UP_DOWN_INTERVAL_LABELS = {key: label for key, label in UP_DOWN_INTERVALS}


def normalize_up_down_symbols(values: Any) -> list[str]:
    """Return unique uppercase stock symbols from a string or iterable."""
    if isinstance(values, str):
        raw_values = values.replace(",", " ").replace(";", " ").split()
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = []
    symbols: list[str] = []
    seen = set()
    for value in raw_values:
        symbol = str(value or "").upper().strip()
        if not symbol or symbol == "CASH" or symbol in seen:
            continue
        if not any(ch.isalpha() for ch in symbol):
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


def interval_fetch_config(interval_key: Any, today: datetime.date | None = None) -> dict[str, Any]:
    """Return yfinance fetch kwargs for one Up/Down interval."""
    key = str(interval_key or "1d").strip().lower()
    today = today or datetime.date.today()
    if key in {"1d", "5d"}:
        return {"period": "10d", "interval": "1d"}
    if key == "30d":
        return {"period": "2mo", "interval": "1d"}
    if key == "ytd":
        return {"start": (today.replace(month=1, day=1) - datetime.timedelta(days=10)).isoformat(), "interval": "1d"}
    if key == "1y":
        return {"period": "13mo", "interval": "1d"}
    return {"period": "5d", "interval": "1d"}


def calculate_up_down_row(
    symbol: str,
    close: Any,
    interval_key: Any,
    *,
    name: str = "",
) -> dict[str, Any] | None:
    """Calculate days-up/days-down metrics from one daily close series."""
    series = _clean_close_series(close)
    if series is None or len(series) < 2:
        return None
    key = str(interval_key or "1d").strip().lower()
    changes = series.diff().dropna()
    returns = series.pct_change().dropna() * 100.0
    selected_changes = _select_interval_series(changes, key, latest_time=series.index[-1])
    selected_returns = returns.reindex(selected_changes.index).dropna()
    if selected_changes.empty:
        return None
    trading_days = int(len(selected_changes))
    days_up = int((selected_changes > 0).sum())
    days_down = int((selected_changes < 0).sum())
    interval_return = _interval_return(series, selected_changes.index)
    try:
        last_close = float(series.iloc[-1])
    except Exception:
        last_close = None
    return {
        "ticker": str(symbol or "").upper().strip(),
        "name": str(name or "").strip(),
        "last_close": last_close if isinstance(last_close, (int, float)) and math.isfinite(float(last_close)) else None,
        "interval_return": interval_return,
        "trading_days": trading_days,
        "days_up": days_up,
        "days_down": days_down,
        "flat_days": max(0, trading_days - days_up - days_down),
        "positive_return_days": int((selected_returns > 0).sum()) if not selected_returns.empty else days_up,
        "negative_return_days": int((selected_returns < 0).sum()) if not selected_returns.empty else days_down,
    }


def sort_up_down_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows by the Up/Down page default ranking."""
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("days_up") or 0),
            int(row.get("days_down") or 0),
            str(row.get("ticker") or ""),
        ),
    )


class UpDownDataService:
    """Fetch daily closes and calculate Up/Down page rows."""

    def fetch(self, symbols: list[str], interval_key: Any, *, names: dict[str, str] | None = None) -> dict[str, Any]:
        clean_symbols = normalize_up_down_symbols(symbols)
        if not clean_symbols:
            return {
                "rows": [],
                "missing": [],
                "as_of": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Yahoo Finance",
            }
        names = {str(key or "").upper().strip(): str(value or "").strip() for key, value in (names or {}).items()}
        yahoo_symbols = [self._yahoo_symbol(symbol) for symbol in clean_symbols]
        yahoo_to_original = {self._yahoo_symbol(symbol): symbol for symbol in clean_symbols}
        config = interval_fetch_config(interval_key)
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        try:
            with YF_LOCK:
                history = yf.download(
                    yahoo_symbols,
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                    **config,
                )
        except Exception as exc:
            logger.info("Up/Down history fetch failed for %s symbol(s): %s", len(clean_symbols), exc)
            history = None
        for yahoo_symbol in yahoo_symbols:
            original = yahoo_to_original.get(yahoo_symbol, yahoo_symbol)
            frame = self._history_frame_for_symbol(history, yahoo_symbol, len(yahoo_symbols))
            close = self._close_series(frame)
            row = calculate_up_down_row(original, close, interval_key, name=names.get(original, ""))
            if row is None:
                missing.append(original)
                continue
            rows.append(row)
        return {
            "rows": sort_up_down_rows(rows),
            "missing": missing,
            "as_of": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo Finance",
        }

    @staticmethod
    def _yahoo_symbol(symbol: Any) -> str:
        return str(symbol or "").upper().strip().replace(".", "-")

    def _history_frame_for_symbol(self, history: Any, symbol: str, symbol_count: int) -> Any:
        if history is None or getattr(history, "empty", True):
            return None
        try:
            columns = history.columns
        except Exception:
            return None
        try:
            if isinstance(columns, pd.MultiIndex):
                if symbol in columns.get_level_values(0):
                    return history[symbol]
                if symbol in columns.get_level_values(1):
                    return history.xs(symbol, axis=1, level=1)
            if symbol_count == 1:
                return history
        except Exception:
            return None
        return None

    @staticmethod
    def _close_series(frame: Any) -> Any:
        if frame is None or getattr(frame, "empty", True):
            return None
        for column in ("Close", "Adj Close"):
            try:
                if column in frame.columns:
                    return frame[column]
            except Exception:
                continue
        return None


def _clean_close_series(close: Any) -> Any:
    if close is None or getattr(close, "empty", True):
        return None
    try:
        series = pd.to_numeric(close, errors="coerce").dropna().astype(float)
        series.index = pd.DatetimeIndex(pd.to_datetime(series.index, errors="coerce")).tz_localize(None)
        series = series[pd.notna(series.index)]
        series = series[series > 0].sort_index()
    except Exception:
        return None
    return series if len(series) >= 2 else None


def _select_interval_series(values: Any, interval_key: str, *, latest_time: Any) -> Any:
    key = str(interval_key or "1d").strip().lower()
    if key == "1d":
        return values.tail(1)
    if key == "5d":
        return values.tail(5)
    if key == "30d":
        return values.tail(30)
    if key == "ytd":
        start = pd.Timestamp(year=int(latest_time.year), month=1, day=1)
        return values[values.index >= start]
    if key == "1y":
        start = pd.Timestamp(latest_time) - pd.DateOffset(years=1)
        return values[values.index >= start]
    return values.tail(1)


def _interval_return(series: Any, selected_index: Any) -> float | None:
    if series is None or getattr(series, "empty", True) or len(selected_index) <= 0:
        return None
    try:
        first_end = selected_index[0]
        end_position = int(series.index.get_indexer([first_end])[0])
        base_position = max(0, end_position - 1)
        base = float(series.iloc[base_position])
        latest = float(series.iloc[-1])
    except Exception:
        return None
    if not base or not math.isfinite(base) or not math.isfinite(latest):
        return None
    return (latest - base) / base * 100.0
