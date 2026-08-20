from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.services.fundamentals_compare import (
    GROWTH_BASIS_PRIOR_PERIOD,
    GROWTH_BASIS_YEAR_AGO,
    align_series_by_label,
    column_sort_key,
    compute_growth,
    index_series_values,
    previous_year_label,
    series_bar_geometry,
    trim_columns,
)


def test_bar_geometry() -> None:
    # A lone series must keep the exact look the page had before the even-layout helper.
    assert series_bar_geometry(1) == [(0.0, 0.7)]

    for count in (1, 2, 3, 4):
        geometry = series_bar_geometry(count)
        assert len(geometry) == count
        offsets = [offset for offset, _ in geometry]
        widths = [width for _, width in geometry]
        assert all(abs(width - widths[0]) < 1e-9 for width in widths), "series must share one width"
        assert offsets == sorted(offsets), "offsets must run left to right"
        assert abs(sum(offsets)) < 1e-9, "offsets must be symmetric about the column centre"
        # Bars must never bleed into the neighbouring period slot.
        assert max(offsets) + widths[0] / 2.0 < 0.5

    # Two series should land within a hair of the hard-coded pairs they replace.
    (left_offset, left_width), (right_offset, right_width) = series_bar_geometry(2)
    assert abs(left_offset + 0.22) < 0.01 and abs(right_offset - 0.22) < 0.01
    assert abs(left_width - 0.42) < 0.01 and abs(right_width - 0.42) < 0.01

    # Garbage counts degrade to a single series rather than raising.
    assert series_bar_geometry(0) == [(0.0, 0.7)]
    assert series_bar_geometry(None) == [(0.0, 0.7)]


def test_trim_columns() -> None:
    columns = ["2019", "2020", "2021", "2022", "2023"]
    assert trim_columns(columns, 10) == columns
    assert trim_columns(columns, 5) == columns
    assert trim_columns(columns, 2) == ["2022", "2023"], "trim must keep the newest periods"
    assert trim_columns(columns, 0) == columns
    assert trim_columns(columns, -3) == columns
    assert trim_columns(columns, "x") == columns
    assert trim_columns([], 4) == []


def test_index_series_values() -> None:
    values, base = index_series_values([50.0, 75.0, 100.0])
    assert values[0] == 100.0 and base == 50.0
    assert abs(values[1] - 150.0) < 1e-9

    # A shrinking loss must stay below zero and rise toward it.
    values, base = index_series_values([-5.0, -2.0])
    assert values[0] == -100.0 and base == -5.0
    assert abs(values[1] + 40.0) < 1e-9

    # A loss turning into a profit must cross zero upward.
    values, _ = index_series_values([-5.0, 2.0])
    assert values[0] == -100.0 and values[1] > 0

    # A leading zero is not a usable base; fall through to the first non-zero point.
    values, base = index_series_values([0.0, 25.0, 50.0])
    assert base == 25.0
    assert values[0] == 0.0 and values[1] == 100.0 and values[2] == 200.0

    # An all-zero series keeps its points so the legend does not lie about what is on screen.
    values, base = index_series_values([0.0, 0.0])
    assert values == [0.0, 0.0] and base is None

    # Non-numeric and non-finite input degrades to zero rather than raising.
    values, base = index_series_values([None, "x", 4.0])
    assert base == 4.0 and values[2] == 100.0


def test_column_sort_key() -> None:
    assert sorted(["Current", "2025", "2024"], key=column_sort_key) == ["2024", "2025", "Current"]
    assert sorted(["2023-Q1", "2022-Q4"], key=column_sort_key) == ["2022-Q4", "2023-Q1"]
    assert sorted(["2024-Q2", "2024-Q1", "2024-Q10"], key=column_sort_key) == [
        "2024-Q1",
        "2024-Q10",
        "2024-Q2",
    ]
    # A lowercase sentinel must still sort last; plain string ordering would put it first.
    assert sorted(["current", "2024"], key=column_sort_key) == ["2024", "current"]


def test_align_series_by_label() -> None:
    values, labels, columns = align_series_by_label([1.0, 2.0], ["2024", "2025"], ["a", "b"])
    assert values == [1.0, 2.0]
    assert labels == ["2024", "2025"]
    assert columns == ["2024", "2025"], "columns must be re-keyed onto the display labels"

    # Two tickers on different fiscal calendars must land on the same columns.
    _, _, left = align_series_by_label([1.0], ["2024"], ["2024-01-31"])
    _, _, right = align_series_by_label([2.0], ["2024"], ["2024-09-28"])
    assert left == right

    # A mismatched triple is passed through untouched rather than silently mangled.
    assert align_series_by_label([1.0], ["2024", "2025"], ["a"]) == ([1.0], ["2024", "2025"], ["a"])


