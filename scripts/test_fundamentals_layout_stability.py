"""Fundamentals must paint its chart grid in the frame the page becomes visible.

The page used to reveal itself in stages: switch_page painted page2, then a zero-timer reflowed
the six-chart grid, then another zero-timer re-plotted every chart, then a third placed the value
labels and rescaled each Y axis. This smoke pins the three properties that removed that pop-in:

1. The grid reflow happens inside the switch_page call stack, before the first paint.
2. Returning to an unchanged page rebuilds nothing and re-renders nothing.
3. A real reflow (crossing the 3-column width threshold) still rebuilds.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-fundamentals-layout-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from test_tab_picker_search import _build_window


FUNDAMENTALS_INDEX = 8
DASHBOARD_INDEX = 0
CHART_COUNT = 6
# The window's minimum width is 1264px, which always clears _p2_relayout_charts' 1200px
# three-column threshold, so height is the axis a test can actually move. Shrinking it changes
# spacing, chart_height, plot_height and box_height together.
TALL = (1600, 1200)
SHORT = (1600, 760)


def _drain(app, passes: int = 8) -> None:
    for _ in range(passes):
        app.processEvents()


def _sample_payload() -> dict:
    """Minimal payload shaped like a FundamentalsWorker result, enough to plot every chart."""
    import pandas as pd

    columns = pd.to_datetime(["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"])
    income = pd.DataFrame(
        {
            "Total Revenue": [100.0, 130.0, 170.0, 210.0],
            "Net Income": [10.0, 18.0, 25.0, 33.0],
            "Operating Expense": [40.0, 48.0, 55.0, 62.0],
        }
    ).T
    income.columns = columns
    cashflow = pd.DataFrame(
        {
            "Operating Cash Flow": [20.0, 28.0, 36.0, 45.0],
            "Capital Expenditure": [-6.0, -7.0, -8.0, -9.0],
        }
    ).T
    cashflow.columns = columns
    balance = pd.DataFrame(
        {
            "Ordinary Shares Number": [1000.0, 990.0, 975.0, 960.0],
            "Cash And Cash Equivalents": [50.0, 60.0, 72.0, 85.0],
            "Total Debt": [30.0, 28.0, 26.0, 24.0],
        }
    ).T
    balance.columns = columns
    return {
        "ticker": "TEST",
        "info": {"longName": "Test Corp", "sector": "Tech", "industry": "Software", "currency": "USD"},
        "financials": income,
        "quarterly_financials": income,
        "cashflow": cashflow,
        "quarterly_cashflow": cashflow,
        "balance_sheet": balance,
        "quarterly_balance_sheet": balance,
    }


def _show(app, window, size=TALL) -> None:
    """Give the window real geometry. Hidden widgets report stale sizes, which is exactly the
    condition the fix is about, so a test that never shows the window proves nothing."""
    window.resize(*size)
    window.show()
    _drain(app)


def _load_fundamentals(app, window) -> None:
    _show(app, window)
    window._ensure_page_initialized(FUNDAMENTALS_INDEX)
    window.switch_page(FUNDAMENTALS_INDEX)
    _drain(app)
    window.update_page2(_sample_payload())
    _drain(app)


def test_reflow_happens_before_the_first_paint() -> None:
    app, window = _build_window()
    try:
        _show(app, window)
        window._ensure_page_initialized(FUNDAMENTALS_INDEX)
        window.switch_page(DASHBOARD_INDEX)
        _drain(app)

        window._p2_chart_layout_signature = None
        before = int(window._p2_chart_layout_rebuilds)
        window.switch_page(FUNDAMENTALS_INDEX)
        # No processEvents: anything counted here ran inside switch_page itself, which is the
        # whole point. A deferred reflow would leave this at `before`.
        during_switch = int(window._p2_chart_layout_rebuilds)
        assert during_switch > before, (
            "the chart grid reflowed after the page was painted, not inside switch_page"
        )

        _drain(app)
        assert int(window._p2_chart_layout_rebuilds) == during_switch, (
            "a deferred pass rebuilt the grid again after the switch"
        )
        assert window._p2_chart_layout_signature is not None
        assert window.p2_charts_grid.count() == CHART_COUNT
    finally:
        window.close()
        app.processEvents()


def test_returning_to_an_unchanged_page_is_free() -> None:
    app, window = _build_window()
    try:
        _load_fundamentals(app, window)

        renders = []
        original_render = window._render_simple_charts
        window._render_simple_charts = lambda data, period: (
            renders.append(period), original_render(data, period)
        )[1]
        rebuilds_before = int(window._p2_chart_layout_rebuilds)

        window.switch_page(DASHBOARD_INDEX)
        _drain(app)
        window.switch_page(FUNDAMENTALS_INDEX)
        _drain(app)

        assert int(window._p2_chart_layout_rebuilds) == rebuilds_before, (
            f"revisiting an unchanged page rebuilt the grid "
            f"{int(window._p2_chart_layout_rebuilds) - rebuilds_before} time(s)"
        )
        assert not renders, f"revisiting an unchanged page re-plotted the charts {len(renders)} time(s)"
        assert not window._p2_chart_density_refresh_pending, "a redundant rerender was left queued"
    finally:
        window.close()
        app.processEvents()


def test_a_real_reflow_still_rebuilds() -> None:
    app, window = _build_window()
    try:
        _load_fundamentals(app, window)
        assert window._p2_chart_layout_signature is not None
        tall_signature = window._p2_chart_layout_signature
        rebuilds_before = int(window._p2_chart_layout_rebuilds)

        # A genuine geometry change must not be swallowed by the no-op cache. The window's own
        # resize path calls _p2_relayout_charts while the page is current.
        window.resize(*SHORT)
        _drain(app, passes=20)

        assert window._p2_chart_layout_signature != tall_signature, (
            "the layout cache swallowed a genuine reflow"
        )
        assert int(window._p2_chart_layout_rebuilds) > rebuilds_before, (
            "a real resize did not rebuild the grid"
        )
        assert window.p2_charts_grid.count() == CHART_COUNT

        # ...and the cache settles again straight after, so the reflow costs exactly one rebuild.
        settled = int(window._p2_chart_layout_rebuilds)
        window._p2_relayout_charts()
        assert int(window._p2_chart_layout_rebuilds) == settled, (
            "a redundant relayout after a resize rebuilt the grid again"
        )
    finally:
        window.close()
        app.processEvents()


def test_theme_reapply_rebuilds_rather_than_hitting_the_cache() -> None:
    app, window = _build_window()
    try:
        _load_fundamentals(app, window)
        assert window._p2_chart_layout_signature is not None
        rebuilds_before = int(window._p2_chart_layout_rebuilds)

        # A theme re-apply rebuilds chart chrome at identical geometry, so the cached signature
        # would otherwise match and skip the reflow the new chrome needs.
        window._apply_fundamentals_theme()
        _drain(app)

        assert int(window._p2_chart_layout_rebuilds) > rebuilds_before, (
            "the layout cache survived a theme re-apply and skipped the rebuild"
        )
        assert window.p2_charts_grid.count() == CHART_COUNT
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_reflow_happens_before_the_first_paint()
    test_returning_to_an_unchanged_page_is_free()
    test_a_real_reflow_still_rebuilds()
    test_theme_reapply_rebuilds_rather_than_hitting_the_cache()
    print("Fundamentals layout stability tests passed.")
