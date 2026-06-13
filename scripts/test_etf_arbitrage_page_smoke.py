from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.etf_analyser import EtfAnalyserMixin
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    original_fetch_aum = EtfAnalyserMixin._p13_fetch_aum_universe
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    EtfAnalyserMixin._p13_fetch_aum_universe = lambda self, *args, **kwargs: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window._ensure_page_initialized(12)
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
        EtfAnalyserMixin._p13_fetch_aum_universe = original_fetch_aum
    return app, window


def test_etf_arbitrage_page_smoke() -> None:
    app, window = _build_window()
    try:
        assert window._PAGE_LABELS[12] == "ETF"
        assert window.p13_tabs.count() == 2
        assert window.p13_tabs.tabText(0) == "Holdings"
        assert window.p13_tabs.tabText(1) == "Arbitrage"
        assert window.p13_tabs.currentIndex() == 0
        window.p13_tabs.setCurrentIndex(1)
        app.processEvents()
        assert window.p13_tabs.tabText(window.p13_tabs.currentIndex()) == "Arbitrage"
        assert window.p13_arbitrage_table.columnCount() == 6
        assert window.p13_arbitrage_table.horizontalHeaderItem(5).text() == "Contribution"
        window._p13_arbitrage_payload = {
            "ticker": "SPY",
            "etf_price": 500.0,
            "etf_move_pct": 1.0,
            "basket_move_pct": 0.75,
            "gap_bps": 25.0,
            "signal": "ETF rich vs basket",
            "quote_coverage": 1,
            "total_holdings": 1,
            "rows": [
                {
                    "symbol": "AAA",
                    "name": "AAA Corp",
                    "weight": 0.25,
                    "price": 100.0,
                    "move_pct": 0.75,
                    "contribution_pct": 0.75,
                }
            ],
        }
        window._p13_render_arbitrage_payload()
        app.processEvents()
        assert window.p13_arbitrage_metric_labels["gap_bps"].text() == "+25.0 bps"
        assert window.p13_arbitrage_table.rowCount() == 1
        assert window.p13_arbitrage_table.item(0, 5).text() == "+0.75%"
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_etf_arbitrage_page_smoke()
    print("ETF arbitrage page smoke passed")
    sys.stdout.flush()
    os._exit(0)
