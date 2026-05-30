from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.constants import (
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_COST,
    P4_PORTFOLIO_COL_DAY_CHANGE,
    P4_PORTFOLIO_COL_DOLLAR_GAIN,
    P4_PORTFOLIO_COL_GROWTH,
    P4_PORTFOLIO_COL_MARKET_CAP,
    P4_PORTFOLIO_COL_MARKET_VALUE,
    P4_PORTFOLIO_COL_PRICE,
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_SYMBOL,
    P4_PORTFOLIO_COL_WEIGHT,
    P4_PORTFOLIO_COLUMNS,
)
from budget_terminal_app.mixins.options_table_rows import OptionsTableRowsMixin
from budget_terminal_app.mixins.portfolio_presenters import (
    P4_MISSING_NUMERIC_SORT_VALUE,
    build_portfolio_stock_row,
    format_market_cap,
    market_cap_color_token,
    market_cap_sort_value,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_stock_row_formatting_and_sort_values() -> None:
    row = build_portfolio_stock_row(
        "spy",
        {
            "shares": 3.5,
            "avg_price": 100.25,
            "price": 110.5,
            "change": 1.234,
            "cost": 350.875,
            "market_value": 386.75,
            "weight": 42.42,
            "dollar_gain": 35.875,
            "growth": 10.225,
        },
        default_color="#dddddd",
        gain_color="#00ff00",
        change_color="#00ff00",
        market_cap=250_000_000_000,
        market_cap_color="#ffaa00",
    )

    _assert(len(row) == len(P4_PORTFOLIO_COLUMNS), "stock row should keep Portfolio column count")
    _assert(row[P4_PORTFOLIO_COL_SYMBOL].text == "spy", "symbol text should pass through unchanged")
    _assert(row[P4_PORTFOLIO_COL_SHARES].text == "3.5", "shares should use compact numeric formatting")
    _assert(row[P4_PORTFOLIO_COL_AVG_PRICE].text == "100.25", "average price should keep two decimals")
    _assert(row[P4_PORTFOLIO_COL_COST].text == "$350.88", "cost should render as currency")
    _assert(row[P4_PORTFOLIO_COL_PRICE].text == "$110.50", "price should render as currency")
    _assert(row[P4_PORTFOLIO_COL_DAY_CHANGE].text == "+1.23%", "day change should show positive sign")
    _assert(row[P4_PORTFOLIO_COL_MARKET_VALUE].text == "$386.75", "market value should render as currency")
    _assert(row[P4_PORTFOLIO_COL_WEIGHT].text == "42.4%", "weight should render with one decimal")
    _assert(row[P4_PORTFOLIO_COL_DOLLAR_GAIN].text == "+$35.88", "dollar gain should show positive sign")
    _assert(row[P4_PORTFOLIO_COL_GROWTH].text == "+10.2%", "growth should show positive sign")
    _assert(row[P4_PORTFOLIO_COL_MARKET_CAP].text == "Mega $250.00B", "market cap should include bucket")

    _assert(row[P4_PORTFOLIO_COL_SHARES].editable, "shares should remain editable")
    _assert(row[P4_PORTFOLIO_COL_AVG_PRICE].editable, "average price should remain editable")
    for column in (
        P4_PORTFOLIO_COL_COST,
        P4_PORTFOLIO_COL_PRICE,
        P4_PORTFOLIO_COL_DAY_CHANGE,
        P4_PORTFOLIO_COL_MARKET_VALUE,
        P4_PORTFOLIO_COL_WEIGHT,
        P4_PORTFOLIO_COL_DOLLAR_GAIN,
        P4_PORTFOLIO_COL_GROWTH,
        P4_PORTFOLIO_COL_MARKET_CAP,
    ):
        _assert(not row[column].editable, f"column {column} should remain read-only")
        _assert(row[column].sort_value is not None, f"column {column} should carry numeric sort data")


def test_empty_stock_row_defaults() -> None:
    row = build_portfolio_stock_row(
        "",
        {},
        default_color="#dddddd",
        gain_color="#00ff00",
        change_color="#00ff00",
    )
    _assert(row[P4_PORTFOLIO_COL_SYMBOL].text == "", "empty symbol should stay empty")
    _assert(row[P4_PORTFOLIO_COL_SHARES].text == "0", "missing shares should render as zero")
    _assert(row[P4_PORTFOLIO_COL_AVG_PRICE].text == "0.00", "missing average price should render as zero")
    _assert(row[P4_PORTFOLIO_COL_MARKET_CAP].text == "--", "missing market cap should render as muted placeholder")
    _assert(row[P4_PORTFOLIO_COL_MARKET_CAP].sort_value == P4_MISSING_NUMERIC_SORT_VALUE, "missing market cap should use the missing sort sentinel")


def test_market_cap_helpers() -> None:
    _assert(format_market_cap(None) == "--", "empty market cap should use placeholder")
    _assert(market_cap_sort_value(None) == P4_MISSING_NUMERIC_SORT_VALUE, "empty market cap should use missing sort value")
    _assert(market_cap_color_token(None) == "text_muted", "empty market cap should use muted color token")
    _assert(format_market_cap(15_000_000_000) == "Large $15.00B", "large cap display should be compact")
    _assert(market_cap_sort_value("15,000,000,000") == 15_000_000_000, "market cap sort should coerce strings")
    _assert(market_cap_color_token(15_000_000_000) == "series_0", "large cap should keep previous color bucket")


def test_option_row_id_preservation() -> None:
    mixin = OptionsTableRowsMixin()
    position = {}
    first_id = mixin._ensure_option_row_id(position)
    _assert(position.get("row_id") == first_id, "row_id should be persisted into the option position")
    _assert(mixin._ensure_option_row_id(position) == first_id, "row_id should remain stable across calls")


def main() -> None:
    test_stock_row_formatting_and_sort_values()
    test_empty_stock_row_defaults()
    test_market_cap_helpers()
    test_option_row_id_preservation()
    print("portfolio presenter smoke tests passed")


if __name__ == "__main__":
    main()
