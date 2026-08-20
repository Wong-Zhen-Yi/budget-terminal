"""Regressions for persistent crash diagnostics.

The failure this guards against is silent: a PySide6 process aborted from C++ leaves no traceback,
no log line, and no exit message. The end-to-end case below provokes a real abort in a child
process and asserts the parent can still find out what happened.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app import crash_reporting  # noqa: E402


def _isolated_user_data(tmp_dir: str) -> None:
    """Point every writable path at a scratch directory for the duration of a test."""
    os.environ['LOCALAPPDATA'] = tmp_dir
    os.environ['APPDATA'] = tmp_dir


def test_crash_report_contains_context() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        _isolated_user_data(tmp_dir)
        buffer = crash_reporting.RecentLogBuffer()
        crash_reporting._RECENT_LOG_HANDLER = buffer
        buffer.emit(
            logging.LogRecord('test', logging.INFO, __file__, 1, 'portfolio refresh started', None, None)
        )
        try:
            raise ValueError('synthetic failure')
        except ValueError as exc:
            report = crash_reporting.write_crash_report(
                'uncaught-exception',
                'ValueError: synthetic failure',
                exc_info=(type(exc), exc, exc.__traceback__),
                details={'page': 'portfolio'},
            )

        assert report is not None and report.exists()
        text = report.read_text(encoding='utf-8')
        assert 'Kind: uncaught-exception' in text
        assert 'ValueError: synthetic failure' in text
        assert 'page: portfolio' in text
        assert '-- Python thread stacks --' in text
        assert 'portfolio refresh started' in text, 'the log tail gives the crash its context'
        assert 'pyside6:' in text and 'app_version:' in text
        crash_reporting._RECENT_LOG_HANDLER = None


def test_report_writing_never_raises_on_a_bad_location() -> None:
    """Crash reporting must degrade quietly; it can never be the reason a shutdown fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        blocker = Path(tmp_dir) / 'blocker.txt'
        blocker.write_text('not a directory', encoding='utf-8')
        _isolated_user_data(str(blocker / 'BudgetTerminal'))
        # The failure is logged with a traceback by design; keep it out of the smoke output.
        logging.disable(logging.CRITICAL)
        try:
            assert crash_reporting.write_crash_report('uncaught-exception', 'boom') is None
        finally:
            logging.disable(logging.NOTSET)


def test_old_reports_are_pruned() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        _isolated_user_data(tmp_dir)
        for index in range(crash_reporting.MAX_CRASH_REPORTS + 5):
            (crash_reporting.crash_dir() / f'crash-2026010{index:02d}-000000-1-test.log').write_text(
                'x', encoding='utf-8'
            )
        crash_reporting._prune_crash_reports()
        assert len(crash_reporting.list_crash_reports()) == crash_reporting.MAX_CRASH_REPORTS


def test_process_liveness_probe_is_non_destructive() -> None:
    """os.kill() terminates the target on Windows, so liveness must not go through it."""
    assert crash_reporting._process_is_alive(os.getpid()) is True
    assert crash_reporting._process_is_alive(0) is False
    assert crash_reporting._process_is_alive(-5) is False


def test_native_fault_capture_writes_a_session_banner() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        _isolated_user_data(tmp_dir)
        crash_reporting.disable_native_fault_capture()
        try:
            path = crash_reporting.enable_native_fault_capture()
            assert path is not None and path.exists()
            assert 'session start' in path.read_text(encoding='utf-8')
        finally:
            # faulthandler holds the descriptor open, which would block the scratch cleanup.
            crash_reporting.disable_native_fault_capture()


