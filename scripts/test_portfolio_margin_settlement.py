from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.portfolio_presenters import margin_health_color_token
from budget_terminal_app.services.portfolio_analysis import margin_utilization, settle_trade


def test_buy_covered_by_cash() -> None:
    assert settle_trade(10000.0, 0.0, 4000.0) == (6000.0, 0.0)


def test_buy_overdraws_into_margin() -> None:
    assert settle_trade(1000.0, 0.0, 5000.0) == (0.0, 4000.0)


def test_buy_with_margin_already_open() -> None:
    assert settle_trade(0.0, 4000.0, 1000.0) == (0.0, 5000.0)


def test_sell_repays_margin_first() -> None:
    assert settle_trade(0.0, 4000.0, -1000.0) == (0.0, 3000.0)


def test_sell_exceeding_margin_credits_cash() -> None:
    assert settle_trade(0.0, 1000.0, -5000.0) == (4000.0, 0.0)


def test_zero_and_invalid_deltas_are_no_ops() -> None:
    assert settle_trade(500.0, 250.0, 0.0) == (500.0, 250.0)
    assert settle_trade(500.0, 250.0, None) == (500.0, 250.0)
    assert settle_trade(500.0, 250.0, float("nan")) == (500.0, 250.0)


def test_negative_balances_are_clamped() -> None:
    assert settle_trade(-100.0, -50.0, 200.0) == (0.0, 200.0)


def test_margin_utilization_percent() -> None:
    assert margin_utilization(9000.0, 1000.0, 2000.0) == 20.0
    assert abs(margin_utilization(15000.0, 0.0, 5000.0) - 33.3333333333) < 1e-6


def test_margin_utilization_none_cases() -> None:
    assert margin_utilization(0.0, 0.0, 500.0) is None
    assert margin_utilization(9000.0, 1000.0, 0.0) is None
    assert margin_utilization(9000.0, 1000.0, None) is None


def test_margin_health_bands() -> None:
    assert margin_health_color_token(None) == "text_muted"
    assert margin_health_color_token(0.0) == "text_muted"
    assert margin_health_color_token(14.9) == "accent_positive"
    assert margin_health_color_token(15.0) == "warning"
    assert margin_health_color_token(24.9) == "warning"
    assert margin_health_color_token(25.0) == "series_3"
    assert margin_health_color_token(40.0) == "series_3"
    assert margin_health_color_token(40.1) == "accent_negative"


def test_round_trip_restores_balances() -> None:
    cash, margin = settle_trade(10000.0, 0.0, 15000.0)
    assert (cash, margin) == (0.0, 5000.0)
    assert settle_trade(cash, margin, -15000.0) == (10000.0, 0.0)


def main() -> None:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"ok {name}")
    print("portfolio margin settlement checks passed")


if __name__ == "__main__":
    main()
