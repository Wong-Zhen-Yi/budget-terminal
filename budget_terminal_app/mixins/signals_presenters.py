"""Presentation helpers for the Signals page.

Deliberately Qt-free so the smoke tests can exercise row building and formatting without a
``QApplication``, and so the page's theme hook can rebuild every colour-carrying row by simply
calling these again with the new palette.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable, Mapping, Sequence

from ..services.signal_models import SignalClass, SignalResult, TradeStatus
from ..table_cells import TableCell

SIGNAL_HEADERS = (
    "Rank",
    "Ticker",
    "Price",
    "Market Cap",
    "20D $ Volume",
    "Score",
    "Signal",
    "Trade Status",
)

SIGNAL_RANK = {
    SignalClass.NONE: 0,
    SignalClass.WATCH: 1,
    SignalClass.LONG: 2,
    SignalClass.STRONG_LONG: 3,
}

#: Sort payload for a cell whose real value is unknown. Every cell must carry a finite sort value:
#: ``render_table_rows`` only builds a sortable item when ``sort_value is not None``, so a single
#: ``None`` in a column silently downgrades that whole column to string comparison.
MISSING_SORT_VALUE = float("-inf")

ROLE_LABELS = {
    "trend": "Trend (daily)",
    "momentum": "Momentum (hourly)",
    "setup": "Setup (5-minute)",
    "entry": "Entry (1-minute)",
    "relative": "Relative strength (vs benchmark)",
}

INDICATOR_FIELDS = (
    ("EMA20", "ema20", "$"),
    ("EMA50", "ema50", "$"),
    ("EMA200", "ema200", "$"),
    ("RSI", "rsi", ""),
    ("MACD", "macd", ""),
    ("MACD signal", "macd_signal", ""),
    ("MACD histogram", "macd_histogram", ""),
    ("VWAP", "vwap", "$"),
    ("VWAP distance", "vwap_distance_pct", "%"),
    ("Relative volume", "relative_volume", "x"),
    ("Prior 20-bar high", "breakout_level", "$"),
    ("ATR (daily)", "atr", "$"),
    # The setup ATR grades the breakout, which carries the single heaviest weight.
    ("ATR (setup)", "atr_setup", "$"),
    ("ATR (entry)", "atr_entry", "$"),
    ("Relative strength (long)", "relative_strength_long_pct", "%"),
    ("Relative strength (short)", "relative_strength_short_pct", "%"),
)

SCORE_COMPONENTS = (
    ("Trend", "trend_score", "trend_max_score", "Daily direction"),
    ("Momentum", "momentum_score", "momentum_max_score", "Hourly structure"),
    ("Volume", "volume_score", "volume_max_score", "5-minute confirmation"),
    ("Entry", "entry_score", "entry_max_score", "5-minute breakout + 1-minute VWAP"),
    ("Relative strength", "relative_score", "relative_max_score", "Daily excess return vs benchmark"),
)


def finite_or_none(value: Any) -> float | None:
    """Coerce to a float, treating NaN/inf and non-numerics alike as absent."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_compact_money(value: Any) -> str:
    numeric = finite_or_none(value)
    if numeric is None:
        return "—"
    if abs(numeric) >= 1_000_000_000:
        return f"${numeric / 1_000_000_000:.1f}B"
    if abs(numeric) >= 1_000_000:
        return f"${numeric / 1_000_000:.1f}M"
    return f"${numeric:,.0f}"


def format_price(value: Any) -> str:
    numeric = finite_or_none(value)
    return f"${numeric:,.2f}" if numeric is not None else "—"


def score_fraction(result: SignalResult) -> float:
    """A result's score as a share of the points that were available to it."""

    maximum = finite_or_none(result.max_score) or 0.0
    if maximum <= 0.0:
        return 0.0
    return (finite_or_none(result.raw_score) or 0.0) / maximum


def format_score(score: Any, maximum: Any) -> str:
    def display(value: Any) -> str:
        numeric = finite_or_none(value) or 0.0
        return str(int(numeric)) if float(numeric).is_integer() else f"{numeric:.1f}"

    return f"{display(score)}/{display(maximum)}"


def as_naive_local(value: Any) -> dt.datetime | None:
    """Coerce a timestamp to naive local time so ages can be measured against ``datetime.now()``.

    The payload mixes both kinds: the universe stamps ``sourced_at`` in UTC via a tz-aware clock,
    while the scan stamps ``started_at``/``completed_at`` with a naive local one. Subtracting one
    from the other raises, so every age calculation normalizes first.
    """

    if not isinstance(value, dt.datetime):
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def format_age(delta: dt.timedelta) -> str:
    """Render an elapsed duration in the coarsest unit that still reads precisely."""

    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return "1 day ago" if days == 1 else f"{days} days ago"


