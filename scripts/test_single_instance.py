"""Focused IPC smoke test for Budget Terminal single-instance activation."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication

from budget_terminal_app.single_instance import (
    BudgetTerminalInstanceOwnership,
    BudgetTerminalSingleInstanceServer,
    QueuedActivation,
    make_window_command_handler,
    send_single_instance_command,
)


def _send_from_background_thread(request: dict[str, object]) -> dict[str, object] | None:
    response: dict[str, object] = {}

    def _send() -> None:
        response["value"] = send_single_instance_command(request, timeout_ms=1500)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + 5.0
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.join(timeout=0.1)
    assert not thread.is_alive(), "single-instance IPC request timed out"
    value = response.get("value")
    return value if isinstance(value, dict) else None


@contextmanager
def _isolated_instance_paths() -> Iterator[Path]:
    original_local_app_data = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory(prefix="budget-terminal-single-") as temp_dir:
        isolated_root = Path(temp_dir) / "local"
        os.environ["LOCALAPPDATA"] = str(isolated_root)
        try:
            yield isolated_root
        finally:
            if original_local_app_data is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = original_local_app_data


def test_single_instance_activation_ipc() -> None:
    app = QApplication.instance() or QApplication([])
    with _isolated_instance_paths():
        activations: list[bool] = []
        ownership = BudgetTerminalInstanceOwnership()
        assert ownership.try_acquire(), "primary ownership lock was not acquired"
        server = BudgetTerminalSingleInstanceServer(
            command_handler=make_window_command_handler(
                activate_callback=lambda: activations.append(True) or True,
            ),
            ownership=ownership,
        )
        try:
            assert server.start(), "single-instance IPC server did not start"
            assert _send_from_background_thread({"command": "activate"}) == {
                "ok": True,
                "activated": True,
            }
            assert activations == [True]
            assert _send_from_background_thread({"command": "unsupported_command"}) == {
                "ok": False,
                "error": "Unknown single-instance command: unsupported_command",
            }
        finally:
            server.close()
            ownership.release()
            app.processEvents()


def test_queued_activation_flushes_when_surface_is_ready() -> None:
    activation = QueuedActivation()
    calls: list[str] = []

    assert activation.request()
    assert activation.request()
    assert activation.pending
    assert activation.set_callback(lambda: calls.append("activated") or True)
    assert not activation.pending
    assert calls == ["activated"], "multiple early requests should collapse into one activation"
    assert activation.request()
    assert calls == ["activated", "activated"]


def test_atomic_primary_ownership_under_synchronized_contention() -> None:
    with _isolated_instance_paths():
        start_barrier = threading.Barrier(3)
        acquired_barrier = threading.Barrier(3)
        release_owner = threading.Event()
        results: list[bool] = []
        errors: list[BaseException] = []
        results_lock = threading.Lock()

        def contend() -> None:
            ownership = BudgetTerminalInstanceOwnership()
            try:
                start_barrier.wait(timeout=5.0)
                acquired = ownership.try_acquire()
                with results_lock:
                    results.append(acquired)
                acquired_barrier.wait(timeout=5.0)
                if acquired:
                    release_owner.wait(timeout=5.0)
            except BaseException as exc:
                with results_lock:
                    errors.append(exc)
            finally:
                ownership.release()

        threads = [threading.Thread(target=contend, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        start_barrier.wait(timeout=5.0)
        acquired_barrier.wait(timeout=5.0)
        try:
            assert not errors, errors
            assert sorted(results) == [False, True], f"expected exactly one owner, got {results}"
        finally:
            release_owner.set()
            for thread in threads:
                thread.join(timeout=5.0)
        assert all(not thread.is_alive() for thread in threads)

        next_owner = BudgetTerminalInstanceOwnership()
        try:
            assert next_owner.try_acquire(), "ownership was not released for the next process"
        finally:
            next_owner.release()


def test_contender_server_cannot_steal_or_remove_live_endpoint() -> None:
    app = QApplication.instance() or QApplication([])
    with _isolated_instance_paths():
        primary_activations: list[bool] = []
        primary_ownership = BudgetTerminalInstanceOwnership()
        contender_ownership = BudgetTerminalInstanceOwnership()
        assert primary_ownership.try_acquire()
        assert not contender_ownership.try_acquire()

        primary_server = BudgetTerminalSingleInstanceServer(
            command_handler=make_window_command_handler(
                activate_callback=lambda: primary_activations.append(True) or True,
            ),
            ownership=primary_ownership,
        )
        contender_server = BudgetTerminalSingleInstanceServer(
            command_handler=make_window_command_handler(activate_callback=lambda: True),
            ownership=contender_ownership,
        )
        same_owner_server = BudgetTerminalSingleInstanceServer(
            command_handler=make_window_command_handler(activate_callback=lambda: True),
            ownership=primary_ownership,
        )
        try:
            assert primary_server.start()
            assert not same_owner_server.start(), "second listener unexpectedly reused the primary ownership"
            assert same_owner_server.live_endpoint_detected
            assert not same_owner_server.owns_endpoint
            assert not contender_server.start(), "contender unexpectedly stole the live endpoint"
            assert not contender_server.owns_endpoint

            same_owner_server.close()
            contender_server.close()
            assert primary_server.owns_endpoint
            assert _send_from_background_thread({"command": "activate"}) == {
                "ok": True,
                "activated": True,
            }
            assert primary_activations == [True]
        finally:
            same_owner_server.close()
            contender_server.close()
            primary_server.close()
            contender_ownership.release()
            primary_ownership.release()
            app.processEvents()


def main() -> int:
    test_single_instance_activation_ipc()
    test_queued_activation_flushes_when_surface_is_ready()
    test_atomic_primary_ownership_under_synchronized_contention()
    test_contender_server_cannot_steal_or_remove_live_endpoint()
    print("PASS single-instance ownership, activation queue, IPC, and contender safety")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
