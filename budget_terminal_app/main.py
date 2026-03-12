from __future__ import annotations
from .app import BudgetTerminalApp
from .compat import QApplication, pg, sys

def main() -> int:
    """Run the application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    pg.setConfigOptions(antialias=True)
    window = BudgetTerminalApp()
    window.show()
    return app.exec()
