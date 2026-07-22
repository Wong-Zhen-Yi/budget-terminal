from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.persistence import _normalize_valuation_page_settings


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins import valuation as valuation_mixin
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    original_save_valuation_page_settings = valuation_mixin.save_valuation_page_settings
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    valuation_mixin.save_valuation_page_settings = _normalize_valuation_page_settings
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window._ensure_page_initialized(22)
        window.valuation_page_state = _normalize_valuation_page_settings(
            {
                "last_ticker": "NVDA",
                "custom_peers_by_ticker": {"NVDA": ["AMD"]},
            }
        )
        window.valuation_ticker_input.setText("NVDA")
        window._valuation_sync_custom_peer_list("NVDA")
        app.processEvents()
    except Exception:
        valuation_mixin.save_valuation_page_settings = original_save_valuation_page_settings
        raise
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window, valuation_mixin, original_save_valuation_page_settings


def test_valuation_peers_page_smoke() -> None:
    app, window, valuation_mixin, original_save_valuation_page_settings = _build_window()
    try:
        tab_labels = [window.valuation_detail_tabs.tabText(index) for index in range(window.valuation_detail_tabs.count())]
        assert "Peers" in tab_labels
        assert window.valuation_peer_table.columnCount() == 9
        assert window.valuation_peer_table.horizontalHeaderItem(1).text() == "Source"
        assert window.valuation_peer_list.count() == 1
        assert window.valuation_peer_list.item(0).text() == "AMD"

        window.load_valuation_data = lambda *args, **kwargs: None
        window.valuation_peer_input.setText("MSFT")
        window._valuation_add_custom_peer()
        peers = window.valuation_page_state["custom_peers_by_ticker"]["NVDA"]
        assert peers == ["AMD", "MSFT"]
        assert window.valuation_peer_list.count() == 2

        window.valuation_peer_list.setCurrentRow(0)
        window._valuation_remove_custom_peer()
        peers = window.valuation_page_state["custom_peers_by_ticker"]["NVDA"]
        assert peers == ["MSFT"]
    finally:
        valuation_mixin.save_valuation_page_settings = original_save_valuation_page_settings
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_valuation_peers_page_smoke()
    print("valuation peers page smoke passed")
    sys.stdout.flush()
    os._exit(0)
