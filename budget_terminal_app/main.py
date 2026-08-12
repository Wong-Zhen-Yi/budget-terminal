from __future__ import annotations

import ctypes
import logging
import os
import re
import threading

from typing import Any

from .dependencies import QApplication, QIcon, QMessageBox, QTimer, logger, pg, sys, yf
from .data_service import EmbeddedDataServiceRuntime
from .dpi import configure_qt_high_dpi_policy
from .error_logging import error_log_path
from .paths import resource_path
from .startup_loading import StartupLoadingLogHandler, StartupLoadingScreen, StartupProgressReporter
from .startup_profile import StartupProfiler


APP_USER_MODEL_ID = 'BudgetTerminal.Desktop'
MINIMUM_YFINANCE_VERSION = (1, 5, 2)


def _version_tuple(value: Any) -> tuple[int, int, int]:
    """Return a comparable three-part numeric version tuple."""
    parts = [int(part) for part in re.findall(r'\d+', str(value or ''))[:3]]
    return tuple((parts + [0, 0, 0])[:3])


def _validate_market_data_runtime() -> str:
    """Fail clearly when the active runtime cannot satisfy the supported Yahoo contract."""
    active_version = str(getattr(yf, '__version__', '') or '').strip()
    if _version_tuple(active_version) < MINIMUM_YFINANCE_VERSION:
        required = '.'.join(str(part) for part in MINIMUM_YFINANCE_VERSION)
        raise RuntimeError(
            f'Budget Terminal requires yfinance {required} or newer; found {active_version or "unknown"}. '
            'Launch with .\\.venv\\Scripts\\python.exe budget_terminal.py after installing requirements.txt.'
        )
    logger.info('Validated yfinance runtime version %s.', active_version)
    return active_version


def _configure_windows_app_identity() -> None:
    """Set a stable Windows taskbar identity before QApplication is created."""
    if sys.platform != 'win32':
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        logger.debug('Unable to set Windows AppUserModelID.', exc_info=True)


def _show_fatal_startup_error(error: BaseException) -> None:
    """Explain a fatal pre-window failure without hiding the persistent log path."""
    if isinstance(error, ModuleNotFoundError):
        missing_module = error.name or 'a required package'
        detail = (
            f'Missing dependency: {missing_module}\n\n'
            'Install project requirements with:\n'
            'python -m pip install -r requirements.txt'
        )
    else:
        detail = f'{type(error).__name__}: {error}'
    message = (
        'Budget Terminal could not finish starting.\n\n'
        f'{detail}\n\n'
        f'Error log: {error_log_path()}'
    )
    if str(os.environ.get('QT_QPA_PLATFORM', '') or '').strip().lower() == 'offscreen':
        return
    try:
        QMessageBox.critical(None, 'Budget Terminal Startup Error', message)
    except Exception:
        logger.debug('Unable to display the startup error dialog.', exc_info=True)


def _start_data_service_async(data_service: EmbeddedDataServiceRuntime, window: Any) -> threading.Thread:
    """Start the embedded data service without delaying first paint."""
    window._data_service_startup_pending = True

    def _finish_startup(client: Any = None) -> None:
        window._data_service_client = client
        window._data_service_startup_pending = False

    def _run() -> None:
        try:
            if not data_service.start(timeout_seconds=3.0):
                logger.warning('Embedded data service is unavailable; using direct workers.')
                try:
                    window._invoke_main.emit(lambda: _finish_startup(None))
                except RuntimeError:
                    logger.debug('Window closed before embedded data service failure could be recorded.')
                return
            client = data_service.client
            if client is None:
                logger.warning('Embedded data service started without a client; using direct workers.')
                try:
                    window._invoke_main.emit(lambda: _finish_startup(None))
                except RuntimeError:
                    logger.debug('Window closed before embedded data service failure could be recorded.')
                return
            try:
                window._invoke_main.emit(lambda: _finish_startup(client))
            except RuntimeError:
                logger.debug('Window closed before embedded data service client could be attached.')
        except Exception:
            logger.exception('Embedded data service background startup failed.')
            try:
                window._invoke_main.emit(lambda: _finish_startup(None))
            except RuntimeError:
                logger.debug('Window closed before embedded data service exception could be recorded.')

    thread = threading.Thread(target=_run, name='BudgetTerminalDataServiceStartup', daemon=True)
    thread.start()
    return thread


