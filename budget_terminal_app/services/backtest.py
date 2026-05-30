from __future__ import annotations

import datetime
from typing import Any

from ..dependencies import logger, math, pd, yf


BACKTEST_INTERVALS = {
    "1D": "1d",
    "1W": "1wk",
}
BACKTEST_RANGES = ("Max", "5Y", "3Y", "1Y", "YTD")
BACKTEST_START_VALUE = 10000.0


def normalize_backtest_rows(rows: Any) -> tuple[list[dict[str, float | str]], float]:
    """Return valid unique backtest rows and the raw weight total."""
    normalized: list[dict[str, float | str]] = []
    seen: set[str] = set()
    total_weight = 0.0
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "") or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        try:
            weight = float(row.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if not math.isfinite(weight) or weight <= 0.0:
            continue
        seen.add(symbol)
        total_weight += weight
        normalized.append({"symbol": symbol, "weight": weight})
    return normalized, total_weight


def _price_column(frame: Any) -> str:
    if frame is None or getattr(frame, "empty", True):
        return ""
    for column in ("Adj Close", "Close"):
        if column in frame.columns:
            return column
    return ""


def price_series_from_frame(frame: Any) -> Any:
    """Extract the adjusted close series used by the backtest."""
    column = _price_column(frame)
    if not column:
        return pd.Series(dtype=float)
    series = pd.Series(frame[column]).astype(float).dropna()
    if series.empty:
        return pd.Series(dtype=float)
    index = pd.DatetimeIndex(pd.to_datetime(series.index))
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    series.index = pd.DatetimeIndex(index.astype("datetime64[ns]"))
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series[series > 0.0]


def slice_backtest_range(frame: Any, range_key: Any) -> Any:
    """Slice a price frame to one supported local backtest range."""
    if frame is None or getattr(frame, "empty", True):
        return frame
    key = str(range_key or "Max").strip().upper()
    if key == "MAX":
        return frame
    end = frame.index.max()
    if key == "YTD":
        start = pd.Timestamp(datetime.date(int(end.year), 1, 1))
    elif key.endswith("Y"):
        try:
            years = int(key[:-1])
        except (TypeError, ValueError):
            return frame
        start = end - pd.DateOffset(years=years)
    else:
        return frame
    return frame.loc[frame.index >= start].copy()


def calculate_buy_hold_backtest(
    price_frames: dict[str, Any],
    rows: Any,
    *,
    range_key: Any = "Max",
    compare_frame: Any = None,
    compare_symbol: Any = "",
) -> dict[str, Any]:
    """Calculate a normalized buy-and-hold portfolio backtest."""
    normalized_rows, total_weight = normalize_backtest_rows(rows)
    if not normalized_rows:
        raise ValueError("Add at least one ticker with a positive weight.")
    weights = {str(row["symbol"]): float(row["weight"]) / total_weight for row in normalized_rows}
    missing = []
    series_map = {}
    for symbol in weights:
        series = price_series_from_frame(price_frames.get(symbol))
        if series.empty:
            missing.append(symbol)
        else:
            series_map[symbol] = series.rename(symbol)
    if missing:
        raise ValueError(f"No valid price data for: {', '.join(missing)}.")
    prices = pd.concat(series_map.values(), axis=1, join="inner").dropna()
    prices = slice_backtest_range(prices, range_key)
    if prices.empty or len(prices) < 2:
        raise ValueError("Not enough overlapping history for the selected range.")
    normalized_prices = prices / prices.iloc[0]
    weight_series = pd.Series(weights)
    portfolio_value = normalized_prices.mul(weight_series, axis=1).sum(axis=1)
    portfolio_return = (portfolio_value - 1.0) * 100.0
    drawdown = (portfolio_value / portfolio_value.cummax() - 1.0) * 100.0
    start = portfolio_value.index[0]
    end = portfolio_value.index[-1]
    elapsed_days = max((end - start).total_seconds() / 86400.0, 0.0)
    total_return_pct = float(portfolio_return.iloc[-1])
    cagr_pct = 0.0
    if elapsed_days > 0.0 and portfolio_value.iloc[-1] > 0.0:
        years = elapsed_days / 365.25
        if years > 0.0:
            cagr_pct = (float(portfolio_value.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0
    compare_return = None
    compare_error = ""
    compare_symbol_text = str(compare_symbol or "").upper().strip()
    if compare_symbol_text:
        compare_series = price_series_from_frame(compare_frame).rename(compare_symbol_text)
        compare_series = compare_series.loc[(compare_series.index >= start) & (compare_series.index <= end)].dropna()
        if compare_series.empty or len(compare_series) < 2:
            compare_error = f"No valid compare data for {compare_symbol_text} in the portfolio window."
        else:
            compare_series = compare_series.reindex(portfolio_value.index).ffill().dropna()
            if compare_series.empty or len(compare_series) < 2:
                compare_error = f"Compare data for {compare_symbol_text} could not be aligned."
            else:
                compare_return = (compare_series / float(compare_series.iloc[0]) - 1.0) * 100.0
    return {
        "rows": normalized_rows,
        "weights": weights,
        "raw_weight_total": total_weight,
        "prices": prices,
        "portfolio_value": portfolio_value,
        "portfolio_return": portfolio_return,
        "drawdown": drawdown,
        "compare_return": compare_return,
        "compare_symbol": compare_symbol_text,
        "compare_error": compare_error,
        "stats": {
            "start": start,
            "end": end,
            "total_return_pct": total_return_pct,
            "cagr_pct": cagr_pct,
            "max_drawdown_pct": float(drawdown.min()),
            "final_value": BACKTEST_START_VALUE * float(portfolio_value.iloc[-1]),
        },
    }


class BacktestDataService:
    """Fetch yfinance price frames and calculate buy-and-hold backtests."""

    def fetch_price_frame(self, symbol: Any, *, interval: Any) -> Any:
        symbol_text = str(symbol or "").upper().strip()
        if not symbol_text:
            return pd.DataFrame()
        interval_text = str(interval or "1d").strip().lower()
        try:
            frame = yf.download(
                symbol_text,
                period="max",
                interval=interval_text,
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:
            logger.info("Backtest price fetch failed for %s: %s", symbol_text, exc)
            return pd.DataFrame()
        if frame is None or getattr(frame, "empty", True):
            return pd.DataFrame()
        if isinstance(frame.columns, pd.MultiIndex):
            try:
                if symbol_text in [str(value).upper() for value in frame.columns.get_level_values(0)]:
                    frame = frame[symbol_text]
                elif symbol_text in [str(value).upper() for value in frame.columns.get_level_values(1)]:
                    frame = frame.xs(symbol_text, axis=1, level=1)
            except Exception:
                pass
        return frame.copy()

    def run_backtest(
        self,
        rows: Any,
        *,
        compare_symbol: Any,
        interval: Any,
        range_key: Any,
    ) -> dict[str, Any]:
        normalized_rows, _ = normalize_backtest_rows(rows)
        symbols = [str(row["symbol"]) for row in normalized_rows]
        price_frames = {
            symbol: self.fetch_price_frame(symbol, interval=interval)
            for symbol in symbols
        }
        compare_symbol_text = str(compare_symbol or "").upper().strip()
        compare_frame = self.fetch_price_frame(compare_symbol_text, interval=interval) if compare_symbol_text else None
        return calculate_buy_hold_backtest(
            price_frames,
            normalized_rows,
            range_key=range_key,
            compare_frame=compare_frame,
            compare_symbol=compare_symbol_text,
        )
