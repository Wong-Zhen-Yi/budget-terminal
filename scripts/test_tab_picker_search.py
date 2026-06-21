from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent

from budget_terminal_app.persistence import DEFAULT_NAVIGATION_PAGE_ORDER, normalize_navigation_settings


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
        window.closeEvent = lambda event: event.accept()
        window.navigation_state = normalize_navigation_settings(
            {
                "page_order": list(DEFAULT_NAVIGATION_PAGE_ORDER),
                "hidden_pages": [21],
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
        labels = _list_labels(window)
        assert "Calendar > Earnings" in labels
        assert "Portfolio > Pie Chart" in labels
        assert "Valuation > Peers" in labels
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

        window._filter_tab_picker_items("allocation")
        assert window._tab_picker_list.count() == 1
        assert window._tab_picker_list.item(0).text() == "Portfolio > Pie Chart"

        window._filter_tab_picker_items("heatmap")
        assert window._tab_picker_list.count() >= 2
        assert window._tab_picker_list.item(0).text() == "Heatmap"
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
    test_tab_picker_indexes_visible_pages_and_subpages()
    test_tab_picker_activates_lazy_subpage()
    test_tab_picker_activates_portfolio_pie_chart()
    test_backtick_opens_and_refocuses_from_input()
    print("tab picker search smoke passed")
    sys.stdout.flush()
    os._exit(0)