def _run_primary_application(
    app: QApplication,
    profiler: StartupProfiler,
    data_service: EmbeddedDataServiceRuntime,
) -> int:
    """Construct and run one independent desktop application instance."""
    loading_screen: StartupLoadingScreen | None = None
    startup_progress: StartupProgressReporter | None = None
    startup_log_handler: StartupLoadingLogHandler | None = None

    def _detach_startup_log_handler() -> None:
        nonlocal startup_log_handler
        if startup_log_handler is None:
            return
        logger.removeHandler(startup_log_handler)
        startup_log_handler.close()
        startup_log_handler = None

    try:
        loading_screen = StartupLoadingScreen()
        startup_progress = StartupProgressReporter(loading_screen)
        startup_log_handler = StartupLoadingLogHandler(loading_screen)
        startup_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(startup_log_handler)
        loading_screen.show()
        logger.info('Startup loading screen initialized.')
        startup_progress.complete('qt_app_init', 'Qt application')
        app.aboutToQuit.connect(data_service.stop)
        startup_progress.begin('app_icon', 'Application icon')
        icon_path = resource_path('budget_terminal_app', 'assets', 'app_icon.png')
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        startup_progress.complete('app_icon', 'Application icon')
        startup_progress.begin('pyqtgraph_config', 'Chart engine')
        with profiler.step('pyqtgraph_config'):
            pg.setConfigOptions(antialias=True)
        startup_progress.complete('pyqtgraph_config', 'Chart engine')
        startup_progress.begin('import_app', 'Application modules')
        with profiler.step('import_app'):
            from .app import BudgetTerminalApp
        startup_progress.complete('import_app', 'Application modules')
        window = BudgetTerminalApp(
            startup_profiler=profiler,
            data_service_client=None,
            startup_progress=startup_progress,
        )

        def _close_window_data_services() -> None:
            for attribute in ('_chart_data_service', '_options_data_service'):
                service = getattr(window, attribute, None)
                close = getattr(service, 'close', None)
                if callable(close):
                    try:
                        close()
                    except Exception as exc:
                        logger.debug('Unable to close %s cleanly: %s', attribute, exc)

        app.aboutToQuit.connect(_close_window_data_services)

        _start_data_service_async(data_service, window)
        startup_progress.begin('first_show', 'First usable view')

        startup_finished = {'done': False}

        def _show_window_when_ready(reason: str = 'complete') -> None:
            if startup_finished['done']:
                return
            startup_finished['done'] = True
            try:
                clean_reason = str(reason or 'complete').strip().lower()
                setattr(window, '_startup_release_reason', clean_reason)
                setattr(window, '_startup_released_to_user', True)
                setattr(window, '_startup_ready_before_show', True)
                if clean_reason == 'skip':
                    logger.info('Startup loading skipped by user; remaining startup work will continue in the background.')
                elif clean_reason == 'timeout':
                    logger.warning('Startup loading reached 30s max wait; opening app while remaining work continues.')
                profiler.stamp('show_requested')
                window.show()
                startup_progress.complete('first_show', 'First usable view')
                _detach_startup_log_handler()
                loading_screen.close()
            except Exception:
                logger.exception('Failed to show the main window after startup preparation.')
                _detach_startup_log_handler()
                loading_screen.close()
                app.exit(1)

        def _start_hidden_startup() -> None:
            try:
                prepare_startup = getattr(window, '_prepare_startup_before_show', None)
                if callable(prepare_startup):
                    prepare_startup()
                else:
                    _show_window_when_ready()
            except Exception:
                logger.exception('Hidden startup preparation failed; showing the main window.')
                _show_window_when_ready('startup_error')

        startup_progress.on_ready(lambda: _show_window_when_ready('complete'))
        startup_progress.on_skip(lambda: _show_window_when_ready('skip'))
        QTimer.singleShot(30000, lambda: _show_window_when_ready('timeout'))
        QTimer.singleShot(0, _start_hidden_startup)
        return app.exec()
    finally:
        _detach_startup_log_handler()
        if startup_progress is not None:
            startup_progress.close()
        elif loading_screen is not None:
            loading_screen.close()
        data_service.stop()


def main() -> int:
    """Run one independent Budget Terminal application instance."""
    profiler = StartupProfiler(logger)
    try:
        with profiler.step('qt_app_init'):
            _configure_windows_app_identity()
            configure_qt_high_dpi_policy()
            app = QApplication(sys.argv)
            app.setStyle('Fusion')
    except Exception:
        logger.exception('Qt application initialization failed.')
        return 1

    data_service: EmbeddedDataServiceRuntime | None = None
    try:
        _validate_market_data_runtime()
        data_service = EmbeddedDataServiceRuntime()
        return _run_primary_application(app, profiler, data_service)
    except Exception as exc:
        logger.exception('Budget Terminal startup failed before the main event loop completed.')
        if data_service is not None:
            try:
                data_service.stop()
            except Exception:
                logger.debug('Data service cleanup after startup failure did not complete.', exc_info=True)
        _show_fatal_startup_error(exc)
        return 1