def test_hard_abort_in_a_child_process_leaves_a_crash_report() -> None:
    """The end-to-end case: a QThread destroyed while running used to vanish without a trace."""
    child_source = textwrap.dedent(
        '''
        import gc, os, sys, time
        sys.path.insert(0, {root!r})
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from budget_terminal_app.crash_reporting import configure_crash_reporting
        configure_crash_reporting()
        from PySide6.QtCore import QThread, QObject, Signal
        from PySide6.QtWidgets import QApplication

        app = QApplication(sys.argv)

        class Worker(QObject):
            done = Signal()
            def run(self):
                time.sleep(30)

        def leak():
            thread = QThread()
            worker = Worker()
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            thread.start()
            time.sleep(0.2)

        leak()
        gc.collect()   # destroys a running QThread -> Qt calls qFatal() -> abort
        print('NO-ABORT')
        '''
    ).format(root=str(PROJECT_ROOT))

    with tempfile.TemporaryDirectory() as tmp_dir:
        env = dict(os.environ)
        env['LOCALAPPDATA'] = tmp_dir
        env['APPDATA'] = tmp_dir
        env['BUDGET_TERMINAL_SKIP_LOCAL_VENV'] = '1'
        child = subprocess.run(
            [sys.executable, '-c', child_source],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        assert child.returncode != 0, f'the child was expected to abort, got {child.stdout!r}'

        _isolated_user_data(tmp_dir)
        reports = crash_reporting.list_crash_reports()
        assert reports, 'a hard abort must leave a crash report behind'
        combined = '\n'.join(report.read_text(encoding='utf-8', errors='replace') for report in reports)
        assert 'QThread' in combined, combined[:2000]

        # A second launch must also notice the previous session never shut down cleanly.
        crash_reporting._SESSION_MARKER_PATH = None
        recovered = crash_reporting._report_unclean_previous_sessions()
        assert recovered, 'the stale session marker should be reported on the next launch'
        assert 'without a clean shutdown' in recovered[0].read_text(encoding='utf-8')


def test_settings_panel_lists_and_previews_reports() -> None:
    """The Diagnostics panel is how a user reaches a crash report without a file browser."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from budget_terminal_app.compat import QApplication, QLabel, QWidget
    from budget_terminal_app.mixins.settings import SettingsMixin

    class _Harness(SettingsMixin, QWidget):
        def __init__(self) -> None:
            QWidget.__init__(self)
            self.settings_separator_lines = []

        def set_theme_role(self, widget, role: str) -> None:
            widget.setProperty('bt_role', role)

        def set_theme_variant(self, widget, variant) -> None:
            widget.setProperty('bt_variant', variant)

        def _settings_section_header(self, title: str, description: str) -> QLabel:
            return QLabel(f'{title}: {description}')

    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp_dir:
        _isolated_user_data(tmp_dir)
        crash_reporting.write_crash_report('qt-fatal', 'QThread: Destroyed while thread is still running')
        try:
            raise ValueError('boom')
        except ValueError as exc:
            crash_reporting.write_crash_report(
                'uncaught-exception',
                'ValueError: boom',
                exc_info=(type(exc), exc, exc.__traceback__),
            )

        harness = _Harness()
        box = harness._build_settings_crash_reports_box()
        harness._refresh_settings_crash_reports()

        assert box.title() == 'Crash Reports'
        assert harness.settings_crash_selector.count() == 2
        newest = harness.settings_crash_selector.itemText(0)
        assert 'uncaught-exception' in newest, 'reports should be listed newest first'
        assert '2 crash report(s)' in harness.settings_crash_meta_label.text()
        assert 'Kind: uncaught-exception' in harness.settings_crash_output.toPlainText()

        harness.settings_crash_selector.setCurrentIndex(1)
        assert 'QThread' in harness.settings_crash_output.toPlainText()


def test_settings_panel_handles_an_empty_folder() -> None:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from budget_terminal_app.compat import QApplication, QLabel, QWidget
    from budget_terminal_app.mixins.settings import SettingsMixin

    class _Harness(SettingsMixin, QWidget):
        def __init__(self) -> None:
            QWidget.__init__(self)
            self.settings_separator_lines = []

        def set_theme_role(self, widget, role: str) -> None:
            widget.setProperty('bt_role', role)

        def set_theme_variant(self, widget, variant) -> None:
            widget.setProperty('bt_variant', variant)

        def _settings_section_header(self, title: str, description: str) -> QLabel:
            return QLabel(f'{title}: {description}')

    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp_dir:
        _isolated_user_data(tmp_dir)
        harness = _Harness()
        # The box owns the widgets; dropping it would delete them out from under the wrappers.
        box = harness._build_settings_crash_reports_box()
        harness._refresh_settings_crash_reports()
        assert box.title() == 'Crash Reports'
        assert harness.settings_crash_selector.count() == 0
        assert 'No crash reports' in harness.settings_crash_meta_label.text()
        assert 'No crash reports' in harness.settings_crash_output.toPlainText()


if __name__ == '__main__':
    original_localappdata = os.environ.get('LOCALAPPDATA')
    original_appdata = os.environ.get('APPDATA')
    try:
        test_crash_report_contains_context()
        test_report_writing_never_raises_on_a_bad_location()
        test_old_reports_are_pruned()
        test_process_liveness_probe_is_non_destructive()
        test_native_fault_capture_writes_a_session_banner()
        test_hard_abort_in_a_child_process_leaves_a_crash_report()
        test_settings_panel_lists_and_previews_reports()
        test_settings_panel_handles_an_empty_folder()
    finally:
        for name, value in (('LOCALAPPDATA', original_localappdata), ('APPDATA', original_appdata)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    print('Crash reporting tests passed.')
