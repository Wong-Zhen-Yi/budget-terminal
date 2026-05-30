from __future__ import annotations

import os
import sys
from collections import namedtuple
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.charts_page import ChartsPageMixin
from budget_terminal_app.persistence import _normalize_chart_page_settings, _normalize_indicator_list


Row = namedtuple('Row', 'Open High Low Close Volume')


class _ChartHarness(ChartsPageMixin):
    def __init__(self, rows: list[Row]) -> None:
        self._p10_chart_rows = rows
        self.p10_symbol = 'SPY'
        self.p10_timeframe_label = '1 Day'
        self.p10_fib_mode = 'auto'
        self.p10_fib_lookback = 120
        self.p10_fib_manual_by_context = {}


def _row(low: float, high: float, close: float | None=None) -> Row:
    close_value = close if close is not None else (low + high) / 2.0
    return Row(Open=close_value, High=high, Low=low, Close=close_value, Volume=1000)


def _level_price(fib: dict, label: str) -> float:
    for level in fib['levels']:
        if level['label'] == label:
            return float(level['price'])
    raise AssertionError(f'Missing Fibonacci level {label}')


def _assert_close(actual: float, expected: float, message: str) -> None:
    if abs(float(actual) - float(expected)) > 0.000001:
        raise AssertionError(f'{message}: expected {expected}, got {actual}')


def test_upswing_recent_window() -> None:
    chart = _ChartHarness([
        _row(100, 108),
        _row(90, 96),
        _row(110, 130),
        _row(125, 150),
    ])

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'upswing data should produce Fibonacci levels'
    assert fib['direction'] == 'up', 'low before high should be treated as an upswing'
    _assert_close(_level_price(fib, '0%'), 150.0, 'upswing 0% should equal swing high')
    _assert_close(_level_price(fib, '100%'), 90.0, 'upswing 100% should equal swing low')
    level_618 = _level_price(fib, '61.8%')
    assert 90.0 < level_618 < 150.0, 'upswing 61.8% should sit between low and high'


def test_downswing_recent_window() -> None:
    chart = _ChartHarness([
        _row(140, 150),
        _row(125, 132),
        _row(90, 100),
        _row(95, 105),
    ])

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'downswing data should produce Fibonacci levels'
    assert fib['direction'] == 'down', 'high before low should be treated as a downswing'
    _assert_close(_level_price(fib, '0%'), 90.0, 'downswing 0% should equal swing low')
    _assert_close(_level_price(fib, '100%'), 150.0, 'downswing 100% should equal swing high')


def test_lookback_ignores_older_extremes() -> None:
    rows = [_row(1, 1000) for _ in range(10)]
    rows.extend(_row(80 + index, 86 + index) for index in range(120))
    chart = _ChartHarness(rows)

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'lookback window should produce Fibonacci levels'
    assert fib['low']['index'] == 10, 'lookback should ignore older low outside the last 120 candles'
    assert fib['high']['index'] == 129, 'lookback should ignore older high outside the last 120 candles'
    _assert_close(fib['low']['price'], 80.0, 'lookback low should come from first retained candle')
    _assert_close(fib['high']['price'], 205.0, 'lookback high should come from final retained candle')


def test_playback_row_limit() -> None:
    rows = [_row(100, 105) for _ in range(150)]
    rows[20] = _row(80, 90)
    rows[50] = _row(110, 120)
    rows[100] = _row(1, 1000)
    chart = _ChartHarness(rows)

    fib = chart._p10_calculate_fib_retracement(row_limit=80)

    assert fib is not None, 'playback-limited rows should produce Fibonacci levels'
    assert fib['low']['index'] == 20, 'playback low should ignore candles after row_limit'
    assert fib['high']['index'] == 50, 'playback high should ignore candles after row_limit'
    _assert_close(fib['low']['price'], 80.0, 'playback low should use visible playback rows')
    _assert_close(fib['high']['price'], 120.0, 'playback high should use visible playback rows')


