from __future__ import annotations

import logging
import threading

from typing import Any

from .dependencies import QApplication, QIcon, QTimer, logger, pg, sys
from .data_service import EmbeddedDataServiceRuntime
from .paths import resource_path
from .startup_loading import StartupLoadingLogHandler, StartupLoadingScreen, StartupProgressReporter
from .startup_profile import StartupProfiler


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


def main() -> int:
    """Run the application entry point."""
    profiler = StartupProfiler(logger)
    data_service = EmbeddedDataServiceRuntime()
    with profiler.step('qt_app_init'):
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
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
    _start_data_service_async(data_service, window)
    startup_progress.begin('first_show', 'First usable view')

    startup_finished = {'done': False}

    def _show_window_when_ready() -> None:
        if startup_finished['done']:
            return
        startup_finished['done'] = True
        try:
            setattr(window, '_startup_ready_before_show', True)
            profiler.stamp('show_requested')
            window.show()
            startup_progress.complete('first_show', 'First usable view')
            _detach_startup_log_handler()
            loading_screen.close()
        except Exception:
            logger.exception('Failed to show the main window after startup preparation.')
            _detach_startup_log_handler()
            loading_screen.close()
            app.quit()

    def _start_hidden_startup() -> None:
        try:
            prepare_startup = getattr(window, '_prepare_startup_before_show', None)
            if callable(prepare_startup):
                prepare_startup()
            else:
                _show_window_when_ready()
        except Exception:
            logger.exception('Hidden startup preparation failed; showing the main window.')
            _show_window_when_ready()

    startup_progress.on_ready(_show_window_when_ready)
    QTimer.singleShot(0, _start_hidden_startup)
    try:
        return app.exec()
    finally:
        _detach_startup_log_handler()
        startup_progress.close()
        data_service.stop()
