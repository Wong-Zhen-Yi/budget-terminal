from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.compat import QApplication, QLabel, QTableWidget
from budget_terminal_app.mixins.overview import (
    _P20_DOT_TABLE_COLUMNS,
    _P20_FILTER_DEFAULT,
    _P20_FILTER_EXCLUDE,
    _P20_FILTER_ROW_RANGE,
    OverviewMixin,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _TradingVolumesProbe(OverviewMixin):
    def set_status_text(self, _: Any, text: Any, **__: Any) -> None:
        self.status_messages.append(str(text))

    def _p20_render_dot_plot(self, rows: list[dict[str, Any]]) -> None:
        self.rendered_dot_tickers = [str(row.get('ticker') or '') for row in rows]


def _build_probe() -> tuple[QApplication, _TradingVolumesProbe]:
    app = QApplication.instance() or QApplication([])
    probe = _TradingVolumesProbe()
    probe._p20_dot_metric = '1d'
    probe._p20_filter_mode = _P20_FILTER_DEFAULT
    probe._p20_exclude_top_count = 0
    probe._p20_row_range_start = 1
    probe._p20_row_range_end = 100
    probe._p20_trading_volume_rows = []
    probe._p20_trading_volume_source = 'Test Source'
    probe._p20_trading_volume_as_of = '2026-06-19 09:00'
    probe.status_messages = []
    probe.p20_status_lbl = QLabel()
    probe.p20_trading_volume_table = QTableWidget(0, 9)
    probe._p20_trading_volume_all_rows = [
        {
            'ticker': 'AAA',
            'name': 'Alpha',
            'market_cap': 1_000,
            'one_day_dollar_volume': 500,
            'five_day_avg_dollar_volume': 100,
            'thirty_day_avg_dollar_volume': 400,
            'ytd_avg_dollar_volume': None,
            'one_year_avg_dollar_volume': 200,
        },
        {
            'ticker': 'BBB',
            'name': 'Beta',
            'market_cap': 2_000,
            'one_day_dollar_volume': 400,
            'five_day_avg_dollar_volume': 500,
            'thirty_day_avg_dollar_volume': 300,
            'ytd_avg_dollar_volume': 100,
            'one_year_avg_dollar_volume': None,
        },
        {
            'ticker': 'CCC',
            'name': 'Gamma',
            'market_cap': 3_000,
            'one_day_dollar_volume': 300,
            'five_day_avg_dollar_volume': 400,
            'thirty_day_avg_dollar_volume': 500,
            'ytd_avg_dollar_volume': 300,
            'one_year_avg_dollar_volume': 100,
        },
        {
            'ticker': 'DDD',
            'name': 'Delta',
            'market_cap': 4_000,
            'one_day_dollar_volume': 200,
            'five_day_avg_dollar_volume': None,
            'thirty_day_avg_dollar_volume': None,
            'ytd_avg_dollar_volume': 200,
            'one_year_avg_dollar_volume': 400,
        },
    ]
    return app, probe


def _tickers(probe: _TradingVolumesProbe) -> list[str]:
    return [str(row.get('ticker') or '') for row in probe._p20_trading_volume_rows]


def _ranks(probe: _TradingVolumesProbe) -> list[int]:
    return [int(row.get('_p20_rank') or 0) for row in probe._p20_trading_volume_rows]


def _export_section_tickers(export_text: str, section_label: str) -> list[str]:
    marker = f'## {section_label} Trading Volumes'
    section = export_text.split(marker, 1)[1]
    section = section.split('\n## ', 1)[0]
    tickers: list[str] = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.split('|')]
        if len(cells) >= 4 and cells[1].isdigit():
            tickers.append(cells[2])
    return tickers


def _export_without_timestamp(export_text: str) -> str:
    return '\n'.join(line for line in export_text.splitlines() if not line.startswith('- Exported at:'))


