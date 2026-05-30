from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.dashboard_presenters import (
    DASHBOARD_MISSING_NUMERIC_SORT_VALUE,
    build_dashboard_option_rows,
    build_dashboard_portfolio_rows,
    build_dashboard_target_rows,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _portfolio_rows(tickers, quote_map, tracker):
    return build_dashboard_portfolio_rows(
        tickers,
        quote_map,
        tracker,
        default_color="#dddddd",
        positive_color="#00ff00",
        negative_color="#ff0000",
        positive_bg="#001a00",
        negative_bg="#1a0000",
        no_quote_bg="#111111",
    )


def test_empty_portfolio_rows() -> None:
    _assert(_portfolio_rows([], {}, {}) == [], "empty dashboard portfolio should render no rows")


def test_portfolio_formatting_sort_values_and_order() -> None:
    rows = _portfolio_rows(
        ["AAA", "BBB", "CCC"],
        {
            "AAA": {"price": 15.0, "change": 1.25},
            "BBB": {"price": 5.0, "change": -2.5},
            "CCC": {},
        },
        {
            "AAA": {"shares": 10, "avg_price": 10},
            "BBB": {"shares": 4, "avg_price": 10},
            "CCC": {"shares": 3, "avg_price": 10},
        },
    )
    _assert([ticker for ticker, _row in rows] == ["AAA", "BBB", "CCC"], "rows should sort by dollar gain descending")

    aaa = rows[0][1]
    _assert(aaa[0].text == "AAA", "ticker should render unchanged")
    _assert(aaa[1].text == "$15.00", "price should render as currency")
    _assert(aaa[2].text == "+1.25%", "positive change should include sign")
    _assert(aaa[3].text == "88.2%", "weight should use one decimal")
    _assert(aaa[4].text == "+$50", "positive dollar gain should include sign")
    _assert(aaa[2].foreground == "#00ff00", "positive change should use positive color")
    _assert(aaa[0].background == "#001a00", "positive row should use positive background")
    _assert(aaa[4].sort_value == 50.0, "gain cell should carry numeric sort value")

    bbb = rows[1][1]
    _assert(bbb[2].text == "-2.50%", "negative change should render without plus sign")
    _assert(bbb[4].text == "$-20", "negative gain should preserve existing currency order")
    _assert(bbb[2].foreground == "#ff0000", "negative change should use negative color")
    _assert(bbb[0].background == "#1a0000", "negative row should use negative background")

    ccc = rows[2][1]
    _assert(ccc[1].text == "--", "missing quote price should use placeholder")
    _assert(ccc[2].text == "--", "missing quote change should use placeholder")
    _assert(ccc[3].text == "--", "missing quote weight should use placeholder")
    _assert(ccc[4].text == "--", "missing quote gain should use placeholder")
    _assert(ccc[0].background == "#111111", "missing quote row should use neutral background")
    _assert(ccc[1].sort_value == DASHBOARD_MISSING_NUMERIC_SORT_VALUE, "missing quote price should use missing sort sentinel")


def test_target_rows() -> None:
    rows = build_dashboard_target_rows(
        [
            {"ticker": "AAA", "current": 100.0, "target": 125.0},
            {"ticker": "BBB", "current": 100.0, "target": 80.0},
            {"ticker": "CCC", "current": "N/A", "target": 50.0},
        ],
        positive_color="#00ff00",
        negative_color="#ff0000",
    )
    _assert(rows[0][1].text == "$100.00", "numeric current price should render as currency")
    _assert(rows[0][3].text == "+25.0%", "positive upside should render with plus sign")
    _assert(rows[0][3].foreground == "#00ff00", "positive upside should use positive color")
    _assert(rows[1][3].text == "-20.0%", "negative upside should render with minus sign")
    _assert(rows[1][3].foreground == "#ff0000", "negative upside should use negative color")
    _assert(rows[2][1].text == "N/A", "non-numeric current should pass through")
    _assert(rows[2][3].text == "N/A", "invalid current should produce upside fallback")


def test_option_rows() -> None:
    rows = build_dashboard_option_rows(
        [
            {"ticker": "SPY", "type": "Call", "strike": 500.0, "expiration": "2026-06-19", "lastPrice": 1.25, "volume": 1234},
            {"ticker": "SPY", "type": "Put", "strike": 490.0, "expiration": "2026-06-19", "lastPrice": None, "volume": 0},
        ],
        symbol="SPY",
        positive_color="#00ff00",
        negative_color="#ff0000",
    )
    _assert(rows[0][1].text == "Call", "call type should render")
    _assert(rows[0][1].foreground == "#00ff00", "call type should use positive color")
    _assert(rows[0][2].text == "500.0", "strike should use one decimal")
    _assert(rows[0][4].text == "1.25", "last price should use two decimals")
    _assert(rows[0][5].text == "1,234", "volume should use thousands separator")
    _assert(rows[0][5].sort_value == 1234.0, "volume should carry numeric sort value")
    _assert(rows[1][1].foreground == "#ff0000", "put type should use negative color")
    _assert(rows[1][4].text == "", "missing last price should render blank")
    _assert(rows[1][5].text == "0", "zero volume should render zero")


def main() -> None:
    test_empty_portfolio_rows()
    test_portfolio_formatting_sort_values_and_order()
    test_target_rows()
    test_option_rows()
    print("dashboard presenter smoke tests passed")


if __name__ == "__main__":
    main()
