"""Regressions for the GUI-thread guard on data-health view refreshes.

Background fetches reach `_refresh_data_health_views` from pool threads and from the startup warmup
threads in `window_lifecycle`. That method calls `set_status_text`, which calls `setStyleSheet` --
re-polishing and repainting a widget. Doing that off the GUI thread corrupts Qt's internal state and
aborts the process later, with the access violation surfacing inside `app.exec()` and no Python
frame to blame. These tests assert the work is marshalled instead.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.compat import QApplication, QObject, QThread, Signal  # noqa: E402
from budget_terminal_app.mixins.data_health import DataHealthMixin  # noqa: E402


class _RecordingLabel:
    """Stands in for a QLabel, recording which thread each write came from."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, Any]] = []
        self.text = ''

    def _record(self, kind: str) -> None:
        self.writes.append((kind, QThread.currentThread()))

    def setText(self, value: Any) -> None:
        self.text = str(value)
        self._record('setText')

    def setToolTip(self, value: Any) -> None:
        self._record('setToolTip')

    def setStyleSheet(self, value: Any) -> None:
        # The dangerous one: forces a style re-polish and repaint.
        self._record('setStyleSheet')

    def setProperty(self, name: Any, value: Any) -> None:
        self._record('setProperty')

    def setPlainText(self, value: Any) -> None:
        self.text = str(value)
        self._record('setPlainText')


class _Harness(DataHealthMixin, QObject):
    _invoke_main = Signal(object)

    def __init__(self) -> None:
        QObject.__init__(self)
        self._init_data_health_state()
        self._invoke_main.connect(self._on_invoke_main)
        self.data_health_label = _RecordingLabel()
        self.settings_data_health_summary_label = _RecordingLabel()
        self.settings_data_health_report = _RecordingLabel()

    def _on_invoke_main(self, fn: Any) -> None:
        fn()

    def set_status_text(self, widget: Any, text: Any, *, status: str = 'muted') -> None:
        # Mirrors ThemeSupportMixin.set_status_text, including the setStyleSheet call.
        widget.setText(str(text))
        widget.setToolTip(str(text))
        widget.setStyleSheet('color: #fff; font-size: 11px;')
        widget.setProperty('bt_status', status)

    def _build_data_health_report(self) -> str:
        return 'report'

    def all_writes(self) -> list[tuple[str, Any]]:
        return (
            self.data_health_label.writes
            + self.settings_data_health_summary_label.writes
            + self.settings_data_health_report.writes
        )


def _run_off_thread(fn: Any) -> None:
    """Run fn on a plain worker thread, like the startup warmup threads do."""
    error: list[BaseException] = []

    def _target() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            error.append(exc)

    thread = threading.Thread(target=_target, name='DataHealthProbe')
    thread.start()
    thread.join(10)
    assert not thread.is_alive(), 'the off-thread call did not finish'
    if error:
        raise error[0]


def test_off_thread_refresh_touches_no_widget_before_marshalling() -> None:
    app = QApplication.instance() or QApplication([])
    harness = _Harness()
    gui_thread = QThread.currentThread()

    _run_off_thread(harness._refresh_data_health_views)

    # Nothing may have been written yet, and certainly not from the worker thread.
    for kind, thread in harness.all_writes():
        assert thread is gui_thread, f'{kind} ran on a non-GUI thread'

    app.processEvents()

    writes = harness.all_writes()
    assert writes, 'the refresh should still happen, just marshalled onto the GUI thread'
    for kind, thread in writes:
        assert thread is gui_thread, f'{kind} ran on a non-GUI thread'
    assert harness.data_health_label.text == 'Data health: OK'


def test_record_payload_from_worker_thread_is_marshalled() -> None:
    """The real path: a background fetch resolving an earlier warning."""
    app = QApplication.instance() or QApplication([])
    harness = _Harness()
    gui_thread = QThread.currentThread()

    # Seed an active warning so the later 'fresh' payload resolves it and triggers a view refresh.
    harness._record_data_health_event('Warmup options expiries', severity='warning', symbols=['AAPL'])
    app.processEvents()
    baseline = len(harness.all_writes())

    payload = {'_market_data_meta': {'freshness': 'fresh', 'source': 'cache'}, 'portfolio': {}}
    _run_off_thread(lambda: harness._record_data_health_payload(
        'Warmup options expiries', payload, symbols=['AAPL'],
    ))

    for kind, thread in harness.all_writes():
        assert thread is gui_thread, f'{kind} ran on a non-GUI thread'

    app.processEvents()
    assert len(harness.all_writes()) > baseline, 'resolving the warning should refresh the views'
    for kind, thread in harness.all_writes():
        assert thread is gui_thread, f'{kind} ran on a non-GUI thread'


def test_refresh_without_a_marshalling_channel_is_skipped_not_executed() -> None:
    """A harness with no _invoke_main must skip rather than write from the wrong thread."""
    app = QApplication.instance() or QApplication([])

    class _NoChannel(_Harness):
        def __init__(self) -> None:
            super().__init__()
            # Simulate early startup, before the channel exists.
            self._invoke_main = None

    harness = _NoChannel()
    _run_off_thread(harness._refresh_data_health_views)
    app.processEvents()
    assert harness.all_writes() == [], 'no widget may be written without a GUI-thread channel'


def test_gui_thread_refresh_still_writes_directly() -> None:
    app = QApplication.instance() or QApplication([])
    harness = _Harness()
    harness._refresh_data_health_views()
    assert harness.data_health_label.text == 'Data health: OK'
    kinds = [kind for kind, _thread in harness.data_health_label.writes]
    assert 'setStyleSheet' in kinds
    app.processEvents()


if __name__ == '__main__':
    test_off_thread_refresh_touches_no_widget_before_marshalling()
    test_record_payload_from_worker_thread_is_marshalled()
    test_refresh_without_a_marshalling_channel_is_skipped_not_executed()
    test_gui_thread_refresh_still_writes_directly()
    print('Data health thread-safety tests passed.')
