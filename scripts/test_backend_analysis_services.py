from __future__ import annotations

import datetime
import math
import sys
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from budget_terminal_app.services.dashboard_payloads import (
    dedupe_symbols,
    extract_close_series,
    normalize_chart_configs,
    price_payload,
)
from budget_terminal_app.services.fiscal_periods import fiscal_year, safe_year
from budget_terminal_app.services.news_analysis import dedupe_articles, mentions_blocked_ticker
from budget_terminal_app.services.options_analysis import (
    calculate_greeks,
    extract_dividend_yield,
    implied_volatility,
)
from budget_terminal_app.services.portfolio_analysis import filtered_summary, filtered_weights, returns_cache_key
from budget_terminal_app.services.technical_analysis import (
    calculate_atr,
    calculate_macd,
    calculate_mfi,
    calculate_rsi,
    calculate_true_range,
)


def test_dashboard_payload_helpers() -> None:
    assert normalize_chart_configs({"symbol": "SPY", "period": "1y", "interval": "1d"}) == [
        ("SPY", "1y", "1d")
    ]
    assert dedupe_symbols(["SPY", "QQQ"], ["SPY", "GLD"]) == ["SPY", "QQQ", "GLD"]
    index = pd.date_range("2026-01-01", periods=2)
    columns = pd.MultiIndex.from_product([["SPY"], ["Close", "Open"]])
    frame = pd.DataFrame([[100, 99], [105, 101]], index=index, columns=columns)
    close = extract_close_series(frame, ["SPY"], "SPY")
    assert list(close) == [100, 105]
    assert price_payload(close) == {"price": 105.0, "change": 5.0, "abs_change": 5.0}


def test_news_helpers() -> None:
    existing = [{"title": "Same", "url": "https://example.test/a", "ticker": "AAPL"}]
    articles = [
        {"title": "Duplicate", "url": "https://example.test/a", "ticker": "AAPL"},
        {"title": "New", "url": "https://example.test/b", "ticker": "MSFT"},
    ]
    assert dedupe_articles(articles, existing) == [articles[1]]
    assert mentions_blocked_ticker({"title": "AAPL rallies", "ticker": "OTHER"}, {"AAPL"})
    assert not mentions_blocked_ticker({"title": "Markets rally", "ticker": "MSFT"}, {"AAPL"})


def test_technical_indicators() -> None:
    closes = pd.Series(range(1, 50), dtype=float)
    rsi = calculate_rsi(closes)
    assert len(rsi) == len(closes)
    assert rsi.dropna().between(0, 100).all()
    macd, signal, histogram = calculate_macd(closes)
    pd.testing.assert_series_equal(histogram, macd - signal)
    frame = pd.DataFrame(
        {
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": pd.Series([1_000.0] * len(closes)),
        }
    )
    assert calculate_mfi(frame).dropna().between(0, 100).all()

    # True range spans the wider of the bar and the gap from the previous close.
    true_range = calculate_true_range(frame)
    assert pd.isna(true_range.iloc[0]) or true_range.iloc[0] == 2.0
    assert float(true_range.iloc[-1]) == 2.0
    atr = calculate_atr(frame, period=14)
    assert len(atr) == len(closes)
    # No back-fill: the warm-up window stays empty rather than borrowing a later reading.
    assert atr.iloc[:13].isna().all()
    assert float(atr.iloc[-1]) > 0.0
    assert calculate_atr(pd.DataFrame(), period=14).empty
    assert calculate_true_range(frame.drop(columns=["High"])).isna().all()


def _black_scholes_call(spot: float, strike: float, years: float, rate: float, volatility: float) -> float:
    normal = NormalDist()
    denominator = volatility * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * years) / denominator
    d2 = d1 - denominator
    return spot * normal.cdf(d1) - strike * math.exp(-rate * years) * normal.cdf(d2)


def test_option_analysis() -> None:
    today = datetime.date(2026, 1, 1)
    expiry = "2027-01-01"
    market_price = _black_scholes_call(100, 100, 1.0, 0.04, 0.25)
    volatility = implied_volatility(100, 100, expiry, 0.04, 0.0, market_price, "call", today=today)
    assert abs(volatility - 0.25) < 0.001
    call = calculate_greeks(100, 100, expiry, 0.25, "call", 0.04, 0.0, today=today)
    put = calculate_greeks(100, 100, expiry, 0.25, "put", 0.04, 0.0, today=today)
    assert call["greeks_valid"] and put["greeks_valid"]
    assert 0 < call["delta_calc"] < 1
    assert -1 < put["delta_calc"] < 0
    assert extract_dividend_yield({"dividendYield": 2.5}) == 0.025


def test_portfolio_analysis() -> None:
    metrics = {
        "AAPL": {"market_value": 60, "dollar_gain": 5},
        "MSFT": {"market_value": 40, "dollar_gain": -2},
    }
    weights, total = filtered_weights(metrics, ["AAPL"], 40)
    assert total == 100
    assert weights == {"AAPL": 60.0, "CASH": 40.0}
    assert filtered_summary(metrics, ["AAPL"], 40) == {
        "checked_stock_value": 60.0,
        "checked_stock_pnl": 5.0,
        "filtered_total": 100.0,
    }
    assert filtered_summary(metrics, ["AAPL"], 40, 25) == {
        "checked_stock_value": 60.0,
        "checked_stock_pnl": 5.0,
        "filtered_total": 75.0,
    }
    assert returns_cache_key("main", "1y", ["msft", "AAPL"]) == ("main", "1y", ("AAPL", "MSFT"))


def test_fiscal_periods() -> None:
    assert safe_year("FY 2026") == 2026
    assert fiscal_year(datetime.date(2024, 4, 1), 1) == 2025
    assert fiscal_year(datetime.date(2024, 1, 31), 1) == 2024
    assert fiscal_year(datetime.date(2024, 6, 30), 12) == 2024


if __name__ == "__main__":
    test_dashboard_payload_helpers()
    test_news_helpers()
    test_technical_indicators()
    test_option_analysis()
    test_portfolio_analysis()
    test_fiscal_periods()
    print("backend analysis service tests passed")
