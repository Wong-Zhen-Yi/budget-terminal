from __future__ import annotations

import os
import sys
import time
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
    P4_PORTFOLIO_COL_WEIGHT,
    P4_PORTFOLIO_COLUMNS,
)
from budget_terminal_app.dependencies import QApplication, QLabel, QObject, QPushButton, QTableWidget, Qt
from budget_terminal_app.mixins.portfolio_metrics import PortfolioMetricsMixin
from budget_terminal_app.mixins.portfolio_setup import PortfolioSetupMixin
from budget_terminal_app.widgets.pie_chart import PieChartWidget

_QT_APP = None


class _ImmediateSignal:
    def emit(self, callback) -> None:
        callback()


class _PortfolioDataClient:
    def __init__(self, probe) -> None:
        self.probe = probe
        self.quote_generation = 0

    def fetch_portfolio_quotes(self, tickers):
        self.probe.refresh_count += 1
        self.quote_generation += 1
        self.probe.last_quote_tickers = list(tickers)
        return {
            "portfolio": {
                ticker: {"price": float(self.quote_generation * 10 + index + 1), "change": 1.0}
                for index, ticker in enumerate(tickers)
            }
        }

    def fetch_market_caps(self, tickers):
        self.probe.market_cap_fetch_count += 1
        self.probe.last_market_cap_tickers = list(tickers)
        return {ticker: float(index + 1) * 1_000_000_000 for index, ticker in enumerate(tickers)}

    def fetch_month_returns(self, tickers, **_kwargs):
        self.probe.returns_fetch_count += 1
        return {ticker: float(index + 1) for index, ticker in enumerate(tickers)}

    def fetch_portfolio_momentum(self, *_args, **_kwargs):
        self.probe.momentum_fetch_count += 1
        return {"dates": [], "returns": []}

    def fetch_portfolio_analytics(self, *_args, **_kwargs):
        self.probe.metrics_refresh_count += 1
        return {"metrics": {}, "exposure": {}}


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
        self.cash_balance = 0.0
        self.portfolio_entry = {"include_cash_in_weight": True}
        self.p4_weight_chart = object()
        self._invoke_main = _ImmediateSignal()
        self._data_service_client = _PortfolioDataClient(self)

        self.p4_table = QTableWidget(0, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        self.p4_table.horizontalHeader().setSortIndicator(
            P4_PORTFOLIO_COL_MARKET_VALUE,
            Qt.SortOrder.DescendingOrder,
        )
        self.p4_table.setSortingEnabled(True)
        self.p4_table.currentCellChanged.connect(self._p4_on_stock_current_cell_changed)
        self.p4_total_label = QLabel()
        self.p4_stock_pl_label = QLabel()
        self.p4_stock_positions_label = QLabel()
        self.p4_refresh_holdings_btn = QPushButton("Refresh Holdings")
        self.p4_refresh_holdings_btn.clicked.connect(self._p4_refresh_holdings)
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
        return self.cash_balance

    def _get_portfolio_entry(self, portfolio_id=None):
        return self.portfolio_entry

    def _persist_all_portfolios(self, *, immediate: bool = False) -> None:
        self.persist_count += 1
        self.persist_immediate = immediate

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
        needed = self._p4_get_mktcap_refresh_candidates(tickers)
        if needed:
            self.market_cap_fetch_count += 1
            self.last_market_cap_tickers = list(needed)

    def _update_returns_chart(self, timeframe_key, results) -> None:
        self.last_return_payload = (timeframe_key, dict(results or {}))

    def _p4_metrics_tab_visible(self) -> bool:
        return False

    def _p4_schedule_portfolio_metrics_refresh(self) -> None:
        self.metrics_refresh_count += 1

    def _p4_submit_background_task(self, fn) -> None:
        fn()


class _DeferredPortfolioProbe(_PortfolioProbe):
    def __init__(self) -> None:
        self.visible = True
        self.render_count = 0
        self.pending_tasks = []
        super().__init__()
        self.render_count = 0

    def _p4_page_visible(self) -> bool:
        return self.visible

    def update_page4(self, *args, **kwargs) -> None:
        self.render_count += 1
        super().update_page4(*args, **kwargs)

    def _p4_submit_background_task(self, fn) -> None:
        self.pending_tasks.append(fn)


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
    _assert(probe.tracker_data["ZZZ"] == {"shares": 0, "avg_price": 0, "include_in_weight": True}, "new position should start empty and included")
    _assert(_symbols(probe)[-1] == "ZZZ", "new ticker should render immediately at the inserted row")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_SHARES, "focus should move to Shares")
    _assert(probe.p4_table.item(probe.p4_table.currentRow(), P4_PORTFOLIO_COL_SYMBOL).text() == "ZZZ", "focus should stay on new ticker")
    _assert_no_refresh_work(probe, "new incomplete ticker")


