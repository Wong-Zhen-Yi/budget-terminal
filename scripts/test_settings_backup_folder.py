from __future__ import annotations

import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app import backup_bundle as bundle_module
from budget_terminal_app import persistence as persistence_module
from budget_terminal_app import strategies as strategies_module
from budget_terminal_app.backup_bundle import (
    BACKUP_FILENAMES,
    CARDS_KIND,
    PAPER_TRADING_KIND,
    USER_DATA_KIND,
    BackupBundleError,
    apply_backup_bundle,
    discover_backup_bundle,
    export_backup_bundle,
)
from budget_terminal_app.paper_trading import (
    PaperTradingStore,
    RecurringRunStatus,
    RecurringScheduleSpec,
)
from budget_terminal_app.paper_trading import store as paper_store_module
from budget_terminal_app.mixins.settings import SettingsMixin


def _user_payload(name: str) -> dict[str, Any]:
    payload = persistence_module._default_user_data_document()
    portfolio_id = payload["portfolio_order"][0]
    payload["portfolios"][portfolio_id]["name"] = name
    payload["exported_at"] = "2026-07-15T12:00:00+00:00"
    payload["app_version"] = "test"
    return payload


def _card(name: str, card_id: str) -> dict[str, Any]:
    return {
        "id": card_id,
        "name": name,
        "symbols": ["SPY"],
        "weighting": "equal",
        "weights": {},
    }


