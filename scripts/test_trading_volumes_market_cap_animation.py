from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pyqtgraph as pg

from budget_terminal_app.compat import QApplication, QLabel, QPushButton, QTimer, QWidget
from budget_terminal_app.mixins.overview import (
    _P20CompactCurrencyAxisItem,
    _P20_MARKET_CAP_ANIMATION_FRAME_MS,
    OverviewMixin,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_close(actual: float, expected: float, message: str) -> None:
    _assert(math.isclose(actual, expected, rel_tol=1e-9), message)


class _TradingVolumesAnimationProbe(OverviewMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self._p20_dot_metric = '5d'
        self._p20_trading_volume_rows: list[dict[str, Any]] = []
        self._p20_dot_plot_points = []
        self._p20_dot_plot_log_points = []
        self._p20_dot_plot_return_states = []
        self._p20_dot_label_items = []
        self._p20_dot_scatter_item = None
        self._p20_market_cap_animation_entries = []
        self._p20_market_cap_animation_dates = []
        self._p20_market_cap_animation_frame_points = []
        self._p20_market_cap_animation_progress = 1.0
        self._p20_market_cap_animation_timer = QTimer(self)
        self._p20_market_cap_animation_timer.setInterval(_P20_MARKET_CAP_ANIMATION_FRAME_MS)
        self._p20_market_cap_animation_timer.timeout.connect(self._p20_step_market_cap_animation)
        self.p20_dot_empty_lbl = QLabel()
        self.p20_market_cap_replay_btn = QPushButton('Replay')
        self.p20_market_cap_animation_lbl = QLabel('Estimated market cap')
        self.p20_dot_plot = pg.PlotWidget(axisItems={
            'bottom': _P20CompactCurrencyAxisItem(orientation='bottom', log_values=True),
            'left': _P20CompactCurrencyAxisItem(orientation='left', log_values=True),
        })


def _history(values: list[float]) -> list[dict[str, Any]]:
    return [
        {'date': f'2026-07-{20 + index:02d}', 'value': value}
        for index, value in enumerate(values)
    ]


def _rows() -> list[dict[str, Any]]:
    return [
        {
            'ticker': 'AAA',
            'market_cap': 1_000.0,
            'one_day_dollar_volume': 90.0,
            'five_day_avg_dollar_volume': 100.0,
            'one_day_price_return_pct': 10.0,
            'five_day_price_return_pct': 100.0,
            'three_year_avg_dollar_volume': 80.0,
            'three_year_price_return_pct': 100.0,
            'market_cap_estimate_history': _history([500.0, 600.0, 700.0, 800.0, 900.0, 1_000.0]),
        },
        {
            'ticker': 'STATIC',
            'market_cap': 500.0,
            'one_day_dollar_volume': 180.0,
            'five_day_avg_dollar_volume': 200.0,
            'one_day_price_return_pct': 0.0,
            'five_day_price_return_pct': None,
            'three_year_avg_dollar_volume': 160.0,
            'three_year_price_return_pct': None,
            'market_cap_estimate_history': _history([500.0]),
        },
    ]


def test_market_cap_replay_moves_y_only_and_restores_current_values() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _TradingVolumesAnimationProbe()
    rows = _rows()
    probe._p20_trading_volume_rows = rows

    try:
        probe._p20_render_dot_plot(rows)
        _assert(probe.p20_market_cap_replay_btn.isEnabled(), 'live rows with daily history should enable Replay')
        _assert(probe._p20_dot_scatter_item.opts.get('hoverable'), 'estimated market-cap details should be hoverable')

        probe._p20_replay_market_cap_animation()
        probe._p20_market_cap_animation_timer.stop()
        _assert(len(probe._p20_market_cap_animation_dates) == 6, '5D replay should include six close observations')
        fixed_y_range = list(probe.p20_dot_plot.viewRange()[1])

        probe._p20_apply_market_cap_animation_frame(0.0)
        start_points = list(probe._p20_market_cap_animation_frame_points)
        _assert_close(start_points[0][0], 100.0, 'Replay should keep selected ADV fixed on X')
        _assert_close(start_points[0][1], 500.0, 'Replay should begin at the interval-start estimated cap')
        _assert_close(start_points[1][1], 500.0, 'insufficient-history tickers should remain at current cap')

        probe._p20_apply_market_cap_animation_frame(0.5)
        middle_points = list(probe._p20_market_cap_animation_frame_points)
        _assert_close(middle_points[0][0], 100.0, 'ADV should remain fixed through intermediate frames')
        _assert_close(middle_points[0][1], math.sqrt(700.0 * 800.0), 'daily observations should interpolate smoothly in log-cap space')
        _assert(probe.p20_dot_plot.viewRange()[1] == fixed_y_range, 'Y-axis bounds should remain fixed during Replay')

        probe._p20_apply_market_cap_animation_frame(1.0)
        end_points = list(probe._p20_market_cap_animation_frame_points)
        _assert_close(end_points[0][1], 1_000.0, 'Replay should finish at current market cap')
        _assert('2026-07-25' in probe.p20_market_cap_animation_lbl.text(), 'playback status should show the active date')

        tooltip = probe._p20_market_cap_tooltip(
            0,
            0,
            probe._p20_market_cap_tooltip_payload(
                rows[0],
                ticker='AAA',
                market_cap=1_000.0,
                metric_key='5d',
            ),
        )
        _assert('Change from interval start: +$500 (+100.00%)' in tooltip, 'hover should show dollar and percent change')
        _assert('Price-based estimate' in tooltip, 'hover should disclose the estimation method')

        insufficient_tooltip = probe._p20_market_cap_tooltip(
            0,
            0,
            probe._p20_market_cap_tooltip_payload(
                rows[1],
                ticker='STATIC',
                market_cap=500.0,
                metric_key='5d',
            ),
        )
        _assert('Insufficient history' in insufficient_tooltip, 'stationary tickers should explain missing history')

        probe._p20_replay_market_cap_animation()
        _assert(probe._p20_market_cap_animation_timer.isActive(), 'Replay should start the animation timer')
        probe._p20_set_dot_metric('1d')
        _assert(not probe._p20_market_cap_animation_timer.isActive(), 'interval changes should stop Replay')
        _assert(probe._p20_market_cap_animation_entries == [], 'interval changes should clear playback state')

        probe._p20_replay_market_cap_animation()
        probe._p20_on_hide()
        _assert(not probe._p20_market_cap_animation_timer.isActive(), 'page hide should stop Replay')
        _assert_close(probe._p20_market_cap_animation_frame_points[0][1], 1_000.0, 'page hide should restore current caps')

        cached_rows = probe._p20_snapshot_rows(rows)
        _assert('market_cap_estimate_history' not in cached_rows[0], 'daily histories should stay out of the session snapshot')
        _assert(cached_rows[0].get('three_year_avg_dollar_volume') == 80.0, 'snapshot should retain 3Y ADV')
        _assert(cached_rows[0].get('three_year_price_return_pct') == 100.0, 'snapshot should retain 3Y return')
        probe._p20_render_dot_plot(cached_rows)
        _assert(not probe.p20_market_cap_replay_btn.isEnabled(), 'cached rows without history should disable Replay')
    finally:
        probe._p20_market_cap_animation_timer.stop()
        probe.p20_dot_plot.close()
        probe.close()
        app.processEvents()


def test_three_year_replay_uses_exact_calendar_window() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _TradingVolumesAnimationProbe()
    probe._p20_dot_metric = '3y'
    rows = [{
        'ticker': 'AAA',
        'market_cap': 1_000.0,
        'three_year_avg_dollar_volume': 100.0,
        'three_year_price_return_pct': 25.0,
        'market_cap_estimate_history': [
            {'date': '2023-07-24', 'value': 400.0},
            {'date': '2023-07-25', 'value': 500.0},
            {'date': '2025-01-01', 'value': 750.0},
            {'date': '2026-07-25', 'value': 1_000.0},
        ],
    }]
    probe._p20_trading_volume_rows = rows

    try:
        history = probe._p20_interval_market_cap_history(rows[0], '3y')
        _assert([point[0].isoformat() for point in history] == ['2023-07-25', '2025-01-01', '2026-07-25'], '3Y replay should exclude history before the exact calendar cutoff')

        probe._p20_render_dot_plot(rows)
        probe._p20_replay_market_cap_animation()
        probe._p20_market_cap_animation_timer.stop()
        _assert(probe._p20_market_cap_animation_dates[0].isoformat() == '2023-07-25', '3Y replay should begin exactly three years before the latest observation')
        probe._p20_apply_market_cap_animation_frame(0.0)
        _assert_close(probe._p20_market_cap_animation_frame_points[0][0], 100.0, '3Y replay should keep 3Y ADV fixed on X')
        _assert_close(probe._p20_market_cap_animation_frame_points[0][1], 500.0, '3Y replay should begin at the cutoff market cap')
        probe._p20_apply_market_cap_animation_frame(1.0)
        _assert_close(probe._p20_market_cap_animation_frame_points[0][1], 1_000.0, '3Y replay should finish at current market cap')
    finally:
        probe._p20_market_cap_animation_timer.stop()
        probe.p20_dot_plot.close()
        probe.close()
        app.processEvents()


def test_trading_volumes_page_initializes_replay_controls_and_cleanup() -> None:
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window._ensure_page_initialized(19)
        app.processEvents()
        _assert(window.p20_market_cap_replay_btn.text() == 'Replay', 'Trading Volumes should expose the Replay button')
        _assert('3y' in window.p20_dot_metric_buttons, 'Trading Volumes should expose the 3Y selector')
        _assert(window.p20_dot_metric_buttons['3y'].text() == '3Y', '3Y selector should use the requested label')
        _assert(window.p20_trading_volume_table.columnCount() == 10, 'Trading Volumes should include the 3Y ADV column')
        _assert(not window.p20_market_cap_replay_btn.isEnabled(), 'Replay should begin disabled without live history')
        _assert(window._p20_market_cap_animation_timer.interval() == _P20_MARKET_CAP_ANIMATION_FRAME_MS, 'page timer should target approximately 30 FPS')
        _assert(window._pages[19].get('on_hide') is not None, 'Trading Volumes should register page-hide cleanup')
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
        if 'window' in locals():
            window.close()
            window.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    test_market_cap_replay_moves_y_only_and_restores_current_values()
    test_three_year_replay_uses_exact_calendar_window()
    test_trading_volumes_page_initializes_replay_controls_and_cleanup()
    print('Trading Volumes market-cap animation smoke passed.')
