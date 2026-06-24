from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


VISIBLE_APP_START_TIMEOUT_MS = 28_000
VISIBLE_APP_POLL_INTERVAL_SECONDS = 0.25


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _activate_existing_app(*, timeout_ms: int = 1500) -> bool:
    from budget_terminal_app.single_instance import send_single_instance_command

    response = send_single_instance_command({"command": "activate"}, timeout_ms=timeout_ms)
    return bool(response and response.get("ok"))


def _wait_for_visible_app(*, timeout_ms: int = VISIBLE_APP_START_TIMEOUT_MS) -> bool:
    deadline = time.monotonic() + max(1, timeout_ms) / 1000.0
    while time.monotonic() < deadline:
        if _activate_existing_app(timeout_ms=750):
            return True
        time.sleep(VISIBLE_APP_POLL_INTERVAL_SECONDS)
    return _activate_existing_app(timeout_ms=750)


def _launch_desktop_app() -> None:
    project_root = _project_root()
    launcher = project_root / "budget_terminal.py"
    env = dict(os.environ)
    env["BUDGET_TERMINAL_SKIP_LOCAL_VENV"] = "1"
    kwargs = {
        "cwd": str(project_root),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(launcher)], **kwargs)


def _ensure_visible_app_running() -> bool:
    if _activate_existing_app(timeout_ms=1500):
        return True

    from PyQt6.QtCore import QLockFile
    from budget_terminal_app.paths import user_data_path

    lock = QLockFile(str(user_data_path("mcp_autostart.lock")))
    lock.setStaleLockTime(15_000)
    if not lock.tryLock(250):
        return _wait_for_visible_app()
    try:
        if _activate_existing_app(timeout_ms=750):
            return True
        _launch_desktop_app()
        return _wait_for_visible_app()
    finally:
        lock.unlock()


def _run_headless_server() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from budget_terminal_app.dpi import configure_qt_high_dpi_policy

    configure_qt_high_dpi_policy()

    from budget_terminal_app.dependencies import QApplication, pg
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.mcp.server import run_server

    QApplication.setApplicationName("BudgetTerminalMCP")
    QApplication.setApplicationDisplayName("Budget Terminal MCP")
    QApplication.setOrganizationName("BudgetTerminal")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    pg.setConfigOptions(antialias=True)
    window = BudgetTerminalApp()
    return run_server(window, app)


def _run_visible_proxy() -> int:
    from budget_terminal_app.dpi import configure_qt_high_dpi_policy

    configure_qt_high_dpi_policy()

    from budget_terminal_app.dependencies import QApplication
    from budget_terminal_app.mcp.server import run_single_instance_proxy

    QApplication.setApplicationName("BudgetTerminalMCP")
    QApplication.setApplicationDisplayName("Budget Terminal MCP")
    QApplication.setOrganizationName("BudgetTerminal")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    _ensure_visible_app_running()
    return run_single_instance_proxy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Budget Terminal as an MCP-controlled Qt application.")
    parser.add_argument("--headless", action="store_true", help="Use Qt's offscreen platform and do not show the window.")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Budget Terminal requires Python 3.10 or newer; use the project's virtual environment.")
    if args.headless:
        return _run_headless_server()
    return _run_visible_proxy()


if __name__ == "__main__":
    raise SystemExit(main())
