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
    EQUITY_RISK_PREMIUM_PCT,
    MIN_GORDON_SPREAD_PCT,
    _fade_growth,
    _margin_of_safety_pct,
    _peer_exit_multiple,
    calculate_fair_value_details,
    calculate_fair_value_per_share,
    calculate_valuation_scenarios,
    derive_valuation_suggestions,
    estimate_required_return,
    normalize_valuation_assumptions,
)
from budget_terminal_app.workers.valuation import _analyst_estimates, _build_trends, _extract_metrics


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


def _grvy_info(**updates):
    """Yahoo's shape for a foreign listing: a USD quote over KRW statements.

    The numbers are the live 2026-08-21 GRVY (Gravity Co.) reading that exposed the defect:
    a $70.25 quote against a 10,040.58 KRW FCF/share.
    """
    info = {
        "symbol": "GRVY",
        "shortName": "Gravity Co Ltd",
        "currency": "USD",
        "financialCurrency": "KRW",
        "currentPrice": 70.25,
        "marketCap": 488_000_000.0,
        "sharesOutstanding": 1000.0,
        "freeCashflow": 10_040_580.0,
        "trailingEps": 12_000.0,
        "totalRevenue": 500_000_000.0,
        "ebitda": 100_000_000.0,
        "enterpriseValue": 400_000_000.0,
    }
    info.update(updates)
    return info


def _metrics_from_info(info):
    blank = pd.DataFrame()
    return _extract_metrics("GRVY", info, blank, blank, blank, blank, blank, blank, blank)


def test_currency_mismatch_detection() -> None:
    mismatched = _metrics_from_info(_grvy_info())
    assert mismatched["currency"] == "USD"
    assert mismatched["financial_currency"] == "KRW"
    assert mismatched["currency_mismatch"] is True
    # The quote price and the statement-derived basis are both reported, each in its own unit.
    _assert_close(mismatched["price"], 70.25, "quote price survives the mismatch")
    _assert_close(mismatched["fcf_per_share"], 10040.58, "reported FCF/share survives the mismatch")
    _assert_close(mismatched["basis_value"], 10040.58, "basis value is the reported FCF/share")
    # Every ratio that divides a quoted figure by a reported one is withheld instead.
    for key in ("pe", "ps", "ev_ebitda", "fcf_yield", "earnings_yield"):
        assert mismatched[key] is None, (key, mismatched[key])

    matched = _metrics_from_info(_grvy_info(financialCurrency="USD"))
    assert matched["currency_mismatch"] is False
    for key in ("pe", "ps", "ev_ebitda", "fcf_yield", "earnings_yield"):
        assert matched[key] is not None, key
    _assert_close(matched["pe"], 70.25 / 12_000.0, "P/E is computed once the units agree")

    # A missing financialCurrency is the ordinary US case and must not raise a warning by itself.
    silent = _metrics_from_info({key: value for key, value in _grvy_info().items() if key != "financialCurrency"})
    assert silent["currency_mismatch"] is False
    assert silent["financial_currency"] is None
    assert silent["pe"] is not None

    # Case alone is not a mismatch, but Yahoo's minor-unit spelling is: GBp is 1/100 of GBP.
    assert _metrics_from_info(_grvy_info(currency="usd", financialCurrency="USD"))["currency_mismatch"] is False
    assert _metrics_from_info(_grvy_info(currency="GBp", financialCurrency="GBP"))["currency_mismatch"] is True

    # A quoted market cap over reported net debt is not a leverage ratio; the premium is dropped.
    leveraged = {"beta": 1.0, "net_debt": 900.0, "market_cap": 1000.0, "free_cash_flow": 100.0}
    market = {"risk_free_rate": 4.0}
    assert any(
        item["factor"] == "Net debt / market cap"
        for item in estimate_required_return(leveraged, market)["adjustments"]
    )
    crossed = estimate_required_return({**leveraged, "currency_mismatch": True}, market)
    assert not any(item["factor"] == "Net debt / market cap" for item in crossed["adjustments"])
    assert any(item["factor"] == "Negative FCF" for item in estimate_required_return(
        {**leveraged, "currency_mismatch": True, "free_cash_flow": -1.0}, market
    )["adjustments"]), "a sign test survives the currency split"

    # Enterprise value is only derived from market cap plus reported debt when the units agree.
    derived_ok = _metrics_from_info(_grvy_info(financialCurrency="USD", enterpriseValue=None))
    assert derived_ok["enterprise_value"] is not None
    derived_blocked = _metrics_from_info(_grvy_info(enterpriseValue=None))
    assert derived_blocked["enterprise_value"] is None


