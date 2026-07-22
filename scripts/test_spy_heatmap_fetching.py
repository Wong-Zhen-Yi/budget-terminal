from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.spy_heatmap import SpyHeatmapMixin
from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin


class _DeferredExecutor:
    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def submit(self, fn: Any) -> object:
        self.tasks.append(fn)
        return object()


class _RequestProbe(SpyHeatmapMixin):
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str | None]] = []

    def _p17_request_refresh(self, *, force: bool = False, symbol: Any = None) -> bool:
        self.calls.append((force, symbol))
        return True


class _RefreshProbe(SpyHeatmapMixin):
    def __init__(self) -> None:
        self._p17_etf_symbol = "SPY"
        self._p17_fetching_symbols: set[str] = set()
        self._p17_fetch_futures: dict[str, Any] = {}
        self._p17_last_fetch_by_etf: dict[str, float] = {}
        self._p17_results: dict[str, Any] = {}
        self._p17_fetch_executor = _DeferredExecutor()
        self.p17_status_lbl = object()
        self.render_count = 0

    def set_status_text(self, label: Any, text: str, *, status: str = "muted") -> None:
        return None

    def _p17_update_refresh_state(self) -> None:
        return None

    def _p17_render_interval_result(self, *, reset_view: bool = False) -> None:
        self.render_count += 1


class _LifecycleProbe(WindowLifecycleMixin):
    def __init__(self) -> None:
        self.initialized: list[int] = []
        self.calls: list[tuple[str, str | None]] = []

    def _startup_work_can_run(self) -> bool:
        return True

    def _page_label(self, page_index: Any) -> str:
        return "Heatmap"

    def _ensure_page_initialized(self, page_index: int) -> None:
        self.initialized.append(page_index)

    def _call_if_page_initialized(
        self,
        method_name: str,
        *,
        page_attr: str | None = None,
        status_text: str | None = None,
    ) -> None:
        self.calls.append((method_name, page_attr))


def test_request_all_etfs_uses_shared_fetch_path() -> None:
    probe = _RequestProbe()

    scheduled = probe._p17_request_all_etfs()

    assert scheduled == ("SPY", "NDX", "DJI")
    assert probe.calls == [(False, "SPY"), (False, "NDX"), (False, "DJI")]


def test_request_all_etfs_preserves_force_flag() -> None:
    probe = _RequestProbe()

    probe._p17_request_all_etfs(force=True)

    assert probe.calls == [(True, "SPY"), (True, "NDX"), (True, "DJI")]


def test_repeated_load_waves_use_inflight_and_fresh_cache_guards() -> None:
    probe = _RefreshProbe()

    first = probe._p17_request_all_etfs()
    repeated_while_fetching = probe._p17_request_all_etfs()

    assert first == ("SPY", "NDX", "DJI")
    assert repeated_while_fetching == ()
    assert len(probe._p17_fetch_executor.tasks) == 3

    probe._p17_fetching_symbols.clear()
    now = datetime.datetime.now().timestamp()
    probe._p17_results = {symbol: object() for symbol in ("SPY", "NDX", "DJI")}
    probe._p17_last_fetch_by_etf = {symbol: now for symbol in ("SPY", "NDX", "DJI")}

    repeated_with_fresh_cache = probe._p17_request_all_etfs()

    assert repeated_with_fresh_cache == ()
    assert len(probe._p17_fetch_executor.tasks) == 3
    assert probe.render_count == 1


def test_page_show_preloads_all_etfs() -> None:
    probe = _RequestProbe()

    probe._p17_on_show()

    assert probe.calls == [(False, "SPY"), (False, "NDX"), (False, "DJI")]


def test_selecting_cached_etf_renders_without_scheduling_fetch() -> None:
    probe = _RefreshProbe()
    cached_qqq = object()
    probe._p17_results["NDX"] = cached_qqq
    probe._p17_last_fetch_by_etf["NDX"] = datetime.datetime.now().timestamp()
    probe._p17_etf_buttons = {}

    probe._p17_select_etf("NDX")

    assert probe._p17_etf_symbol == "NDX"
    assert probe._p17_result is cached_qqq
    assert probe.render_count >= 1
    assert probe._p17_fetch_executor.tasks == []


def test_startup_paths_preload_all_etfs() -> None:
    prefetch_probe = _LifecycleProbe()
    prefetch_probe._run_startup_heatmap_prefetch()

    assert prefetch_probe.initialized == [6]
    assert prefetch_probe.calls == [("_p17_request_all_etfs", "page17")]

    warmup_probe = _LifecycleProbe()
    warmup_probe._warm_startup_etf_heatmap()

    assert warmup_probe.initialized == [6]
    assert warmup_probe.calls == [("_p17_request_all_etfs", "page17")]


def test_manual_refresh_remains_selected_etf_only() -> None:
    probe = _RequestProbe()

    probe._p17_request_refresh(force=True, symbol="NDX")

    assert probe.calls == [(True, "NDX")]


if __name__ == "__main__":
    test_request_all_etfs_uses_shared_fetch_path()
    test_request_all_etfs_preserves_force_flag()
    test_repeated_load_waves_use_inflight_and_fresh_cache_guards()
    test_page_show_preloads_all_etfs()
    test_selecting_cached_etf_renders_without_scheduling_fetch()
    test_startup_paths_preload_all_etfs()
    test_manual_refresh_remains_selected_etf_only()
    print("spy heatmap fetching smoke tests passed")