def test_incomplete_position_entry_does_not_fetch_or_move() -> None:
    app = _qt_app()
    probe = _PortfolioProbe()
    _add_zzz_position(probe)
    original_row = _row_for(probe, "ZZZ")

    shares_item = probe.p4_table.item(original_row, P4_PORTFOLIO_COL_SHARES)
    shares_item.setText("5")
    probe._on_tracker_cell_changed(shares_item)
    probe._p4_active_position_entry_guard["column"] = P4_PORTFOLIO_COL_AVG_PRICE
    _assert(probe.tracker_data["ZZZ"] == {"shares": 5.0, "avg_price": 0, "include_in_weight": True}, "shares-only entry should remain incomplete")
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

    probe.p4_table.setCurrentCell(_row_for(probe, "AAA"), P4_PORTFOLIO_COL_SHARES)
    app.processEvents()
    _assert_no_refresh_work(probe, "focus change after shares-only entry")


def test_complete_position_entry_waits_for_manual_refresh() -> None:
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
    _assert(probe.tracker_data["ZZZ"] == {"shares": 5.0, "avg_price": 25.0, "include_in_weight": True}, "shares and average price should complete the entry")
    _assert_no_refresh_work(probe, "completed ticker before manual refresh")

    probe.update_page4(probe.last_data)
    app.processEvents()
    _assert(_row_for(probe, "ZZZ") == original_row, "completed active entry should stay stable before manual refresh")
    _assert(probe.p4_table.currentColumn() == P4_PORTFOLIO_COL_AVG_PRICE, "completed edit column should stay focused before manual refresh")
    _assert_no_refresh_work(probe, "completed ticker before manual refresh")

    probe.p4_table.setCurrentCell(_row_for(probe, "AAA"), P4_PORTFOLIO_COL_SHARES)
    app.processEvents()
    _assert_no_refresh_work(probe, "focus change after completed entry")
    _assert(probe.p4_table.isSortingEnabled(), "normal sorting should resume after entry focus leaves the row")

    probe.p4_refresh_holdings_btn.click()
    _assert(probe.dashboard_membership_count == 0, "manual refresh should not redraw Dashboard")
    _assert(probe.refresh_count == 1, "manual refresh should refresh quotes once")
    _assert(probe.market_cap_fetch_count == 1, "manual refresh should refresh market caps once")
    _assert(probe.last_market_cap_tickers == ["AAA", "BBB", "ZZZ"], "manual refresh should cover every active holding")
    _assert(probe.returns_fetch_count == 1, "manual refresh should fetch returns once")
    _assert(probe.momentum_fetch_count == 0, "hidden Momentum should stay deferred")
    _assert(probe.metrics_refresh_count == 0, "hidden Metrics should stay deferred")
    _assert(probe.p4_refresh_holdings_btn.isEnabled(), "manual refresh should always restore its button")
    _assert(probe.p4_refresh_holdings_btn.text() == "Refresh Holdings", "manual refresh should restore its label")


