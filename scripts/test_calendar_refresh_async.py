"""Focused smoke tests for non-blocking Calendar refresh behavior."""

from __future__ import annotations

import datetime
import os
import sys
import threading
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.calendar_page import CalendarPageMixin
from budget_terminal_app.workers import calendar as calendar_worker_module
from budget_terminal_app.workers.calendar import EconomicCalendarWarmupWorker


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _CalendarHarness(CalendarPageMixin):
    def __init__(self) -> None:
        self.tickers = ['AAPL']
        self._p7_year = 2026
        self._p7_month = 12
        self._p7_events = {}
        self._p7_fetching = False
        self._p7_event_generation = 0
        self._p7_event_active_request = None
        self._p7_event_pending_signature = None
        self._p7_event_cache = {}
        self._p7_economic_fetching = False
        self._p7_economic_generation = 0
        self._p7_economic_active_request = None
        self._p7_economic_pending_request = None
        self._p7_economic_attempted_at = {}
        self._p7_market_holiday_fetching = False
        self._p7_market_holiday_force_refresh = False
        self._p7_market_holiday_pending_years = []
        self._p7_render_pending = False
        self.visible = True
        self.earnings_visible = False
        self.render_count = 0
        self.earnings_payloads: list[object] = []
        self.launched: list[tuple[object, object, str]] = []

    def _launch_worker(self, worker: object, slot: object, flag_attr: str) -> bool:
        if getattr(self, flag_attr, False):
            return False
        setattr(self, flag_attr, True)
        self.launched.append((worker, slot, flag_attr))
        return True

    def _p7_calendar_view_is_visible(self) -> bool:
        return self.visible

    def _p7_calendar_tab_is_active(self) -> bool:
        return True

    def _p7_earnings_view_is_visible(self) -> bool:
        return self.earnings_visible

    def _p7_render_month(self) -> None:
        self.render_count += 1

    def _p7_apply_monthly_responsive_layout(self) -> None:
        return None

    def _p7_save_session_snapshot(self, *, immediate: bool = False) -> None:
        return None

    def _p7_update_earnings_refresh_button_state(self) -> None:
        return None

    def _p7_apply_earnings_payload(self, payload: object, *, restored: bool) -> None:
        self.earnings_payloads.append(payload)
        self._p7_earnings_rows = list(payload.get('rows', [])) if isinstance(payload, dict) else []


def test_cached_month_read_never_fetches_network() -> None:
    event = (datetime.date(2026, 7, 30), 'GDP Report', 'high')
    original_memory = dict(calendar_worker_module._ECONOMIC_EVENTS_MEMORY_CACHE)
    original_fetch = calendar_worker_module._fetch_official_economic_events_for_year
    calls: list[int] = []
    try:
        calendar_worker_module._ECONOMIC_EVENTS_MEMORY_CACHE.clear()
        calendar_worker_module._ECONOMIC_EVENTS_MEMORY_CACHE[2026] = (0.0, [event])
        calendar_worker_module._fetch_official_economic_events_for_year = lambda year: calls.append(int(year)) or []
        rows = calendar_worker_module._get_economic_events(2026, 7, allow_network=False)
        _assert(rows == [event], 'cache-only Calendar render should return stale cached rows')
        _assert(not calls, 'cache-only Calendar render must not call official sources')
    finally:
        calendar_worker_module._fetch_official_economic_events_for_year = original_fetch
        calendar_worker_module._ECONOMIC_EVENTS_MEMORY_CACHE.clear()
        calendar_worker_module._ECONOMIC_EVENTS_MEMORY_CACHE.update(original_memory)


