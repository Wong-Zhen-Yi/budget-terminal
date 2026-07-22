from __future__ import annotations

import datetime
import math
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.workers.overview import TradingVolumeWorker


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_close(actual: float | None, expected: float, message: str) -> None:
    _assert(actual is not None and math.isclose(actual, expected, rel_tol=1e-9), message)


def test_quote_rows_include_one_day_price_return() -> None:
    worker = TradingVolumeWorker()
    rows = worker._rows_from_quotes([
        {
            'quoteType': 'EQUITY',
            'symbol': 'AAA',
            'regularMarketPrice': 110.0,
            'regularMarketPreviousClose': 100.0,
            'regularMarketVolume': 1_000_000,
        },
        {
            'quoteType': 'EQUITY',
            'symbol': 'MISS',
            'regularMarketPrice': 50.0,
            'regularMarketVolume': 1_000_000,
        },
    ])

    _assert_close(rows[0].get('one_day_price_return_pct'), 10.0, 'quote 1D return should use previous close')
    _assert(rows[1].get('one_day_price_return_pct') is None, 'missing previous close should produce missing 1D return')


def test_history_metrics_include_interval_price_returns() -> None:
    worker = TradingVolumeWorker()
    start = datetime.date.today().replace(month=1, day=1)
    dates = pd.date_range(start, periods=40, freq='D')
    closes = [100.0] * 40
    closes[9] = 80.0
    closes[34] = 150.0
    closes[38] = 130.0
    closes[39] = 120.0
    frame = pd.DataFrame({'Close': closes, 'Volume': [1_000_000] * 40}, index=dates)

    metrics = worker._dollar_volume_metrics(frame)

    _assert_close(metrics.get('one_day_price_return_pct'), ((120.0 / 130.0) - 1.0) * 100.0, '1D return should use latest two closes')
    _assert_close(metrics.get('five_day_price_return_pct'), -20.0, '5D return should use the close five sessions back')
    _assert_close(metrics.get('thirty_day_price_return_pct'), 50.0, '30D return should use the close thirty sessions back')
    _assert_close(metrics.get('ytd_price_return_pct'), 20.0, 'YTD return should use first current-year close')
    _assert_close(metrics.get('one_year_price_return_pct'), 20.0, '1Y return should use first close in the one-year window')

    flat_frame = pd.DataFrame({'Close': [100.0, 100.0], 'Volume': [1_000_000, 1_000_000]}, index=pd.date_range(start, periods=2, freq='D'))
    flat_metrics = worker._dollar_volume_metrics(flat_frame)
    _assert_close(flat_metrics.get('one_day_price_return_pct'), 0.0, 'flat return should stay zero for neutral dot coloring')

    short_frame = pd.DataFrame({'Close': [100.0], 'Volume': [1_000_000]}, index=pd.date_range(start, periods=1, freq='D'))
    short_metrics = worker._dollar_volume_metrics(short_frame)
    _assert(short_metrics.get('one_day_price_return_pct') is None, 'insufficient history should not fabricate a trailing return')
    _assert(worker._price_return_pct(None, 100.0) is None, 'missing start price should produce missing return')
    _assert(worker._price_return_pct(100.0, 0.0) is None, 'non-positive end price should produce missing return')


if __name__ == '__main__':
    test_quote_rows_include_one_day_price_return()
    test_history_metrics_include_interval_price_returns()
    print('Trading volume worker return smoke passed.')
