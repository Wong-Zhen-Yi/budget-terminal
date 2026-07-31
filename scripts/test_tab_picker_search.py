from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-tab-picker-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent

from budget_terminal_app.persistence import DEFAULT_NAVIGATION_PAGE_ORDER, normalize_navigation_settings


EXPECTED_DEFAULT_NAVIGATION_ORDER = [
    0, 25, 1, 30, 31, 28, 2, 13, 26, 19, 29, 6, 5, 33, 3, 7, 8,
    22, 9, 27, 11, 12, 14, 24, 18, 20, 23, 21, 15, 16, 37, 17,
]


def test_default_navigation_order_and_normalization() -> None:
    assert DEFAULT_NAVIGATION_PAGE_ORDER == EXPECTED_DEFAULT_NAVIGATION_ORDER
    assert len(DEFAULT_NAVIGATION_PAGE_ORDER) == len(set(DEFAULT_NAVIGATION_PAGE_ORDER))
    assert DEFAULT_NAVIGATION_PAGE_ORDER[0] == 0
    assert DEFAULT_NAVIGATION_PAGE_ORDER[-1] == 17

    partial_order = [0, 25, 1, 5, 26, 27]
    normalized = normalize_navigation_settings({"page_order": partial_order, "hidden_pages": [21]})
    migrated_partial = [0, 25, 1, 30, 31, 5, 33, 26, 27]
    assert normalized["page_order"][:len(migrated_partial)] == migrated_partial
    assert normalized["page_order"][len(migrated_partial):] == [
        page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index not in migrated_partial
    ]
    assert normalized["hidden_pages"] == [21, 30]

    defaults = normalize_navigation_settings(None)
    assert defaults["hidden_pages"] == [21, 30]

    explicitly_visible_paper = normalize_navigation_settings(
        {"page_order": list(EXPECTED_DEFAULT_NAVIGATION_ORDER), "hidden_pages": [21]}
    )
    assert explicitly_visible_paper["hidden_pages"] == [21]

    old_saved_order = [page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index != 29]
    migrated = normalize_navigation_settings({"page_order": old_saved_order, "hidden_pages": []})
    assert migrated["page_order"].index(29) == migrated["page_order"].index(19) + 1

    pre_paper_order = [page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index != 30]
    migrated = normalize_navigation_settings({"page_order": pre_paper_order, "hidden_pages": []})
    assert migrated["page_order"].index(30) == migrated["page_order"].index(1) + 1
    assert migrated["hidden_pages"] == [30]

    pre_virtual_order = [page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index != 31]
    migrated = normalize_navigation_settings({"page_order": pre_virtual_order, "hidden_pages": []})
    assert migrated["page_order"].index(31) == migrated["page_order"].index(30) + 1

    pre_news_order = [page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index != 33]
    migrated = normalize_navigation_settings({"page_order": pre_news_order, "hidden_pages": []})
    assert migrated["page_order"].index(33) == migrated["page_order"].index(5) + 1

    stale_game_order = [
        *[page_index for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER if page_index not in {37, 17}],
        34,
        35,
        36,
        17,
    ]
    migrated = normalize_navigation_settings({"page_order": stale_game_order, "hidden_pages": [34, 35, 36]})
    assert migrated["page_order"] == EXPECTED_DEFAULT_NAVIGATION_ORDER
    assert migrated["hidden_pages"] == []

    legacy_news_order = [0, 25, 1, 5, 4, 32, 33, 3, 17]
    migrated = normalize_navigation_settings({"page_order": legacy_news_order, "hidden_pages": [4, 32]})
    assert 4 not in migrated["page_order"] and 32 not in migrated["page_order"]
    assert 4 not in migrated["hidden_pages"] and 32 not in migrated["hidden_pages"]


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
        # Keep every smoke that reuses this helper deterministic: navigation
        # must not restart production's deferred page warmup after the class
        # monkeypatch below is restored.
        window._start_lazy_warmup = lambda: None

        def close_event(event):
            # Exercise the same worker, timer, batched-render, and executor
            # cleanup as the real window. A minimal test-only close leaves Qt
            # resources alive and can race interpreter shutdown on Windows.
            WindowLifecycleMixin.closeEvent(window, event)

        window.closeEvent = close_event
        window.navigation_state = normalize_navigation_settings(
            {
                "page_order": list(DEFAULT_NAVIGATION_PAGE_ORDER),
                "hidden_pages": [21, 30],
            }
        )
        window._apply_navigation_settings_to_shell()
        window.load_valuation_data = lambda *args, **kwargs: None
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def _list_labels(window) -> list[str]:
    window._refresh_main_tab_picker_items()
    return [str(entry.get("label", "")) for entry in window._tab_picker_entries]