def result_color(result: SignalResult, colors: Mapping[str, str]) -> str:
    if result.trade_status is TradeStatus.INSUFFICIENT_HISTORY:
        # Benign: the feed answered, the symbol is just too young. Muted, not alarming red.
        return colors.get("secondary", "")
    if result.trade_status is TradeStatus.DATA_ERROR:
        return colors.get("negative", "")
    if result.trade_status is TradeStatus.TOO_EXTENDED:
        return colors.get("warning", "")
    if result.signal in {SignalClass.LONG, SignalClass.STRONG_LONG}:
        return colors.get("positive", "")
    if result.signal is SignalClass.WATCH:
        return colors.get("warning", "")
    return colors.get("secondary", "")


def build_signal_row(
    candidate: Any,
    result: SignalResult,
    *,
    colors: Mapping[str, str],
    ticker_role: Any,
) -> tuple[TableCell, ...]:
    """Build one results row. Every numeric column carries a finite sort payload."""

    rank = int(getattr(candidate, "quality_rank", 0)) if candidate is not None else None
    market_cap = finite_or_none(getattr(candidate, "market_cap", None)) if candidate is not None else None
    dollar_volume = (
        finite_or_none(getattr(candidate, "median_dollar_volume", None)) if candidate is not None else None
    )
    price = finite_or_none(result.price)
    if price is None and candidate is not None:
        price = finite_or_none(getattr(candidate, "price", None))
    color = result_color(result, colors)
    return (
        TableCell(
            str(rank) if rank else "—",
            alignment="right",
            # Missing ranks sort last ascending rather than jumping to the top.
            sort_value=float(rank) if rank else float("inf"),
        ),
        TableCell(result.ticker, foreground=color, data_roles=((ticker_role, result.ticker),)),
        TableCell(
            format_price(price),
            alignment="right",
            foreground=color,
            sort_value=price if price is not None else MISSING_SORT_VALUE,
        ),
        TableCell(
            format_compact_money(market_cap),
            alignment="right",
            sort_value=market_cap if market_cap is not None else MISSING_SORT_VALUE,
        ),
        TableCell(
            format_compact_money(dollar_volume),
            alignment="right",
            sort_value=dollar_volume if dollar_volume is not None else MISSING_SORT_VALUE,
        ),
        TableCell(
            format_score(result.raw_score, result.max_score),
            alignment="right",
            foreground=color,
            # Sort on the fraction, not the raw points: a scan whose benchmark was unavailable
            # scores every row out of a smaller maximum, and raw points would rank those rows
            # below an equally strong scan that had one.
            sort_value=score_fraction(result),
        ),
        TableCell(
            result.signal_label,
            foreground=color,
            sort_value=float(SIGNAL_RANK.get(result.signal, 0)),
        ),
        TableCell(
            result.trade_status_label,
            foreground=color,
            tooltip=result.error or "\n".join(result.warnings),
            sort_value=float(SIGNAL_RANK.get(result.signal, 0)),
        ),
    )


def build_signal_rows(
    candidates: Mapping[str, Any],
    results: Sequence[SignalResult],
    *,
    colors: Mapping[str, str],
    ticker_role: Any,
) -> list[tuple[TableCell, ...]]:
    return [
        build_signal_row(candidates.get(result.ticker), result, colors=colors, ticker_role=ticker_role)
        for result in results
    ]


def build_score_component_rows(result: SignalResult) -> list[tuple[TableCell, ...]]:
    rows = []
    for name, score_attr, max_attr, evidence in SCORE_COMPONENTS:
        score = getattr(result, score_attr, 0.0)
        maximum = getattr(result, max_attr, 0.0)
        rows.append((
            TableCell(name, alignment="left"),
            TableCell(format_score(score, maximum), alignment="right", sort_value=finite_or_none(score) or 0.0),
            TableCell(evidence, alignment="left"),
        ))
    return rows


def build_indicator_lines(result: SignalResult) -> list[str]:
    lines = []
    for label, key, unit in INDICATOR_FIELDS:
        numeric = finite_or_none(result.indicators.get(key))
        if numeric is None:
            text = "Unavailable"
        elif unit == "$":
            text = f"${numeric:,.2f}"
        else:
            text = f"{numeric:,.2f}{unit}"
        lines.append(f"{label}: {text}")
    return lines


