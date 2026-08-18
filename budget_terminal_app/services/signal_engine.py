from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from .technical_analysis import calculate_macd
from .signal_models import (
    RiskFilter,
    SignalClass,
    SignalConfig,
    SignalReason,
    SignalResult,
    SignalStrategy,
    SignalThreshold,
    TradeStatus,
)

__all__ = [
    "SignalClass",
    "SignalConfig",
    "SignalReason",
    "SignalResult",
    "SignalStrategy",
    "SignalThreshold",
    "TradeStatus",
    "TrendBreakoutStrategy",
    "VwapExtensionRiskFilter",
    "calculate_indicators",
    "classify_score",
    "data_error_result",
    "evaluate_signal",
    "evaluate_signal_at_index",
    "rsi_in_bullish_range",
]


class VwapExtensionRiskFilter:
    """Keep the technical score visible while blocking an extended entry."""

    def apply(self, result: SignalResult, config: SignalConfig) -> None:
        if result.signal not in {SignalClass.LONG, SignalClass.STRONG_LONG}:
            return
        extension = _finite_float(result.indicators.get("vwap_distance_pct"))
        if extension is None or extension <= config.max_vwap_extension_pct:
            return
        result.trade_status = TradeStatus.TOO_EXTENDED
        result.warnings.append(
            f"Price is {extension:.2f}% above VWAP; maximum configured extension is "
            f"{config.max_vwap_extension_pct:.2f}%."
        )


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _normalize_ohlcv(frame: Any) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        if normalized.columns.nlevels != 2:
            return pd.DataFrame()
        field_names = {"OPEN", "HIGH", "LOW", "CLOSE", "ADJ CLOSE", "VOLUME"}
        scores = [
            len({str(value).upper().strip() for value in normalized.columns.get_level_values(level)} & field_names)
            for level in range(2)
        ]
        if not max(scores):
            return pd.DataFrame()
        normalized.columns = normalized.columns.get_level_values(0 if scores[0] >= scores[1] else 1)
    aliases = {str(column).strip().lower(): column for column in normalized.columns}
    rename = {}
    for target in ("Open", "High", "Low", "Close", "Volume"):
        source = aliases.get(target.lower())
        if source is not None:
            rename[source] = target
    normalized = normalized.rename(columns=rename)
    if "Close" not in normalized.columns:
        return pd.DataFrame()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.loc[~normalized.index.duplicated(keep="last")].sort_index()
    return normalized.loc[normalized["Close"].notna()].copy()


def _calculate_rsi_no_lookahead(close: pd.Series, period: int) -> pd.Series:
    delta = close.astype(float).diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0.0, float("nan"))
    rsi = 100.0 - 100.0 / (1.0 + relative_strength)
    rsi = rsi.where(~((average_loss == 0.0) & (average_gain > 0.0)), 100.0)
    rsi = rsi.where(~((average_gain == 0.0) & (average_loss > 0.0)), 0.0)
    return rsi.clip(lower=0.0, upper=100.0)


def _calculate_session_vwap(frame: pd.DataFrame) -> pd.Series:
    if any(column not in frame.columns for column in ("High", "Low", "Close", "Volume")):
        return pd.Series(index=frame.index, dtype=float)
    typical_price = (frame["High"] + frame["Low"] + frame["Close"]) / 3.0
    volume = frame["Volume"].fillna(0.0).clip(lower=0.0)
    if isinstance(frame.index, pd.DatetimeIndex):
        session = pd.Series(frame.index.date, index=frame.index)
        cumulative_value = (typical_price * volume).groupby(session).cumsum()
        cumulative_volume = volume.groupby(session).cumsum()
    else:
        cumulative_value = (typical_price * volume).cumsum()
        cumulative_volume = volume.cumsum()
    return cumulative_value / cumulative_volume.replace(0.0, float("nan"))


