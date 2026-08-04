from __future__ import annotations

import datetime
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paper_trading import PaperTradingStore
from .persistence import (
    apply_user_data_backup,
    create_rollback_backup_file,
    export_user_data_backup,
    load_user_data_backup,
)
from .strategies import (
    export_custom_strategies,
    load_custom_strategies_import,
    load_strategies_state,
    merge_custom_strategies_import,
    save_strategies_state,
)


USER_DATA_KIND = "user_data"
CARDS_KIND = "cards"
PAPER_TRADING_KIND = "paper_trading"
BACKUP_KINDS = (USER_DATA_KIND, CARDS_KIND, PAPER_TRADING_KIND)

BACKUP_FILENAMES = {
    USER_DATA_KIND: "budget_terminal_user_data.json",
    CARDS_KIND: "budget_terminal_cards.json",
    PAPER_TRADING_KIND: "budget_terminal_paper_trading.json",
}


class BackupBundleError(ValueError):
    """Raised when a backup folder cannot be exported, identified, or applied safely."""


@dataclass(frozen=True)
class BackupBundle:
    folder: Path
    paths: dict[str, Path]
    payloads: dict[str, dict[str, Any]]
    metadata: dict[str, dict[str, str]]
    unrecognized_files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class BackupBundleApplyResult:
    user_data: dict[str, Any]
    cards: dict[str, Any]
    user_data_rollback: str
    paper_trading_rollback: str


def _unique_bundle_directory(parent: Path, now: datetime.datetime | None = None) -> Path:
    timestamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    base_name = f"BudgetTerminal_Backup_{timestamp}"
    destination = parent / base_name
    suffix = 2
    while destination.exists():
        destination = parent / f"{base_name}_{suffix}"
        suffix += 1
    return destination


def _classify_json_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    matches = []
    if payload.get("backup_type") == "budget_terminal_paper_trading":
        matches.append(PAPER_TRADING_KIND)
    if "custom_cards" in payload and isinstance(payload.get("custom_cards"), list):
        matches.append(CARDS_KIND)
    if isinstance(payload.get("portfolios"), dict) or any(
        key in payload for key in ("portfolio", "portfolio_tracker", "options_tracker")
    ):
        matches.append(USER_DATA_KIND)
    if len(matches) > 1:
        raise BackupBundleError(
            f"JSON document matches multiple backup types: {', '.join(matches)}."
        )
    return matches[0] if matches else None


def _load_identified_payload(path: Path, kind: str) -> dict[str, Any]:
    if kind == USER_DATA_KIND:
        return load_user_data_backup(path)
    if kind == CARDS_KIND:
        return load_custom_strategies_import(path, allow_empty=True)
    if kind == PAPER_TRADING_KIND:
        payload = PaperTradingStore.load_backup(path)
        PaperTradingStore._validate_backup_tables(payload["tables"])
        return payload
    raise BackupBundleError(f"Unsupported backup type: {kind}")


def discover_backup_bundle(folder: str | Path) -> BackupBundle:
    root = Path(folder)
    if not root.is_dir():
        raise BackupBundleError("The selected backup folder does not exist.")

    candidates: dict[str, list[tuple[Path, dict[str, Any], dict[str, str]]]] = {
        kind: [] for kind in BACKUP_KINDS
    }
    unrecognized = []
    invalid = []
    json_files = (
        path for path in root.iterdir()
        if path.is_file() and path.suffix.lower() == ".json"
    )
    for path in sorted(json_files, key=lambda item: item.name.lower()):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unrecognized.append(path)
            continue
        try:
            kind = _classify_json_payload(raw)
        except BackupBundleError as exc:
            invalid.append(f"{path.name}: {exc}")
            continue
        if kind is None:
            unrecognized.append(path)
            continue
        try:
            payload = _load_identified_payload(path, kind)
        except Exception as exc:
            invalid.append(f"{path.name}: {exc}")
            continue
        metadata = {
            "exported_at": str(raw.get("exported_at", "") or ""),
            "app_version": str(raw.get("app_version", "") or ""),
        }
        candidates[kind].append((path, payload, metadata))

    problems = list(invalid)
    for kind in BACKUP_KINDS:
        matches = candidates[kind]
        label = {
            USER_DATA_KIND: "user data",
            CARDS_KIND: "Cards",
            PAPER_TRADING_KIND: "Virtual Trading",
        }[kind]
        if not matches:
            problems.append(f"Missing a valid {label} JSON file.")
        elif len(matches) > 1:
            names = ", ".join(path.name for path, _payload, _metadata in matches)
            problems.append(f"Multiple valid {label} JSON files were found: {names}.")
    if problems:
        raise BackupBundleError("\n".join(problems))

    return BackupBundle(
        folder=root,
        paths={kind: candidates[kind][0][0] for kind in BACKUP_KINDS},
        payloads={kind: candidates[kind][0][1] for kind in BACKUP_KINDS},
        metadata={kind: candidates[kind][0][2] for kind in BACKUP_KINDS},
        unrecognized_files=tuple(unrecognized),
    )


def export_backup_bundle(
    parent_directory: str | Path,
    *,
    paper_store: PaperTradingStore | None = None,
    now: datetime.datetime | None = None,
) -> BackupBundle:
    parent = Path(parent_directory)
    if not parent.is_dir():
        raise BackupBundleError("The selected export destination does not exist.")
    destination = _unique_bundle_directory(parent, now)
    staging = parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        export_user_data_backup(staging / BACKUP_FILENAMES[USER_DATA_KIND])
        export_custom_strategies(staging / BACKUP_FILENAMES[CARDS_KIND])
        (paper_store or PaperTradingStore()).export_backup(
            staging / BACKUP_FILENAMES[PAPER_TRADING_KIND]
        )
        discover_backup_bundle(staging)
        staging.rename(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return discover_backup_bundle(destination)


def apply_backup_bundle(
    bundle: BackupBundle,
    *,
    paper_store: PaperTradingStore | None = None,
) -> BackupBundleApplyResult:
    cards_before = load_strategies_state()
    user_data_rollback = ""
    try:
        user_data_rollback = create_rollback_backup_file(reason="before_folder_import")
        normalized_user_data = apply_user_data_backup(bundle.payloads[USER_DATA_KIND])
        cards_payload = bundle.payloads[CARDS_KIND]
        if cards_payload.get("custom_cards"):
            cards_result = merge_custom_strategies_import(cards_payload)
        else:
            cards_result = {
                "state": cards_before,
                "added_count": 0,
                "updated_count": 0,
                "total_imported": 0,
                "skipped_count": int(cards_payload.get("skipped_count", 0) or 0),
            }
        paper_rollback = (paper_store or PaperTradingStore()).import_backup(
            bundle.payloads[PAPER_TRADING_KIND]
        )
    except Exception as exc:
        recovery_errors = []
        try:
            save_strategies_state(cards_before)
        except Exception as recovery_exc:
            recovery_errors.append(f"Cards recovery failed: {recovery_exc}")
        if user_data_rollback:
            try:
                apply_user_data_backup(load_user_data_backup(user_data_rollback))
            except Exception as recovery_exc:
                recovery_errors.append(f"User-data recovery failed: {recovery_exc}")
        detail = f"Unable to import the complete backup folder: {exc}"
        if recovery_errors:
            detail = f"{detail}\n" + "\n".join(recovery_errors)
        raise BackupBundleError(detail) from exc

    return BackupBundleApplyResult(
        user_data=normalized_user_data,
        cards=cards_result,
        user_data_rollback=user_data_rollback,
        paper_trading_rollback=paper_rollback,
    )
