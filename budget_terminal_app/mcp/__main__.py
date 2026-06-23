from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Budget Terminal as an MCP-controlled Qt application.")
    parser.add_argument("--headless", action="store_true", help="Use Qt's offscreen platform and do not show the window.")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Budget Terminal requires Python 3.10 or newer; use the project's virtual environment.")
    if args.headless:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from budget_terminal_app.dpi import configure_qt_high_dpi_policy
    configure_qt_high_dpi_policy()

    from budget_terminal_app.dependencies import QApplication, QTimer, pg
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.mcp.server import run_server

    QApplication.setApplicationName("BudgetTerminalMCP")
    QApplication.setApplicationDisplayName("Budget Terminal MCP")
    QApplication.setOrganizationName("BudgetTerminal")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    pg.setConfigOptions(antialias=True)
    window = BudgetTerminalApp()
    if not args.headless:
        window.show()

        def activate_window() -> None:
            window.show()
            window.raise_()
            window.activateWindow()

        QTimer.singleShot(0, activate_window)
    return run_server(window, app)


if __name__ == "__main__":
    raise SystemExit(main())
