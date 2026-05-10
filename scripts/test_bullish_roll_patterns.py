from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.workers.random_recommender import RandomStockWorker


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
        high_value = max(open_value, close_value) * 1.012
        low_value = min(open_value, close_value) * 0.988
        opens.append(open_value)
        highs.append(high_value)
        lows.append(low_value)
        volumes.append(1_000_000 + index * 2_000 + (150_000 if close_value >= open_value else 0))
    return pd.DataFrame(
        {
            'Open': opens,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes,
        }
    )


def _worker(modes: list[str]) -> RandomStockWorker:
    return RandomStockWorker(pattern_modes=modes)


def test_positive_actionable_bullish_flag() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 80.0,
            70: 90.0,
            100: 122.0,
            112: 108.0,
            124: 118.0,
        },
    )
    matched, score, reasons, snapshot = _worker(['bullish_flag'])._evaluate_bullish_flag_pattern(frame)
    assert matched, (score, reasons, snapshot)
    assert score >= 62
    assert snapshot['setup_stage'] in {'Bullish Flag Setup', 'Bullish Flag Breakout'}
    assert snapshot['flagpole_gain_pct'] >= 12.0
    assert 3.0 <= snapshot['pullback_pct'] <= 18.0
    assert -5.0 <= snapshot['distance_to_flag_resistance_pct'] <= 4.0


def test_rejects_bullish_flag_without_flagpole() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 100.0,
            70: 102.0,
            100: 108.0,
            112: 100.0,
            124: 105.0,
        },
    )
    matched, score, _reasons, snapshot = _worker(['bullish_flag'])._evaluate_bullish_flag_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_rejects_bullish_flag_excessive_pullback() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 80.0,
            70: 90.0,
            100: 122.0,
            112: 92.0,
            124: 110.0,
        },
    )
    matched, score, _reasons, snapshot = _worker(['bullish_flag'])._evaluate_bullish_flag_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_positive_actionable_bullish_rsi_divergence() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 120.0,
            35: 78.0,
            55: 100.0,
            88: 76.0,
            110: 88.0,
            124: 92.0,
        },
    )
    matched, score, reasons, snapshot = _worker(['bullish_rsi_divergence'])._evaluate_bullish_rsi_divergence_pattern(frame)
    assert matched, (score, reasons, snapshot)
    assert score >= 62
    assert snapshot['setup_stage'] in {'Bullish RSI Divergence', 'Bullish RSI Divergence Triggered'}
    assert snapshot['price_low_change_pct'] <= 2.0
    assert snapshot['rsi_divergence_points'] >= 4.0
    assert snapshot['rebound_from_second_pct'] >= 3.5


def test_rejects_rsi_divergence_without_rsi_higher_low() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 120.0,
            35: 90.0,
            55: 100.0,
            88: 70.0,
            110: 77.0,
            124: 80.0,
        },
    )
    matched, score, _reasons, snapshot = _worker(['bullish_rsi_divergence'])._evaluate_bullish_rsi_divergence_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_rejects_rsi_divergence_without_rebound_confirmation() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 120.0,
            35: 78.0,
            55: 100.0,
            88: 76.0,
            110: 77.0,
            124: 77.4,
        },
    )
    matched, score, _reasons, snapshot = _worker(['bullish_rsi_divergence'])._evaluate_bullish_rsi_divergence_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_mode_normalization_accepts_new_bullish_modes() -> None:
    worker = RandomStockWorker(pattern_modes=['BULLISH_FLAG', 'bullish_rsi_divergence', 'unknown'])
    assert worker.pattern_modes == {'bullish_flag', 'bullish_rsi_divergence'}


if __name__ == '__main__':
    test_positive_actionable_bullish_flag()
    test_rejects_bullish_flag_without_flagpole()
    test_rejects_bullish_flag_excessive_pullback()
    test_positive_actionable_bullish_rsi_divergence()
    test_rejects_rsi_divergence_without_rsi_higher_low()
    test_rejects_rsi_divergence_without_rebound_confirmation()
    test_mode_normalization_accepts_new_bullish_modes()
    print('All bullish Roll pattern tests passed.')
