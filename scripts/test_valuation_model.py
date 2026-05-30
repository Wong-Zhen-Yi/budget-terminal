from __future__ import annotations

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.valuation import (
    calculate_fair_value_per_share,
    calculate_valuation_scenarios,
    normalize_valuation_assumptions,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_close(actual: float | None, expected: float, message: str, *, tolerance: float = 1e-9) -> None:
    _assert(actual is not None, f"{message}: expected a number")
    _assert(abs(float(actual) - expected) <= tolerance, f"{message}: expected {expected}, got {actual}")


def test_normalization_bounds() -> None:
    values = normalize_valuation_assumptions({
        "basis_type": "bad",
        "basis_value": -50,
        "growth_1_5": 500,
        "growth_6_10": -500,
        "discount_rate": 0,
        "terminal_growth": 50,
        "exit_multiple": 0,
        "projection_years": 50,
        "margin_of_safety": 120,
    })
    _assert(values["basis_type"] == "FCF", "unsupported basis should fall back to FCF")
    _assert(values["basis_value"] == 0.0, "basis should be clamped non-negative")
    _assert(values["growth_1_5"] == 100.0, "near-term growth should be capped")
    _assert(values["growth_6_10"] == -50.0, "outer growth should be floored")
    _assert(values["discount_rate"] == 0.1, "discount rate should preserve a positive floor")
    _assert(values["terminal_growth"] == 20.0, "terminal growth should be capped")
    _assert(values["exit_multiple"] == 1.0, "exit multiple should preserve a positive floor")
    _assert(values["projection_years"] == 15, "projection years should be capped")
    _assert(values["margin_of_safety"] == 90.0, "margin of safety should be capped")


def test_scenarios_and_verdicts() -> None:
    assumptions = {
        "basis_type": "FCF",
        "basis_value": 10.0,
        "growth_1_5": 10.0,
        "growth_6_10": 5.0,
        "discount_rate": 10.0,
        "terminal_growth": 2.0,
        "exit_multiple": 15.0,
        "projection_years": 10,
        "margin_of_safety": 20.0,
    }
    base_value = calculate_fair_value_per_share(assumptions)
    _assert(base_value is not None and math.isfinite(base_value), "base value should be finite")

    scenarios = calculate_valuation_scenarios(base_value * 0.75, assumptions)
    values = [row["fair_value"] for row in scenarios["scenarios"]]
    _assert(values[0] < values[1] < values[2], "bear/base/bull values should be ordered")
    _assert_close(scenarios["base_fair_value"], base_value, "base scenario should match standalone model")
    _assert_close(scenarios["buy_below"], base_value * 0.8, "buy-below band should use margin of safety")
    _assert_close(scenarios["trim_above"], base_value * 1.2, "trim-above band should use margin of safety")
    _assert(scenarios["verdict"] == "Undervalued", "price below buy-below band should be undervalued")

    fair = calculate_valuation_scenarios(base_value, assumptions)
    _assert(fair["verdict"] == "Fairly valued", "price inside band should be fairly valued")
    expensive = calculate_valuation_scenarios(base_value * 1.25, assumptions)
    _assert(expensive["verdict"] == "Overvalued", "price above trim band should be overvalued")


def test_missing_basis_is_uncertain() -> None:
    scenarios = calculate_valuation_scenarios(100.0, {"basis_value": 0})
    _assert(scenarios["base_fair_value"] is None, "missing basis should not produce fair value")
    _assert(scenarios["verdict"] == "Too uncertain", "missing basis should be too uncertain")


def main() -> None:
    test_normalization_bounds()
    test_scenarios_and_verdicts()
    test_missing_basis_is_uncertain()
    print("valuation model tests passed")


if __name__ == "__main__":
    main()
