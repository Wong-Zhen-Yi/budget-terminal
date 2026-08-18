from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.data_service.results import (
    attach_market_data_result,
    make_market_data_meta,
    market_data_errors,
    market_data_meta,
)
from budget_terminal_app.data_service.tasks import MarketDataTaskRunner
from budget_terminal_app.persistence import _normalize_chart_page_settings
from budget_terminal_app.services.chart_data import ChartDataService
from budget_terminal_app.services.relationship_analysis import (
    build_relationship_analysis,
    normalize_relationship_symbols,
)
from scripts.test_charts_startup_indicators import _build_window


def _close_frame(dates: Any, closes: Any) -> pd.DataFrame:
    values = [float(value) for value in closes]
    frame = pd.DataFrame({"Close": values}, index=pd.DatetimeIndex(dates))
    frame.index.name = "Date"
    return frame


def _ohlcv_frame(dates: Any, closes: Any) -> pd.DataFrame:
    values = pd.Series([float(value) for value in closes], index=pd.DatetimeIndex(dates))
    frame = pd.DataFrame(
        {
            "Open": values * 0.99,
            "High": values * 1.01,
            "Low": values * 0.98,
            "Close": values,
            "Volume": 1_000.0,
        },
        index=values.index,
    )
    frame.index.name = "Date"
    return frame


def _regression_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2025-01-02", periods=7)
    right_returns = [0.01, 0.02, -0.01, 0.03, 0.005, -0.02]
    left_returns = [0.001 + 2.0 * value for value in right_returns]
    right_prices = [100.0]
    left_prices = [80.0]
    for right_return, left_return in zip(right_returns, left_returns):
        right_prices.append(right_prices[-1] * (1.0 + right_return))
        left_prices.append(left_prices[-1] * (1.0 + left_return))
    return _close_frame(dates, left_prices), _close_frame(dates, right_prices)


