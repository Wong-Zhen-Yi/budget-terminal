from __future__ import annotations

import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
from types import TracebackType
from typing import Any

ERROR_LOG_DIR_NAME = 'logs'
ERROR_LOG_FILE_NAME_FORMAT = 'errors-{month}.log'
ERROR_LOG_MAX_BYTES = 1024 * 1024
ERROR_LOG_BACKUP_COUNT = 5
ERROR_LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_ERROR_LOG_HANDLER_ATTR = '_budget_terminal_error_log_path'
_ERROR_LOG_HANDLER_DIR_ATTR = '_budget_terminal_error_log_dir'

_ORIGINAL_SYS_EXCEPTHOOK: Any = None
_ORIGINAL_THREADING_EXCEPTHOOK: Any = None
_HOOKS_INSTALLED = False


def _runtime_root() -> Path:
    """Return the writable application root for source and frozen launches."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def error_log_path() -> Path:
    """Return the repo-local persistent error log path."""
    month = _current_month_key()
    return _runtime_root() / ERROR_LOG_DIR_NAME / _error_log_file_name(month)


def _current_month_key() -> str:
    return datetime.datetime.now().strftime('%Y-%m')


def _error_log_file_name(month: str) -> str:
    return ERROR_LOG_FILE_NAME_FORMAT.format(month=month)


class _MonthlyRotatingFileHandler(RotatingFileHandler):
    """Size-rotating error handler that switches files at month boundaries."""

    def __init__(
        self,
        log_dir: Path,
        *,
        max_bytes: int,
        backup_count: int,
        encoding: str = 'utf-8',
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_month = _current_month_key()
        super().__init__(
            self._path_for_month(self._current_month),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )

    def _path_for_month(self, month: str) -> str:
        return os.fspath(self.log_dir / _error_log_file_name(month))

    def _switch_to_current_month_if_needed(self) -> None:
        month = _current_month_key()
        if month == self._current_month:
            return
        self._current_month = month
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = os.path.abspath(self._path_for_month(month))

    def emit(self, record: logging.LogRecord) -> None:
        self._switch_to_current_month_if_needed()
        super().emit(record)


def _ensure_root_logger_ready() -> None:
    """Keep existing INFO-level app logging behavior active after early setup."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    root_logger = logging.getLogger()
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)


def _has_error_file_handler(root_logger: logging.Logger, log_dir: Path) -> bool:
    target_dir = str(log_dir.resolve(strict=False))
    for handler in root_logger.handlers:
        handler_dir = getattr(handler, _ERROR_LOG_HANDLER_DIR_ATTR, None)
        if handler_dir and str(handler_dir) == target_dir:
            return True
        handler_path = getattr(handler, _ERROR_LOG_HANDLER_ATTR, None)
        if handler_path and str(Path(handler_path).parent.resolve(strict=False)) == target_dir:
            return True
    return False


def _attach_error_file_handler(path: Path) -> None:
    root_logger = logging.getLogger()
    log_dir = path.parent
    if _has_error_file_handler(root_logger, log_dir):
        return
    handler = _MonthlyRotatingFileHandler(
        log_dir,
        max_bytes=ERROR_LOG_MAX_BYTES,
        backup_count=ERROR_LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter(ERROR_LOG_FORMAT))
    setattr(handler, _ERROR_LOG_HANDLER_ATTR, str(path.resolve(strict=False)))
    setattr(handler, _ERROR_LOG_HANDLER_DIR_ATTR, str(log_dir.resolve(strict=False)))
    root_logger.addHandler(handler)


def _log_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    logging.getLogger(__name__).critical(
        'Uncaught exception in main thread.',
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def _install_exception_hooks() -> None:
    global _HOOKS_INSTALLED, _ORIGINAL_SYS_EXCEPTHOOK, _ORIGINAL_THREADING_EXCEPTHOOK
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True
    _ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
    _ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, 'excepthook', None)

    def _sys_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        _log_uncaught_exception(exc_type, exc_value, exc_traceback)
        if _ORIGINAL_SYS_EXCEPTHOOK is not None:
            _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, KeyboardInterrupt):
            thread_name = getattr(args.thread, 'name', 'unknown')
            logging.getLogger(__name__).critical(
                'Uncaught exception in thread %s.',
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        if _ORIGINAL_THREADING_EXCEPTHOOK is not None:
            _ORIGINAL_THREADING_EXCEPTHOOK(args)

    sys.excepthook = _sys_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _threading_excepthook


def configure_error_logging() -> Path:
    """Configure repo-local persistent error logging and uncaught hooks."""
    path = error_log_path()
    _ensure_root_logger_ready()
    _attach_error_file_handler(path)
    _install_exception_hooks()
    return path
