from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.services.signal_engine import (
    SignalClass,
    SignalConfig,
    TradeStatus,
    calculate_indicators,
    classify_score,
    evaluate_signal,
    evaluate_signal_at_index,
    rsi_in_bullish_range,
)


def _frame(close: np.ndarray, *, frequency: str, volume: np.ndarray | None = None) -> pd.DataFrame:
    close_values = np.asarray(close, dtype=float)
    count = len(close_values)
    volume_values = np.asarray(volume if volume is not None else np.full(count, 1_000.0), dtype=float)
    index = pd.date_range("2025-01-02 09:30", periods=count, freq=frequency)
    return pd.DataFrame(
        {
            "Open": close_values - 0.08,
            "High": close_values + 0.12,
            "Low": close_values - 0.18,
            "Close": close_values,
            "Volume": volume_values,
        },
        index=index,
    )


def _bullish_frames(*, extended: bool = False) -> dict[str, pd.DataFrame]:
    trend_close = np.linspace(100.0, 170.0, 240)

    momentum_count = 90
    momentum_x = np.arange(momentum_count, dtype=float)
    momentum_close = 120.0 + momentum_x * 0.035 + np.sin(momentum_x / 2.5) * 0.55

    setup_close = np.linspace(130.0, 132.0, 45)
    setup_close[-1] = float(setup_close[:-1].max() + 1.0)
    setup_volume = np.full(45, 1_000.0)
    setup_volume[-1] = 2_000.0

    entry_close = np.linspace(132.0, 132.8, 30)
    if extended:
        entry_close[-1] = 142.0

    return {
        "trend": _frame(trend_close, frequency="1D"),
        "momentum": _frame(momentum_close, frequency="1h"),
        "setup": _frame(setup_close, frequency="5min", volume=setup_volume),
        "entry": _frame(entry_close, frequency="1min"),
    }


def _weak_frames() -> dict[str, pd.DataFrame]:
    trend_close = np.linspace(170.0, 100.0, 240)
    momentum_close = np.linspace(130.0, 110.0, 90)
    setup_close = np.linspace(120.0, 115.0, 45)
    setup_volume = np.full(45, 1_000.0)
    entry_close = np.linspace(116.0, 114.0, 30)
    return {
        "trend": _frame(trend_close, frequency="1D"),
        "momentum": _frame(momentum_close, frequency="1h"),
        "setup": _frame(setup_close, frequency="5min", volume=setup_volume),
        "entry": _frame(entry_close, frequency="1min"),
    }


def test_strong_bullish_setup() -> None:
    result = evaluate_signal("TEST", _bullish_frames())
    assert result.error == "", result.error
    assert result.trend_score == result.trend_max_score
    assert result.volume_score == result.volume_max_score
    assert result.entry_score == result.entry_max_score
    assert result.raw_score >= 8.0, result
    assert result.signal is SignalClass.STRONG_LONG
    assert result.trade_status is TradeStatus.VALID_LONG
    assert all(reason.description for reason in result.reasons)


def test_weak_setup() -> None:
    result = evaluate_signal("WEAK", _weak_frames())
    assert result.error == ""
    assert result.raw_score <= 3.0, result.raw_score
    assert result.signal is SignalClass.NONE
    assert result.trade_status is TradeStatus.NONE


def test_overextended_keeps_technical_score() -> None:
    normal = evaluate_signal("TEST", _bullish_frames())
    extended = evaluate_signal("TEST", _bullish_frames(extended=True))
    assert extended.raw_score == normal.raw_score
    assert extended.signal is normal.signal
    assert extended.trade_status is TradeStatus.TOO_EXTENDED
    assert extended.indicators["vwap_distance_pct"] > SignalConfig().max_vwap_extension_pct


def test_missing_data_is_controlled() -> None:
    frames = _bullish_frames()
    frames.pop("entry")
    result = evaluate_signal("MISS", frames)
    assert result.trade_status is TradeStatus.DATA_ERROR
    assert "entry: Unavailable" in result.error