def test_relationship_alignment_returns_ratios_and_regression() -> None:
    left, right = _regression_frames()
    extra_date = left.index[0] - pd.Timedelta(days=1)
    right = pd.concat([_close_frame([extra_date], [90.0]), right])
    analysis = build_relationship_analysis(left, right, rolling_window=30)

    assert analysis["aligned"].index.equals(left.index)
    assert analysis["indexed"].iloc[0].tolist() == [100.0, 100.0]
    assert math.isclose(float(analysis["ratio"].iloc[0]), 0.8)
    assert len(analysis["returns"]) == 6
    assert set(analysis["rolling_correlations"]) == {30, 60, 120, 252}
    assert set(analysis["rolling_sample_sizes"]) == {30, 60, 120, 252}
    assert analysis["latest_correlation_sample"] == 6
    stats = analysis["stats"]
    assert stats["observations"] == 6
    assert math.isclose(stats["beta"], 2.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(stats["alpha_daily_pct"], 0.1, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(stats["r"], 1.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(stats["r_squared"], 1.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(stats["std_error_pct"], 0.0, abs_tol=1e-9)
    assert analysis["regression_line"].shape == (2, 2)


def test_relationship_validation_invalid_prices_and_insufficient_observations() -> None:
    assert normalize_relationship_symbols([" qqq ", "spy"]) == ("QQQ", "SPY")
    for symbols in (("SPY", "SPY"), ("SPY",), ("SPY", "QQQ", "DIA")):
        try:
            normalize_relationship_symbols(symbols)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid pair was accepted: {symbols}")

    dates = pd.bdate_range("2025-01-02", periods=6)
    left = _close_frame(dates, [100.0, 0.0, 102.0, -3.0, 104.0, 105.0])
    right = _close_frame(dates, [50.0, 51.0, 52.0, 53.0, 54.0, 55.0])
    analysis = build_relationship_analysis(left, right, rolling_window=60)
    assert len(analysis["aligned"]) == 4
    assert len(analysis["returns"]) == 3
    assert analysis["stats"]["observations"] == 3
    for key in ("beta", "alpha_daily_pct", "r", "r_squared", "std_error_pct"):
        assert analysis["stats"][key] is None
    assert analysis["latest_correlation"] is None
    assert analysis["latest_correlation_sample"] == 0


def test_relationship_adjusted_cache_fresh_force_max_stale_partial_and_failed() -> None:
    import budget_terminal_app.services.chart_data as chart_data_module

    dates = pd.bdate_range("2025-01-02", periods=65)
    adjusted = {
        "AAA": _ohlcv_frame(dates, range(100, 165)),
        "BBB": _ohlcv_frame(dates, range(200, 265)),
    }
    raw_batch = pd.concat(adjusted, axis=1)
    calls: list[dict[str, Any]] = []

    def fake_download(*args: Any, **kwargs: Any) -> pd.DataFrame:
        calls.append(dict(kwargs))
        return raw_batch

    original_download = chart_data_module.yf.download
    chart_data_module.yf.download = fake_download
    try:
        with tempfile.TemporaryDirectory(prefix="budget-terminal-relationship-") as temp_dir:
            cache = CacheManager(Path(temp_dir) / "cache.db")
            runner = MarketDataTaskRunner(default_timeout_seconds=2.0, default_retries=0)
            service = ChartDataService(cache_manager=cache, task_runner=runner)
            ordinary = _ohlcv_frame(dates, [10.0] * len(dates))
            cache.save_data("AAA", "1d", ordinary)
            try:
                live = service.fetch_relationship_frames_payload(["AAA", "BBB"], period="1mo")
                assert set(live["frames"]) == {"AAA", "BBB"}
                assert live["missing"] == []
                assert market_data_meta(live)["freshness"] == "fresh"
                assert calls[-1]["auto_adjust"] is True
                assert calls[-1]["interval"] == "1d"
                assert float(cache.get_data("AAA", "1d")["Close"].iloc[-1]) == 10.0
                assert float(cache.get_data("AAA", "1d_adj")["Close"].iloc[-1]) == 164.0

                cached = service.fetch_relationship_frames_payload(["AAA", "BBB"], period="1mo")
                assert len(calls) == 1
                assert market_data_meta(cached)["source"] == "adjusted history cache"

                service.fetch_relationship_frames_payload(["AAA", "BBB"], period="1mo", force_refresh=True)
                assert len(calls) == 2
                service.fetch_relationship_frames_payload(["AAA", "BBB"], period="max")
                assert len(calls) == 3

                def failing_download(*_args: Any, **_kwargs: Any) -> pd.DataFrame:
                    raise RuntimeError("offline")

                chart_data_module.yf.download = failing_download
                stale = service.fetch_relationship_frames_payload(
                    ["AAA", "BBB"], period="1mo", force_refresh=True
                )
                assert set(stale["frames"]) == {"AAA", "BBB"}
                assert market_data_meta(stale)["freshness"] == "stale"
                assert market_data_errors(stale)
            finally:
                runner.shutdown(wait=True)

        with tempfile.TemporaryDirectory(prefix="budget-terminal-relationship-partial-") as temp_dir:
            cache = CacheManager(Path(temp_dir) / "cache.db")
            cache.save_data("AAA", "1d_adj", adjusted["AAA"])
            runner = MarketDataTaskRunner(default_timeout_seconds=2.0, default_retries=0)
            service = ChartDataService(cache_manager=cache, task_runner=runner)
            try:
                partial = service.fetch_relationship_frames_payload(["AAA", "BBB"], period="1mo")
                assert set(partial["frames"]) == {"AAA"}
                assert partial["missing"] == ["BBB"]
                assert market_data_meta(partial)["freshness"] == "partial"
                assert market_data_errors(partial)
            finally:
                runner.shutdown(wait=True)

        with tempfile.TemporaryDirectory(prefix="budget-terminal-relationship-failed-") as temp_dir:
            runner = MarketDataTaskRunner(default_timeout_seconds=2.0, default_retries=0)
            service = ChartDataService(
                cache_manager=CacheManager(Path(temp_dir) / "cache.db"),
                task_runner=runner,
            )
            try:
                failed = service.fetch_relationship_frames_payload(["AAA", "BBB"], period="1mo")
                assert failed["frames"] == {}
                assert failed["missing"] == ["AAA", "BBB"]
                assert market_data_meta(failed)["freshness"] == "failed"
                assert market_data_errors(failed)
            finally:
                runner.shutdown(wait=True)
    finally:
        chart_data_module.yf.download = original_download


def test_relationship_offscreen_ui_lifecycle_and_latest_request_guard() -> None:
    import budget_terminal_app.mixins.charts_page as charts_page_module

    saved_states: list[dict[str, Any]] = []
    original_save = charts_page_module.save_chart_page_settings

    def fake_save(settings: Any) -> dict[str, Any]:
        normalized = _normalize_chart_page_settings(settings)
        saved_states.append(normalized)
        return normalized

    charts_page_module.save_chart_page_settings = fake_save
    app = window = None
    try:
        state = _normalize_chart_page_settings({"symbol": "SPY"})
        app, window = _build_window(state)
        assert [window.p10_tabs.tabText(index) for index in range(window.p10_tabs.count())] == [
            "Main",
            "Multi Charts",
            "Compare",
            "Relationship",
            "Cheat Sheet",
        ]
        assert window.p10_relationship_symbols == ["QQQ", "SPY"]
        assert window.p10_relationship_widget.settings()["range_label"] == "1Y"
        assert window.p10_relationship_widget.settings()["window"] == 120

        refreshes: list[bool] = []
        window._p10_refresh_relationship = lambda *, force=False: refreshes.append(bool(force))
        window.p10_tabs.setCurrentWidget(window.p10_relationship_tab)
        app.processEvents()
        assert window._p10_active_subtab_key() == "relationship"
        assert refreshes == [False]

        widget = window.p10_relationship_widget
        widget.swap_button.click()
        app.processEvents()
        assert widget.left_input.text() == "SPY"
        assert widget.right_input.text() == "QQQ"
        assert saved_states[-1]["relationship_symbols"] == ["SPY", "QQQ"]
        assert refreshes[-1] is False

        left, right = _regression_frames()
        analysis = build_relationship_analysis(left, right, rolling_window=30)
        widget.render_analysis(("SPY", "QQQ"), analysis)
        assert widget._metric_values["beta"].text() == "2.000"
        assert widget._metric_values["observations"].text() == "6"
        assert len(widget._crosshair_lines) == 3
        assert widget._scatter_highlight is not None
        widget._select_date_index(3)
        assert "2025-01" in widget.detail_label.text()
        widget.apply_theme()

        window._p10_relationship_active_request = 2
        window._p10_relationship_display_signature = None
        window._p10_apply_relationship_payload(
            1,
            {
                "signature": (("SPY", "QQQ"), "1Y", 30),
                "symbols": ("SPY", "QQQ"),
                "analysis": analysis,
            },
        )
        assert window._p10_relationship_display_signature is None

        window.p10_relationship_symbols = ["SPY", "QQQ"]
        window.p10_relationship_range_label = "1Y"
        window.p10_relationship_window = 30
        widget.set_settings(("SPY", "QQQ"), "1Y", 30)
        window._p10_relationship_active_request = 3
        partial_payload = attach_market_data_result(
            {"frames": {"SPY": left}, "missing": ["QQQ"]},
            meta=make_market_data_meta(
                source="adjusted history cache",
                freshness="partial",
                failure_reason="No adjusted history was available for QQQ.",
            ),
        )
        window._p10_apply_relationship_unavailable(
            3,
            {
                "signature": (("SPY", "QQQ"), "1Y", 30),
                "symbols": ("SPY", "QQQ"),
                "frame_payload": partial_payload,
            },
        )
        assert widget._analysis is None
        assert widget.status_label.property("bt_status") == "warning"
        assert "QQQ" in widget.status_label.text()

        widget.left_input.setText("SPY")
        widget.right_input.setText("SPY")
        window._p10_analyze_relationship()
        assert window._p10_relationship_display_signature is None
        assert widget._analysis is None
        assert "different" in widget.status_label.text().lower()

        widget.left_input.setText("QQQ")
        widget.right_input.setText("SPY")
        window.stacked_widget.setCurrentWidget(window.page10)
        refreshes.clear()
        window._refresh_current_page()
        assert refreshes == [True]
    finally:
        charts_page_module.save_chart_page_settings = original_save
        if window is not None:
            window.close()
            window.deleteLater()
        if app is not None:
            app.processEvents()


if __name__ == "__main__":
    test_relationship_alignment_returns_ratios_and_regression()
    test_relationship_validation_invalid_prices_and_insufficient_observations()
    test_relationship_adjusted_cache_fresh_force_max_stale_partial_and_failed()
    test_relationship_offscreen_ui_lifecycle_and_latest_request_guard()
    print("charts relationship tests passed")
