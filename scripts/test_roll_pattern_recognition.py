from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.workers.random_recommender import RandomStockWorker


PATTERN_MODES = (
    'breakout',
    'consolidation',
    'downtrend',
    'double_bottom',
    'bullish_flag',
    'bullish_rsi_divergence',
)

AFFIRMING_VOLUME_REASONS = {
    'constructive volume',
    'downside volume',
    'orderly volume',
    'volume accumulation',
    'volume controlled',
    'volume stabilizing',
}

AFFIRMING_VOLUME_STATES = {
    'accumulation',
    'constructive',
    'controlled',
    'downside participation',
    'orderly',
    'stabilizing',
}


def _interpolated_closes(length: int, anchors: dict[int, float]) -> list[float]:
    ordered = sorted(anchors.items())
    values = [0.0] * length
    for (start_index, start_value), (end_index, end_value) in zip(ordered, ordered[1:]):
        span = max(end_index - start_index, 1)
        for index in range(start_index, min(end_index, length - 1) + 1):
            progress = (index - start_index) / span
            values[index] = start_value + (end_value - start_value) * progress
    first_index, first_value = ordered[0]
    for index in range(0, min(first_index, length)):
        values[index] = first_value
    last_index, last_value = ordered[-1]
    for index in range(max(last_index, 0), length):
        values[index] = last_value
    return values


def _frame_from_anchors(length: int, anchors: dict[int, float]) -> pd.DataFrame:
    closes = _interpolated_closes(length, anchors)
    opens = []
    highs = []
    lows = []
    volumes = []
    for index, close_value in enumerate(closes):
        open_value = closes[index - 1] if index else close_value * 1.002
        opens.append(open_value)
        highs.append(max(open_value, close_value) * 1.012)
        lows.append(min(open_value, close_value) * 0.988)
        volumes.append(1_000_000 + index * 2_000 + (150_000 if close_value >= open_value else 0))
    return pd.DataFrame({
        'Open': opens,
        'High': highs,
        'Low': lows,
        'Close': closes,
        'Volume': volumes,
    })


def _breakout_frame() -> pd.DataFrame:
    closes = [85.0 + 18.0 * index / 69.0 + 0.4 * math.sin(index * 0.5) for index in range(70)]
    closes.extend(103.5 + math.sin(index * 0.8) for index in range(54))
    closes.append(105.5)
    opens = [closes[index - 1] if index else closes[0] for index in range(len(closes))]
    return pd.DataFrame({
        'Open': opens,
        'High': [max(open_value, close_value) + 0.5 for open_value, close_value in zip(opens, closes)],
        'Low': [min(open_value, close_value) - 0.5 for open_value, close_value in zip(opens, closes)],
        'Close': closes,
        'Volume': [1_000_000] * (len(closes) - 1) + [1_500_000],
    })


def _flat_consolidation_frame() -> pd.DataFrame:
    closes = [100.0 + (-1) ** index * 3.0 for index in range(80)]
    closes.extend(100.0 + (-1) ** index * 0.3 for index in range(19))
    closes.append(100.0)
    spreads = [4.0] * 80 + [0.8] * 20
    return pd.DataFrame({
        'Open': [value - 0.1 for value in closes],
        'High': [value + spread for value, spread in zip(closes, spreads)],
        'Low': [value - spread for value, spread in zip(closes, spreads)],
        'Close': closes,
        'Volume': [1_000_000] * len(closes),
    })


def _downtrend_frame() -> pd.DataFrame:
    closes = [150.0 - index * 0.3 + 1.5 * math.sin(index * 1.1) for index in range(100)]
    opens = [value + (0.4 if index % 3 else -0.3) for index, value in enumerate(closes)]
    return pd.DataFrame({
        'Open': opens,
        'High': [max(open_value, close_value) + 0.8 for open_value, close_value in zip(opens, closes)],
        'Low': [min(open_value, close_value) - 0.9 for open_value, close_value in zip(opens, closes)],
        'Close': closes,
        'Volume': [1_000_000 + index * 1_000 for index in range(len(closes))],
    })


def _double_bottom_frame() -> pd.DataFrame:
    return _frame_from_anchors(125, {
        0: 132.0,
        20: 116.0,
        42: 91.0,
        62: 112.0,
        88: 92.0,
        112: 106.0,
        124: 109.0,
    })


def _bullish_flag_frame() -> pd.DataFrame:
    return _frame_from_anchors(125, {
        0: 80.0,
        70: 90.0,
        100: 122.0,
        112: 108.0,
        124: 118.0,
    })


