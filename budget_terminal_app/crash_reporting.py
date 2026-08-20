"""Persistent crash diagnostics for aborts that never reach Python exception handling.

`error_logging` records exceptions that Python can still see. The failures that end a PySide6
session outright — a `QThread` destroyed while running, a deleted C++ object, a segfault inside a
native chart path — abort the process from C++ and leave no traceback behind. This module captures
those: `faulthandler` writes native stacks straight to a file descriptor, a Qt message handler
records `qFatal` text before Qt calls `abort()`, and a per-process session marker lets the next
launch notice that the previous one never shut down cleanly.

Every entry point is best-effort. Crash reporting must never be the reason a launch fails.
"""

from __future__ import annotations

import atexit
import datetime
import faulthandler
import json
import logging
import os
import platform
import sys
import threading
import traceback
from collections import deque
from pathlib import Path
from types import TracebackType
from typing import Any

from .error_logging import QT_LOGGER_NAME
from .paths import user_data_dir

CRASH_DIR_NAME = 'crashes'
ERROR_LOG_DIR_NAME = 'logs'
SESSION_DIR_NAME = 'sessions'
NATIVE_FAULT_LOG_NAME = 'native-faults.log'
CRASH_REPORT_SUFFIX = '.log'
MAX_CRASH_REPORTS = 20
MAX_NATIVE_FAULT_LOG_BYTES = 512 * 1024
RECENT_LOG_CAPACITY = 400
NATIVE_TAIL_CHARS = 8000

_logger = logging.getLogger(__name__)

_CONFIGURED = False
_NATIVE_FAULT_STREAM: Any = None
_RECENT_LOG_HANDLER: Any = None
_SESSION_MARKER_PATH: Path | None = None
_PREVIOUS_SESSION_REPORTS: tuple[Path, ...] = ()
_ORIGINAL_SYS_EXCEPTHOOK: Any = None
_ORIGINAL_THREADING_EXCEPTHOOK: Any = None
_ORIGINAL_QT_MESSAGE_HANDLER: Any = None
_REPORT_LOCK = threading.Lock()


# --------------------------------------------------------------------------- locations


def crash_dir() -> Path:
    """Return the writable directory holding crash reports and native fault output."""
    path = user_data_dir() / ERROR_LOG_DIR_NAME / CRASH_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def native_fault_log_path() -> Path:
    """Return the file that receives native (C-level) fault tracebacks."""
    return crash_dir() / NATIVE_FAULT_LOG_NAME


def _session_dir() -> Path:
    path = crash_dir() / SESSION_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_crash_reports() -> list[Path]:
    """Return existing crash reports, newest first."""
    try:
        reports = [
            entry
            for entry in crash_dir().iterdir()
            if entry.is_file() and entry.name.startswith('crash-') and entry.suffix == CRASH_REPORT_SUFFIX
        ]
    except Exception:
        return []
    return sorted(reports, key=lambda entry: entry.name, reverse=True)


def previous_session_crash_reports() -> tuple[Path, ...]:
    """Return reports written this launch for sessions that ended without a clean shutdown."""
    return _PREVIOUS_SESSION_REPORTS


# --------------------------------------------------------------------------- recent log buffer


class RecentLogBuffer(logging.Handler):
    """Keep the last few hundred formatted log records in memory for crash reports."""

    def __init__(self, capacity: int = RECENT_LOG_CAPACITY) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[str] = deque(maxlen=max(1, int(capacity)))
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._records.append(self.format(record))
        except Exception:
            # A logging handler must never raise into the emitting call site.
            pass

    def snapshot(self) -> list[str]:
        """Return a copy of the buffered lines, oldest first."""
        return list(self._records)


def recent_log_lines() -> list[str]:
    """Return the buffered log tail, or an empty list when buffering is unavailable."""
    handler = _RECENT_LOG_HANDLER
    if handler is None:
        return []
    return handler.snapshot()


# --------------------------------------------------------------------------- environment summary


def _app_version() -> str:
    try:
        from . import __version__

        return str(__version__ or 'unknown')
    except Exception:
        return 'unknown'


def _qt_versions() -> tuple[str, str]:
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        return str(getattr(PySide6, '__version__', 'unknown')), str(qVersion())
    except Exception:
        return 'unavailable', 'unavailable'


