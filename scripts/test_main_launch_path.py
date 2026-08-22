"""Hermetic process-level regressions for the real desktop launch path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_RESULT_PREFIX = "BUDGET_TERMINAL_TEST_RESULT="


def _isolated_environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "LOCALAPPDATA": str(root / "local"),
            "APPDATA": str(root / "roaming"),
            "USERPROFILE": str(root / "profile"),
        }
    )
    return env


def _wait_for_paths(paths: tuple[Path, ...], *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if all(path.exists() for path in paths):
            return
        time.sleep(0.01)
    missing = [str(path) for path in paths if not path.exists()]
    raise AssertionError(f"timed out waiting for child-process signals: {missing}")


def _emit_result(payload: dict[str, Any]) -> None:
    print(f"{_RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)


def _parse_child_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if completed.returncode != 0:
        raise AssertionError(
            f"child exited with {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line.removeprefix(_RESULT_PREFIX))
            if isinstance(payload, dict):
                return payload
    raise AssertionError(
        f"child did not emit a structured result\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _run_child(mode: str, *, env: dict[str, str], timeout_seconds: float = 20.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), mode],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"{mode} child hung for more than {timeout_seconds:.0f}s") from exc
    return _parse_child_result(completed)


def _close_qt_windows(qapplication: Any) -> None:
    app = qapplication.instance()
    if app is None:
        return
    app.closeAllWindows()
    app.processEvents()


def _failure_main_child() -> int:
    import budget_terminal_app.main as main_module
    from budget_terminal_app.startup_loading import StartupLoadingLogHandler

    dialog_calls: list[str] = []
    data_service_stop_calls: list[bool] = []
    fake_app_module = types.ModuleType("budget_terminal_app.app")

    class FakeDataService:
        def stop(self) -> None:
            data_service_stop_calls.append(True)

    class FailingBudgetTerminalApp:
        def __init__(self, **_kwargs: Any) -> None:
            raise RuntimeError("intentional BudgetTerminalApp construction failure")

    class NoDialog:
        @staticmethod
        def critical(*_args: Any, **_kwargs: Any) -> None:
            dialog_calls.append("critical")

    fake_app_module.BudgetTerminalApp = FailingBudgetTerminalApp
    sys.modules["budget_terminal_app.app"] = fake_app_module
    main_module.EmbeddedDataServiceRuntime = FakeDataService
    main_module.QMessageBox = NoDialog

    handlers_before = sum(isinstance(handler, StartupLoadingLogHandler) for handler in main_module.logger.handlers)
    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at
    handlers_after = sum(isinstance(handler, StartupLoadingLogHandler) for handler in main_module.logger.handlers)
    _close_qt_windows(main_module.QApplication)

    _emit_result(
        {
            "dialog_calls": len(dialog_calls),
            "data_service_stop_calls": len(data_service_stop_calls),
            "elapsed_seconds": elapsed_seconds,
            "exit_code": exit_code,
            "startup_log_handlers_after": handlers_after,
            "startup_log_handlers_before": handlers_before,
        }
    )
    return 0


def _ready_main_child() -> int:
    import budget_terminal_app.main as main_module
    from PySide6.QtCore import QTimer as RealQTimer
    from PySide6.QtWidgets import QWidget

    from budget_terminal_app.startup_loading import REQUIRED_STARTUP_TASK_KEYS

    state: dict[str, Any] = {
        "constructed": False,
        "hold_fired": False,
        "hold_registered": False,
        "prepare_calls": 0,
        "show_calls": 0,
    }
    fake_app_module = types.ModuleType("budget_terminal_app.app")

    class FakeDataService:
        def stop(self) -> None:
            state["data_service_stop_calls"] = state.get("data_service_stop_calls", 0) + 1

    class DeterministicTimer:
        @staticmethod
        def singleShot(delay_ms: int, callback: Any) -> None:
            if int(delay_ms) == main_module.STARTUP_HOLD_MS:
                # The startup hold is the only release path; drive it by hand so the test does
                # not wait 30 real seconds, and so it can prove nothing opened before it fired.
                state["hold_registered"] = True

                def fire_hold() -> None:
                    state["hold_fired"] = True
                    callback()

                state["hold_callback"] = fire_hold
                return
            RealQTimer.singleShot(int(delay_ms), callback)

    class ReadyBudgetTerminalApp(QWidget):
        def __init__(self, *, startup_progress: Any, **_kwargs: Any) -> None:
            super().__init__()
            self._startup_progress = startup_progress
            state["constructed"] = True

        def _prepare_startup_before_show(self) -> None:
            state["prepare_calls"] += 1
            screen = self._startup_progress.screen
            assert screen is not None
            for key in REQUIRED_STARTUP_TASK_KEYS:
                self._startup_progress.complete(key, key)
            for page_key in tuple(screen._page_keys):
                screen.complete_task(page_key, page_key)
            state["loader_finished"] = self._startup_progress.finish_if_complete()
            # Completing every required task must not open the window on its own.
            state["show_calls_before_hold"] = state["show_calls"]
            RealQTimer.singleShot(0, state["hold_callback"])

        def show(self) -> None:
            super().show()
            state["show_calls"] += 1
            state["release_reason"] = getattr(self, "_startup_release_reason", None)
            state["ready_before_show"] = getattr(self, "_startup_ready_before_show", False)
            state["visible_when_shown"] = self.isVisible()
            app = main_module.QApplication.instance()
            assert app is not None
            RealQTimer.singleShot(0, app.quit)

    def skip_data_service_start(_data_service: Any, window: Any) -> None:
        state["data_service_start_bypassed"] = True
        window._data_service_startup_pending = False
        window._data_service_client = None

    fake_app_module.BudgetTerminalApp = ReadyBudgetTerminalApp
    sys.modules["budget_terminal_app.app"] = fake_app_module
    main_module.EmbeddedDataServiceRuntime = FakeDataService
    main_module.QTimer = DeterministicTimer
    main_module._start_data_service_async = skip_data_service_start

    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at

    _close_qt_windows(main_module.QApplication)
    state.pop("hold_callback", None)
    state.update({"elapsed_seconds": elapsed_seconds, "exit_code": exit_code})
    _emit_result(state)
    return 0


def _early_failure_main_child() -> int:
    import budget_terminal_app.main as main_module

    state = {
        "data_service_stop_calls": 0,
        "handler_close_calls": 0,
        "progress_close_calls": 0,
        "screen_close_calls": 0,
    }

    class FakeDataService:
        def stop(self) -> None:
            state["data_service_stop_calls"] += 1

    class FakeLoadingScreen:
        def close(self) -> None:
            state["screen_close_calls"] += 1

    class FakeProgressReporter:
        def __init__(self, _screen: Any) -> None:
            return

        def close(self) -> None:
            state["progress_close_calls"] += 1

    class FailingLogHandler:
        def __init__(self, _screen: Any) -> None:
            return

        def setFormatter(self, _formatter: Any) -> None:
            raise RuntimeError("intentional startup log formatter failure")

        def close(self) -> None:
            state["handler_close_calls"] += 1

    main_module.EmbeddedDataServiceRuntime = FakeDataService
    main_module.StartupLoadingScreen = FakeLoadingScreen
    main_module.StartupProgressReporter = FakeProgressReporter
    main_module.StartupLoadingLogHandler = FailingLogHandler

    exit_code = main_module.main()
    _close_qt_windows(main_module.QApplication)
    state["exit_code"] = exit_code
    _emit_result(state)
    return 0


def _concurrent_main_child() -> int:
    import budget_terminal_app.main as main_module

    ready_path = Path(os.environ["BT_TEST_READY_PATH"])
    release_path = Path(os.environ["BT_TEST_RELEASE_PATH"])

    class FakeDataService:
        def stop(self) -> None:
            return

    def run_until_released(*_args: Any, **_kwargs: Any) -> int:
        ready_path.write_text(str(os.getpid()), encoding="utf-8")
        _wait_for_paths((release_path,), timeout_seconds=10.0)
        return 0

    main_module.EmbeddedDataServiceRuntime = FakeDataService
    main_module._run_primary_application = run_until_released

    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at
    _close_qt_windows(main_module.QApplication)
    _emit_result({"exit_code": exit_code, "elapsed_seconds": elapsed_seconds})
    return 0


def test_main_failure_returns_one(root: Path) -> None:
    result = _run_child("--failure-main-child", env=_isolated_environment(root / "construction-failure"))
    assert result["exit_code"] == 1, result
    assert result["dialog_calls"] == 0, result
    assert result["data_service_stop_calls"] >= 1, result
    assert result["startup_log_handlers_after"] == result["startup_log_handlers_before"], result
    assert result["elapsed_seconds"] < 10.0, result


def test_main_holds_window_until_the_startup_hold_elapses(root: Path) -> None:
    result = _run_child("--ready-main-child", env=_isolated_environment(root / "ready-path"))
    assert result["exit_code"] == 0, result
    assert result["constructed"] is True, result
    assert result["prepare_calls"] == 1, result
    assert result["loader_finished"] is True, result
    assert result["hold_registered"] is True, result
    assert result["show_calls_before_hold"] == 0, result
    assert result["hold_fired"] is True, result
    assert result["show_calls"] == 1, result
    assert result["visible_when_shown"] is True, result
    assert result["release_reason"] == "complete", result
    assert result["ready_before_show"] is True, result
    assert result["data_service_start_bypassed"] is True, result
    assert result["elapsed_seconds"] < 10.0, result


def test_early_startup_failure_closes_partially_initialized_resources(root: Path) -> None:
    result = _run_child("--early-failure-main-child", env=_isolated_environment(root / "early-failure"))
    assert result["exit_code"] == 1, result
    assert result["handler_close_calls"] == 1, result
    assert result["progress_close_calls"] == 1, result
    assert result["screen_close_calls"] == 0, result
    assert result["data_service_stop_calls"] >= 1, result


def test_two_launches_enter_application_concurrently(root: Path) -> None:
    case_root = root / "concurrent-launches"
    case_root.mkdir(parents=True)
    release_path = case_root / "release"
    ready_paths = (case_root / "ready-0", case_root / "ready-1")
    processes: list[subprocess.Popen[str]] = []
    completed_processes: list[subprocess.CompletedProcess[str]] = []

    try:
        for ready_path in ready_paths:
            env = _isolated_environment(case_root)
            env.update(
                {
                    "BT_TEST_READY_PATH": str(ready_path),
                    "BT_TEST_RELEASE_PATH": str(release_path),
                }
            )
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--concurrent-main-child"],
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )

        _wait_for_paths(ready_paths, timeout_seconds=5.0)
    finally:
        release_path.write_text("release", encoding="utf-8")
        for process in processes:
            try:
                stdout, stderr = process.communicate(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            completed_processes.append(
                subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
            )

    for completed in completed_processes:
        result = _parse_child_result(completed)
        assert result["exit_code"] == 0, result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="budget-terminal-main-launch-") as temp_dir:
        root = Path(temp_dir)
        test_two_launches_enter_application_concurrently(root)
        test_early_startup_failure_closes_partially_initialized_resources(root)
        test_main_failure_returns_one(root)
        test_main_holds_window_until_the_startup_hold_elapses(root)
    print("PASS concurrent launch, startup failure, and startup-hold release paths")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--failure-main-child":
        raise SystemExit(_failure_main_child())
    if mode == "--ready-main-child":
        raise SystemExit(_ready_main_child())
    if mode == "--early-failure-main-child":
        raise SystemExit(_early_failure_main_child())
    if mode == "--concurrent-main-child":
        raise SystemExit(_concurrent_main_child())
    raise SystemExit(main())
