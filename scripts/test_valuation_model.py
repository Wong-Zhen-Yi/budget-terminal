from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.persistence import (
    _normalize_valuation_assumptions as normalize_persisted_assumptions,
    _normalize_valuation_page_settings,
)
from budget_terminal_app.services.valuation import (
    calculate_fair_value_details,
    calculate_fair_value_per_share,
    calculate_valuation_scenarios,
    derive_valuation_suggestions,
    normalize_valuation_assumptions,
)
from budget_terminal_app.workers.valuation import _build_trends, _extract_metrics


def _assert_close(actual: float | None, expected: float, message: str, *, tolerance: float = 1e-9) -> None:
    if actual is None or abs(float(actual) - expected) > tolerance:
        raise AssertionError(f"{message}: expected {expected}, got {actual}")


def _base(**updates):
    values = {
        "basis_type": "FCF",
        "terminal_method": "gordon_growth",
        "basis_value": 10.0,
        "growth_1_5": 10.0,
        "growth_6_10": 5.0,
        "discount_rate": 10.0,
        "terminal_growth": 2.5,
        "exit_multiple": 15.0,
        "projection_years": 10,
        "margin_of_safety": 20.0,
    }
    values.update(updates)
    return values


def _manual_projection(values):
    current = values["basis_value"]
    projected = []
    for year in range(1, values["projection_years"] + 1):
        growth = values["growth_1_5"] if year <= 5 else values["growth_6_10"]
        current *= 1.0 + growth / 100.0
        projected.append(current)
    return projected


def test_normalization_and_persistence_parity() -> None:
    raw = {
        "basis_type": "bad",
        "terminal_method": "bad",
        "basis_value": -50,
        "growth_1_5": 500,
        "growth_6_10": -500,
        "discount_rate": 0,
        "terminal_growth": 50,
        "exit_multiple": 0,
        "projection_years": 2,
        "margin_of_safety": 120,
    }
    expected = {
        "basis_type": "FCF",
        "basis_value": 0.0,
        "growth_1_5": 50.0,
        "growth_6_10": -15.0,
        "discount_rate": 4.0,
        "terminal_method": "gordon_growth",
        "terminal_growth": 5.0,
        "exit_multiple": 3.0,
        "projection_years": 5,
        "margin_of_safety": 50.0,
    }
    assert normalize_valuation_assumptions(raw) == expected
    assert normalize_persisted_assumptions(raw) == expected


def test_gordon_oracle_and_components() -> None:
    values = _base()
    projected = _manual_projection(values)
    rate = values["discount_rate"] / 100.0
    explicit = sum(value / ((1.0 + rate) ** year) for year, value in enumerate(projected, 1))
    terminal_value = projected[-1] * (1.0 + values["terminal_growth"] / 100.0) / (
        rate - values["terminal_growth"] / 100.0
    )
    terminal_pv = terminal_value / ((1.0 + rate) ** values["projection_years"])
    details = calculate_fair_value_details(values)
    _assert_close(details["explicit_forecast_pv"], explicit, "explicit forecast PV")
    _assert_close(details["terminal_pv"], terminal_pv, "terminal PV")
    _assert_close(details["fair_value"], explicit + terminal_pv, "Gordon fair value")
    _assert_close(details["terminal_value_share"], terminal_pv / (explicit + terminal_pv), "terminal share")


def test_exit_multiple_and_eps_models() -> None:
    exit_values = _base(terminal_method="exit_multiple")
    projected = _manual_projection(exit_values)
    rate = exit_values["discount_rate"] / 100.0
    explicit = sum(value / ((1.0 + rate) ** year) for year, value in enumerate(projected, 1))
    terminal = projected[-1] * exit_values["exit_multiple"] / ((1.0 + rate) ** exit_values["projection_years"])
    _assert_close(calculate_fair_value_per_share(exit_values), explicit + terminal, "exit-multiple DCF")
    unchanged = calculate_fair_value_per_share({**exit_values, "terminal_growth": -2.0})
    _assert_close(unchanged, explicit + terminal, "exit method must ignore terminal growth")

    eps_values = _base(basis_type="EPS", terminal_method="gordon_growth", basis_value=3.0)
    eps_n = _manual_projection(eps_values)[-1]
    expected = eps_n * eps_values["exit_multiple"] / ((1.0 + rate) ** eps_values["projection_years"])
    details = calculate_fair_value_details(eps_values)
    _assert_close(details["explicit_forecast_pv"], 0.0, "EPS must not sum annual earnings")
    _assert_close(details["fair_value"], expected, "EPS terminal-multiple value")
    assert details["method"] == "earnings_multiple"


