from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


Point = tuple[float, float]


@dataclass(frozen=True)
class ChartPatternGuide:
    start: Point
    end: Point
    label: str
    role: str = "structure"


@dataclass(frozen=True)
class ChartPatternDefinition:
    pattern_id: str
    name: str
    aliases: tuple[str, ...]
    family: str
    bias: str
    recognition: str
    confirmation: str
    invalidation: str
    target: str
    price_path: tuple[Point, ...]
    guide_lines: tuple[ChartPatternGuide, ...]
    breakout_marker: Point
    direction: str


REVERSAL_FAMILY = "Reversal"
CONTINUATION_FAMILY = "Continuation"
COMPRESSION_FAMILY = "Compression / Breakout"
CHANNEL_FAMILY = "Trend Channel"

CHART_PATTERN_FAMILIES = (
    REVERSAL_FAMILY,
    CONTINUATION_FAMILY,
    COMPRESSION_FAMILY,
    CHANNEL_FAMILY,
)
CHART_PATTERN_BIASES = ("Bullish", "Bearish", "Neutral")


def _guide(start: Point, end: Point, label: str, role: str = "structure") -> ChartPatternGuide:
    return ChartPatternGuide(start=start, end=end, label=label, role=role)


def _pattern(
    pattern_id: str,
    name: str,
    aliases: Iterable[str],
    family: str,
    bias: str,
    recognition: str,
    confirmation: str,
    invalidation: str,
    target: str,
    price_path: Iterable[Point],
    guide_lines: Iterable[ChartPatternGuide],
    breakout_marker: Point,
    direction: str,
) -> ChartPatternDefinition:
    return ChartPatternDefinition(
        pattern_id=pattern_id,
        name=name,
        aliases=tuple(aliases),
        family=family,
        bias=bias,
        recognition=recognition,
        confirmation=confirmation,
        invalidation=invalidation,
        target=target,
        price_path=tuple(price_path),
        guide_lines=tuple(guide_lines),
        breakout_marker=breakout_marker,
        direction=direction,
    )