def test_interval_selector_reranks_table_filters_and_dot_plot() -> None:
    app, probe = _build_probe()
    expected_orders = {
        '1d': ['AAA', 'BBB', 'CCC', 'DDD'],
        '5d': ['BBB', 'CCC', 'AAA', 'DDD'],
        '30d': ['CCC', 'AAA', 'BBB', 'DDD'],
        'ytd': ['CCC', 'DDD', 'BBB', 'AAA'],
        '1y': ['DDD', 'AAA', 'CCC', 'BBB'],
    }

    try:
        for metric_key, expected in expected_orders.items():
            probe._p20_filter_mode = _P20_FILTER_DEFAULT
            probe._p20_set_dot_metric(metric_key)
            _assert(_tickers(probe) == expected, f'{metric_key} should rank rows by its ADV values')
            _assert(_ranks(probe) == [1, 2, 3, 4], f'{metric_key} should recalculate sequential ranks')
            _assert(probe.rendered_dot_tickers == expected, f'{metric_key} dot plot should receive the ranked rows')
            _assert(
                probe.p20_trading_volume_table.horizontalHeader().sortIndicatorSection() == _P20_DOT_TABLE_COLUMNS[metric_key],
                f'{metric_key} should select its ADV table column for descending sort',
            )
            _assert(
                probe.p20_trading_volume_table.item(0, 1).text() == expected[0],
                f'{metric_key} table should display the highest-ranked ticker first',
            )

        probe._p20_dot_metric = '30d'
        probe._p20_filter_mode = _P20_FILTER_EXCLUDE
        probe._p20_exclude_top_count = 1
        probe._p20_apply_trading_volume_filter()
        _assert(_tickers(probe) == ['AAA', 'BBB', 'DDD'], 'exclude-top should use the active 30D ranking')
        _assert(_ranks(probe) == [2, 3, 4], 'exclude-top should preserve active ranking numbers')

        probe._p20_filter_mode = _P20_FILTER_ROW_RANGE
        probe._p20_row_range_start = 2
        probe._p20_row_range_end = 3
        probe._p20_apply_trading_volume_filter()
        _assert(_tickers(probe) == ['AAA', 'BBB'], 'row-range should use the active 30D ranking')
        _assert(_ranks(probe) == [2, 3], 'row-range should preserve active ranking numbers')
    finally:
        probe.p20_trading_volume_table.close()
        probe.p20_status_lbl.close()
        app.processEvents()


def test_llm_export_contains_all_unfiltered_interval_rankings() -> None:
    app, probe = _build_probe()
    expected_orders = {
        '1D': ['AAA', 'BBB', 'CCC', 'DDD'],
        '5D': ['BBB', 'CCC', 'AAA', 'DDD'],
        '30D': ['CCC', 'AAA', 'BBB', 'DDD'],
        'YTD': ['CCC', 'DDD', 'BBB', 'AAA'],
        '1Y': ['DDD', 'AAA', 'CCC', 'BBB'],
    }

    try:
        probe._p20_dot_metric = '30d'
        probe._p20_filter_mode = _P20_FILTER_ROW_RANGE
        probe._p20_row_range_start = 2
        probe._p20_row_range_end = 2
        probe._p20_apply_trading_volume_filter()
        _assert(_tickers(probe) == ['AAA'], 'test setup should display only one active-interval row')

        probe._p20_export_trading_volume_for_llm()
        export_text = QApplication.clipboard().text()

        heading_positions = [export_text.index(f'## {label} Trading Volumes') for label in expected_orders]
        _assert(heading_positions == sorted(heading_positions), 'export sections should follow selector order')
        for label, expected in expected_orders.items():
            _assert(export_text.count(f'## {label} Trading Volumes') == 1, f'{label} section should appear once')
            _assert(_export_section_tickers(export_text, label) == expected, f'{label} section should have independent ranks')

        _assert('- Page modifiers: Ignored' in export_text, 'export metadata should disclose that filters are ignored')
        _assert('- Stocks exported per interval: 4' in export_text, 'export should include every loaded stock per interval')
        _assert('| 4 | DDD | Delta | N/A | $4,000 | N/A |' in export_text, 'missing 5D values should rank last as N/A')
        _assert(
            any('4 stocks across 5 trading-volume intervals' in message for message in probe.status_messages),
            'success status should summarize stocks and intervals',
        )

        probe._p20_dot_metric = '1y'
        probe._p20_export_trading_volume_for_llm()
        _assert(
            _export_without_timestamp(QApplication.clipboard().text()) == _export_without_timestamp(export_text),
            'active selector should not change the all-interval export',
        )
    finally:
        probe.p20_trading_volume_table.close()
        probe.p20_status_lbl.close()
        app.processEvents()


if __name__ == '__main__':
    test_interval_selector_reranks_table_filters_and_dot_plot()
    test_llm_export_contains_all_unfiltered_interval_rankings()
    print('Trading Volumes interval-sync smoke passed.')
