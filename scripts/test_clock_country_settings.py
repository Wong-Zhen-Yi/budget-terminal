from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app import persistence as persistence_module
from budget_terminal_app.constants import CLOCK_COUNTRY_CHOICES, TIMEZONE_CHOICES


def _use_temp_user_data(tmp_dir: Path) -> None:
    persistence_module.USER_DATA_FILE = tmp_dir / 'user_data.json'
    persistence_module.LEGACY_USER_DATA_FILE = tmp_dir / 'legacy_user_data.json'
    persistence_module.LEGACY_NOTES_IMAGES_DIR = tmp_dir / 'notes_images'


def test_clock_country_normalization() -> None:
    assert persistence_module.normalize_clock_country_code(None) == 'US'
    assert persistence_module.normalize_clock_country_code('') == 'US'
    assert persistence_module.normalize_clock_country_code('bad') == 'US'
    assert persistence_module.normalize_clock_country_code('sg') == 'SG'


def test_clock_country_persistence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _use_temp_user_data(Path(tmp))
        assert persistence_module.load_clock_country_code() == 'US'
        assert persistence_module.save_clock_country_code('SG') == 'SG'
        assert persistence_module.load_clock_country_code() == 'SG'
        backup = persistence_module.build_user_data_backup()
        assert backup['clock_country_code'] == 'SG'
        ai_export = persistence_module.build_ai_user_data_export()
        assert '## Clock Settings' in ai_export
        assert '"clock_country_code": "SG"' in ai_export
        imported = persistence_module.apply_user_data_backup({**backup, 'clock_country_code': 'bad'})
        assert imported['clock_country_code'] == 'US'
        persistence_module.reset_user_data()
        assert persistence_module.load_clock_country_code() == 'US'


def test_clock_country_choices_and_calendar_timezones() -> None:
    countries = [choice['name'] for choice in CLOCK_COUNTRY_CHOICES]
    assert countries == [
        'United States',
        'Singapore',
        'Canada',
        'United Kingdom',
        'Germany',
        'France',
        'Switzerland',
        'Japan',
        'Hong Kong',
        'Australia',
        'New Zealand',
    ]
    assert ('SGT', 'Asia/Singapore') in TIMEZONE_CHOICES
    assert ('Local', None) in TIMEZONE_CHOICES


if __name__ == '__main__':
    test_clock_country_normalization()
    test_clock_country_persistence()
    test_clock_country_choices_and_calendar_timezones()
    print('Clock country settings smoke tests passed.')
