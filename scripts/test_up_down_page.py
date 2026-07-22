from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.persistence import (
    load_up_down_page_settings,
    save_up_down_page_settings,
)
from budget_terminal_app.services.up_down import (
    calculate_up_down_row,
    normalize_up_down_symbols,
    sort_up_down_rows,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_up_down_calculation_and_sorting() -> None:
    index = pd.date_range("2026-01-02", periods=6, freq="D")
    close = pd.Series([100, 101, 100, 100, 102, 101], index=index)

    one_day = calculate_up_down_row("AAA", close, "1d", name="Alpha")
    _assert(one_day is not None, "1D row should be calculated")
    _assert(one_day["days_up"] == 0, "latest down day should not count as up")
    _assert(one_day["days_down"] == 1, "latest down day should count as down")
    _assert(one_day["trading_days"] == 1, "1D should include one return observation")

    five_day = calculate_up_down_row("AAA", close, "5d", name="Alpha")
    _assert(five_day is not None, "5D row should be calculated")
    _assert(five_day["days_up"] == 2, "5D should count two up days")
    _assert(five_day["days_down"] == 2, "5D should count two down days")
    _assert(five_day["flat_days"] == 1, "flat days should be neither up nor down")
    _assert(five_day["trading_days"] == 5, "5D should include five return observations when available")

    ytd = calculate_up_down_row("AAA", close, "ytd", name="Alpha")
    one_year = calculate_up_down_row("AAA", close, "1y", name="Alpha")
    _assert(ytd is not None and ytd["trading_days"] == 5, "YTD should use current-year observations")
    _assert(one_year is not None and one_year["trading_days"] == 5, "1Y should use one-year observations")

    rows = sort_up_down_rows([
        {"ticker": "BBB", "days_up": 3, "days_down": 2},
        {"ticker": "AAA", "days_up": 3, "days_down": 1},
        {"ticker": "CCC", "days_up": 2, "days_down": 0},
    ])
    _assert([row["ticker"] for row in rows] == ["AAA", "BBB", "CCC"], "default sort should rank up days, then down days, then ticker")
    _assert(normalize_up_down_symbols("aaa, BBB\ncash aaa") == ["AAA", "BBB"], "custom symbols should normalize and de-dupe")


class _InlineExecutor:
    def submit(self, fn: Any) -> None:
        fn()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeUpDownService:
    def fetch(self, symbols: list[str], interval_key: Any, *, names: dict[str, str] | None = None) -> dict[str, Any]:
        rows = []
        for index, symbol in enumerate(symbols):
            rows.append({
                "ticker": symbol,
                "name": (names or {}).get(symbol, f"{symbol} Inc"),
                "last_close": 100.0 + index,
                "interval_return": 1.0 - index,
                "trading_days": 5,
                "days_up": 5 - index,
                "days_down": index,
            })
        return {"rows": sort_up_down_rows(rows), "missing": [], "as_of": "2026-06-26 09:00", "source": "test"}


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
        window.up_down_page_state = {"active_source": "custom", "interval_key": "5d", "custom_symbols": []}
        window._ensure_page_initialized(26)
        window._up_down_data_service = _FakeUpDownService()
        window._p27_executor = _InlineExecutor()
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_up_down_page_smoke() -> None:
    original_state = load_up_down_page_settings()
    app = None
    window = None
    try:
        app, window = _build_window()
        _assert(window._PAGE_LABELS[26] == "Up/Down", "page label should be registered")
        _assert(window.btn_page27.text() == "Up/Down", "nav button should be registered")
        _assert(window.p27_tabs.count() == 3, "Up/Down should have three source tabs")
        _assert([window.p27_tabs.tabText(i) for i in range(3)] == ["Portfolio", "SPY Holdings", "Custom"], "source tabs should match the plan")
        window._refresh_main_tab_picker_items()
        picker_labels = [entry["label"] for entry in getattr(window, "_tab_picker_entries", [])]
        _assert("Up/Down > Custom" in picker_labels, "Up/Down subtabs should be registered in the picker")
        custom_table = window._p27_tables["custom"]
        headers = [custom_table.horizontalHeaderItem(i).text() for i in range(custom_table.columnCount())]
        _assert(headers[-2:] == ["Days Up", "Days Down"], "Days Up and Days Down should be the rightmost columns")
        _assert(window.p27_interval_key == "5d", "saved interval should initialize")
        _assert(window._p27_interval_buttons["5d"].isChecked(), "saved interval button should be checked")

        window.p27_custom_input.setPlainText("aaa, bbb\ncash aaa")
        window._p27_apply_custom_symbols(save=True)
        app.processEvents()
        _assert(window.p27_custom_symbols == ["AAA", "BBB"], "custom symbols should normalize on save")
        saved = load_up_down_page_settings()
        _assert(saved["custom_symbols"] == ["AAA", "BBB"], "custom symbols should persist")
        _assert(custom_table.rowCount() == 2, "custom tab should render fake service rows")
        _assert(custom_table.item(0, 1).text() == "AAA", "highest days-up ticker should render first")
    finally:
        save_up_down_page_settings(original_state)
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()


if __name__ == "__main__":
    test_up_down_calculation_and_sorting()
    test_up_down_page_smoke()
    print("Up/Down page smoke passed.")
    sys.stdout.flush()
    os._exit(0)
