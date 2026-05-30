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
from budget_terminal_app.persistence import _normalize_backtest_page_settings
from budget_terminal_app.services.backtest import calculate_buy_hold_backtest


def _frame(values):
    index = pd.date_range("2020-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Adj Close": values,
            "Volume": [1000] * len(values),
        },
        index=index,
    )


class _InlineExecutor:
    def submit(self, fn: Any) -> None:
        fn()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeBacktestService:
    def run_backtest(self, rows: Any, *, compare_symbol: Any, interval: Any, range_key: Any) -> dict[str, Any]:
        return calculate_buy_hold_backtest(
            {
                "AAA": _frame([100, 110, 120]),
                "BBB": _frame([100, 100, 100]),
            },
            rows,
            compare_frame=_frame([100, 105, 115]),
            compare_symbol=compare_symbol,
            range_key=range_key,
        )


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
        window.backtest_page_state = _normalize_backtest_page_settings(
            {
                "rows": [{"symbol": "AAA", "weight": 50}, {"symbol": "BBB", "weight": 50}],
                "compare_symbol": "SPY",
            }
        )
        window._ensure_page_initialized(24)
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_backtest_page_smoke() -> None:
    app, window = _build_window()
    try:
        assert window._PAGE_LABELS[24] == "Backtest"
        assert window.btn_page25.text() == "Backtest"
        assert window.p25_table.rowCount() == 2
        assert window.p25_compare_input.text() == "SPY"
        window._backtest_data_service = _FakeBacktestService()
        window._p25_executor = _InlineExecutor()
        window._p25_run_backtest()
        app.processEvents()
        assert "Backtest loaded" in window.p25_status_label.text()
        assert "Return +10.00%" == window.p25_return_label.text()
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_backtest_page_smoke()
    print("backtest page smoke passed")
    sys.stdout.flush()
    os._exit(0)