def _cards_payload(cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": strategies_module.STRATEGIES_VERSION,
        "exported_at": "2026-07-15T12:00:01+00:00",
        "weighting_modes": ["equal", "custom"],
        "custom_cards": cards,
        "card_order": [card["id"] for card in cards],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_export_staging_collision_and_cleanup(root: Path) -> None:
    parent = root / "exports"
    parent.mkdir()
    paper_store = PaperTradingStore(root / "export_source.db")
    fixed_now = datetime.datetime(2026, 7, 15, 14, 30, 45)
    original_user_export = bundle_module.export_user_data_backup
    original_cards_export = bundle_module.export_custom_strategies
    try:
        bundle_module.export_user_data_backup = lambda path: _write_json(
            Path(path), _user_payload("Exported")
        )
        bundle_module.export_custom_strategies = lambda path: _write_json(
            Path(path), _cards_payload([])
        )
        first = export_backup_bundle(parent, paper_store=paper_store, now=fixed_now)
        second = export_backup_bundle(parent, paper_store=paper_store, now=fixed_now)
        assert first.folder.name == "BudgetTerminal_Backup_20260715_143045"
        assert second.folder.name == "BudgetTerminal_Backup_20260715_143045_2"
        assert {path.name for path in first.paths.values()} == set(BACKUP_FILENAMES.values())
        assert first.payloads[CARDS_KIND]["custom_cards"] == []
        assert first.metadata[USER_DATA_KIND]["app_version"] == "test"

        before = set(parent.iterdir())

        def _fail_cards_export(_path: Any) -> None:
            raise RuntimeError("simulated Cards export failure")

        bundle_module.export_custom_strategies = _fail_cards_export
        try:
            export_backup_bundle(parent, paper_store=paper_store, now=fixed_now)
        except RuntimeError as exc:
            assert "simulated Cards export failure" in str(exc)
        else:
            raise AssertionError("a failed staged export should raise")
        assert set(parent.iterdir()) == before
        assert not any(path.name.startswith(".BudgetTerminal_Backup_") for path in parent.iterdir())
    finally:
        bundle_module.export_user_data_backup = original_user_export
        bundle_module.export_custom_strategies = original_cards_export


def test_content_discovery_and_strict_completeness(root: Path) -> None:
    folder = root / "discovery"
    folder.mkdir()
    _write_json(folder / "renamed-alpha.json", _cards_payload([]))
    _write_json(folder / "renamed-beta.json", _user_payload("Discovered"))
    PaperTradingStore(root / "discovery_source.db").export_backup(folder / "renamed-gamma.json")
    _write_json(folder / "notes.json", {"notes": ["unrelated"]})
    (folder / "broken.json").write_text("{not-json", encoding="utf-8")

    discovered = discover_backup_bundle(folder)
    assert discovered.paths[CARDS_KIND].name == "renamed-alpha.json"
    assert discovered.paths[USER_DATA_KIND].name == "renamed-beta.json"
    assert discovered.paths[PAPER_TRADING_KIND].name == "renamed-gamma.json"
    assert {path.name for path in discovered.unrecognized_files} == {"notes.json", "broken.json"}

    duplicate = folder / "duplicate-user.json"
    shutil.copy2(folder / "renamed-beta.json", duplicate)
    try:
        discover_backup_bundle(folder)
    except BackupBundleError as exc:
        assert "Multiple valid user data JSON files" in str(exc)
    else:
        raise AssertionError("duplicate recognized types should fail discovery")
    duplicate.unlink()

    paper_path = folder / "renamed-gamma.json"
    hidden_path = folder / "renamed-gamma.backup"
    paper_path.rename(hidden_path)
    try:
        discover_backup_bundle(folder)
    except BackupBundleError as exc:
        assert "Missing a valid Virtual Trading JSON file" in str(exc)
    else:
        raise AssertionError("a missing required type should fail discovery")
    hidden_path.rename(paper_path)

    cards_path = folder / "renamed-alpha.json"
    original_cards = cards_path.read_text(encoding="utf-8")
    _write_json(cards_path, _cards_payload([{"id": "invalid"}]))
    try:
        discover_backup_bundle(folder)
    except BackupBundleError as exc:
        assert "does not contain any valid custom cards" in str(exc)
    else:
        raise AssertionError("invalid Cards payloads should fail discovery")
    cards_path.write_text(original_cards, encoding="utf-8")
    assert discover_backup_bundle(folder).payloads[CARDS_KIND]["custom_cards"] == []


def test_round_trip_merge_replace_and_recovery(root: Path) -> None:
    original_user_data_file = persistence_module.USER_DATA_FILE
    original_rollback_dir = persistence_module.ROLLBACK_BACKUPS_DIR
    original_strategies_file = strategies_module.STRATEGIES_FILE
    original_paper_rollback_dir = paper_store_module.PAPER_ROLLBACK_DIR
    try:
        persistence_module.USER_DATA_FILE = root / "target_user_data.json"
        persistence_module.ROLLBACK_BACKUPS_DIR = root / "user_rollbacks"
        strategies_module.STRATEGIES_FILE = root / "target_strategies.json"
        paper_store_module.PAPER_ROLLBACK_DIR = root / "paper_rollbacks"

        persistence_module.apply_user_data_backup(_user_payload("Before Import"))
        matching = _card("Old Matching", "custom:matching")
        unrelated = _card("Keep Unrelated", "custom:unrelated")
        strategies_module.save_strategies_state({
            "starter_cards_version": strategies_module.STARTER_CARDS_VERSION,
            "custom_cards": [matching, unrelated],
            "card_order": [matching["id"], unrelated["id"]],
        })
        target_paper = PaperTradingStore(root / "target_paper.db")
        target_paper.create_account("Before Paper", 1_000)

        folder = root / "round_trip"
        folder.mkdir()
        _write_json(folder / "data.json", _user_payload("Imported User Data"))
        imported_matching = {**matching, "name": "Updated Matching"}
        added = _card("Added Card", "custom:added")
        _write_json(folder / "cards.json", _cards_payload([imported_matching, added]))
        source_paper = PaperTradingStore(root / "source_paper.db")
        imported_account = source_paper.create_account("Imported Paper", 50_000)
        schedule = source_paper.create_recurring_schedule(
            RecurringScheduleSpec(
                account_id=imported_account["id"],
                kind="funding",
                cadence="monthly",
                amount=500,
                timezone="Asia/Singapore",
                local_time="08:00",
                month_day=31,
            ),
            next_run_at="2026-07-15T00:00:00Z",
        )
        run = source_paper.claim_recurring_run(
            schedule["id"],
            scheduled_for="2026-07-15T00:00:00Z",
            next_run_at="2026-07-31T00:00:00Z",
            started_at="2026-07-15T00:01:00Z",
        )
        assert run is not None
        source_paper.complete_recurring_run(
            run["id"],
            RecurringRunStatus.SKIPPED,
            message="Retained history",
            completed_at="2026-07-15T00:01:00Z",
        )
        source_paper.export_backup(folder / "ledger.json")

        result = apply_backup_bundle(discover_backup_bundle(folder), paper_store=target_paper)
        state = persistence_module.load_all_portfolios_state()
        portfolio_id = state["portfolio_order"][0]
        assert state["portfolios"][portfolio_id]["name"] == "Imported User Data"
        cards_by_id = {
            card["id"]: card for card in strategies_module.load_strategies_state()["custom_cards"]
        }
        assert cards_by_id[matching["id"]]["name"] == "Updated Matching"
        assert unrelated["id"] in cards_by_id
        assert added["id"] in cards_by_id
        assert result.cards["updated_count"] == 1
        assert result.cards["added_count"] == 1
        assert [account["name"] for account in target_paper.list_accounts()] == ["Imported Paper"]
        imported_schedules = target_paper.list_recurring_schedules(imported_account["id"])
        assert len(imported_schedules) == 1
        assert imported_schedules[0]["cadence"] == "monthly"
        imported_runs = target_paper.list_recurring_runs(imported_schedules[0]["id"])
        assert imported_runs[0]["message"] == "Retained history"
        assert Path(result.user_data_rollback).exists()
        assert Path(result.paper_trading_rollback).exists()

        before_user = persistence_module.load_all_portfolios_state()
        before_cards = strategies_module.load_strategies_state()

        class _FailingPaperStore:
            def import_backup(self, _payload: Any) -> str:
                raise RuntimeError("simulated Paper import failure")

        try:
            apply_backup_bundle(discover_backup_bundle(folder), paper_store=_FailingPaperStore())
        except BackupBundleError as exc:
            assert "simulated Paper import failure" in str(exc)
        else:
            raise AssertionError("a failed Paper import should fail the combined import")
        assert persistence_module.load_all_portfolios_state() == before_user
        assert strategies_module.load_strategies_state() == before_cards
    finally:
        persistence_module.USER_DATA_FILE = original_user_data_file
        persistence_module.ROLLBACK_BACKUPS_DIR = original_rollback_dir
        strategies_module.STRATEGIES_FILE = original_strategies_file
        paper_store_module.PAPER_ROLLBACK_DIR = original_paper_rollback_dir


def test_initialized_runtime_refresh_hooks() -> None:
    class _Harness:
        def __init__(self) -> None:
            self.runtime_payload = None
            self.strategies_state = None
            self._p29_performance_cache = {"stale": object()}
            self.cards_refreshes = 0

        def _page_initialized(self, *, page_attr: str) -> bool:
            assert page_attr != "page32"
            return page_attr == "page29"

        def _apply_runtime_user_data(self, payload: Any) -> None:
            self.runtime_payload = payload

        def _p29_refresh_cards(self, *, request_data: bool) -> None:
            assert request_data is False
            self.cards_refreshes += 1

    harness = _Harness()
    result = SimpleNamespace(
        user_data={"portfolios": {"portfolio_1": {}}},
        cards={"state": {"custom_cards": []}},
    )
    SettingsMixin._settings_refresh_after_backup_import(harness, result)
    assert harness.runtime_payload == result.user_data
    assert harness.strategies_state == result.cards["state"]
    assert harness._p29_performance_cache == {}
    assert harness.cards_refreshes == 1



def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        test_export_staging_collision_and_cleanup(root)
        test_content_discovery_and_strict_completeness(root)
        test_round_trip_merge_replace_and_recovery(root)
        test_initialized_runtime_refresh_hooks()
    print("Settings backup-folder smoke tests passed")


if __name__ == "__main__":
    main()