def test_tab_picker_indexes_visible_pages_and_subpages() -> None:
    app, window = _build_window()
    try:
        assert window._recurring_scheduler_startup_status in {"pending", "starting", "ready"}
        executor = window._recurring_scheduler_executor
        if executor is not None:
            assert executor._max_workers == 1
        assert not window._page_initialized(index=30)
        assert not window._page_initialized(index=31)
        visible_order = [
            page_index
            for page_index in EXPECTED_DEFAULT_NAVIGATION_ORDER
            if page_index not in {21, 30}
        ]
        assert [
            page_index
            for page_index in window._navigation_page_order()
            if page_index not in window._hidden_navigation_pages()
        ] == visible_order
        assert [button.text() for button in window._ordered_nav_buttons(visible_only=True)] == [
            window._PAGE_LABELS[page_index] for page_index in visible_order
        ]

        labels = _list_labels(window)
        assert "Calendar > Earnings" in labels
        assert "Portfolio > Pie Chart" in labels
        assert "Valuation > Peers" in labels
        assert "Valuation > Notes" in labels
        assert "Valuation > Sources" in labels
        assert "Charts > Cheat Sheet" in labels
        assert "Projections" in labels
        assert "Cards" in labels
        assert "Price" in labels
        assert [label for label in labels if label.startswith("News")] == ["News"]
        assert "Paper" not in labels
        assert window.btn_page31.isHidden()
        assert "Virtual" in labels
        assert "Ticker Detective" not in labels
        assert "Chart Lab" not in labels
        assert "Analyst Academy" not in labels
        assert "Dictionary" in labels
        assert labels.index("Dictionary") == labels.index("YouTube") + 1
        assert labels.index("Settings") == labels.index("Dictionary") + 1
        assert not window.btn_page38.isHidden()
        assert "Options > Options by Top Volume" in labels
        assert "ETF > Holdings" in labels
        assert "ETF > Arbitrage" in labels
        assert "DATAROMA > Overview" not in labels

        window._filter_tab_picker_items("earnings")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Calendar > Earnings"

        window._filter_tab_picker_items("peers")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Valuation > Peers"

        window._filter_tab_picker_items("arbitrage")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "ETF > Arbitrage"

        window._filter_tab_picker_items("dictionary")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Dictionary"

        window._filter_tab_picker_items("allocation")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Portfolio > Pie Chart"

        window._filter_tab_picker_items("heatmap")
        assert window._tab_picker_list.count() >= 2
        assert window._tab_picker_list.item(0).text() == "Heatmap"

        window._filter_tab_picker_items("price")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Price"
    finally:
        window.close()
        app.processEvents()


def test_tab_picker_activates_lazy_subpage() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=22)
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("peers")
        item = window._tab_picker_list.currentItem()
        assert item is not None

        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 22
        assert window._page_initialized(index=22)
        assert window.valuation_detail_tabs.tabText(window.valuation_detail_tabs.currentIndex()) == "Peers"
        assert not window._tab_picker_popup.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_price_page_is_lazy_and_refreshable() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=29)
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("price")
        item = window._tab_picker_list.currentItem()
        assert item is not None
        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 29
        assert window._page_initialized(index=29)
        assert window.p30_minimum_price_spin.value() == 100.0
        assert window.p30_maximum_price_spin.value() == 200.0

        refreshes = []
        window._p30_fetch = lambda *args, **kwargs: refreshes.append(True)
        window._refresh_current_page()
        assert refreshes == [True]
    finally:
        window.close()
        app.processEvents()


def test_news_page_is_lazy_hydrated_and_refreshable() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=33)
        window.last_data = {
            'news': [
                {
                    'category': 'portfolio',
                    'ticker': 'AAA',
                    'title': 'Hydrated News story',
                    'source': 'Test',
                    '_ts': 1,
                }
            ]
        }
        window._refresh_main_tab_picker_items()
        item = next(
            (window._tab_picker_list.item(index) for index in range(window._tab_picker_list.count()) if window._tab_picker_list.item(index).text() == 'News'),
            None,
        )
        assert item is not None
        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 33
        assert window._page_initialized(index=33)
        assert len(window._p34_portfolio_cards) == 1
        assert window._p34_portfolio_cards[0].article['title'] == 'Hydrated News story'

        refreshes = []
        window._p34_request_news_refresh = lambda: refreshes.append(True)
        window._refresh_current_page()
        assert refreshes == [True]
    finally:
        window.close()
        app.processEvents()


def test_tab_picker_activates_charts_cheat_sheet() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=9)
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("chart patterns")
        assert window._tab_picker_list.count() == 1
        item = window._tab_picker_list.currentItem()
        assert item is not None
        assert item.text() == "Charts > Cheat Sheet"

        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 9
        assert window._page_initialized(index=9)
        assert window.p10_tabs.currentWidget() is window.p10_cheat_tab
        assert window._p10_active_subtab_key() == "cheatsheet"
        assert "Offline reference" in window.status_bar.text()
    finally:
        window.close()
        app.processEvents()


