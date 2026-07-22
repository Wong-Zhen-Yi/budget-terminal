from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SectorStats:
    total: int
    quote_count: int
    average_change: float | None
    advancers: int
    decliners: int
    unchanged: int
    leaders: tuple[tuple[str, float], ...]
    laggards: tuple[tuple[str, float], ...]


def _snapshot_value(snapshot: Any, key: str) -> Any:
    if isinstance(snapshot, dict):
        return snapshot.get(key)
    return getattr(snapshot, key, None)


def calculate_sector_stats(symbols: Iterable[str], results: dict[str, Any]) -> SectorStats:
    normalized_symbols = [str(symbol or "").strip().upper() for symbol in symbols]
    normalized_symbols = [symbol for symbol in normalized_symbols if symbol]
    changes: list[tuple[str, float]] = []
    quote_count = 0
    advancers = 0
    decliners = 0
    unchanged = 0
    for symbol in normalized_symbols:
        snapshot = results.get(symbol)
        price = _snapshot_value(snapshot, "price")
        if isinstance(price, (int, float)):
            quote_count += 1
        change = _snapshot_value(snapshot, "change")
        if not isinstance(change, (int, float)):
            continue
        numeric_change = float(change)
        changes.append((symbol, numeric_change))
        if numeric_change > 0:
            advancers += 1
        elif numeric_change < 0:
            decliners += 1
        else:
            unchanged += 1
    ordered = sorted(changes, key=lambda item: item[1], reverse=True)
    average = sum(change for _symbol, change in changes) / len(changes) if changes else None
    return SectorStats(
        total=len(normalized_symbols),
        quote_count=quote_count,
        average_change=average,
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        leaders=tuple(ordered[:2]),
        laggards=tuple(reversed(ordered[-2:])),
    )


def filter_sector_rows(rows: Iterable[Any], query: Any) -> list[Any]:
    normalized = str(query or "").strip().casefold()
    materialized = list(rows)
    if not normalized:
        return materialized
    return [
        row
        for row in materialized
        if normalized in str(getattr(row, "symbol", "") or "").casefold()
        or normalized in str(getattr(row, "name", "") or "").casefold()
    ]
