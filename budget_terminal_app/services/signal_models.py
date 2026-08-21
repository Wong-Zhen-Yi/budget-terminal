from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol

import pandas as pd


class SignalClass(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    LONG = "LONG"
    STRONG_LONG = "STRONG_LONG"


class TradeStatus(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    VALID_LONG = "VALID_LONG"
    TOO_EXTENDED = "TOO_EXTENDED"
    #: The feed answered correctly but the symbol is too young to score — a recent listing cannot
    #: have a 200-bar average. Kept apart from DATA_ERROR so a healthy fetch is never reported as
    #: a failure.
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class SignalThreshold:
    """A classification cut expressed as a fraction of the score actually on offer.

    Fractions rather than absolute points: the available maximum shrinks when a component cannot
    be evaluated (a scan without its benchmark scores out of 84, not 100), and absolute cuts would
    quietly become stricter every time that happened.
    """

    minimum_fraction: float
    signal: SignalClass


@dataclass(frozen=True)
class SignalConfig:
    """Configuration for the multi-timeframe trend-breakout strategy.

    Weights are points out of 100 and every check awards a *fraction* of its weight, so two
    candidates that both clear a condition are still separated by how decisively they clear it.
    Distances are measured in ATR of the timeframe being scored rather than in percent: one fixed
    percentage cannot judge a quiet utility and a high-beta name on the same footing.
    """

    ema_fast: int = 20
    ema_medium: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    #: Width of the linear taper on each side of the RSI band. A hard window scored RSI 71 exactly
    #: as harshly as RSI 30, which reads strong momentum as no momentum at all.
    rsi_taper: float = 10.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    #: Histogram deltas inspected for the "rising" check. One bar of uptick is noise.
    macd_slope_bars: int = 3
    volume_lookback: int = 20
    #: Relative volume earning no credit; credit ramps from here to ``relative_volume_threshold``.
    relative_volume_floor: float = 1.0
    relative_volume_threshold: float = 1.5
    breakout_lookback: int = 20
    atr_period: int = 14
    #: Entry extension beyond VWAP that blocks a trade, in ATR of the entry timeframe.
    max_vwap_extension_atr: float = 2.0
    #: Percentage fallback used only when the entry ATR is unavailable.
    max_vwap_extension_pct: float = 3.0
    #: ATR multiples at which each graded check reaches full credit.
    trend_fast_full_atr: float = 0.5
    trend_alignment_full_atr: float = 0.5
    trend_long_full_atr: float = 2.0
    macd_signal_full_atr: float = 0.25
    breakout_full_atr: float = 0.25
    vwap_full_atr: float = 0.5
    #: Daily bars of excess return measured against the benchmark.
    relative_strength_lookback: int = 63
    relative_strength_short_lookback: int = 21
    relative_strength_full_excess_pct: float = 15.0
    relative_strength_short_full_excess_pct: float = 6.0
    #: Score the context timeframes on the last closed bar. The volume and breakout rules compare
    #: the scored bar against averages built from completed bars, so including a partially formed
    #: bar makes those comparisons meaningless and the score flicker within a single bar. The entry
    #: role deliberately keeps the live bar because it supplies the current price and VWAP distance.
    score_on_completed_bars: bool = True
    price_above_ema_fast_weight: float = 8.0
    ema_alignment_weight: float = 8.0
    price_above_ema_long_weight: float = 8.0
    rsi_weight: float = 9.0
    macd_histogram_weight: float = 5.0
    macd_signal_weight: float = 4.0
    relative_volume_weight: float = 16.0
    price_above_vwap_weight: float = 9.0
    breakout_weight: float = 17.0
    relative_strength_weight: float = 10.0
    relative_strength_short_weight: float = 6.0
    #: Share of the trend weight a candidate must hold before the lower timeframes can lift it
    #: past WATCH.
    minimum_trend_fraction_for_long: float = 2.0 / 3.0
    thresholds: tuple[SignalThreshold, ...] = (
        SignalThreshold(0.80, SignalClass.STRONG_LONG),
        SignalThreshold(0.60, SignalClass.LONG),
        SignalThreshold(0.40, SignalClass.WATCH),
        SignalThreshold(0.0, SignalClass.NONE),
    )

    def __post_init__(self) -> None:
        """Reject a configuration that would score nonsense rather than discovering it per ticker."""

        for name in (
            "ema_fast", "ema_medium", "ema_long", "rsi_period", "macd_fast", "macd_slow",
            "macd_signal", "macd_slope_bars", "volume_lookback", "breakout_lookback",
            "atr_period", "relative_strength_lookback", "relative_strength_short_lookback",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"SignalConfig.{name} must be at least 1")
        for name in (
            "price_above_ema_fast_weight", "ema_alignment_weight", "price_above_ema_long_weight",
            "rsi_weight", "macd_histogram_weight", "macd_signal_weight", "relative_volume_weight",
            "price_above_vwap_weight", "breakout_weight", "relative_strength_weight",
            "relative_strength_short_weight",
        ):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"SignalConfig.{name} must be positive")
        for name in (
            "rsi_taper", "trend_fast_full_atr", "trend_alignment_full_atr", "trend_long_full_atr",
            "macd_signal_full_atr", "breakout_full_atr", "vwap_full_atr",
            "relative_strength_full_excess_pct", "relative_strength_short_full_excess_pct",
        ):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"SignalConfig.{name} must be positive")
        if not self.rsi_min < self.rsi_max:
            raise ValueError("SignalConfig.rsi_min must be below rsi_max")
        if not 0.0 <= self.minimum_trend_fraction_for_long <= 1.0:
            raise ValueError("SignalConfig.minimum_trend_fraction_for_long must be within 0..1")
        if not self.thresholds:
            raise ValueError("SignalConfig.thresholds must not be empty")
        fractions = [float(threshold.minimum_fraction) for threshold in self.thresholds]
        if any(not 0.0 <= fraction <= 1.0 for fraction in fractions):
            raise ValueError("SignalConfig threshold fractions must be within 0..1")
        if sorted(fractions, reverse=True) != fractions or len(set(fractions)) != len(fractions):
            raise ValueError("SignalConfig.thresholds must be ordered strictly high to low")

    @property
    def trend_max_score(self) -> float:
        return (
            self.price_above_ema_fast_weight
            + self.ema_alignment_weight
            + self.price_above_ema_long_weight
        )

    @property
    def momentum_max_score(self) -> float:
        return self.rsi_weight + self.macd_histogram_weight + self.macd_signal_weight

    @property
    def volume_max_score(self) -> float:
        return self.relative_volume_weight

    @property
    def entry_max_score(self) -> float:
        return self.price_above_vwap_weight + self.breakout_weight

    @property
    def relative_max_score(self) -> float:
        return self.relative_strength_weight + self.relative_strength_short_weight

    @property
    def max_score(self) -> float:
        """The full budget. A single result may be scored out of less; see ``SignalResult``."""

        return (
            self.trend_max_score
            + self.momentum_max_score
            + self.volume_max_score
            + self.entry_max_score
            + self.relative_max_score
        )

    @property
    def long_minimum_fraction(self) -> float:
        values = [
            float(threshold.minimum_fraction)
            for threshold in self.thresholds
            if threshold.signal is SignalClass.LONG
        ]
        return min(values) if values else 1.0


