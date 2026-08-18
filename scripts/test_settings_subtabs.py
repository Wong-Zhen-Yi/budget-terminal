from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.compat import QApplication, QCheckBox, QGroupBox, QLabel, QPushButton, QScrollArea, Qt, QWidget
from budget_terminal_app.mixins import settings as settings_module
from budget_terminal_app.mixins.settings import SettingsMixin


class _SettingsHarness(SettingsMixin, QWidget):
    def __init__(self, state: dict[str, str]) -> None:
        QWidget.__init__(self)
        self.settings_page_state = state
        self.settings_separator_lines = []
        self._clock_country_choices = [{'name': 'United States', 'code': 'US'}]
        self._time_12h = True

    def set_theme_role(self, widget, role: str) -> None:
        widget.setProperty('bt_role', role)

    def set_theme_variant(self, widget, variant) -> None:
        widget.setProperty('bt_variant', variant)

    def set_status_text(self, widget, text, status: str = 'muted') -> None:
        widget.setText(str(text))
        widget.setProperty('bt_status', status)

    def theme_color(self, _name: str) -> str:
        return '#2a3242'

    def _current_clock_country_index(self) -> int:
        return 0

    def _on_settings_clock_country_changed(self, *_args) -> None:
        pass

    def _toggle_time_format(self) -> None:
        self._time_12h = not self._time_12h

def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _panel(title: str) -> QGroupBox:
    return QGroupBox(title)


def _build_tabs(harness: _SettingsHarness):
    return harness._build_settings_tabs(
        _panel('Preferences'),
        _panel('Privacy'),
        _panel('Page Navigation'),
        _panel('User Data'),
        _panel('Keyboard Shortcuts'),
        _panel('Data Health'),
        _panel('Application Logs'),
        _panel('Startup Performance'),
    )


def main() -> None:
    app = QApplication.instance() or QApplication([])
    saved_states: list[dict[str, str]] = []
    original_save = settings_module.save_settings_page_settings
    settings_module.save_settings_page_settings = lambda state: saved_states.append(dict(state)) or dict(state)
    try:
        harness = _SettingsHarness({'active_tab': 'diagnostics'})
        harness.settings_tabs = _build_tabs(harness)
        _assert(harness.settings_tabs.count() == 4, 'Settings should expose four grouped subtabs')
        _assert(
            [harness.settings_tabs.tabText(index) for index in range(harness.settings_tabs.count())]
            == ['General', 'Workspace', 'Data', 'Diagnostics'],
            'Settings subtab labels should remain stable',
        )
        _assert(harness.settings_tabs.currentIndex() == 3, 'the persisted Diagnostics tab should be restored')

        expected_panels = [
            ['Preferences', 'Keyboard Shortcuts'],
            ['Page Navigation', 'Privacy'],
            ['User Data', 'Data Health'],
            ['Application Logs', 'Startup Performance'],
        ]
        for index, expected in enumerate(expected_panels):
            tab = harness.settings_tabs.widget(index)
            titles = [box.title() for box in tab.findChildren(QGroupBox)]
            _assert(titles == expected, f'{harness.settings_tabs.tabText(index)} should contain {expected}')
            scroll_areas = tab.findChildren(QScrollArea)
            _assert(len(scroll_areas) == 1, 'each Settings subtab should have one scroll area')
            _assert(
                scroll_areas[0].horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                'Settings subtabs should not expose nested horizontal scrolling',
            )

        harness.settings_tabs.setCurrentIndex(1)
        _assert(saved_states[-1] == {'active_tab': 'workspace'}, 'changing subtabs should save the stable tab key')

        fallback_harness = _SettingsHarness({'active_tab': 'not-a-tab'})
        fallback_harness.settings_tabs = _build_tabs(fallback_harness)
        _assert(fallback_harness.settings_tabs.currentIndex() == 0, 'invalid state should fall back to General')

        preferences_harness = _SettingsHarness({'active_tab': 'general'})
        preferences_box = preferences_harness._build_settings_preferences_box()
        button_texts = [button.text() for button in preferences_box.findChildren(QPushButton)]
        _assert('Check for Updates' not in button_texts, 'General settings should not expose application updates')
        label_texts = [label.text() for label in preferences_box.findChildren(QLabel)]
        _assert(
            not any(text in {'Windows Startup', 'Application Updates'} for text in label_texts),
            'General settings should not expose Windows startup or application updates sections',
        )
        checkbox_texts = [checkbox.text() for checkbox in preferences_box.findChildren(QCheckBox)]
        _assert(
            not any('sign in to Windows' in text for text in checkbox_texts),
            'General settings should not expose the Windows startup toggle',
        )

        harness.resize(640, 480)
        harness.settings_tabs.resize(620, 420)
        harness.show()
        app.processEvents()
        _assert(harness.settings_tabs.width() <= harness.width(), 'Settings subtabs should fit a narrow page width')
    finally:
        settings_module.save_settings_page_settings = original_save
    print('Settings subtab UI smoke tests passed')


if __name__ == '__main__':
    main()
