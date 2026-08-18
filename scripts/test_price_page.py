from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pyqtgraph as pg

from budget_terminal_app.compat import QApplication, QWidget
from budget_terminal_app.mixins.price_page import PricePageMixin
from budget_terminal_app.workers.price_screen import PriceScreenWorker


def _quote(
    symbol: str,
    *,
    price: float = 150.0,
    market_cap: float = 1_000_000_000.0,
    exchange: str = 'NYQ',
    quote_type: str = 'EQUITY',
) -> dict[str, object]:
    return {
        'symbol': symbol,
        'shortName': f'{symbol} Company',
        'regularMarketPrice': price,
        'marketCap': market_cap,
        'exchange': exchange,
        'quoteType': quote_type,
    }


def test_worker_query_and_normalization() -> None:
    worker = PriceScreenWorker(100, 200)
    query = worker._query().to_dict()
    assert query['operator'] == 'AND'
    assert {'operator': 'GTE', 'operands': ['intradayprice', 100.0]} in query['operands']
    assert {'operator': 'LTE', 'operands': ['intradayprice', 200.0]} in query['operands']
    exchange_operand = next(item for item in query['operands'] if item['operator'] == 'OR')
    assert {item['operands'][1] for item in exchange_operand['operands']} == {'NYQ', 'NMS', 'NGM', 'NCM', 'ASE'}

    assert worker._row_from_quote(_quote('NYSE'))['exchange'] == 'NYSE'
    assert worker._row_from_quote(_quote('NASDAQ', exchange='NMS'))['exchange'] == 'Nasdaq'
    assert worker._row_from_quote(_quote('AMEX', exchange='ASE'))['exchange'] == 'NYSE American'
    assert worker._row_from_quote(_quote('ETF', quote_type='ETF')) is None
    assert worker._row_from_quote(_quote('OTC', exchange='PNK')) is None
    assert worker._row_from_quote(_quote('LOW', price=99.99)) is None
    assert worker._row_from_quote(_quote('HIGH', price=200.01)) is None
    assert worker._row_from_quote(_quote('NOCAP', market_cap=0)) is None
    assert worker._row_from_quote(_quote('MIN', price=100.0)) is not None
    assert worker._row_from_quote(_quote('MAX', price=200.0)) is not None


def test_worker_paginates_deduplicates_and_keeps_largest_market_caps() -> None:
    worker = PriceScreenWorker(100, 200, limit=2)
    worker._PAGE_SIZE = 3
    pages = {
        0: {
            'total': 6,
            'quotes': [
                _quote('AAA', market_cap=10_000_000_000),
                _quote('FUND', market_cap=50_000_000_000, quote_type='ETF'),
                _quote('OTC', market_cap=40_000_000_000, exchange='PNK'),
            ],
        },
        3: {
            'total': 6,
            'quotes': [
                _quote('BBB', market_cap=9_000_000_000),
                _quote('CCC', market_cap=8_000_000_000),
                _quote('AAA', market_cap=7_000_000_000),
            ],
        },
    }
    with patch.object(worker, '_screen_page', side_effect=lambda query, offset: pages[offset]) as screen_page:
        payload = worker.fetch()

    assert screen_page.call_count == 2
    assert payload['candidate_count'] == 6
    assert [row['ticker'] for row in payload['rows']] == ['AAA', 'BBB']
    assert payload['rows'][0]['market_cap'] == 10_000_000_000


def test_worker_caps_results_at_top_100() -> None:
    worker = PriceScreenWorker(100, 200, limit=100)
    quotes = [
        _quote(f'T{index:03d}', price=100 + index / 10, market_cap=(120 - index) * 1_000_000)
        for index in range(120)
    ]
    with patch.object(worker, '_screen_page', return_value={'total': 120, 'quotes': quotes}):
        rows = worker.fetch()['rows']
    assert len(rows) == 100
    assert rows[0]['ticker'] == 'T000'
    assert rows[-1]['ticker'] == 'T099'
    assert rows == sorted(rows, key=lambda row: -float(row['market_cap']))


