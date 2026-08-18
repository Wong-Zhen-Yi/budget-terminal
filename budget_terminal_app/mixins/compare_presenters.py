"""Presentation helpers for the Charts page Compare subtab.

Deliberately Qt-free so the smoke tests can exercise cell building and heatmap colouring without a
``QApplication``, and so the page's theme hook can rebuild every colour-carrying row by simply
calling these again with the new palette.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..services.compare_analysis import mix_hex_color
from ..table_cells import TableCell, TableRow

CORRELATION_STRONG_THRESHOLD = 0.6
CORRELATION_MIN_TINT = 0.15
CORRELATION_MAX_TINT = 0.85


def build_correlation_headers(symbols: Sequence[str]) -> tuple[str, ...]:
    """Return the correlation table header labels, including the leading row-label column."""
    return ("", *[str(symbol) for symbol in symbols])


def correlation_cell_background(value: Any, colors: Mapping[str, str]) -> str:
    """Return the diverging heatmap colour for one correlation value."""
    neutral = colors.get("neutral", "#202020")
    if value is None:
        return neutral
    strength = min(abs(float(value)), 1.0)
    target = colors.get("positive", "#3bc27c") if float(value) >= 0.0 else colors.get("negative", "#ff5a5a")
    return mix_hex_color(neutral, target, CORRELATION_MIN_TINT + CORRELATION_MAX_TINT * strength)


def _correlation_cell(
    value: Any,
    *,
    observations: Any,
    row_symbol: str,
    column_symbol: str,
    colors: Mapping[str, str],
    min_observations: int,
) -> TableCell:
    """Build one heatmap-coloured correlation cell."""
    if row_symbol == column_symbol:
        return TableCell(
            text="1.00",
            foreground=colors.get("muted"),
            background=colors.get("neutral"),
            tooltip=f"{row_symbol} versus itself.",
        )
    if value is None:
        shared = int(observations or 0)
        return TableCell(
            text="--",
            foreground=colors.get("muted"),
            background=colors.get("neutral"),
            tooltip=f"{row_symbol} vs {column_symbol}\nOnly {shared} shared period(s); {min_observations} required.",
        )
    numeric = float(value)
    strong = abs(numeric) > CORRELATION_STRONG_THRESHOLD
    return TableCell(
        text=f"{numeric:.2f}",
        foreground=colors.get("contrast_text") if strong else colors.get("text_primary"),
        background=correlation_cell_background(numeric, colors),
        tooltip=f"{row_symbol} vs {column_symbol}\nr = {numeric:.3f}\nn = {int(observations or 0)} periods",
    )


def build_correlation_rows(
    payload: Mapping[str, Any],
    *,
    colors: Mapping[str, str],
    series_colors: Sequence[str] = (),
) -> list[TableRow]:
    """Build the correlation matrix rows, one per compared ticker."""
    symbols = [str(symbol) for symbol in payload.get("symbols", [])]
    matrix = list(payload.get("matrix", []) or [])
    observations = list(payload.get("observations", []) or [])
    try:
        min_observations = int(payload.get("min_observations", 0) or 0)
    except (TypeError, ValueError):
        min_observations = 0
    rows: list[TableRow] = []
    for row_index, row_symbol in enumerate(symbols):
        matrix_row = list(matrix[row_index]) if row_index < len(matrix) else []
        observation_row = list(observations[row_index]) if row_index < len(observations) else []
        label_color = series_colors[row_index] if row_index < len(series_colors) else colors.get("text_primary")
        cells = [
            TableCell(
                text=row_symbol,
                alignment="left",
                foreground=label_color,
                background=colors.get("header"),
                tooltip=f"Correlation of {row_symbol} against every other compared ticker.",
            )
        ]
        for column_index, column_symbol in enumerate(symbols):
            cells.append(
                _correlation_cell(
                    matrix_row[column_index] if column_index < len(matrix_row) else None,
                    observations=observation_row[column_index] if column_index < len(observation_row) else 0,
                    row_symbol=row_symbol,
                    column_symbol=column_symbol,
                    colors=colors,
                    min_observations=min_observations,
                )
            )
        rows.append(tuple(cells))
    return rows
