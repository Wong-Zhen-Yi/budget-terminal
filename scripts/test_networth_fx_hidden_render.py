"""Focused regression checks for deferred Personal Finance FX rendering."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.networth import NetWorthMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FxRenderHarness(NetWorthMixin):
    def __init__(self, *, dashboard_pending: bool = False) -> None:
        self.page6 = object()
        self.page_visible = False
        self.dashboard_pending = bool(dashboard_pending)
        self._p6_fx_loading = True
        self._p6_fx_render_dirty = False
        self._p6_progress_autoplay_done = True
        self._p6_usd_sgd_rate = None
        self._p6_fx_collected_at = None
        self._p6_fx_source = ""
        self._p6_fx_error = ""
        self.fx_label_calls = 0
        self.total_calls: list[bool] = []
        self.fetch_calls = 0

    def _is_current_page(self, page: Any) -> bool:
        return page is self.page6 and self.page_visible

    def _p6_refresh_fx_label(self) -> None:
        self.fx_label_calls += 1

    def _p6_update_total(self, *, force_progress_rebuild: bool = False) -> None:
        self.total_calls.append(bool(force_progress_rebuild))

    def _p6_refresh_fx_rate(self, *, force: bool = False) -> None:
        self.fetch_calls += 1

    def _dashboard_apply_pending_page_data(self, key: str) -> bool:
        _assert(key == "personal_finance", "on-show should request only Personal Finance data")
        if not self.dashboard_pending:
            return False
        self.dashboard_pending = False
        self._p6_update_total()
        return True


def _complete_fx(harness: _FxRenderHarness) -> None:
    harness._p6_on_fx_rate_result(
        {
            "ok": True,
            "usd_sgd": 1.3456,
            "source": "test-provider",
            "collected_at": 1_785_000_000.0,
        }
    )


def test_hidden_fx_completion_applies_once_on_show_without_refetch() -> None:
    harness = _FxRenderHarness()
    _complete_fx(harness)

    _assert(harness._p6_usd_sgd_rate == 1.3456, "hidden completion should cache the FX rate")
    _assert(harness._p6_fx_source == "test-provider", "hidden completion should cache provider metadata")
    _assert(harness._p6_fx_render_dirty, "hidden completion should retain one dirty render")
    _assert(harness.fx_label_calls == 0, "hidden completion must not touch the FX label")
    _assert(not harness.total_calls, "hidden completion must not rebuild totals, charts, silos, or goals")

    harness.page_visible = True
    harness._p6_on_show()
    _assert(harness.fx_label_calls == 1, "page show should apply the cached FX label once")
    _assert(harness.total_calls == [True], "page show should perform one complete FX-dependent render")
    _assert(not harness._p6_fx_render_dirty, "successful visible rendering should consume the dirty flag")
    _assert(harness.fetch_calls == 0, "applying a cached completion must not refetch FX")

    harness._p6_on_show()
    _assert(harness.fx_label_calls == 1, "a consumed FX completion must not render twice")
    _assert(harness.total_calls == [True], "a consumed FX completion must not rebuild totals twice")
    _assert(harness.fetch_calls == 0, "repeated page shows must remain network-free")


def test_dashboard_and_fx_pending_work_coalesce_to_one_total_render() -> None:
    harness = _FxRenderHarness(dashboard_pending=True)
    _complete_fx(harness)
    harness.page_visible = True
    harness._p6_on_show()

    _assert(harness.fx_label_calls == 1, "cached FX metadata should still update its label")
    _assert(harness.total_calls == [False], "dashboard and FX dirty state should share one totals render")
    _assert(not harness._p6_fx_render_dirty, "the shared render should consume the FX dirty flag")
    _assert(harness.fetch_calls == 0, "coalesced rendering must remain network-free")


def main() -> None:
    test_hidden_fx_completion_applies_once_on_show_without_refetch()
    test_dashboard_and_fx_pending_work_coalesce_to_one_total_render()
    print("Personal Finance hidden FX render smoke tests passed.")


if __name__ == "__main__":
    main()
