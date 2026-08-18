from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView

from budget_terminal_app.persistence import (
    COMBINED_PORTFOLIO_ID,
    COMBINED_PORTFOLIO_NAME,
    _normalize_multi_portfolio_state,
    _serialize_options_storage,
    _serialize_portfolio_storage,
    _serialize_tracker_storage,
    build_combined_portfolio_entry,
)
from scripts.test_tab_picker_search import _build_window


def _source_state() -> dict:
    return {
        "main_portfolio_id": COMBINED_PORTFOLIO_ID,
        "active_portfolio_id": COMBINED_PORTFOLIO_ID,
        "portfolio_order": ["portfolio_1", "portfolio_2"],
        "portfolios": {
            "portfolio_1": {
                "id": "portfolio_1",
                "name": "Broker One",
                "portfolio": ["AAPL", "MSFT"],
                "chart_slots": ["AAPL", "MSFT", "SPY"],
                "portfolio_tracker": {
                    "AAPL": {"shares": 2, "avg_price": 100, "include_in_weight": False},
                    "MSFT": {"shares": 1, "avg_price": 300},
                },
                "options_tracker": [{"row_id": "same", "ticker": "AAPL", "strategy": "Calls"}],
                "cash_balance": 100,
                "margin_debt": 40,
                "include_cash_in_weight": False,
            },
            "portfolio_2": {
                "id": "portfolio_2",
                "name": "Broker Two",
                "portfolio": ["AAPL", "NVDA"],
                "chart_slots": ["NVDA", "AAPL", "QQQ"],
                "portfolio_tracker": {
                    "AAPL": {"shares": 3, "avg_price": 200},
                    "NVDA": {"shares": 0, "avg_price": 900},
                },
                "options_tracker": [{"row_id": "same", "ticker": "NVDA", "strategy": "Puts"}],
                "cash_balance": 250,
                "margin_debt": 60,
            },
        },
    }


def test_combined_portfolio_aggregation_and_normalization() -> None:
    state = _source_state()
    combined = build_combined_portfolio_entry(state)

    assert combined["id"] == COMBINED_PORTFOLIO_ID
    assert combined["name"] == COMBINED_PORTFOLIO_NAME
    assert combined["portfolio"] == ["AAPL", "MSFT", "NVDA"]
    assert combined["portfolio_tracker"]["AAPL"]["shares"] == 5
    assert math.isclose(combined["portfolio_tracker"]["AAPL"]["avg_price"], 160.0)
    assert combined["portfolio_tracker"]["AAPL"]["include_in_weight"] is True
    assert combined["portfolio_tracker"]["NVDA"]["avg_price"] == 0.0
    assert combined["cash_balance"] == 350.0
    assert combined["margin_debt"] == 100.0
    assert combined["include_cash_in_weight"] is True
    assert [row["ticker"] for row in combined["options_tracker"]] == ["AAPL", "NVDA"]
    assert len({row["row_id"] for row in combined["options_tracker"]}) == 2

    state["portfolios"][COMBINED_PORTFOLIO_ID] = {"portfolio": ["SHOULD_NOT_APPEAR"]}
    rebuilt = build_combined_portfolio_entry(state)
    assert "SHOULD_NOT_APPEAR" not in rebuilt["portfolio"]

    normalized = _normalize_multi_portfolio_state(state)
    assert normalized["main_portfolio_id"] == COMBINED_PORTFOLIO_ID
    assert normalized["active_portfolio_id"] == COMBINED_PORTFOLIO_ID
    assert normalized["portfolio_order"] == ["portfolio_1", "portfolio_2"]
    assert COMBINED_PORTFOLIO_ID not in normalized["portfolios"]
    assert normalized["portfolios"]["portfolio_1"]["include_cash_in_weight"] is False
    assert normalized["portfolios"]["portfolio_2"]["include_cash_in_weight"] is True
    assert normalized["portfolios"]["portfolio_1"]["margin_debt"] == 40.0
    assert normalized["portfolios"]["portfolio_2"]["margin_debt"] == 60.0
    for serialized in (
        _serialize_portfolio_storage(state),
        _serialize_tracker_storage(state),
        _serialize_options_storage(state),
    ):
        assert COMBINED_PORTFOLIO_ID not in serialized["portfolio_order"]
        assert COMBINED_PORTFOLIO_ID not in serialized["portfolios"]

    state["portfolios"]["portfolio_2"]["portfolio_tracker"]["AAPL"]["shares"] = 8
    refreshed = build_combined_portfolio_entry(state)
    assert refreshed["portfolio_tracker"]["AAPL"]["shares"] == 10
    assert math.isclose(refreshed["portfolio_tracker"]["AAPL"]["avg_price"], 180.0)

    invalid_margin_state = _normalize_multi_portfolio_state({
        "portfolio_order": ["portfolio_1", "portfolio_2", "portfolio_3"],
        "portfolios": {
            "portfolio_1": {"margin_debt": -10},
            "portfolio_2": {"margin_debt": float("nan")},
            "portfolio_3": {},
        },
    })
    assert invalid_margin_state["portfolios"]["portfolio_1"]["margin_debt"] == 0.0
    assert invalid_margin_state["portfolios"]["portfolio_2"]["margin_debt"] == 0.0
    assert invalid_margin_state["portfolios"]["portfolio_3"]["margin_debt"] == 0.0


