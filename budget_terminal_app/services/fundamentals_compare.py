"""Layout and rebasing math for the Fundamentals page overview charts.

Deliberately Qt-free *and* pandas-free so the smoke tests can exercise the geometry and
indexing rules without a ``QApplication`` and without paying for a heavy import, matching
the style of :mod:`budget_terminal_app.services.compare_analysis`.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Fraction of one column slot that the whole bar group may occupy, and the share of each
# bar's pitch left empty so neighbouring bars stay visually separate.
DEFAULT_SLOT_WIDTH = 0.90
DEFAULT_GAP_RATIO = 0.07

# The single-series look predates the even-layout helper; keep it byte-identical.
SINGLE_SERIES_WIDTH = 0.7

# What each bar's growth figure is measured against. 'prior_period' is the previous reported
# period in the same series; 'year_ago' is the same period one year earlier, which is the basis
# that survives seasonality on quarterly statements.
GROWTH_BASIS_PRIOR_PERIOD = 'prior_period'
GROWTH_BASIS_YEAR_AGO = 'year_ago'

# Period labels come from _p2_col_label: "2024" annual, "2024-Q3" quarterly, and a "2024-03"
# style fallback for columns that are not timestamps.
_PERIOD_LABEL_PATTERN = re.compile(r'^(\d{4})(.*)$')


def series_bar_geometry(
    count: Any,
    *,
    slot_width: float = DEFAULT_SLOT_WIDTH,
    gap_ratio: float = DEFAULT_GAP_RATIO,
) -> list[tuple[float, float]]:
    """Return evenly spaced ``(offset, width)`` pairs for ``count`` side-by-side bar series.

    Offsets are symmetric about the column centre so the group stays visually anchored to its
    period tick, and every bar shares one width. The group never spans more than ``slot_width``
    of a column, which keeps ``max(offset) + width / 2`` below 0.5 and stops bars from bleeding
    into the neighbouring period.
    """
    try:
        total = max(1, int(count))
    except (TypeError, ValueError):
        total = 1
    if total == 1:
        return [(0.0, SINGLE_SERIES_WIDTH)]
    pitch = float(slot_width) / total
    width = pitch * (1.0 - float(gap_ratio))
    centre = (total - 1) / 2.0
    return [((index - centre) * pitch, width) for index in range(total)]


def trim_columns(ordered_columns: Any, limit: Any) -> list[Any]:
    """Keep only the newest ``limit`` columns, treating a non-positive limit as no trim."""
    columns = list(ordered_columns or [])
    try:
        keep = int(limit)
    except (TypeError, ValueError):
        return columns
    if keep <= 0 or keep >= len(columns):
        return columns
    return columns[-keep:]


def index_series_values(values: Any) -> tuple[list[float], float | None]:
    """Rebase a series so its first non-zero value reads 100, preserving sign.

    Dividing by ``abs(base)`` rather than ``base`` matters for loss-making companies: a
    shrinking loss must stay below zero and rise toward it, and a loss that turns into a profit
    must cross zero upward. Dividing by a negative base flips both, so a shrinking loss would
    render as a falling bar above zero and read as deterioration.
    """
    numbers: list[float] = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        numbers.append(0.0 if not math.isfinite(number) else number)
    base = next((number for number in numbers if number != 0.0), None)
    if base is None:
        return ([0.0 for _ in numbers], None)
    denominator = abs(base)
    return ([number / denominator * 100.0 for number in numbers], base)


def previous_year_label(label: Any) -> str | None:
    """Return the period label one year earlier, or None when the label carries no year.

    ``"2024-Q3" -> "2023-Q3"``, ``"2024" -> "2023"``, ``"2024-03" -> "2023-03"``. Sentinel labels
    such as the shares-outstanding ``"Current"`` have no year-ago counterpart and return None.
    """
    match = _PERIOD_LABEL_PATTERN.match(str(label or '').strip())
    if match is None:
        return None
    year, suffix = match.groups()
    return f'{int(year) - 1:04d}{suffix}'


def growth_rate(current: Any, baseline: Any) -> float | None:
    """Return percent change against a baseline, scaled by the baseline's magnitude.

    The denominator is ``abs(baseline)`` so that a negative baseline keeps the sign meaningful:
    a loss shrinking from -5 to -2 reads as +60%, not -60%.
    """
    if baseline in (None, 0):
        return None
    try:
        return (float(current) - float(baseline)) / abs(float(baseline)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def compute_growth(
    labels: Any,
    values: Any,
    *,
    basis: str = GROWTH_BASIS_PRIOR_PERIOD,
) -> list[tuple[float | None, str]]:
    """Return one ``(growth, baseline_label)`` pair per point for the requested basis.

    Pass the *untrimmed* series: a year-ago baseline can sit up to four periods before the oldest
    period the chart will end up showing.

    The year-ago basis matches on the label rather than counting back four positions. Statement
    frames have gaps, and counting would silently pair the wrong quarters across one; matching
    returns no baseline instead, which is the honest answer.
    """
    label_list = [str(label) for label in (labels or [])]
    value_list = list(values or [])
    if len(label_list) != len(value_list):
        return [(None, '') for _ in label_list]

    def pair(value: Any, baseline: Any, baseline_label: Any) -> tuple[float | None, str]:
        """Pair one growth figure with the period it measured against, or with nothing."""
        growth = growth_rate(value, baseline)
        # An unusable baseline (absent, or zero) leaves no period worth naming in the tooltip.
        return (growth, str(baseline_label) if growth is not None else '')

    results = []
    if basis == GROWTH_BASIS_YEAR_AGO:
        by_label: dict[str, Any] = {}
        for label, value in zip(label_list, value_list):
            by_label.setdefault(label, value)
        for label, value in zip(label_list, value_list):
            baseline_label = previous_year_label(label) or ''
            results.append(pair(value, by_label.get(baseline_label), baseline_label))
        return results

    previous_value = None
    previous_label = ''
    for label, value in zip(label_list, value_list):
        results.append(pair(value, previous_value, previous_label))
        previous_value = value
        previous_label = label
    return results


def column_sort_key(label: Any) -> tuple[int, str]:
    """Sort dated period labels chronologically and sentinel labels ('Current') last."""
    text = str(label)
    return (0, text) if text[:4].isdigit() else (1, text)


def align_series_by_label(values: Any, labels: Any, columns: Any) -> tuple[list, list, list]:
    """Re-key one series onto its display labels so two tickers share chart columns.

    Two companies almost never share a fiscal calendar, so their raw period-end timestamps never
    match and the chart model would group them into disjoint columns. Keying on the rendered
    label ("2025", "2025-Q3") aligns them by calendar year or quarter instead.

    Call this only on the final triple handed to a chart series. The statement helpers that build
    derived metrics join on raw column identity within one ticker, so re-keying their inputs
    silently empties those metrics.
    """
    value_list = list(values or [])
    label_list = list(labels or [])
    column_list = list(columns or [])
    if len(label_list) != len(column_list):
        return (value_list, label_list, column_list)
    return (value_list, label_list, [str(label) for label in label_list])