def calculate_indicators(
    frame: pd.DataFrame,
    config: SignalConfig | None = None,
    *,
    include_vwap: bool = True,
) -> pd.DataFrame:
    """Calculate causal indicators; every output row uses only that row and earlier rows."""

    cfg = config or SignalConfig()
    calculated = _normalize_ohlcv(frame)
    if calculated.empty:
        return calculated
    close = calculated["Close"]
    calculated["EMA_FAST"] = close.ewm(span=cfg.ema_fast, adjust=False, min_periods=cfg.ema_fast).mean()
    calculated["EMA_MEDIUM"] = close.ewm(span=cfg.ema_medium, adjust=False, min_periods=cfg.ema_medium).mean()
    calculated["EMA_LONG"] = close.ewm(span=cfg.ema_long, adjust=False, min_periods=cfg.ema_long).mean()
    calculated["RSI"] = _calculate_rsi_no_lookahead(close, cfg.rsi_period)
    macd, macd_signal, histogram = calculate_macd(
        close,
        fast_period=cfg.macd_fast,
        slow_period=cfg.macd_slow,
        signal_period=cfg.macd_signal,
    )
    calculated["MACD"] = macd
    calculated["MACD_SIGNAL"] = macd_signal
    calculated["MACD_HISTOGRAM"] = histogram
    if "Volume" in calculated.columns:
        calculated["AVERAGE_VOLUME"] = (
            calculated["Volume"].shift(1).rolling(cfg.volume_lookback, min_periods=cfg.volume_lookback).mean()
        )
        calculated["RELATIVE_VOLUME"] = calculated["Volume"] / calculated["AVERAGE_VOLUME"].replace(0.0, float("nan"))
    else:
        calculated["AVERAGE_VOLUME"] = float("nan")
        calculated["RELATIVE_VOLUME"] = float("nan")
    if "High" in calculated.columns:
        calculated["BREAKOUT_LEVEL"] = (
            calculated["High"].shift(1).rolling(cfg.breakout_lookback, min_periods=cfg.breakout_lookback).max()
        )
    else:
        calculated["BREAKOUT_LEVEL"] = float("nan")
    calculated["VWAP"] = _calculate_session_vwap(calculated) if include_vwap else float("nan")
    return calculated


def rsi_in_bullish_range(value: Any, config: SignalConfig | None = None) -> bool:
    cfg = config or SignalConfig()
    numeric = _finite_float(value)
    return numeric is not None and cfg.rsi_min <= numeric <= cfg.rsi_max


def classify_score(
    score: Any,
    trend_score: Any,
    config: SignalConfig | None = None,
) -> SignalClass:
    cfg = config or SignalConfig()
    numeric_score = _finite_float(score) or 0.0
    numeric_trend = _finite_float(trend_score) or 0.0
    classification = SignalClass.NONE
    for threshold in sorted(cfg.thresholds, key=lambda item: item.minimum_score, reverse=True):
        if numeric_score >= threshold.minimum_score:
            classification = threshold.signal
            break
    if classification in {SignalClass.LONG, SignalClass.STRONG_LONG} and numeric_trend < cfg.minimum_trend_score_for_long:
        return SignalClass.WATCH
    return classification


def _slice_frame_at_index(frame: Any, index: Any = None) -> pd.DataFrame:
    normalized = _normalize_ohlcv(frame)
    if normalized.empty or index is None:
        return normalized
    if isinstance(index, int):
        position = index if index >= 0 else len(normalized) + index
        if position < 0 or position >= len(normalized):
            return pd.DataFrame()
        return normalized.iloc[: position + 1].copy()
    try:
        return normalized.loc[normalized.index <= index].copy()
    except Exception:
        return pd.DataFrame()


def _to_naive_utc(value: Any) -> datetime | None:
    """Normalize any pandas timestamp to a tz-naive UTC datetime for comparison."""

    try:
        timestamp_value = pd.Timestamp(value)
        if timestamp_value.tzinfo is not None:
            timestamp_value = timestamp_value.tz_convert("UTC").tz_localize(None)
        return timestamp_value.to_pydatetime()
    except Exception:
        return None


