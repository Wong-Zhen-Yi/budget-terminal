from __future__ import annotations

from dataclasses import dataclass
from typing import Any


USER_DATA_SCHEMA_VERSION = 13
TAB_SESSION_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MigrationResult:
    payload: dict[str, Any]
    source_version: int
    target_version: int
    migrated: bool = False


def _coerce_version(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def migrate_user_data_payload(payload: Any, default_document: dict[str, Any], *, strict_future: bool = False) -> MigrationResult:
    """Return a payload shaped for current user_data.json normalization."""
    raw = dict(payload) if isinstance(payload, dict) else {}
    source_version = _coerce_version(raw.get("version", 0))
    if strict_future and source_version > USER_DATA_SCHEMA_VERSION:
        raise ValueError(
            f"Backup schema version {source_version} is newer than supported version {USER_DATA_SCHEMA_VERSION}."
        )
    migrated = source_version != USER_DATA_SCHEMA_VERSION
    if not raw:
        raw = dict(default_document)
    raw["version"] = USER_DATA_SCHEMA_VERSION
    return MigrationResult(
        payload=raw,
        source_version=source_version,
        target_version=USER_DATA_SCHEMA_VERSION,
        migrated=migrated,
    )


def migrate_tab_session_payload(payload: Any, tab_keys: tuple[str, ...]) -> MigrationResult:
    """Return a payload shaped for current tab_session_cache.json normalization."""
    raw = dict(payload) if isinstance(payload, dict) else {}
    source_version = _coerce_version(raw.get("version", 0))
    raw_tabs = raw.get("tabs", raw)
    tabs = {}
    if isinstance(raw_tabs, dict):
        for tab_key in tab_keys:
            value = raw_tabs.get(tab_key)
            tabs[tab_key] = value if isinstance(value, dict) else None
    else:
        tabs = {tab_key: None for tab_key in tab_keys}
    return MigrationResult(
        payload={"version": TAB_SESSION_CACHE_SCHEMA_VERSION, "tabs": tabs},
        source_version=source_version,
        target_version=TAB_SESSION_CACHE_SCHEMA_VERSION,
        migrated=source_version != TAB_SESSION_CACHE_SCHEMA_VERSION or "tabs" not in raw,
    )
