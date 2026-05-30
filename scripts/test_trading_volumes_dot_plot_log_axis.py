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

from budget_terminal_app.compat import QApplication, QLabel
from budget_terminal_app.mixins.overview import _P20CompactCurrencyAxisItem, OverviewMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _axis_label(plot: pg.PlotWidget, axis_name: str) -> str:
    axis = plot.getPlotItem().getAxis(axis_name)
    return str(getattr(axis, 'labelText', '') or '').strip()


class _TradingVolumesProbe(OverviewMixin):
    pass


def _build_probe() -> tuple[QApplication, _TradingVolumesProbe]:
    app = QApplication.instance() or QApplication([])
    probe = _TradingVolumesProbe()
    probe._p20_dot_metric = '1d'
    probe._p20_dot_plot_points = []
    probe._p20_dot_plot_log_points = []
    probe._p20_dot_label_items = []
    probe.p20_dot_empty_lbl = QLabel()
    probe.p20_dot_plot = pg.PlotWidget(axisItems={
        'bottom': _P20CompactCurrencyAxisItem(orientation='bottom', log_values=True),
        'left': _P20CompactCurrencyAxisItem(orientation='left', log_values=True),
    })
    return app, probe


def test_trading_volumes_dot_plot_uses_log_adv_x_and_market_cap_y() -> None:
    app, probe = _build_probe()
    rows: list[dict[str, Any]] = [
        {
            'ticker': 'AAA',
            'market_cap': 1_000_000_000_000,
            'one_day_dollar_volume': 1_000_000_000,
            'five_day_avg_dollar_volume': 2_000_000_000,
        },
        {
            'ticker': 'BBB',
            'market_cap': 100_000_000_000,
            'one_day_dollar_volume': 10_000_000_000,
            'five_day_avg_dollar_volume': 20_000_000_000,
        },
        {'ticker': 'ZERO', 'market_cap': 0, 'one_day_dollar_volume': 5_000_000_000},
        {'ticker': 'NEG', 'market_cap': 10_000_000_000, 'one_day_dollar_volume': -1},
        {'ticker': 'MISS', 'market_cap': None, 'one_day_dollar_volume': 5_000_000_000},
    ]

    try:
        probe._p20_render_dot_plot(rows)

        _assert(_axis_label(probe.p20_dot_plot, 'bottom') == '1D ADV ($)', 'bottom axis should show active ADV metric')
        _assert(_axis_label(probe.p20_dot_plot, 'left') == 'Market Cap', 'left axis should show Market Cap')
        _assert(
            probe._p20_dot_plot_points == [
                (1_000_000_000, 1_000_000_000_000, 'AAA'),
                (10_000_000_000, 100_000_000_000, 'BBB'),
            ],
            'raw dot points should store ADV X, Market Cap Y, and ticker',
        )
        expected_logs = [
            (math.log10(1_000_000_000), math.log10(1_000_000_000_000), 'AAA'),
            (math.log10(10_000_000_000), math.log10(100_000_000_000), 'BBB'),
        ]
        for actual, expected in zip(probe._p20_dot_plot_log_points, expected_logs):
            _assert(
                math.isclose(actual[0], expected[0]) and math.isclose(actual[1], expected[1]) and actual[2] == expected[2],
                'plotted coordinates should be log10-transformed raw values',
            )
        _assert(len(probe._p20_dot_label_items) == 2, 'ticker labels should be kept for valid points')

        probe._p20_dot_metric = '5d'
        probe._p20_render_dot_plot(rows)
        _assert(_axis_label(probe.p20_dot_plot, 'bottom') == '5D ADV ($)', 'bottom axis should update with metric')
        _assert(probe._p20_dot_plot_points[0] == (2_000_000_000, 1_000_000_000_000, 'AAA'), '5D metric should drive X values')

        labels = _P20CompactCurrencyAxisItem(orientation='bottom', log_values=True).tickStrings([9, 10, 12], 1, 1)
        _assert(labels == ['$1.0B', '$10.0B', '$1.0T'], 'log-space axis ticks should render compact raw currency')
    finally:
        probe.p20_dot_plot.close()
        app.processEvents()


if __name__ == '__main__':
    test_trading_volumes_dot_plot_uses_log_adv_x_and_market_cap_y()
    print('Trading Volumes dot plot log-axis smoke passed.')
