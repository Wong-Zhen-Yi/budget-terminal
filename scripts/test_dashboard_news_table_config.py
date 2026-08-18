from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.compat import QApplication, QHeaderView, QTableWidget, Qt
from budget_terminal_app.mixins.window_setup import WindowSetupMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_dashboard_news_table_configuration() -> None:
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 4)
    WindowSetupMixin._configure_dashboard_news_table(table)

    _assert(not table.isColumnHidden(1), 'dashboard news ticker column should be visible')
    _assert(table.isColumnHidden(2), 'dashboard news source column should stay hidden')
    _assert(table.isColumnHidden(3), 'dashboard news time column should stay hidden')
    _assert(table.wordWrap(), 'dashboard news headlines should wrap')
    _assert(table.textElideMode() == Qt.TextElideMode.ElideNone, 'dashboard news headlines should not be elided')
    _assert(table.property('bt_full_headlines') is True, 'dashboard news should opt into full-headline row sizing')
    _assert(table.property('bt_full_headlines_max_height') == 0, 'dashboard news row sizing should be uncapped')
    _assert(
        table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch,
        'headline column should stretch',
    )
    _assert(
        table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents,
        'ticker column should resize to contents',
    )

    app.quit()


def main() -> None:
    test_dashboard_news_table_configuration()
    print('dashboard news table configuration smoke tests passed')


if __name__ == '__main__':
    main()
