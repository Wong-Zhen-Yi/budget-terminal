from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_DATA_DIR = tempfile.TemporaryDirectory(
    prefix="budget-terminal-signal-scanner2-",
    ignore_cleanup_errors=True,
)
os.environ["LOCALAPPDATA"] = _TEST_DATA_DIR.name

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.services.automatic_signal_scanner import (
    AutoTickerCandidate,
    AutoUniverseConfig,
    AutomaticSignalScanPayload,
    AutomaticSignalScannerService,
    AutomaticTickerUniverseService,
)
from budget_terminal_app.services.signal_engine import evaluate_signal
from budget_terminal_app.services.signal_models import SignalClass, TradeStatus
from budget_terminal_app.services.signal_scanner import SignalScanRequest, SignalScannerService


def _daily_frame(close: float, volume: float, *, current_volume: float | None = None) -> pd.DataFrame:
    index = pd.date_range("2026-07-15", periods=21, freq="B")
    volumes = np.full(21, volume, dtype=float)
    if current_volume is not None:
        volumes[-1] = current_volume
    return pd.DataFrame(
        {
            "Open": np.full(21, close),
            "High": np.full(21, close + 1.0),
            "Low": np.full(21, close - 1.0),
            "Close": np.full(21, close),
            "Volume": volumes,
        },
        index=index,
    )


class _FakeUniverseService(AutomaticTickerUniverseService):
    def _screen_quotes(self):
        return [
            {"symbol": "AAA", "quoteType": "EQUITY", "exchange": "NMS", "regularMarketPrice": 100, "marketCap": 10_000_000_000},
            {"symbol": "BBB", "quoteType": "EQUITY", "exchange": "NYQ", "regularMarketPrice": 50, "marketCap": 20_000_000_000},
            {"symbol": "PARTIAL", "quoteType": "EQUITY", "exchange": "NMS", "regularMarketPrice": 20, "marketCap": 3_000_000_000},
            {"symbol": "ETF", "quoteType": "ETF", "exchange": "NMS", "regularMarketPrice": 500, "marketCap": 500_000_000_000},
        ]

    def _download_daily_frames(self, tickers):
        assert set(tickers) == {"AAA", "BBB", "PARTIAL"}
        return {
            "AAA": _daily_frame(100.0, 400_000.0),
            "BBB": _daily_frame(50.0, 2_000_000.0),
            "PARTIAL": _daily_frame(20.0, 100_000.0, current_volume=100_000_000.0),
        }


def _signal_frame(close: np.ndarray, *, frequency: str, volume: np.ndarray | None = None) -> pd.DataFrame:
    close_values = np.asarray(close, dtype=float)
    volumes = np.asarray(volume if volume is not None else np.full(len(close_values), 1_000.0), dtype=float)
    return pd.DataFrame(
        {
            "Open": close_values - 0.08,
            "High": close_values + 0.12,
            "Low": close_values - 0.18,
            "Close": close_values,
            "Volume": volumes,
        },
        index=pd.date_range("2025-01-02 09:30", periods=len(close_values), freq=frequency),
    )


def _bullish_frames() -> dict[str, pd.DataFrame]:
    momentum_x = np.arange(90, dtype=float)
    setup_close = np.linspace(130.0, 132.0, 45)
    setup_close[-1] = float(setup_close[:-1].max() + 1.0)
    setup_volume = np.full(45, 1_000.0)
    setup_volume[-1] = 2_000.0
    return {
        "trend": _signal_frame(np.linspace(100.0, 170.0, 240), frequency="1D"),
        "momentum": _signal_frame(120.0 + momentum_x * 0.035 + np.sin(momentum_x / 2.5) * 0.55, frequency="1h"),
        "setup": _signal_frame(setup_close, frequency="5min", volume=setup_volume),
        "entry": _signal_frame(np.linspace(132.0, 132.8, 30), frequency="1min"),
    }


def test_universe_ranks_liquidity_and_ignores_partial_bar() -> None:
    cache = CacheManager(Path(_TEST_DATA_DIR.name) / "universe.db")
    config = AutoUniverseConfig(shortlist_limit=2, minimum_median_dollar_volume=20_000_000.0)
    service = _FakeUniverseService(
        cache,
        config=config,
        now=lambda: dt.datetime(2026, 8, 15, 12, tzinfo=dt.timezone.utc),
    )
    payload = service.source_candidates(force_refresh=True)
    assert [item.ticker for item in payload["candidates"]] == ["BBB", "AAA"]
    assert [item.quality_rank for item in payload["candidates"]] == [1, 2]
    assert payload["rejected_candidate_count"] == 2
    # Only filter failures count as rejections; the shortlist cut is reported separately.
    assert payload["passed_filter_count"] == 2
    cached = service.source_candidates()
    assert cached["from_cache"] is True
    assert [item.ticker for item in cached["candidates"]] == ["BBB", "AAA"]


