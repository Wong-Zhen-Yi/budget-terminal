from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_DATA_DIR = tempfile.TemporaryDirectory(
    prefix="budget-terminal-valuation-smoke-",
    ignore_cleanup_errors=True,
)
os.environ["LOCALAPPDATA"] = _TEST_DATA_DIR.name

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
        window.stacked_widget.setCurrentIndex(22)
        window.resize(1280, 720)
        window.show()
        app.processEvents()
    except Exception:
        valuation_mixin.save_valuation_page_settings = original_save
        raise
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
    return app, window, valuation_mixin, original_save


DERIVED_VALUES = {
    "growth_1_5": 14.2,
    "growth_6_10": 7.0,
    "discount_rate": 9.4,
    "terminal_growth": 2.4,
    "exit_multiple": 21.3,
    "margin_of_safety": 20.0,
}


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
            "eps": [None, 1.1, 1.21, 1.331],
            "comparable_history_points": 4,
            "per_share_approximate": False,
        },
        "price_history": history,
        "peer_rows": [
            {"ticker": ticker, "company": ticker, "source": "Loaded", "market_cap": 1e9, "fcf_yield": 1.0, "pe": 60.0},
            {"ticker": "AMD", "company": "AMD", "source": "Auto", "market_cap": 2e11, "fcf_yield": 5.0, "pe": 20.0},
            {"ticker": "INTC", "company": "Intel", "source": "Auto", "market_cap": 1e11, "fcf_yield": 4.0, "pe": 25.0},
            {"ticker": "AVGO", "company": "Broadcom", "source": "Auto", "market_cap": 5e11, "fcf_yield": 10.0, "pe": 10.0},
        ],
        "peer_warnings": [],
        "market_context": {
            "risk_free_rate": 4.21,
            "real_rate": 1.85,
            "breakeven_inflation": 2.36,
            "as_of": "2026-08-20",
            "tenor": "10Y",
            "freshness": "fresh",
            "source": "US Treasury daily par yield curve, 10Y",
        },
        "analyst_estimates": {
            "long_term_growth_pct": 21.4,
            "next_year_growth_pct": 18.0,
            "current_year_growth_pct": 25.0,
            "analyst_count": 42,
            "available": True,
            "source": "Yahoo analyst earnings trend",
        },
        "sources": {"quote": "Test quote", "statements": "Test statements", "computed": "Test calculation"},
        "sec": {
            "available": True,
            "statements_available": True,
            "provenance": {
                "Total Revenue": {
                    "quarterly": {
                        "2025-03-31": {
                            "tag": "Revenues",
                            "form": "10-Q",
                            "filed": "2025-05-01",
                            "accession": "0001-25-000001",
                            "derived": False,
                        }
                    },
                    "annual": {},
                }
            },
        },
        "suggested_assumptions": DERIVED_VALUES,
        "valuation_suggestions": {
            "fields": {
                "growth_1_5": {
                    "value": 14.2,
                    "source": "40% analyst next-year growth blended with 60% median of 3-year revenue CAGR",
                    "inputs": [
                        {"name": "3-year revenue CAGR", "value": 10.0},
                        {"name": "analyst next-year growth", "value": 18.0},
                    ],
                },
                "growth_6_10": {"value": 7.0, "source": "Average of a linear fade toward terminal growth"},
                "discount_rate": {
                    "value": 9.4,
                    "source": "CAPM: 4.21% 10Y Treasury + 1.07 adjusted beta",
                    "method": "capm",
                    "risk_free_rate": 4.21,
                },
                "terminal_growth": {
                    "value": 2.4,
                    "source": "10Y breakeven inflation (2.36%)",
                    "breakeven_inflation": 2.36,
                    "caps_applied": [],
                },
                "exit_multiple": {"value": 21.3, "source": "Median P/FCF of 3 peers", "peer_count": 3},
                "margin_of_safety": {"value": 20.0, "source": "Scaled to model support"},
            },
            "caveats": [
                "Suggestions require consecutive, consistently positive annual history.",
                "Analyst estimates unavailable; near-term growth uses reported history only.",
            ],
        },
        "fetched_at": "2026-07-11T09:00:00+08:00",
    }


