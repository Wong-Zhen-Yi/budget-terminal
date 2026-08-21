from __future__ import annotations

from typing import Any

import pandas as pd


def calculate_rsi(close_series: Any, period: int = 14) -> pd.Series:
    """Calculate Wilder-style RSI from closing prices."""
    closes = pd.Series(close_series).astype(float)
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    relative_strength = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - 100 / (1 + relative_strength)).bfill().clip(lower=0, upper=100)


def calculate_rsi_average(rsi_series: Any, period: int = 14) -> pd.Series:
    rsi = pd.Series(rsi_series).astype(float)
    if rsi.empty:
        return pd.Series(dtype=float)
    return rsi.rolling(period, min_periods=period).mean().bfill().clip(lower=0, upper=100)


def calculate_mfi(frame: Any, period: int = 14) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.Series(dtype=float)
    required = ("High", "Low", "Close", "Volume")
    if any(column not in frame.columns for column in required):
        return pd.Series(index=getattr(frame, "index", pd.Index([])), dtype=float)
    high = pd.Series(frame["High"], index=frame.index).astype(float)
    low = pd.Series(frame["Low"], index=frame.index).astype(float)
    close = pd.Series(frame["Close"], index=frame.index).astype(float)
    volume = pd.Series(frame["Volume"], index=frame.index).fillna(0.0).astype(float)
    typical_price = (high + low + close) / 3.0
    raw_flow = typical_price * volume
    delta = typical_price.diff()
    positive_sum = raw_flow.where(delta > 0, 0.0).rolling(period, min_periods=period).sum()
    negative_sum = raw_flow.where(delta < 0, 0.0).abs().rolling(period, min_periods=period).sum()
    ratio = positive_sum / negative_sum.replace(0.0, float("nan"))
    mfi = pd.Series(100.0 - (100.0 / (1.0 + ratio)), index=frame.index, dtype=float)
    mfi = mfi.where(~((negative_sum == 0) & (positive_sum > 0)), 100.0)
    mfi = mfi.where(~((positive_sum == 0) & (negative_sum > 0)), 0.0)
    mfi = mfi.where(~((positive_sum == 0) & (negative_sum == 0)), 50.0)
    return mfi.clip(lower=0.0, upper=100.0)


def calculate_macd(
    close_series: Any,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    closes = pd.Series(close_series).astype(float)
    if closes.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty
    fast = closes.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
    slow = closes.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()
    macd = fast - slow
    signal = macd.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
    return macd, signal, macd - signal


def calculate_true_range(frame: Any) -> pd.Series:
    """Calculate the per-bar true range from an OHLC frame."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.Series(dtype=float)
    required = ("High", "Low", "Close")
    if any(column not in frame.columns for column in required):
        return pd.Series(index=getattr(frame, "index", pd.Index([])), dtype=float)
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    previous_close = close.shift(1)
    return pd.concat(
        [
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def calculate_atr(frame: Any, period: int = 14) -> pd.Series:
    """Calculate Wilder-style ATR without back-filling the warm-up window.

    Unlike ``calculate_rsi`` this never calls ``bfill``: a back-filled warm-up value is a future
    reading copied backwards, and callers that normalize distances by ATR would silently score
    early bars against a range that had not happened yet.
    """

    true_range = calculate_true_range(frame)
    if true_range.empty:
        return true_range
    span = max(1, int(period))
    return true_range.ewm(alpha=1 / span, min_periods=span, adjust=False).mean()
