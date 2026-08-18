"""Presentation helpers for the Quant page.

Deliberately Qt-free so the smoke tests can exercise row building and formatting without a
``QApplication``, and so the page's theme hook can rebuild every colour-carrying row by simply
calling these again with the new palette.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Sequence

from ..services.quant import DICKEY_FULLER_CRITICAL_VALUES, QuantPairRow, QuantScanPayload, QuantScreenRow
from ..table_cells import TableCell

SCREEN_HEADERS = (
    "Rank",
    "Ticker",
    "Price",
    "1M %",
    "3M %",
    "6M %",
    "12M %",
    "Vol %",
    "Sharpe",
    "Max DD %",
    "Z-Score",
    "RSI",
    "Composite",
)

PAIR_HEADERS = (
    "Rank",
    "Long",
    "Short",
    "Corr",
    "Hedge",
    "Spread Z",
    "Half-life",
    "Hurst",
    "DF stat",
    "Stationary",
    "Score",
)

#: Sort payload for a cell whose real value is unknown. Every cell must carry a finite sort value:
#: ``render_table_rows`` only builds a sortable item when ``sort_value is not None``, so a single
#: ``None`` in a column silently downgrades that whole column to string comparison.
MISSING_SORT_VALUE = float("-inf")

SCREEN_FILTERS = (
    ("All ranked", "all"),
    ("Top quartile", "top_quartile"),
    ("Positive 6M momentum", "momentum"),
    ("Oversold (RSI < 35)", "oversold"),
    ("Overbought (RSI > 65)", "overbought"),
    ("Low volatility", "low_volatility"),
)

PAIR_FILTERS = (
    ("All pairs", "all"),
    ("Stationary (5% or better)", "stationary"),
    ("Spread stretched (|Z| > 2)", "stretched"),
    ("Fast reversion (half-life < 20d)", "fast"),
)

#: Column metadata for the screener: attribute, formatter key, and whether higher is better for
#: colouring. Kept beside the headers so the two cannot drift apart.
_SCREEN_COLUMNS = (
    ("momentum_1m", "percent", True),
    ("momentum_3m", "percent", True),
    ("momentum_6m", "percent", True),
    ("momentum_12m", "percent", True),
    ("volatility_pct", "plain", None),
    ("sharpe", "ratio", True),
    ("max_drawdown_pct", "percent", None),
    ("z_score", "ratio", None),
    ("rsi", "plain", None),
)


def finite_or_none(value: Any) -> float | None:
    """Coerce to a float, treating NaN/inf and non-numerics alike as absent."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_percent(value: Any, digits: int = 1) -> str:
    numeric = finite_or_none(value)
    return f"{numeric:+.{digits}f}%" if numeric is not None else "—"


def format_plain(value: Any, digits: int = 1) -> str:
    numeric = finite_or_none(value)
    return f"{numeric:.{digits}f}" if numeric is not None else "—"


def format_ratio(value: Any, digits: int = 2) -> str:
    numeric = finite_or_none(value)
    return f"{numeric:.{digits}f}" if numeric is not None else "—"


def format_price(value: Any) -> str:
    numeric = finite_or_none(value)
    return f"${numeric:,.2f}" if numeric is not None else "—"


def format_half_life(value: Any) -> str:
    numeric = finite_or_none(value)
    if numeric is None:
        return "—"
    return f"{numeric:.1f}d"


def format_compact_money(value: Any) -> str:
    numeric = finite_or_none(value)
    if numeric is None:
        return "—"
    if abs(numeric) >= 1_000_000_000:
        return f"${numeric / 1_000_000_000:.1f}B"
    if abs(numeric) >= 1_000_000:
        return f"${numeric / 1_000_000:.1f}M"
    return f"${numeric:,.0f}"


_FORMATTERS = {"percent": format_percent, "plain": format_plain, "ratio": format_ratio}


def directional_color(value: Any, colors: Mapping[str, str], higher_is_better: bool | None) -> str | None:
    """Colour a cell green/red by sign, or leave it neutral when direction is meaningless."""

    numeric = finite_or_none(value)
    if numeric is None or higher_is_better is None:
        return None
    favourable = numeric > 0.0 if higher_is_better else numeric < 0.0
    if numeric == 0.0:
        return None
    return colors.get("positive") if favourable else colors.get("negative")


