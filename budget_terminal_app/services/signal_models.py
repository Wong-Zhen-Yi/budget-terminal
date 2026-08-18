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
    minimum_score: float
    signal: SignalClass


@dataclass(frozen=True)
class SignalConfig:
    """Configuration for the initial multi-timeframe trend-breakout strategy."""

    ema_fast: int = 20
    ema_medium: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_lookback: int = 20
    relative_volume_threshold: float = 1.5
    breakout_lookback: int = 20
    max_vwap_extension_pct: float = 3.0
    #: Score the context timeframes on the last closed bar. The volume and breakout rules compare
    #: the scored bar against averages built from completed bars, so including a partially formed
    #: bar makes those comparisons meaningless and the score flicker within a single bar. The entry
    #: role deliberately keeps the live bar because it supplies the current price and VWAP distance.
    score_on_completed_bars: bool = True
    price_above_ema_fast_weight: float = 1.0
    ema_alignment_weight: float = 1.0
    price_above_ema_long_weight: float = 1.0
    rsi_weight: float = 1.0
    macd_histogram_weight: float = 1.0
    relative_volume_weight: float = 2.0
    price_above_vwap_weight: float = 1.0
    breakout_weight: float = 2.0
    minimum_trend_score_for_long: float = 2.0
    thresholds: tuple[SignalThreshold, ...] = (
        SignalThreshold(8.0, SignalClass.STRONG_LONG),
        SignalThreshold(6.0, SignalClass.LONG),
        SignalThreshold(4.0, SignalClass.WATCH),
        SignalThreshold(0.0, SignalClass.NONE),
    )

    @property
    def trend_max_score(self) -> float:
        return (
            self.price_above_ema_fast_weight
            + self.ema_alignment_weight
            + self.price_above_ema_long_weight
        )

    @property
    def momentum_max_score(self) -> float:
        return self.rsi_weight + self.macd_histogram_weight

    @property
    def volume_max_score(self) -> float:
        return self.relative_volume_weight

    @property
    def entry_max_score(self) -> float:
        return self.price_above_vwap_weight + self.breakout_weight

    @property
    def max_score(self) -> float:
        return (
            self.trend_max_score
            + self.momentum_max_score
            + self.volume_max_score
            + self.entry_max_score
        )

    @property
    def long_minimum_score(self) -> float:
        values = [threshold.minimum_score for threshold in self.thresholds if threshold.signal is SignalClass.LONG]
        return min(values) if values else self.max_score


@dataclass(frozen=True)
class SignalReason:
    name: str
    group: str
    passed: bool
    points: float
    description: str
    value: float | None = None
    reference: float | None = None


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
