"""Focused smoke tests for responsive Options result application."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import QApplication, QComboBox, QLabel, QLineEdit, Qt, pd
from budget_terminal_app.mixins.options_chain import OptionsChainMixin
from budget_terminal_app.mixins.options_chain_presenters import build_option_summary_rows
from budget_terminal_app.widgets.table_render import render_table_rows


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _TabsProbe:
    def __init__(self, current_index: int = 0) -> None:
        self._current_index = int(current_index)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = int(index)


class _DeferredOptionsHarness(OptionsChainMixin):
    """Small result-handler probe with observable rendering and fetch counts."""

    def __init__(self) -> None:
        self.page5 = object()
        self.page_visible = False
        self.p5_tabs = _TabsProbe(0)
        self.p5_shared_ticker_input = QLineEdit()
        self.p5_shared_ticker_input.setText("SPY")
        self.p5_price_lbl = QLabel("")
        self.p5_status_lbl = QLabel("Waiting")
        self.p5_strategy_combo = QComboBox()
        self.p5_strategy_combo.addItems(list(self._P5_STRATEGIES))
        self.p5_expiry_combo = QComboBox()
        self.p5_strike_combo = QComboBox()
        self.p5_strike_status_lbl = QLabel("Waiting")
        self._p5_top_volume_tab_order = [self._P5_TOP_VOLUME_VIEW_KEY]
        self._p5_top_volume_type_filter = "both"
        self.p5_top_volume_views = {
            self._P5_TOP_VOLUME_VIEW_KEY: {
                "tab_label": self._P5_TOP_VOLUME_TAB_LABEL,
                "status_lbl": QLabel("Waiting"),
                "bucket_config": (),
                "sections": {},
            }
        }
        self._p5_top_volume_payloads = {
            self._P5_TOP_VOLUME_VIEW_KEY: self._p5_empty_top_volume_payload(())
        }
        self._p5_top_volume_latest_request_ids = {self._P5_TOP_VOLUME_VIEW_KEY: 1}
        self._p5_expiry_latest_request_id = 1
        self._p5_strike_payload = self._p5_empty_strike_payload()
        self._p5_strike_available_strikes: list[float] = []
        self._p5_strike_bucket_config = ()
        self._p5_strike_latest_request_id = 1
        self._p5_strike_values_latest_request_id = 1
        self._p5_chain_latest_request_id = 1
        self._p5_chain_df = pd.DataFrame()
        self._p5_chain_ticker = ""
        self._p5_chain_expiry = ""
        self._p5_chain_spot_price = 0.0
        self._p5_chain_rate = 0.0
        self._p5_chain_dividend_yield = 0.0
        self._p5_chain_rate_source = "default"
        self._p5_chain_dividend_source = "default"
        self._p5_completion_sequence = 0
        self._p5_completion_cache: dict[str, dict[str, Any]] = {}
        self._p5_completion_applied_versions: dict[str, int] = {}
        self._p5_completion_applying_versions: dict[str, int] = {}
        self._p5_render_generations: dict[Any, int] = {}
        self.render_calls: list[tuple[int, str]] = []
        self.expiry_render_calls: list[tuple[list[str], str, bool]] = []
        self.top_volume_render_calls: list[tuple[str, str, int]] = []
        self.strike_render_calls: list[tuple[str, float | None, int]] = []
        self.fetch_calls = 0
        self.snapshot_calls = 0

    def _is_current_page(self, page: Any) -> bool:
        return page is self.page5 and self.page_visible

    def _p5_populate_tables(self, df: Any, expiry: str, *, on_complete: Any = None) -> None:
        self._p5_chain_df = df.copy() if hasattr(df, "copy") else df
        self._p5_chain_expiry = str(expiry or "")
        self.render_calls.append((len(df.index), str(expiry or "")))
        if callable(on_complete):
            on_complete(True)

    def _p5_populate_expiries(
        self,
        exps: Any,
        *,
        preferred_expiry: str = "",
        load_chain: bool = True,
    ) -> None:
        self.expiry_render_calls.append((list(exps or []), preferred_expiry, load_chain))

    def _p5_set_top_volume_bucket_config(self, view_key: str, bucket_config: Any) -> None:
        self.p5_top_volume_views[view_key]["bucket_config"] = tuple(bucket_config or ())

    def _p5_clear_top_volume_tables(self, view_key: str) -> None:
        return None

    def _p5_render_top_volume_tables(
        self,
        view_key: str,
        ticker: str,
        bucket_records: dict[str, list[dict[str, Any]]],
        bucket_expirations: dict[str, str],
        *,
        on_complete: Any = None,
    ) -> None:
        self.top_volume_render_calls.append(
            (view_key, ticker, sum(len(rows) for rows in bucket_records.values()))
        )
        if callable(on_complete):
            on_complete(True)

    def _p5_set_strike_bucket_config(self, bucket_config: Any) -> None:
        self._p5_strike_bucket_config = tuple(bucket_config or ())

    def _p5_clear_strike_tables(self) -> None:
        return None

    def _p5_render_strike_tables(
        self,
        ticker: str,
        selected_strike: float | None,
        bucket_records: dict[str, list[dict[str, Any]]],
        bucket_expirations: dict[str, str],
        *,
        on_complete: Any = None,
    ) -> None:
        self.strike_render_calls.append(
            (ticker, selected_strike, sum(len(rows) for rows in bucket_records.values()))
        )
        if callable(on_complete):
            on_complete(True)

    def _p5_save_session_snapshot(self, *, immediate: bool = False) -> None:
        self.snapshot_calls += 1

    def _submit_options_fetch(self, fn: Any) -> None:
        self.fetch_calls += 1

    def set_status_text(self, label: Any, text: str, *, status: str = "muted") -> None:
        label.setText(text)
        label.setProperty("bt_status", status)


class _BulkOptionsHarness(OptionsChainMixin):
    """Visible full-window-style probe used to exercise batched rendering."""

    def __init__(self) -> None:
        self.page5 = object()
        self.p5_tabs = _TabsProbe(0)
        self.p5_calls_table = self._make_chain_table()
        self.p5_puts_table = self._make_chain_table()
        self.p5_strategy_combo = QComboBox()
        self.p5_strategy_combo.addItems(list(self._P5_STRATEGIES))
        self.p5_status_lbl = QLabel("")
        self._p5_chain_df = pd.DataFrame()
        self._p5_chain_expiry = ""
        self._p5_chain_rate = 0.0
        self._p5_chain_dividend_yield = 0.0
        self._p5_chain_rate_source = "default"
        self._p5_chain_dividend_source = "default"
        self._p5_render_generations: dict[Any, int] = {}

    def _is_current_page(self, page: Any) -> bool:
        return page is self.page5

    def theme_color(self, token: str) -> str:
        return {
            "accent_positive": "#00aa66",
            "accent_negative": "#dd4455",
            "accent_positive_bg": "#133d2b",
            "info_bg": "#17314d",
            "accent_soft": "#29364d",
            "background_secondary": "#202632",
            "text_muted": "#8a94a6",
        }.get(str(token), "#808080")

    def set_status_text(self, label: Any, text: str, *, status: str = "muted") -> None:
        label.setText(text)
        label.setProperty("bt_status", status)


class _StandaloneOptionsHarness(_BulkOptionsHarness):
    """Compatibility probe with no main-window visibility helper."""

    _is_current_page = None


def _chain_frame(rows_per_side: int) -> Any:
    rows: list[dict[str, Any]] = []
    for side_index, option_type in enumerate(("Call", "Put")):
        for row_index in range(rows_per_side):
            strike = 50.0 + row_index + side_index * 0.25
            rows.append(
                {
                    "type": option_type,
                    "strike": strike,
                    "lastPrice": 1.0 + row_index / 100.0,
                    "bid": 0.95 + row_index / 100.0,
                    "ask": 1.05 + row_index / 100.0,
                    "change": 0.01 if option_type == "Call" else -0.01,
                    "volume": 10_000 - row_index,
                    "openInterest": 20_000 - row_index,
                    "iv_percent": 25.0,
                    "delta_calc": 0.5 if option_type == "Call" else -0.5,
                    "gamma_calc": 0.02,
                    "theta_calc": -0.03,
                    "vega_calc": 0.10,
                    "rho_calc": 0.01,
                }
            )
    return pd.DataFrame(rows)


def _loaded_chain(harness: _DeferredOptionsHarness, rows_per_side: int = 3) -> None:
    harness._p5_handle_loaded_chain(
        1,
        "SPY",
        _chain_frame(rows_per_side),
        "2026-12-18",
        101.25,
        {
            "risk_free_rate": 0.04,
            "dividend_yield": 0.01,
            "rate_source": "test",
            "dividend_source": "test",
        },
    )


def test_hidden_completion_applies_once_on_page_show_without_refetch() -> None:
    harness = _DeferredOptionsHarness()
    _loaded_chain(harness)

    _assert(not harness.render_calls, "hidden Options completion must not rebuild chain tables")
    cached_chain = harness._p5_completion_cache.get(harness._P5_CHAIN_COMPLETION_KEY, {}).get("df")
    _assert(len(cached_chain.index) == 6, "hidden completion should retain the newest chain payload")
    _assert(harness.p5_price_lbl.text() == "", "hidden completion must not mutate visible price text")

    harness.page_visible = True
    harness._p5_on_show()
    _assert(harness.render_calls == [(6, "2026-12-18")], "page show should render the cached chain exactly once")
    _assert(harness.p5_price_lbl.text() == "$101.25", "page show should apply cached chain metadata")
    _assert(harness.fetch_calls == 0, "showing a completed cached result must not start another fetch")

    harness._p5_on_show()
    _assert(len(harness.render_calls) == 1, "a consumed cached result must not render twice")
    _assert(harness.fetch_calls == 0, "repeated on-show callbacks must stay network-free")


def test_hidden_subtab_completion_applies_once_when_selected() -> None:
    harness = _DeferredOptionsHarness()
    harness.page_visible = True
    harness.p5_tabs.setCurrentIndex(1)
    _loaded_chain(harness)

    _assert(not harness.render_calls, "a hidden Chain subtab must not render its completion")
    harness.p5_tabs.setCurrentIndex(0)
    harness._p5_on_subtab_changed(0)
    _assert(harness.render_calls == [(6, "2026-12-18")], "selecting Chain should consume its cached result")
    _assert(harness.fetch_calls == 0, "selecting a cached subtab must not refetch")

    harness._p5_on_subtab_changed(0)
    _assert(len(harness.render_calls) == 1, "a cached subtab result must be consumed exactly once")


def test_expiry_completion_defers_until_chain_is_visible() -> None:
    harness = _DeferredOptionsHarness()
    harness._p5_handle_loaded_expiries(
        1,
        "SPY",
        ["2026-12-18", "2027-01-15"],
        102.50,
        preferred_expiry="2027-01-15",
    )

    _assert(not harness.expiry_render_calls, "hidden expiry completion must not rebuild the selector")
    _assert(harness.p5_price_lbl.text() == "", "hidden expiry completion must not update price text")
    harness.page_visible = True
    harness._p5_on_show()
    _assert(
        harness.expiry_render_calls == [
            (["2026-12-18", "2027-01-15"], "2027-01-15", True)
        ],
        "showing Chain should apply the cached expiries once",
    )
    _assert(harness.p5_price_lbl.text() == "$102.50", "visible Chain should apply cached spot metadata")
    harness._p5_on_show()
    _assert(len(harness.expiry_render_calls) == 1, "cached expiries must not apply twice")


def test_top_volume_and_strike_completions_wait_for_matching_subtabs() -> None:
    expiry = "2026-12-18"
    top_harness = _DeferredOptionsHarness()
    top_harness.page_visible = True
    top_harness._p5_update_top_volume_view(
        top_harness._P5_TOP_VOLUME_VIEW_KEY,
        1,
        "SPY",
        ((expiry, expiry, 140),),
        {
            expiry: [
                {
                    "ticker": "SPY",
                    "type": "Call",
                    "strike": 600.0,
                    "expiration": expiry,
                    "lastPrice": 4.5,
                    "volume": 1_000,
                }
            ]
        },
        {expiry: expiry},
    )
    _assert(not top_harness.top_volume_render_calls, "hidden top-volume subtab must not render")
    top_harness.p5_tabs.setCurrentIndex(1)
    top_harness._p5_on_subtab_changed(1)
    _assert(
        top_harness.top_volume_render_calls == [("top_volume", "SPY", 1)],
        "selecting top volume should apply its cached payload once",
    )
    top_harness._p5_on_subtab_changed(1)
    _assert(len(top_harness.top_volume_render_calls) == 1, "top-volume payload must not apply twice")

    strike_harness = _DeferredOptionsHarness()
    strike_harness.page_visible = True
    strike_harness._p5_strike_available_strikes = [600.0]
    strike_harness._p5_update_strike_view(
        1,
        "SPY",
        600.0,
        ((expiry, expiry, 140),),
        {
            expiry: [
                {
                    "ticker": "SPY",
                    "type": "Put",
                    "strike": 600.0,
                    "expiration": expiry,
                    "lastPrice": 5.0,
                    "volume": 900,
                }
            ]
        },
        {expiry: expiry},
    )
    _assert(not strike_harness.strike_render_calls, "hidden strike subtab must not render")
    strike_harness.p5_tabs.setCurrentIndex(2)
    strike_harness._p5_on_subtab_changed(2)
    _assert(
        strike_harness.strike_render_calls == [("SPY", 600.0, 1)],
        "selecting strike should apply its cached payload once",
    )
    strike_harness._p5_on_subtab_changed(2)
    _assert(len(strike_harness.strike_render_calls) == 1, "strike payload must not apply twice")


def test_standalone_presenter_probe_is_treated_as_visible() -> None:
    harness = _StandaloneOptionsHarness()
    _assert(harness._p5_page_is_visible(), "presenter probes without a page API should remain visible")
    harness._p5_populate_tables(_chain_frame(2), "2026-12-18")
    _assert(harness.p5_calls_table.rowCount() == 2, "standalone calls should render synchronously")
    _assert(harness.p5_puts_table.rowCount() == 2, "standalone puts should render synchronously")


def test_large_chain_tables_finish_in_multiple_ui_batches() -> None:
    app = QApplication.instance() or QApplication([])
    harness = _BulkOptionsHarness()
    rows_per_side = 225
    harness._p5_populate_tables(_chain_frame(rows_per_side), "2026-12-18")

    handles_by_key = getattr(harness, "_budget_terminal_batched_render_handles", {})
    handles = list(handles_by_key.values()) if isinstance(handles_by_key, dict) else []
    _assert(handles, "large Options tables should be scheduled through the shared batched renderer")
    _assert(any(handle.running for handle in handles), "large Options rendering should remain pending after dispatch")

    deadline = time.perf_counter() + 3.0
    while any(handle.running for handle in handles) and time.perf_counter() < deadline:
        app.processEvents()

    _assert(all(not handle.running for handle in handles), "batched Options rendering should finish before timeout")
    _assert(all(handle.completed for handle in handles), "visible Options render handles should complete, not cancel")
    _assert(any(handle.batch_count > 1 for handle in handles), "large Options tables should span multiple UI turns")
    for table, side in ((harness.p5_calls_table, "calls"), (harness.p5_puts_table, "puts")):
        _assert(table.rowCount() == rows_per_side, f"all {side} should be rendered")
        _assert(table.item(rows_per_side - 1, table.columnCount() - 1) is not None, f"last {side} row should finish")


def test_batched_table_render_preserves_sort_and_selection() -> None:
    app = QApplication.instance() or QApplication([])
    harness = _BulkOptionsHarness()
    table = harness._make_top_volume_table()
    records = [
        {
            "ticker": "SPY",
            "type": "Call" if index % 2 == 0 else "Put",
            "strike": 500.0 + index,
            "expiration": "2026-12-18",
            "lastPrice": 1.0 + index / 10.0,
            "volume": 1_000 - index,
        }
        for index in range(120)
    ]
    rows = build_option_summary_rows(
        records,
        ticker="SPY",
        expiry="2026-12-18",
        positive_color="#00aa66",
        negative_color="#dd4455",
        pd_module=pd,
    )
    render_table_rows(table, rows)
    table.sortItems(2, Qt.SortOrder.DescendingOrder)
    selected_strike = "560.0"
    selected_row = next(
        row_index
        for row_index in range(table.rowCount())
        if table.item(row_index, 2).text() == selected_strike
    )
    table.setCurrentCell(selected_row, 2)

    refreshed_records = [
        {
            **record,
            "lastPrice": float(record["lastPrice"]) + 0.25,
            "volume": int(record["volume"]) + 10,
        }
        for record in reversed(records)
    ]
    refreshed_rows = build_option_summary_rows(
        refreshed_records,
        ticker="SPY",
        expiry="2026-12-18",
        positive_color="#00aa66",
        negative_color="#dd4455",
        pd_module=pd,
    )

    harness._p5_render_table_groups(
        "sort-selection-probe",
        [(table, refreshed_rows)],
        is_visible=lambda: True,
    )
    handles = list(getattr(harness, "_budget_terminal_batched_render_handles", {}).values())
    deadline = time.perf_counter() + 3.0
    while any(handle.running for handle in handles) and time.perf_counter() < deadline:
        app.processEvents()

    _assert(all(handle.completed for handle in handles), "sort-selection batch should complete")
    _assert(table.isSortingEnabled(), "batched refresh should restore sorting")
    strikes = [float(table.item(row_index, 2).text()) for row_index in range(table.rowCount())]
    _assert(strikes == sorted(strikes, reverse=True), "batched refresh should preserve descending strike sort")
    _assert(table.currentItem() is not None, "batched refresh should restore the selected row")
    _assert(table.item(table.currentRow(), 2).text() == selected_strike, "batched refresh should preserve selection")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    test_hidden_completion_applies_once_on_page_show_without_refetch()
    test_hidden_subtab_completion_applies_once_when_selected()
    test_expiry_completion_defers_until_chain_is_visible()
    test_top_volume_and_strike_completions_wait_for_matching_subtabs()
    test_standalone_presenter_probe_is_treated_as_visible()
    test_large_chain_tables_finish_in_multiple_ui_batches()
    test_batched_table_render_preserves_sort_and_selection()
    print("Options refresh responsiveness smoke tests passed.")


if __name__ == "__main__":
    main()