def environment_summary() -> dict[str, str]:
    """Return the runtime facts worth knowing when reading a crash report."""
    pyside_version, qt_version = _qt_versions()
    return {
        'app_version': _app_version(),
        'python': sys.version.replace('\n', ' '),
        'pyside6': pyside_version,
        'qt': qt_version,
        'platform': f'{platform.system()} {platform.release()} ({platform.machine()})',
        'frozen': 'yes' if getattr(sys, 'frozen', False) else 'no',
        'pid': str(os.getpid()),
        'executable': os.path.basename(sys.executable or 'unknown'),
        'qt_platform': str(os.environ.get('QT_QPA_PLATFORM', '') or 'default'),
    }


def _thread_dump() -> list[str]:
    """Return a stack listing for every live Python thread."""
    lines: list[str] = []
    try:
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        frames = sys._current_frames()
    except Exception:
        return ['Thread dump unavailable.']
    for ident, frame in frames.items():
        name = names.get(ident, 'unknown')
        lines.append(f'--- Thread {name} (id {ident}) ---')
        try:
            lines.extend(line.rstrip() for line in traceback.format_stack(frame))
        except Exception:
            lines.append('  <stack unavailable>')
    return lines or ['No live threads reported.']


def _native_fault_tail(max_chars: int = NATIVE_TAIL_CHARS) -> str:
    try:
        path = native_fault_log_path()
        if not path.exists():
            return ''
        text = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''
    return text[-max_chars:].strip()


# --------------------------------------------------------------------------- report writing


def _report_path(kind: str, when: datetime.datetime, pid: int) -> Path:
    stamp = when.strftime('%Y%m%d-%H%M%S')
    safe_kind = ''.join(char if char.isalnum() or char in {'-', '_'} else '-' for char in str(kind or 'crash'))
    return crash_dir() / f'crash-{stamp}-{pid}-{safe_kind}{CRASH_REPORT_SUFFIX}'


def write_crash_report(
    kind: str,
    summary: str,
    *,
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = None,
    details: dict[str, Any] | None = None,
    include_thread_dump: bool = True,
    include_native_tail: bool = False,
    pid: int | None = None,
    when: datetime.datetime | None = None,
) -> Path | None:
    """Write one self-contained crash report and return its path, or None when writing failed."""
    moment = when or datetime.datetime.now()
    process_id = int(pid if pid is not None else os.getpid())
    sections: list[str] = []
    sections.append('=' * 78)
    sections.append('Budget Terminal crash report')
    sections.append('=' * 78)
    sections.append(f'Kind: {kind}')
    sections.append(f'Time: {moment.isoformat(timespec="seconds")}')
    sections.append(f'Summary: {summary}')
    sections.append('')
    sections.append('-- Environment --')
    for key, value in environment_summary().items():
        sections.append(f'{key}: {value}')
    if details:
        sections.append('')
        sections.append('-- Details --')
        for key, value in details.items():
            sections.append(f'{key}: {value}')
    if exc_info is not None:
        sections.append('')
        sections.append('-- Traceback --')
        try:
            sections.extend(
                line.rstrip() for line in traceback.format_exception(exc_info[0], exc_info[1], exc_info[2])
            )
        except Exception:
            sections.append('<traceback formatting failed>')
    if include_thread_dump:
        sections.append('')
        sections.append('-- Python thread stacks --')
        sections.extend(_thread_dump())
    if include_native_tail:
        tail = _native_fault_tail()
        sections.append('')
        sections.append('-- Native fault log tail --')
        sections.append(tail or '(no native fault output was recorded)')
    recent = recent_log_lines()
    if recent:
        sections.append('')
        sections.append('-- Recent log --')
        sections.extend(recent)
    sections.append('')

    try:
        with _REPORT_LOCK:
            path = _report_path(kind, moment, process_id)
            path.write_text('\n'.join(sections), encoding='utf-8', errors='replace')
        _prune_crash_reports()
        return path
    except Exception:
        _logger.warning('Unable to write a crash report for %s.', kind, exc_info=True)
        return None