def _bullish_rsi_divergence_frame() -> pd.DataFrame:
    return _frame_from_anchors(125, {
        0: 120.0,
        35: 78.0,
        55: 100.0,
        88: 76.0,
        110: 88.0,
        124: 92.0,
    })


def _apply_all_modes(frame: pd.DataFrame, symbol: str) -> dict[str, Any]:
    worker = RandomStockWorker(pattern_modes=PATTERN_MODES)
    candidate = {'symbol': symbol, 'score': 50.0, 'rank': 1}
    with patch.object(worker, '_prepare_pattern_histories', return_value={symbol: frame}):
        pool, _status = worker._apply_pattern_analysis([candidate])
    assert len(pool) == 1
    return pool[0]


def _assert_volume_neutral(result: tuple[bool, float, list[str], dict[str, Any]]) -> None:
    _matched, _score, reasons, snapshot = result
    normalized_reasons = {str(reason or '').strip().casefold() for reason in reasons}
    assert not normalized_reasons.intersection(AFFIRMING_VOLUME_REASONS), normalized_reasons
    volume_state = str(snapshot.get('volume_state') or '').strip().casefold()
    assert volume_state not in AFFIRMING_VOLUME_STATES, volume_state


def test_cross_pattern_confusion_matrix_prefers_intended_structure() -> None:
    RandomStockWorker.clear_caches()
    fixtures = {
        'BREAKOUT': ('breakout', _breakout_frame()),
        'CONSOLIDATION': ('consolidation', _flat_consolidation_frame()),
        'DOWNTREND': ('downtrend', _downtrend_frame()),
        'DOUBLEBOTTOM': ('double_bottom', _double_bottom_frame()),
        'BULLISHFLAG': ('bullish_flag', _bullish_flag_frame()),
        'RSIDIVERGENCE': ('bullish_rsi_divergence', _bullish_rsi_divergence_frame()),
    }
    matrix = {}
    for symbol, (intended_mode, frame) in fixtures.items():
        candidate = _apply_all_modes(frame, symbol)
        matched_modes = set(candidate.get('matched_modes') or [])
        matrix[symbol] = {
            'matched': sorted(matched_modes),
            'primary': candidate.get('primary_pattern_mode'),
            'score': candidate.get('pattern_score'),
        }
        assert intended_mode in matched_modes, matrix
        assert candidate.get('primary_pattern_mode') == intended_mode, matrix
    RandomStockWorker.clear_caches()


def test_flat_consolidation_does_not_confuse_directional_or_swing_patterns() -> None:
    RandomStockWorker.clear_caches()
    candidate = _apply_all_modes(_flat_consolidation_frame(), 'FLAT')
    matched_modes = set(candidate.get('matched_modes') or [])
    assert 'consolidation' in matched_modes, candidate
    assert matched_modes.isdisjoint({'downtrend', 'double_bottom', 'bullish_rsi_divergence'}), candidate
    assert candidate.get('primary_pattern_mode') == 'consolidation'
    RandomStockWorker.clear_caches()


def test_last_bar_bullish_flag_breakout_is_reachable() -> None:
    frame = _frame_from_anchors(126, {
        0: 80.0,
        70: 90.0,
        100: 122.0,
        112: 108.0,
        124: 118.0,
        125: 124.0,
    })
    matched, score, reasons, snapshot = RandomStockWorker(
        pattern_modes=['bullish_flag']
    )._evaluate_bullish_flag_pattern(frame)
    assert matched, (score, reasons, snapshot)
    assert snapshot.get('setup_stage') == 'Bullish Flag Breakout', snapshot
    distance = snapshot.get('distance_to_flag_resistance_pct')
    assert isinstance(distance, (int, float)) and float(distance) >= 0.0, snapshot


def test_smooth_gradual_rise_is_not_a_bullish_flag_impulse() -> None:
    frame = _frame_from_anchors(125, {
        0: 80.0,
        99: 120.0,
        112: 112.0,
        124: 119.0,
    })
    matched, score, reasons, snapshot = RandomStockWorker(
        pattern_modes=['bullish_flag']
    )._evaluate_bullish_flag_pattern(frame)
    assert not matched, (score, reasons, snapshot)


