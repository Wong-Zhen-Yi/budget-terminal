from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

from .paths import user_data_path


STARTUP_METRICS_SCHEMA_VERSION = 1
STARTUP_METRICS_HISTORY_LIMIT = 30
STARTUP_METRICS_FILE = user_data_path('startup_metrics.json')


def utc_now_iso() -> str:
    """Return a UTC ISO timestamp for persisted startup metrics."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def make_launch_id() -> str:
    """Return a launch identifier stable for this process."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    return f'{timestamp}-{os.getpid()}'


def _coerce_seconds(value: Any) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def _normalize_stage(stage: Any) -> dict[str, Any]:
    raw = dict(stage) if isinstance(stage, dict) else {}
    normalized = {
        'label': str(raw.get('label', '') or ''),
        'status': str(raw.get('status', 'pending') or 'pending'),
        'detail': str(raw.get('detail', '') or ''),
        'count': raw.get('count'),
        'started_seconds': _coerce_seconds(raw.get('started_seconds')),
        'completed_seconds': _coerce_seconds(raw.get('completed_seconds')),
        'duration_seconds': _coerce_seconds(raw.get('duration_seconds')),
    }
    if normalized['status'] not in {'pending', 'running', 'complete', 'skipped', 'failed'}:
        normalized['status'] = 'pending'
    return normalized


def _normalize_launch(launch: Any) -> dict[str, Any] | None:
    raw = dict(launch) if isinstance(launch, dict) else {}
    launch_id = str(raw.get('launch_id', '') or '').strip()
    if not launch_id:
        return None
    stages = raw.get('stages', {})
    normalized_stages = {}
    if isinstance(stages, dict):
        for key, value in stages.items():
            clean_key = str(key or '').strip()
            if clean_key:
                normalized_stages[clean_key] = _normalize_stage(value)
    status = str(raw.get('status', 'running') or 'running')
    if status not in {'running', 'complete', 'partial', 'failed'}:
        status = 'running'
    return {
        'launch_id': launch_id,
        'started_at': str(raw.get('started_at', '') or ''),
        'completed_at': str(raw.get('completed_at', '') or ''),
        'app_version': str(raw.get('app_version', '') or ''),
        'status': status,
        'total_seconds': _coerce_seconds(raw.get('total_seconds')),
        'stages': normalized_stages,
    }


def _default_document() -> dict[str, Any]:
    return {
        'version': STARTUP_METRICS_SCHEMA_VERSION,
        'launches': [],
    }


def _read_json(path: Any, default: Any) -> Any:
    try:
        with Path(path).open(encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path: Any, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(f'{target.suffix}.tmp')
    with temp_path.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
    temp_path.replace(target)


def normalize_startup_metrics_document(payload: Any) -> dict[str, Any]:
    """Normalize persisted startup timing history."""
    raw = dict(payload) if isinstance(payload, dict) else {}
    launches = []
    raw_launches = raw.get('launches', [])
    if isinstance(raw_launches, list):
        for value in raw_launches:
            launch = _normalize_launch(value)
            if launch is not None:
                launches.append(launch)
    return {
        'version': STARTUP_METRICS_SCHEMA_VERSION,
        'launches': launches[:STARTUP_METRICS_HISTORY_LIMIT],
    }


def load_startup_metrics_history() -> dict[str, Any]:
    """Load recent startup timing history."""
    return normalize_startup_metrics_document(_read_json(STARTUP_METRICS_FILE, {}))


def save_startup_metrics_history(payload: Any) -> dict[str, Any]:
    """Persist recent startup timing history."""
    normalized = normalize_startup_metrics_document(payload)
    _write_json(STARTUP_METRICS_FILE, normalized)
    return normalized


def upsert_startup_launch(launch: Any) -> dict[str, Any]:
    """Insert or replace one launch in the bounded startup timing history."""
    normalized_launch = _normalize_launch(launch)
    document = load_startup_metrics_history()
    if normalized_launch is None:
        return document
    launch_id = normalized_launch['launch_id']
    launches = [
        existing for existing in document.get('launches', [])
        if str(existing.get('launch_id', '') or '') != launch_id
    ]
    launches.insert(0, normalized_launch)
    document['launches'] = launches[:STARTUP_METRICS_HISTORY_LIMIT]
    return save_startup_metrics_history(document)


def clear_startup_metrics_history() -> dict[str, Any]:
    """Remove persisted startup timing history."""
    return save_startup_metrics_history(_default_document())