def test_currency_mismatch_blocks_price_comparison() -> None:
    assumptions = _base(basis_value=10040.58)
    warning = "Price is quoted in USD but the statements report in KRW."

    comparable = calculate_valuation_scenarios(70.25, assumptions, history_points=4)
    assert comparable["price_comparison_valid"] is True
    # This is the defect in one line: a KRW fair value beside a USD price reads as a screaming buy.
    assert comparable["verdict"] == "Undervalued"
    assert comparable["buy_below"] is not None
    assert comparable["trim_above"] is not None

    blocked = calculate_valuation_scenarios(
        70.25,
        assumptions,
        history_points=4,
        blocking_warnings=[warning],
    )
    assert blocked["price_comparison_valid"] is False
    assert blocked["verdict"] is None
    assert blocked["buy_below"] is None
    assert blocked["trim_above"] is None
    assert blocked["upper_scenario"] is None
    assert all(row["upside_pct"] is None for row in blocked["scenarios"])
    assert warning in blocked["warnings"]
    assert blocked["blocking_warnings"] == [warning]
    assert blocked["model_quality"] == "Low"
    # The DCF is still solved; it is only the comparison against price that is withheld.
    _assert_close(
        blocked["base_fair_value"],
        comparable["base_fair_value"],
        "the fair value itself is unchanged by the block",
    )
    assert [row["fair_value"] for row in blocked["scenarios"]] == [
        row["fair_value"] for row in comparable["scenarios"]
    ]

    # Blank entries are not warnings and must not silently kill the verdict.
    assert calculate_valuation_scenarios(
        70.25, assumptions, history_points=4, blocking_warnings=["", "   "]
    )["verdict"] == "Undervalued"


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
    original_risk_free = valuation_worker.fetch_risk_free_snapshot
    valuation_worker.yf.Ticker = lambda _symbol: FakeTicker()
    valuation_worker.fetch_company_bundle = lambda _symbol: sec_bundle
    valuation_worker.fetch_risk_free_snapshot = lambda **_kwargs: None
    try:
        payload = valuation_worker.fetch_company_analysis_payload("TEST", include_peers=False)
    finally:
        valuation_worker.yf.Ticker = original_ticker
        valuation_worker.fetch_company_bundle = original_sec_fetch
        valuation_worker.fetch_risk_free_snapshot = original_risk_free
    assert payload["metrics"]["price"] == 123.0
    assert payload["metrics"]["forward_pe"] == 18.0
    assert payload["metrics"]["revenue"] == 100.0
    assert payload["financials"].loc["Total Revenue", columns[0]] == 90.0
    assert payload["financials"].loc["Yahoo Custom Row", columns[0]] == 42.0
    assert payload["statement_sources"]["primary"] == "SEC EDGAR"
    assert payload["valuation_provenance"]["Revenue"]["basis"] == "TTM from four complete quarters"
    assert payload["market_context"] is None
    assert payload["analyst_estimates"]["available"] is False
    assert payload["valuation_suggestions"]["fields"]["discount_rate"]["method"] == "heuristic"


def _derivation_metrics(**updates):
    metrics = {
        "ticker": "TEST",
        "revenue_growth": 8.0,
        "beta": 1.2,
        "free_cash_flow": 100.0,
        "net_debt": 0.0,
        "market_cap": 1_000_000_000_000.0,
        "basis_value": 10.0,
    }
    metrics.update(updates)
    return metrics


def _derivation_trends(**updates):
    trends = {
        "labels": ["2022", "2023", "2024", "2025"],
        "fcf_per_share": [2.0, 2.5, 3.0, 3.5],
        "revenue": [100.0, 110.0, 121.0, 133.1],
        "comparable_history_points": 4,
    }
    trends.update(updates)
    return trends


