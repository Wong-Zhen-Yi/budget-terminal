from __future__ import annotations

import math
import sys
from pathlib import Path

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


def main() -> None:
    test_normalization_and_persistence_parity()
    test_gordon_oracle_and_components()
    test_exit_multiple_and_eps_models()
    test_validation_scenarios_and_verdicts()
    test_monotonic_sensitivities()
    test_suggestion_quality_rules()
    test_ticker_specific_legacy_migration()
    assert math.isfinite(calculate_fair_value_per_share(_base()))
    print("valuation model tests passed")


if __name__ == "__main__":
    main()