CHART_PATTERN_CATALOG = (
    _pattern(
        "head_and_shoulders",
        "Head and Shoulders",
        ("H&S", "Head & Shoulders"),
        REVERSAL_FAMILY,
        "Bearish",
        "Three peaks form after an advance; the middle head is highest and the shoulders are similar.",
        "A decisive close below the neckline, ideally with expanding volume.",
        "Price reclaims the neckline and then closes above the right shoulder.",
        "Project the head-to-neckline height downward from the neckline break.",
        ((0.02, 0.28), (0.13, 0.57), (0.23, 0.35), (0.38, 0.88), (0.52, 0.36), (0.66, 0.61), (0.78, 0.35), (0.88, 0.27), (0.98, 0.12)),
        (_guide((0.16, 0.36), (0.84, 0.35), "Neckline", "neckline"),),
        (0.86, 0.30),
        "down",
    ),
    _pattern(
        "inverse_head_and_shoulders",
        "Inverse Head and Shoulders",
        ("Inverse H&S", "Inverse Head & Shoulders"),
        REVERSAL_FAMILY,
        "Bullish",
        "Three troughs form after a decline; the middle head is lowest and the shoulders are similar.",
        "A decisive close above the neckline, ideally with expanding volume.",
        "Price loses the neckline and then closes below the right shoulder.",
        "Project the neckline-to-head height upward from the neckline break.",
        ((0.02, 0.72), (0.13, 0.43), (0.23, 0.65), (0.38, 0.12), (0.52, 0.64), (0.66, 0.39), (0.78, 0.65), (0.88, 0.73), (0.98, 0.90)),
        (_guide((0.16, 0.64), (0.84, 0.65), "Neckline", "neckline"),),
        (0.86, 0.70),
        "up",
    ),
    _pattern(
        "double_top",
        "Double Top",
        ("M Top", "Two Tops"),
        REVERSAL_FAMILY,
        "Bearish",
        "Two comparable highs are separated by a clear reaction low after an advance.",
        "Price closes below the reaction-low neckline after the second top.",
        "Price closes back above the two-peak resistance zone.",
        "Project the resistance-to-neckline height downward from the break.",
        ((0.02, 0.27), (0.18, 0.48), (0.32, 0.80), (0.48, 0.39), (0.64, 0.78), (0.77, 0.43), (0.88, 0.31), (0.98, 0.16)),
        (
            _guide((0.24, 0.79), (0.70, 0.79), "Resistance", "resistance"),
            _guide((0.42, 0.40), (0.84, 0.40), "Neckline", "neckline"),
        ),
        (0.84, 0.36),
        "down",
    ),
    _pattern(
        "double_bottom",
        "Double Bottom",
        ("W Bottom", "Two Bottoms"),
        REVERSAL_FAMILY,
        "Bullish",
        "Two comparable lows are separated by a clear reaction high after a decline.",
        "Price closes above the reaction-high neckline after the second bottom.",
        "Price closes back below the two-trough support zone.",
        "Project the neckline-to-support height upward from the break.",
        ((0.02, 0.73), (0.18, 0.52), (0.32, 0.20), (0.48, 0.61), (0.64, 0.22), (0.77, 0.57), (0.88, 0.69), (0.98, 0.84)),
        (
            _guide((0.24, 0.21), (0.70, 0.21), "Support", "support"),
            _guide((0.42, 0.60), (0.84, 0.60), "Neckline", "neckline"),
        ),
        (0.84, 0.64),
        "up",
    ),
    _pattern(
        "triple_top",
        "Triple Top",
        ("Three Tops",),
        REVERSAL_FAMILY,
        "Bearish",
        "Three failed pushes test a similar resistance zone with reaction lows between them.",
        "Price closes beneath the shared reaction-low support after the third peak.",
        "Price establishes acceptance above the three-peak resistance zone.",
        "Project the resistance-to-support range downward from the support break.",
        ((0.02, 0.28), (0.14, 0.76), (0.27, 0.39), (0.40, 0.78), (0.53, 0.38), (0.66, 0.75), (0.78, 0.39), (0.88, 0.28), (0.98, 0.15)),
        (
            _guide((0.08, 0.76), (0.72, 0.76), "Resistance", "resistance"),
            _guide((0.22, 0.39), (0.84, 0.39), "Support", "support"),
        ),
        (0.84, 0.34),
        "down",
    ),
    _pattern(
        "triple_bottom",
        "Triple Bottom",
        ("Three Bottoms",),
        REVERSAL_FAMILY,
        "Bullish",
        "Three failed declines test a similar support zone with reaction highs between them.",
        "Price closes above the shared reaction-high resistance after the third trough.",
        "Price establishes acceptance below the three-trough support zone.",
        "Project the resistance-to-support range upward from the resistance break.",
        ((0.02, 0.72), (0.14, 0.24), (0.27, 0.61), (0.40, 0.22), (0.53, 0.62), (0.66, 0.25), (0.78, 0.61), (0.88, 0.72), (0.98, 0.85)),
        (
            _guide((0.08, 0.24), (0.72, 0.24), "Support", "support"),
            _guide((0.22, 0.61), (0.84, 0.61), "Resistance", "resistance"),
        ),
        (0.84, 0.66),
        "up",
    ),
    _pattern(
        "rounding_top",
        "Rounding Top",
        ("Inverted Bowl", "Dome Top"),
        REVERSAL_FAMILY,
        "Bearish",
        "A gradual dome develops as an advance loses momentum and lower highs begin to appear.",
        "Price breaks the base support after the right side of the dome develops.",
        "Price recovers the base and resumes making higher highs.",
        "Project the dome depth downward from the base break.",
        ((0.02, 0.28), (0.12, 0.44), (0.23, 0.62), (0.35, 0.75), (0.48, 0.81), (0.60, 0.77), (0.72, 0.65), (0.82, 0.47), (0.90, 0.31), (0.98, 0.16)),
        (_guide((0.02, 0.30), (0.92, 0.30), "Base", "support"),),
        (0.92, 0.26),
        "down",
    ),
    _pattern(
        "rounding_bottom",
        "Rounding Bottom",
        ("Saucer Bottom", "Bowl Bottom"),
        REVERSAL_FAMILY,
        "Bullish",
        "A gradual saucer develops as a decline loses momentum and higher lows begin to appear.",
        "Price breaks the rim resistance after the right side of the saucer develops.",
        "Price falls back below the rim and resumes making lower lows.",
        "Project the saucer depth upward from the rim break.",
        ((0.02, 0.72), (0.12, 0.56), (0.23, 0.38), (0.35, 0.25), (0.48, 0.19), (0.60, 0.23), (0.72, 0.35), (0.82, 0.53), (0.90, 0.69), (0.98, 0.84)),
        (_guide((0.02, 0.70), (0.92, 0.70), "Rim", "resistance"),),
        (0.92, 0.74),
        "up",
    ),
    _pattern(
        "cup_and_handle",
        "Cup and Handle",
        ("Cup with Handle",),
        REVERSAL_FAMILY,
        "Bullish",
        "A rounded cup returns to prior resistance, followed by a smaller controlled handle pullback.",
        "Price closes above the cup rim after holding the handle structure.",
        "Price breaks the handle low or falls back deeply into the cup.",
        "Project the cup depth upward from the rim breakout.",
        ((0.02, 0.72), (0.13, 0.45), (0.25, 0.25), (0.39, 0.18), (0.53, 0.28), (0.65, 0.53), (0.75, 0.72), (0.82, 0.60), (0.88, 0.56), (0.94, 0.71), (0.98, 0.86)),
        (
            _guide((0.02, 0.72), (0.96, 0.72), "Rim", "resistance"),
            _guide((0.78, 0.58), (0.91, 0.54), "Handle", "channel"),
        ),
        (0.95, 0.76),
        "up",
    ),
    _pattern(
        "inverse_cup_and_handle",
        "Inverse Cup and Handle",
        ("Inverted Cup and Handle",),
        REVERSAL_FAMILY,
        "Bearish",
        "An inverted rounded cup returns to support, followed by a smaller upward handle retracement.",
        "Price closes below the cup base after failing within the handle.",
        "Price breaks the handle high or recovers deeply into the inverted cup.",
        "Project the inverted-cup height downward from the base breakout.",
        ((0.02, 0.28), (0.13, 0.55), (0.25, 0.75), (0.39, 0.82), (0.53, 0.72), (0.65, 0.47), (0.75, 0.28), (0.82, 0.40), (0.88, 0.44), (0.94, 0.29), (0.98, 0.14)),
        (
            _guide((0.02, 0.28), (0.96, 0.28), "Base", "support"),
            _guide((0.78, 0.42), (0.91, 0.46), "Handle", "channel"),
        ),
        (0.95, 0.24),
        "down",
    ),
    _pattern(
        "bull_flag",
        "Bull Flag",
        ("Bullish Flag",),
        CONTINUATION_FAMILY,
        "Bullish",
        "A sharp flagpole advance is followed by a short, orderly downward-sloping channel.",
        "Price closes above flag resistance after the controlled pullback.",
        "Price breaks below the flag low and loses the pullback structure.",
        "Project the flagpole length upward from the flag breakout.",
        ((0.02, 0.18), (0.28, 0.78), (0.40, 0.68), (0.50, 0.74), (0.61, 0.61), (0.71, 0.67), (0.81, 0.55), (0.90, 0.70), (0.98, 0.88)),
        (
            _guide((0.29, 0.80), (0.84, 0.61), "Flag resistance", "resistance"),
            _guide((0.37, 0.65), (0.82, 0.50), "Flag support", "support"),
        ),
        (0.89, 0.68),
        "up",
    ),
    _pattern(
        "bear_flag",
        "Bear Flag",
        ("Bearish Flag",),
        CONTINUATION_FAMILY,
        "Bearish",
        "A sharp flagpole decline is followed by a short, orderly upward-sloping channel.",
        "Price closes below flag support after the controlled rebound.",
        "Price breaks above the flag high and loses the rebound structure.",
        "Project the flagpole length downward from the flag breakout.",
        ((0.02, 0.82), (0.28, 0.22), (0.40, 0.32), (0.50, 0.26), (0.61, 0.39), (0.71, 0.33), (0.81, 0.45), (0.90, 0.30), (0.98, 0.12)),
        (
            _guide((0.29, 0.20), (0.84, 0.39), "Flag support", "support"),
            _guide((0.37, 0.35), (0.82, 0.50), "Flag resistance", "resistance"),
        ),
        (0.89, 0.32),
        "down",
    ),
    _pattern(
        "bull_pennant",
        "Bull Pennant",
        ("Bullish Pennant",),
        CONTINUATION_FAMILY,
        "Bullish",
        "A sharp advance is followed by a small contracting consolidation with converging boundaries.",
        "Price closes above the pennant’s upper boundary with renewed participation.",
        "Price breaks the lower boundary and fails to regain it.",
        "Project the flagpole length upward from the pennant breakout.",
        ((0.02, 0.18), (0.28, 0.80), (0.40, 0.62), (0.50, 0.75), (0.60, 0.64), (0.69, 0.71), (0.78, 0.66), (0.88, 0.74), (0.98, 0.90)),
        (
            _guide((0.30, 0.80), (0.82, 0.68), "Resistance", "resistance"),
            _guide((0.36, 0.58), (0.82, 0.68), "Support", "support"),
        ),
        (0.86, 0.72),
        "up",
    ),
    _pattern(
        "bear_pennant",
        "Bear Pennant",
        ("Bearish Pennant",),
        CONTINUATION_FAMILY,
        "Bearish",
        "A sharp decline is followed by a small contracting consolidation with converging boundaries.",
        "Price closes below the pennant’s lower boundary with renewed participation.",
        "Price breaks the upper boundary and fails to fall back through it.",
        "Project the flagpole length downward from the pennant breakout.",
        ((0.02, 0.82), (0.28, 0.20), (0.40, 0.38), (0.50, 0.25), (0.60, 0.36), (0.69, 0.29), (0.78, 0.34), (0.88, 0.26), (0.98, 0.10)),
        (
            _guide((0.30, 0.20), (0.82, 0.32), "Support", "support"),
            _guide((0.36, 0.42), (0.82, 0.32), "Resistance", "resistance"),
        ),
        (0.86, 0.28),
        "down",
    ),
    _pattern(
        "bullish_rectangle",
        "Bullish Rectangle",
        ("Bull Rectangle", "Bullish Range"),
        CONTINUATION_FAMILY,
        "Bullish",
        "An advance pauses inside a horizontal range while buyers repeatedly defend support.",
        "Price closes above range resistance and holds the breakout area.",
        "Price falls below range support or cannot recover a failed breakout.",
        "Project the rectangle height upward from the resistance break.",
        ((0.02, 0.18), (0.25, 0.64), (0.36, 0.47), (0.48, 0.66), (0.59, 0.46), (0.70, 0.65), (0.80, 0.48), (0.89, 0.68), (0.98, 0.86)),
        (
            _guide((0.25, 0.66), (0.91, 0.66), "Resistance", "resistance"),
            _guide((0.25, 0.46), (0.86, 0.46), "Support", "support"),
        ),
        (0.90, 0.70),
        "up",
    ),
    _pattern(
        "bearish_rectangle",
        "Bearish Rectangle",
        ("Bear Rectangle", "Bearish Range"),
        CONTINUATION_FAMILY,
        "Bearish",
        "A decline pauses inside a horizontal range while sellers repeatedly defend resistance.",
        "Price closes below range support and holds beneath the breakdown area.",
        "Price rises above range resistance or cannot stay below a failed breakdown.",
        "Project the rectangle height downward from the support break.",
        ((0.02, 0.82), (0.25, 0.36), (0.36, 0.53), (0.48, 0.34), (0.59, 0.54), (0.70, 0.35), (0.80, 0.52), (0.89, 0.32), (0.98, 0.14)),
        (
            _guide((0.25, 0.34), (0.91, 0.34), "Support", "support"),
            _guide((0.25, 0.54), (0.86, 0.54), "Resistance", "resistance"),
        ),
        (0.90, 0.30),
        "down",
    ),
    _pattern(
        "ascending_triangle",
        "Ascending Triangle",
        ("Flat-top Triangle",),
        COMPRESSION_FAMILY,
        "Bullish",
        "Repeated tests of flat resistance occur while each reaction low rises.",
        "Price closes above horizontal resistance after the range contracts.",
        "Price breaks the rising support line and fails to recover it.",
        "Project the triangle’s widest height upward from the breakout.",
        ((0.02, 0.25), (0.18, 0.72), (0.31, 0.37), (0.44, 0.72), (0.56, 0.48), (0.67, 0.72), (0.77, 0.58), (0.86, 0.73), (0.98, 0.88)),
        (
            _guide((0.14, 0.72), (0.89, 0.72), "Resistance", "resistance"),
            _guide((0.04, 0.24), (0.86, 0.66), "Rising support", "support"),
        ),
        (0.88, 0.76),
        "up",
    ),
    _pattern(
        "descending_triangle",
        "Descending Triangle",
        ("Flat-bottom Triangle",),
        COMPRESSION_FAMILY,
        "Bearish",
        "Repeated tests of flat support occur while each reaction high falls.",
        "Price closes below horizontal support after the range contracts.",
        "Price breaks the falling resistance line and holds above it.",
        "Project the triangle’s widest height downward from the breakdown.",
        ((0.02, 0.75), (0.18, 0.28), (0.31, 0.63), (0.44, 0.28), (0.56, 0.52), (0.67, 0.28), (0.77, 0.42), (0.86, 0.27), (0.98, 0.12)),
        (
            _guide((0.14, 0.28), (0.89, 0.28), "Support", "support"),
            _guide((0.04, 0.76), (0.86, 0.34), "Falling resistance", "resistance"),
        ),
        (0.88, 0.24),
        "down",
    ),
    _pattern(
        "symmetrical_triangle",
        "Symmetrical Triangle",
        ("Symmetric Triangle", "Coil"),
        COMPRESSION_FAMILY,
        "Neutral",
        "Lower highs and higher lows compress price toward an apex without confirming direction.",
        "A close outside either boundary confirms direction; follow-through matters more than prediction.",
        "Price immediately re-enters the triangle and crosses toward the opposite boundary.",
        "Project the triangle’s widest height in the confirmed breakout direction.",
        ((0.02, 0.72), (0.18, 0.25), (0.32, 0.63), (0.45, 0.34), (0.58, 0.56), (0.69, 0.41), (0.79, 0.51), (0.88, 0.58), (0.98, 0.76)),
        (
            _guide((0.02, 0.75), (0.86, 0.48), "Upper boundary", "resistance"),
            _guide((0.02, 0.22), (0.86, 0.48), "Lower boundary", "support"),
        ),
        (0.88, 0.58),
        "either",
    ),
    _pattern(
        "rising_wedge",
        "Rising Wedge",
        ("Ascending Wedge",),
        COMPRESSION_FAMILY,
        "Bearish",
        "Price makes higher highs and higher lows inside two rising, converging boundaries.",
        "Price closes below the lower wedge boundary with downside follow-through.",
        "Price reclaims the lower boundary and breaks above the wedge high.",
        "Project the wedge’s widest height downward from the breakdown.",
        ((0.02, 0.22), (0.18, 0.62), (0.31, 0.36), (0.45, 0.68), (0.57, 0.47), (0.69, 0.72), (0.79, 0.57), (0.87, 0.70), (0.94, 0.49), (0.98, 0.28)),
        (
            _guide((0.05, 0.22), (0.90, 0.63), "Rising support", "support"),
            _guide((0.15, 0.65), (0.90, 0.74), "Rising resistance", "resistance"),
        ),
        (0.91, 0.52),
        "down",
    ),
    _pattern(
        "falling_wedge",
        "Falling Wedge",
        ("Descending Wedge",),
        COMPRESSION_FAMILY,
        "Bullish",
        "Price makes lower highs and lower lows inside two falling, converging boundaries.",
        "Price closes above the upper wedge boundary with upside follow-through.",
        "Price loses the upper boundary and breaks below the wedge low.",
        "Project the wedge’s widest height upward from the breakout.",
        ((0.02, 0.78), (0.18, 0.38), (0.31, 0.64), (0.45, 0.32), (0.57, 0.53), (0.69, 0.28), (0.79, 0.43), (0.87, 0.30), (0.94, 0.51), (0.98, 0.72)),
        (
            _guide((0.05, 0.78), (0.90, 0.37), "Falling resistance", "resistance"),
            _guide((0.15, 0.35), (0.90, 0.26), "Falling support", "support"),
        ),
        (0.91, 0.48),
        "up",
    ),
    _pattern(
        "broadening_formation",
        "Broadening Formation",
        ("Megaphone", "Broadening Wedge"),
        COMPRESSION_FAMILY,
        "Neutral",
        "Higher highs and lower lows expand volatility between diverging boundaries.",
        "A close beyond either outer boundary confirms direction; whipsaw risk remains elevated.",
        "Price returns inside the formation and crosses back through its midpoint.",
        "Project the formation’s widest completed swing in the confirmed direction.",
        ((0.02, 0.50), (0.18, 0.62), (0.31, 0.39), (0.45, 0.70), (0.58, 0.30), (0.71, 0.78), (0.84, 0.21), (0.92, 0.81), (0.98, 0.91)),
        (
            _guide((0.05, 0.55), (0.92, 0.83), "Upper boundary", "resistance"),
            _guide((0.05, 0.45), (0.92, 0.18), "Lower boundary", "support"),
        ),
        (0.94, 0.84),
        "either",
    ),
    _pattern(
        "ascending_channel",
        "Ascending Channel",
        ("Rising Channel", "Uptrend Channel"),
        CHANNEL_FAMILY,
        "Bullish",
        "Higher highs and higher lows oscillate between two roughly parallel rising boundaries.",
        "Trend continuation is supported while pullbacks hold the lower channel; an upper break can accelerate.",
        "A sustained close below the lower channel breaks the rising structure.",
        "Use the opposite channel boundary first; on breakout, project the channel height upward.",
        ((0.02, 0.20), (0.17, 0.47), (0.30, 0.31), (0.44, 0.59), (0.57, 0.43), (0.70, 0.71), (0.82, 0.55), (0.91, 0.79), (0.98, 0.91)),
        (
            _guide((0.02, 0.18), (0.91, 0.72), "Channel support", "support"),
            _guide((0.10, 0.49), (0.92, 0.88), "Channel resistance", "resistance"),
        ),
        (0.94, 0.84),
        "up",
    ),
    _pattern(
        "descending_channel",
        "Descending Channel",
        ("Falling Channel", "Downtrend Channel"),
        CHANNEL_FAMILY,
        "Bearish",
        "Lower highs and lower lows oscillate between two roughly parallel falling boundaries.",
        "Trend continuation is supported while rebounds fail at the upper channel; a lower break can accelerate.",
        "A sustained close above the upper channel breaks the falling structure.",
        "Use the opposite channel boundary first; on breakdown, project the channel height downward.",
        ((0.02, 0.80), (0.17, 0.53), (0.30, 0.69), (0.44, 0.41), (0.57, 0.57), (0.70, 0.29), (0.82, 0.45), (0.91, 0.21), (0.98, 0.09)),
        (
            _guide((0.02, 0.82), (0.91, 0.28), "Channel resistance", "resistance"),
            _guide((0.10, 0.51), (0.92, 0.12), "Channel support", "support"),
        ),
        (0.94, 0.16),
        "down",
    ),
)


