from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def configure_process_dpi_awareness() -> None:
    """Request crisp per-monitor DPI rendering before Qt creates windows."""
    if sys.platform != 'win32':
        return

    try:
        set_context = ctypes.windll.user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        if set_context(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError, ValueError):
        pass

    try:
        set_awareness = ctypes.windll.shcore.SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int]
        set_awareness.restype = ctypes.c_long
        if set_awareness(2) == 0:
            return
    except (AttributeError, OSError, ValueError):
        pass

    try:
        set_dpi_aware = ctypes.windll.user32.SetProcessDPIAware
        set_dpi_aware.argtypes = []
        set_dpi_aware.restype = wintypes.BOOL
        set_dpi_aware()
    except (AttributeError, OSError, ValueError):
        pass


def configure_qt_high_dpi_policy() -> None:
    """Keep Qt fractional display scaling from being rounded unnecessarily."""
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication

        policy = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy)
    except (AttributeError, ImportError, RuntimeError, ValueError):
        pass
