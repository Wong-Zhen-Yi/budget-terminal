from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budget_terminal_app.app import BudgetTerminalApp
from budget_terminal_app.compat import QApplication
import budget_terminal_app.persistence as persistence


def main() -> None:
    original_user_data_file = persistence.USER_DATA_FILE
    original_legacy_user_data_file = persistence.LEGACY_USER_DATA_FILE
    try:
        with tempfile.TemporaryDirectory() as tmp:
            persistence.USER_DATA_FILE = Path(tmp) / 'user_data.json'
            persistence.LEGACY_USER_DATA_FILE = Path(tmp) / 'legacy_user_data.json'
            app = QApplication.instance() or QApplication([])
            window = BudgetTerminalApp()

            assert window.privacy_state == {'obscured_pages': [2]}
            assert window.privacy_btn.isChecked()
            assert window.privacy_btn.minimumWidth() >= 82
            assert window._privacy_obscured is True
            assert window.privacy_btn.text() == 'Reveal'
            assert window.page6.graphicsEffect() is not None
            assert window.page6.graphicsEffect().isEnabled()
            assert not window.page6.isEnabled()
            assert window.page4.graphicsEffect() is None
            assert window.page4.isEnabled()
            window._ensure_page_initialized(2)
            assert window.page6.graphicsEffect() is not None
            assert window.page6.graphicsEffect().isEnabled()
            assert not window.page6.isEnabled()

            window._ensure_page_initialized(17)
            from budget_terminal_app.compat import Qt
            for row in range(window.settings_privacy_list.count()):
                item = window.settings_privacy_list.item(row)
                page_index = int(item.data(Qt.ItemDataRole.UserRole))
                desired = Qt.CheckState.Checked if page_index in {0, 1} else Qt.CheckState.Unchecked
                item.setCheckState(desired)
            assert window.privacy_state == {'obscured_pages': [0, 1]}
            assert not window.page1.isEnabled()
            assert not window.page4.isEnabled()
            assert window.page6.isEnabled()
            assert window.page9.isEnabled()

            for row in range(window.settings_privacy_list.count()):
                window.settings_privacy_list.item(row).setCheckState(Qt.CheckState.Unchecked)
            assert window.privacy_state == {'obscured_pages': []}
            assert persistence.load_privacy_settings() == {'obscured_pages': []}
            assert window._privacy_obscured is True
            assert window.privacy_btn.text() == 'Reveal'
            assert window.page1.isEnabled()
            assert window.page4.isEnabled()
            assert window.page6.isEnabled()

            window._privacy_toggle_shortcut.activated.emit()
            assert window._privacy_obscured is False
            assert window.privacy_btn.text() == 'Obscure'

            window.close()
            app.processEvents()
    finally:
        persistence.USER_DATA_FILE = original_user_data_file
        persistence.LEGACY_USER_DATA_FILE = original_legacy_user_data_file
    print('configurable privacy toggle smoke test passed')


if __name__ == '__main__':
    main()
