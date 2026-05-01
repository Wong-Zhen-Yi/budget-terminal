from __future__ import annotations

from .dependencies import QApplication, QIcon, logger, pg, sys
from .data_service import EmbeddedDataServiceRuntime
from .paths import resource_path
from .startup_profile import StartupProfiler

def main() -> int:
    """Run the application entry point."""
    profiler = StartupProfiler(logger)
    data_service = EmbeddedDataServiceRuntime()
    data_service.start(timeout_seconds=3.0)
    with profiler.step('qt_app_init'):
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
    app.aboutToQuit.connect(data_service.stop)
    icon_path = resource_path('budget_terminal_app', 'assets', 'app_icon.png')
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    with profiler.step('pyqtgraph_config'):
        pg.setConfigOptions(antialias=True)
    with profiler.step('import_app'):
        from .app import BudgetTerminalApp
    window = BudgetTerminalApp(startup_profiler=profiler, data_service_client=data_service.client)
    window.show()
    profiler.stamp('show_requested')
    try:
        return app.exec()
    finally:
        data_service.stop()
