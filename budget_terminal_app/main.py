from __future__ import annotations

from .dependencies import QApplication, QIcon, logger, pg, sys
from .paths import resource_path
from .startup_profile import StartupProfiler

def main() -> int:
    """Run the application entry point."""
    profiler = StartupProfiler(logger)
    with profiler.step('qt_app_init'):
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
    icon_path = resource_path('budget_terminal_app', 'assets', 'app_icon.png')
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    with profiler.step('pyqtgraph_config'):
        pg.setConfigOptions(antialias=True)
    with profiler.step('import_app'):
        from .app import BudgetTerminalApp
    window = BudgetTerminalApp(startup_profiler=profiler)
    window.show()
    profiler.stamp('show_requested')
    return app.exec()
