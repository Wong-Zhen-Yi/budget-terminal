from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.persistence import _normalize_valuation_page_settings


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins import valuation as valuation_mixin
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    original_save = valuation_mixin.save_valuation_page_settings
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    valuation_mixin.save_valuation_page_settings = _normalize_valuation_page_settings
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window._ensure_page_initialized(22)
        window.resize(1280, 720)
        app.processEvents()
    except Exception:
        valuation_mixin.save_valuation_page_settings = original_save
        raise
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
    return app, window, valuation_mixin, original_save


def _payload(ticker="NVDA", basis=5.0):
    history = pd.DataFrame({"Close": [90.0, 95.0, 100.0, 105.0]})
    return {
        "ticker": ticker,
        "metrics": {
            "ticker": ticker,
            "company_name": "A Very Long Example Semiconductor Company Name",
            "sector": "Technology",
            "industry": "Semiconductors and Advanced Integrated Circuits",
            "price": 105.0,
            "previous_close": 100.0,
            "market_cap": 1_000_000_000.0,
            "basis_type": "FCF",
            "basis_value": basis,
            "fcf_per_share": basis,
            "eps": 3.0,
            "free_cash_flow": 100_000_000.0,
            "net_debt": 0.0,
            "revenue_growth": 12.0,
            "beta": 1.1,
        },
        "trends": {
            "labels": ["2022", "2023", "2024", "2025"],
            "revenue": [100.0, 110.0, 121.0, 133.1],
            "fcf": [20.0, 22.0, 24.2, 26.62],
            "fcf_per_share": [2.0, 2.2, 2.42, 2.662],
            "eps": [1.0, 1.1, 1.21, 1.331],
            "comparable_history_points": 4,
            "per_share_approximate": False,
        },
        "price_history": history,
        "peer_rows": [],
        "peer_warnings": [],
        "sources": {"quote": "Test quote", "statements": "Test statements", "computed": "Test calculation"},
        "suggested_assumptions": {"growth_1_5": 9.0, "growth_6_10": 5.75, "discount_rate": 10.2, "terminal_growth": 2.5},
        "valuation_suggestions": {
            "fields": {
                "growth_1_5": {"value": 9.0, "source": "Median of company growth inputs"},
                "growth_6_10": {"value": 5.75, "source": "Fade toward mature growth"},
                "discount_rate": {"value": 10.2, "source": "10% baseline plus beta"},
                "terminal_growth": {"value": 2.5, "source": "Independent mature-growth anchor"},
            }
        },
        "fetched_at": "2026-07-11T09:00:00+08:00",
    }


def test_valuation_page_smoke() -> None:
    app, window, valuation_mixin, original_save = _build_window()
    try:
        tabs = [window.valuation_detail_tabs.tabText(index) for index in range(window.valuation_detail_tabs.count())]
        assert tabs == ["Main", "Scenarios", "Peers", "Risk", "Trends", "Notes", "Sources"]
        assert window.valuation_page_state["assumptions"]["terminal_method"] == "gordon_growth"
        assert window.valuation_projection_years_spin.minimum() == 5
        assert window.valuation_margin_spin.maximum() == 50.0
        assert window.page23.minimumSizeHint().width() <= 1280

        window.update_valuation_page(_payload(), update_collection_info=False)
        app.processEvents()
        assert window.valuation_fair_value_label.text() != "--"
        assert window.valuation_confidence_label.text() in {"High", "Medium", "Low"}
        assert window.valuation_fair_value_plot.getPlotItem().legend is not None
        assert window.valuation_validation_label.isHidden()

        window._valuation_apply_suggested_assumptions()
        assert window.valuation_growth_1_5_spin.value() == 9.0
        assert "Median of company growth inputs" in window.valuation_assumption_state_label.text()

        window.valuation_terminal_method_combo.setCurrentText("Exit Multiple")
        app.processEvents()
        assert window.valuation_terminal_growth_spin.isHidden()
        assert not window.valuation_exit_multiple_spin.isHidden()
        assert window._valuation_assumptions_from_controls()["terminal_method"] == "exit_multiple"

        window.valuation_basis_type_combo.setCurrentText("EPS")
        app.processEvents()
        assert window.valuation_basis_value_label.text() == "Starting EPS"
        assert window.valuation_terminal_method_combo.isHidden()
        assert window.valuation_exit_multiple_label.text() == "Exit P/E"

        window.valuation_basis_type_combo.setCurrentText("FCF")
        window.valuation_terminal_method_combo.setCurrentText("Gordon Growth")
        window.valuation_discount_spin.setValue(4.0)
        window.valuation_terminal_growth_spin.setValue(5.0)
        app.processEvents()
        assert not window.valuation_validation_label.isHidden()
        assert "at least 1 percentage point" in window.valuation_validation_label.text()
        assert window.valuation_fair_value_label.text() == "--"

        window.valuation_discount_spin.setValue(10.0)
        window.valuation_terminal_growth_spin.setValue(2.5)
        window.valuation_basis_value_spin.setValue(12.0)
        window.valuation_assumption_ticker = "NVDA"
        window.valuation_ticker_input.setText("MSFT")
        window.valuation_page_state = _normalize_valuation_page_settings(window._valuation_settings_payload())
        window._valuation_apply_payload_basis(_payload("MSFT", basis=4.0))
        assert window.valuation_assumption_ticker == "MSFT"
        assert window.valuation_basis_value_spin.value() == 4.0
        assert window.valuation_page_state["assumptions_by_ticker"]["NVDA"]["basis_value"] == 12.0

        snapshot = window._valuation_session_snapshot()
        assert snapshot["assumptions"]["terminal_method"] == "gordon_growth"
        assert window._valuation_restore_session_snapshot(snapshot) is True
    finally:
        valuation_mixin.save_valuation_page_settings = original_save
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_valuation_page_smoke()
    print("valuation page smoke passed")
    sys.stdout.flush()
    os._exit(0)
