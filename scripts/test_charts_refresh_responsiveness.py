from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.charts_page import (
    P10_MULTI_INTERVAL_MAX_WORKERS,
    ChartsPageMixin,
)
from budget_terminal_app.services.refresh_control import RefreshCoordinator


class _MultiIntervalProbe(ChartsPageMixin):
    def __init__(self) -> None:
        self.p10_symbol = "AAPL"
        self.p10_multi_interval_labels = ["1 Day", "1 Week"]
        self._p10_multi_interval_request_token = 4
        self._p10_multi_interval_pending_labels = {"1 Day", "1 Week"}
        self._p10_multi_interval_failed_labels = {}
        self._p10_multi_interval_cache = {}
        self._refresh_coordinator = RefreshCoordinator()
        self.request_token, _ = self._refresh_coordinator.request(
            ("charts", "multiintervals"),
            ("AAPL", ("1 Day", "1 Week"), True),
        )
        self._p10_multi_interval_refresh_contexts = {
            self.request_token.generation: {
                "symbol": "AAPL",
                "labels": ("1 Day", "1 Week"),
                "force": True,
            }
        }
        self.finalized: list[tuple[int, str]] = []
        self.statuses: list[str] = []

    def _p10_set_multi_interval_status(self, text, _status="muted") -> None:
        self.statuses.append(str(text))

    def _p10_finalize_multi_interval_request(self, request_token, symbol: str) -> None:
        self.finalized.append((request_token.generation, symbol))


class _HiddenFinalizeProbe(ChartsPageMixin):
    def __init__(self) -> None:
        self.p10_symbol = "AAPL"
        self.p10_multi_interval_labels = ["1 Day"]
        self._p10_multi_interval_finalized_request_token = None
        self._p10_multi_interval_failed_labels = {}
        self._p10_multi_interval_cache = {}
        self.page10 = object()
        self._refresh_coordinator = RefreshCoordinator()
        self.request_token, _ = self._refresh_coordinator.request(
            ("charts", "multiintervals"),
            ("AAPL", ("1 Day",), True),
        )
        self._p10_multi_interval_refresh_contexts = {
            self.request_token.generation: {
                "symbol": "AAPL",
                "labels": ("1 Day",),
                "force": True,
            }
        }

    def _p10_build_multi_interval_indicator_frame(self, *_args):
        return None

    def _is_current_page(self, _page) -> bool:
        return False

    def _p10_active_subtab_key(self) -> str:
        return "multiintervals"


def test_multi_interval_fetch_is_bounded_and_coalesced() -> None:
    assert P10_MULTI_INTERVAL_MAX_WORKERS == 2
    probe = _MultiIntervalProbe()

    ChartsPageMixin._p10_apply_multi_interval_payload(probe, probe.request_token, "AAPL", "1 Day", {"rsi": [1]})
    assert probe.finalized == []
    ChartsPageMixin._p10_apply_multi_interval_payload(probe, probe.request_token, "AAPL", "1 Week", {"rsi": [2]})
    assert probe.finalized == [(probe.request_token.generation, "AAPL")]


def test_completed_hidden_generation_is_dirty_and_finalized_once() -> None:
    probe = _HiddenFinalizeProbe()
    ChartsPageMixin._p10_finalize_multi_interval_request(probe, probe.request_token, "AAPL")
    assert probe._p10_multi_interval_dirty is True
    assert probe._p10_multi_interval_finalized_request_token == probe.request_token.generation

    probe._p10_multi_interval_dirty = False
    ChartsPageMixin._p10_finalize_multi_interval_request(probe, probe.request_token, "AAPL")
    assert probe._p10_multi_interval_dirty is False


if __name__ == "__main__":
    test_multi_interval_fetch_is_bounded_and_coalesced()
    test_completed_hidden_generation_is_dirty_and_finalized_once()
    print("Charts refresh responsiveness smoke tests passed.")
