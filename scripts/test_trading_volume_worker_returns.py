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
from budget_terminal_app.workers import overview as overview_worker_module
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
    _assert(rows[0].get('market_cap_estimate_history') == [], 'quote rows should initialize live-only market-cap history')


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
    _assert_close(metrics.get('three_year_price_return_pct'), 20.0, '3Y return should use first close in the three-year window')

    flat_frame = pd.DataFrame({'Close': [100.0, 100.0], 'Volume': [1_000_000, 1_000_000]}, index=pd.date_range(start, periods=2, freq='D'))
    flat_metrics = worker._dollar_volume_metrics(flat_frame)
    _assert_close(flat_metrics.get('one_day_price_return_pct'), 0.0, 'flat return should stay zero for neutral dot coloring')

    short_frame = pd.DataFrame({'Close': [100.0], 'Volume': [1_000_000]}, index=pd.date_range(start, periods=1, freq='D'))
    short_metrics = worker._dollar_volume_metrics(short_frame)
    _assert(short_metrics.get('one_day_price_return_pct') is None, 'insufficient history should not fabricate a trailing return')
    _assert(worker._price_return_pct(None, 100.0) is None, 'missing start price should produce missing return')
    _assert(worker._price_return_pct(100.0, 0.0) is None, 'non-positive end price should produce missing return')


def test_three_year_metrics_use_exact_calendar_window() -> None:
    worker = TradingVolumeWorker()
    today = pd.Timestamp(datetime.date.today())
    cutoff = today - pd.DateOffset(years=3)
    frame = pd.DataFrame(
        {
            'Close': [50.0, 100.0, 150.0],
            'Volume': [10.0, 20.0, 30.0],
        },
        index=pd.DatetimeIndex([cutoff - pd.Timedelta(days=1), cutoff, today]),
    )

    metrics = worker._dollar_volume_metrics(frame)

    _assert_close(metrics.get('three_year_avg_dollar_volume'), 3_250.0, '3Y ADV should exclude observations before the calendar cutoff')
    _assert_close(metrics.get('three_year_price_return_pct'), 50.0, '3Y return should start at the first close on the calendar cutoff')


def test_history_download_uses_exact_three_year_start() -> None:
    worker = TradingVolumeWorker()
    today = pd.Timestamp(datetime.date.today())
    cutoff = today - pd.DateOffset(years=3)
    frame = pd.DataFrame(
        {'Close': [100.0, 120.0], 'Volume': [1_000.0, 1_500.0]},
        index=pd.DatetimeIndex([cutoff, today]),
    )
    captured: dict[str, object] = {}
    original_download = overview_worker_module.yf.download

    def fake_download(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return frame

    overview_worker_module.yf.download = fake_download
    row = {'ticker': 'AAA', 'market_cap': 1_000_000.0}
    try:
        worker._merge_trading_volume_history([row])
    finally:
        overview_worker_module.yf.download = original_download

    _assert(captured.get('start') == cutoff.date(), 'history download should start exactly three calendar years ago')
    _assert('period' not in captured, 'history download should not use an unsupported 3Y period string')
    _assert_close(row.get('three_year_price_return_pct'), 20.0, 'downloaded history should populate the 3Y return')
    _assert(len(row.get('market_cap_estimate_history') or []) == 2, 'downloaded history should feed the 3Y replay path')


def test_market_cap_estimate_history_scales_to_current_cap() -> None:
    worker = TradingVolumeWorker()
    dates = pd.date_range('2026-07-20', periods=4, freq='D')
    frame = pd.DataFrame({'Close': [50.0, None, 75.0, 100.0]}, index=dates)

    history = worker._market_cap_estimate_history(frame, 2_000_000_000)

    _assert([point.get('date') for point in history] == ['2026-07-20', '2026-07-22', '2026-07-23'], 'history should keep ordered valid close dates')
    _assert_close(history[0].get('value'), 1_000_000_000, 'first estimate should scale from the latest close')
    _assert_close(history[1].get('value'), 1_500_000_000, 'intermediate estimate should scale from the latest close')
    _assert_close(history[-1].get('value'), 2_000_000_000, 'latest estimate should equal current market cap')
    _assert(worker._market_cap_estimate_history(frame, None) == [], 'missing current cap should disable estimated history')
    _assert(worker._market_cap_estimate_history(None, 2_000_000_000) == [], 'missing price history should return no estimates')


if __name__ == '__main__':
    test_quote_rows_include_one_day_price_return()
    test_history_metrics_include_interval_price_returns()
    test_three_year_metrics_use_exact_calendar_window()
    test_history_download_uses_exact_three_year_start()
    test_market_cap_estimate_history_scales_to_current_cap()
    print('Trading volume worker return smoke passed.')
