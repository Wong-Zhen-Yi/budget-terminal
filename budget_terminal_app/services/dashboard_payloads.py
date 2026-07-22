from __future__ import annotations

from typing import Any

import pandas as pd


def normalize_chart_configs(configs: Any) -> list[tuple[str, Any, Any]]:
    normalized = []
    if isinstance(configs, (list, tuple)):
        for config in configs:
            if isinstance(config, (list, tuple)) and len(config) >= 3:
                symbol = str(config[0] or "").strip()
                if symbol:
                    normalized.append((symbol, config[1], config[2]))
    elif isinstance(configs, dict):
        symbol = str(configs.get("symbol") or "").strip()
        period = configs.get("period")
        interval = configs.get("interval")
        if symbol and period and interval:
            normalized.append((symbol, period, interval))
    return normalized


def dedupe_symbols(*groups: Any) -> list[str]:
    seen: set[str] = set()
    ordered = []
    for group in groups:
        if not isinstance(group, (list, tuple)):
            continue
        for symbol in group:
            text = str(symbol or "").strip()
            if text and text not in seen:
                seen.add(text)
                ordered.append(text)
    return ordered


def extract_close_series(batch_data: Any, all_symbols: list[str], symbol: str) -> Any:
    if batch_data is None or batch_data.empty:
        return None
    if isinstance(batch_data.columns, pd.MultiIndex):
        level_zero = batch_data.columns.get_level_values(0)
        level_one = batch_data.columns.get_level_values(1)
        if symbol in level_zero:
            frame = batch_data[symbol]
        elif symbol in level_one:
            frame = batch_data.xs(symbol, axis=1, level=1)
        else:
            return None
        return frame["Close"].dropna() if "Close" in frame.columns else None
    if symbol in batch_data.columns:
        return batch_data[symbol].dropna()
    if len(all_symbols) == 1 and all_symbols[0] == symbol and "Close" in batch_data.columns:
        return batch_data["Close"].dropna()
    return None


def price_payload(close: Any) -> dict[str, float] | None:
    if close is None or close.empty:
        return None
    current = float(close.iloc[-1])
    if len(close) < 2:
        return {"price": current, "change": 0.0, "abs_change": 0.0}
    previous = float(close.iloc[-2])
    absolute = current - previous
    return {"price": current, "change": absolute / previous * 100 if previous else 0.0, "abs_change": absolute}


def market_payload(close: Any) -> dict[str, float] | None:
    payload = price_payload(close)
    return None if payload is None else {"price": payload["price"], "change": payload["change"]}