def test_weight_checkbox_filters_only_requested_views() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 10.0
    probe.tracker_data["AAA"]["avg_price"] = 7.0
    probe.tracker_data["BBB"]["avg_price"] = 15.0
    probe.update_page4(probe.last_data)
    _assert(probe.p4_total_label.text() == "Total:  $40.00  USD", "initial total should include all checked stocks plus cash")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$8.00", "initial stock P&L should include all checked stocks")
    probe.weight_chart_count = 0
    probe.heatmap_refresh_count = 0
    probe.returns_fetch_count = 0
    probe.momentum_fetch_count = 0
    probe.metrics_refresh_count = 0
    probe.refresh_count = 0
    probe.dashboard_membership_count = 0
    probe.market_cap_fetch_count = 0

    bbb_row = _row_for(probe, "BBB")
    bbb_symbol = probe.p4_table.item(bbb_row, P4_PORTFOLIO_COL_SYMBOL)
    _assert(bbb_symbol.checkState() == Qt.CheckState.Checked, "existing positions should default to checked")
    _assert("Pie Chart" in bbb_symbol.toolTip(), "checkbox tooltip should identify the Pie Chart as a filtered view")
    bbb_symbol.setCheckState(Qt.CheckState.Unchecked)
    probe._p4_on_weight_inclusion_changed(bbb_symbol)

    _assert(probe.tracker_data["BBB"]["include_in_weight"] is False, "unchecked state should persist in tracker data")
    _assert(probe.persist_immediate is True, "checkbox changes should persist immediately")
    _assert(probe._p4_weight_included_tickers() == ["AAA"], "Dip Finder and Heatmap ticker selection should exclude BBB")
    _assert(abs(probe.last_weights["AAA"] - 50.0) < 0.001, "AAA should rebase against included stocks plus cash")
    _assert(abs(probe.last_weights["CASH"] - 50.0) < 0.001, "cash should remain in the filtered denominator")
    _assert("BBB" not in probe.last_weights, "unchecked BBB should not appear in the weight chart payload")
    _assert(
        probe.p4_table.item(_row_for(probe, "BBB"), P4_PORTFOLIO_COL_WEIGHT).text() == "--",
        "unchecked positions should show no table weight",
    )
    _assert(probe.p4_total_label.text() == "Total:  $20.00  USD", "top total should include checked stocks plus cash")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$3.00", "stock P&L should include only checked stocks")
    _assert(probe.weight_chart_count == 1, "weight chart should refresh once")
    _assert(probe.heatmap_refresh_count == 1, "heatmap should refresh once")
    _assert(probe.returns_fetch_count == 0, "Dip Finder should wait for explicit holdings refresh")
    _assert(probe.momentum_fetch_count == 0, "momentum should not refresh")
    _assert(probe.metrics_refresh_count == 0, "portfolio analytics should not refresh")
    _assert(probe.refresh_count == 0, "quotes should not refresh")
    _assert(probe.dashboard_membership_count == 0, "dashboard membership should not change")
    _assert(probe.market_cap_fetch_count == 0, "market caps should not refresh")

    heatmap_rows = probe._p4_portfolio_heatmap_rows(probe.last_data["portfolio"], "live", {})
    _assert([row["symbol"] for row in heatmap_rows] == ["AAA"], "heatmap rows should exclude BBB")
    _assert(abs(heatmap_rows[0]["weight"] - 0.5) < 0.001, "heatmap weight should include cash in its denominator")
    cache_key = probe._p4_returns_cache_key("dip_finder")
    _assert(cache_key[2] == ("AAA",), "Dip Finder cache key should include the enabled ticker signature")


def test_cash_checkbox_persists_and_rebases_filtered_views() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 10.0
    probe.update_page4(probe.last_data)
    probe.weight_chart_count = 0
    probe.heatmap_refresh_count = 0
    probe.returns_fetch_count = 0
    probe.momentum_fetch_count = 0
    probe.metrics_refresh_count = 0

    probe._p4_on_cash_weight_inclusion_changed(False)

    _assert(probe.portfolio_entry["include_cash_in_weight"] is False, "unchecked Cash should persist per portfolio")
    _assert(probe.persist_immediate is True, "Cash checkbox changes should persist immediately")
    _assert("CASH" not in probe.last_weights, "unchecked Cash should not appear in Portfolio Weight")
    _assert(abs(probe.last_weights["AAA"] - (100.0 / 3.0)) < 0.001, "AAA should rebase without Cash")
    _assert(abs(probe.last_weights["BBB"] - (200.0 / 3.0)) < 0.001, "BBB should rebase without Cash")
    _assert(probe.p4_total_label.text() == "Total:  $30.00  USD", "checked total should exclude unchecked Cash")
    _assert(probe.weight_chart_count == 1, "Cash toggle should refresh Portfolio Weight once")
    _assert(probe.heatmap_refresh_count == 1, "Cash toggle should refresh the linked Heatmap once")
    _assert(probe.returns_fetch_count == 0, "Cash toggle should not fetch returns")
    _assert(probe.momentum_fetch_count == 0, "Cash toggle should not refresh Momentum")
    _assert(probe.metrics_refresh_count == 0, "Cash toggle should not refresh Portfolio Metrics")

    probe._p4_on_cash_weight_inclusion_changed(True)
    _assert(probe.portfolio_entry["include_cash_in_weight"] is True, "checked Cash should persist per portfolio")
    _assert(abs(probe.last_weights["CASH"] - 25.0) < 0.001, "checked Cash should return to Portfolio Weight")
    _assert(probe.p4_total_label.text() == "Total:  $40.00  USD", "checked total should include checked Cash")