def test_validation_scenarios_and_verdicts() -> None:
    invalid = calculate_fair_value_details(_base(discount_rate=4.0, terminal_growth=3.5))
    assert invalid["fair_value"] is None
    assert any("at least 1 percentage point" in warning for warning in invalid["warnings"])
    assert calculate_fair_value_details(_base(basis_value=float("nan")))["fair_value"] is None

    assumptions = _base(growth_1_5=-10.0, growth_6_10=-5.0, terminal_method="exit_multiple")
    model = calculate_valuation_scenarios(None, assumptions, history_points=4)
    fair_values = [row["fair_value"] for row in model["scenarios"]]
    assert fair_values[0] < fair_values[1] < fair_values[2]
    assert model["scenarios_ordered"] is True
    assert model["verdict"] is None
    assert model["base_fair_value"] is not None

    base_value = model["base_fair_value"]
    bull_value = model["upper_scenario"]
    buy_below = model["buy_below"]
    assert calculate_valuation_scenarios(buy_below - 0.01, assumptions, history_points=4)["verdict"] == "Undervalued"
    assert calculate_valuation_scenarios(buy_below, assumptions, history_points=4)["verdict"] == "Fairly valued"
    assert calculate_valuation_scenarios(bull_value + 0.01, assumptions, history_points=4)["verdict"] == "Overvalued"
    assert calculate_valuation_scenarios(base_value, assumptions, history_points=4)["verdict"] == "Fairly valued"

    warned = calculate_valuation_scenarios(
        base_value,
        assumptions,
        history_points=4,
        material_warnings=["Approximate history"],
    )
    assert warned["verdict"] == "Fairly valued"
    assert warned["model_quality"] == "Low"


def test_monotonic_sensitivities() -> None:
    base = calculate_fair_value_per_share(_base())
    assert calculate_fair_value_per_share(_base(basis_value=11.0)) > base
    assert calculate_fair_value_per_share(_base(growth_1_5=11.0)) > base
    assert calculate_fair_value_per_share(_base(discount_rate=11.0)) < base
    exit_base = calculate_fair_value_per_share(_base(terminal_method="exit_multiple"))
    assert calculate_fair_value_per_share(_base(terminal_method="exit_multiple", exit_multiple=16.0)) > exit_base


def test_suggestion_quality_rules() -> None:
    metrics = {"revenue_growth": 8.0, "beta": 1.2, "free_cash_flow": 100.0, "net_debt": 0.0, "market_cap": 1000.0}
    trends = {
        "labels": ["2022", "2023", "2024", "2025"],
        "fcf_per_share": [2.0, -1.0, 3.0, 4.0],
        "revenue": [100.0, 110.0, 121.0, 133.1],
    }
    suggestions = derive_valuation_suggestions(metrics, trends, "FCF")
    source = suggestions["fields"]["growth_1_5"]["source"]
    assert "FCF CAGR" not in source
    assert "revenue CAGR" in source
    assert suggestions["fields"]["terminal_growth"]["value"] == 2.5
    assert "Heuristic" in suggestions["fields"]["discount_rate"]["caveat"]

    nonconsecutive = {**trends, "labels": ["2021", "2023", "2024", "2025"], "revenue": [100.0, 110.0, 121.0, 133.1]}
    source = derive_valuation_suggestions(metrics, nonconsecutive, "FCF")["fields"]["growth_1_5"]["source"]
    assert "3-year revenue CAGR" not in source


def test_ticker_specific_legacy_migration() -> None:
    migrated = _normalize_valuation_page_settings({
        "last_ticker": "msft",
        "assumptions": _base(basis_value=7.0),
    })
    assert migrated["last_ticker"] == "MSFT"
    assert migrated["assumptions_by_ticker"]["MSFT"]["basis_value"] == 7.0
    assert migrated["assumptions"] == migrated["assumptions_by_ticker"]["MSFT"]

    isolated = _normalize_valuation_page_settings({
        "last_ticker": "AAPL",
        "assumptions": _base(basis_value=99.0),
        "assumptions_by_ticker": {
            "MSFT": _base(basis_value=7.0),
            "AAPL": _base(basis_value=4.0, terminal_method="exit_multiple"),
        },
    })
    assert isolated["assumptions"]["basis_value"] == 4.0
    assert isolated["assumptions_by_ticker"]["MSFT"]["basis_value"] == 7.0


