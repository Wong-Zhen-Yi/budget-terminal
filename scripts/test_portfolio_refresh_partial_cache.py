from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.portfolio_metrics import PortfolioMetricsMixin


class _PortfolioReturnProbe(PortfolioMetricsMixin):
    def __init__(self) -> None:
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self.active_portfolio_id = "other"
        self._active_return_timeframe = "1M"

    def _p4_returns_cache_key(self, timeframe_key, portfolio_id=None):
        return (str(portfolio_id or "main"), str(timeframe_key), ("AAA", "BBB"))


def test_pipeline_partial_returns_preserve_previous_symbols() -> None:
    probe = _PortfolioReturnProbe()
    key = ("main", "1M", ("AAA", "BBB"))
    probe._return_metrics_cache[key] = {"AAA": 1.0, "BBB": 2.0}
    context = SimpleNamespace(
        portfolio_id="main",
        return_timeframe="1M",
        included_tickers=("AAA", "BBB"),
    )
    probe._p4_cache_visible_dependency(context, ("returns", {"AAA": 3.0}))
    assert probe._return_metrics_cache[key] == {"AAA": 3.0, "BBB": 2.0}


def test_subtab_partial_returns_preserve_previous_symbols() -> None:
    probe = _PortfolioReturnProbe()
    key = ("main", "1M", ("AAA", "BBB"))
    probe._return_metrics_cache[key] = {"AAA": 1.0, "BBB": 2.0}
    probe._on_returns_ready("1M", "main", {"AAA": 4.0}, key)
    assert probe._return_metrics_cache[key] == {"AAA": 4.0, "BBB": 2.0}
    probe._on_returns_ready("1M", "main", {}, key)
    assert probe._return_metrics_cache[key] == {"AAA": 4.0, "BBB": 2.0}


if __name__ == "__main__":
    test_pipeline_partial_returns_preserve_previous_symbols()
    test_subtab_partial_returns_preserve_previous_symbols()
    print("Portfolio partial return cache tests passed.")