def test_paper_page_is_lazy_and_engine_continues_when_hidden() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=30)
        assert 30 in window._hidden_navigation_pages()
        window.navigation_state = normalize_navigation_settings(
            {
                "page_order": list(DEFAULT_NAVIGATION_PAGE_ORDER),
                "hidden_pages": [21],
            }
        )
        window._apply_navigation_settings_to_shell()
        assert 30 not in window._hidden_navigation_pages()
        assert not window.btn_page31.isHidden()
        refreshes = []
        window._p31_run_engine_cycle = lambda *args, **kwargs: refreshes.append(dict(kwargs))
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("paper")
        item = window._tab_picker_list.currentItem()
        assert item is not None
        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 30
        assert window._page_initialized(index=30)
        assert window._p31_engine_started is True
        assert window._p31_engine_timer.isActive()
        assert window._p31_mark_timer.isActive()
        assert refreshes == [{"mark": True, "force": True}]

        window.switch_page(0)
        app.processEvents()
        assert window._p31_engine_timer.isActive()
        assert window._p31_mark_timer.isActive()
        window._p31_stop()
    finally:
        window.close()
        app.processEvents()


def test_virtual_page_is_lazy_and_engine_continues_when_hidden() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=31)
        refreshes = []
        window._p32_run_engine_cycle = lambda *args, **kwargs: refreshes.append(dict(kwargs))
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("virtual")
        item = window._tab_picker_list.currentItem()
        assert item is not None
        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 31
        assert window._page_initialized(index=31)
        assert window._p32_engine_started is True
        assert window._p32_engine_timer.isActive()
        assert window._p32_mark_timer.isActive()
        assert refreshes == [{"mark": True, "force": True}]

        window.switch_page(0)
        app.processEvents()
        assert window._p32_engine_timer.isActive()
        assert window._p32_mark_timer.isActive()
        window._p32_stop()
    finally:
        window.close()
        app.processEvents()


def test_tab_picker_activates_portfolio_pie_chart() -> None:
    app, window = _build_window()
    try:
        window._refresh_main_tab_picker_items()
        window._filter_tab_picker_items("pie chart")
        item = window._tab_picker_list.currentItem()
        assert item is not None

        window._activate_tab_picker_item(item)
        app.processEvents()

        assert window.stacked_widget.currentIndex() == 1
        assert window._page_initialized(index=1)
        assert window.p4_content_tabs.currentWidget() is window.p4_pie_page
        assert window.p4_content_tabs.tabText(window.p4_content_tabs.currentIndex()) == "Pie Chart"
        assert window.p4_pie_chart._donut_enabled is True
        assert abs(window.p4_pie_chart._donut_hole_ratio - 0.50) < 0.001
        assert window.p4_pie_chart._callout_labels_enabled is True
        assert window.p4_pie_scroll_area.widget() is window.p4_pie_chart
        assert window.p4_pie_scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        window._apply_portfolio_theme()
        assert tuple(window.p4_pie_chart.slice_colors) == tuple(window.theme_pie_palette())
    finally:
        window.close()
        app.processEvents()


def test_backtick_opens_and_refocuses_from_input() -> None:
    app, window = _build_window()
    try:
        window.ticker_input.setFocus()
        app.processEvents()
        quote_left = getattr(Qt.Key, "Key_QuoteLeft", Qt.Key.Key_Apostrophe)
        event = QKeyEvent(QEvent.Type.KeyPress, quote_left, Qt.KeyboardModifier.NoModifier, "`")

        assert window._handle_global_input_exit_event(window.ticker_input, event)
        app.processEvents()
        assert window._tab_picker_popup.isVisible()
        assert window._tab_picker_input.hasFocus()

        window._tab_picker_input.setText("earnings")
        window._handle_tab_picker_shortcut()
        app.processEvents()
        assert window._tab_picker_popup.isVisible()
        assert window._tab_picker_input.text() == "earnings"
        assert window._tab_picker_input.hasFocus()
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_default_navigation_order_and_normalization()
    test_tab_picker_indexes_visible_pages_and_subpages()
    test_tab_picker_activates_lazy_subpage()
    test_tab_picker_activates_charts_cheat_sheet()
    test_price_page_is_lazy_and_refreshable()
    test_news_page_is_lazy_hydrated_and_refreshable()
    test_paper_page_is_lazy_and_engine_continues_when_hidden()
    test_virtual_page_is_lazy_and_engine_continues_when_hidden()
    test_tab_picker_activates_portfolio_pie_chart()
    test_backtick_opens_and_refocuses_from_input()
    print("tab picker search smoke passed")
    sys.stdout.flush()
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.closeAllWindows()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        app.quit()
