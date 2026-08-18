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
        volumes.append(1_000_000 + index * 2_000 + (140_000 if close_value >= open_value else 0))
    return pd.DataFrame(
        {
            'Open': opens,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes,
        }
    )


def _worker() -> RandomStockWorker:
    return RandomStockWorker(pattern_modes=['double_bottom'])


def test_positive_actionable_double_bottom() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 132.0,
            20: 116.0,
            42: 91.0,
            62: 112.0,
            88: 92.0,
            112: 106.0,
            124: 109.0,
        },
    )
    matched, score, reasons, snapshot = _worker()._evaluate_double_bottom_pattern(frame)
    assert matched, (score, reasons, snapshot)
    assert score >= 62
    assert snapshot['setup_stage'] in {'Double Bottom Rebound', 'Double Bottom Breakout'}
    assert snapshot['bottom_gap_pct'] <= 5.0
    assert -8.0 <= snapshot['distance_to_neckline_pct'] <= 6.0


def test_rejects_bottoms_too_far_apart() -> None:
    frame = _frame_from_anchors(
        155,
        {
            0: 132.0,
            18: 118.0,
            35: 91.0,
            72: 112.0,
            121: 92.0,
            142: 106.0,
            154: 109.0,
        },
    )
    matched, score, _reasons, snapshot = _worker()._evaluate_double_bottom_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_rejects_missing_neckline_rebound() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 132.0,
            20: 116.0,
            42: 91.0,
            62: 112.0,
            88: 92.0,
            112: 98.0,
            124: 99.0,
        },
    )
    matched, score, _reasons, snapshot = _worker()._evaluate_double_bottom_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_rejects_missing_prior_downtrend() -> None:
    frame = _frame_from_anchors(
        125,
        {
            0: 96.0,
            20: 95.0,
            42: 91.0,
            62: 112.0,
            88: 92.0,
            112: 106.0,
            124: 109.0,
        },
    )
    matched, score, _reasons, snapshot = _worker()._evaluate_double_bottom_pattern(frame)
    assert not matched
    assert score == 0.0
    assert snapshot == {}


def test_mode_normalization_accepts_double_bottom() -> None:
    worker = RandomStockWorker(pattern_modes=['DOUBLE_BOTTOM', 'breakout', 'unknown'])
    assert worker.pattern_modes == {'double_bottom', 'breakout'}


if __name__ == '__main__':
    test_positive_actionable_double_bottom()
    test_rejects_bottoms_too_far_apart()
    test_rejects_missing_neckline_rebound()
    test_rejects_missing_prior_downtrend()
    test_mode_normalization_accepts_double_bottom()
    print('All double-bottom pattern tests passed.')
