"""Presentation helpers for the Economic page.

Deliberately Qt-free so the smoke tests can exercise row building and formatting without a
``QApplication``, and so the page's theme hook can rebuild every colour-carrying row by simply
calling these again with the new palette. Mirrors ``mixins/quant_presenters``.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..services.economic import (
    ECONOMIC_GROUPS,
    HEADLINE_SERIES,
    PROVIDER_LABELS,
    SERIES_BY_ID,
    format_change,
    format_value,
    normalize_name_list,
)
from ..table_cells import TableCell

OVERVIEW_HEADERS = ('Indicator', 'Group', 'Latest', 'As of', 'Prior', 'Change', 'YoY %', 'Source')
GROUP_HEADERS = ('Indicator', 'Latest', 'As of', 'Prior', 'Change', 'YoY %', 'Notes')
CURVE_HEADERS = ('Tenor', 'Yield', 'vs 3M', 'vs 10Y')

#: Sort payload for a cell whose real value is unknown. Every cell must carry a finite sort
#: value: ``render_table_rows`` only builds a sortable item when ``sort_value is not None``, so
#: a single ``None`` in a column silently downgrades that whole column to string comparison.
MISSING_SORT_VALUE = float('-inf')

#: Overview filters, mirroring the persisted ``group_filter`` values.
GROUP_FILTERS = (('All groups', 'all'),) + tuple((name, name.lower()) for name in ECONOMIC_GROUPS)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return number


def _sort_value(value: Any) -> float:
    number = _finite(value)
    return MISSING_SORT_VALUE if number is None else number


def _change_color(row: Mapping[str, Any], value: Any, colors: Mapping[str, str]) -> str | None:
    """Colour a change by whether it moved the indicator in the helpful direction.

    ``higher_is_better`` is deliberately tri-state: ``None`` means the direction carries no
    good/bad meaning (a participation rate reading, a breakeven), so those stay neutral rather
    than being painted with a misleading judgement.
    """
    number = _finite(value)
    if number is None or number == 0.0:
        return None
    preference = row.get('higher_is_better')
    if preference is None:
        return None
    helpful = (number > 0.0) if bool(preference) else (number < 0.0)
    return colors.get('positive') if helpful else colors.get('negative')


def filter_rows(rows: Any, group_key: Any) -> list[dict[str, Any]]:
    """Restrict overview rows to one group, or return them all."""
    items = [row for row in list(rows or []) if isinstance(row, dict)]
    key = str(group_key or 'all').strip().lower()
    if key in ('', 'all'):
        return items
    return [row for row in items if str(row.get('group', '')).strip().lower() == key]


def drop_unavailable(rows: Any) -> list[dict[str, Any]]:
    """Keep only rows whose provider actually returned an observation.

    A provider the current network cannot reach leaves a long run of em dashes that reads as a
    broken page, so the tables hide those by default and the status line carries the count.
    """
    return [row for row in list(rows or []) if isinstance(row, dict) and row.get('available')]


def search_rows(rows: Any, text: Any) -> list[dict[str, Any]]:
    """Match the search box against both the display label and the FRED series id."""
    items = [row for row in list(rows or []) if isinstance(row, dict)]
    needle = str(text or '').strip().upper()
    if not needle:
        return items
    return [
        row for row in items
        if needle in str(row.get('label', '')).upper() or needle in str(row.get('series_id', '')).upper()
    ]


def rows_for_group(rows: Any, group: Any) -> list[dict[str, Any]]:
    """Return the rows belonging to one catalog group, in catalog order."""
    name = str(group or '').strip()
    return [row for row in list(rows or []) if isinstance(row, dict) and str(row.get('group')) == name]


def _common_cells(row: Mapping[str, Any], colors: Mapping[str, str]) -> list[TableCell]:
    units = row.get('units')
    decimals = row.get('decimals', 1)
    latest = row.get('latest')
    prior = row.get('prior')
    change = row.get('change')
    yoy = row.get('yoy')
    return [
        TableCell(
            text=format_value(latest, units, decimals),
            alignment='right',
            sort_value=_sort_value(latest),
        ),
        TableCell(text=str(row.get('latest_date') or '—'), alignment='center'),
        TableCell(
            text=format_value(prior, units, decimals),
            alignment='right',
            foreground=colors.get('secondary'),
            sort_value=_sort_value(prior),
        ),
        TableCell(
            text=format_change(change, units, decimals),
            alignment='right',
            foreground=_change_color(row, change, colors),
            sort_value=_sort_value(change),
        ),
        TableCell(
            text='—' if _finite(yoy) is None else f'{float(yoy):+,.1f}%',
            alignment='right',
            sort_value=_sort_value(yoy),
        ),
    ]


def build_overview_rows(
    rows: Any,
    *,
    colors: Mapping[str, str],
    series_role: Any = None,
) -> list[tuple[TableCell, ...]]:
    """Build the Overview table, which spans every group."""
    built: list[tuple[TableCell, ...]] = []
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        series_id = str(row.get('series_id') or '')
        data_roles = ((series_role, series_id),) if series_role is not None else ()
        label = TableCell(
            text=str(row.get('label') or series_id),
            alignment='left',
            tooltip=_tooltip(row),
            data_roles=data_roles,
        )
        group = TableCell(text=str(row.get('group') or ''), alignment='center', foreground=colors.get('secondary'))
        source = TableCell(
            text=str(row.get('source') or ''),
            alignment='left',
            foreground=colors.get('secondary'),
        )
        built.append(tuple([label, group, *_common_cells(row, colors), source]))
    return built


def build_group_rows(
    rows: Any,
    *,
    colors: Mapping[str, str],
    series_role: Any = None,
) -> list[tuple[TableCell, ...]]:
    """Build one group tab's table, which trades the Group column for the source note."""
    built: list[tuple[TableCell, ...]] = []
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        series_id = str(row.get('series_id') or '')
        data_roles = ((series_role, series_id),) if series_role is not None else ()
        label = TableCell(
            text=str(row.get('label') or series_id),
            alignment='left',
            tooltip=_tooltip(row),
            data_roles=data_roles,
        )
        note = TableCell(
            text=str(row.get('note') or row.get('source') or series_id),
            alignment='left',
            foreground=colors.get('secondary'),
        )
        built.append(tuple([label, *_common_cells(row, colors), note]))
    return built