def test_holdings_refresh_is_single_flight_and_preserves_dashboard_payload() -> None:
    _qt_app()
    probe = _DeferredPortfolioProbe()
    probe.last_data.update({
        "charts": {"SPY": "chart"},
        "chart_options": {"SPY": ["option"]},
        "news": [{"title": "kept"}],
        "targets": [{"ticker": "AAA", "target": 50.0}],
    })

    probe._p4_refresh_holdings()
    probe._p4_refresh_holdings()
    _assert(len(probe.pending_tasks) == 1, "same-signature refreshes should share one active task")
    _assert(not probe.p4_refresh_holdings_btn.isEnabled(), "only the holdings refresh button should be busy")

    probe.tracker_data["AAA"]["shares"] = 2.0
    probe._p4_refresh_holdings()
    _assert(len(probe.pending_tasks) == 1, "changed inputs should queue, not start, one replacement task")

    probe.pending_tasks.pop(0)()
    _assert(len(probe.pending_tasks) == 1, "the latest changed-input request should run after the active task")
    _assert(probe.last_data["portfolio"]["AAA"]["price"] == 10.0, "superseded quotes must not overwrite current data")

    probe.pending_tasks.pop(0)()
    _assert(probe.last_data["portfolio"]["AAA"]["price"] == 21.0, "the latest generation should update quotes")
    _assert(probe.last_data["charts"] == {"SPY": "chart"}, "quote merge should preserve Dashboard charts")
    _assert(probe.last_data["chart_options"] == {"SPY": ["option"]}, "quote merge should preserve options")
    _assert(probe.last_data["news"] == [{"title": "kept"}], "quote merge should preserve news")
    _assert(probe.last_data["targets"] == [{"ticker": "AAA", "target": 50.0}], "quote merge should preserve targets")
    _assert(probe.p4_refresh_holdings_btn.isEnabled(), "the refresh action should recover after the queued run")


def test_hidden_holdings_completion_defers_one_render() -> None:
    _qt_app()
    probe = _DeferredPortfolioProbe()
    probe._p4_refresh_holdings()
    probe.visible = False
    probe.pending_tasks.pop(0)()

    _assert(probe.render_count == 0, "a hidden Portfolio page must not render worker results")
    _assert(probe.last_data["portfolio"]["AAA"]["price"] == 11.0, "hidden completion should still cache current quotes")
    probe.visible = True
    probe._p4_render_deferred_subtab()
    _assert(probe.render_count == 1, "returning to Portfolio should render cached data exactly once")
    probe._p4_render_deferred_subtab()
    _assert(probe.render_count == 1, "a clean sub-tab should not render again")


def test_portfolio_switch_queues_new_context_and_rejects_old_result() -> None:
    _qt_app()
    probe = _DeferredPortfolioProbe()
    probe._p4_refresh_holdings()

    probe.active_portfolio_id = "secondary"
    probe.tickers = ["CCC"]
    probe.tracker_data = {"CCC": {"shares": 3.0, "avg_price": 7.0}}
    probe.last_data["portfolio"]["CCC"] = {"price": 7.0, "change": 0.0}
    probe._p4_refresh_holdings()

    probe.pending_tasks.pop(0)()
    _assert(probe.last_data["portfolio"]["AAA"]["price"] == 10.0, "old portfolio quotes must be rejected")
    _assert(len(probe.pending_tasks) == 1, "portfolio switch should retain one newest rerun")

    probe.pending_tasks.pop(0)()
    _assert(probe.last_data["portfolio"]["CCC"]["price"] == 21.0, "new portfolio quotes should apply")


def test_shutdown_rejects_late_holdings_completion() -> None:
    _qt_app()
    probe = _DeferredPortfolioProbe()
    previous = dict(probe.last_data["portfolio"]["AAA"])
    probe._p4_refresh_holdings()
    probe._refresh_shutdown = True
    probe._refresh_coordinator.clear()

    probe.pending_tasks.pop(0)()

    _assert(probe.render_count == 0, "shutdown must not render a late holdings result")
    _assert(probe.last_data["portfolio"]["AAA"] == previous, "shutdown must not merge a late quote payload")