def _mismatched_currency_payload():
    """A GRVY-shaped payload: a USD quote over KRW statements, as Yahoo reports it."""
    payload = _payload("GRVY", basis=10040.58)
    payload["metrics"].update(
        {
            "company_name": "Gravity Co Ltd",
            "price": 70.25,
            "previous_close": 69.80,
            "currency": "USD",
            "financial_currency": "KRW",
            "currency_mismatch": True,
            "eps": 12000.0,
            "fcf_per_share": 10040.58,
            "cash": 200_000_000_000.0,
            "debt": 0.0,
            "net_debt": -200_000_000_000.0,
            # The worker withholds every crossed ratio; the page must render that, not backfill it.
            "pe": None,
            "ps": None,
            "ev_ebitda": None,
            "fcf_yield": None,
            "earnings_yield": None,
        }
    )
    return payload


def _assert_currency_mismatch_is_blocking(window, app) -> None:
    """A KRW fair value must never be shown as a verdict against a USD price."""
    window.update_valuation_page(_mismatched_currency_payload(), update_collection_info=False)
    app.processEvents()

    scenarios = window.valuation_current_scenarios
    assert scenarios["price_comparison_valid"] is False
    assert scenarios["verdict"] is None
    assert scenarios["buy_below"] is None
    assert scenarios["trim_above"] is None
    assert scenarios["base_fair_value"] is not None, "the DCF itself still solves in KRW"

    assert window.valuation_verdict_value.text() == "Not comparable"
    assert window.valuation_fair_value_label.text() == "--"
    assert window.valuation_upside_label.text() == "--"
    assert window.valuation_band_label.text() == "--"

    assert not window.valuation_validation_label.isHidden()
    validation_text = window.valuation_validation_label.text()
    assert "quoted in USD" in validation_text, validation_text
    assert "report in KRW" in validation_text, validation_text
    assert window.valuation_validation_label.property("bt_role") == "status_negative"

    # Only the price line survives on the band chart; a KRW band on a USD axis is the defect itself.
    fair_value_series = [item.name() for item in window.valuation_fair_value_plot.getPlotItem().listDataItems()]
    assert fair_value_series == ["Current price"], fair_value_series
    assert not window.valuation_pe_plot.getPlotItem().listDataItems()

    assert window.valuation_metric_values["pe"][0].text() == "--"
    assert window.valuation_metric_values["pe"][1].text() == "currency mismatch"
    assert window.valuation_metric_values["pb"][1].text() == "quote/statements"

    risk_notes = [
        window.valuation_risk_table.item(row, 2).text()
        for row in range(window.valuation_risk_table.rowCount())
    ]
    assert "Liquidity - reported in KRW" in risk_notes, risk_notes

    # A matching-currency payload leaves every one of those outputs intact.
    window.update_valuation_page(_payload(), update_collection_info=False)
    app.processEvents()
    assert window.valuation_current_scenarios["price_comparison_valid"] is True
    assert window.valuation_fair_value_label.text() != "--"
    assert window.valuation_validation_label.isHidden()
    assert window.valuation_metric_values["pe"][1].text() == "computed"