def test_capm_required_return() -> None:
    metrics = _derivation_metrics(beta=1.5)
    capm = estimate_required_return(metrics, {"risk_free_rate": 4.0, "as_of": "2026-08-20"})
    assert capm["method"] == "capm"
    # Blume: 0.67 * 1.5 + 0.33 = 1.335, and a trillion-dollar cap earns no size premium.
    _assert_close(capm["beta_adjusted"], 1.335, "adjusted beta", tolerance=1e-12)
    _assert_close(capm["value"], 4.0 + 1.335 * EQUITY_RISK_PREMIUM_PCT, "CAPM required return")
    factors = [row["factor"] for row in capm["adjustments"]]
    assert factors == ["Risk-free rate (10Y Treasury)", "Beta x equity risk premium"], factors
    assert capm["baseline"] == 4.0

    # Every add-on stacks on top of the CAPM core.
    loaded = estimate_required_return(
        _derivation_metrics(beta=1.5, free_cash_flow=-5.0, net_debt=6.0e11, market_cap=1.0e9),
        {"risk_free_rate": 4.0},
    )
    _assert_close(
        loaded["value"],
        4.0 + 1.335 * EQUITY_RISK_PREMIUM_PCT + 1.0 + 1.5 + 2.0,
        "CAPM with size, FCF, and leverage add-ons",
    )
    assert [row["factor"] for row in loaded["adjustments"]][2:] == [
        "Size premium",
        "Negative FCF",
        "Net debt / market cap",
    ]

    # Losing the market snapshot must reproduce the pre-CAPM heuristic exactly.
    fallback = estimate_required_return(metrics)
    assert fallback["method"] == "heuristic"
    _assert_close(fallback["value"], 10.0 + (1.5 - 1.0) * 2.0, "heuristic fallback required return")
    assert fallback["beta_adjusted"] is None
    assert "Heuristic" in fallback["caveat"]


def test_terminal_growth_never_breaks_gordon_spread() -> None:
    for risk_free in (0.0, 0.5, 2.0, 4.0, 6.0):
        for beta in (0.2, 1.0, 2.5):
            for breakeven in (0.5, 2.4, 4.0):
                market = {"risk_free_rate": risk_free, "breakeven_inflation": breakeven}
                bundle = derive_valuation_suggestions(
                    _derivation_metrics(beta=beta), _derivation_trends(), "FCF", market=market
                )
                derived = _base(**{
                    key: bundle["fields"][key]["value"]
                    for key in ("growth_1_5", "growth_6_10", "discount_rate", "terminal_growth", "margin_of_safety")
                })
                label = f"rf={risk_free} beta={beta} breakeven={breakeven}"
                spread = derived["discount_rate"] - derived["terminal_growth"]
                assert spread >= MIN_GORDON_SPREAD_PCT - 1e-9, f"{label}: base spread {spread}"

                result = calculate_valuation_scenarios(100.0, derived, history_points=4)
                for row in result["scenarios"]:
                    assert row["fair_value"] is not None, f"{label}: {row['name']} did not solve"
                assert result["scenarios_ordered"] is True, label
                assert not any("at least 1 percentage point" in text for text in result["warnings"]), label

                # Derivation must never emit a value the normalizer silently rewrites.
                assert normalize_valuation_assumptions(derived) == derived, label


def test_growth_fade_is_linear_average() -> None:
    _assert_close(_fade_growth(20.0, 2.5, 10), 0.4 * 20.0 + 0.6 * 2.5, "fade at N=10")
    _assert_close(_fade_growth(20.0, 2.5, 5), 2.5, "fade at N=5 has no stage-two tail")
    # The fade lands on terminal growth at year N, so at N=6 the only stage-two year is already there.
    _assert_close(_fade_growth(20.0, 2.5, 6), 2.5, "fade at N=6 is already terminal")
    _assert_close(_fade_growth(20.0, 2.5, 7), 20.0 + (2.5 - 20.0) * 0.75, "fade at N=7")
    for near in (-30.0, 0.0, 50.0):
        for terminal in (-2.0, 2.5, 5.0):
            for years in range(5, 16):
                value = _fade_growth(near, terminal, years)
                assert -15.0 <= value <= 30.0, (near, terminal, years, value)


def test_analyst_blend_weights() -> None:
    metrics = _derivation_metrics(revenue_growth=10.0)
    trends = _derivation_trends(labels=["2021", "2023", "2024", "2025"])  # kills both CAGRs

    def near(analyst):
        return derive_valuation_suggestions(metrics, trends, "FCF", analyst=analyst)["fields"]["growth_1_5"]["value"]

    _assert_close(near({"long_term_growth_pct": 20.0}), 0.6 * 20.0 + 0.4 * 10.0, "long-term blend")
    _assert_close(near({"next_year_growth_pct": 20.0}), 0.4 * 20.0 + 0.6 * 10.0, "next-year blend")
    _assert_close(near(None), 10.0, "history only")
    _assert_close(near({"long_term_growth_pct": 250.0}), 10.0, "absurd analyst growth is rejected")

    no_history = derive_valuation_suggestions(
        _derivation_metrics(revenue_growth=None), trends, "FCF", analyst={"long_term_growth_pct": 20.0}
    )
    _assert_close(no_history["fields"]["growth_1_5"]["value"], 20.0, "analyst only")