def test_momentum_cache_key_tracks_share_changes() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    first_key = probe._p4_momentum_cache_key("1mo")
    probe.tracker_data["AAA"]["shares"] = 3.0
    second_key = probe._p4_momentum_cache_key("1mo")
    _assert(first_key != second_key, "momentum cache keys must change when share counts change")


def test_failed_and_empty_holdings_refreshes_recover_cleanly() -> None:
    _qt_app()
    failed = _DeferredPortfolioProbe()
    previous = dict(failed.last_data["portfolio"]["AAA"])
    failed._data_service_client.fetch_portfolio_quotes = lambda _tickers: {
        "portfolio": {},
        "_market_data_meta": {"freshness": "failed", "failure_reason": "offline"},
    }
    failed._p4_refresh_holdings()
    failed.pending_tasks.pop(0)()
    _assert(failed.last_data["portfolio"]["AAA"] == previous, "failed quotes should preserve previous values")
    _assert(failed.p4_refresh_holdings_btn.isEnabled(), "failed refresh should restore its button")

    empty = _DeferredPortfolioProbe()
    empty.tickers = []
    empty.tracker_data = {}
    empty._p4_refresh_holdings()
    empty.pending_tasks.pop(0)()
    _assert(empty.p4_refresh_holdings_btn.isEnabled(), "empty portfolio refresh should restore its button")

    rejected = _DeferredPortfolioProbe()

    def reject_submission(_work) -> None:
        raise RuntimeError("executor unavailable")

    rejected._p4_submit_background_task = reject_submission
    rejected._p4_refresh_holdings()
    _assert(rejected.p4_refresh_holdings_btn.isEnabled(), "worker submission failure should restore its button")
    _assert(
        rejected._refresh_coordinator.active_token("portfolio.holdings") is None,
        "worker submission failure should clear coordinator state",
    )


def test_large_positions_table_finishes_batched_render() -> None:
    app = _qt_app()
    probe = _PortfolioProbe()
    probe.tickers = [f"T{index:03d}" for index in range(120)]
    probe.tracker_data = {
        ticker: {"shares": 1.0, "avg_price": 10.0, "include_in_weight": True}
        for ticker in probe.tickers
    }
    probe.last_data = {
        "portfolio": {
            ticker: {"price": float(index + 10), "change": 0.0}
            for index, ticker in enumerate(probe.tickers)
        }
    }
    probe.update_page4(probe.last_data)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        handle = getattr(probe, "_budget_terminal_batched_render_handles", {}).get("portfolio.positions.rows")
        if handle is None:
            break
    _assert(probe.p4_table.rowCount() == 120, "batched Portfolio render should create every row")
    _assert(set(_symbols(probe)) == set(probe.tickers), "batched Portfolio render should preserve every holding")


def test_pie_chart_data_excludes_unticked_positions_and_keeps_cash() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 10.0
    probe.tracker_data["BBB"]["include_in_weight"] = False
    metrics_map, total_value = probe._p4_build_tracker_metrics_map(probe.last_data["portfolio"])
    slices, filtered_total = probe._p4_pie_chart_data(metrics_map)

    _assert(total_value == 40.0, "full portfolio total should retain the unticked stock")
    _assert(filtered_total == 20.0, "Pie Chart total should exclude the unticked stock")
    _assert(slices == {"AAA": 50.0, "CASH": 50.0}, "Pie Chart should contain checked stocks plus cash")

    probe.p4_pie_chart = PieChartWidget()
    probe.p4_pie_empty_label = QLabel()
    probe.p4_pie_total_label = QLabel()
    probe._p4_refresh_pie_chart(metrics_map)
    _assert(not probe.p4_pie_chart.isHidden(), "Pie Chart should be shown when included value exists")
    _assert(probe.p4_pie_empty_label.isHidden(), "Pie Chart empty state should be hidden when slices exist")
    _assert(probe.p4_pie_total_label.text() == "Filtered Total:  $20.00  USD", "Pie Chart should display its filtered total")


