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
from PyQt6.QtCore import QObject, QEvent, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPalette, QPicture, QPolygonF, QScreen, QShortcut
from PyQt6.QtWidgets import QApplication, QAbstractSpinBox, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGraphicsItem, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget


class _LazyModuleProxy:
    """Import heavy third-party modules only when their attributes are first used."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        module = self._module
        if module is not None:
            return module
        with self._lock:
            module = self._module
            if module is None:
                module = importlib.import_module(self._module_name)
                self._module = module
        return module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __dir__(self) -> list[str]:
        return dir(self._load())

    def __repr__(self) -> str:
        state = 'loaded' if self._module is not None else 'pending'
        return f'<lazy-module {self._module_name} ({state})>'


pd = _LazyModuleProxy('pandas')
pg = _LazyModuleProxy('pyqtgraph')
requests = _LazyModuleProxy('requests')
yf = _LazyModuleProxy('yfinance')

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