def build_screen_row(
    row: QuantScreenRow,
    *,
    colors: Mapping[str, str],
    ticker_role: Any,
) -> tuple[TableCell, ...]:
    """Build one screener row. Every numeric column carries a finite sort payload."""

    cells = [
        TableCell(
            str(row.rank) if row.rank else "—",
            alignment="right",
            # Missing ranks sort last ascending rather than jumping to the top.
            sort_value=float(row.rank) if row.rank else float("inf"),
        ),
        TableCell(
            row.ticker,
            alignment="left",
            tooltip=row.name or row.ticker,
            data_roles=((ticker_role, row.ticker),),
        ),
        TableCell(
            format_price(row.last_price),
            alignment="right",
            sort_value=finite_or_none(row.last_price) or MISSING_SORT_VALUE,
        ),
    ]
    for attribute, formatter, higher_is_better in _SCREEN_COLUMNS:
        value = getattr(row, attribute)
        numeric = finite_or_none(value)
        cells.append(
            TableCell(
                _FORMATTERS[formatter](value),
                alignment="right",
                foreground=directional_color(value, colors, higher_is_better),
                sort_value=numeric if numeric is not None else MISSING_SORT_VALUE,
            )
        )
    composite = finite_or_none(row.composite)
    cells.append(
        TableCell(
            format_plain(composite),
            alignment="right",
            foreground=colors.get("accent") if composite is not None and composite >= 75.0 else None,
            tooltip="Cross-sectional percentile: 50% momentum, 30% Sharpe, 20% low volatility.",
            sort_value=composite if composite is not None else MISSING_SORT_VALUE,
        )
    )
    return tuple(cells)


def build_screen_rows(
    rows: Sequence[QuantScreenRow],
    *,
    colors: Mapping[str, str],
    ticker_role: Any,
) -> list[tuple[TableCell, ...]]:
    return [build_screen_row(row, colors=colors, ticker_role=ticker_role) for row in rows]


def build_pair_row(
    row: QuantPairRow,
    *,
    colors: Mapping[str, str],
    pair_role: Any,
) -> tuple[TableCell, ...]:
    """Build one pairs row. Every numeric column carries a finite sort payload."""

    spread_z = finite_or_none(row.spread_z)
    stationary_color = colors.get("positive") if row.stationary_at else colors.get("secondary")
    # A stretched spread is the entry condition, so flag it in the same colour language.
    stretch_color = colors.get("warning") if spread_z is not None and abs(spread_z) >= 2.0 else None
    score = finite_or_none(row.score)
    hurst = finite_or_none(row.hurst)
    return (
        TableCell(
            str(row.rank) if row.rank else "—",
            alignment="right",
            sort_value=float(row.rank) if row.rank else float("inf"),
        ),
        TableCell(row.left, alignment="left", data_roles=((pair_role, f"{row.left}/{row.right}"),)),
        TableCell(row.right, alignment="left"),
        TableCell(
            format_ratio(row.correlation),
            alignment="right",
            sort_value=finite_or_none(row.correlation) or MISSING_SORT_VALUE,
        ),
        TableCell(
            format_ratio(row.hedge_ratio, 3),
            alignment="right",
            tooltip="Shares of the short leg per share of the long leg (OLS on price levels).",
            sort_value=finite_or_none(row.hedge_ratio) or MISSING_SORT_VALUE,
        ),
        TableCell(
            format_ratio(spread_z),
            alignment="right",
            foreground=stretch_color,
            sort_value=spread_z if spread_z is not None else MISSING_SORT_VALUE,
        ),
        TableCell(
            format_half_life(row.half_life),
            alignment="right",
            tooltip="Sessions for the spread to close half the gap to its mean.",
            sort_value=finite_or_none(row.half_life) or float("inf"),
        ),
        TableCell(
            format_ratio(hurst),
            alignment="right",
            foreground=colors.get("positive") if hurst is not None and hurst < 0.45 else None,
            tooltip=(
                "Below 0.5 indicates mean reversion, 0.5 a random walk. Estimated from the "
                "log-log slope of increment dispersion, which biases low on short histories — "
                "read it against the other pairs rather than as an absolute."
            ),
            sort_value=hurst if hurst is not None else MISSING_SORT_VALUE,
        ),
        TableCell(
            format_ratio(row.dickey_fuller),
            alignment="right",
            tooltip=describe_dickey_fuller(row.dickey_fuller, row.stationary_at),
            sort_value=finite_or_none(row.dickey_fuller) or MISSING_SORT_VALUE,
        ),
        TableCell(
            row.stationary_at or "no",
            foreground=stationary_color,
            sort_value=_stationary_sort_value(row.stationary_at),
        ),
        TableCell(
            format_plain(score),
            alignment="right",
            foreground=colors.get("accent") if score is not None and score >= 60.0 else None,
            sort_value=score if score is not None else MISSING_SORT_VALUE,
        ),
    )


def build_pair_rows(
    rows: Sequence[QuantPairRow],
    *,
    colors: Mapping[str, str],
    pair_role: Any,
) -> list[tuple[TableCell, ...]]:
    return [build_pair_row(row, colors=colors, pair_role=pair_role) for row in rows]


def _stationary_sort_value(label: Any) -> float:
    return {"1%": 3.0, "5%": 2.0, "10%": 1.0}.get(str(label or ""), 0.0)


