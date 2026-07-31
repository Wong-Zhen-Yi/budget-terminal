"""Responsive, generation-aware batching for GUI result application."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from time import perf_counter
from typing import Any, Generic, Hashable, TypeVar
from weakref import ref

from PyQt6.QtCore import QTimer


logger = logging.getLogger(__name__)

DEFAULT_MAX_BATCH_MS = 8.0
DEFAULT_MAX_ITEMS = 50
LABEL_MAX_ITEMS = 25
_OWNER_HANDLES_ATTR = "_budget_terminal_batched_render_handles"

T = TypeVar("T")


class BatchedRenderHandle(Generic[T]):
    """A cancellable zero-delay render job.

    ``prepare`` runs once before the first item. ``finish`` runs exactly once
    after success, cancellation, or error, making it safe for restoring widget
    updates, sorting, and signals.  Guard callbacks are checked before every
    slice so navigation or a newer generation aborts the remaining UI work.
    """

    def __init__(
        self,
        items: Iterable[T],
        apply_item: Callable[[int, T], None],
        *,
        generation: Any = None,
        prepare: Callable[[], None] | None = None,
        finish: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        is_current: Callable[[Any], bool] | None = None,
        is_visible: Callable[[], bool] | None = None,
        max_batch_ms: float = DEFAULT_MAX_BATCH_MS,
        max_items: int = DEFAULT_MAX_ITEMS,
        on_terminal: Callable[["BatchedRenderHandle[T]"], None] | None = None,
    ) -> None:
        if max_batch_ms <= 0:
            raise ValueError("max_batch_ms must be greater than zero")
        if max_items <= 0:
            raise ValueError("max_items must be greater than zero")

        self.generation = generation
        self.max_batch_ms = float(max_batch_ms)
        self.max_items = int(max_items)
        self._items = iter(items)
        self._apply_item = apply_item
        self._prepare = prepare
        self._finish = finish
        self._on_error = on_error
        self._is_current = is_current
        self._is_visible = is_visible
        self._on_terminal = on_terminal
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_batch)

        self.processed_count = 0
        self.batch_count = 0
        self.prepared = False
        self.completed = False
        self.cancelled = False
        self.finished = False
        self.error: Exception | None = None

    @property
    def running(self) -> bool:
        return not self.finished

    def start(self) -> "BatchedRenderHandle[T]":
        """Schedule the first render slice and return this handle."""
        if not self.finished and not self._timer.isActive():
            self._timer.start(0)
        return self

    def cancel(self) -> bool:
        """Cancel remaining slices and run cleanup; return whether work changed."""
        if self.finished:
            return False
        self._terminate(cancelled=True)
        return True

    def _guards_allow_render(self) -> bool:
        if self._is_current is not None and not self._is_current(self.generation):
            return False
        return self._is_visible is None or bool(self._is_visible())

    def _run_batch(self) -> None:
        if self.finished:
            return
        try:
            guards_allow_render = self._guards_allow_render()
        except Exception as exc:
            self._fail(exc)
            return
        if not guards_allow_render:
            self._terminate(cancelled=True)
            return

        if not self.prepared:
            try:
                if self._prepare is not None:
                    self._prepare()
                self.prepared = True
            except Exception as exc:
                self._fail(exc)
                return

        started_at = perf_counter()
        applied = 0
        self.batch_count += 1
        while applied < self.max_items:
            if applied and (perf_counter() - started_at) * 1000.0 >= self.max_batch_ms:
                break
            try:
                item = next(self._items)
            except StopIteration:
                self._terminate(completed=True)
                return
            except Exception as exc:
                self._fail(exc)
                return

            try:
                self._apply_item(self.processed_count, item)
            except Exception as exc:
                self._fail(exc)
                return
            self.processed_count += 1
            applied += 1

        self._timer.start(0)

    def _fail(self, exc: Exception) -> None:
        self.error = exc
        logger.exception("Batched render failed.")
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                logger.exception("Batched render error callback failed.")
        self._terminate()

    def _terminate(self, *, completed: bool = False, cancelled: bool = False) -> None:
        if self.finished:
            return
        self._timer.stop()
        self.completed = bool(completed)
        self.cancelled = bool(cancelled)
        self.finished = True
        try:
            if self._finish is not None:
                self._finish()
        except Exception as exc:
            if self.error is None:
                self.error = exc
            logger.exception("Batched render cleanup failed.")
        finally:
            if self._on_terminal is not None:
                try:
                    self._on_terminal(self)
                except Exception:
                    logger.exception("Batched render terminal callback failed.")
            self._timer.deleteLater()


def run_batched(
    owner: Any,
    key: Hashable,
    items: Iterable[T],
    apply_item: Callable[[int, T], None],
    *,
    generation: Any = None,
    prepare: Callable[[], None] | None = None,
    finish: Callable[[], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    is_current: Callable[[Any], bool] | None = None,
    is_visible: Callable[[], bool] | None = None,
    max_batch_ms: float = DEFAULT_MAX_BATCH_MS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> BatchedRenderHandle[T]:
    """Start or replace an owner's keyed render job.

    Pass ``generation=token`` and ``is_current=coordinator.is_current`` to tie
    rendering directly to a :class:`RefreshCoordinator`.  For chart labels use
    ``max_items=LABEL_MAX_ITEMS``.
    """
    handles = _owner_handles(owner)
    previous = handles.pop(key, None)
    if previous is not None:
        previous.cancel()

    try:
        owner_ref = ref(owner)
    except TypeError:
        def owner_ref() -> Any:
            return owner

    def remove_finished(handle: BatchedRenderHandle[T]) -> None:
        live_owner = owner_ref()
        if live_owner is None:
            return
        live_handles = getattr(live_owner, _OWNER_HANDLES_ATTR, None)
        if isinstance(live_handles, dict) and live_handles.get(key) is handle:
            live_handles.pop(key, None)

    handle = BatchedRenderHandle(
        items,
        apply_item,
        generation=generation,
        prepare=prepare,
        finish=finish,
        on_error=on_error,
        is_current=is_current,
        is_visible=is_visible,
        max_batch_ms=max_batch_ms,
        max_items=max_items,
        on_terminal=remove_finished,
    )
    handles[key] = handle
    return handle.start()


def cancel_batched(owner: Any, key: Hashable) -> bool:
    """Cancel one keyed render job and run its cleanup callback."""
    handles = getattr(owner, _OWNER_HANDLES_ATTR, None)
    if not isinstance(handles, dict):
        return False
    handle = handles.pop(key, None)
    return bool(handle is not None and handle.cancel())


def cancel_all_batched(owner: Any) -> int:
    """Cancel every render job owned by *owner* and return the count."""
    handles = getattr(owner, _OWNER_HANDLES_ATTR, None)
    if not isinstance(handles, dict):
        return 0
    active = tuple(handles.values())
    handles.clear()
    return sum(1 for handle in active if handle.cancel())


def _owner_handles(owner: Any) -> dict[Hashable, BatchedRenderHandle[Any]]:
    handles = getattr(owner, _OWNER_HANDLES_ATTR, None)
    if handles is None:
        handles = {}
        try:
            setattr(owner, _OWNER_HANDLES_ATTR, handles)
        except (AttributeError, TypeError) as exc:
            raise TypeError("batched render owner must support instance attributes") from exc
    if not isinstance(handles, dict):
        raise TypeError(f"{_OWNER_HANDLES_ATTR} must be a dictionary")
    return handles