def test_custom_auto_lookback() -> None:
    rows = [_row(1, 1000) for _ in range(30)]
    rows.extend(_row(80 + index, 86 + index) for index in range(40))
    chart = _ChartHarness(rows)
    chart.p10_fib_lookback = 40

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'custom lookback should produce Fibonacci levels'
    assert fib['low']['index'] == 30, 'custom lookback should ignore older lows'
    assert fib['high']['index'] == 69, 'custom lookback should ignore older highs'


def test_set_fib_lookback_clamps() -> None:
    chart = _ChartHarness([_row(90, 100), _row(105, 120)])

    chart._p10_set_fib_lookback(5, persist=False, refresh=False)
    assert chart.p10_fib_lookback == 20, 'lookback helper should clamp to minimum'

    chart._p10_set_fib_lookback(999, persist=False, refresh=False)
    assert chart.p10_fib_lookback == 500, 'lookback helper should clamp to maximum'


def test_manual_upswing() -> None:
    chart = _ChartHarness([_row(90, 100), _row(105, 120), _row(130, 150)])
    chart.p10_fib_mode = 'manual'
    chart.p10_fib_manual_by_context = {
        'SPY|1 Day': {
            'start_index': 0,
            'start_price': 90.0,
            'start_role': 'low',
            'end_index': 2,
            'end_price': 150.0,
            'end_role': 'high',
        }
    }

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'manual upswing should produce Fibonacci levels'
    assert fib['direction'] == 'up', 'manual end above start should be an upswing'
    _assert_close(_level_price(fib, '0%'), 150.0, 'manual upswing 0% should equal end anchor')
    _assert_close(_level_price(fib, '100%'), 90.0, 'manual upswing 100% should equal start anchor')


def test_manual_downswing() -> None:
    chart = _ChartHarness([_row(140, 150), _row(105, 120), _row(80, 90)])
    chart.p10_fib_mode = 'manual'
    chart.p10_fib_manual_by_context = {
        'SPY|1 Day': {
            'start_index': 0,
            'start_price': 150.0,
            'start_role': 'high',
            'end_index': 2,
            'end_price': 80.0,
            'end_role': 'low',
        }
    }

    fib = chart._p10_calculate_fib_retracement()

    assert fib is not None, 'manual downswing should produce Fibonacci levels'
    assert fib['direction'] == 'down', 'manual end below start should be a downswing'
    _assert_close(_level_price(fib, '0%'), 80.0, 'manual downswing 0% should equal end anchor')
    _assert_close(_level_price(fib, '100%'), 150.0, 'manual downswing 100% should equal start anchor')


def test_manual_invalid_and_playback_hidden() -> None:
    chart = _ChartHarness([_row(90, 100), _row(105, 120), _row(130, 150)])
    chart.p10_fib_mode = 'manual'
    chart.p10_fib_manual_by_context = {
        'SPY|1 Day': {
            'start_index': 0,
            'start_price': 100.0,
            'start_role': 'high',
            'end_index': 1,
            'end_price': 100.0,
            'end_role': 'low',
        }
    }
    assert chart._p10_calculate_fib_retracement() is None, 'equal-price manual anchors should be rejected'

    chart.p10_fib_manual_by_context['SPY|1 Day'] = {
        'start_index': 0,
        'start_price': 90.0,
        'start_role': 'low',
        'end_index': 2,
        'end_price': 150.0,
        'end_role': 'high',
    }
    assert chart._p10_calculate_fib_retracement(row_limit=2) is None, 'playback should hide anchors ahead of the frame'