@dataclass(frozen=True)
class SignalReason:
    """One scored check. ``points`` is fractional; ``weight`` is what it could have earned."""

    name: str
    group: str
    passed: bool
    points: float
    description: str
    value: float | None = None
    reference: float | None = None
    weight: float = 0.0


@dataclass
class SignalResult:
    ticker: str
    timestamp: datetime
    price: float | None
    raw_score: float
    max_score: float
    trend_score: float
    trend_max_score: float
    momentum_score: float
    momentum_max_score: float
    volume_score: float
    volume_max_score: float
    entry_score: float
    entry_max_score: float
    relative_score: float
    #: Zero when the scan had no usable benchmark. ``max_score`` excludes it in that case, so a
    #: score stays a comparable fraction instead of being silently penalized.
    relative_max_score: float
    signal: SignalClass
    trade_status: TradeStatus
    reasons: list[SignalReason] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    indicators: dict[str, float | str | None] = field(default_factory=dict)
    timeframe_status: dict[str, str] = field(default_factory=dict)
    #: Per-role bar provenance: ``{"as_of": iso_string|None, "partial": bool, "dropped": bool}``.
    #: ``dropped`` records that a still-forming bar was excluded from scoring.
    timeframe_bars: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""

    @property
    def signal_label(self) -> str:
        return self.signal.value.replace("_", " ")

    @property
    def trade_status_label(self) -> str:
        return self.trade_status.value.replace("_", " ")


class SignalStrategy(Protocol):
    name: str

    def evaluate(
        self,
        ticker: str,
        frames: Mapping[str, pd.DataFrame],
        *,
        indices: Mapping[str, Any] | None = None,
    ) -> SignalResult:
        ...


class RiskFilter(Protocol):
    def apply(self, result: SignalResult, config: SignalConfig) -> None:
        ...
