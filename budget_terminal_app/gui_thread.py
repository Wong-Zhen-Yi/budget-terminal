"""One place to ask "am I allowed to touch widgets right now?".

Qt widgets may only be read or mutated from the thread that owns them. Breaking that rule does not
raise -- it corrupts Qt's internal state and aborts the process later with a native access
violation and, usually, no Python frame pointing at the culprit. Several such aborts have been
traced back to background workers reaching render code, so the check lives here rather than being
re-derived at each call site.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def on_gui_thread() -> bool:
    """Return whether the caller is running on the thread that owns the widgets.

    With no QApplication there are no widgets to protect, so the answer is trivially yes; that
    keeps headless service and worker code free of a Qt dependency it does not need.
    """
    app = QApplication.instance()
    if app is None:
        return True
    return QThread.currentThread() is app.thread()


def warn_if_off_gui_thread(what: str) -> bool:
    """Return True when it is safe to touch widgets, logging a stack trace when it is not.

    The stack is the point of this: an off-thread widget touch otherwise shows up as an access
    violation minutes later in an unrelated frame. Callers are expected to bail out on False.
    """
    if on_gui_thread():
        return True
    logger.error(
        '%s was called off the GUI thread; skipping it to avoid corrupting Qt state.',
        what,
        stack_info=True,
    )
    return False
