from __future__ import annotations

import datetime
import math
from typing import Any

import pandas as pd


FRAME_MARKER = "__budget_terminal_dataframe__"
SERIES_MARKER = "__budget_terminal_series__"


def _json_scalar(value: Any) -> Any:
    """Return one JSON-safe scalar while preserving useful numeric/date values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_scalar(value.item())
        except Exception:
            pass
    return str(value) if not isinstance(value, (str, list, tuple, dict)) else value


def _serialize_index(index: Any) -> list[Any]:
    return [_json_scalar(value) for value in list(index)]


def serialize_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Serialize a dashboard payload returned by DataWorker for HTTP transport."""
    return _serialize_value(payload)


def deserialize_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Rebuild pandas objects from an HTTP dashboard payload."""
    value = _deserialize_value(payload)
    return value if isinstance(value, dict) else {}


def _serialize_frame(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        FRAME_MARKER: True,
        "index": _serialize_index(frame.index),
        "index_name": _json_scalar(frame.index.name),
        "columns": [str(column) for column in list(frame.columns)],
        "data": [
            [_serialize_value(value) for value in row]
            for row in frame.itertuples(index=False, name=None)
        ],
    }


def _serialize_series(series: pd.Series) -> dict[str, Any]:
    return {
        SERIES_MARKER: True,
        "index": _serialize_index(series.index),
        "name": _json_scalar(series.name),
        "data": [_serialize_value(value) for value in list(series)],
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _serialize_frame(value)
    if isinstance(value, pd.Series):
        return _serialize_series(value)
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return _json_scalar(value)


def _deserialize_index(values: Any) -> Any:
    if not isinstance(values, list):
        return pd.Index([])
    try:
        parsed = pd.to_datetime(values, errors="coerce", utc=True)
        if not pd.isna(parsed).all():
            return pd.DatetimeIndex(parsed).tz_convert(None)
    except Exception:
        pass
    return pd.Index(values)


def _deserialize_frame(value: dict[str, Any]) -> pd.DataFrame:
    columns = list(value.get("columns") or [])
    frame = pd.DataFrame(value.get("data") or [], columns=columns)
    frame.index = _deserialize_index(value.get("index") or [])
    index_name = value.get("index_name")
    frame.index.name = str(index_name) if index_name else "Date"
    for column in frame.columns:
        try:
            frame[column] = pd.to_numeric(frame[column])
        except Exception:
            pass
    return frame


def _deserialize_series(value: dict[str, Any]) -> pd.Series:
    series = pd.Series(value.get("data") or [], index=_deserialize_index(value.get("index") or []))
    name = value.get("name")
    if name:
        series.name = str(name)
    try:
        series = pd.to_numeric(series)
    except Exception:
        pass
    return series


def _deserialize_value(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get(FRAME_MARKER):
            return _deserialize_frame(value)
        if value.get(SERIES_MARKER):
            return _deserialize_series(value)
        return {key: _deserialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deserialize_value(item) for item in value]
    return value