def test_payload_round_trip() -> None:
    result = evaluate_signal("AAA", _bullish_frames())
    candidate = AutoTickerCandidate(
        ticker="AAA",
        name="AAA Inc",
        exchange="Nasdaq",
        price=100.0,
        market_cap=10_000_000_000.0,
        median_dollar_volume=40_000_000.0,
        quality_rank=1,
        reasons=("Liquid",),
    )
    payload = AutomaticSignalScanPayload(candidates=[candidate], results=[result], passed_filter_count=7)
    restored = AutomaticSignalScannerService.payload_from_dict(
        AutomaticSignalScannerService.payload_to_dict(payload)
    )
    assert restored.candidates == [candidate]
    assert restored.results[0].ticker == "AAA"
    assert restored.results[0].signal is result.signal
    assert restored.results[0].reasons == result.reasons
    assert restored.passed_filter_count == 7
    assert set(restored.results[0].timeframe_bars) == {"trend", "momentum", "setup", "entry"}
    assert restored.results[0].timeframe_bars["trend"]["as_of"] == result.timeframe_bars["trend"]["as_of"]


def test_presenters_handle_mixed_timezone_payload_stamps() -> None:
    """The universe stamps ``sourced_at`` tz-aware while the scan stamps ``completed_at`` naive."""
    from budget_terminal_app.mixins import signals_presenters as presenters

    payload = AutomaticSignalScanPayload(
        candidates=[],
        results=[],
        sourced_at=dt.datetime(2026, 8, 15, 12, tzinfo=dt.timezone.utc),
        completed_at=dt.datetime(2026, 8, 15, 14, 30),
        started_at=dt.datetime(2026, 8, 15, 14, 0),
        passed_filter_count=3,
    )
    universe_text = presenters.describe_universe(payload)
    assert "2026-08-15" in universe_text
    freshness_text, status = presenters.describe_scan_freshness(payload)
    assert "2026-08-15 14:30" in freshness_text
    assert status in {"positive", "warning", "muted"}


def test_batch_split_supports_both_column_orientations() -> None:
    from budget_terminal_app.services.signal_scanner import SignalMarketDataService

    base = _daily_frame(100.0, 1_000.0)
    price_first = pd.concat({"AAA": base, "BBB": base * 2}, axis=1).swaplevel(0, 1, axis=1).sort_index(axis=1)
    ticker_first = pd.concat({"AAA": base, "BBB": base * 2}, axis=1)
    for batch in (price_first, ticker_first):
        split = SignalMarketDataService.split_download_frame(batch, ("AAA", "BBB"))
        assert set(split) == {"AAA", "BBB"}
        assert set(split["AAA"].columns) >= {"Close", "Volume"}


class _FakeBatchDataService:
    source_name = "Test Feed"

    @staticmethod
    def timeframe_request(label):
        from budget_terminal_app.services.signal_scanner import SignalMarketDataService

        return SignalMarketDataService.timeframe_request(label)

    def fetch_frames(self, tickers, request, *, force_refresh=False):
        role_by_interval = {"1d": "trend", "1h": "momentum", "5m": "setup", "1m": "entry"}
        return {"GOOD": _bullish_frames()[role_by_interval[request.interval]]}, {"BAD": "simulated failure"}


def test_batched_scan_isolates_ticker_failure() -> None:
    request = SignalScanRequest(
        tickers=("GOOD", "BAD"),
        role_timeframes={"trend": "1 Day", "momentum": "1 Hour", "setup": "5 Minutes", "entry": "1 Minute"},
    )
    results, errors = SignalScannerService(_FakeBatchDataService()).scan_tickers_batched(request)
    assert [result.ticker for result in results] == ["GOOD", "BAD"]
    assert results[0].trade_status is TradeStatus.VALID_LONG
    assert results[1].trade_status is TradeStatus.DATA_ERROR
    assert "BAD" in errors


