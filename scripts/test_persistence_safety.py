from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import budget_terminal_app.persistence as persistence


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    original_user_data_file = persistence.USER_DATA_FILE
    original_legacy_user_data_file = persistence.LEGACY_USER_DATA_FILE
    original_corrupt_backup_dir = persistence.CORRUPT_USER_DATA_BACKUPS_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            user_data_file = tmp_path / 'user_data.json'
            legacy_user_data_file = tmp_path / 'legacy_user_data.json'
            corrupt_backup_dir = tmp_path / 'backups' / 'corrupt'
            user_data_file.write_text('{"portfolios": ', encoding='utf-8')

            persistence.USER_DATA_FILE = user_data_file
            persistence.LEGACY_USER_DATA_FILE = legacy_user_data_file
            persistence.CORRUPT_USER_DATA_BACKUPS_DIR = corrupt_backup_dir

            loaded = persistence._load_user_data_document()
            _assert(isinstance(loaded, dict), 'corrupt user data should fall back to a normalized document')
            _assert(loaded['privacy'] == {'obscured_pages': [2]}, 'missing privacy settings should default to Personal Finance')
            _assert(loaded['settings_page'] == {'active_tab': 'general'}, 'missing Settings-page state should default to General')
            backups = list(corrupt_backup_dir.glob('user_data_invalid_json_*.json'))
            _assert(len(backups) == 1, 'corrupt user data should be copied to one timestamped backup')
            _assert(backups[0].read_text(encoding='utf-8') == '{"portfolios": ', 'backup should preserve corrupt contents')

            saved = persistence._save_user_data_document({'portfolio': ['SPY']})
            on_disk = json.loads(user_data_file.read_text(encoding='utf-8'))
            _assert(on_disk['version'] == saved['version'], 'atomic save should write valid normalized JSON')
            _assert(not list(tmp_path.glob('.*.tmp')), 'atomic save should not leave temp files after success')

            persistence.save_networth_data({
                'cash': [],
                'debt': [],
                'recurring_bills': [
                    {'desc': 'Rent', 'amount': '2500', 'frequency': 'monthly', 'currency': 'SGD'},
                    {'description': 'Streaming', 'amount': 180, 'frequency': 'yearly', 'currency': 'USD'},
                ],
                'totals_currency': 'USD',
            })
            loaded_networth = persistence.load_networth_data()
            loaded_bills = loaded_networth.get('recurring_bills', [])
            _assert(len(loaded_bills) == 2, 'recurring bills should round-trip through user_data.json')
            _assert(loaded_bills[0]['desc'] == 'Rent', 'recurring bill descriptions should persist')
            _assert(loaded_bills[0]['amount'] == 2500.0, 'recurring bill amounts should persist as numbers')
            _assert(loaded_bills[0]['frequency'] == 'monthly', 'recurring bill cycle should persist')
            _assert(loaded_bills[1]['currency'] == 'USD', 'recurring bill currency should persist')
            _assert('pension_insurance' not in loaded_networth, 'pension and insurance data should not be persisted')
            saved_payload = json.loads(user_data_file.read_text(encoding='utf-8'))
            _assert('pension_insurance' not in saved_payload['net_worth'], 'user_data.json should not contain pension_insurance')

            _assert(
                persistence.normalize_privacy_settings({'obscured_pages': []}) == {'obscured_pages': []},
                'an explicit empty privacy selection should remain empty',
            )
            _assert(
                persistence.normalize_privacy_settings({'obscured_pages': [17, 999, '1', 1]}) == {'obscured_pages': [1]},
                'privacy normalization should discard Settings, invalid indexes, and duplicates',
            )
            persistence.save_privacy_settings({'obscured_pages': [0, 1]})
            _assert(
                persistence.load_privacy_settings() == {'obscured_pages': [0, 1]},
                'privacy settings should round-trip through user_data.json',
            )
            _assert(
                persistence.normalize_settings_page_settings({'active_tab': 'unknown'}) == {'active_tab': 'general'},
                'unknown Settings subtabs should fall back to General',
            )
            persistence.save_settings_page_settings({'active_tab': 'diagnostics'})
            _assert(
                persistence.load_settings_page_settings() == {'active_tab': 'diagnostics'},
                'the active Settings subtab should round-trip through user_data.json',
            )
            backup = persistence.build_user_data_backup()
            _assert(backup['privacy'] == {'obscured_pages': [0, 1]}, 'backups should include privacy settings')
            _assert(backup['settings_page'] == {'active_tab': 'diagnostics'}, 'backups should include Settings-page state')
            backup['privacy'] = {'obscured_pages': []}
            backup['settings_page'] = {'active_tab': 'workspace'}
            imported = persistence.apply_user_data_backup(backup)
            _assert(imported['privacy'] == {'obscured_pages': []}, 'backup import should preserve an empty privacy selection')
            _assert(imported['settings_page'] == {'active_tab': 'workspace'}, 'backup import should restore the active Settings subtab')

            persistence.save_networth_data({
                'cash': [],
                'pension_insurance': [{'desc': 'Legacy Pension', 'amount': 1000}],
                'debt': [],
            })
            legacy_payload = json.loads(user_data_file.read_text(encoding='utf-8'))
            _assert('pension_insurance' not in legacy_payload['net_worth'], 'legacy pension_insurance input should be dropped on save')
            reset_payload = persistence.reset_user_data()
            _assert(reset_payload['privacy'] == {'obscured_pages': [2]}, 'reset should restore the Personal Finance privacy default')
            _assert(reset_payload['settings_page'] == {'active_tab': 'general'}, 'reset should restore the General Settings subtab')
    finally:
        persistence.USER_DATA_FILE = original_user_data_file
        persistence.LEGACY_USER_DATA_FILE = original_legacy_user_data_file
        persistence.CORRUPT_USER_DATA_BACKUPS_DIR = original_corrupt_backup_dir
    print('persistence safety smoke tests passed')


if __name__ == '__main__':
    main()