def test_peer_exit_multiple_selection() -> None:
    rows = [
        {"ticker": "TEST", "source": "Loaded", "fcf_yield": 1.0, "pe": 90.0},
        {"ticker": "AAA", "source": "Auto", "fcf_yield": 5.0, "pe": 20.0},
        {"ticker": "BBB", "source": "Auto", "fcf_yield": 4.0, "pe": None, "forward_pe": 25.0},
        {"ticker": "CCC", "source": "Auto", "fcf_yield": 10.0, "pe": 10.0},
        {"ticker": "DDD", "source": "Auto", "fcf_yield": 0.1, "pe": 1000.0},
    ]
    fcf = _peer_exit_multiple(rows, "FCF", "TEST")
    _assert_close(fcf["value"], 20.0, "median P/FCF")
    assert fcf["peer_count"] == 3
    assert [item["ticker"] for item in fcf["inputs"]] == ["AAA", "BBB", "CCC"]

    eps = _peer_exit_multiple(rows, "EPS", "TEST")
    _assert_close(eps["value"], 20.0, "median P/E with a forward fallback")
    assert [item["value"] for item in eps["inputs"]] == [20.0, 25.0, 10.0]

    assert _peer_exit_multiple(rows[:3], "FCF", "TEST") is None

    bundle = derive_valuation_suggestions(
        _derivation_metrics(), _derivation_trends(), "FCF", peer_rows=rows[:3]
    )
    _assert_close(bundle["fields"]["exit_multiple"]["value"], 15.0, "exit multiple falls back to the default")
    assert any("usable peer multiples" in text for text in bundle["caveats"])


def test_analyst_estimate_extraction() -> None:
    earnings = pd.DataFrame(
        {"growth": [0.1407, 0.1960], "numberOfAnalysts": [35, 33]},
        index=["0y", "+1y"],
    )
    # yfinance 1.5.2 labels the long-term row "LTG"; Yahoo leaves it empty for most tickers.
    populated = _analyst_estimates(earnings, pd.DataFrame({"stockTrend": [0.145]}, index=["LTG"]))
    _assert_close(populated["long_term_growth_pct"], 14.5, "LTG scaled to percent", tolerance=1e-9)
    _assert_close(populated["next_year_growth_pct"], 19.6, "+1y growth scaled to percent", tolerance=1e-9)
    assert populated["analyst_count"] == 33
    assert populated["available"] is True

    blank = _analyst_estimates(earnings, pd.DataFrame({"stockTrend": [float("nan")]}, index=["LTG"]))
    assert blank["long_term_growth_pct"] is None
    _assert_close(blank["next_year_growth_pct"], 19.6, "next-year carries the blend", tolerance=1e-9)

    legacy = _analyst_estimates(earnings, pd.DataFrame({"stockTrend": [0.145]}, index=["+5y"]))
    _assert_close(legacy["long_term_growth_pct"], 14.5, "legacy +5y label still read", tolerance=1e-9)

    missing = _analyst_estimates(None, None)
    assert missing["available"] is False
    assert missing["next_year_growth_pct"] is None


def test_margin_of_safety_scaling() -> None:
    best = _margin_of_safety_pct(
        basis_type="FCF", history_points=5, terminal_share=0.6, missing_inputs=[]
    )
    _assert_close(best["value"], 15.0, "fully supported margin of safety")

    worst = _margin_of_safety_pct(
        basis_type="EPS",
        history_points=2,
        terminal_share=0.9,
        missing_inputs=["risk-free rate", "analyst estimates", "peer multiples"],
    )
    _assert_close(worst["value"], 50.0, "worst-case margin of safety")

    unsolved = _margin_of_safety_pct(
        basis_type="FCF", history_points=5, terminal_share=None, missing_inputs=[]
    )
    _assert_close(unsolved["value"], 25.0, "an unsolved probe is treated as terminal-heavy")


def main() -> None:
    test_normalization_and_persistence_parity()
    test_gordon_oracle_and_components()
    test_exit_multiple_and_eps_models()
    test_validation_scenarios_and_verdicts()
    test_currency_mismatch_detection()
    test_currency_mismatch_blocks_price_comparison()
    test_monotonic_sensitivities()
    test_suggestion_quality_rules()
    test_ticker_specific_legacy_migration()
    test_sec_first_reported_metric_resolution()
    test_valuation_payload_reuses_sec_bundle()
    test_capm_required_return()
    test_terminal_growth_never_breaks_gordon_spread()
    test_growth_fade_is_linear_average()
    test_analyst_blend_weights()
    test_peer_exit_multiple_selection()
    test_analyst_estimate_extraction()
    test_margin_of_safety_scaling()
    assert math.isfinite(calculate_fair_value_per_share(_base()))
    print("valuation model tests passed")


if __name__ == "__main__":
    main()