def _final_bar_is_open(timestamp: datetime | None, bar_seconds: Any, now: datetime | None) -> bool:
    """Report whether the last bar's own interval has not elapsed yet."""

    duration = _finite_float(bar_seconds)
    if timestamp is None or duration is None or duration <= 0.0:
        return False
    reference = now or datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed = (reference - timestamp).total_seconds()
    # A bar stamped in the future (clock skew, or a source that stamps the bar close) is treated as
    # complete rather than open, so skew can never silently discard the newest row.
    return 0.0 <= elapsed < duration


@dataclass(frozen=True)
class _TimeframeRead:
    row: pd.Series | None
    status: str
    timestamp: datetime | None
    calculated: pd.DataFrame
    partial: bool = False
    dropped: bool = False
    #: ``ok`` | ``short`` (too few bars to score) | ``missing`` (nothing usable arrived).
    kind: str = "ok"

    @property
    def available(self) -> bool:
        """Whether a row could be scored. Kept separate from ``status`` so the status text stays
        free to describe *which* bar was used without being mistaken for a data failure."""

        return self.row is not None

    def provenance(self) -> dict[str, Any]:
        return {
            "as_of": self.timestamp.isoformat() if self.timestamp is not None else None,
            "partial": bool(self.partial),
            "dropped": bool(self.dropped),
        }


def _timeframe_row(
    frames: Mapping[str, pd.DataFrame],
    role: str,
    config: SignalConfig,
    indices: Mapping[str, Any],
    *,
    minimum_bars: int,
    include_vwap: bool = False,
    bar_seconds: Any = None,
    now: datetime | None = None,
    drop_open_bar: bool = False,
) -> _TimeframeRead:
    frame = _slice_frame_at_index(frames.get(role), indices.get(role))
    if frame.empty:
        return _TimeframeRead(None, "Unavailable", None, pd.DataFrame(), kind="missing")
    # Dropping a still-forming bar consumes one row, so require it up front rather than letting the
    # drop turn an already-marginal frame into a short one.
    required_bars = minimum_bars + (1 if drop_open_bar else 0)
    if len(frame) < required_bars:
        return _TimeframeRead(
            None,
            f"Insufficient history ({len(frame)}/{required_bars} bars)",
            None,
            pd.DataFrame(),
            kind="short",
        )
    calculated = calculate_indicators(frame, config, include_vwap=include_vwap)
    if calculated.empty:
        return _TimeframeRead(None, "Malformed OHLCV data", None, pd.DataFrame(), kind="missing")

    position = -1
    partial = _final_bar_is_open(_to_naive_utc(calculated.index[-1]), bar_seconds, now)
    dropped = False
    if partial and drop_open_bar and len(calculated) >= 2:
        position = -2
        dropped = True
    elif partial and drop_open_bar:
        return _TimeframeRead(
            None, "Only a partially formed bar is available", None, pd.DataFrame(), kind="short"
        )

    row = calculated.iloc[position]
    timestamp_value = _to_naive_utc(calculated.index[position])
    status = "Available (last closed bar)" if dropped else "Available"
    scored = calculated.iloc[: position + 1] if position == -2 else calculated
    return _TimeframeRead(row, status, timestamp_value, scored, partial=partial, dropped=dropped)


def _reason(
    name: str,
    group: str,
    passed: bool,
    weight: float,
    description: str,
    *,
    value: Any = None,
    reference: Any = None,
) -> SignalReason:
    return SignalReason(
        name=name,
        group=group,
        passed=bool(passed),
        points=float(weight) if passed else 0.0,
        description=description,
        value=_finite_float(value),
        reference=_finite_float(reference),
    )