def test_signal_scanner2_page_smoke() -> None:
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.dependencies import QApplication, Qt
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    app = QApplication.instance() or QApplication([])
    window = None
    try:
        window = BudgetTerminalApp()
        window._ensure_page_initialized(39)
        window.stacked_widget.setCurrentIndex(39)
        result = evaluate_signal("AAA", _bullish_frames())
        candidate = AutoTickerCandidate(
            ticker="AAA",
            name="AAA Inc",
            exchange="Nasdaq",
            price=100.0,
            market_cap=10_000_000_000.0,
            median_dollar_volume=40_000_000.0,
            quality_rank=1,
            reasons=("20-session median dollar volume $40.0M",),
        )
        second_result = replace(
            result,
            ticker="BBB",
            price=50.0,
            raw_score=4.0,
            signal=SignalClass.WATCH,
            trade_status=TradeStatus.WATCH,
        )
        second_candidate = AutoTickerCandidate(
            ticker="BBB",
            name="BBB Inc",
            exchange="NYSE",
            price=50.0,
            market_cap=20_000_000_000.0,
            median_dollar_volume=100_000_000.0,
            quality_rank=2,
            reasons=("20-session median dollar volume $100.0M",),
        )
        window._p40_payload = AutomaticSignalScanPayload(
            candidates=[candidate, second_candidate],
            results=[result, second_result],
        )
        window._p40_render_payload()
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        assert window.btn_page40.text() == "Signals"
        assert 38 not in window._pages
        assert hasattr(window, "_retired_page38")
        assert window._navigation_page_order().index(39) == window._navigation_page_order().index(19) + 1
        assert window.p40_table.rowCount() == 2
        initial_ticker = window.p40_table.item(0, 1).text()
        initial_rank = window.p40_table.item(0, 0).text()
        # Qt defaults the sort indicator to column 0 descending, which once opened the shortlist
        # with the worst-ranked candidate on top. The best candidate must lead.
        assert initial_rank == "1", f"expected rank 1 first, got {initial_rank}"
        assert [
            window.p40_table.item(row, 0).text() for row in range(window.p40_table.rowCount())
        ] == ["1", "2"]
        assert window.p40_detail_ticker.text().startswith(f"{initial_ticker} ·")
        assert f"Quality rank #{initial_rank}" in window.p40_detail_summary.text(), repr(window.p40_detail_summary.text())
        assert "EMA20" in window.p40_indicators_text.toPlainText()
        assert "median dollar volume" in window.p40_reasons_text.toPlainText()
        assert not hasattr(window, "p40_pause_btn")
        assert not hasattr(window, "_p40_scheduler_timer")

        bbb_row = next(
            row
            for row in range(window.p40_table.rowCount())
            if window.p40_table.item(row, 1).text() == "BBB"
        )
        window.p40_table.selectRow(bbb_row)
        app.processEvents()
        assert window.p40_detail_ticker.text().startswith("BBB ·")
        assert "Quality rank #2" in window.p40_detail_summary.text()

        window.p40_table.sortItems(1, Qt.SortOrder.DescendingOrder)
        window.p40_table.selectRow(0)
        app.processEvents()
        selected_ticker = window.p40_table.item(0, 1).text()
        assert window.p40_detail_ticker.text().startswith(f"{selected_ticker} ·")

        watch_index = window.p40_filter_combo.findData("watch")
        window.p40_filter_combo.setCurrentIndex(watch_index)
        app.processEvents()
        assert window.p40_table.rowCount() == 1
        assert window.p40_table.item(0, 1).text() == "BBB"
        assert window.p40_detail_ticker.text().startswith("BBB ·")
        window.p40_filter_combo.setCurrentIndex(window.p40_filter_combo.findData("all"))
        app.processEvents()

        # A blocked entry must not be presented as a tradable long or strong setup.
        blocked = replace(second_result, ticker="CCC", signal=SignalClass.STRONG_LONG,
                          trade_status=TradeStatus.TOO_EXTENDED, raw_score=9.0)
        window._p40_payload = AutomaticSignalScanPayload(
            candidates=[candidate, second_candidate],
            results=[result, second_result, blocked],
        )
        for filter_key in ("long", "strong"):
            window.p40_filter_combo.setCurrentIndex(window.p40_filter_combo.findData(filter_key))
            app.processEvents()
            shown = {window.p40_table.item(row, 1).text() for row in range(window.p40_table.rowCount())}
            assert "CCC" not in shown, (filter_key, shown)
        window.p40_filter_combo.setCurrentIndex(window.p40_filter_combo.findData("blocked"))
        app.processEvents()
        assert [window.p40_table.item(row, 1).text() for row in range(window.p40_table.rowCount())] == ["CCC"]

        # An empty filter result explains itself instead of leaving a blank table.
        window.p40_search_input.setText("ZZZZ")
        window.p40_filter_combo.setCurrentIndex(window.p40_filter_combo.findData("all"))
        window._p40_apply_search()
        app.processEvents()
        assert window.p40_table.rowCount() == 0
        assert window.p40_empty_lbl.isVisible()
        assert "No results match" in window.p40_empty_lbl.text()
        window.p40_search_input.setText("")
        window._p40_apply_search()
        app.processEvents()

        # A row missing its candidate metadata must still sort numerically, not lexically.
        orphan = replace(result, ticker="DDD", price=None)
        window._p40_payload = AutomaticSignalScanPayload(
            candidates=[candidate, second_candidate],
            results=[result, second_result, orphan],
        )
        window._p40_render_payload()
        window.p40_table.sortItems(2, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        prices = [window.p40_table.item(row, 2).text() for row in range(window.p40_table.rowCount())]
        # Descending by price: the unknown price sorts last rather than between the two numbers.
        assert prices[-1] == "—", prices
        assert [float(text.lstrip("$").replace(",", "")) for text in prices[:-1]] == sorted(
            [float(text.lstrip("$").replace(",", "")) for text in prices[:-1]], reverse=True
        ), prices

        # Selection survives a re-render triggered by typing in the search box.
        window._p40_payload = AutomaticSignalScanPayload(
            candidates=[candidate, second_candidate],
            results=[result, second_result],
        )
        window._p40_render_payload()
        bbb_row = next(
            row for row in range(window.p40_table.rowCount())
            if window.p40_table.item(row, 1).text() == "BBB"
        )
        window.p40_table.selectRow(bbb_row)
        app.processEvents()
        window._p40_render_payload()
        app.processEvents()
        assert window._p40_selected_ticker() == "BBB"
        assert window.p40_detail_ticker.text().startswith("BBB ·")

        # The ticker payload must survive on its own role, clear of the sort role.
        ticker_item = window.p40_table.item(bbb_row, 1)
        assert ticker_item.data(Qt.ItemDataRole.UserRole + 1) in {"AAA", "BBB"}
        window.p40_table.selectRow(0)
        app.processEvents()
        alerts = []
        window.on_signal2_generated = alerts.append
        window._p40_alert_states.clear()
        window._p40_process_signal_transitions([result])
        window._p40_process_signal_transitions([result])
        assert alerts == []

        class _InstantService:
            @staticmethod
            def run_scan(**kwargs):
                progress = kwargs.get("progress")
                if progress:
                    progress(1, 1, "AAA")
                return window._p40_payload

        window._p40_service = _InstantService()
        assert window._p40_request_scan() is True
        deadline = time.monotonic() + 2.0
        while window._p40_thread is not None and time.monotonic() < deadline:
            app.processEvents()
        assert window._p40_thread is None
        # The single-flight slot must be released, otherwise the next click is refused forever.
        assert window._refresh_coordinator.active_token(("signals", "scan")) is None
        assert window.p40_refresh_btn.isEnabled()

        launch_calls = []
        window._p40_launch_scan = lambda token, context: launch_calls.append(dict(context)) or True
        window._p40_market_session = lambda: SimpleNamespace(is_open=False)
        window._p40_manual_refresh()
        assert len(launch_calls) == 1
        # The default refresh honours the per-timeframe cache ages; forcing is a separate action.
        assert launch_calls[0] == {"force_market_refresh": False, "force_universe_refresh": False}
        window._p40_finish_scan(window._refresh_coordinator.active_token(("signals", "scan")))

        window._refresh_current_page()
        assert len(launch_calls) == 2
        assert launch_calls[1] == {"force_market_refresh": False, "force_universe_refresh": False}

        # A second request while one is active is queued, then runs on completion.
        active = window._refresh_coordinator.active_token(("signals", "scan"))
        assert window._p40_force_refresh() is None
        assert len(launch_calls) == 2
        window._p40_finish_scan(active)
        assert len(launch_calls) == 3
        assert launch_calls[2] == {"force_market_refresh": True, "force_universe_refresh": True}
        window._p40_finish_scan(window._refresh_coordinator.active_token(("signals", "scan")))
    finally:
        if window is not None:
            window.close()
            app.processEvents()
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup


def main() -> None:
    tests = (
        test_universe_ranks_liquidity_and_ignores_partial_bar,
        test_payload_round_trip,
        test_presenters_handle_mixed_timezone_payload_stamps,
        test_batch_split_supports_both_column_orientations,
        test_batched_scan_isolates_ticker_failure,
        test_signal_scanner2_page_smoke,
    )
    for test in tests:
        test()
    print(f"Signals tests passed ({len(tests)} checks).")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    _TEST_DATA_DIR.cleanup()
    os._exit(0)