def build_curve_rows(curve: Any, *, colors: Mapping[str, str]) -> list[tuple[TableCell, ...]]:
    """Build the tenor-by-tenor table beside the yield-curve plot."""
    tenors = [item for item in (curve or {}).get('tenors', []) if isinstance(item, dict)]
    lookup = {str(item.get('series_id')): _finite(item.get('yield')) for item in tenors}
    front = lookup.get('DGS3MO')
    ten_year = lookup.get('DGS10')
    built: list[tuple[TableCell, ...]] = []
    for item in tenors:
        value = _finite(item.get('yield'))
        vs_front = None if value is None or front is None else value - front
        vs_ten = None if value is None or ten_year is None else value - ten_year
        built.append((
            TableCell(text=str(item.get('label') or ''), alignment='left', sort_value=_sort_value(item.get('years'))),
            TableCell(text=format_value(value, 'percent', 2), alignment='right', sort_value=_sort_value(value)),
            TableCell(
                text='—' if vs_front is None else f'{vs_front:+,.2f}',
                alignment='right',
                foreground=None if vs_front is None or vs_front >= 0 else colors.get('negative'),
                sort_value=_sort_value(vs_front),
            ),
            TableCell(
                text='—' if vs_ten is None else f'{vs_ten:+,.2f}',
                alignment='right',
                sort_value=_sort_value(vs_ten),
            ),
        ))
    return built


def _tooltip(row: Mapping[str, Any]) -> str:
    parts = []
    source = str(row.get('source') or '').strip()
    if source:
        parts.append(source)
    frequency = str(row.get('frequency') or '').strip()
    if frequency:
        parts.append(frequency.capitalize())
    note = str(row.get('note') or '').strip()
    if note:
        parts.append(note)
    if not row.get('available'):
        parts.append('No data returned by this provider.')
    return ' · '.join(parts)


