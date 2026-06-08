from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.constants import (
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_MARKET_VALUE,
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_SYMBOL,
    P4_PORTFOLIO_COLUMNS,
)
from budget_terminal_app.dependencies import QApplication, QLabel, QObject, QTableWidget, Qt
from budget_terminal_app.mixins.portfolio_metrics import PortfolioMetricsMixin
from budget_terminal_app.mixins.portfolio_setup import PortfolioSetupMixin

_QT_APP = None


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _qt_app():
    global _QT_APP
    app = QApplication.instance()
    if app is None:
        _QT_APP = QApplication([])
        app = _QT_APP
    else:
        _QT_APP = app
    return app


class _PortfolioProbe(QObject, PortfolioSetupMixin, PortfolioMetricsMixin):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.active_portfolio_id = "main"
        self.main_portfolio_id = "main"
        self.tickers = ["AAA", "BBB"]
        self.tracker_data = {
            "AAA": {"shares": 1.0, "avg_price": 10.0},
            "BBB": {"shares": 1.0, "avg_price": 20.0},
        }
        self.last_data = {
            "portfolio": {
                "AAA": {"price": 10.0, "change": 0.0},
                "BBB": {"price": 20.0, "change": 0.0},
            }
        }
        self._dashboard_showing_all = False
        self._mktcap_cache = {}
        self._mktcap_cache_ts = {}
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self._momentum_metrics_cache = {}
        self._momentum_metrics_fetching = {}
        self._portfolio_analytics_cache = {}
        self._portfolio_analytics_fetching = {}
        self._active_return_timeframe = "dip_finder"
        self._active_momentum_timeframe = "1mo"
        self.persist_count = 0
        self.refresh_count = 0
        self.dashboard_membership_count = 0
        self.returns_fetch_count = 0
        self.momentum_fetch_count = 0
        self.market_cap_fetch_count = 0
        self.metrics_refresh_count = 0
        self.weight_chart_count = 0
        self.heatmap_refresh_count = 0

        self.p4_table = QTableWidget(0, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        self.p4_table.horizontalHeader().setSortIndicator(
            P4_PORTFOLIO_COL_MARKET_VALUE,
            Qt.SortOrder.DescendingOrder,
        )
        self.p4_table.setSortingEnabled(True)
        self.p4_table.currentCellChanged.connect(self._p4_on_stock_current_cell_changed)
        self.p4_total_label = QLabel()
        self.p4_stock_positions_label = QLabel()
        self.update_page4(self.last_data)
        self.refresh_count = 0
        self.dashboard_membership_count = 0
        self.returns_fetch_count = 0
        self.momentum_fetch_count = 0
        self.market_cap_fetch_count = 0
        self.metrics_refresh_count = 0
        self.weight_chart_count = 0
        self.heatmap_refresh_count = 0

    def theme_color(self, token: str) -> str:
        return "#dddddd"

    def theme_series_color(self, index: int) -> str:
        return "#dddddd"

    def _p4_active_tickers(self):
        return self.tickers

    def _p4_active_tracker_data(self):
        return self.tracker_data

    def _p4_active_cash_balance(self, portfolio_id=None) -> float:
        return 0.0

    def _persist_all_portfolios(self) -> None:
        self.persist_count += 1

    def _update_weight_chart(self, weights) -> None:
        self.weight_chart_count += 1
        self.last_weights = weights

    def _p4_update_remove_stock_button_state(self) -> None:
        return None

    def _p4_apply_table_width_preferences(self, table_key: str) -> None:
        return None

    def _p4_refresh_portfolio_heatmap_view(self, *, reset_view: bool = False) -> None:
        self.heatmap_refresh_count += 1
        self.heatmap_reset = reset_view

    def _dashboard_apply_local_portfolio_membership(self, data=None):
        self.dashboard_membership_count += 1
        return {}

    def refresh_data(self, *, force: bool = False, reason: str = "full") -> None:
        self.refresh_count += 1
        self.last_refresh_reason = reason

    def _fetch_returns_for_timeframe(self, timeframe_key) -> None:
        self.returns_fetch_count += 1

    def _fetch_momentum_for_timeframe(self, timeframe_key) -> None:
        self.momentum_fetch_count += 1

    def _fetch_market_caps(self, tickers=None) -> None:
        self.market_cap_fetch_count += 1
        self.last_market_cap_tickers = list(tickers or [])

    def _p4_metrics_tab_visible(self) -> bool:
        return False

    def _p4_schedule_portfolio_metrics_refresh(self) -> None:
        self.metrics_refresh_count += 1


def _symbols(probe: _PortfolioProbe) -> list[str]:
    return [
        probe.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL).text()
        for row in range(probe.p4_table.rowCount())
    ]


