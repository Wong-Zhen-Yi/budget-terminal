from __future__ import annotations

import os
import sys
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from budget_terminal_app.widgets.batched_render import (
    DEFAULT_MAX_BATCH_MS,
    DEFAULT_MAX_ITEMS,
    LABEL_MAX_ITEMS,
    cancel_batched,
    logger as batched_render_logger,
    run_batched,
)


_QT_APP = None


def _app() -> QApplication:
    global _QT_APP
    app = QApplication.instance()
    if app is None:
        _QT_APP = QApplication([])
        app = _QT_APP
    return app


def _drain_until(predicate, timeout: float = 2.0) -> None:
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate(), "timed out waiting for batched render"


class _Owner:
    pass


def test_batches_and_cleanup() -> None:
    _app()
    owner = _Owner()
    applied: list[tuple[int, int]] = []
    lifecycle: list[str] = []
    generation = object()

    handle = run_batched(
        owner,
        "rows",
        range(121),
        lambda index, item: applied.append((index, item)),
        generation=generation,
        prepare=lambda: lifecycle.append("prepare"),
        finish=lambda: lifecycle.append("finish"),
        is_current=lambda candidate: candidate is generation,
        is_visible=lambda: True,
        max_items=50,
    )
    _drain_until(lambda: handle.finished)

    assert handle.completed and not handle.cancelled and handle.error is None
    assert handle.processed_count == 121
    assert handle.batch_count >= 3
    assert applied == list(enumerate(range(121)))
    assert lifecycle == ["prepare", "finish"]
    assert not cancel_batched(owner, "rows")
    assert DEFAULT_MAX_BATCH_MS == 8.0
    assert DEFAULT_MAX_ITEMS == 50
    assert LABEL_MAX_ITEMS == 25


def test_new_render_replaces_old_and_cleans_both() -> None:
    _app()
    owner = _Owner()
    cleanup: list[str] = []
    first = run_batched(
        owner,
        "table",
        range(100),
        lambda _index, _item: None,
        finish=lambda: cleanup.append("first"),
        max_items=1,
    )
    second_values: list[int] = []
    second = run_batched(
        owner,
        "table",
        range(3),
        lambda _index, item: second_values.append(item),
        finish=lambda: cleanup.append("second"),
        max_items=1,
    )

    assert first.finished and first.cancelled
    _drain_until(lambda: second.finished)
    assert second.completed
    assert second_values == [0, 1, 2]
    assert cleanup == ["first", "second"]


def test_generation_guard_cancels_remaining_items() -> None:
    _app()
    owner = _Owner()
    current = {"value": 1}
    applied: list[int] = []
    cleanup: list[str] = []

    def apply_item(_index: int, item: int) -> None:
        applied.append(item)
        if item == 1:
            current["value"] = 2

    handle = run_batched(
        owner,
        "guarded",
        range(20),
        apply_item,
        generation=1,
        is_current=lambda generation: generation == current["value"],
        is_visible=lambda: True,
        finish=lambda: cleanup.append("finish"),
        max_items=2,
    )
    _drain_until(lambda: handle.finished)

    assert handle.cancelled and not handle.completed
    assert applied == [0, 1]
    assert cleanup == ["finish"]


def test_hidden_surface_cancels_before_prepare() -> None:
    _app()
    owner = _Owner()
    lifecycle: list[str] = []
    handle = run_batched(
        owner,
        "hidden",
        range(5),
        lambda _index, _item: lifecycle.append("apply"),
        prepare=lambda: lifecycle.append("prepare"),
        finish=lambda: lifecycle.append("finish"),
        is_visible=lambda: False,
    )
    _drain_until(lambda: handle.finished)

    assert handle.cancelled and handle.processed_count == 0
    assert not handle.prepared
    assert lifecycle == ["finish"]


def test_errors_still_run_cleanup() -> None:
    _app()
    owner = _Owner()
    errors: list[str] = []
    cleanup: list[str] = []

    def fail_on_second(index: int, _item: int) -> None:
        if index == 1:
            raise RuntimeError("render failed")

    was_disabled = batched_render_logger.disabled
    batched_render_logger.disabled = True
    try:
        handle = run_batched(
            owner,
            "errors",
            range(4),
            fail_on_second,
            on_error=lambda exc: errors.append(str(exc)),
            finish=lambda: cleanup.append("finish"),
        )
        _drain_until(lambda: handle.finished)
    finally:
        batched_render_logger.disabled = was_disabled

    assert isinstance(handle.error, RuntimeError)
    assert not handle.completed and not handle.cancelled
    assert errors == ["render failed"]
    assert cleanup == ["finish"]


if __name__ == "__main__":
    test_batches_and_cleanup()
    test_new_render_replaces_old_and_cleans_both()
    test_generation_guard_cancels_remaining_items()
    test_hidden_surface_cancels_before_prepare()
    test_errors_still_run_cleanup()
    print("Batched render tests passed.")
