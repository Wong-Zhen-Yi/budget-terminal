from __future__ import annotations
from .app import BudgetTerminalApp
from .compat import QApplication, QIcon, pg, sys
from .paths import resource_path

def main() -> int:
    """Run the application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    icon_path = resource_path('budget_terminal_app', 'assets', 'app_icon.png')
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    pg.setConfigOptions(antialias=True)
    window = BudgetTerminalApp()
    window.show()
    return app.exec()