def _row_for(probe: _PortfolioProbe, ticker: str) -> int:
    row = probe._p4_find_stock_row(ticker)
    _assert(row >= 0, f"{ticker} should be visible")
    return row


def _assert_no_refresh_work(probe: _PortfolioProbe, message_prefix: str) -> None:
    _assert(probe.refresh_count == 0, f"{message_prefix}: quote refresh should not run")
    _assert(probe.dashboard_membership_count == 0, f"{message_prefix}: dashboard membership should not refresh")
    _assert(probe.market_cap_fetch_count == 0, f"{message_prefix}: market-cap refresh should not run")
    _assert(probe.returns_fetch_count == 0, f"{message_prefix}: returns refresh should not run")
    _assert(probe.momentum_fetch_count == 0, f"{message_prefix}: momentum refresh should not run")
    _assert(probe.metrics_refresh_count == 0, f"{message_prefix}: analytics refresh should not run")
    _assert(probe.weight_chart_count == 0, f"{message_prefix}: weight chart should not redraw")
    _assert(probe.heatmap_refresh_count == 0, f"{message_prefix}: heatmap should not redraw")


def _add_zzz_position(probe: _PortfolioProbe) -> None:
    import budget_terminal_app.mixins.portfolio_setup as portfolio_setup

    app = _qt_app()
    original_get_text = portfolio_setup.QInputDialog.getText
    portfolio_setup.QInputDialog.getText = staticmethod(lambda *args, **kwargs: ("ZZZ", True))
    try:
        probe._on_add_stock_clicked()
        app.processEvents()
    finally:
        portfolio_setup.QInputDialog.getText = original_get_text


def test_add_position_is_immediate_and_local_until_complete() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    _add_zzz_position(probe)

    _assert("ZZZ" in probe.tickers, "new ticker should be added to active tickers immediately")
    _assert(probe.tracker_data["ZZZ"] == {"shares": 0, "avg_price": 0}, "new position should start empty")
    _assert(_symbols(probe)[-1] == "ZZZ", "new ticker should render immediately at the inserted row")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_SHARES, "focus should move to Shares")
    _assert(probe.p4_table.item(probe.p4_table.currentRow(), P4_PORTFOLIO_COL_SYMBOL).text() == "ZZZ", "focus should stay on new ticker")
    _assert_no_refresh_work(probe, "new incomplete ticker")

    probe._p4_flush_position_entry_refresh()
    _assert_no_refresh_work(probe, "manual flush for incomplete ticker")


