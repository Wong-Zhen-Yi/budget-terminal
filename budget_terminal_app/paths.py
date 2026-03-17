from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

APP_DIR_NAME = 'BudgetTerminal'
DOCUMENTS_USER_DATA_DIR_NAME = 'Budget Terminal User Data'


def is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return bool(getattr(sys, 'frozen', False))


def bundle_root() -> Path:
    """Return the root directory containing bundled application resources."""
    if is_frozen():
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: Any) -> Path:
    """Resolve a read-only resource path for source and frozen execution."""
    return bundle_root().joinpath(*map(str, parts))


def user_data_dir() -> Path:
    """Return the writable directory for per-user application data."""
    base_dir = (
        os.environ.get('LOCALAPPDATA')
        or os.environ.get('APPDATA')
        or str(Path.home())
    )
    path = Path(base_dir) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_data_path(*parts: Any) -> Path:
    """Resolve a writable per-user application data path."""
    path = user_data_dir().joinpath(*map(str, parts))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def documents_user_data_dir() -> Path:
    """Return the writable Documents folder used for user-entered app data."""
    home_dir = Path(os.environ.get('USERPROFILE') or Path.home())
    path = home_dir / 'Documents' / DOCUMENTS_USER_DATA_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_user_data_path(*parts: Any) -> Path:
    """Resolve a writable user-data path under the Documents folder."""
    path = documents_user_data_dir().joinpath(*map(str, parts))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
