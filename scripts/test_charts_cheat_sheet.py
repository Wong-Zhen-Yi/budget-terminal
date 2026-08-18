from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.persistence import _normalize_chart_page_settings
from budget_terminal_app.services.chart_pattern_catalog import (
    CHART_PATTERN_CATALOG,
    CHART_PATTERN_FAMILIES,
)
from budget_terminal_app.widgets.chart_pattern_cheat_sheet import ChartPatternCheatSheet
from scripts.test_charts_startup_indicators import _build_window


EXPECTED_PATTERN_NAMES = {
    "Head and Shoulders",
    "Inverse Head and Shoulders",
    "Double Top",
    "Double Bottom",
    "Triple Top",
    "Triple Bottom",
    "Rounding Top",
    "Rounding Bottom",
    "Cup and Handle",
    "Inverse Cup and Handle",
    "Bull Flag",
    "Bear Flag",
    "Bull Pennant",
    "Bear Pennant",
    "Bullish Rectangle",
    "Bearish Rectangle",
    "Ascending Triangle",
    "Descending Triangle",
    "Symmetrical Triangle",
    "Rising Wedge",
    "Falling Wedge",
    "Broadening Formation",
    "Ascending Channel",
    "Descending Channel",
}


def test_chart_pattern_catalog_is_complete_and_normalized() -> None:
    assert len(CHART_PATTERN_CATALOG) == 24
    assert {pattern.name for pattern in CHART_PATTERN_CATALOG} == EXPECTED_PATTERN_NAMES
    assert len({pattern.pattern_id for pattern in CHART_PATTERN_CATALOG}) == 24
    assert Counter(pattern.family for pattern in CHART_PATTERN_CATALOG) == {
        "Reversal": 10,
        "Continuation": 6,
        "Compression / Breakout": 6,
        "Trend Channel": 2,
    }
    for pattern in CHART_PATTERN_CATALOG:
        assert pattern.aliases
        assert pattern.family in CHART_PATTERN_FAMILIES
        assert pattern.bias in {"Bullish", "Bearish", "Neutral"}
        assert pattern.direction in {"up", "down", "either"}
        assert len(pattern.price_path) >= 4
        assert pattern.guide_lines
        assert all((pattern.recognition, pattern.confirmation, pattern.invalidation, pattern.target))
        geometry = [*pattern.price_path, pattern.breakout_marker]
        for guide in pattern.guide_lines:
            geometry.extend((guide.start, guide.end))
        assert all(0.0 <= x_value <= 1.0 and 0.0 <= y_value <= 1.0 for x_value, y_value in geometry)


def _theme_palette() -> dict[str, str]:
    return {
        "accent": "#4da3ff",
        "accent_positive": "#36c98f",
        "accent_negative": "#ff6b7a",
        "chart_bg": "#10151d",
        "chart_reference": "#64748b",
        "panel_background": "#151c26",
        "panel_border": "#2a3545",
        "text_muted": "#8c99ae",
        "text_secondary": "#c0c8d4",
        "warning": "#f4bd61",
        "warning_bg": "#2f2719",
    }


def test_cheat_sheet_filters_reflow_and_theme_offscreen() -> None:
    from budget_terminal_app.main import QApplication

    app = QApplication.instance() or QApplication([])
    palette = _theme_palette()
    sheet = ChartPatternCheatSheet(lambda token: palette[token])
    sheet.resize(1500, 900)
    sheet.show()
    app.processEvents()
    try:
        assert len(sheet.cards) == 24
        assert sheet.visible_pattern_ids() == tuple(pattern.pattern_id for pattern in CHART_PATTERN_CATALOG)
        assert sheet.count_label.text() == "24 of 24 patterns"
        assert "Offline reference" in sheet.status_text
        assert "probabilistic" in sheet.notice_label.text()
        for card in sheet.cards.values():
            assert set(card.detail_labels) == {"recognition", "confirmation", "invalidation", "target"}
            assert all(label.text().strip() for label in card.detail_labels.values())
            assert not card.isHidden()

        sheet.search_input.setText("shoulders")
        app.processEvents()
        assert len(sheet.visible_pattern_ids()) == 2
        assert sheet.count_label.text() == "2 of 24 patterns"

        sheet.search_input.clear()
        continuation_index = sheet.family_combo.findData("Continuation")
        assert continuation_index >= 0
        sheet.family_combo.setCurrentIndex(continuation_index)
        app.processEvents()
        assert len(sheet.visible_pattern_ids()) == 6

        bullish_index = sheet.bias_combo.findData("Bullish")
        assert bullish_index >= 0
        sheet.bias_combo.setCurrentIndex(bullish_index)
        app.processEvents()
        assert len(sheet.visible_pattern_ids()) == 3

        sheet.search_input.setText("not-a-real-pattern")
        app.processEvents()
        assert sheet.visible_pattern_ids() == ()
        assert sheet.count_label.text() == "0 of 24 patterns"
        assert not sheet.empty_label.isHidden()

        sheet.search_input.clear()
        sheet.family_combo.setCurrentIndex(0)
        sheet.bias_combo.setCurrentIndex(0)
        for width, expected_columns in ((850, 1), (1000, 2), (1500, 3)):
            sheet.resize(width, 900)
            sheet._reflow_cards(width=width)
            app.processEvents()
            assert sheet.column_count == expected_columns
            diagram = sheet.cards["double_bottom"].diagram
            assert diagram.hasHeightForWidth()
            assert abs(diagram.height() - diagram.width() * 9 / 16) <= 1

        diagram = sheet.cards["double_bottom"].diagram
        assert not diagram.grab().isNull()
        before = diagram.colors["bullish"]
        palette["accent_positive"] = "#11ee99"
        sheet.apply_theme()
        assert diagram.colors["bullish"] == "#11ee99"
        assert diagram.colors["bullish"] != before
    finally:
        sheet.close()
        sheet.deleteLater()
        app.processEvents()


def test_charts_cheat_sheet_tab_and_refresh_isolation() -> None:
    app, window = _build_window(_normalize_chart_page_settings({}))
    try:
        assert [window.p10_tabs.tabText(index) for index in range(window.p10_tabs.count())] == [
            "Main",
            "Multi Charts",
            "Compare",
            "Relationship",
            "Cheat Sheet",
        ]
        calls: list[str] = []
        window._p10_refresh_chart = lambda *args, **kwargs: calls.append("main")
        window._p10_refresh_compare_view = lambda *args, **kwargs: calls.append("compare")
        window._p10_refresh_multi_interval_views = lambda *args, **kwargs: calls.append("multiintervals")
        window._mc_on_show = lambda *args, **kwargs: calls.append("multicharts-show")
        window._mc_refresh_all = lambda *args, **kwargs: calls.append("multicharts-refresh")

        window.p10_tabs.setCurrentWidget(window.p10_cheat_tab)
        app.processEvents()
        assert window._p10_active_subtab_key() == "cheatsheet"
        window._p10_on_show()
        window.stacked_widget.setCurrentWidget(window.page10)
        window._refresh_current_page()
        app.processEvents()

        assert calls == []
        assert "Offline reference" in window.p10_cheat_status_label.text()
        assert "Offline reference" in window.status_bar.text()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    test_chart_pattern_catalog_is_complete_and_normalized()
    test_cheat_sheet_filters_reflow_and_theme_offscreen()
    test_charts_cheat_sheet_tab_and_refresh_isolation()
    print("charts cheat sheet tests passed")
