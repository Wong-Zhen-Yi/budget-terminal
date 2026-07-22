from __future__ import annotations

import datetime
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .dependencies import logger
from .paths import user_data_path


STRATEGIES_FILE = user_data_path("strategies.json")
STRATEGIES_VERSION = 2
STARTER_CARDS_VERSION = 1
BUILTIN_INDEX_CARD_ID = "builtin:index"
STRATEGY_INTERVAL_KEYS = ("1d", "30d", "1y")
STARTER_CUSTOM_CARDS = (
    {
        "id": "custom:starter_balanced_core",
        "name": "Balanced Core",
        "symbols": ["SPY", "BND", "GLD"],
        "weighting": "custom",
        "weights": {"SPY": 60.0, "BND": 30.0, "GLD": 10.0},
    },
    {
        "id": "custom:starter_growth_hedge",
        "name": "Growth & Hedge",
        "symbols": ["SPY", "TLT", "GLD"],
        "weighting": "custom",
        "weights": {"SPY": 50.0, "TLT": 25.0, "GLD": 25.0},
    },
    {
        "id": "custom:starter_three_way_equal",
        "name": "Three-Way Equal",
        "symbols": ["SPY", "IEF", "GLD"],
        "weighting": "equal",
        "weights": {},
    },
)
DEFAULT_STRATEGIES_STATE = {
    "version": STRATEGIES_VERSION,
    "starter_cards_version": STARTER_CARDS_VERSION,
    "custom_cards": [dict(card) for card in STARTER_CUSTOM_CARDS],
    "card_order": [BUILTIN_INDEX_CARD_ID, *(card["id"] for card in STARTER_CUSTOM_CARDS)],
    "hidden_portfolio_ids": [],
    "intervals": {},
}


def normalize_strategy_symbols(values: Any) -> list[str]:
    """Return unique, uppercase ticker symbols from text or a sequence."""
    if isinstance(values, str):
        raw_values = re.split(r"[\s,;]+", values)
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = []
    normalized = []
    for value in raw_values:
        symbol = str(value or "").upper().strip()
        if symbol and symbol != "CASH" and symbol not in normalized:
            normalized.append(symbol)
    return normalized