def test_refresh_dispatches_official_fetch_and_defers_hidden_redraw() -> None:
    harness = _CalendarHarness()
    original_get_year = calendar_worker_module._get_economic_events_for_year
    main_thread_id = threading.get_ident()
    worker_thread_ids: list[int] = []
    try:
        calendar_worker_module._get_economic_events_for_year = (
            lambda _year, force_refresh=False: worker_thread_ids.append(threading.get_ident()) or []
        )
        harness._p7_fetch_events()
        _assert(harness.render_count == 1, 'manual refresh should render cached data immediately')
        economic_workers = [entry[0] for entry in harness.launched if isinstance(entry[0], EconomicCalendarWarmupWorker)]
        _assert(len(economic_workers) == 1, 'manual refresh should launch one economic warmup worker')

        worker = economic_workers[0]
        thread = threading.Thread(target=worker.run)
        thread.start()
        thread.join(timeout=2.0)
        _assert(not thread.is_alive(), 'economic warmup worker should finish in the smoke test')
        _assert(worker_thread_ids and all(thread_id != main_thread_id for thread_id in worker_thread_ids), 'official fetch must run outside the UI thread')

        harness.visible = False
        harness._p7_on_economic_events_ready(worker.generation, {})
        _assert(harness.render_count == 1, 'hidden Calendar must not redraw on worker completion')
        _assert(harness._p7_render_pending, 'hidden completion should retain one pending render')

        harness.visible = True
        harness._p7_on_show()
        _assert(harness.render_count == 2, 'returning to Calendar should apply the cached result once')
        _assert(not harness._p7_render_pending, 'pending Calendar render should clear after page show')
    finally:
        calendar_worker_module._get_economic_events_for_year = original_get_year


def test_duplicate_refresh_is_single_flight() -> None:
    harness = _CalendarHarness()
    harness._p7_fetch_events()
    first_launch_count = len(harness.launched)
    harness._p7_fetch_events()
    _assert(first_launch_count == 3, 'Calendar refresh should launch economic, holiday, and company workers')
    _assert(len(harness.launched) == first_launch_count, 'duplicate Calendar refresh must not launch duplicate workers')


def test_returning_to_active_view_discards_obsolete_pending_year() -> None:
    harness = _CalendarHarness()
    harness.p7_month_label = object()
    harness._p7_year = 2026
    _assert(harness._p7_queue_economic_years([2026], force_refresh=True), 'initial year should start')
    active = dict(harness._p7_economic_active_request or {})
    harness._p7_year = 2027
    _assert(harness._p7_queue_economic_years([2027], force_refresh=True), 'changed year should queue')
    _assert(harness._p7_economic_pending_request is not None, 'changed year was not retained')
    harness._p7_year = 2026
    _assert(
        not harness._p7_queue_economic_years([2026], force_refresh=True),
        'returning to the active request should reuse it',
    )
    _assert(harness._p7_economic_pending_request is None, 'obsolete intermediate year was not discarded')
    harness._p7_on_economic_events_ready(int(active['generation']), {})
    _assert(harness.render_count == 1, 'the active current year should render exactly once')
    _assert(len(harness.launched) == 1, 'obsolete pending year should not launch after completion')


def test_hidden_earnings_completion_renders_once_on_return() -> None:
    harness = _CalendarHarness()
    payload = {'rows': [{'symbol': 'AAPL'}]}
    harness._p7_on_earnings_ready(payload)
    _assert(not harness.earnings_payloads, 'hidden Earnings subtab must not rebuild cards')
    _assert(harness._p7_earnings_pending_update == ('ready', payload), 'hidden Earnings should retain its newest result')
    harness.earnings_visible = True
    _assert(harness._p7_apply_pending_earnings_update(), 'visible Earnings should consume its pending result')
    _assert(harness.earnings_payloads == [payload], 'Earnings should render the cached payload once')
    _assert(not harness._p7_apply_pending_earnings_update(), 'Earnings must not replay a consumed payload')


def main() -> None:
    test_cached_month_read_never_fetches_network()
    test_refresh_dispatches_official_fetch_and_defers_hidden_redraw()
    test_duplicate_refresh_is_single_flight()
    test_returning_to_active_view_discards_obsolete_pending_year()
    test_hidden_earnings_completion_renders_once_on_return()
    print('Calendar async refresh smoke tests passed')


if __name__ == '__main__':
    main()
