"""Analytics for the Charts page Compare subtab.

Deliberately Qt-free so the smoke tests can exercise the correlation math without a
``QApplication``, matching the style of :mod:`budget_terminal_app.services.relationship_analysis`.
"""

from __future__ import annotations

from typing import Any

from ..dependencies import math, pd

COMPARE_CORRELATION_MIN_OBSERVATIONS = 10


def _compare_interval_returns(frame: Any) -> Any:
    """Rebuild per-interval returns from one cumulative-percent compare frame.

    Compare series hold cumulative percent change versus the range start, so the interval return
    between two points is ``(100 + current) / (100 + previous) - 1``. Each column steps from its own
    previous *valid* observation, matching ``_p10_calculate_compare_interval_changes`` on the page.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    columns = {}
    for column in numeric.columns:
        base = (numeric[column].astype(float) / 100.0 + 1.0).dropna()
        base = base[base.map(lambda value: math.isfinite(float(value)) and float(value) != 0.0)]
        if base.size < 2:
            continue
        returns = base.pct_change(fill_method=None).dropna()
        returns = returns[returns.map(lambda value: math.isfinite(float(value)))]
        if returns.empty:
            continue
        columns[str(column)] = returns
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).reindex(columns=[str(column) for column in numeric.columns if str(column) in columns])


def build_compare_correlation_matrix(
    frame: Any,
    *,
    min_observations: int = COMPARE_CORRELATION_MIN_OBSERVATIONS,
) -> dict[str, Any]:
    """Build the pairwise correlation matrix for one cumulative-percent compare frame."""
    try:
        min_periods = max(2, int(min_observations))
    except (TypeError, ValueError):
        min_periods = COMPARE_CORRELATION_MIN_OBSERVATIONS
    empty = {
        "symbols": [],
        "matrix": [],
        "observations": [],
        "min_observations": min_periods,
        "message": "Add at least two tickers to see correlations.",
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty or frame.shape[1] < 2:
        return empty

    returns = _compare_interval_returns(frame)
    symbols = [str(column) for column in returns.columns]
    if returns.empty or len(symbols) < 2:
        return dict(empty, message="Not enough price history to correlate the selected tickers.")

    correlations = returns.corr(min_periods=min_periods)
    valid = returns.notna()
    matrix: list[list[float | None]] = []
    observations: list[list[int]] = []
    for row_symbol in symbols:
        matrix_row: list[float | None] = []
        observation_row: list[int] = []
        for column_symbol in symbols:
            shared = int((valid[row_symbol] & valid[column_symbol]).sum())
            observation_row.append(shared)
            try:
                value = float(correlations.at[row_symbol, column_symbol])
            except (KeyError, TypeError, ValueError):
                value = float("nan")
            if not math.isfinite(value) or shared < min_periods:
                matrix_row.append(None)
                continue
            matrix_row.append(max(-1.0, min(1.0, value)))
        matrix.append(matrix_row)
        observations.append(observation_row)

    message = ""
    if all(value is None for row in matrix for value in row):
        message = f"Need at least {min_periods} shared periods to correlate the selected tickers."
    return {
        "symbols": symbols,
        "matrix": matrix,
        "observations": observations,
        "min_observations": min_periods,
        "message": message,
    }


def _parse_hex_color(value: Any) -> tuple[int, int, int]:
    """Parse one ``#rrggbb`` string into an RGB triple."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        return (0, 0, 0)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def mix_hex_color(left: Any, right: Any, amount: Any) -> str:
    """Blend two ``#rrggbb`` colors, where ``amount`` 0 keeps ``left`` and 1 keeps ``right``."""
    try:
        ratio = float(amount)
    except (TypeError, ValueError):
        ratio = 0.0
    if not math.isfinite(ratio):
        ratio = 0.0
    ratio = max(0.0, min(1.0, ratio))
    left_rgb = _parse_hex_color(left)
    right_rgb = _parse_hex_color(right)
    mixed = [int(round(left_value + (right_value - left_value) * ratio)) for left_value, right_value in zip(left_rgb, right_rgb)]
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, value)) for value in mixed])