def test_incomplete_position_entry_does_not_fetch_or_move() -> None:
    app = _qt_app()
    probe = _PortfolioProbe()
    _add_zzz_position(probe)
    original_row = _row_for(probe, "ZZZ")

    shares_item = probe.p4_table.item(original_row, P4_PORTFOLIO_COL_SHARES)
    shares_item.setText("5")
    probe._on_tracker_cell_changed(shares_item)
    probe._p4_active_position_entry_guard["column"] = P4_PORTFOLIO_COL_AVG_PRICE
    _assert(probe.tracker_data["ZZZ"] == {"shares": 5.0, "avg_price": 0}, "shares-only entry should remain incomplete")
    _assert_no_refresh_work(probe, "shares-only incomplete ticker")

    probe.last_data = {
        "portfolio": {
            "AAA": {"price": 10.0, "change": 0.0},
            "BBB": {"price": 20.0, "change": 0.0},
            "ZZZ": {"price": 999.0, "change": 4.0},
        }
    }
    probe.update_page4(probe.last_data)
    app.processEvents()

    _assert(_row_for(probe, "ZZZ") == original_row, "incomplete active entry row should not move when price data arrives")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_AVG_PRICE, "incomplete edit column should be restored")
    _assert(probe.p4_table.item(probe.p4_table.currentRow(), P4_PORTFOLIO_COL_SYMBOL).text() == "ZZZ", "current cell should stay on active ticker")
    _assert_no_refresh_work(probe, "quote render for incomplete ticker")

    probe._p4_flush_position_entry_refresh()
    _assert_no_refresh_work(probe, "manual flush after shares-only entry")


def test_complete_position_entry_fetches_once_and_sorting_resumes() -> None:
    app = _qt_app()
    probe = _PortfolioProbe()
    _add_zzz_position(probe)
    original_row = _row_for(probe, "ZZZ")

    shares_item = probe.p4_table.item(original_row, P4_PORTFOLIO_COL_SHARES)
    shares_item.setText("5")
    probe._on_tracker_cell_changed(shares_item)
    probe._p4_active_position_entry_guard["column"] = P4_PORTFOLIO_COL_AVG_PRICE

    probe.last_data = {
        "portfolio": {
            "AAA": {"price": 10.0, "change": 0.0},
            "BBB": {"price": 20.0, "change": 0.0},
            "ZZZ": {"price": 999.0, "change": 4.0},
        }
    }
    probe.update_page4(probe.last_data)
    app.processEvents()

    _assert(_row_for(probe, "ZZZ") == original_row, "active entry row should not move when price data arrives")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_AVG_PRICE, "active edit column should be restored")
    _assert(probe.p4_table.item(probe.p4_table.currentRow(), P4_PORTFOLIO_COL_SYMBOL).text() == "ZZZ", "current cell should stay on active ticker")
    _assert_no_refresh_work(probe, "shares-only active entry")

    avg_item = probe.p4_table.item(original_row, P4_PORTFOLIO_COL_AVG_PRICE)
    avg_item.setText("25")
    probe._on_tracker_cell_changed(avg_item)
    _assert(probe.tracker_data["ZZZ"] == {"shares": 5.0, "avg_price": 25.0}, "shares and average price should complete the entry")
    _assert_no_refresh_work(probe, "completed ticker before debounce flush")

    probe.update_page4(probe.last_data)
    app.processEvents()
    _assert(_row_for(probe, "ZZZ") == original_row, "completed active entry should stay stable while debounce is pending")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_AVG_PRICE, "completed edit column should stay focused while debounce is pending")
    _assert_no_refresh_work(probe, "completed ticker while debounce is pending")

    probe._p4_flush_position_entry_refresh()
    _assert(probe.dashboard_membership_count == 1, "completed entry should refresh dashboard membership once")
    _assert(probe.refresh_count == 1, "completed entry should refresh quotes once after debounce")
    _assert(probe.market_cap_fetch_count == 1, "completed entry should refresh market cap once after debounce")
    _assert(probe.returns_fetch_count == 1, "completed entry should fetch returns once after debounce")
    _assert(probe.momentum_fetch_count == 1, "completed entry should fetch momentum once after debounce")
    _assert(probe.metrics_refresh_count == 1, "completed entry should refresh analytics once after debounce")

    probe._p4_end_position_entry(schedule_refresh=False)
    probe.update_page4(probe.last_data)
    _assert(_symbols(probe)[0] == "ZZZ", "normal market-value sorting should resume after entry guard releases")


def main() -> None:
    test_add_position_is_immediate_and_local_until_complete()
    test_incomplete_position_entry_does_not_fetch_or_move()
    test_complete_position_entry_fetches_once_and_sorting_resumes()
    print("portfolio position row stability smoke tests passed")


if __name__ == "__main__":
    main()