def test_margin_debt_is_per_portfolio_and_updates_net_totals() -> None:
    app, window = _build_window()
    try:
        window.all_portfolios_state = _normalize_multi_portfolio_state(_source_state())
        window.main_portfolio_id = "portfolio_1"
        window.active_portfolio_id = "portfolio_1"
        window._rebuild_portfolio_slots()
        window._apply_main_portfolio_runtime()
        window._apply_active_portfolio_editor_state()
        window.last_data = {
            "portfolio": {
                "AAPL": {"price": 10.0, "change": 0.0},
                "MSFT": {"price": 20.0, "change": 0.0},
                "NVDA": {"price": 30.0, "change": 0.0},
            }
        }
        window.switch_page(1)
        app.processEvents()
        window._p4_sync_cash_input()
        assert window.p4_margin_input.value() == 40.0

        _metrics, initial_net_total = window._p4_build_tracker_metrics_map(window.last_data["portfolio"])
        assert initial_net_total == 100.0

        window._ensure_page_initialized(2)
        window._p6_usd_sgd_rate = 1.0
        window.networth_data["cash"] = []
        window.networth_data["debt"] = []
        initial_net_worth, available = window._p6_goal_net_worth("USD")
        assert available
        assert initial_net_worth == 320.0

        persist_calls = []
        window._persist_all_portfolios = lambda **kwargs: persist_calls.append(kwargs)

        def _unexpected_refresh(*_args, **_kwargs):
            raise AssertionError("Editing Margin must not trigger expensive market-data analytics")

        window.update_page4 = _unexpected_refresh
        window._p4_update_cash_dependent_views = _unexpected_refresh
        window._p4_invalidate_momentum_cache = _unexpected_refresh
        window._p4_invalidate_portfolio_analytics_cache = _unexpected_refresh

        window.p4_margin_input.setValue(125.5)
        assert window.all_portfolios_state["portfolios"]["portfolio_1"]["margin_debt"] == 125.5
        assert window.all_portfolios_state["portfolios"]["portfolio_2"]["margin_debt"] == 60.0
        assert persist_calls == [{}]
        _metrics, updated_net_total = window._p4_build_tracker_metrics_map(window.last_data["portfolio"])
        assert updated_net_total == 14.5
        updated_net_worth, available = window._p6_goal_net_worth("USD")
        assert available
        assert updated_net_worth == 234.5
        assert "US$185.50 margin" in window.p6_debt_total_label.text()
        current_series = window._p6_current_total_series()
        portfolio_series = [item for item in current_series if item.get("kind") == "asset"]
        assert [item["value"] for item in portfolio_series] == [14.5, 220.0]
        margin_series = [item for item in current_series if item.get("kind") == "debt"]
        assert [item["value"] for item in margin_series] == [125.5, 60.0]
        assert all(item.get("included_in_portfolio_net") for item in margin_series)
        silo_values = {item["label"]: item["value"] for item in window.p6_silo_bar.items}
        assert silo_values["Broker One"] == 14.5
        assert silo_values["Broker Two"] == 220.0

        window.active_portfolio_id = "portfolio_2"
        window._rebuild_portfolio_slots()
        window._apply_active_portfolio_editor_state()
        window._p4_sync_cash_input()
        assert window.p4_margin_input.value() == 60.0
    finally:
        window.close()
        app.processEvents()