def _prune_crash_reports(keep: int = MAX_CRASH_REPORTS) -> None:
    try:
        reports = list_crash_reports()
        for stale in reports[max(0, int(keep)):]:
            stale.unlink(missing_ok=True)
    except Exception:
        _logger.debug('Crash report pruning did not complete.', exc_info=True)


# --------------------------------------------------------------------------- native fault capture


def _rotate_native_fault_log(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_NATIVE_FAULT_LOG_BYTES:
            backup = path.with_suffix(path.suffix + '.1')
            backup.unlink(missing_ok=True)
            path.rename(backup)
    except Exception:
        _logger.debug('Native fault log rotation did not complete.', exc_info=True)


def enable_native_fault_capture() -> Path | None:
    """Point `faulthandler` at a persistent file so hard aborts leave a native traceback."""
    global _NATIVE_FAULT_STREAM
    if _NATIVE_FAULT_STREAM is not None:
        return native_fault_log_path()
    try:
        path = native_fault_log_path()
        _rotate_native_fault_log(path)
        # Kept open for the whole process: faulthandler writes to the raw descriptor, so the
        # stream must outlive this call. Line buffering keeps partial output usable after an abort.
        stream = open(path, 'a', encoding='utf-8', errors='replace', buffering=1)
        stream.write(
            f'\n===== session start {datetime.datetime.now().isoformat(timespec="seconds")} '
            f'pid={os.getpid()} =====\n'
        )
        stream.flush()
        faulthandler.enable(file=stream, all_threads=True)
        _NATIVE_FAULT_STREAM = stream
        return path
    except Exception:
        _logger.warning('Native fault capture is unavailable; hard crashes will not leave a stack.', exc_info=True)
        return None


# --------------------------------------------------------------------------- Qt message capture


def disable_native_fault_capture() -> None:
    """Stop native fault capture and release the log file. Used by tests and orderly teardown."""
    global _NATIVE_FAULT_STREAM
    stream = _NATIVE_FAULT_STREAM
    _NATIVE_FAULT_STREAM = None
    try:
        faulthandler.disable()
    except Exception:
        pass
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass


def install_qt_message_handler() -> bool:
    """Route Qt's own diagnostics into logging, capturing `qFatal` text before Qt aborts."""
    global _ORIGINAL_QT_MESSAGE_HANDLER
    if _ORIGINAL_QT_MESSAGE_HANDLER is not None:
        return True
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        _logger.debug('Qt message handler unavailable; PySide6 could not be imported.', exc_info=True)
        return False

    level_for_type = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    qt_logger = logging.getLogger(QT_LOGGER_NAME)

    def _handler(message_type: Any, context: Any, message: Any) -> None:
        text = str(message or '').strip()
        level = level_for_type.get(message_type, logging.INFO)
        location = ''
        try:
            if getattr(context, 'file', None):
                location = f' ({os.path.basename(str(context.file))}:{int(getattr(context, "line", 0) or 0)})'
        except Exception:
            location = ''
        qt_logger.log(level, 'Qt: %s%s', text, location)
        if message_type == QtMsgType.QtFatalMsg:
            # Qt calls abort() the moment this handler returns, so the report must be written now.
            write_crash_report(
                'qt-fatal',
                text or 'Qt reported a fatal condition.',
                details={'qt_location': location.strip() or 'unknown'},
                include_native_tail=False,
            )
            _flush_native_stream()

    _ORIGINAL_QT_MESSAGE_HANDLER = qInstallMessageHandler(_handler) or True
    return True


def _flush_native_stream() -> None:
    stream = _NATIVE_FAULT_STREAM
    if stream is None:
        return
    try:
        stream.flush()
        os.fsync(stream.fileno())
    except Exception:
        pass


# --------------------------------------------------------------------------- exception hooks


def _install_exception_hooks() -> None:
    global _ORIGINAL_SYS_EXCEPTHOOK, _ORIGINAL_THREADING_EXCEPTHOOK
    if _ORIGINAL_SYS_EXCEPTHOOK is not None:
        return
    _ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
    _ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, 'excepthook', None)

    def _sys_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            write_crash_report(
                'uncaught-exception',
                f'{exc_type.__name__}: {exc_value}',
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        if _ORIGINAL_SYS_EXCEPTHOOK is not None:
            _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, KeyboardInterrupt):
            thread_name = getattr(args.thread, 'name', 'unknown')
            write_crash_report(
                'uncaught-thread-exception',
                f'{args.exc_type.__name__}: {args.exc_value} (thread {thread_name})',
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                details={'thread': thread_name},
            )
        if _ORIGINAL_THREADING_EXCEPTHOOK is not None:
            _ORIGINAL_THREADING_EXCEPTHOOK(args)

    sys.excepthook = _sys_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _threading_excepthook


