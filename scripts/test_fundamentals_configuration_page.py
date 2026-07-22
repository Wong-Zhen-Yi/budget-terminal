from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.persistence import _normalize_fundamentals_page_settings


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins import fundamentals_setup as fundamentals_mixin
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    original_save = fundamentals_mixin.save_fundamentals_page_settings
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    fundamentals_mixin.save_fundamentals_page_settings = _normalize_fundamentals_page_settings
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window.fundamentals_page_state = _normalize_fundamentals_page_settings(
            {
                "last_ticker": "NVDA",
                "selected_configuration": "default",
                "custom_selections_by_ticker": {},
            }
        )
        window._startup_session_restored_tabs.add("fundamentals")
        window._ensure_page_initialized(8)
        window._p2_save_session_snapshot = lambda **_: None
        window.resize(1440, 820)
        app.processEvents()
    except Exception:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        raise
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
    return app, window, fundamentals_mixin, original_save


def _statement_frame(rows: list[str], columns: list[str], start: float) -> object:
    values = {
        pd.Timestamp(column): [start + row_index * 10 + column_index for row_index in range(len(rows))]
        for column_index, column in enumerate(columns)
    }
    return pd.DataFrame(values, index=rows)


def _payload(ticker: str = "NVDA") -> dict[str, object]:
    annual_columns = ["2023-12-31", "2024-12-31"]
    quarterly_columns = ["2024-09-30", "2024-12-31"]
    return {
        "ticker": ticker,
        "info": {
            "longName": f"{ticker} Test Company",
            "sector": "Technology",
            "industry": "Semiconductors",
            "exchange": "NMS",
            "currency": "USD",
        },
        "financials": _statement_frame(["Total Revenue", "Net Income"], annual_columns, 100.0),
        "quarterly_financials": _statement_frame(
            ["Total Revenue", "Operating Expense"], quarterly_columns, 25.0
        ),
        "cashflow": _statement_frame(["Operating Cash Flow", "Free Cash Flow"], annual_columns, 40.0),
        "quarterly_cashflow": _statement_frame(
            ["Operating Cash Flow", "Capital Expenditure"], quarterly_columns, 10.0
        ),
        "balance_sheet": _statement_frame(
            ["Cash And Cash Equivalents", "Total Debt"], annual_columns, 80.0
        ),
        "quarterly_balance_sheet": _statement_frame(["Total Assets"], quarterly_columns, 200.0),
        "earnings_dates": pd.DataFrame(),
        "av_used": False,
    }