def describe_dickey_fuller(statistic: Any, stationary_at: Any) -> str:
    """Explain the stationarity verdict without implying a p-value we cannot compute."""

    numeric = finite_or_none(statistic)
    if numeric is None:
        return "Dickey-Fuller (constant, no lags): not enough history."
    thresholds = ", ".join(
        f"{label} {value:.2f}" for label, value in sorted(DICKEY_FULLER_CRITICAL_VALUES.items())
    )
    verdict = (
        f"stationary at the {stationary_at} level"
        if stationary_at
        else "not stationary at the 10% level"
    )
    return f"Dickey-Fuller (constant, no lags) = {numeric:.2f}; {verdict}. Critical values: {thresholds}."


def filter_screen_rows(rows: Sequence[QuantScreenRow], key: str) -> list[QuantScreenRow]:
    """Apply one screener filter, leaving rows with no value for the tested factor out."""

    if key == "top_quartile":
        return [row for row in rows if (finite_or_none(row.composite) or 0.0) >= 75.0]
    if key == "momentum":
        return [row for row in rows if (finite_or_none(row.momentum_6m) or 0.0) > 0.0]
    if key == "oversold":
        return [row for row in rows if (value := finite_or_none(row.rsi)) is not None and value < 35.0]
    if key == "overbought":
        return [row for row in rows if (value := finite_or_none(row.rsi)) is not None and value > 65.0]
    if key == "low_volatility":
        volatilities = [
            value for row in rows if (value := finite_or_none(row.volatility_pct)) is not None
        ]
        if not volatilities:
            return list(rows)
        median = sorted(volatilities)[len(volatilities) // 2]
        return [
            row
            for row in rows
            if (value := finite_or_none(row.volatility_pct)) is not None and value <= median
        ]
    return list(rows)


def filter_pair_rows(rows: Sequence[QuantPairRow], key: str) -> list[QuantPairRow]:
    """Apply one pairs filter."""

    if key == "stationary":
        return [row for row in rows if row.stationary_at in {"1%", "5%"}]
    if key == "stretched":
        return [
            row
            for row in rows
            if (value := finite_or_none(row.spread_z)) is not None and abs(value) >= 2.0
        ]
    if key == "fast":
        return [
            row
            for row in rows
            if (value := finite_or_none(row.half_life)) is not None and value < 20.0
        ]
    return list(rows)


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
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 36:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def describe_scan_freshness(payload: QuantScanPayload | None) -> tuple[str, str]:
    """Summarize a completed scan for the status line."""

    if payload is None or not payload.rows:
        return "No Quant scan yet. Run a scan to source and rank a universe.", "muted"
    completed = as_naive_local(payload.completed_at)
    age = format_age(dt.datetime.now() - completed) if completed else "just now"
    detail = f"{len(payload.rows)} ranked, {len(payload.pairs)} pair(s) — scanned {age}"
    if payload.errors:
        return f"{detail}; {len(payload.errors)} ticker(s) returned incomplete data.", "warning"
    return detail, "positive"


def summarize_metrics(payload: QuantScanPayload | None) -> dict[str, str]:
    """Values for the metric strip above the screener table."""

    if payload is None or not payload.rows:
        return {key: "—" for key in ("ranked", "universe", "pairs", "stationary", "leader", "errors")}
    stationary = [row for row in payload.pairs if row.stationary_at in {"1%", "5%"}]
    leader = payload.rows[0] if payload.rows else None
    return {
        "ranked": str(len(payload.rows)),
        "universe": str(payload.universe_size),
        "pairs": str(len(payload.pairs)),
        "stationary": str(len(stationary)),
        "leader": f"{leader.ticker} ({format_plain(leader.composite)})" if leader else "—",
        "errors": str(len(payload.errors)),
    }


def build_pair_detail_lines(detail: Mapping[str, Any]) -> list[str]:
    """Human-readable summary of one analysed pair."""

    hedge = finite_or_none(detail.get("hedge_ratio"))
    spread_z = finite_or_none(detail.get("latest_z"))
    left = str(detail.get("left") or "")
    right = str(detail.get("right") or "")
    lines = [
        f"Pair: long {left} / short {right}",
        f"Hedge ratio: {format_ratio(hedge, 3)} shares of {right} per share of {left}",
        f"Correlation of daily returns: {format_ratio(detail.get('correlation'))}",
        f"Spread Z-score: {format_ratio(spread_z)}",
        f"Half-life of mean reversion: {format_half_life(detail.get('half_life'))}",
        f"Hurst exponent: {format_ratio(detail.get('hurst'))}",
        describe_dickey_fuller(detail.get("dickey_fuller"), detail.get("stationary_at")),
        f"Overlapping sessions: {int(detail.get('observations') or 0)}",
    ]
    if spread_z is not None and abs(spread_z) >= 2.0:
        direction = "short the spread" if spread_z > 0 else "long the spread"
        lines.append(f"Spread is stretched beyond 2 sigma — the mean-reversion setup is to {direction}.")
    return lines
