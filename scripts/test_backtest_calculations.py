from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.services import backtest as backtest_module
from budget_terminal_app.services.backtest import (
    BacktestDataService,
    calculate_buy_hold_backtest,
    normalize_backtest_rows,
    price_series_from_frame,
)


def _frame(values, *, start: str = "2020-01-01"):
    index = pd.date_range(start=start, periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Adj Close": values,
            "Volume": [1000] * len(values),
        },
        index=index,
    )


def test_weight_normalization():
    rows, total = normalize_backtest_rows(
        [
            {"symbol": "aapl", "weight": "60"},
            {"symbol": "MSFT", "weight": 40},
            {"symbol": "MSFT", "weight": 20},
            {"symbol": "", "weight": 20},
        ]
    )
    assert total == 100.0
    assert rows == [{"symbol": "AAPL", "weight": 60.0}, {"symbol": "MSFT", "weight": 40.0}]


def test_buy_and_hold_return():
    result = calculate_buy_hold_backtest(
        {
            "AAA": _frame([100, 110, 120]),
            "BBB": _frame([100, 100, 100]),
        },
        [{"symbol": "AAA", "weight": 50}, {"symbol": "BBB", "weight": 50}],
    )
    assert round(float(result["portfolio_return"].iloc[-1]), 4) == 10.0
    assert round(float(result["stats"]["final_value"]), 2) == 11000.0


def test_common_date_alignment():
    result = calculate_buy_hold_backtest(
        {
            "AAA": _frame([100, 110, 120], start="2020-01-01"),
            "BBB": _frame([100, 105, 110], start="2020-01-02"),
        },
        [{"symbol": "AAA", "weight": 50}, {"symbol": "BBB", "weight": 50}],
    )
    assert str(result["stats"]["start"].date()) == "2020-01-02"


def test_missing_ticker_failure():
    try:
        calculate_buy_hold_backtest(
            {"AAA": _frame([100, 110, 120])},
            [{"symbol": "AAA", "weight": 50}, {"symbol": "BBB", "weight": 50}],
        )
    except ValueError as exc:
        assert "BBB" in str(exc)
    else:
        raise AssertionError("missing ticker did not fail")


def test_compare_alignment():
    result = calculate_buy_hold_backtest(
        {"AAA": _frame([100, 110, 120])},
        [{"symbol": "AAA", "weight": 100}],
        compare_frame=_frame([200, 220, 240, 260], start="2019-12-31"),
        compare_symbol="SPY",
    )
    compare_return = result["compare_return"]
    assert compare_return is not None
    assert round(float(compare_return.iloc[-1]), 4) == 18.1818


def _multiindex_frame(values, *, ticker_first: bool):
    frame = _frame(values)
    if ticker_first:
        frame.columns = pd.MultiIndex.from_tuples(
            [("LOW", column) for column in frame.columns],
            names=["Ticker", "Price"],
        )
    else:
        frame.columns = pd.MultiIndex.from_tuples(
            [(column, "LOW") for column in frame.columns],
            names=["Price", "Ticker"],
        )
    return frame


def test_low_ticker_multiindex_orientation():
    original_download = backtest_module.yf.download
    try:
        for ticker_first in (False, True):
            source = _multiindex_frame([100, 110, 120], ticker_first=ticker_first)
            backtest_module.yf.download = lambda *args, _source=source, **kwargs: _source.copy()
            frame = BacktestDataService().fetch_price_frame("LOW", interval="1d")
            assert not isinstance(frame.columns, pd.MultiIndex)
            assert list(frame.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
            series = price_series_from_frame(frame)
            assert list(series.astype(float)) == [100.0, 110.0, 120.0]
    finally:
        backtest_module.yf.download = original_download


def test_ambiguous_price_columns_failure():
    frame = pd.DataFrame(
        [[100.0, 101.0], [110.0, 111.0]],
        columns=["Adj Close", "Adj Close"],
        index=pd.date_range("2020-01-01", periods=2, freq="D"),
    )
    try:
        price_series_from_frame(frame)
    except ValueError as exc:
        assert "expected one column, found 2" in str(exc)
    else:
        raise AssertionError("ambiguous price columns did not fail")


if __name__ == "__main__":
    tests = [
        test_weight_normalization,
        test_buy_and_hold_return,
        test_common_date_alignment,
        test_missing_ticker_failure,
        test_compare_alignment,
        test_low_ticker_multiindex_orientation,
        test_ambiguous_price_columns_failure,
    ]
    for test in tests:
        test()
    print(f"backtest calculation tests passed ({len(tests)})")
