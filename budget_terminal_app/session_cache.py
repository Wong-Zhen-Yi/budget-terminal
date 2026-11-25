from __future__ import annotations

import math
from io import StringIO
from pathlib import Path
from typing import Any

from .dependencies import datetime, json, pd
from .paths import user_data_path
from .persistence_schema import TAB_SESSION_CACHE_SCHEMA_VERSION, migrate_tab_session_payload


SESSION_CACHE_VERSION = TAB_SESSION_CACHE_SCHEMA_VERSION
SESSION_CACHE_FILE = user_data_path('tab_session_cache.json')
_SESSION_TAB_KEYS = ('stocks', 'fundamentals', 'options', 'etf', 'politics', 'youtube', 'roll')
_DATAFRAME_MARKER = '__bt_dataframe__'


def _looks_like_datetime_label(value: Any) -> bool:
    """Return True when a label is already datetime-like or stored as an ISO timestamp string."""
    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return True
    text = str(value or '').strip()
    if not text:
        return False
    if len(text) < 10:
        return False
    if text[4] != '-' or text[7] != '-':
        return False
    if not (text[:4].isdigit() and text[5:7].isdigit() and text[8:10].isdigit()):
        return False
    return True


def _deserialize_datetime_axis(values: Any) -> Any:
    """Restore a cached DataFrame axis as datetimes when every label already looks datetime-like."""
    try:
        axis = pd.Index(values)
    except Exception:
        return None
    if axis.empty:
        return None
    if not all(_looks_like_datetime_label(value) for value in axis):
        return None
    try:
        parsed = pd.to_datetime(axis, errors='coerce', format='ISO8601')
    except Exception:
        return None
    if getattr(parsed, 'isna', lambda: [])().any():
        return None
    return parsed


def _read_json(path: Any, default: Any) -> Any:
    """Read JSON from disk, returning a fallback on failure."""
    try:
        with Path(path).open(encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path: Any, data: Any) -> None:
    """Write JSON data atomically."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(f'{target.suffix}.tmp')
    with temp_path.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
    temp_path.replace(target)


def _default_session_cache() -> dict[str, Any]:
    """Return the canonical tab-session cache shape."""
    return {
        'version': SESSION_CACHE_VERSION,
        'tabs': {tab_key: None for tab_key in _SESSION_TAB_KEYS},
    }


def _normalize_session_cache(payload: Any) -> dict[str, Any]:
    """Normalize persisted session cache data into the supported shape."""
    normalized = _default_session_cache()
    migration = migrate_tab_session_payload(payload, _SESSION_TAB_KEYS)
    raw = migration.payload if isinstance(migration.payload, dict) else {}
    raw_tabs = raw.get('tabs', raw)
    if not isinstance(raw_tabs, dict):
        return normalized
    for tab_key in _SESSION_TAB_KEYS:
        value = raw_tabs.get(tab_key)
        normalized['tabs'][tab_key] = value if isinstance(value, dict) else None
    return normalized


def load_tab_session_cache() -> dict[str, Any]:
    """Load the versioned tab-session cache from disk."""
    return _normalize_session_cache(_read_json(SESSION_CACHE_FILE, {}))


def save_tab_session_cache(payload: Any) -> dict[str, Any]:
    """Persist the versioned tab-session cache to disk."""
    normalized = _normalize_session_cache(payload)
    _write_json(SESSION_CACHE_FILE, normalized)
    return normalized


def clear_tab_session_cache() -> dict[str, Any]:
    """Clear any persisted tab-session cache from disk."""
    target = Path(SESSION_CACHE_FILE)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        save_tab_session_cache(_default_session_cache())
    return _default_session_cache()


def serialize_session_value(value: Any) -> Any:
    """Convert nested runtime values into JSON-safe session-cache data."""
    if isinstance(value, pd.DataFrame):
        return {
            _DATAFRAME_MARKER: True,
            'orient': 'split',
            'json': value.to_json(orient='split', date_format='iso', date_unit='ns'),
        }
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): serialize_session_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_session_value(item) for item in value]
    item_fn = getattr(value, 'item', None)
    if callable(item_fn):
        try:
            return serialize_session_value(item_fn())
        except Exception:
            pass
    return str(value)


def deserialize_session_value(value: Any) -> Any:
    """Restore JSON-safe session-cache data into runtime values."""
    if isinstance(value, dict):
        if value.get(_DATAFRAME_MARKER):
            raw_json = str(value.get('json', '') or '')
            if not raw_json:
                return pd.DataFrame()
            try:
                frame = pd.read_json(StringIO(raw_json), orient=str(value.get('orient', 'split') or 'split'))
            except Exception:
                return pd.DataFrame()
            parsed_index = _deserialize_datetime_axis(frame.index)
            if parsed_index is not None:
                frame.index = parsed_index
            parsed_columns = _deserialize_datetime_axis(frame.columns)
            if parsed_columns is not None:
                frame.columns = parsed_columns
            return frame
        return {str(key): deserialize_session_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [deserialize_session_value(item) for item in value]
    return value