def test_sec_first_reported_metric_resolution() -> None:
    quarters = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    quarterly_financials = pd.DataFrame(
        {
            quarter: values
            for quarter, values in zip(
                quarters,
                ([40.0, 4.0, 1.0], [30.0, 3.0, 1.0], [20.0, 2.0, 1.0], [10.0, 1.0, 1.0]),
            )
        },
        index=["Total Revenue", "Net Income", "Diluted EPS"],
    )
    quarterly_cashflow = pd.DataFrame(
        {
            quarter: values
            for quarter, values in zip(
                quarters,
                ([12.0, 2.0, 10.0], [11.0, 2.0, 9.0], [10.0, 2.0, 8.0], [9.0, 2.0, 7.0]),
            )
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
    )
    quarterly_balance_sheet = pd.DataFrame(
        {quarters[0]: [50.0, 20.0, 5.0]},
        index=[
            "Cash Cash Equivalents And Short Term Investments",
            "Total Debt",
            "Common Stock Shares Outstanding",
        ],
    )
    annual_financials = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [999.0, 99.0]},
        index=["Total Revenue", "Net Income"],
    )
    annual_cashflow = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [100.0, 25.0]},
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    info = {
        "currentPrice": 123.0,
        "marketCap": 1_000.0,
        "totalRevenue": 777.0,
        "netIncome": 77.0,
        "operatingCashflow": 70.0,
        "freeCashflow": 60.0,
        "sharesOutstanding": 9.0,
        "totalCash": 80.0,
        "totalDebt": 70.0,
        "trailingEps": 8.0,
        "forwardPE": 18.0,
    }
    sec_metrics = _extract_metrics(
        "TEST",
        info,
        annual_financials,
        annual_cashflow,
        pd.DataFrame(),
        quarterly_financials,
        quarterly_cashflow,
        quarterly_balance_sheet,
        pd.DataFrame(),
        prefer_statements=True,
    )
    assert sec_metrics["price"] == 123.0
    assert sec_metrics["forward_pe"] == 18.0
    assert sec_metrics["revenue"] == 100.0
    assert sec_metrics["net_income"] == 10.0
    assert sec_metrics["operating_cash_flow"] == 42.0
    assert sec_metrics["free_cash_flow"] == 34.0
    assert sec_metrics["shares"] == 5.0
    assert sec_metrics["cash"] == 50.0
    assert sec_metrics["debt"] == 20.0
    assert sec_metrics["eps"] == 4.0

    annual_fallback = _extract_metrics(
        "TEST",
        info,
        annual_financials,
        annual_cashflow,
        pd.DataFrame(),
        quarterly_financials.iloc[:, :3],
        quarterly_cashflow.iloc[:, :3],
        quarterly_balance_sheet,
        pd.DataFrame(),
        prefer_statements=True,
    )
    assert annual_fallback["revenue"] == 999.0
    assert annual_fallback["operating_cash_flow"] == 100.0

    ascending_dates = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
    ascending_financials = pd.DataFrame(
        {ascending_dates[0]: [300.0], ascending_dates[1]: [400.0]},
        index=["Total Revenue"],
    )
    ascending_balance = pd.DataFrame(
        {ascending_dates[0]: [30.0, 10.0], ascending_dates[1]: [50.0, 20.0]},
        index=["Cash Cash Equivalents And Short Term Investments", "Total Debt"],
    )
    latest_metrics = _extract_metrics(
        "TEST",
        info,
        ascending_financials,
        pd.DataFrame(),
        ascending_balance,
        pd.DataFrame(),
        pd.DataFrame(),
        ascending_balance,
        pd.DataFrame(),
        prefer_statements=True,
    )
    assert latest_metrics["revenue"] == 400.0
    assert latest_metrics["cash"] == 50.0
    assert latest_metrics["debt"] == 20.0

    trend_cashflow = pd.DataFrame(
        {ascending_dates[1]: [100.0, 20.0], ascending_dates[0]: [90.0, 15.0]},
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    trend_financials = pd.DataFrame(
        {ascending_dates[1]: [200.0], ascending_dates[0]: [180.0]},
        index=["Total Revenue"],
    )
    trends = _build_trends(trend_financials, trend_cashflow, {"shares": 10.0, "basis_type": "FCF"})
    assert trends["fcf"] == [75.0, 80.0]

    yahoo_metrics = _extract_metrics(
        "TEST",
        info,
        annual_financials,
        annual_cashflow,
        pd.DataFrame(),
        quarterly_financials.iloc[:, :3],
        quarterly_cashflow.iloc[:, :3],
        pd.DataFrame(),
        pd.DataFrame(),
        prefer_statements=False,
    )
    assert yahoo_metrics["revenue"] == 777.0
    assert yahoo_metrics["free_cash_flow"] == 60.0
    assert yahoo_metrics["cash"] == 80.0


def test_valuation_payload_reuses_sec_bundle() -> None:
    from budget_terminal_app.workers import valuation as valuation_worker

    columns = [
        pd.Timestamp("2024-12-31"),
        pd.Timestamp("2024-09-30"),
        pd.Timestamp("2024-06-30"),
        pd.Timestamp("2024-03-31"),
    ]
    sec_financials = pd.DataFrame(
        {column: [value] for column, value in zip(columns, (40.0, 30.0, 20.0, 10.0))},
        index=["Total Revenue"],
    )
    sec_cashflow = pd.DataFrame(
        {column: values for column, values in zip(columns, ([12.0, 2.0], [11.0, 2.0], [10.0, 2.0], [9.0, 2.0]))},
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    annual = pd.DataFrame({columns[0]: [90.0]}, index=["Total Revenue"])
    yahoo_financials = pd.DataFrame(
        {columns[0]: [777.0, 42.0]},
        index=["Total Revenue", "Yahoo Custom Row"],
    )

    class FakeTicker:
        info = {
            "currentPrice": 123.0,
            "previousClose": 120.0,
            "marketCap": 1_000.0,
            "totalRevenue": 777.0,
            "sharesOutstanding": 5.0,
            "forwardPE": 18.0,
        }
        financials = yahoo_financials
        cashflow = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        quarterly_financials = pd.DataFrame()
        quarterly_cashflow = pd.DataFrame()
        quarterly_balance_sheet = pd.DataFrame()

        def history(self, **_kwargs):
            return pd.DataFrame({"Close": [120.0, 123.0]})

    sec_bundle = {
        "available": True,
        "statements_available": True,
        "freshness": "cached",
        "frames": {
            "financials": annual,
            "quarterly_financials": sec_financials,
            "cashflow": pd.DataFrame(),
            "quarterly_cashflow": sec_cashflow,
            "balance_sheet": pd.DataFrame(),
            "quarterly_balance_sheet": pd.DataFrame(),
        },
        "filings": [],
        "warnings": [],
        "provenance": {
            "Total Revenue": {
                "annual": {"2024-12-31": {"tag": "Revenues", "accession": "annual"}},
                "quarterly": {
                    str(column.date()): {"tag": "Revenues", "accession": f"q{index}"}
                    for index, column in enumerate(reversed(columns), 1)
                },
            }
        },
    }
    original_ticker = valuation_worker.yf.Ticker
    original_sec_fetch = valuation_worker.fetch_company_bundle
    valuation_worker.yf.Ticker = lambda _symbol: FakeTicker()
    valuation_worker.fetch_company_bundle = lambda _symbol: sec_bundle
    try:
        payload = valuation_worker.fetch_company_analysis_payload("TEST", include_peers=False)
    finally:
        valuation_worker.yf.Ticker = original_ticker
        valuation_worker.fetch_company_bundle = original_sec_fetch
    assert payload["metrics"]["price"] == 123.0
    assert payload["metrics"]["forward_pe"] == 18.0
    assert payload["metrics"]["revenue"] == 100.0
    assert payload["financials"].loc["Total Revenue", columns[0]] == 90.0
    assert payload["financials"].loc["Yahoo Custom Row", columns[0]] == 42.0
    assert payload["statement_sources"]["primary"] == "SEC EDGAR"
    assert payload["valuation_provenance"]["Revenue"]["basis"] == "TTM from four complete quarters"


def main() -> None:
    test_normalization_and_persistence_parity()
    test_gordon_oracle_and_components()
    test_exit_multiple_and_eps_models()
    test_validation_scenarios_and_verdicts()
    test_monotonic_sensitivities()
    test_suggestion_quality_rules()
    test_ticker_specific_legacy_migration()
    test_sec_first_reported_metric_resolution()
    test_valuation_payload_reuses_sec_bundle()
    assert math.isfinite(calculate_fair_value_per_share(_base()))
    print("valuation model tests passed")


if __name__ == "__main__":
    main()