def _validate_catalog(catalog: tuple[ChartPatternDefinition, ...]) -> None:
    if len(catalog) != 24:
        raise ValueError("The chart-pattern cheat sheet must contain exactly 24 patterns.")
    ids = {pattern.pattern_id for pattern in catalog}
    names = {pattern.name.casefold() for pattern in catalog}
    if len(ids) != len(catalog) or len(names) != len(catalog):
        raise ValueError("Chart-pattern IDs and names must be unique.")
    for pattern in catalog:
        if pattern.family not in CHART_PATTERN_FAMILIES:
            raise ValueError(f"Unknown chart-pattern family: {pattern.family}")
        if pattern.bias not in CHART_PATTERN_BIASES:
            raise ValueError(f"Unknown chart-pattern bias: {pattern.bias}")
        if pattern.direction not in {"up", "down", "either"}:
            raise ValueError(f"Unknown chart-pattern direction: {pattern.direction}")
        if len(pattern.price_path) < 4 or not pattern.guide_lines:
            raise ValueError(f"Incomplete chart-pattern geometry: {pattern.name}")
        points = [*pattern.price_path, pattern.breakout_marker]
        for guide in pattern.guide_lines:
            points.extend((guide.start, guide.end))
        if any(not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) for x, y in points):
            raise ValueError(f"Chart-pattern geometry must be normalized: {pattern.name}")
        if not all((pattern.recognition, pattern.confirmation, pattern.invalidation, pattern.target)):
            raise ValueError(f"Chart-pattern guidance is incomplete: {pattern.name}")


_validate_catalog(CHART_PATTERN_CATALOG)