def normalize_strategy_weights(symbols: Any, values: Any) -> dict[str, float]:
    """Normalize positive per-symbol weights to a 100% total."""
    clean_symbols = normalize_strategy_symbols(symbols)
    source = values if isinstance(values, dict) else {}
    raw_weights = {}
    for symbol in clean_symbols:
        try:
            weight = float(source.get(symbol, source.get(symbol.lower(), 0.0)) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight > 0.0:
            raw_weights[symbol] = weight
    total = sum(raw_weights.values())
    if total <= 0.0:
        return {}
    return {symbol: weight / total * 100.0 for symbol, weight in raw_weights.items()}


def _normalize_custom_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    symbols = normalize_strategy_symbols(value.get("symbols", []))
    if not symbols:
        return None
    raw_id = str(value.get("id", "") or "").strip()
    card_id = raw_id if raw_id.startswith("custom:") else f"custom:{uuid.uuid4().hex}"
    name = str(value.get("name", "") or "").strip() or "Untitled Strategy"
    weighting = str(value.get("weighting", "equal") or "equal").strip().lower()
    if weighting not in {"equal", "custom"}:
        weighting = "equal"
    weights = normalize_strategy_weights(symbols, value.get("weights", {})) if weighting == "custom" else {}
    if weighting == "custom" and not weights:
        weighting = "equal"
    return {
        "id": card_id,
        "name": name[:80],
        "symbols": symbols,
        "weighting": weighting,
        "weights": weights,
    }


def normalize_strategies_state(value: Any) -> dict[str, Any]:
    """Normalize the separate strategies JSON document."""
    raw = value if isinstance(value, dict) else {}
    custom_cards = []
    custom_ids = set()
    for entry in raw.get("custom_cards", []):
        card = _normalize_custom_card(entry)
        if card is None or card["id"] in custom_ids:
            continue
        custom_ids.add(card["id"])
        custom_cards.append(card)

    try:
        starter_cards_version = int(raw.get("starter_cards_version", 0) or 0)
    except (TypeError, ValueError):
        starter_cards_version = 0
    if starter_cards_version < STARTER_CARDS_VERSION:
        for starter in STARTER_CUSTOM_CARDS:
            if starter["id"] in custom_ids:
                continue
            card = _normalize_custom_card(starter)
            if card is not None:
                custom_ids.add(card["id"])
                custom_cards.append(card)
        starter_cards_version = STARTER_CARDS_VERSION

    card_order = []
    for value_id in raw.get("card_order", []):
        card_id = str(value_id or "").strip()
        if card_id and card_id not in card_order:
            card_order.append(card_id)
    if BUILTIN_INDEX_CARD_ID not in card_order:
        card_order.insert(0, BUILTIN_INDEX_CARD_ID)
    for card in custom_cards:
        if card["id"] not in card_order:
            card_order.append(card["id"])

    hidden_portfolio_ids = []
    for value_id in raw.get("hidden_portfolio_ids", []):
        portfolio_id = str(value_id or "").strip()
        if portfolio_id and portfolio_id not in hidden_portfolio_ids:
            hidden_portfolio_ids.append(portfolio_id)

    intervals = {}
    raw_intervals = raw.get("intervals", {})
    if isinstance(raw_intervals, dict):
        for card_id, interval_key in raw_intervals.items():
            clean_id = str(card_id or "").strip()
            clean_interval = str(interval_key or "").strip().lower()
            if clean_id and clean_interval in STRATEGY_INTERVAL_KEYS:
                intervals[clean_id] = clean_interval

    return {
        "version": STRATEGIES_VERSION,
        "starter_cards_version": starter_cards_version,
        "custom_cards": custom_cards,
        "card_order": card_order,
        "hidden_portfolio_ids": hidden_portfolio_ids,
        "intervals": intervals,
    }


def load_strategies_state(path: Any = None) -> dict[str, Any]:
    """Load custom strategy cards without touching user_data.json."""
    target = Path(path or STRATEGIES_FILE)
    try:
        with target.open(encoding="utf-8") as stream:
            return normalize_strategies_state(json.load(stream))
    except FileNotFoundError:
        return normalize_strategies_state(DEFAULT_STRATEGIES_STATE)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Unable to load strategies from %s: %s", target, exc)
        return normalize_strategies_state(DEFAULT_STRATEGIES_STATE)


def save_strategies_state(value: Any, path: Any = None) -> dict[str, Any]:
    """Atomically persist the normalized strategy-card document."""
    normalized = normalize_strategies_state(value)
    target = Path(path or STRATEGIES_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.{timestamp}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as stream:
            json.dump(normalized, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp_path), str(target))
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return normalized


def clear_custom_strategies(path: Any = None) -> dict[str, Any]:
    """Remove all custom-card data while retaining the built-in index card."""
    return save_strategies_state({
        "version": STRATEGIES_VERSION,
        "starter_cards_version": STARTER_CARDS_VERSION,
        "custom_cards": [],
        "card_order": [BUILTIN_INDEX_CARD_ID],
        "hidden_portfolio_ids": [],
        "intervals": {},
    }, path)


def create_custom_strategy(
    name: Any,
    symbols: Any,
    *,
    weighting: str = "equal",
    weights: Any = None,
) -> dict[str, Any]:
    """Build one normalized custom equal-weight strategy card."""
    card = _normalize_custom_card({
        "id": f"custom:{uuid.uuid4().hex}",
        "name": name,
        "symbols": symbols,
        "weighting": weighting,
        "weights": weights or {},
    })
    if card is None:
        raise ValueError("A strategy needs at least one ticker.")
    return card


def export_custom_strategies(path: Any) -> None:
    """Export custom cards and their display order as portable JSON."""
    state = load_strategies_state()
    custom_ids = {card["id"] for card in state["custom_cards"]}
    payload = {
        "version": STRATEGIES_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "weighting_modes": ["equal", "custom"],
        "custom_cards": state["custom_cards"],
        "card_order": [card_id for card_id in state["card_order"] if card_id in custom_ids],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)


def load_custom_strategies_import(path: Any, *, allow_empty: bool = False) -> dict[str, Any]:
    """Read and validate a portable custom-card JSON export without changing local state."""
    target = Path(path)
    try:
        with target.open(encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read custom-card JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("custom_cards"), list):
        raise ValueError("The selected file does not contain a custom_cards list.")
    raw_cards = raw.get("custom_cards", [])
    cards = []
    seen_ids = set()
    skipped_count = 0
    for entry in raw_cards:
        card = _normalize_custom_card(entry)
        if card is None or card["id"] in seen_ids:
            skipped_count += 1
            continue
        seen_ids.add(card["id"])
        cards.append(card)
    if not cards and (raw_cards or not allow_empty):
        raise ValueError("The selected file does not contain any valid custom cards.")
    imported_order = []
    for value in raw.get("card_order", []):
        card_id = str(value or "").strip()
        if card_id in seen_ids and card_id not in imported_order:
            imported_order.append(card_id)
    for card in cards:
        if card["id"] not in imported_order:
            imported_order.append(card["id"])
    return {
        "source_path": str(target),
        "exported_at": str(raw.get("exported_at", "") or ""),
        "custom_cards": cards,
        "card_order": imported_order,
        "skipped_count": skipped_count,
    }


def merge_custom_strategies_import(payload: Any, path: Any = None) -> dict[str, Any]:
    """Merge validated custom cards into local state, updating matching IDs and appending new IDs."""
    imported = payload if isinstance(payload, dict) else {}
    imported_cards = imported.get("custom_cards", [])
    if not isinstance(imported_cards, list) or not imported_cards:
        raise ValueError("No validated custom cards were supplied for import.")
    current = load_strategies_state(path)
    existing_cards = list(current.get("custom_cards", []))
    existing_by_id = {card["id"]: card for card in existing_cards}
    added_count = 0
    updated_count = 0
    for raw_card in imported_cards:
        card = _normalize_custom_card(raw_card)
        if card is None:
            continue
        if card["id"] in existing_by_id:
            existing_by_id[card["id"]].update(card)
            updated_count += 1
        else:
            existing_cards.append(card)
            existing_by_id[card["id"]] = card
            added_count += 1
    order = list(current.get("card_order", []))
    imported_order = imported.get("card_order", []) if isinstance(imported.get("card_order"), list) else []
    for card_id in imported_order:
        clean_id = str(card_id or "").strip()
        if clean_id in existing_by_id and clean_id not in order:
            order.append(clean_id)
    for card in existing_cards:
        if card["id"] not in order:
            order.append(card["id"])
    current["custom_cards"] = existing_cards
    current["card_order"] = order
    state = save_strategies_state(current, path)
    return {
        "state": state,
        "added_count": added_count,
        "updated_count": updated_count,
        "total_imported": added_count + updated_count,
        "skipped_count": int(imported.get("skipped_count", 0) or 0),
    }