class _PricePageProbe(PricePageMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.page30 = QWidget()
        self.status_messages: list[str] = []
        self.init_page30()

    def set_theme_role(self, *args, **kwargs) -> None:
        return None

    def set_theme_variant(self, *args, **kwargs) -> None:
        return None

    def style_plot_widget(self, *args, **kwargs) -> None:
        return None

    def theme_brush(self, token: str):
        return pg.mkBrush('#4ea1ff')

    def theme_pen(self, token: str, *, width: float = 1.0, **kwargs):
        return pg.mkPen('#9aa4b2', width=width)

    def set_status_text(self, label, text, **kwargs) -> None:
        label.setText(str(text))
        self.status_messages.append(str(text))

    def _launch_worker(self, worker, finished_slot, flag_attr):
        setattr(self, flag_attr, True)
        return True


class _Point:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


def test_price_page_render_validation_hover_and_selection() -> None:
    app = QApplication.instance() or QApplication([])
    probe = _PricePageProbe()
    try:
        assert probe.p30_minimum_price_spin.value() == 100.0
        assert probe.p30_maximum_price_spin.value() == 200.0
        probe.p30_minimum_price_spin.setValue(201.0)
        probe.p30_maximum_price_spin.setValue(200.0)
        assert probe._p30_fetch() is False
        assert 'cannot exceed' in probe.p30_status_lbl.text()

        probe.p30_minimum_price_spin.setValue(100.0)
        rows = [
            {'ticker': 'BIG', 'name': 'Big Company', 'exchange': 'NYSE', 'price': 175.0, 'market_cap': 900_000_000_000},
            {'ticker': 'MID', 'name': 'Mid Company', 'exchange': 'Nasdaq', 'price': 125.0, 'market_cap': 50_000_000_000},
        ]
        probe._p30_on_ready({
            'rows': list(reversed(rows)),
            'candidate_count': 24,
            'source': 'Test',
            'as_of': '2026-07-14 10:00',
        })
        app.processEvents()

        assert probe.p30_table.rowCount() == 2
        assert probe.p30_table.item(0, 1).text() == 'BIG'
        assert probe.p30_table.item(0, 5).text() == '$900.00B'
        assert probe._p30_plot_points == [
            (175.0, math.log10(900_000_000_000), 'BIG'),
            (125.0, math.log10(50_000_000_000), 'MID'),
        ]
        assert [label.toPlainText() for label in probe._p30_label_items] == ['BIG', 'MID']
        tooltip = probe._p30_point_tooltip(rows[0])
        assert 'BIG — Big Company' in tooltip
        assert 'Price: $175.00' in tooltip
        assert 'Market Cap: $900.00B' in tooltip

        probe.p30_table.selectRow(1)
        app.processEvents()
        assert len(probe._p30_selection_scatter.points()) == 1
        probe._p30_on_scatter_clicked(None, [_Point(rows[0])])
        app.processEvents()
        selected_row = probe.p30_table.selectedRanges()[0].topRow()
        assert probe.p30_table.item(selected_row, 1).text() == 'BIG'

        probe._p30_on_ready({'rows': list(reversed(rows)), 'candidate_count': 24, 'source': 'Test'})
        app.processEvents()
        selected_row = probe.p30_table.selectedRanges()[0].topRow()
        assert probe.p30_table.item(selected_row, 1).text() == 'BIG'

        probe.p30_table.sortItems(4)
        assert probe.p30_table.item(0, 1).text() == 'MID'

        probe._p30_on_ready({'rows': [], 'candidate_count': 0})
        assert probe.p30_table.rowCount() == 0
        assert not probe.p30_plot_empty_lbl.isHidden()
        assert 'No qualifying' in probe.p30_status_lbl.text()
    finally:
        probe.page30.close()
        probe.close()
        app.processEvents()


if __name__ == '__main__':
    test_worker_query_and_normalization()
    test_worker_paginates_deduplicates_and_keeps_largest_market_caps()
    test_worker_caps_results_at_top_100()
    test_price_page_render_validation_hover_and_selection()
    print('Price page smoke passed.')
