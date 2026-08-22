from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.portfolio_presenters import margin_health_color_token
from budget_terminal_app.services.portfolio_analysis import margin_utilization


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


def main() -> None:
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"ok {name}")
    print("portfolio margin utilization checks passed")


if __name__ == "__main__":
    main()
