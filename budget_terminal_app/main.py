from __future__ import annotations
from .app import BudgetTerminalApp
from .compat import QApplication, QColor, QPalette, Qt, sys

def main() -> int:
    """Run the application entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Button, QColor(50, 50, 50))
    palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    app.setPalette(palette)
    window = BudgetTerminalApp()
    window.show()
    return app.exec()
