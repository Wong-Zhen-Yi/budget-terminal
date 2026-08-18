from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QLineEdit, QMessageBox

from budget_terminal_app.persistence import COMBINED_PORTFOLIO_ID, _normalize_multi_portfolio_state
from scripts.test_combined_portfolio import _source_state
from scripts.test_tab_picker_search import _build_window


def _manager_state() -> dict:
    state = _source_state()
    state["main_portfolio_id"] = "portfolio_1"
    state["active_portfolio_id"] = "portfolio_1"
    state["portfolios"]["portfolio_1"]["options_tracker"] = [
        {
            "row_id": "long",
            "ticker": "AAPL",
            "strategy": "Calls",
            "current_price": 2.0,
            "premium": 1.0,
            "contracts": 2,
        }
    ]
    state["portfolios"]["portfolio_2"]["options_tracker"] = [
        {
            "row_id": "short",
            "ticker": "NVDA",
            "strategy": "Covered Call",
            "current_price": 1.0,
            "premium": 3.0,
            "contracts": 1,
        }
    ]
    return state


def _configure_window(window) -> None:
    window.all_portfolios_state = _normalize_multi_portfolio_state(_manager_state())
    window.main_portfolio_id = "portfolio_1"
    window.active_portfolio_id = "portfolio_1"
    window._rebuild_portfolio_slots()
    window._apply_main_portfolio_runtime()
    window._apply_active_portfolio_editor_state()
    window._persist_all_portfolios = lambda **_kwargs: None
    window.refresh_data = lambda **_kwargs: None


def test_manager_summaries_and_network_free_open() -> None:
    app, window = _build_window()
    try:
        _configure_window(window)
        window.last_data = {
            "portfolio": {
                "AAPL": {"price": 110.0},
                "MSFT": {"price": 310.0},
                "NVDA": {"price": 900.0},
            }
        }
        refresh_calls = []
        window.refresh_data = lambda **kwargs: refresh_calls.append(kwargs)
        window.switch_page(1)
        app.processEvents()

        first = window._p4_portfolio_manager_summary("portfolio_1")
        assert first["stock_count"] == 2
        assert first["option_count"] == 1
        assert first["held_count"] == 2
        assert first["priced_count"] == 2
        assert first["stock_value"] == 530.0
        assert first["options_value"] == 400.0
        assert first["cash"] == 100.0
        assert first["margin_debt"] == 40.0
        assert window._p4_portfolio_manager_value_text(first) == "Est. $990.00"

        second = window._p4_portfolio_manager_summary("portfolio_2")
        assert second["stock_value"] == 330.0
        assert second["options_value"] == 200.0
        assert second["margin_debt"] == 60.0
        assert window._p4_portfolio_manager_value_text(second) == "Est. $720.00"

        combined = window._p4_portfolio_manager_summary(COMBINED_PORTFOLIO_ID)
        assert combined["stock_count"] == 4
        assert combined["option_count"] == 2
        assert combined["stock_value"] == 860.0
        assert combined["margin_debt"] == 100.0
        assert window._p4_portfolio_manager_value_text(combined) == "Est. $1,710.00"

        window.last_data = {"portfolio": {"AAPL": {"price": 110.0}}}
        partial = window._p4_portfolio_manager_summary("portfolio_1")
        assert window._p4_portfolio_manager_value_text(partial) == "Partial est. $680.00  ·  1/2 priced"
        window.last_data = None
        unavailable = window._p4_portfolio_manager_summary("portfolio_1")
        assert window._p4_portfolio_manager_value_text(unavailable) == "Value unavailable  ·  0/2 priced"

        dialog = window._p4_build_portfolio_manager_dialog()
        app.processEvents()
        assert dialog.windowTitle() == "Manage Portfolios"
        assert window.p4_portfolio_manager_list.count() == 3
        assert refresh_calls == []
    finally:
        window.close()
        app.processEvents()