def test_fundamentals_configuration_page() -> None:
    app, window, fundamentals_mixin, original_save = _build_window()
    try:
        assert not hasattr(window, "p2_configuration_combo")
        assert list(window.p2_configuration_buttons) == ["default", "custom"]
        assert window.p2_configuration_group.exclusive()
        assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["default"]
        assert window.p2_workspace_stack.currentWidget() is window.p2_default_workspace
        assert window.p2_custom_editor_frame.isHidden()

        default_frames = tuple(window.p2_chart_frames)
        default_titles = tuple(label.text() for label in window.p2_simple_titles)
        assert default_titles == (
            "Revenue",
            "Net Income",
            "Cash Flow",
            "Shares Outstanding",
            "Cash & Total Debt",
            "Operating Expenses",
        )

        window.update_page2(_payload(), update_collection_info=False)
        app.processEvents()
        assert sum(len(rows) for rows in window.p2_custom_available_rows.values()) == 9

        window.p2_configuration_buttons["custom"].click()
        app.processEvents()
        assert window.p2_selected_configuration == "custom"
        assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["custom"]
        assert window.p2_workspace_stack.currentWidget() is window.p2_custom_workspace
        assert not window.p2_custom_editor_frame.isHidden()
        assert window.fundamentals_page_state["selected_configuration"] == "custom"

        selection_before_search = window._p2_current_custom_selection("NVDA")
        window.p2_custom_filter_input.setText("revenue")
        app.processEvents()
        assert not window.p2_custom_checkboxes["financials"]["Total Revenue"].isHidden()
        assert window.p2_custom_checkboxes["financials"]["Net Income"].isHidden()
        assert window.p2_custom_group_boxes["cashflow"].isHidden()
        assert window._p2_current_custom_selection("NVDA") == selection_before_search

        window.p2_custom_checkboxes["financials"]["Total Revenue"].click()
        app.processEvents()
        assert window._p2_current_custom_selection("NVDA")["financials"] == ["Total Revenue"]
        assert window.p2_custom_selection_count.text() == "1 / 9 selected"
        assert window.p2_custom_clear_btn.isEnabled()
        screenshot_path = str(os.environ.get("BT_FUNDAMENTALS_SCREENSHOT", "") or "").strip()
        if not screenshot_path and "--screenshot" in sys.argv:
            screenshot_index = sys.argv.index("--screenshot")
            if screenshot_index + 1 < len(sys.argv):
                screenshot_path = sys.argv[screenshot_index + 1]
        if screenshot_path:
            window.stacked_widget.setCurrentIndex(8)
            window.show()
            app.processEvents()
            assert window.grab().save(screenshot_path)

        window.p2_custom_filter_input.clear()
        window.p2_custom_selected_only_cb.setChecked(True)
        app.processEvents()
        assert not window.p2_custom_checkboxes["financials"]["Total Revenue"].isHidden()
        assert window.p2_custom_checkboxes["financials"]["Net Income"].isHidden()

        window.p2_custom_clear_btn.click()
        app.processEvents()
        assert not any(window._p2_current_custom_selection("NVDA").values())
        assert window.p2_custom_panel_descriptors == []
        assert window.p2_custom_selection_count.text() == "0 / 9 selected"
        assert not window.p2_custom_clear_btn.isEnabled()
        assert window.p2_custom_no_matches_label.text() == "No selected metrics yet."
        assert not window.p2_custom_no_matches_label.isHidden()

        window.p2_custom_selected_only_cb.setChecked(False)
        window.p2_custom_checkboxes["financials"]["Net Income"].click()
        assert window._p2_current_custom_selection("NVDA")["financials"] == ["Net Income"]

        window.p2_ticker_input.setText("MSFT")
        window.update_page2(_payload("MSFT"), update_collection_info=False)
        app.processEvents()
        assert not any(window._p2_current_custom_selection("MSFT").values())
        window.p2_custom_checkboxes["balance_sheet"]["Total Debt"].click()
        assert window._p2_current_custom_selection("MSFT")["balance_sheet"] == ["Total Debt"]

        window.p2_ticker_input.setText("NVDA")
        window.update_page2(_payload("NVDA"), update_collection_info=False)
        app.processEvents()
        assert window.p2_custom_checkboxes["financials"]["Net Income"].isChecked()
        assert not window.p2_custom_checkboxes["balance_sheet"]["Total Debt"].isChecked()
        window.p2_custom_clear_btn.click()
        assert not any(window._p2_current_custom_selection("NVDA").values())
        assert window._p2_current_custom_selection("MSFT")["balance_sheet"] == ["Total Debt"]

        window.p2_ticker_input.setText("MSFT")
        window.update_page2(_payload("MSFT"), update_collection_info=False)
        app.processEvents()
        assert window.p2_custom_checkboxes["balance_sheet"]["Total Debt"].isChecked()

        window.p2_configuration_buttons["default"].click()
        app.processEvents()
        assert window.p2_workspace_stack.currentWidget() is window.p2_default_workspace
        assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["default"]
        assert tuple(window.p2_chart_frames) == default_frames
        assert tuple(label.text() for label in window.p2_simple_titles) == default_titles

        window.fundamentals_page_state = _normalize_fundamentals_page_settings(
            {
                "last_ticker": "NVDA",
                "selected_configuration": "custom",
                "custom_selections_by_ticker": window.p2_custom_selections_by_ticker,
            }
        )
        window._p2_apply_runtime_state()
        app.processEvents()
        assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["custom"]
        assert window.p2_workspace_stack.currentWidget() is window.p2_custom_workspace
        assert window.p2_ticker_input.text() == "MSFT"
        assert window.p2_custom_editor_hint.text().startswith("MSFT selections")

        wrong_typed_data = {
            "ticker": "NVDA",
            "info": {},
            "financials": [],
            "quarterly_financials": [],
            "cashflow": [],
            "quarterly_cashflow": [],
            "balance_sheet": [],
            "quarterly_balance_sheet": [],
        }
        for invalid_data in ({}, wrong_typed_data):
            invalid_snapshot = {
                "ticker": "NVDA",
                "configuration": "default",
                "data": invalid_data,
            }
            assert window._p2_restore_session_snapshot(invalid_snapshot) is False
            assert window.p2_ticker_input.text() == "MSFT"
            assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["custom"]
            assert window.p2_workspace_stack.currentWidget() is window.p2_custom_workspace

        snapshot = window._p2_session_snapshot()
        assert snapshot is not None
        snapshot["configuration"] = "default"
        assert window._p2_restore_session_snapshot(snapshot) is True
        app.processEvents()
        assert window.p2_configuration_group.checkedButton() is window.p2_configuration_buttons["default"]
        assert window.p2_workspace_stack.currentWidget() is window.p2_default_workspace
    finally:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_fundamentals_configuration_page()
    print("fundamentals configuration page smoke passed")
    sys.stdout.flush()
    os._exit(0)