def test_manual_context_keying() -> None:
    chart = _ChartHarness([_row(90, 100), _row(105, 120), _row(130, 150)])
    chart.p10_fib_mode = 'manual'
    chart.p10_fib_manual_by_context = {
        'SPY|1 Week': {
            'start_index': 0,
            'start_price': 90.0,
            'start_role': 'low',
            'end_index': 2,
            'end_price': 150.0,
            'end_role': 'high',
        },
        'QQQ|1 Day': {
            'start_index': 0,
            'start_price': 90.0,
            'start_role': 'low',
            'end_index': 2,
            'end_price': 150.0,
            'end_role': 'high',
        },
    }
    assert chart._p10_calculate_fib_retracement() is None, 'manual anchors should not leak across context keys'


def test_manual_anchor_update_helper() -> None:
    chart = _ChartHarness([_row(90, 100), _row(105, 120), _row(130, 150)])
    chart.p10_fib_manual_by_context = {
        'SPY|1 Day': {
            'start_index': 0,
            'start_price': 90.0,
            'start_role': 'low',
            'end_index': 2,
            'end_price': 150.0,
            'end_role': 'high',
        },
        'QQQ|1 Day': {
            'start_index': 0,
            'start_price': 50.0,
            'start_role': 'low',
            'end_index': 2,
            'end_price': 80.0,
            'end_role': 'high',
        },
    }

    assert chart._p10_update_manual_fib_anchor('start', {'index': 1, 'price': 105.0, 'role': 'low'}), 'start anchor drag should persist'
    spy_anchor = chart.p10_fib_manual_by_context['SPY|1 Day']
    assert spy_anchor['start_index'] == 1, 'start index should update'
    assert spy_anchor['start_price'] == 105.0, 'start price should update'
    assert spy_anchor['end_index'] == 2, 'end index should stay unchanged'
    assert chart.p10_fib_manual_by_context['QQQ|1 Day']['start_price'] == 50.0, 'other contexts should not change'

    assert chart._p10_update_manual_fib_anchor('end', {'index': 2, 'price': 130.0, 'role': 'low'}), 'end anchor drag should persist'
    spy_anchor = chart.p10_fib_manual_by_context['SPY|1 Day']
    assert spy_anchor['end_price'] == 130.0, 'end price should update'
    assert spy_anchor['start_price'] == 105.0, 'start price should stay unchanged after end drag'

    assert not chart._p10_update_manual_fib_anchor('end', {'index': 1, 'price': 105.0, 'role': 'low'}), 'equal-price drag should be rejected'
    assert chart.p10_fib_manual_by_context['SPY|1 Day']['end_price'] == 130.0, 'rejected drag should not alter saved anchor'


def test_invalid_or_flat_data_returns_none() -> None:
    assert _ChartHarness([])._p10_calculate_fib_retracement() is None, 'empty data should not produce levels'
    assert _ChartHarness([_row(100, 105)])._p10_calculate_fib_retracement() is None, 'one row should not produce levels'
    assert _ChartHarness([_row(100, 100), _row(100, 100)])._p10_calculate_fib_retracement() is None, 'flat data should not produce levels'


def test_indicator_normalization_accepts_fibonacci_aliases() -> None:
    normalized = _normalize_indicator_list(
        ['Volume', 'Fibonacci', 'Auto Fibonacci', 'Fib Retracement'],
        ['Volume'],
    )

    assert normalized == ['Volume', 'Fib Retracement'], 'Fibonacci aliases should normalize once in canonical order'