def test_valuation_page_smoke() -> None:
    app, window, valuation_mixin, original_save = _build_window()
    try:
        tabs = [window.valuation_detail_tabs.tabText(index) for index in range(window.valuation_detail_tabs.count())]
        assert tabs == ["Main", "Scenarios", "Peers", "Risk", "Trends", "Notes", "Sources"]
        assert window.valuation_page_state["assumptions"]["terminal_method"] == "gordon_growth"
        assert window.valuation_projection_years_spin.minimum() == 5
        assert window.valuation_margin_spin.maximum() == 50.0
        assert window.page23.minimumSizeHint().width() <= 1280
        assert window.valuation_verdict_frame.height() < 80
        for column in range(6):
            assert window.valuation_verdict_layout.getItemPosition(column * 2) == (0, column, 1, 1)
            assert window.valuation_verdict_layout.getItemPosition(column * 2 + 1) == (1, column, 1, 1)
        visible_assumption_controls = (
            window.valuation_basis_type_combo,
            window.valuation_basis_value_spin,
            window.valuation_growth_1_5_spin,
            window.valuation_growth_6_10_spin,
            window.valuation_projection_years_spin,
            window.valuation_discount_spin,
            window.valuation_terminal_method_combo,
            window.valuation_terminal_growth_spin,
            window.valuation_margin_spin,
        )
        for control in visible_assumption_controls:
            assert control.isVisible()
            assert control.height() >= control.minimumSizeHint().height()

        window.valuation_page_state = {
            **window.valuation_page_state,
            "assumptions_by_ticker": {"NVDA": {**window.valuation_page_state["assumptions"], "growth_1_5": 42.0}},
        }
        window.update_valuation_page(_payload(), update_collection_info=False)
        app.processEvents()
        for field, expected in DERIVED_VALUES.items():
            spin = {
                "growth_1_5": window.valuation_growth_1_5_spin,
                "growth_6_10": window.valuation_growth_6_10_spin,
                "discount_rate": window.valuation_discount_spin,
                "terminal_growth": window.valuation_terminal_growth_spin,
                "exit_multiple": window.valuation_exit_multiple_spin,
                "margin_of_safety": window.valuation_margin_spin,
            }[field]
            assert spin.value() == expected, (field, spin.value(), expected)
        assert window.valuation_assumption_state_label.text().startswith("Auto-derived")
        assert "1 caveat" in window.valuation_assumption_state_label.text()
        assert "analyst + reported history" in window.valuation_assumption_state_label.text()
        assert window.valuation_basis_value_spin.value() == 5.0
        assert window.valuation_fair_value_label.text() != "--"
        assert window.valuation_confidence_label.text() in {"High", "Medium", "Low"}
        assert window.valuation_fair_value_plot.getPlotItem().legend is not None
        assert window.valuation_validation_label.isHidden()
        trend_items = window.valuation_trend_plot.getPlotItem().listDataItems()
        eps_item = next(item for item in trend_items if item.name() == "EPS")
        assert eps_item.yData.dtype.kind == "f"
        assert pd.isna(eps_item.yData[0])
        source_labels = [
            window.valuation_source_table.item(row, 0).text()
            for row in range(window.valuation_source_table.rowCount())
        ]
        assert "Total Revenue" in source_labels
        revenue_source_row = source_labels.index("Total Revenue")
        assert "0001-25-000001" in window.valuation_source_table.item(revenue_source_row, 1).text()

        window.valuation_growth_1_5_spin.setValue(7.0)
        app.processEvents()
        assert window.valuation_assumption_state_label.text().startswith("Manual override")
        assert window.valuation_current_scenarios["assumptions"]["growth_1_5"] == 7.0
        assert "Auto-derived" in window.valuation_assumption_state_label.toolTip()

        window._valuation_rederive_assumptions()
        assert window.valuation_growth_1_5_spin.value() == 14.2
        label = window.valuation_assumption_state_label.text()
        # The label carries compact tags; the unabridged sources belong in the tooltip.
        assert "required return 9.4% (CAPM on 4.21% 10Y)" in label, label
        assert "terminal 2.4% (10Y breakeven)" in label, label
        assert "exit 21.3x (median of 3 peers)" in label, label
        assert len(label) < 260, len(label)
        assert "Median P/FCF of 3 peers" in window.valuation_assumption_state_label.toolTip()
        assert window.valuation_use_suggestions_btn.text() == "Re-derive assumptions"
        assert not hasattr(window, "_valuation_apply_auto_fill_estimates")

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
        assert window.valuation_current_scenarios["assumptions"]["basis_type"] == "EPS"

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
        window._valuation_apply_derived_assumptions(_payload("MSFT", basis=4.0))
        assert window.valuation_assumption_ticker == "MSFT"
        assert window.valuation_basis_value_spin.value() == 4.0
        assert window.valuation_page_state["assumptions_by_ticker"]["NVDA"]["basis_value"] == 12.0

        window.valuation_growth_1_5_spin.setValue(7.5)
        app.processEvents()
        snapshot = window._valuation_session_snapshot()
        assert snapshot["assumptions"]["terminal_method"] == "gordon_growth"
        assert snapshot["assumptions"]["growth_1_5"] == 7.5
        window.valuation_growth_1_5_spin.setValue(30.0)
        assert window._valuation_restore_session_snapshot(snapshot) is True
        app.processEvents()
        assert window.valuation_growth_1_5_spin.value() == 7.5

        _assert_currency_mismatch_is_blocking(window, app)
    finally:
        valuation_mixin.save_valuation_page_settings = original_save
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_valuation_page_smoke()
    print("valuation page smoke passed")
    sys.stdout.flush()
    _TEST_DATA_DIR.cleanup()
    os._exit(0)
