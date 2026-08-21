from __future__ import annotations
import datetime
import importlib
import json
import logging
import math
import os
import sqlite3
import sys
import threading
import webbrowser
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo
from PySide6.QtCore import QObject, QEvent, QPoint, QSize, Qt, QThread, QTime, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPalette, QPicture, QPolygonF, QScreen, QShortcut
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGraphicsBlurEffect, QGraphicsItem, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QTimeEdit, QToolButton, QToolTip, QVBoxLayout, QWidget


class _LazyModuleProxy:
    """Import heavy third-party modules only when their attributes are first used."""

    def __init__(self, module_name: str, on_load: Any = None) -> None:
        self._module_name = module_name
        self._module = None
        self._on_load = on_load
        self._lock = threading.Lock()

    def _load(self) -> Any:
        module = self._module
        if module is not None:
            return module
        with self._lock:
            module = self._module
            if module is None:
                module = importlib.import_module(self._module_name)
                if self._on_load is not None:
                    # Runs before the module is published so no thread can take the fast path and
                    # use the module before the hook has configured it. The hook therefore must not
                    # touch this proxy: the lock is not reentrant.
                    try:
                        self._on_load(module)
                    except Exception:
                        logging.getLogger(__name__).debug(
                            'lazy on_load hook failed for %s', self._module_name, exc_info=True
                        )
                self._module = module
        return module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __dir__(self) -> list[str]:
        return dir(self._load())

    def __repr__(self) -> str:
        state = 'loaded' if self._module is not None else 'pending'
        return f'<lazy-module {self._module_name} ({state})>'


# pyqtgraph probes PyQt6 before PySide6, so name the binding explicitly rather than relying on
# import order. Loading a second Qt binding into this process would be fatal.
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PySide6')

def _configure_yahoo_client(_module: Any) -> None:
    """Prepare yfinance as soon as it is first imported, before any request goes out.

    Hooked onto the lazy proxy rather than called from startup: yfinance must stay lazily imported,
    but both of these have to be in place before the first request, and the proxy's load is the one
    point that is both.

    Order matters. The timezone cache is repaired first because yfinance resolves a ticker's
    timezone through it before returning any history -- a corrupt cache fails every symbol no matter
    how well paced the requests are. Pacing goes on afterwards. See ``services/yahoo_tz_cache.py``
    and ``services/yahoo_rate_limit.py``.
    """
    from .services.yahoo_rate_limit import install_yahoo_rate_limit
    from .services.yahoo_tz_cache import install_yahoo_tz_cache

    install_yahoo_tz_cache()
    install_yahoo_rate_limit()


pd = _LazyModuleProxy('pandas')
pg = _LazyModuleProxy('pyqtgraph')
requests = _LazyModuleProxy('requests')
yf = _LazyModuleProxy('yfinance', on_load=_configure_yahoo_client)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

YAHOO_UNAUTHORIZED_MARKERS = (
    'HTTP Error 401',
    '401 Client Error: Unauthorized',
    '"code":"Unauthorized"',
    '"code":"unauthorized"',
    'Unauthorized',
    'User is unable to access this feature',
    'Invalid Crumb',
    'User is not logged in',
)


def is_yahoo_unauthorized_error(error: Any) -> bool:
    """Return whether an exception/log message is a known Yahoo Finance refusal."""
    text = str(error or '')
    try:
        text = f'{text} {repr(error)}'
    except Exception:
        pass
    return any(marker in text for marker in YAHOO_UNAUTHORIZED_MARKERS)


class _YahooUnauthorizedLogFilter(logging.Filter):
    """Suppress noisy yfinance 401 logs that optional app fallbacks handle."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not is_yahoo_unauthorized_error(record.getMessage())
        except Exception:
            return True


yfinance_logger = logging.getLogger('yfinance')
yfinance_logger.setLevel(logging.WARNING)
yfinance_logger.addFilter(_YahooUnauthorizedLogFilter())
logging.getLogger('peewee').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('uvicorn').setLevel(logging.WARNING)
YF_LOCK = threading.Lock()
