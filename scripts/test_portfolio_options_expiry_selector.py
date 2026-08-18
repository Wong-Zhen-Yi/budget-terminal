from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox

from budget_terminal_app.mixins.options_table_rows import OptionsTableRowsMixin


class _OptionsComboProbe(OptionsTableRowsMixin):
    pass


def test_expiry_text_opens_selector_and_accepts_selection() -> None:
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItem("2026-08-21  (10d)", "2026-08-21")
    combo.addItem("2026-09-18  (38d)", "2026-09-18")
    _OptionsComboProbe()._p4_center_option_combo(combo)
    combo.resize(180, 26)
    combo.show()
    app.processEvents()

    QTest.mouseClick(
        combo,
        Qt.MouseButton.LeftButton,
        pos=QPoint(24, combo.height() // 2),
    )
    app.processEvents()
    assert combo.view().isVisible(), "clicking the displayed expiry should open the date selector"

    QTest.keyClick(combo, Qt.Key.Key_Down)
    app.processEvents()
    assert combo.currentData() == "2026-09-18", "the expiry selector should accept another date"

    combo.hidePopup()
    combo.close()


if __name__ == "__main__":
    test_expiry_text_opens_selector_and_accepts_selection()
    print("portfolio options expiry selector smoke passed")
