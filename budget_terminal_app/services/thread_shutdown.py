"""Deterministic drain for the window's QThread-backed workers.

Qt aborts the process outright when a ``QThread`` is destroyed while it is still running, and that
abort produces no Python traceback — the window simply disappears. Closing the app used to stop
only a handful of the page workers, so any page still fetching at close could take the process down
on the way out.

This module drains them all. It is deliberately Qt-free and duck-typed so the smoke tests can
exercise the ordering without a display: it only calls ``cancel``/``requestInterruption``/``quit``/
``wait``/``isRunning`` when those attributes exist.

The drain runs in two phases. Every worker is asked to stop first, then each thread is waited on
against a shared deadline — draining eight workers serially at three seconds apiece would freeze the
close for half a minute.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterator

DEFAULT_SHUTDOWN_BUDGET_MS = 4000
MIN_THREAD_WAIT_MS = 150

# Threads that outlive the drain are parked here so Python never finalizes them. Destroying a
# running QThread is the abort this module exists to prevent; leaking the object is the safe
# trade, because terminate() could cut a worker mid-write to the sqlite cache.
_LINGERING_THREADS: list[Any] = []


@dataclass(frozen=True)
class WorkerThreadSpec:
    """One place the window parks a QThread, and the worker driving it."""

    thread_attr: str
    worker_attr: str | None = None
    kind: str = 'single'  # 'single' | 'mapping' | 'pair_mapping'


# Every QThread the main window owns. A page that starts a QThread and is missing here will crash
# the app on close, so scripts/test_thread_shutdown.py asserts this list stays complete.
WORKER_THREAD_SPECS: tuple[WorkerThreadSpec, ...] = (
    WorkerThreadSpec('_p6_fx_thread', '_p6_fx_worker'),
    WorkerThreadSpec('_p14_thread', '_p14_worker'),
    WorkerThreadSpec('_p15_thread', '_p15_worker'),
    WorkerThreadSpec('_p15_export_thread', '_p15_export_worker'),
    WorkerThreadSpec('_p16_thread', '_p16_worker'),
    WorkerThreadSpec('_p19_thread', '_p19_worker'),
    WorkerThreadSpec('_p24_thread', '_p24_worker'),
    WorkerThreadSpec('_p40_thread', '_p40_worker'),
    WorkerThreadSpec('_p41_thread', '_p41_worker'),
    WorkerThreadSpec('_p42_thread', '_p42_worker'),
    WorkerThreadSpec('valuation_thread', 'valuation_worker'),
    WorkerThreadSpec('p18_thread', 'p18_worker'),
    WorkerThreadSpec('_p18_inflight_workers', kind='pair_mapping'),
    WorkerThreadSpec('p2_fund_threads', 'p2_fund_workers', kind='mapping'),
)


def iter_worker_threads(owner: Any) -> Iterator[tuple[str, Any, Any]]:
    """Yield ``(label, worker, thread)`` for every live worker thread the owner holds."""
    for spec in WORKER_THREAD_SPECS:
        container = getattr(owner, spec.thread_attr, None)
        if container is None:
            continue
        if spec.kind == 'single':
            worker = getattr(owner, spec.worker_attr, None) if spec.worker_attr else None
            yield spec.thread_attr, worker, container
            continue
        if not isinstance(container, dict):
            continue
        workers = getattr(owner, spec.worker_attr, None) if spec.worker_attr else None
        for key, value in list(container.items()):
            if spec.kind == 'pair_mapping':
                try:
                    worker, thread = value
                except (TypeError, ValueError):
                    continue
            else:
                thread = value
                worker = workers.get(key) if isinstance(workers, dict) else None
            if thread is None:
                continue
            yield f'{spec.thread_attr}[{key}]', worker, thread


def _call_quietly(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    try:
        return method(*args)
    except Exception:
        return None


def _is_running(thread: Any) -> bool:
    return bool(_call_quietly(thread, 'isRunning'))


def request_worker_stop(worker: Any, thread: Any) -> None:
    """Ask one worker/thread pair to stop without waiting for it.

    ``quit`` only unwinds a thread's event loop, which does nothing while the worker is inside a
    blocking ``run``. The worker's own ``cancel`` is what actually shortens the work.
    """
    _call_quietly(worker, 'cancel')
    _call_quietly(thread, 'requestInterruption')
    _call_quietly(thread, 'quit')


def shutdown_worker_threads(
    owner: Any,
    *,
    budget_ms: int = DEFAULT_SHUTDOWN_BUDGET_MS,
    logger: Any = None,
) -> dict[str, Any]:
    """Stop every worker thread the owner holds and report what drained.

    Returns a summary with the labels that stopped and the labels still running when the budget
    ran out. Never raises: a failure here would leave the rest of the close path unfinished.
    """
    entries = []
    try:
        entries = list(iter_worker_threads(owner))
    except Exception:
        if logger is not None:
            logger.exception('Unable to enumerate worker threads during shutdown.')

    for label, worker, thread in entries:
        try:
            request_worker_stop(worker, thread)
        except Exception:
            if logger is not None:
                logger.exception('Failed to signal worker thread %s during shutdown.', label)

    stopped: list[str] = []
    lingering: list[str] = []
    deadline = time.monotonic() + max(0.0, float(budget_ms) / 1000.0)
    for label, _worker, thread in entries:
        try:
            if not _is_running(thread):
                stopped.append(label)
                continue
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            _call_quietly(thread, 'wait', max(MIN_THREAD_WAIT_MS, remaining_ms))
            if _is_running(thread):
                lingering.append(label)
                _LINGERING_THREADS.append(thread)
                if logger is not None:
                    logger.error(
                        'Worker thread %s did not stop within the shutdown budget; '
                        'leaking it deliberately so Qt does not abort on a running thread.',
                        label,
                    )
            else:
                stopped.append(label)
        except Exception:
            if logger is not None:
                logger.exception('Failed to drain worker thread %s during shutdown.', label)

    return {'total': len(entries), 'stopped': stopped, 'lingering': lingering}