# --------------------------------------------------------------------------- session markers


def _process_is_alive(pid: int) -> bool:
    """Return whether a process id is still running, without signalling it."""
    try:
        process_id = int(pid)
    except Exception:
        return False
    if process_id <= 0:
        return False
    if process_id == os.getpid():
        return True
    if sys.platform == 'win32':
        # os.kill() on Windows terminates the target, so liveness is probed through the Win32 API.
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize | process_query_limited_information, False, process_id)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            still_active = 259
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return int(exit_code.value) == still_active
            return kernel32.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _write_session_marker() -> Path | None:
    global _SESSION_MARKER_PATH
    try:
        path = _session_dir() / f'session-{os.getpid()}.json'
        payload = {
            'pid': os.getpid(),
            'started_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'environment': environment_summary(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        _SESSION_MARKER_PATH = path
        return path
    except Exception:
        _logger.debug('Unable to record a session marker.', exc_info=True)
        return None


def note_clean_shutdown() -> None:
    """Remove this process's session marker so the next launch sees a clean exit."""
    global _SESSION_MARKER_PATH
    path = _SESSION_MARKER_PATH
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        _logger.debug('Unable to clear the session marker.', exc_info=True)
    finally:
        _SESSION_MARKER_PATH = None
    _flush_native_stream()


def _report_unclean_previous_sessions() -> tuple[Path, ...]:
    """Turn markers left by processes that are gone into crash reports."""
    written: list[Path] = []
    try:
        markers = sorted(_session_dir().glob('session-*.json'))
    except Exception:
        return ()
    for marker in markers:
        try:
            payload = json.loads(marker.read_text(encoding='utf-8'))
        except Exception:
            payload = {}
        pid = payload.get('pid')
        if pid is None or pid == os.getpid():
            continue
        if _process_is_alive(int(pid)):
            # Another Budget Terminal window is still using this marker.
            continue
        started_at = str(payload.get('started_at') or 'unknown')
        report = write_crash_report(
            'previous-session-aborted',
            f'A previous session (pid {pid}, started {started_at}) ended without a clean shutdown.',
            details={
                'previous_pid': pid,
                'previous_started_at': started_at,
                'previous_environment': payload.get('environment', {}),
            },
            include_thread_dump=False,
            include_native_tail=True,
            pid=int(pid),
        )
        if report is not None:
            written.append(report)
            _logger.error(
                'Previous Budget Terminal session (pid %s) ended unexpectedly. Crash report: %s',
                pid,
                report,
            )
        try:
            marker.unlink(missing_ok=True)
        except Exception:
            _logger.debug('Unable to clear a stale session marker.', exc_info=True)
    return tuple(written)


# --------------------------------------------------------------------------- entry point


def configure_crash_reporting(*, install_qt_handler: bool = True) -> Path:
    """Enable crash diagnostics. Safe to call more than once; never raises."""
    global _CONFIGURED, _RECENT_LOG_HANDLER, _PREVIOUS_SESSION_REPORTS
    if _CONFIGURED:
        return crash_dir()
    _CONFIGURED = True
    try:
        if _RECENT_LOG_HANDLER is None:
            handler = RecentLogBuffer()
            logging.getLogger().addHandler(handler)
            _RECENT_LOG_HANDLER = handler
        enable_native_fault_capture()
        _install_exception_hooks()
        if install_qt_handler:
            install_qt_message_handler()
        _PREVIOUS_SESSION_REPORTS = _report_unclean_previous_sessions()
        _write_session_marker()
        atexit.register(note_clean_shutdown)
    except Exception:
        _logger.warning('Crash reporting could not be fully configured; continuing startup.', exc_info=True)
    try:
        return crash_dir()
    except Exception:
        return Path('.')