def summarize_headlines(payload: Any) -> dict[str, str]:
    """Format the headline tiles, keyed by FRED series id."""
    rows = {}
    for row in (payload or {}).get('rows', []) if isinstance(payload, dict) else []:
        if isinstance(row, dict) and row.get('series_id'):
            rows[str(row['series_id'])] = row
    summary: dict[str, str] = {}
    for series_id in HEADLINE_SERIES:
        row = rows.get(series_id)
        if not isinstance(row, dict):
            summary[series_id] = '—'
            continue
        summary[series_id] = format_value(row.get('latest'), row.get('units'), row.get('decimals', 1))
    return summary


def headline_captions() -> tuple[tuple[str, str], ...]:
    """Return ``(series_id, caption)`` for the headline strip, in display order."""
    captions = []
    for series_id in HEADLINE_SERIES:
        series = SERIES_BY_ID.get(series_id)
        captions.append((series_id, series.label if series is not None else series_id))
    return tuple(captions)


def describe_curve(curve: Any) -> str:
    """One line summarizing the shape of the treasury curve."""
    data = curve if isinstance(curve, dict) else {}
    tenors = [item for item in data.get('tenors', []) if isinstance(item, dict)]
    if not tenors:
        return 'Treasury curve unavailable.'
    as_of = str(tenors[-1].get('date') or '')
    spread = _finite(data.get('spread_10y2y'))
    if spread is None:
        return f'Treasury curve as of {as_of}.' if as_of else 'Treasury curve loaded.'
    shape = 'inverted' if spread < 0 else 'flat' if abs(spread) < 0.15 else 'upward sloping'
    body = f'10Y-2Y at {spread:+,.2f} pp — curve is {shape}.'
    return f'{body} As of {as_of}.' if as_of else body


def history_series(row: Any, *, years: Any = None) -> tuple[list[str], list[float]]:
    """Split a row's stored history into parallel date and value lists for plotting."""
    points = (row or {}).get('history', []) if isinstance(row, dict) else []
    dates: list[str] = []
    values: list[float] = []
    for point in list(points or []):
        try:
            stamp, value = point[0], point[1]
        except (TypeError, IndexError, KeyError):
            continue
        number = _finite(value)
        if number is None:
            continue
        dates.append(str(stamp))
        values.append(number)
    limit = _finite(years)
    if limit is not None and limit > 0 and dates:
        cutoff = _shift_years(dates[-1], limit)
        if cutoff is not None:
            kept = [index for index, stamp in enumerate(dates) if stamp >= cutoff]
            if kept:
                start = kept[0]
                dates, values = dates[start:], values[start:]
    return dates, values


def _shift_years(iso_date: Any, years: float) -> str | None:
    text = str(iso_date or '')
    if len(text) < 10:
        return None
    try:
        year = int(text[:4]) - int(round(years))
    except ValueError:
        return None
    return f'{year:04d}{text[4:10]}'


def missing_summary(payload: Any) -> str:
    """Describe which series came back empty and which provider owed them."""
    document = payload if isinstance(payload, dict) else {}
    names = set(normalize_name_list(document.get('missing')))
    if not names:
        return ''
    owners: dict[str, list[str]] = {}
    for row in document.get('rows', []) or []:
        if not isinstance(row, dict) or str(row.get('series_id')) not in names:
            continue
        provider = PROVIDER_LABELS.get(str(row.get('provider')), str(row.get('provider') or 'unknown'))
        owners.setdefault(provider, []).append(str(row.get('label') or row.get('series_id')))
    if not owners:
        return f'{len(names)} series unavailable.'
    parts = [f'{name} ({len(labels)})' for name, labels in sorted(owners.items())]
    down = {PROVIDER_LABELS.get(item, item) for item in normalize_name_list(document.get('unreachable'))}
    tail = f' Unreachable from this network: {", ".join(sorted(down))}.' if down else ''
    return f'{len(names)} series unavailable — {", ".join(parts)}.{tail}'
