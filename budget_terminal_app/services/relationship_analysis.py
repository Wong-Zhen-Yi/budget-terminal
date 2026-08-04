from __future__ import annotations

from typing import Any

from ..dependencies import math, pd


RELATIONSHIP_WINDOWS = (30, 60, 120, 252)
RELATIONSHIP_MIN_OBSERVATIONS = 5


def normalize_relationship_symbols(symbols: Any) -> tuple[str, str]:
    """Return one distinct normalized ticker pair."""
    values = []
    for value in list(symbols or []):
        symbol = str(value or "").upper().strip()
        if symbol:
            values.append(symbol)
    if len(values) != 2:
        raise ValueError("Enter exactly two ticker symbols.")
    if values[0] == values[1]:
        raise ValueError("Choose two different ticker symbols.")
    return values[0], values[1]


def _relationship_close_series(frame: Any) -> Any:
    """Extract one positive daily close series from an adjusted-history frame."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    selected = frame["Close"]
    if isinstance(selected, pd.DataFrame):
        if selected.shape[1] != 1:
            return pd.Series(dtype=float)
        selected = selected.iloc[:, 0]
    series = pd.to_numeric(pd.Series(selected), errors="coerce")
    index = pd.DatetimeIndex(pd.to_datetime(series.index, errors="coerce"))
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    series.index = index.normalize()
    finite = series.map(lambda value: math.isfinite(float(value)) if not pd.isna(value) else False)
    series = series[finite & (series > 0.0)]
    return series[~series.index.duplicated(keep="last")].sort_index().astype(float)


def _regression_statistics(returns: Any) -> tuple[dict[str, Any], Any]:
    observations = int(len(returns))
    empty_stats = {
        "beta": None,
        "alpha_daily_pct": None,
        "r": None,
        "r_squared": None,
        "std_error_pct": None,
        "observations": observations,
    }
    if observations < RELATIONSHIP_MIN_OBSERVATIONS:
        return empty_stats, pd.DataFrame(columns=["x", "y"])

    x_values = returns["right_return"].astype(float) * 100.0
    y_values = returns["left_return"].astype(float) * 100.0
    x_mean = float(x_values.mean())
    y_mean = float(y_values.mean())
    centered_x = x_values - x_mean
    denominator = float((centered_x * centered_x).sum())
    if not math.isfinite(denominator) or denominator <= 0.0:
        return empty_stats, pd.DataFrame(columns=["x", "y"])

    beta = float((centered_x * (y_values - y_mean)).sum() / denominator)
    alpha = float(y_mean - beta * x_mean)
    correlation = float(x_values.corr(y_values))
    if not all(math.isfinite(value) for value in (beta, alpha, correlation)):
        return empty_stats, pd.DataFrame(columns=["x", "y"])

    fitted = alpha + beta * x_values
    residual_sum_squares = float(((y_values - fitted) ** 2).sum())
    std_error = (
        math.sqrt(residual_sum_squares / (observations - 2))
        if observations > 2 and residual_sum_squares >= 0.0
        else None
    )
    x_min = float(x_values.min())
    x_max = float(x_values.max())
    regression_line = pd.DataFrame(
        {
            "x": [x_min, x_max],
            "y": [alpha + beta * x_min, alpha + beta * x_max],
        }
    )
    return (
        {
            "beta": beta,
            "alpha_daily_pct": alpha,
            "r": correlation,
            "r_squared": correlation * correlation,
            "std_error_pct": float(std_error) if std_error is not None and math.isfinite(std_error) else None,
            "observations": observations,
        },
        regression_line,
    )


def build_relationship_analysis(
    left_frame: Any,
    right_frame: Any,
    *,
    rolling_window: int = 120,
) -> dict[str, Any]:
    """Build aligned price, return, correlation, and regression outputs for two securities."""
    try:
        window = int(rolling_window)
    except (TypeError, ValueError) as exc:
        raise ValueError("Rolling window must be one of 30, 60, 120, or 252 days.") from exc
    if window not in RELATIONSHIP_WINDOWS:
        raise ValueError("Rolling window must be one of 30, 60, 120, or 252 days.")

    left_close = _relationship_close_series(left_frame)
    right_close = _relationship_close_series(right_frame)
    aligned = pd.concat(
        [left_close.rename("left_close"), right_close.rename("right_close")],
        axis=1,
        join="inner",
    ).dropna()
    aligned = aligned[(aligned["left_close"] > 0.0) & (aligned["right_close"] > 0.0)].sort_index()
    if aligned.empty:
        raise ValueError("The selected tickers have no overlapping adjusted price history.")

    indexed = pd.DataFrame(index=aligned.index)
    indexed["left"] = aligned["left_close"] / float(aligned["left_close"].iloc[0]) * 100.0
    indexed["right"] = aligned["right_close"] / float(aligned["right_close"].iloc[0]) * 100.0
    ratio = (aligned["left_close"] / aligned["right_close"]).rename("ratio")

    returns = aligned.pct_change(fill_method=None).dropna().rename(
        columns={"left_close": "left_return", "right_close": "right_return"}
    )
    rolling_correlations = {}
    rolling_sample_sizes = {}
    for candidate_window in RELATIONSHIP_WINDOWS:
        rolling_sample_sizes[candidate_window] = (
            returns["left_return"].rolling(window=candidate_window, min_periods=1).count().astype(int)
        )
        correlation = returns["left_return"].rolling(
            window=candidate_window,
            min_periods=RELATIONSHIP_MIN_OBSERVATIONS,
        ).corr(returns["right_return"])
        rolling_correlations[candidate_window] = correlation.replace(
            [float("inf"), float("-inf")],
            float("nan"),
        )
    rolling_correlation = rolling_correlations[window]
    rolling_sample_size = rolling_sample_sizes[window]

    stats, regression_line = _regression_statistics(returns)
    scatter = pd.DataFrame(index=returns.index)
    scatter["x"] = returns["right_return"] * 100.0
    scatter["y"] = returns["left_return"] * 100.0

    valid_correlation = rolling_correlation.dropna()
    latest_correlation = float(valid_correlation.iloc[-1]) if not valid_correlation.empty else None
    latest_correlation_sample = (
        int(rolling_sample_size.loc[valid_correlation.index[-1]]) if not valid_correlation.empty else 0
    )
    return {
        "aligned": aligned,
        "indexed": indexed,
        "ratio": ratio,
        "returns": returns,
        "rolling_correlations": rolling_correlations,
        "rolling_sample_sizes": rolling_sample_sizes,
        "rolling_correlation": rolling_correlation,
        "rolling_sample_size": rolling_sample_size,
        "scatter": scatter,
        "regression_line": regression_line,
        "stats": stats,
        "latest_ratio": float(ratio.iloc[-1]) if not ratio.empty else None,
        "latest_correlation": latest_correlation,
        "latest_correlation_sample": latest_correlation_sample,
        "aligned_observations": int(len(aligned)),
        "rolling_window": window,
    }
