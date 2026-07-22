from __future__ import annotations

import ctypes
import logging
import os
import threading
import time

from typing import Any

from .dependencies import QApplication, QIcon, QMessageBox, QTimer, logger, pg, sys
from .data_service import EmbeddedDataServiceRuntime
from .dpi import configure_qt_high_dpi_policy
from .error_logging import error_log_path
from .paths import resource_path
from .single_instance import (
    BudgetTerminalInstanceOwnership,
    BudgetTerminalSingleInstanceServer,
    QueuedActivation,
    activate_existing_instance,
    activate_qt_window,
    make_window_command_handler,
)
from .startup_loading import StartupLoadingLogHandler, StartupLoadingScreen, StartupProgressReporter
from .startup_profile import StartupProfiler


APP_USER_MODEL_ID = 'BudgetTerminal.Desktop'
INSTANCE_SHUTDOWN_WAIT_MS = 90_000


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


def _report_unconfirmed_existing_instance(detail: str) -> int:
    """Report an ownership conflict that could not activate a live window."""
    error = RuntimeError(
        f'{detail} Budget Terminal may still be starting or shutting down. '
        'Wait a few seconds and try again.'
    )
    logger.error('%s', error)
    _show_fatal_startup_error(error)
    return 1


def _show_instance_shutdown_wait_dialog() -> Any:
    """Show a cancellable notice while a previous process finishes shutting down."""
    if str(os.environ.get('QT_QPA_PLATFORM', '') or '').strip().lower() == 'offscreen':
        return None
    try:
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle('Budget Terminal')
        dialog.setText('The previous Budget Terminal session is still closing.')
        dialog.setInformativeText('Waiting for background work to stop. The app will reopen automatically.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
        dialog.setModal(False)
        dialog.show()
        return dialog
    except Exception:
        logger.debug('Unable to display the previous-session shutdown notice.', exc_info=True)
        return None


def _wait_for_existing_instance_resolution(
    app: QApplication,
    ownership: BudgetTerminalInstanceOwnership,
    *,
    timeout_ms: int = INSTANCE_SHUTDOWN_WAIT_MS,
) -> str:
    """Wait for a closing primary to exit, or activate it if its IPC endpoint returns."""
    wait_seconds = max(0.1, int(timeout_ms) / 1000.0)
    deadline = time.monotonic() + wait_seconds
    next_activation_attempt = time.monotonic() + 0.5
    quit_on_last_window_closed = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    dialog = _show_instance_shutdown_wait_dialog()
    logger.warning('Previous Budget Terminal process is still shutting down; waiting up to %.1fs.', wait_seconds)
    try:
        while time.monotonic() < deadline:
            try:
                if ownership.try_acquire():
                    logger.info('Previous Budget Terminal process exited; continuing the pending launch.')
                    return 'acquired'
            except Exception:
                logger.exception('Unable to retry Budget Terminal instance ownership.')
                return 'failed'

            now = time.monotonic()
            if now >= next_activation_attempt:
                if activate_existing_instance(timeout_ms=250, retry_interval_ms=50):
                    logger.info('Activated the existing Budget Terminal window while waiting for shutdown.')
                    return 'activated'
                next_activation_attempt = time.monotonic() + 0.75

            try:
                app.processEvents()
            except Exception:
                logger.debug('Unable to process events while waiting for the previous instance.', exc_info=True)
            if dialog is not None and not dialog.isVisible():
                logger.info('Pending Budget Terminal relaunch cancelled by the user.')
                return 'cancelled'
            time.sleep(0.05)
        return 'timeout'
    finally:
        if dialog is not None:
            dialog.close()
        app.setQuitOnLastWindowClosed(quit_on_last_window_closed)


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
    single_instance_server: BudgetTerminalSingleInstanceServer,
    activation: QueuedActivation,
) -> int:
    """Construct and run the primary desktop application after ownership is secured."""
    loading_screen = StartupLoadingScreen()
    startup_progress = StartupProgressReporter(loading_screen)
    startup_log_handler = StartupLoadingLogHandler(loading_screen)
    startup_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(startup_log_handler)

    def _detach_startup_log_handler() -> None:
        nonlocal startup_log_handler
        if startup_log_handler is None:
            return
        logger.removeHandler(startup_log_handler)
        startup_log_handler.close()
        startup_log_handler = None

    window: Any = None

    def _activate_primary_window() -> bool:
        target = window if window is not None and window.isVisible() else loading_screen
        activated = activate_qt_window(target, repeat_ms=150)
        if target is loading_screen and window is not None and window.isVisible():
            activated = activate_qt_window(window, repeat_ms=150) or activated
        return activated

    loading_screen.show()
    activation.set_callback(_activate_primary_window)
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
    setattr(window, '_single_instance_server', single_instance_server)

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
    try:
        return app.exec()
    finally:
        activation.clear_callback()
        _detach_startup_log_handler()
        startup_progress.close()
        data_service.stop()


def main() -> int:
    """Run the application entry point."""
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

    try:
        ownership = BudgetTerminalInstanceOwnership()
        acquired_ownership = ownership.try_acquire()
        if acquired_ownership:
            ownership.hold_until_process_exit()
    except Exception as exc:
        logger.exception('Budget Terminal instance ownership could not be initialized.')
        _show_fatal_startup_error(exc)
        return 1
    if not acquired_ownership:
        if activate_existing_instance():
            logger.info('Activated an existing Budget Terminal instance; exiting duplicate launcher.')
            return 0
        resolution = _wait_for_existing_instance_resolution(app, ownership)
        if resolution == 'activated':
            return 0
        if resolution == 'cancelled':
            return 0
        if resolution == 'acquired':
            acquired_ownership = True
            ownership.hold_until_process_exit()
        else:
            return _report_unconfirmed_existing_instance(
                'Another Budget Terminal process owns the launch lock, but its window could not be activated '
                f'or finish shutting down within {INSTANCE_SHUTDOWN_WAIT_MS // 1000} seconds.'
            )

    activation = QueuedActivation()
    single_instance_server = BudgetTerminalSingleInstanceServer(
        command_handler=make_window_command_handler(
            activate_callback=activation.request,
        ),
        activate_callback=activation.request,
        ownership=ownership,
        parent=app,
    )
    data_service: EmbeddedDataServiceRuntime | None = None
    try:
        if not single_instance_server.start():
            if single_instance_server.live_endpoint_detected:
                if activate_existing_instance():
                    logger.info('Activated a live Budget Terminal IPC endpoint; exiting duplicate launcher.')
                    return 0
                return _report_unconfirmed_existing_instance(
                    'A live Budget Terminal IPC endpoint was detected, but its window could not be activated.'
                )
            logger.warning(
                'Budget Terminal single-instance IPC server could not be started; '
                'the exclusive process lock will still prevent duplicate windows.'
            )
        data_service = EmbeddedDataServiceRuntime()
        return _run_primary_application(
            app,
            profiler,
            data_service,
            single_instance_server,
            activation,
        )
    except Exception as exc:
        logger.exception('Budget Terminal startup failed before the main event loop completed.')
        if data_service is not None:
            try:
                data_service.stop()
            except Exception:
                logger.debug('Data service cleanup after startup failure did not complete.', exc_info=True)
        _show_fatal_startup_error(exc)
        return 1
    finally:
        try:
            single_instance_server.close()
        except Exception:
            logger.debug('Single-instance IPC server cleanup failed.', exc_info=True)
