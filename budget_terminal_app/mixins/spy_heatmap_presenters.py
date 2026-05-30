from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HeatmapHoldingSummary:
    text: str
    change_pct: float | None = None


@dataclass(frozen=True)
class HeatmapSummary:
    holdings_loaded: int
    quote_coverage: int
    weighted_move: float | None
    strongest: HeatmapHoldingSummary
    weakest: HeatmapHoldingSummary


@dataclass(frozen=True)
class HeatmapDetail:
    symbol: str
    name: str
    sector: str
    weight: str
    price: str
    change_label: str
    change_text: str
    change_pct: float | None


def format_heatmap_pct(value: Any, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    sign = "+" if signed and number >= 0 else ""
    return f"{sign}{number:.2f}%"


def format_heatmap_weight_pct(value: Any) -> str:
    try:
        number = float(value) * 100.0
    except (TypeError, ValueError):
        return "--"
    return f"{number:.2f}%"


def heatmap_interval_summary(result: Any, interval_key: Any) -> Any:
    key = str(interval_key or "live").strip().lower() or "live"
    summaries = getattr(result, "interval_summaries", {}) or {}
    return summaries.get(key) or summaries.get("live") or result


def heatmap_holding_change(holding: Any, interval_key: Any) -> Any:
    key = str(interval_key or "live").strip().lower() or "live"
    changes = dict(getattr(holding, "changes", {}) or {})
    change = changes.get(key)
    if not isinstance(change, (int, float)) and key == "live":
        change = getattr(holding, "change_pct", None)
    return change


def build_spy_heatmap_rows(
    result: Any,
    *,
    etf_symbol: Any,
    etf_label: Any,
    interval_key: Any,
    interval_label: Any,
) -> list[dict[str, Any]]:
    """Return the row contract consumed by EtfHeatmapWidget."""
    rows: list[dict[str, Any]] = []
    etf_text = str(etf_symbol or "").upper().strip()
    etf_label_text = str(etf_label or etf_text or "SPY").strip()
    key = str(interval_key or "live").strip().lower() or "live"
    label = str(interval_label or "Live").strip() or "Live"
    for holding in list(getattr(result, "holdings", []) or []):
        changes = dict(getattr(holding, "changes", {}) or {})
        change = changes.get(key)
        if not isinstance(change, (int, float)) and key == "live":
            change = getattr(holding, "change_pct", None)
        rows.append({
            "symbol": str(getattr(holding, "symbol", "") or "").upper().strip(),
            "name": str(getattr(holding, "name", "") or "").strip(),
            "sector": str(getattr(holding, "sector", "") or "Unclassified").strip() or "Unclassified",
            "weight": getattr(holding, "weight", None),
            "price": getattr(holding, "price", None),
            "change_pct": change,
            "changes": changes,
            "interval_key": key,
            "interval_label": label,
            "change_label": f"{label} Change",
            "etf": etf_text,
            "etf_label": etf_label_text,
        })
    return rows


def weighted_change_from_heatmap_rows(rows: Any) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        weight = row.get("weight")
        change = row.get("change_pct")
        if isinstance(weight, (int, float)) and isinstance(change, (int, float)):
            numerator += float(weight) * float(change)
            denominator += float(weight)
    return numerator / denominator if denominator > 0 else None


def select_heatmap_row(rows: list[dict[str, Any]], selected_row: Any, etf_symbol: Any) -> dict[str, Any] | None:
    etf_text = str(etf_symbol or "").upper().strip()
    prior = selected_row if isinstance(selected_row, dict) and selected_row.get("etf") == etf_text else None
    selected_symbol = str((prior or {}).get("symbol") or "").upper().strip()
    selected = next((row for row in rows if row.get("symbol") == selected_symbol), None)
    return selected or (rows[0] if rows else None)


def build_holding_summary(holding: Any, interval_key: Any) -> HeatmapHoldingSummary:
    symbol = str(getattr(holding, "symbol", "") or "").upper().strip()
    change = heatmap_holding_change(holding, interval_key)
    if not symbol or not isinstance(change, (int, float)):
        return HeatmapHoldingSummary("--")
    return HeatmapHoldingSummary(f"{symbol} {format_heatmap_pct(change, signed=True)}", float(change))


def build_heatmap_summary(result: Any, interval_key: Any) -> HeatmapSummary:
    summary = heatmap_interval_summary(result, interval_key)
    holdings_loaded = int(getattr(result, "holdings_loaded", 0) or 0)
    quote_coverage = int(getattr(summary, "quote_coverage", getattr(result, "quote_coverage", 0)) or 0)
    weighted = getattr(summary, "weighted_move", getattr(result, "weighted_day_move", None))
    strongest = getattr(summary, "strongest", getattr(result, "strongest", None))
    weakest = getattr(summary, "weakest", getattr(result, "weakest", None))
    return HeatmapSummary(
        holdings_loaded=holdings_loaded,
        quote_coverage=quote_coverage,
        weighted_move=weighted if isinstance(weighted, (int, float)) else None,
        strongest=build_holding_summary(strongest, interval_key),
        weakest=build_holding_summary(weakest, interval_key),
    )


def build_heatmap_detail(row: Any, interval_label: Any) -> HeatmapDetail:
    payload = row if isinstance(row, dict) else {}
    if not payload:
        return HeatmapDetail(
            symbol="Select a holding",
            name="--",
            sector="Sector: --",
            weight="Weight: --",
            price="Price: --",
            change_label="Change",
            change_text="Change: --",
            change_pct=None,
        )
    price = payload.get("price")
    price_text = f"Price: ${float(price):,.2f}" if isinstance(price, (int, float)) else "Price: --"
    change = payload.get("change_pct")
    fallback_label = f"{str(interval_label or 'Live').strip() or 'Live'} Change"
    change_label = str(payload.get("change_label") or fallback_label)
    return HeatmapDetail(
        symbol=str(payload.get("symbol") or "--"),
        name=str(payload.get("name") or "--"),
        sector=f"Sector: {payload.get('sector') or 'Unclassified'}",
        weight=f"Weight: {format_heatmap_weight_pct(payload.get('weight'))}",
        price=price_text,
        change_label=change_label,
        change_text=f"{change_label}: {format_heatmap_pct(change, signed=True)}",
        change_pct=float(change) if isinstance(change, (int, float)) else None,
    )
