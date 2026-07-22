"""Hermetic process-level regressions for the real desktop launch path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
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


def _ownership_child() -> int:
    start_path = Path(os.environ["BT_TEST_START_PATH"])
    release_path = Path(os.environ["BT_TEST_RELEASE_PATH"])
    ready_path = Path(os.environ["BT_TEST_READY_PATH"])
    result_path = Path(os.environ["BT_TEST_OWNERSHIP_RESULT_PATH"])

    from budget_terminal_app.single_instance import BudgetTerminalInstanceOwnership

    ownership = BudgetTerminalInstanceOwnership()
    ready_path.write_text("ready", encoding="utf-8")
    _wait_for_paths((start_path,), timeout_seconds=10.0)
    acquired = ownership.try_acquire()
    result_path.write_text(
        json.dumps({"pid": os.getpid(), "acquired": acquired}),
        encoding="utf-8",
    )
    try:
        if acquired:
            _wait_for_paths((release_path,), timeout_seconds=10.0)
    finally:
        ownership.release()
    return 0


def _acquire_once_child() -> int:
    from budget_terminal_app.single_instance import BudgetTerminalInstanceOwnership

    ownership = BudgetTerminalInstanceOwnership()
    acquired = ownership.try_acquire()
    ownership.release()
    _emit_result({"acquired": acquired})
    return 0


def _close_qt_windows(qapplication: Any) -> None:
    app = qapplication.instance()
    if app is None:
        return
    app.closeAllWindows()
    app.processEvents()


def _failure_main_child() -> int:
    import budget_terminal_app.main as main_module
    from budget_terminal_app.single_instance import BudgetTerminalInstanceOwnership

    dialog_calls: list[str] = []
    fake_app_module = types.ModuleType("budget_terminal_app.app")

    class FailingBudgetTerminalApp:
        def __init__(self, **_kwargs: Any) -> None:
            raise RuntimeError("intentional BudgetTerminalApp construction failure")

    class NoDialog:
        @staticmethod
        def critical(*_args: Any, **_kwargs: Any) -> None:
            dialog_calls.append("critical")

    fake_app_module.BudgetTerminalApp = FailingBudgetTerminalApp
    sys.modules["budget_terminal_app.app"] = fake_app_module
    main_module.QMessageBox = NoDialog

    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at

    next_owner = BudgetTerminalInstanceOwnership()
    ownership_reacquired_before_process_exit = next_owner.try_acquire()
    next_owner.release()
    _close_qt_windows(main_module.QApplication)

    _emit_result(
        {
            "dialog_calls": len(dialog_calls),
            "elapsed_seconds": elapsed_seconds,
            "exit_code": exit_code,
            "ownership_reacquired_before_process_exit": ownership_reacquired_before_process_exit,
        }
    )
    return 0


def _ready_main_child() -> int:
    import budget_terminal_app.main as main_module
    from PyQt6.QtCore import QTimer as RealQTimer
    from PyQt6.QtWidgets import QWidget

    from budget_terminal_app.single_instance import BudgetTerminalInstanceOwnership
    from budget_terminal_app.startup_loading import REQUIRED_STARTUP_TASK_KEYS

    state: dict[str, Any] = {
        "constructed": False,
        "fallback_fired": False,
        "prepare_calls": 0,
        "show_calls": 0,
        "timeout_registered": False,
    }
    fake_app_module = types.ModuleType("budget_terminal_app.app")

    class FakeDataService:
        def stop(self) -> None:
            state["data_service_stop_calls"] = state.get("data_service_stop_calls", 0) + 1

    class DeterministicTimer:
        @staticmethod
        def singleShot(delay_ms: int, callback: Any) -> None:
            if int(delay_ms) == 30000:
                state["timeout_registered"] = True

                def mark_fallback() -> None:
                    state["fallback_fired"] = True
                    callback()

                state["fallback_callback"] = mark_fallback
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

    next_owner = BudgetTerminalInstanceOwnership()
    ownership_reacquired_before_process_exit = next_owner.try_acquire()
    next_owner.release()
    _close_qt_windows(main_module.QApplication)

    state.pop("fallback_callback", None)
    state.update(
        {
            "elapsed_seconds": elapsed_seconds,
            "exit_code": exit_code,
            "ownership_reacquired_before_process_exit": ownership_reacquired_before_process_exit,
        }
    )
    _emit_result(state)
    return 0


def _shutdown_tail_main_child() -> int:
    from concurrent.futures import ThreadPoolExecutor

    import budget_terminal_app.main as main_module

    from budget_terminal_app.single_instance import BudgetTerminalInstanceOwnership

    worker_started_path = Path(os.environ["BT_TEST_WORKER_STARTED_PATH"])
    main_returned_path = Path(os.environ["BT_TEST_MAIN_RETURNED_PATH"])
    worker_release_path = Path(os.environ["BT_TEST_WORKER_RELEASE_PATH"])
    executors: list[ThreadPoolExecutor] = []

    class FakeDataService:
        def stop(self) -> None:
            return

    def run_until_qt_exits(
        _app: Any,
        _profiler: Any,
        _data_service: Any,
        _single_instance_server: Any,
        _activation: Any,
    ) -> int:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="BudgetTerminalShutdownTailTest")
        executors.append(executor)

        def block_during_shutdown() -> None:
            worker_started_path.write_text("started", encoding="utf-8")
            deadline = time.monotonic() + 30.0
            while not worker_release_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)

        executor.submit(block_during_shutdown)
        _wait_for_paths((worker_started_path,), timeout_seconds=5.0)
        return 0

    main_module.EmbeddedDataServiceRuntime = FakeDataService
    main_module._run_primary_application = run_until_qt_exits

    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at
    main_returned_path.write_text("returned", encoding="utf-8")

    next_owner = BudgetTerminalInstanceOwnership()
    ownership_reacquired_before_process_exit = next_owner.try_acquire()
    next_owner.release()

    for executor in executors:
        executor.shutdown(wait=False, cancel_futures=False)
    _emit_result(
        {
            "elapsed_seconds": elapsed_seconds,
            "exit_code": exit_code,
            "ownership_reacquired_before_process_exit": ownership_reacquired_before_process_exit,
        }
    )
    return 0


def _contended_main_child() -> int:
    import budget_terminal_app.main as main_module

    fatal_errors: list[str] = []
    primary_runs: list[bool] = []
    real_activate_existing_instance = main_module.activate_existing_instance
    real_wait_for_resolution = main_module._wait_for_existing_instance_resolution
    wait_started_path = Path(os.environ["BT_TEST_WAIT_STARTED_PATH"])

    def activate_with_short_timeout(*_args: Any, **_kwargs: Any) -> bool:
        return real_activate_existing_instance(timeout_ms=250, retry_interval_ms=25)

    def capture_fatal_error(error: BaseException) -> None:
        fatal_errors.append(f"{type(error).__name__}: {error}")

    def capture_primary_run(*_args: Any, **_kwargs: Any) -> int:
        primary_runs.append(True)
        return 0

    def capture_wait_for_resolution(app: Any, ownership: Any, **_kwargs: Any) -> str:
        wait_started_path.write_text("waiting", encoding="utf-8")
        return real_wait_for_resolution(app, ownership, timeout_ms=5_000)

    main_module.activate_existing_instance = activate_with_short_timeout
    main_module._show_fatal_startup_error = capture_fatal_error
    main_module._run_primary_application = capture_primary_run
    main_module._wait_for_existing_instance_resolution = capture_wait_for_resolution

    started_at = time.monotonic()
    exit_code = main_module.main()
    elapsed_seconds = time.monotonic() - started_at
    _close_qt_windows(main_module.QApplication)
    _emit_result(
        {
            "elapsed_seconds": elapsed_seconds,
            "exit_code": exit_code,
            "fatal_errors": fatal_errors,
            "primary_runs": len(primary_runs),
        }
    )
    return 0


def test_synchronized_processes_have_one_owner(root: Path) -> None:
    case_root = root / "ownership-contention"
    case_root.mkdir(parents=True)
    start_path = case_root / "start"
    release_path = case_root / "release"
    ready_paths = (case_root / "ready-0", case_root / "ready-1")
    result_paths = (case_root / "result-0.json", case_root / "result-1.json")
    processes: list[subprocess.Popen[str]] = []

    try:
        for ready_path, result_path in zip(ready_paths, result_paths, strict=True):
            env = _isolated_environment(case_root)
            env.update(
                {
                    "BT_TEST_START_PATH": str(start_path),
                    "BT_TEST_RELEASE_PATH": str(release_path),
                    "BT_TEST_READY_PATH": str(ready_path),
                    "BT_TEST_OWNERSHIP_RESULT_PATH": str(result_path),
                }
            )
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--ownership-child"],
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )

        _wait_for_paths(ready_paths, timeout_seconds=10.0)
        start_path.write_text("start", encoding="utf-8")
        _wait_for_paths(result_paths, timeout_seconds=10.0)
        results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
        acquired = [bool(result["acquired"]) for result in results]
        assert sorted(acquired) == [False, True], f"expected exactly one process owner, got {results}"
    finally:
        release_path.write_text("release", encoding="utf-8")
        for process in processes:
            try:
                stdout, stderr = process.communicate(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"ownership child did not terminate\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )
            if process.returncode != 0:
                raise AssertionError(
                    f"ownership child exited with {process.returncode}\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )

    followup = _run_child("--acquire-once-child", env=_isolated_environment(case_root))
    assert followup == {"acquired": True}, f"ownership remained locked after contenders exited: {followup}"


def test_main_failure_returns_one_and_releases_at_process_exit(root: Path) -> None:
    env = _isolated_environment(root / "construction-failure")
    result = _run_child(
        "--failure-main-child",
        env=env,
    )
    assert result["exit_code"] == 1, result
    assert result["ownership_reacquired_before_process_exit"] is False, result
    assert result["dialog_calls"] == 0, result
    assert result["elapsed_seconds"] < 10.0, result
    assert _run_child("--acquire-once-child", env=env) == {"acquired": True}


def test_main_ready_path_does_not_use_fallback(root: Path) -> None:
    env = _isolated_environment(root / "ready-path")
    result = _run_child(
        "--ready-main-child",
        env=env,
    )
    assert result["exit_code"] == 0, result
    assert result["constructed"] is True, result
    assert result["prepare_calls"] == 1, result
    assert result["loader_finished"] is True, result
    assert result["show_calls"] == 1, result
    assert result["visible_when_shown"] is True, result
    assert result["release_reason"] == "complete", result
    assert result["ready_before_show"] is True, result
    assert result["timeout_registered"] is True, result
    assert result["fallback_fired"] is False, result
    assert result["data_service_start_bypassed"] is True, result
    assert result["ownership_reacquired_before_process_exit"] is False, result
    assert result["elapsed_seconds"] < 10.0, result
    assert _run_child("--acquire-once-child", env=env) == {"acquired": True}


def test_shutdown_tail_waits_then_relaunches(root: Path) -> None:
    case_root = root / "shutdown-tail"
    case_root.mkdir(parents=True)
    worker_started_path = case_root / "worker-started"
    main_returned_path = case_root / "main-returned"
    worker_release_path = case_root / "worker-release"
    wait_started_path = case_root / "wait-started"
    env = _isolated_environment(case_root)
    env.update(
        {
            "BT_TEST_WORKER_STARTED_PATH": str(worker_started_path),
            "BT_TEST_MAIN_RETURNED_PATH": str(main_returned_path),
            "BT_TEST_WORKER_RELEASE_PATH": str(worker_release_path),
            "BT_TEST_WAIT_STARTED_PATH": str(wait_started_path),
        }
    )
    primary = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--shutdown-tail-main-child"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    primary_result: dict[str, Any] | None = None
    release_thread: threading.Thread | None = None
    try:
        _wait_for_paths((worker_started_path, main_returned_path), timeout_seconds=10.0)
        assert primary.poll() is None, "primary exited despite its in-flight non-daemon executor worker"

        def release_previous_process() -> None:
            _wait_for_paths((wait_started_path,), timeout_seconds=5.0)
            time.sleep(0.5)
            worker_release_path.write_text("release", encoding="utf-8")

        release_thread = threading.Thread(target=release_previous_process, daemon=True)
        release_thread.start()
        relaunch = _run_child("--contended-main-child", env=env)
        assert relaunch["exit_code"] == 0, relaunch
        assert relaunch["fatal_errors"] == [], relaunch
        assert relaunch["primary_runs"] == 1, relaunch
        assert relaunch["elapsed_seconds"] >= 0.5, relaunch
        assert relaunch["elapsed_seconds"] < 5.0, relaunch
    finally:
        worker_release_path.write_text("release", encoding="utf-8")
        if release_thread is not None:
            release_thread.join(timeout=5.0)
        try:
            stdout, stderr = primary.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            primary.kill()
            stdout, stderr = primary.communicate()
            raise AssertionError(
                f"shutdown-tail primary did not terminate\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        completed = subprocess.CompletedProcess(
            args=primary.args,
            returncode=primary.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        primary_result = _parse_child_result(completed)

    assert primary_result["exit_code"] == 0, primary_result
    assert primary_result["ownership_reacquired_before_process_exit"] is False, primary_result
    assert primary_result["elapsed_seconds"] < 5.0, primary_result
    assert _run_child("--acquire-once-child", env=env) == {"acquired": True}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="budget-terminal-main-launch-") as temp_dir:
        root = Path(temp_dir)
        test_synchronized_processes_have_one_owner(root)
        test_main_failure_returns_one_and_releases_at_process_exit(root)
        test_main_ready_path_does_not_use_fallback(root)
        test_shutdown_tail_waits_then_relaunches(root)
    print("PASS real main launch ownership, shutdown-tail relaunch, and ready release")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--ownership-child":
        raise SystemExit(_ownership_child())
    if mode == "--acquire-once-child":
        raise SystemExit(_acquire_once_child())
    if mode == "--failure-main-child":
        raise SystemExit(_failure_main_child())
    if mode == "--ready-main-child":
        raise SystemExit(_ready_main_child())
    if mode == "--shutdown-tail-main-child":
        raise SystemExit(_shutdown_tail_main_child())
    if mode == "--contended-main-child":
        raise SystemExit(_contended_main_child())
    raise SystemExit(main())