class TrendBreakoutStrategy:
    """Daily trend + hourly momentum + setup volume/breakout + entry VWAP."""

    name = "Trend Breakout"

    def __init__(
        self,
        config: SignalConfig | None = None,
        *,
        risk_filters: Sequence[RiskFilter] | None = None,
    ) -> None:
        self.config = config or SignalConfig()
        self.risk_filters = tuple(risk_filters or (VwapExtensionRiskFilter(),))

    def evaluate(
        self,
        ticker: str,
        frames: Mapping[str, pd.DataFrame],
        *,
        indices: Mapping[str, Any] | None = None,
        role_bar_seconds: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> SignalResult:
        cfg = self.config
        requested_indices = dict(indices or {})
        bar_seconds = dict(role_bar_seconds or {})
        # Explicit indices mean a historical replay, where "the last row" is chosen by the caller
        # and there is no live bar to exclude.
        drop_open = bool(cfg.score_on_completed_bars) and not requested_indices

        trend_read = _timeframe_row(
            frames,
            "trend",
            cfg,
            requested_indices,
            minimum_bars=cfg.ema_long,
            bar_seconds=bar_seconds.get("trend"),
            now=now,
            drop_open_bar=drop_open,
        )
        momentum_read = _timeframe_row(
            frames,
            "momentum",
            cfg,
            requested_indices,
            minimum_bars=cfg.macd_slow + cfg.macd_signal,
            bar_seconds=bar_seconds.get("momentum"),
            now=now,
            drop_open_bar=drop_open,
        )
        setup_read = _timeframe_row(
            frames,
            "setup",
            cfg,
            requested_indices,
            minimum_bars=max(cfg.volume_lookback, cfg.breakout_lookback) + 1,
            bar_seconds=bar_seconds.get("setup"),
            now=now,
            drop_open_bar=drop_open,
        )
        # The entry role keeps the live bar on purpose: it supplies the current price and the VWAP
        # distance that the risk filter acts on.
        entry_read = _timeframe_row(
            frames,
            "entry",
            cfg,
            requested_indices,
            minimum_bars=2,
            include_vwap=True,
            bar_seconds=bar_seconds.get("entry"),
            now=now,
        )
        trend, momentum, setup, entry = trend_read.row, momentum_read.row, setup_read.row, entry_read.row
        momentum_frame = momentum_read.calculated
        timeframe_status = {
            "trend": trend_read.status,
            "momentum": momentum_read.status,
            "setup": setup_read.status,
            "entry": entry_read.status,
        }
        timeframe_bars = {
            "trend": trend_read.provenance(),
            "momentum": momentum_read.provenance(),
            "setup": setup_read.provenance(),
            "entry": entry_read.provenance(),
        }
        reads_by_role = {
            "trend": trend_read,
            "momentum": momentum_read,
            "setup": setup_read,
            "entry": entry_read,
        }
        availability = {role: read.available for role, read in reads_by_role.items()}
        timestamp_candidates = [
            read.timestamp
            for read in (entry_read, setup_read, momentum_read, trend_read)
            if read.timestamp is not None
        ]
        timestamp = max(timestamp_candidates) if timestamp_candidates else datetime.now()
        reasons: list[SignalReason] = []
        indicators: dict[str, float | str | None] = {}
        warnings: list[str] = []

        trend_score = 0.0
        if trend is not None:
            close = _finite_float(trend.get("Close"))
            ema_fast = _finite_float(trend.get("EMA_FAST"))
            ema_medium = _finite_float(trend.get("EMA_MEDIUM"))
            ema_long = _finite_float(trend.get("EMA_LONG"))
            indicators.update({"ema20": ema_fast, "ema50": ema_medium, "ema200": ema_long})
            trend_reasons = (
                _reason("Price above EMA20", "trend", close is not None and ema_fast is not None and close > ema_fast, cfg.price_above_ema_fast_weight, "Daily close is above the fast trend average.", value=close, reference=ema_fast),
                _reason("EMA20 above EMA50", "trend", ema_fast is not None and ema_medium is not None and ema_fast > ema_medium, cfg.ema_alignment_weight, "Daily fast and medium averages are aligned bullishly.", value=ema_fast, reference=ema_medium),
                _reason("Price above EMA200", "trend", close is not None and ema_long is not None and close > ema_long, cfg.price_above_ema_long_weight, "Daily close is above the long-term trend average.", value=close, reference=ema_long),
            )
            reasons.extend(trend_reasons)
            trend_score = sum(item.points for item in trend_reasons)

        momentum_score = 0.0
        if momentum is not None:
            rsi = _finite_float(momentum.get("RSI"))
            macd = _finite_float(momentum.get("MACD"))
            macd_signal = _finite_float(momentum.get("MACD_SIGNAL"))
            histogram = _finite_float(momentum.get("MACD_HISTOGRAM"))
            previous_histogram = _finite_float(momentum_frame["MACD_HISTOGRAM"].iloc[-2]) if len(momentum_frame) >= 2 else None
            indicators.update({
                "rsi": rsi,
                "macd": macd,
                "macd_signal": macd_signal,
                "macd_histogram": histogram,
                "macd_histogram_previous": previous_histogram,
            })
            momentum_reasons = (
                _reason("RSI in bullish range", "momentum", rsi_in_bullish_range(rsi, cfg), cfg.rsi_weight, f"Hourly RSI is between {cfg.rsi_min:g} and {cfg.rsi_max:g}.", value=rsi, reference=cfg.rsi_min),
                _reason("MACD histogram increasing", "momentum", histogram is not None and previous_histogram is not None and histogram > previous_histogram, cfg.macd_histogram_weight, "Hourly MACD histogram is rising from the prior completed bar.", value=histogram, reference=previous_histogram),
            )
            reasons.extend(momentum_reasons)
            momentum_score = sum(item.points for item in momentum_reasons)

        volume_score = 0.0
        entry_score = 0.0
        if setup is not None:
            setup_close = _finite_float(setup.get("Close"))
            relative_volume = _finite_float(setup.get("RELATIVE_VOLUME"))
            average_volume = _finite_float(setup.get("AVERAGE_VOLUME"))
            breakout_level = _finite_float(setup.get("BREAKOUT_LEVEL"))
            indicators.update({
                "relative_volume": relative_volume,
                "average_volume": average_volume,
                "breakout_level": breakout_level,
            })
            volume_reason = _reason(
                "Relative volume elevated",
                "volume",
                relative_volume is not None and relative_volume > cfg.relative_volume_threshold,
                cfg.relative_volume_weight,
                f"Setup-bar volume exceeds {cfg.relative_volume_threshold:g}x its prior {cfg.volume_lookback}-bar average.",
                value=relative_volume,
                reference=cfg.relative_volume_threshold,
            )
            breakout_reason = _reason(
                f"Breakout above prior {cfg.breakout_lookback}-bar high",
                "entry",
                setup_close is not None and breakout_level is not None and setup_close > breakout_level,
                cfg.breakout_weight,
                "Setup close is above resistance calculated from prior completed bars only.",
                value=setup_close,
                reference=breakout_level,
            )
            reasons.extend((volume_reason, breakout_reason))
            volume_score += volume_reason.points
            entry_score += breakout_reason.points

        price = None
        if entry is not None:
            price = _finite_float(entry.get("Close"))
            vwap = _finite_float(entry.get("VWAP"))
            distance = price - vwap if price is not None and vwap is not None else None
            distance_pct = distance / vwap * 100.0 if distance is not None and vwap not in (None, 0.0) else None
            indicators.update({
                "price": price,
                "vwap": vwap,
                "vwap_distance": distance,
                "vwap_distance_pct": distance_pct,
            })
            vwap_reason = _reason(
                "Price above VWAP",
                "entry",
                price is not None and vwap is not None and price > vwap,
                cfg.price_above_vwap_weight,
                "Entry-timeframe price is above session VWAP.",
                value=price,
                reference=vwap,
            )
            reasons.append(vwap_reason)
            entry_score += vwap_reason.points

        raw_score = trend_score + momentum_score + volume_score + entry_score
        missing = [
            f"{role}: {timeframe_status[role]}" for role, ok in availability.items() if not ok
        ]
        signal = classify_score(raw_score, trend_score, cfg) if not missing else SignalClass.NONE
        if not missing and raw_score >= cfg.long_minimum_score and trend_score < cfg.minimum_trend_score_for_long:
            warnings.append("Lower-timeframe strength is capped at WATCH because the higher-timeframe trend is not qualified.")
        if missing:
            warnings.extend(missing)
            # A symbol that is simply too young to carry a 200-bar average is not a feed failure,
            # and reporting it as one buries real fetch problems among benign rows.
            only_short = all(
                read.kind == "short" for role, read in reads_by_role.items() if not availability[role]
            )
            trade_status = TradeStatus.INSUFFICIENT_HISTORY if only_short else TradeStatus.DATA_ERROR
            error = "; ".join(missing)
        elif signal in {SignalClass.LONG, SignalClass.STRONG_LONG}:
            trade_status = TradeStatus.VALID_LONG
            error = ""
        elif signal is SignalClass.WATCH:
            trade_status = TradeStatus.WATCH
            error = ""
        else:
            trade_status = TradeStatus.NONE
            error = ""

        result = SignalResult(
            ticker=str(ticker or "").upper().strip(),
            timestamp=timestamp,
            price=price,
            raw_score=raw_score,
            max_score=cfg.max_score,
            trend_score=trend_score,
            trend_max_score=cfg.trend_max_score,
            momentum_score=momentum_score,
            momentum_max_score=cfg.momentum_max_score,
            volume_score=volume_score,
            volume_max_score=cfg.volume_max_score,
            entry_score=entry_score,
            entry_max_score=cfg.entry_max_score,
            signal=signal,
            trade_status=trade_status,
            reasons=reasons,
            warnings=warnings,
            indicators=indicators,
            timeframe_status=timeframe_status,
            timeframe_bars=timeframe_bars,
            error=error,
        )
        if result.trade_status is not TradeStatus.DATA_ERROR:
            for risk_filter in self.risk_filters:
                risk_filter.apply(result, cfg)
        return result


def evaluate_signal(
    ticker: str,
    frames: Mapping[str, pd.DataFrame],
    config: SignalConfig | None = None,
    *,
    role_bar_seconds: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> SignalResult:
    return TrendBreakoutStrategy(config).evaluate(
        ticker, frames, role_bar_seconds=role_bar_seconds, now=now
    )


def evaluate_signal_at_index(
    ticker: str,
    frames: Mapping[str, pd.DataFrame],
    indices: Mapping[str, Any],
    config: SignalConfig | None = None,
) -> SignalResult:
    """Evaluate historical bars at explicit role indexes without exposing future rows."""

    return TrendBreakoutStrategy(config).evaluate(ticker, frames, indices=indices)


def data_error_result(
    ticker: str,
    message: Any,
    config: SignalConfig | None = None,
) -> SignalResult:
    """Build a controlled scanner result when market data cannot be evaluated."""

    cfg = config or SignalConfig()
    error = str(message or "Market data unavailable").strip()
    return SignalResult(
        ticker=str(ticker or "").upper().strip(),
        timestamp=datetime.now(),
        price=None,
        raw_score=0.0,
        max_score=cfg.max_score,
        trend_score=0.0,
        trend_max_score=cfg.trend_max_score,
        momentum_score=0.0,
        momentum_max_score=cfg.momentum_max_score,
        volume_score=0.0,
        volume_max_score=cfg.volume_max_score,
        entry_score=0.0,
        entry_max_score=cfg.entry_max_score,
        signal=SignalClass.NONE,
        trade_status=TradeStatus.DATA_ERROR,
        warnings=[error],
        timeframe_status={
            "trend": "Unavailable",
            "momentum": "Unavailable",
            "setup": "Unavailable",
            "entry": "Unavailable",
        },
        timeframe_bars={
            role: {"as_of": None, "partial": False, "dropped": False}
            for role in ("trend", "momentum", "setup", "entry")
        },
        error=error,
    )