def test_insufficient_candles_is_controlled() -> None:
    frames = _bullish_frames()
    frames["trend"] = frames["trend"].iloc[-40:]
    result = evaluate_signal("SHORT", frames)
    # Too little history is reported on its own terms rather than as a feed failure.
    assert result.trade_status is TradeStatus.INSUFFICIENT_HISTORY
    assert result.signal is SignalClass.NONE
    assert "Insufficient history" in result.error


def test_rsi_and_score_boundaries() -> None:
    config = SignalConfig()
    assert rsi_in_bullish_range(config.rsi_min, config)
    assert rsi_in_bullish_range(config.rsi_max, config)
    assert not rsi_in_bullish_range(config.rsi_min - 0.01, config)
    assert not rsi_in_bullish_range(config.rsi_max + 0.01, config)
    assert classify_score(3.999, 3.0, config) is SignalClass.NONE
    assert classify_score(4.0, 3.0, config) is SignalClass.WATCH
    assert classify_score(6.0, 3.0, config) is SignalClass.LONG
    assert classify_score(8.0, 3.0, config) is SignalClass.STRONG_LONG
    assert classify_score(10.0, 1.0, config) is SignalClass.WATCH


def test_breakout_uses_previous_completed_bars() -> None:
    config = SignalConfig(breakout_lookback=20)
    close = np.full(25, 10.0)
    frame = _frame(close, frequency="5min")
    frame.loc[frame.index[:-1], "High"] = np.linspace(10.1, 12.0, len(frame) - 1)
    frame.loc[frame.index[-1], ["Open", "High", "Low", "Close"]] = [11.8, 13.5, 11.7, 12.5]
    calculated = calculate_indicators(frame, config)
    expected = float(frame["High"].iloc[-21:-1].max())
    assert float(calculated["BREAKOUT_LEVEL"].iloc[-1]) == expected
    assert float(calculated["Close"].iloc[-1]) > expected
    assert float(calculated["BREAKOUT_LEVEL"].iloc[-1]) != float(frame["High"].iloc[-1])


def test_historical_index_does_not_see_future_rows() -> None:
    frames = _bullish_frames()
    indices = {role: len(frame) - 2 for role, frame in frames.items()}
    before = evaluate_signal_at_index("TEST", frames, indices)
    mutated = {role: frame.copy() for role, frame in frames.items()}
    for frame in mutated.values():
        frame.iloc[-1, frame.columns.get_loc("Close")] = 1_000_000.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 1_000_001.0
        frame.iloc[-1, frame.columns.get_loc("Volume")] = 1_000_000_000.0
    after = evaluate_signal_at_index("TEST", mutated, indices)
    assert after.raw_score == before.raw_score
    assert after.indicators == before.indicators


def test_mixed_timezone_indexes_produce_comparable_timestamp() -> None:
    frames = _bullish_frames()
    for role in ("momentum", "setup", "entry"):
        frames[role].index = frames[role].index.tz_localize("America/New_York")
    result = evaluate_signal("TEST", frames)
    assert result.timestamp.tzinfo is None


def _bar_seconds() -> dict[str, float]:
    return {"trend": 86_400.0, "momentum": 3_600.0, "setup": 300.0, "entry": 60.0}


def _reindex_to_now(frames: dict[str, pd.DataFrame], now: pd.Timestamp, freq: str, role: str) -> None:
    """Re-stamp one role's frame so its final bar is the one currently forming."""
    count = len(frames[role])
    frames[role].index = pd.date_range(end=now, periods=count, freq=freq)


def test_forming_bar_is_excluded_from_context_timeframes() -> None:
    now = pd.Timestamp("2025-06-10 14:32:00")
    frames = _bullish_frames()
    _reindex_to_now(frames, now, "5min", "setup")
    # The still-forming 5m bar carries the breakout and the volume surge. Scoring it against
    # completed-bar averages is exactly the comparison the change is meant to prevent.
    scored = evaluate_signal("TEST", frames, role_bar_seconds=_bar_seconds(), now=now.to_pydatetime())
    setup_bar = scored.timeframe_bars["setup"]
    assert setup_bar["partial"] is True
    assert setup_bar["dropped"] is True
    assert scored.timeframe_status["setup"] == "Available (last closed bar)"
    assert scored.trade_status is not TradeStatus.DATA_ERROR

    breakout = next(item for item in scored.reasons if item.group == "entry" and "Breakout" in item.name)
    volume = next(item for item in scored.reasons if item.group == "volume")
    assert not breakout.passed
    assert not volume.passed