def test_basis_constants_match_persistence() -> None:
    """persistence.py mirrors these values so it need not import this module; pin them together."""
    from budget_terminal_app.persistence import (
        P2_GROWTH_BASES,
        P2_GROWTH_BASIS_PRIOR_PERIOD,
        P2_GROWTH_BASIS_YEAR_AGO,
    )

    assert P2_GROWTH_BASIS_PRIOR_PERIOD == GROWTH_BASIS_PRIOR_PERIOD
    assert P2_GROWTH_BASIS_YEAR_AGO == GROWTH_BASIS_YEAR_AGO
    assert set(P2_GROWTH_BASES) == {GROWTH_BASIS_PRIOR_PERIOD, GROWTH_BASIS_YEAR_AGO}


def test_previous_year_label() -> None:
    assert previous_year_label("2024-Q3") == "2023-Q3"
    assert previous_year_label("2024") == "2023"
    assert previous_year_label("2024-03") == "2023-03"
    assert previous_year_label("2000-Q1") == "1999-Q1"
    # Sentinel and malformed labels have no year-ago counterpart.
    assert previous_year_label("Current") is None
    assert previous_year_label("") is None
    assert previous_year_label(None) is None
    assert previous_year_label("Tota") is None


def test_compute_growth_prior_period() -> None:
    labels = ["2022-Q1", "2022-Q2", "2022-Q3"]
    growth = compute_growth(labels, [100.0, 110.0, 99.0], basis=GROWTH_BASIS_PRIOR_PERIOD)
    assert growth[0] == (None, ""), "the first point has nothing to measure against"
    assert abs(growth[1][0] - 10.0) < 1e-9 and growth[1][1] == "2022-Q1"
    assert abs(growth[2][0] + 10.0) < 1e-9 and growth[2][1] == "2022-Q2"

    # A zero baseline yields no growth, and therefore no period worth naming.
    assert compute_growth(["a", "b"], [0.0, 5.0], basis=GROWTH_BASIS_PRIOR_PERIOD)[1] == (None, "")

    # A negative baseline keeps the sign meaningful: a shrinking loss reads as a gain.
    shrinking = compute_growth(["a", "b"], [-5.0, -2.0], basis=GROWTH_BASIS_PRIOR_PERIOD)
    assert abs(shrinking[1][0] - 60.0) < 1e-9, shrinking


def test_compute_growth_year_ago() -> None:
    labels = [f"{year}-Q{quarter}" for year in (2022, 2023) for quarter in (1, 2, 3, 4)]
    values = [float(100 + index) for index in range(8)]
    growth = compute_growth(labels, values, basis=GROWTH_BASIS_YEAR_AGO)

    # The first year has no prior year to measure against.
    assert [entry == (None, "") for entry in growth[:4]] == [True] * 4
    # 2023-Q1 (104) against 2022-Q1 (100).
    assert abs(growth[4][0] - 4.0) < 1e-9 and growth[4][1] == "2022-Q1"
    assert growth[7][1] == "2022-Q4"

    # A gap year must yield no baseline rather than silently reaching further back.
    gapped = compute_growth(["2020", "2022"], [100.0, 200.0], basis=GROWTH_BASIS_YEAR_AGO)
    assert gapped == [(None, ""), (None, "")], gapped

    # Annual labels pair with the prior calendar year.
    annual = compute_growth(["2023", "2024"], [50.0, 75.0], basis=GROWTH_BASIS_YEAR_AGO)
    assert abs(annual[1][0] - 50.0) < 1e-9 and annual[1][1] == "2023"

    # The 'Current' shares sentinel has no year-ago partner.
    assert compute_growth(["Current"], [42.0], basis=GROWTH_BASIS_YEAR_AGO) == [(None, "")]

    # Mismatched inputs degrade rather than raising.
    assert compute_growth(["2024"], [1.0, 2.0], basis=GROWTH_BASIS_YEAR_AGO) == [(None, "")]
    assert compute_growth([], [], basis=GROWTH_BASIS_YEAR_AGO) == []


if __name__ == "__main__":
    test_bar_geometry()
    test_trim_columns()
    test_index_series_values()
    test_column_sort_key()
    test_align_series_by_label()
    test_basis_constants_match_persistence()
    test_previous_year_label()
    test_compute_growth_prior_period()
    test_compute_growth_year_ago()
    print("Fundamentals compare service tests passed.")
