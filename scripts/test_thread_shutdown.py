"""Regressions for the worker-thread drain that runs when the main window closes.

A QThread still running when Python finalizes it aborts the process with no traceback, so these
cover both the drain's ordering and the inventory staying complete as pages are added.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.services.thread_shutdown import (  # noqa: E402
    WORKER_THREAD_SPECS,
    iter_worker_threads,
    shutdown_worker_threads,
)


class FakeThread:
    """Duck-typed stand-in recording the calls the drain makes."""

    def __init__(self, *, running: bool = True, stops_after_wait: bool = True) -> None:
        self._running = running
        self._stops_after_wait = stops_after_wait
        self.calls: list[str] = []

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.calls.append('requestInterruption')

    def quit(self) -> None:
        self.calls.append('quit')

    def wait(self, timeout_ms: int) -> bool:
        self.calls.append(f'wait({timeout_ms > 0})')
        if self._stops_after_wait:
            self._running = False
        return not self._running


class FakeWorker:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeWindow:
    pass


def test_single_thread_is_cancelled_then_drained() -> None:
    window = FakeWindow()
    thread = FakeThread()
    worker = FakeWorker()
    window._p19_thread = thread
    window._p19_worker = worker

    summary = shutdown_worker_threads(window)

    assert worker.cancelled, 'the worker must be cancelled; quit() alone cannot interrupt a blocking run'
    assert thread.calls[:2] == ['requestInterruption', 'quit']
    assert any(call.startswith('wait') for call in thread.calls)
    assert summary['stopped'] == ['_p19_thread']
    assert summary['lingering'] == []


def test_all_workers_are_signalled_before_any_wait() -> None:
    """Signalling must fan out first, or eight workers would serialize into a long freeze."""
    window = FakeWindow()
    order: list[str] = []

    class TracingThread(FakeThread):
        def __init__(self, label: str) -> None:
            super().__init__()
            self.label = label

        def quit(self) -> None:
            order.append(f'quit:{self.label}')
            super().quit()

        def wait(self, timeout_ms: int) -> bool:
            order.append(f'wait:{self.label}')
            return super().wait(timeout_ms)

    window._p14_thread = TracingThread('p14')
    window._p16_thread = TracingThread('p16')

    shutdown_worker_threads(window)

    assert order == ['quit:p14', 'quit:p16', 'wait:p14', 'wait:p16'], order


def test_unstoppable_thread_is_reported_and_retained() -> None:
    window = FakeWindow()
    stubborn = FakeThread(stops_after_wait=False)
    window._p24_thread = stubborn

    summary = shutdown_worker_threads(window, budget_ms=1)

    assert summary['lingering'] == ['_p24_thread']
    assert summary['stopped'] == []


def test_mapping_containers_are_drained() -> None:
    window = FakeWindow()
    primary, compare = FakeThread(), FakeThread()
    primary_worker, compare_worker = FakeWorker(), FakeWorker()
    window.p2_fund_threads = {'primary': primary, 'compare': compare, 'idle': None}
    window.p2_fund_workers = {'primary': primary_worker, 'compare': compare_worker}

    roll_thread = FakeThread()
    roll_worker = FakeWorker()
    window._p18_inflight_workers = {7: (roll_worker, roll_thread)}

    summary = shutdown_worker_threads(window)

    assert primary_worker.cancelled and compare_worker.cancelled and roll_worker.cancelled
    assert sorted(summary['stopped']) == [
        '_p18_inflight_workers[7]',
        'p2_fund_threads[compare]',
        'p2_fund_threads[primary]',
    ]


def test_drain_survives_a_broken_thread_object() -> None:
    class Exploding:
        def isRunning(self) -> bool:
            raise RuntimeError('Internal C++ object already deleted.')

        def quit(self) -> None:
            raise RuntimeError('Internal C++ object already deleted.')

    window = FakeWindow()
    window._p15_thread = Exploding()
    window._p16_thread = FakeThread()

    summary = shutdown_worker_threads(window)

    assert '_p16_thread' in summary['stopped'], 'a dead C++ object must not stop the rest of the drain'


def test_missing_attributes_are_skipped() -> None:
    assert list(iter_worker_threads(FakeWindow())) == []
    assert shutdown_worker_threads(FakeWindow()) == {'total': 0, 'stopped': [], 'lingering': []}


def _thread_attributes_assigned_in_source() -> set[str]:
    """Return every ``self.<attr> = thread`` target near a QThread() construction site."""
    found: set[str] = set()
    pattern = re.compile(r'self\.([A-Za-z0-9_]+)\s*=\s*thread\b')
    container_pattern = re.compile(r'self\.([A-Za-z0-9_]+)\[[^\]]+\]\s*=\s*(?:thread|\(worker, thread\))')
    for path in (PROJECT_ROOT / 'budget_terminal_app').rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        if 'QThread()' not in text:
            continue
        found.update(pattern.findall(text))
        found.update(container_pattern.findall(text))
    return found


def test_every_qthread_site_is_covered_by_the_shutdown_inventory() -> None:
    covered = {spec.thread_attr for spec in WORKER_THREAD_SPECS}
    assigned = _thread_attributes_assigned_in_source()
    missing = sorted(assigned - covered)
    assert not missing, (
        'These attributes hold a QThread but are absent from WORKER_THREAD_SPECS, so the app can '
        f'abort on close while they run: {missing}'
    )


if __name__ == '__main__':
    test_single_thread_is_cancelled_then_drained()
    test_all_workers_are_signalled_before_any_wait()
    test_unstoppable_thread_is_reported_and_retained()
    test_mapping_containers_are_drained()
    test_drain_survives_a_broken_thread_object()
    test_missing_attributes_are_skipped()
    test_every_qthread_site_is_covered_by_the_shutdown_inventory()
    print('Worker thread shutdown tests passed.')
