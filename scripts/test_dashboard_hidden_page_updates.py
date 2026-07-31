"""Focused smoke tests for Dashboard hidden-page update deferral."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.dashboard import DashboardMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _Stack:
    def __init__(self, current: object) -> None:
        self.current = current

    def currentWidget(self) -> object:
        return self.current


class _Button:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _DashboardHarness(DashboardMixin):
    def __init__(self) -> None:
        self.page1 = object()
        self.page4 = object()
        self.page6 = object()
        self.page7 = object()
        self.page34 = object()
        self.other_page = object()
        self.stacked_widget = _Stack(self.other_page)
        self.dashboard_load_btn = _Button()
        self.dashboard_pending_x_range = None
        self.dashboard_symbol = 'SPY'
        self._dashboard_latest_request_id = 1
        self._dashboard_latest_request_context = {'symbol': 'SPY'}
        self.last_data = {'portfolio': {'OLD': {'price': 1.0}}}
        self.related_calls: list[tuple[str, object]] = []
        self.visible_calls: list[tuple[object, str, bool]] = []
        self.shell_busy: list[bool] = []
        self.tickers = ['AAPL']

    def _page_initialized(self, *, page_attr: str, **_kwargs: object) -> bool:
        return hasattr(self, page_attr)

    def update_page34(self, data: object) -> None:
        self.related_calls.append(('news', data))

    def update_page4(self, data: object) -> None:
        self.related_calls.append(('portfolio', data))

    def _p7_fetch_events(self) -> None:
        self.related_calls.append(('calendar', None))

    def _p6_update_total(self) -> None:
        self.related_calls.append(('personal_finance', None))

    def _p7_calendar_tab_is_active(self) -> bool:
        return True

    def _dashboard_apply_visible_update(self, data: object, *, refresh_reason: str, apply_non_chart: bool) -> None:
        self.visible_calls.append((data, refresh_reason, apply_non_chart))

    def _set_data_collection_info(self, _value: object) -> None:
        return None

    def _get_fetch_tickers(self) -> list[str]:
        return list(self.tickers)

    def _set_shell_refresh_busy(self, busy: bool, _text: object = None) -> None:
        self.shell_busy.append(bool(busy))


def _payload() -> dict[str, object]:
    return {
        'request_id': 1,
        'portfolio': {'AAPL': {'price': 200.0}},
        'market': {},
        'targets': [],
        'news': [],
        'charts': {},
        '_dashboard_refresh_meta': {
            'chart_symbol': 'SPY',
            'refresh_reason': 'full',
            'non_chart_reused': False,
        },
    }


def test_hidden_consumers_apply_only_when_shown() -> None:
    harness = _DashboardHarness()
    payload = _payload()
    harness._dashboard_queue_related_page_updates(payload)
    newest_payload = {**payload, 'portfolio': {'MSFT': {'price': 500.0}}}
    harness._dashboard_queue_related_page_updates(newest_payload)
    _assert(not harness.related_calls, 'hidden related pages should not redraw')
    _assert(set(harness._dashboard_pending_page_data) == {'news', 'portfolio', 'calendar', 'personal_finance'}, 'each initialized hidden consumer should retain one update')

    harness.stacked_widget.current = harness.page4
    _assert(harness._dashboard_apply_pending_page_data('portfolio'), 'Portfolio pending data should apply on show')
    _assert([key for key, _data in harness.related_calls] == ['portfolio'], 'only the visible Portfolio should update')
    _assert(harness.related_calls[0][1] is newest_payload, 'hidden Portfolio should receive only the newest payload')
    _assert(not harness._dashboard_apply_pending_page_data('portfolio'), 'the same payload must not render twice')


def test_dashboard_result_caches_while_hidden() -> None:
    harness = _DashboardHarness()
    harness.stacked_widget.current = harness.page4
    payload = _payload()
    harness.update_ui(payload)
    _assert(harness.last_data is payload, 'Dashboard result should be cached immediately')
    _assert(not harness.visible_calls, 'hidden Dashboard must not rebuild its widgets')
    _assert([key for key, _data in harness.related_calls] == ['portfolio'], 'currently visible Portfolio should receive the shared payload')
    _assert(isinstance(harness._dashboard_pending_visible_update, dict), 'hidden Dashboard should retain one pending render')

    harness.stacked_widget.current = harness.page1
    _assert(harness._dashboard_on_show(), 'Dashboard should consume its pending result on show')
    _assert(len(harness.visible_calls) == 1, 'Dashboard should render the cached result exactly once')
    _assert(not harness._dashboard_on_show(), 'Dashboard should not replay an already-consumed result')


def test_membership_merge_preserves_chart_payload() -> None:
    harness = _DashboardHarness()
    previous = {
        'portfolio': {'OLD': {'price': 1.0}},
        'charts': {'SPY': object()},
        'chart_options': {'SPY': {'0_week': []}},
        'chart_ma200': {'SPY': object()},
    }
    incoming = {'portfolio': {'AAPL': {'price': 200.0}}, 'charts': {}, 'chart_options': {}}
    merged = harness._dashboard_merge_membership_payload(previous, incoming)
    _assert(merged['portfolio'] == incoming['portfolio'], 'membership quotes should replace old quotes')
    _assert(merged['charts'] is previous['charts'], 'empty membership charts must not erase cached charts')
    _assert(merged['chart_options'] is previous['chart_options'], 'empty membership options must not erase cached options')
    _assert(merged['chart_ma200'] is previous['chart_ma200'], 'missing membership indicators must preserve cached indicators')


def test_dashboard_result_cannot_overwrite_newer_portfolio_quotes() -> None:
    harness = _DashboardHarness()
    harness._dashboard_latest_request_context = {
        'request_id': 1,
        'symbol': 'SPY',
        'started_monotonic': 10.0,
    }
    harness._p4_latest_quote_overlay = {
        'completed_monotonic': 11.0,
        'quotes': {
            'AAPL': {'price': 210.0},
            'REMOVED': {'price': 1.0},
        },
    }
    payload = _payload()
    payload['portfolio']['REMOVED'] = {'price': 0.5}
    merged = harness._dashboard_preserve_newer_portfolio_quotes(payload, 1)
    _assert(merged['portfolio']['AAPL']['price'] == 210.0, 'newer Portfolio quotes should win')
    _assert('REMOVED' not in merged['portfolio'], 'removed holdings must not be restored by a late overlay')

    harness._dashboard_latest_request_context['started_monotonic'] = 12.0
    newer_dashboard = harness._dashboard_preserve_newer_portfolio_quotes(payload, 1)
    _assert(newer_dashboard is payload, 'a newer Dashboard request should keep its own quotes')


def main() -> None:
    test_hidden_consumers_apply_only_when_shown()
    test_dashboard_result_caches_while_hidden()
    test_membership_merge_preserves_chart_payload()
    test_dashboard_result_cannot_overwrite_newer_portfolio_quotes()
    print('Dashboard hidden-page update smoke tests passed')


if __name__ == '__main__':
    main()