def test_manager_rename_selector_sync_and_reorder() -> None:
    app, window = _build_window()
    try:
        _configure_window(window)
        window.switch_page(1)
        app.processEvents()
        dialog = window._p4_build_portfolio_manager_dialog()
        dialog.show()
        app.processEvents()

        assert window.active_portfolio_id == "portfolio_1"
        second_item = window.p4_portfolio_manager_list.item(1)
        second_row = window.p4_portfolio_manager_list.itemWidget(second_item)
        name_editor = second_row.findChild(QLineEdit)
        assert name_editor is not None
        name_editor.setText("Retirement")
        name_editor.editingFinished.emit()
        app.processEvents()
        assert window.active_portfolio_id == "portfolio_1"
        assert window.all_portfolios_state["portfolios"]["portfolio_2"]["name"] == "Retirement"
        assert window.dashboard_portfolio_combo.findText("Retirement") >= 0

        window.rename_portfolio(1, "")
        assert window.all_portfolios_state["portfolios"]["portfolio_2"]["name"] == "Portfolio 2"
        window.rename_portfolio(1, "Retirement")

        assert window.reorder_portfolios(["portfolio_2", "portfolio_1"])
        assert window.all_portfolios_state["portfolio_order"] == ["portfolio_2", "portfolio_1"]
        assert window.active_portfolio_id == "portfolio_1"
        assert window.main_portfolio_id == "portfolio_1"
        selector_ids = [
            window.p4_portfolio_combo.itemData(index)
            for index in range(window.p4_portfolio_combo.count())
        ]
        assert selector_ids == ["portfolio_2", "portfolio_1", COMBINED_PORTFOLIO_ID]
        dashboard_labels = [
            window.dashboard_portfolio_combo.itemText(index)
            for index in range(window.dashboard_portfolio_combo.count())
        ]
        assert dashboard_labels == ["All Portfolios", "Retirement", "Broker One", "Combined"]
        assert not window.reorder_portfolios(["portfolio_1"])
        assert not window.reorder_portfolios(["portfolio_1", COMBINED_PORTFOLIO_ID])

        window.p4_portfolio_combo.setCurrentIndex(0)
        app.processEvents()
        assert window.active_portfolio_id == "portfolio_2"
        assert window.p4_main_portfolio_label.text() == "Main: Broker One"
    finally:
        window.close()
        app.processEvents()


def test_manager_create_delete_and_combined_guards() -> None:
    app, window = _build_window()
    original_question = QMessageBox.question
    try:
        _configure_window(window)
        window.switch_page(1)
        app.processEvents()
        dialog = window._p4_build_portfolio_manager_dialog()
        dialog.show()
        app.processEvents()

        QMessageBox.question = staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
        window._p4_manager_delete("portfolio_2")
        assert window.all_portfolios_state["portfolio_order"] == ["portfolio_1"]
        assert not window.delete_portfolio(0)
        assert not window.delete_portfolio(1)

        assert window.create_portfolio()
        assert window.create_portfolio()
        assert window.create_portfolio()
        assert window.create_portfolio()
        assert not window.create_portfolio()
        assert len(window.all_portfolios_state["portfolio_order"]) == 5
        assert window._p4_get_portfolio_slots()[-1]["portfolio_id"] == COMBINED_PORTFOLIO_ID
        window._p4_refresh_portfolio_manager()
        assert not window.p4_manager_add_btn.isEnabled()

        combined_index = window._p4_manager_index_for_id(COMBINED_PORTFOLIO_ID)
        before = dict(window.all_portfolios_state["portfolios"])
        window.rename_portfolio(combined_index, "Changed")
        assert window.all_portfolios_state["portfolios"] == before
        assert window.set_main_portfolio_index(combined_index) is None
        assert window.main_portfolio_id == COMBINED_PORTFOLIO_ID
    finally:
        QMessageBox.question = original_question
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_manager_summaries_and_network_free_open()
    test_manager_rename_selector_sync_and_reorder()
    test_manager_create_delete_and_combined_guards()
    print("portfolio manager smoke passed")
    sys.stdout.flush()
    os._exit(0)