def test_combined_portfolio_ui_is_read_only() -> None:
    app, window = _build_window()
    try:
        window.all_portfolios_state = _normalize_multi_portfolio_state(_source_state())
        window.main_portfolio_id = COMBINED_PORTFOLIO_ID
        window.active_portfolio_id = COMBINED_PORTFOLIO_ID
        window._rebuild_portfolio_slots()
        window._apply_main_portfolio_runtime()
        window._apply_active_portfolio_editor_state()
        window._persist_all_portfolios = lambda **_kwargs: None
        window.refresh_data = lambda **_kwargs: None
        window.main_portfolio_id = "portfolio_1"
        window._rebuild_portfolio_slots()
        window.set_main_portfolio_index(2)
        assert window.main_portfolio_id == COMBINED_PORTFOLIO_ID
        assert window.tickers == ["AAPL", "MSFT", "NVDA"]
        assert window.dashboard_portfolio_combo.itemText(window.dashboard_portfolio_combo.count() - 1) == "Combined"
        window.switch_page(1)
        app.processEvents()

        labels = [window.p4_portfolio_combo.itemText(i) for i in range(window.p4_portfolio_combo.count())]
        ids = [window.p4_portfolio_combo.itemData(i) for i in range(window.p4_portfolio_combo.count())]
        assert labels == ["Broker One", "Broker Two", "Combined  ·  Main · Read only"]
        assert ids == ["portfolio_1", "portfolio_2", COMBINED_PORTFOLIO_ID]
        assert window._p4_editable_portfolio_count() == 2
        assert window.p4_manage_portfolios_btn.isEnabled()
        assert not window.p4_add_stock_btn.isEnabled()
        assert not window.p4_remove_stock_btn.isEnabled()
        assert window.p4_refresh_holdings_btn.isEnabled()
        assert not window.p4_add_options_btn.isEnabled()
        assert not window.p4_remove_options_btn.isEnabled()
        assert not window.p4_cash_input.isEnabled()
        assert not window.p4_margin_input.isEnabled()
        assert window.p4_margin_input.value() == 100.0
        assert not window.p4_cash_include_checkbox.isEnabled()
        assert window.p4_cash_include_checkbox.isChecked()
        assert window.p4_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert window.p4_opt_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert all(
            not (window.p4_table.item(row, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
            for row in range(window.p4_table.rowCount())
            if window.p4_table.item(row, 0) is not None
        )
        assert window.delete_portfolio(2) is False

        before = build_combined_portfolio_entry(window.all_portfolios_state)
        window._on_add_stock_clicked()
        window._add_options_row()
        window._p4_set_active_cash_balance(9999)
        window._p4_set_active_margin_debt(9999)
        window.rename_portfolio(2, "Changed")
        after = build_combined_portfolio_entry(window.all_portfolios_state)
        assert after == before
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_combined_portfolio_aggregation_and_normalization()
    test_margin_debt_is_per_portfolio_and_updates_net_totals()
    test_combined_portfolio_ui_is_read_only()
    print("combined portfolio smoke passed")
    sys.stdout.flush()
    os._exit(0)