def test_equal_or_higher_price_low_is_not_regular_bullish_rsi_divergence() -> None:
    for second_low in (78.0, 79.0):
        frame = _frame_from_anchors(125, {
            0: 120.0,
            35: 78.0,
            55: 100.0,
            88: second_low,
            110: 88.0,
            124: 92.0,
        })
        matched, score, reasons, snapshot = RandomStockWorker(
            pattern_modes=['bullish_rsi_divergence']
        )._evaluate_bullish_rsi_divergence_pattern(frame)
        assert not matched, (second_low, score, reasons, snapshot)


def test_primary_selection_is_mode_order_independent() -> None:
    RandomStockWorker.clear_caches()
    frame = _bullish_flag_frame()
    result_by_mode = {
        'breakout': (True, 90.0, ['breakout'], {'setup_stage': 'Fresh Breakout'}),
        'bullish_flag': (True, 86.0, ['flag'], {'setup_stage': 'Bullish Flag Setup'}),
    }
    selections = []
    for modes in (['breakout', 'bullish_flag'], ['bullish_flag', 'breakout']):
        worker = RandomStockWorker(pattern_modes=modes)
        ordered_results = {mode: result_by_mode[mode] for mode in modes}
        with (
            patch.object(worker, '_prepare_pattern_histories', return_value={'ORDER': frame}),
            patch.object(worker, '_evaluate_selected_patterns', return_value=ordered_results),
        ):
            pool, _status = worker._apply_pattern_analysis([{'symbol': 'ORDER', 'score': 50.0, 'rank': 1}])
        selections.append((pool[0].get('primary_pattern_mode'), tuple(pool[0].get('matched_modes') or [])))
    assert selections == [
        ('bullish_flag', ('breakout', 'bullish_flag')),
        ('bullish_flag', ('breakout', 'bullish_flag')),
    ], selections
    RandomStockWorker.clear_caches()


def test_evaluation_cache_invalidates_when_interior_ohlcv_changes() -> None:
    RandomStockWorker.clear_caches()
    worker = RandomStockWorker(pattern_modes=['breakout'])
    frame = _breakout_frame()
    calls = []

    def evaluate(candidate_frame: pd.DataFrame):
        interior_high = float(candidate_frame.iloc[10]['High'])
        calls.append(interior_high)
        matched = interior_high >= 150.0
        return matched, (80.0 if matched else 20.0), [], {'setup_stage': 'Fresh Breakout'}

    with patch.object(worker, '_evaluate_breakout_pattern', side_effect=evaluate):
        cold = worker._evaluate_selected_patterns('CACHE', frame)
        revised = frame.copy()
        revised.iloc[10, revised.columns.get_loc('High')] = 200.0
        warm = worker._evaluate_selected_patterns('CACHE', revised)

    assert cold['breakout'][0] is False
    assert warm['breakout'][0] is True
    assert len(calls) == 2, (calls, worker._fetch_meta)
    RandomStockWorker.clear_caches()


def test_zero_and_missing_volume_are_neutral_across_all_patterns() -> None:
    fixtures = {
        'breakout': _breakout_frame(),
        'consolidation': _flat_consolidation_frame(),
        'downtrend': _downtrend_frame(),
        'double_bottom': _double_bottom_frame(),
        'bullish_flag': _bullish_flag_frame(),
        'bullish_rsi_divergence': _bullish_rsi_divergence_frame(),
    }
    for mode, frame in fixtures.items():
        evaluator_name = f'_evaluate_{mode}_pattern'
        normal_result = getattr(RandomStockWorker(pattern_modes=[mode]), evaluator_name)(frame)
        for missing_value in (0.0, float('nan')):
            missing_volume_frame = frame.copy()
            missing_volume_frame['Volume'] = missing_value
            missing_result = getattr(
                RandomStockWorker(pattern_modes=[mode]),
                evaluator_name,
            )(missing_volume_frame)
            _assert_volume_neutral(missing_result)
            assert missing_result[1] <= normal_result[1], (mode, normal_result, missing_result)


def main() -> None:
    test_cross_pattern_confusion_matrix_prefers_intended_structure()
    test_flat_consolidation_does_not_confuse_directional_or_swing_patterns()
    test_last_bar_bullish_flag_breakout_is_reachable()
    test_smooth_gradual_rise_is_not_a_bullish_flag_impulse()
    test_equal_or_higher_price_low_is_not_regular_bullish_rsi_divergence()
    test_primary_selection_is_mode_order_independent()
    test_evaluation_cache_invalidates_when_interior_ohlcv_changes()
    test_zero_and_missing_volume_are_neutral_across_all_patterns()
    print('Roll pattern-recognition tests passed.')


if __name__ == '__main__':
    main()