def test_all_positions_unchecked_leaves_cash_at_full_weight() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 25.0
    probe.tracker_data["AAA"]["include_in_weight"] = False
    probe.tracker_data["BBB"]["include_in_weight"] = False
    metrics_map, total_value = probe._p4_build_tracker_metrics_map(probe.last_data["portfolio"])
    weights, filtered_total = probe._p4_filtered_weight_map(metrics_map)

    _assert(total_value == 55.0, "full total should retain all stock positions")
    _assert(filtered_total == 25.0, "filtered total should contain only cash")
    _assert(weights == {"CASH": 100.0}, "cash should become 100% when every stock is unchecked")
    probe._p4_update_filtered_summary_labels(metrics_map)
    _assert(probe.p4_total_label.text() == "Total:  $25.00  USD", "top total should equal cash when every stock is unchecked")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$0.00", "stock P&L should be zero when every stock is unchecked")
    _assert(probe._p4_weight_included_tickers() == [], "no stock should remain in Dip Finder or Heatmap")
    slices, pie_total = probe._p4_pie_chart_data(metrics_map)
    _assert(slices == {"CASH": 100.0}, "Pie Chart should show cash at 100% when all stocks are unchecked")
    _assert(pie_total == 25.0, "Pie Chart total should equal cash when all stocks are unchecked")

    probe.cash_balance = 0.0
    slices, pie_total = probe._p4_pie_chart_data(metrics_map)
    _assert(slices == {}, "Pie Chart should enter its empty state without checked stocks or cash")
    _assert(pie_total == 0.0, "empty Pie Chart total should be zero")
    probe.p4_pie_chart = PieChartWidget()
    probe.p4_pie_empty_label = QLabel()
    probe.p4_pie_total_label = QLabel()
    probe._p4_refresh_pie_chart(metrics_map)
    _assert(probe.p4_pie_chart.isHidden(), "empty Pie Chart should hide the blank chart widget")
    _assert(not probe.p4_pie_empty_label.isHidden(), "empty Pie Chart should show its empty-state label")
    _assert(probe.p4_pie_total_label.text() == "Filtered Total:  $0.00  USD", "empty Pie Chart should show a zero filtered total")


def test_cash_only_refresh_keeps_stock_pnl() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 10.0
    probe.tracker_data["BBB"]["include_in_weight"] = False
    probe.tracker_data["AAA"]["avg_price"] = 8.0
    probe._p4_update_cash_dependent_views()

    _assert(probe.p4_total_label.text() == "Total:  $20.00  USD", "cash refresh should include checked stocks plus cash")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$2.00", "cash refresh should not change checked stock P&L")

    probe.cash_balance = 25.0
    probe._p4_update_cash_dependent_views()
    _assert(probe.p4_total_label.text() == "Total:  $35.00  USD", "cash-only changes should update the filtered total")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$2.00", "cash-only changes should preserve checked stock P&L")


def test_row_recalc_updates_filtered_summary() -> None:
    _qt_app()
    probe = _PortfolioProbe()
    probe.cash_balance = 10.0
    probe.tracker_data["AAA"]["shares"] = 2.0
    probe.tracker_data["AAA"]["avg_price"] = 8.0
    row = _row_for(probe, "AAA")

    probe._recalc_tracker_row(row, "AAA", probe.last_data["portfolio"])

    _assert(probe.p4_total_label.text() == "Total:  $50.00  USD", "row recalc should update checked-stock total plus cash")
    _assert(probe.p4_stock_pl_label.text() == "Stock P&L:  +$4.00", "row recalc should update checked stock P&L")


def main() -> None:
    test_add_position_is_immediate_and_local_until_complete()
    test_incomplete_position_entry_does_not_fetch_or_move()
    test_complete_position_entry_waits_for_manual_refresh()
    test_weight_checkbox_filters_only_requested_views()
    test_cash_checkbox_persists_and_rebases_filtered_views()
    test_holdings_refresh_is_single_flight_and_preserves_dashboard_payload()
    test_hidden_holdings_completion_defers_one_render()
    test_portfolio_switch_queues_new_context_and_rejects_old_result()
    test_shutdown_rejects_late_holdings_completion()
    test_momentum_cache_key_tracks_share_changes()
    test_failed_and_empty_holdings_refreshes_recover_cleanly()
    test_large_positions_table_finishes_batched_render()
    test_pie_chart_data_excludes_unticked_positions_and_keeps_cash()
    test_all_positions_unchecked_leaves_cash_at_full_weight()
    test_cash_only_refresh_keeps_stock_pnl()
    test_row_recalc_updates_filtered_summary()
    print("portfolio position row stability smoke tests passed")


if __name__ == "__main__":
    main()
