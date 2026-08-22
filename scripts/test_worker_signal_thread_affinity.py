"""Regressions for worker-signal slots that must run on the GUI thread.

A QObject worker moved onto a QThread emits its `finished` / `error` / `progress` signals from that
worker thread. Qt picks Queued vs Direct for an AutoConnection by comparing the *receiver's* thread
affinity to the emitting thread -- but a bare lambda is not a QObject, so PySide6 has no receiver
context and falls back to a DirectConnection. The lambda then runs inline inside `emit()`, on the
worker thread.

That is how the valuation page's chart render ended up executing on a worker thread while the GUI
thread was rendering the same pyqtgraph scene, aborting the process with
`Windows fatal exception: access violation` and a stack whose bottom frame was
`workers/valuation.py in run`. `WindowBootstrapMixin._connect_worker_signal` marshals through
`_invoke_main` instead; these tests assert it does, and that the raw idiom really is unsafe.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.compat import QApplication, QObject, QThread, Signal  # noqa: E402
from budget_terminal_app.mixins.window_bootstrap import WindowBootstrapMixin  # noqa: E402
from budget_terminal_app.services.thread_shutdown import WORKER_THREAD_SPECS  # noqa: E402

MIXINS_DIR = PROJECT_ROOT / 'budget_terminal_app' / 'mixins'


class _Worker(QObject):
    """Stands in for any workers/* class: emits from whatever thread runs `run`."""

    finished = Signal(object)
    done = Signal()

    def run(self) -> None:
        self.finished.emit({'ok': True})
        self.done.emit()


class _Harness(WindowBootstrapMixin, QObject):
    """The minimum of BudgetTerminalApp that `_connect_worker_signal` depends on."""

    _invoke_main = Signal(object)

    def __init__(self) -> None:
        QObject.__init__(self)
        self._invoke_main.connect(self._on_invoke_main)
        self.observed: list[tuple[str, Any, Any]] = []

    def handle_result(self, request_id: Any, payload: Any) -> None:
        self.observed.append(('handle_result', QThread.currentThread(), (request_id, payload)))

    def handle_cleanup(self, worker: Any, thread: Any) -> None:
        self.observed.append(('handle_cleanup', QThread.currentThread(), (worker, thread)))


def _drive(connect: Any) -> tuple[QApplication, _Harness, QThread]:
    """Run one worker to completion on a real QThread, wiring it with `connect`."""
    app = QApplication.instance() or QApplication([])
    harness = _Harness()
    worker = _Worker()
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    connect(harness, worker, thread)
    worker.finished.connect(thread.quit)
    thread.start()
    # thread.quit() and every marshalled callback are queued onto the GUI thread, so this thread
    # has to keep pumping rather than block in thread.wait().
    deadline = time.monotonic() + 10.0
    while thread.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not thread.isRunning(), 'the worker thread did not finish'
    app.processEvents()
    return app, harness, thread


def test_connected_slot_runs_on_the_gui_thread() -> None:
    gui_thread = QThread.currentThread()

    def _connect(harness: _Harness, worker: _Worker, thread: QThread) -> None:
        harness._connect_worker_signal(worker.finished, harness.handle_result, 7)

    _app, harness, _thread = _drive(_connect)

    calls = [entry for entry in harness.observed if entry[0] == 'handle_result']
    assert calls, 'the handler never ran'
    for name, thread, _args in calls:
        assert thread is gui_thread, f'{name} ran on a worker thread'
    assert calls[0][2] == (7, {'ok': True}), 'bound args must precede the signal payload'


def test_argumentless_signal_passes_only_bound_values() -> None:
    """`thread.finished` carries no payload; the cleanup slot still needs its identity args."""
    gui_thread = QThread.currentThread()
    sentinel_worker = object()
    sentinel_thread = object()

    def _connect(harness: _Harness, worker: _Worker, thread: QThread) -> None:
        harness._connect_worker_signal(worker.done, harness.handle_cleanup, sentinel_worker, sentinel_thread)

    _app, harness, _thread = _drive(_connect)

    calls = [entry for entry in harness.observed if entry[0] == 'handle_cleanup']
    assert calls, 'the cleanup slot never ran'
    assert calls[0][1] is gui_thread, 'cleanup ran on a worker thread'
    assert calls[0][2] == (sentinel_worker, sentinel_thread)


def test_raw_lambda_connect_runs_on_the_worker_thread() -> None:
    """The unfixed idiom, kept as executable documentation of why the helper exists."""
    gui_thread = QThread.currentThread()

    def _connect(harness: _Harness, worker: _Worker, thread: QThread) -> None:
        worker.finished.connect(lambda payload, req=7: harness.handle_result(req, payload))

    _app, harness, _thread = _drive(_connect)

    calls = [entry for entry in harness.observed if entry[0] == 'handle_result']
    assert calls, 'the handler never ran'
    assert calls[0][1] is not gui_thread, (
        'A lambda slot is expected to run on the emitting worker thread. If this now passes, '
        'PySide6 changed its connection-type resolution and the helper can be revisited.'
    )


def test_shutdown_drops_pending_deliveries() -> None:
    """Once closeEvent sets _refresh_shutdown, late worker results must not reach widgets."""
    app = QApplication.instance() or QApplication([])
    harness = _Harness()
    harness._refresh_shutdown = True
    harness._deliver_to_main(lambda: harness.observed.append(('late', None, None)))
    app.processEvents()
    assert harness.observed == [], 'a result was delivered after shutdown began'


def _mixin_files_owning_worker_threads() -> list[Path]:
    """Map WORKER_THREAD_SPECS onto the mixin files that actually create those QThreads."""
    attrs = [spec.thread_attr for spec in WORKER_THREAD_SPECS]
    files = []
    for path in sorted(MIXINS_DIR.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if 'QThread()' not in text:
            continue
        if any(f'self.{attr}' in text for attr in attrs):
            files.append(path)
    return files


def test_no_worker_signal_is_connected_to_a_lambda() -> None:
    """Stop the idiom creeping back in, the way test_refresh_route_inventory guards its registries."""
    files = _mixin_files_owning_worker_threads()
    assert files, 'expected to find the mixins that own worker QThreads'

    pattern = re.compile(r'^\s*(?:worker|thread)\.\w+\.connect\(\s*(?:lambda|partial)\b', re.MULTILINE)
    offenders = []
    for path in files:
        for match in pattern.finditer(path.read_text(encoding='utf-8')):
            line_no = path.read_text(encoding='utf-8')[: match.start()].count('\n') + 1
            offenders.append(f'{path.relative_to(PROJECT_ROOT)}:{line_no}')

    assert not offenders, (
        'Worker signals must be wired with self._connect_worker_signal, not a lambda -- a plain '
        'callable slot has no QObject receiver, so Qt runs it on the worker thread. Offenders: '
        + ', '.join(offenders)
    )


if __name__ == '__main__':
    test_connected_slot_runs_on_the_gui_thread()
    test_argumentless_signal_passes_only_bound_values()
    test_raw_lambda_connect_runs_on_the_worker_thread()
    test_shutdown_drops_pending_deliveries()
    test_no_worker_signal_is_connected_to_a_lambda()
    print('Worker signal thread-affinity tests passed.')
