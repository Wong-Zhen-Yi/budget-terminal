"""Process-level smoke tests for Budget Terminal single-instance behavior."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_state(pid: int, *, running: bool, timeout_seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _process_is_running(pid) is running:
            return True
        time.sleep(0.1)
    return _process_is_running(pid) is running


def _terminate_process_tree(pid: int) -> None:
    if pid <= 0 or not _process_is_running(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if not _wait_for_process_state(pid, running=False, timeout_seconds=5.0):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _request(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _write_message(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
    process.stdin.flush()


def _read_message(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        raise AssertionError(f"Expected MCP response, process exited with {process.poll()}. stderr={stderr}")
    return json.loads(line.decode("utf-8"))


def _status_from_response(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["result"]["content"][0]["text"])


def _base_env(temp_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "APPDATA": str(temp_root / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(temp_root / "AppData" / "Local"),
            "USERPROFILE": str(temp_root),
            "QT_QPA_PLATFORM": "offscreen",
            "BUDGET_TERMINAL_SKIP_LOCAL_VENV": "1",
        }
    )
    return env


def test_mcp_reuses_primary_instance() -> None:
    with tempfile.TemporaryDirectory(prefix="budget-terminal-single-") as temp_dir:
        temp_root = Path(temp_dir)
        env = _base_env(temp_root)
        app_pid = 0
        primary = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "budget_terminal_mcp.py")],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _write_message(
                primary,
                _request(
                    1,
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "single-instance-primary", "version": "1.0"},
                    },
                ),
            )
            _write_message(primary, _request(2, "tools/call", {"name": "app_status", "arguments": {}}))
            _read_message(primary)
            primary_status = _status_from_response(_read_message(primary))
            app_pid = int(primary_status["process_id"])
            assert app_pid > 0
            assert app_pid != primary.pid, "visible MCP should proxy into the desktop app process"
            assert _process_is_running(app_pid), "desktop app should be alive while primary MCP is connected"
            assert primary.poll() is None

            secondary_payload = b"".join(
                json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
                for message in (
                    _request(
                        3,
                        "initialize",
                        {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "single-instance-secondary", "version": "1.0"},
                        },
                    ),
                    _request(4, "tools/call", {"name": "app_status", "arguments": {}}),
                )
            )
            secondary = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "budget_terminal_mcp.py")],
                cwd=PROJECT_ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            secondary_stdout, secondary_stderr = secondary.communicate(input=secondary_payload, timeout=60)
            assert secondary.returncode == 0, secondary_stderr.decode("utf-8", errors="replace")
            secondary_responses = [
                json.loads(line)
                for line in secondary_stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
            assert [response["id"] for response in secondary_responses] == [3, 4]
            secondary_status = _status_from_response(secondary_responses[1])
            assert int(secondary_status["process_id"]) == app_pid
            assert primary.poll() is None, "proxy MCP exit should not close the primary app"

            launcher = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "budget_terminal.py")],
                cwd=PROJECT_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            assert launcher.returncode == 0, launcher.stderr.decode("utf-8", errors="replace")
            assert primary.poll() is None, "normal duplicate launcher should not close the MCP proxy"
            assert _process_is_running(app_pid), "normal duplicate launcher should not close the desktop app"

            if primary.stdin is not None and not primary.stdin.closed:
                primary.stdin.close()
            primary.wait(timeout=30)
            assert primary.returncode == 0
            assert _process_is_running(app_pid), "MCP proxy exit should not close the desktop app"
        finally:
            if primary.poll() is None and primary.stdin is not None and not primary.stdin.closed:
                primary.stdin.close()
            try:
                primary.wait(timeout=30)
            except subprocess.TimeoutExpired:
                primary.kill()
                primary.wait(timeout=10)
            if app_pid:
                _terminate_process_tree(app_pid)
                assert _wait_for_process_state(app_pid, running=False)


def main() -> int:
    test_mcp_reuses_primary_instance()
    print("PASS MCP and normal launchers reuse the primary Budget Terminal instance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