def test_fib_settings_normalization() -> None:
    defaults = _normalize_chart_page_settings({})['fib_settings']
    assert defaults == {'mode': 'auto', 'lookback': 120, 'manual_by_context': {}}, 'missing fib settings should normalize to defaults'

    low = _normalize_chart_page_settings({'fib_settings': {'lookback': 5}})['fib_settings']
    high = _normalize_chart_page_settings({'fib_settings': {'lookback': 999}})['fib_settings']
    assert low['lookback'] == 20, 'lookback should clamp to minimum'
    assert high['lookback'] == 500, 'lookback should clamp to maximum'

    normalized = _normalize_chart_page_settings({
        'fib_settings': {
            'mode': 'manual',
            'lookback': 64,
            'manual_by_context': {
                'spy|1 Day': {
                    'start_index': 1,
                    'start_price': 100.0,
                    'start_role': 'low',
                    'end_index': 2,
                    'end_price': 120.0,
                    'end_role': 'high',
                },
                'BAD': {
                    'start_index': 0,
                    'start_price': 1.0,
                    'start_role': 'low',
                    'end_index': 1,
                    'end_price': 2.0,
                    'end_role': 'high',
                },
                'QQQ|1 Day': {
                    'start_index': -1,
                    'start_price': 1.0,
                    'start_role': 'low',
                    'end_index': 1,
                    'end_price': 2.0,
                    'end_role': 'high',
                },
            },
        }
    })['fib_settings']
    assert normalized['mode'] == 'manual', 'manual mode should persist'
    assert normalized['lookback'] == 64, 'valid lookback should persist'
    assert list(normalized['manual_by_context']) == ['SPY|1 Day'], 'malformed manual anchors should be dropped'


def test_offscreen_charts_fib_controls_initialization() -> None:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.mixins.charts_page import P10_FIB_RETRACEMENT_LABEL
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    app = QApplication([])
    try:
        window = BudgetTerminalApp()
        window.chart_page_state = _normalize_chart_page_settings({})
        window._ensure_page_initialized(9)
        app.processEvents()
        assert hasattr(window, 'p10_fib_auto_btn'), 'Fib Auto control should initialize'
        assert hasattr(window, 'p10_fib_manual_btn'), 'Fib Manual control should initialize'
        assert hasattr(window, 'p10_fib_lookback_spin'), 'Fib Lookback control should initialize'
        assert hasattr(window, 'p10_fib_lookback_slider'), 'Fib Lookback slider should initialize'
        assert window.p10_fib_mode == 'auto', 'Fib mode should default to Auto'
        assert window.p10_fib_lookback_spin.value() == 120, 'Fib lookback should default to 120'
        assert window.p10_fib_lookback_slider.value() == 120, 'Fib slider should default to 120'
        assert P10_FIB_RETRACEMENT_LABEL not in window.p10_active_indicators, 'Fib should remain off by default'

        window.p10_active_indicators = [P10_FIB_RETRACEMENT_LABEL]
        window.p10_fib_mode = 'manual'
        window._p10_chart_rows = [_row(90, 100), _row(105, 120), _row(130, 150)]
        window._p10_playback_index = len(window._p10_chart_rows) - 1
        window.p10_fib_manual_by_context = {
            'SPY|1 Day': {
                'start_index': 0,
                'start_price': 90.0,
                'start_role': 'low',
                'end_index': 2,
                'end_price': 150.0,
                'end_role': 'high',
            }
        }
        window._p10_refresh_fib_retracement()
        assert window.p10_fib_start_handle is not None, 'manual Fib should render a Start handle'
        assert window.p10_fib_end_handle is not None, 'manual Fib should render an End handle'
        assert getattr(window.p10_fib_start_handle, 'movable', False), 'Start handle should be draggable'
        assert getattr(window.p10_fib_end_handle, 'movable', False), 'End handle should be draggable'
        window.close()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
        app.quit()


if __name__ == '__main__':
    test_upswing_recent_window()
    test_downswing_recent_window()
    test_lookback_ignores_older_extremes()
    test_playback_row_limit()
    test_custom_auto_lookback()
    test_set_fib_lookback_clamps()
    test_manual_upswing()
    test_manual_downswing()
    test_manual_invalid_and_playback_hidden()
    test_manual_context_keying()
    test_manual_anchor_update_helper()
    test_invalid_or_flat_data_returns_none()
    test_indicator_normalization_accepts_fibonacci_aliases()
    test_fib_settings_normalization()
    test_offscreen_charts_fib_controls_initialization()
    print('charts fibonacci tests passed')