def test_entry_timeframe_keeps_the_live_bar() -> None:
    now = pd.Timestamp("2025-06-10 14:32:00")
    frames = _bullish_frames()
    _reindex_to_now(frames, now, "1min", "entry")
    scored = evaluate_signal("TEST", frames, role_bar_seconds=_bar_seconds(), now=now.to_pydatetime())
    entry_bar = scored.timeframe_bars["entry"]
    assert entry_bar["partial"] is True
    # The live bar supplies the current price and VWAP distance, so it is never dropped.
    assert entry_bar["dropped"] is False
    assert scored.price == float(frames["entry"]["Close"].iloc[-1])


def test_completed_bars_can_be_disabled() -> None:
    now = pd.Timestamp("2025-06-10 14:32:00")
    frames = _bullish_frames()
    _reindex_to_now(frames, now, "5min", "setup")
    config = SignalConfig(score_on_completed_bars=False)
    scored = evaluate_signal("TEST", frames, config, role_bar_seconds=_bar_seconds(), now=now.to_pydatetime())
    assert scored.timeframe_bars["setup"]["dropped"] is False
    breakout = next(item for item in scored.reasons if item.group == "entry" and "Breakout" in item.name)
    assert breakout.passed


def test_stale_frames_are_not_treated_as_forming() -> None:
    # Every bar is long closed, so nothing should be dropped even with completed-bar scoring on.
    frames = _bullish_frames()
    scored = evaluate_signal("TEST", frames, role_bar_seconds=_bar_seconds())
    assert all(not bar["dropped"] for bar in scored.timeframe_bars.values())
    assert scored.raw_score == evaluate_signal("TEST", frames).raw_score


def test_timeframe_bars_report_as_of_per_role() -> None:
    scored = evaluate_signal("TEST", _bullish_frames(), role_bar_seconds=_bar_seconds())
    assert set(scored.timeframe_bars) == {"trend", "momentum", "setup", "entry"}
    for role, bar in scored.timeframe_bars.items():
        assert bar["as_of"], role


def test_young_symbol_is_not_reported_as_a_data_error() -> None:
    """A recent listing has healthy data, just not 200 bars of it."""
    frames = _bullish_frames()
    frames["trend"] = frames["trend"].iloc[-40:]
    scored = evaluate_signal("NEWCO", frames)
    assert scored.trade_status is TradeStatus.INSUFFICIENT_HISTORY
    assert "Insufficient history" in scored.error

    # A genuinely absent frame still reports as a data error.
    broken = _bullish_frames()
    broken["momentum"] = broken["momentum"].iloc[:0]
    assert evaluate_signal("BROKEN", broken).trade_status is TradeStatus.DATA_ERROR

    # Mixed causes stay a data error: the real failure must not be masked by the benign one.
    mixed = _bullish_frames()
    mixed["trend"] = mixed["trend"].iloc[-40:]
    mixed["momentum"] = mixed["momentum"].iloc[:0]
    assert evaluate_signal("MIXED", mixed).trade_status is TradeStatus.DATA_ERROR


def main() -> None:
    tests = [
        test_strong_bullish_setup,
        test_weak_setup,
        test_overextended_keeps_technical_score,
        test_missing_data_is_controlled,
        test_insufficient_candles_is_controlled,
        test_rsi_and_score_boundaries,
        test_breakout_uses_previous_completed_bars,
        test_historical_index_does_not_see_future_rows,
        test_mixed_timezone_indexes_produce_comparable_timestamp,
        test_forming_bar_is_excluded_from_context_timeframes,
        test_entry_timeframe_keeps_the_live_bar,
        test_completed_bars_can_be_disabled,
        test_stale_frames_are_not_treated_as_forming,
        test_timeframe_bars_report_as_of_per_role,
        test_young_symbol_is_not_reported_as_a_data_error,
    ]
    for test in tests:
        test()
    print(f"Signal engine tests passed ({len(tests)} checks).")


if __name__ == "__main__":
    main()
