from __future__ import annotations
import datetime
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
import pandas as pd
import pyqtgraph as pg
import requests
import yfinance as yf
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPalette, QPicture, QPolygonF, QScreen
from PyQt6.QtWidgets import QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('yfinance').setLevel(logging.WARNING)
logging.getLogger('peewee').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
YF_LOCK = threading.Lock()
