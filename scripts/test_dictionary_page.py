from __future__ import annotations

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-dictionary-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt

from budget_terminal_app.services.chart_pattern_catalog import CHART_PATTERN_CATALOG
from budget_terminal_app.services.dictionary_catalog import (
    CHART_PATTERNS,
    DICTIONARY_CATEGORIES,
    DICTIONARY_ENTRIES,
    DICTIONARY_ENTRY_BY_ID,
    MACRO_EVENTS,
    get_dictionary_entry,
    search_dictionary_entries,
)


def test_dictionary_catalog_contract() -> None:
    assert len(DICTIONARY_ENTRIES) >= 250
    assert len(DICTIONARY_CATEGORIES) == 14
    assert set(entry.category for entry in DICTIONARY_ENTRIES) == set(DICTIONARY_CATEGORIES)
    assert not [entry_id for entry_id, count in Counter(entry.entry_id for entry in DICTIONARY_ENTRIES).items() if count > 1]
    assert not [term for term, count in Counter(entry.term.casefold() for entry in DICTIONARY_ENTRIES).items() if count > 1]
    assert list(DICTIONARY_ENTRIES) == sorted(DICTIONARY_ENTRIES, key=lambda entry: (entry.term.casefold(), entry.term))

    for entry in DICTIONARY_ENTRIES:
        assert entry.entry_id and entry.term and entry.definition and entry.why_it_matters
        assert entry.category in DICTIONARY_CATEGORIES
        assert entry.entry_id == entry.entry_id.casefold()
        assert all(related_id in DICTIONARY_ENTRY_BY_ID for related_id in entry.related_entry_ids)
        assert entry.entry_id not in entry.related_entry_ids

    formula_entry = get_dictionary_entry("price-to-earnings-ratio")
    assert formula_entry is not None
    assert {section.title for section in formula_entry.sections} == {
        "Formula",
        "Variables",
        "Worked example",
        "Interpretation and limitation",
    }
    event_entry = get_dictionary_entry("cpi-release")
    assert event_entry is not None and event_entry.category == MACRO_EVENTS
    assert {section.title for section in event_entry.sections} == {
        "Publisher and cadence",
        "How to read it",
        "Typical market channels",
        "Caution",
    }

    pattern_entries = [entry for entry in DICTIONARY_ENTRIES if entry.chart_pattern_id]
    assert len(pattern_entries) == len(CHART_PATTERN_CATALOG) == 24
    assert all(entry.category == CHART_PATTERNS for entry in pattern_entries)
    assert {entry.chart_pattern_id for entry in pattern_entries} == {
        pattern.pattern_id for pattern in CHART_PATTERN_CATALOG
    }


def test_dictionary_search_and_filtering() -> None:
    all_entries = search_dictionary_entries()
    assert all_entries == DICTIONARY_ENTRIES

    pe_results = search_dictionary_entries("P/E")
    assert pe_results and pe_results[0].term == "Price-to-Earnings Ratio"
    assert any(entry.term == "Price-to-Earnings Ratio" for entry in search_dictionary_entries("price earnings"))
    assert search_dictionary_entries("RSI")[0].term == "Relative Strength Index"

    macro_results = search_dictionary_entries("inflation", MACRO_EVENTS)
    assert macro_results
    assert all(entry.category == MACRO_EVENTS for entry in macro_results)
    assert any(entry.term == "CPI Release" for entry in macro_results)
    assert not search_dictionary_entries("term-that-does-not-exist-anywhere")


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window._start_lazy_warmup = lambda: None
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_dictionary_page_offscreen_smoke() -> None:
    app, window = _build_window()
    try:
        window.resize(1500, 900)
        window.show()
        app.processEvents()
        assert 37 in window._pages
        assert not window._page_initialized(index=37)
        assert window._ensure_page_initialized(37)
        assert window._page_initialized(index=37)
        assert window.stacked_widget.indexOf(window.page38) == 37
        window.switch_page(37)
        app.processEvents()
        assert len(window.p38_visible_entries) == len(DICTIONARY_ENTRIES)

        window.p38_search_input.setText("P/E")
        app.processEvents()
        assert window.p38_detail_title.text() == "Price-to-Earnings Ratio"
        assert any(title == "Formula" and "P/E" in body for title, body in window.p38_detail_sections)

        window.p38_search_input.clear()
        window.p38_category_combo.setCurrentText(MACRO_EVENTS)
        window.p38_search_input.setText("CPI")
        app.processEvents()
        assert window.p38_detail_title.text() == "CPI Release"
        assert any(title == "Typical market channels" for title, _body in window.p38_detail_sections)

        window.p38_category_combo.setCurrentText("All categories")
        window.p38_search_input.setText("Head and Shoulders")
        app.processEvents()
        assert window.p38_detail_title.text() == "Head and Shoulders"
        assert window.p38_pattern_diagram is not None
        diagram = window.p38_pattern_diagram
        assert diagram.hasHeightForWidth()
        assert abs(diagram.height() - diagram.width() * 9 / 16) <= 1
        window._p38_update_responsive_layout(700)
        assert window.p38_splitter.orientation() == Qt.Orientation.Vertical
        app.processEvents()
        assert abs(diagram.height() - diagram.width() * 9 / 16) <= 1
        window._p38_update_responsive_layout(1100)
        assert window.p38_splitter.orientation() == Qt.Orientation.Horizontal
        app.processEvents()
        assert abs(diagram.height() - diagram.width() * 9 / 16) <= 1

        window._p38_open_related("bid")
        app.processEvents()
        assert window.p38_detail_title.text() == "Bid"
        assert window.p38_search_input.text() == ""
        selected_before_refresh = window.p38_selected_entry_id
        window.switch_page(37)
        app.processEvents()
        window._refresh_current_page()
        assert window.p38_selected_entry_id == selected_before_refresh

        window._apply_dictionary_theme()

        window.p38_search_input.setText("term-that-does-not-exist-anywhere")
        app.processEvents()
        assert not window.p38_visible_entries
        assert "0 of" in window.p38_result_count_label.text()
    finally:
        window.close()
        app.processEvents()


def main() -> None:
    test_dictionary_catalog_contract()
    test_dictionary_search_and_filtering()
    test_dictionary_page_offscreen_smoke()
    print("Dictionary page smoke passed.")


if __name__ == "__main__":
    main()