def build_reason_lines(candidate: Any, result: SignalResult) -> list[str]:
    """Render each check as awarded-out-of-available.

    Checks award a fraction of their weight, so a single glyph and a bare point total would report
    a check that earned most of its weight identically to one that barely registered.
    """

    quality = [f"✓ {reason}" for reason in (getattr(candidate, "reasons", ()) or ())]
    signal_lines = []
    for reason in result.reasons:
        points = finite_or_none(reason.points) or 0.0
        weight = finite_or_none(getattr(reason, "weight", None)) or 0.0
        if weight > 0.0 and points >= weight - 1e-9:
            glyph = "✓"
        elif points > 0.0:
            glyph = "◐"
        else:
            glyph = "○"
        awarded = f"+{format(round(points, 2), 'g')}"
        if weight > 0.0:
            awarded = f"{awarded} of {format(round(weight, 2), 'g')}"
        signal_lines.append(f"{glyph} {reason.name} ({awarded})\n   {reason.description}")
    return quality + ([""] if quality and signal_lines else []) + signal_lines


def describe_timeframe_bar(role: str, result: SignalResult) -> str:
    """One line per role covering both availability and which bar was actually scored."""

    label = ROLE_LABELS.get(role, role.title())
    status = result.timeframe_status.get(role, "Unknown")
    provenance = result.timeframe_bars.get(role) or {}
    as_of = provenance.get("as_of")
    parts = [status]
    if as_of:
        parts.append(f"bar {str(as_of).replace('T', ' ')} UTC")
    if provenance.get("dropped"):
        parts.append("live bar excluded")
    elif provenance.get("partial"):
        parts.append("bar still forming")
    return f"{label}: {' · '.join(parts)}"


def build_warning_lines(result: SignalResult) -> list[str]:
    warnings = [f"⚠ {item}" for item in result.warnings]
    timeframes = [describe_timeframe_bar(role, result) for role in ROLE_LABELS if role in result.timeframe_status]
    if not warnings and not timeframes:
        return ["No warnings."]
    return [*warnings, *([""] if warnings and timeframes else []), *timeframes]


def describe_scan_freshness(payload: Any, now: dt.datetime | None = None) -> tuple[str, str]:
    """Summarize a scan's age and health as ``(text, status)``.

    Cached payloads are accepted for up to a week, so the timestamp must carry its date. Showing
    only a clock time made a scan from several days ago read as if it had just run.
    """

    if payload is None:
        return "No scan yet — click Refresh now.", "muted"
    completed = as_naive_local(getattr(payload, "completed_at", None))
    if completed is None:
        return "Scan time unknown.", "warning"
    reference = as_naive_local(now) or dt.datetime.now()
    age = reference - completed
    stamp = completed.strftime("%Y-%m-%d %H:%M")
    results = list(getattr(payload, "results", []) or [])
    counts = summarize_results(results)
    text = f"Last scan {stamp} · {format_age(age)} · {len(results)} ticker(s) · {getattr(payload, 'source', '')}".rstrip(" ·")
    # Count genuine fetch failures only. A symbol that is too young to score is reported
    # separately so it never inflates the error count the user is trying to drive to zero.
    if counts["errors"]:
        text += f" · {counts['errors']} data error(s)"
    if counts["too_new"]:
        text += f" · {counts['too_new']} too new to score"
    if age >= dt.timedelta(hours=12):
        return f"{text} · stale", "warning"
    if counts["errors"]:
        return text, "warning"
    return text, "positive"


def summarize_results(results: Iterable[SignalResult]) -> dict[str, int]:
    """Count results by outcome for the metric strip."""

    items = list(results)
    return {
        "total": len(items),
        "valid_long": sum(1 for item in items if item.trade_status is TradeStatus.VALID_LONG),
        "blocked": sum(1 for item in items if item.trade_status is TradeStatus.TOO_EXTENDED),
        "watch": sum(1 for item in items if item.trade_status is TradeStatus.WATCH),
        "errors": sum(1 for item in items if item.trade_status is TradeStatus.DATA_ERROR),
        "too_new": sum(1 for item in items if item.trade_status is TradeStatus.INSUFFICIENT_HISTORY),
    }


def describe_universe(payload: Any, now: dt.datetime | None = None) -> str:
    if payload is None:
        return "Universe has not been sourced yet. Click Refresh now to run a scan."
    sourced_at = as_naive_local(getattr(payload, "sourced_at", None))
    reference = as_naive_local(now) or dt.datetime.now()
    when = (
        f"{sourced_at.strftime('%Y-%m-%d %H:%M')} ({format_age(reference - sourced_at)})"
        if sourced_at is not None
        else "unknown"
    )
    cache_label = "cached universe" if getattr(payload, "universe_from_cache", False) else "live universe refresh"
    passed = int(getattr(payload, "passed_filter_count", 0) or 0)
    shortlisted = len(list(getattr(payload, "candidates", []) or []))
    return (
        f"Universe sourced {when} · {getattr(payload, 'source_candidate_count', 0)} screened · "
        f"{passed or shortlisted} passed filters · {shortlisted} shortlisted · "
        f"{getattr(payload, 'rejected_candidate_count', 0)} rejected · {cache_label}"
    )
