from __future__ import annotations

import datetime
import math
from typing import Any, Callable

from budget_terminal_app.table_cells import TableCell, TableRow


def _is_missing(value: Any, pd_module: Any = None) -> bool:
    if value is None:
        return True
    if pd_module is not None:
        try:
            return bool(pd_module.isna(value))
        except Exception:
            pass
    return False


def format_chain_value(value: Any, fmt: str, *, pd_module: Any = None) -> str:
    """Format a chain cell value for display."""
    if _is_missing(value, pd_module):
        return ""
    try:
        fval = float(value)
        if _is_missing(fval, pd_module):
            return ""
        return fmt.format(fval)
    except Exception:
        txt = str(value)
        return "" if txt.lower() == "nan" else txt


def format_top_volume_expiration(expiry: Any) -> str:
    """Render one expiration in compact uppercase month format."""
    expiry_text = str(expiry or "").strip()
    if not expiry_text:
        return ""
    try:
        expiry_date = datetime.date.fromisoformat(expiry_text)
    except ValueError:
        return expiry_text
    return f"{expiry_date.strftime('%b').upper()} {expiry_date.day} '{expiry_date.strftime('%y')}"


def _format_strike(value: Any, *, pd_module: Any = None) -> str:
    if _is_missing(value, pd_module):
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _format_price(value: Any, *, pd_module: Any = None) -> str:
    if _is_missing(value, pd_module):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _format_volume(value: Any, *, pd_module: Any = None) -> str:
    if _is_missing(value, pd_module):
        return "0"
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _numeric_sort_value(value: Any, *, pd_module: Any = None) -> float | None:
    if _is_missing(value, pd_module):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if _is_missing(numeric, pd_module) or not math.isfinite(numeric):
        return None
    return numeric


def _option_type_foreground(option_type: str, *, positive_color: str, negative_color: str) -> str | None:
    if option_type == "Call":
        return positive_color
    if option_type == "Put":
        return negative_color
    return None


def _ranked_numeric_indexes(
    records: list[Any],
    key: str,
    *,
    descending: bool,
    excluded_indexes: set[int] | None = None,
    pd_module: Any = None,
) -> list[int]:
    excluded = set(excluded_indexes or set())
    ranked_values = []
    for row_index, opt in enumerate(records):
        if row_index in excluded or not isinstance(opt, dict):
            continue
        value = opt.get(key)
        if _is_missing(value, pd_module):
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if _is_missing(numeric_value, pd_module) or not math.isfinite(numeric_value):
            continue
        ranked_values.append((row_index, numeric_value))

    ranked_values.sort(key=lambda item: item[1], reverse=descending)
    return [row_index for row_index, _value in ranked_values]


def _summary_cell_backgrounds(
    records: list[Any],
    *,
    price_highlight_backgrounds: tuple[str, ...],
    low_price_highlight_backgrounds: tuple[str, ...],
    top_volume_highlight_backgrounds: tuple[str, ...],
    low_volume_highlight_backgrounds: tuple[str, ...],
    pd_module: Any = None,
) -> list[dict[str, str]]:
    backgrounds: list[dict[str, str]] = [{} for _record in records]
    price_backgrounds = tuple(price_highlight_backgrounds or ())
    low_price_backgrounds = tuple(low_price_highlight_backgrounds or ())
    top_volume_backgrounds = tuple(top_volume_highlight_backgrounds or ())
    low_volume_backgrounds = tuple(low_volume_highlight_backgrounds or ())

    top_price_indexes = _ranked_numeric_indexes(records, "lastPrice", descending=True, pd_module=pd_module)[:len(price_backgrounds)]
    top_price_index_set = set(top_price_indexes)
    low_price_indexes = _ranked_numeric_indexes(
        records,
        "lastPrice",
        descending=False,
        excluded_indexes=top_price_index_set,
        pd_module=pd_module,
    )[:len(low_price_backgrounds)]

    for rank_index, row_index in enumerate(top_price_indexes):
        backgrounds[row_index]["price"] = price_backgrounds[rank_index]
    for rank_index, row_index in enumerate(low_price_indexes):
        backgrounds[row_index]["price"] = low_price_backgrounds[rank_index]

    top_volume_indexes = _ranked_numeric_indexes(records, "volume", descending=True, pd_module=pd_module)[:len(top_volume_backgrounds)]
    top_volume_index_set = set(top_volume_indexes)
    low_volume_indexes = _ranked_numeric_indexes(
        records,
        "volume",
        descending=False,
        excluded_indexes=top_volume_index_set,
        pd_module=pd_module,
    )[:len(low_volume_backgrounds)]

    for rank_index, row_index in enumerate(low_volume_indexes):
        backgrounds[row_index]["volume"] = low_volume_backgrounds[rank_index]
    for rank_index, row_index in enumerate(top_volume_indexes):
        backgrounds[row_index]["volume"] = top_volume_backgrounds[rank_index]

    return backgrounds


def build_option_summary_rows(
    records: Any,
    *,
    ticker: str,
    expiry: str = "",
    positive_color: str,
    negative_color: str,
    price_highlight_backgrounds: tuple[str, ...] = (),
    low_price_highlight_backgrounds: tuple[str, ...] = (),
    top_volume_highlight_backgrounds: tuple[str, ...] = (),
    low_volume_highlight_backgrounds: tuple[str, ...] = (),
    pd_module: Any = None,
) -> list[TableRow]:
    """Return six-column rows for top-volume and strike summary tables."""
    rows: list[TableRow] = []
    record_list = list(records or [])
    backgrounds = _summary_cell_backgrounds(
        record_list,
        price_highlight_backgrounds=tuple(price_highlight_backgrounds or ()),
        low_price_highlight_backgrounds=tuple(low_price_highlight_backgrounds or ()),
        top_volume_highlight_backgrounds=tuple(top_volume_highlight_backgrounds or ()),
        low_volume_highlight_backgrounds=tuple(low_volume_highlight_backgrounds or ()),
        pd_module=pd_module,
    )
    for row_index, opt in enumerate(record_list):
        option_type = str(opt.get("type", "") or "")
        exp_value = str(opt.get("expiration", "") or expiry)
        cell_backgrounds = backgrounds[row_index]
        rows.append(
            (
                TableCell(str(opt.get("ticker", ticker) or ticker)),
                TableCell(
                    option_type,
                    foreground=_option_type_foreground(
                        option_type,
                        positive_color=positive_color,
                        negative_color=negative_color,
                    ),
                ),
                TableCell(
                    _format_strike(opt.get("strike"), pd_module=pd_module),
                    sort_value=_numeric_sort_value(opt.get("strike"), pd_module=pd_module),
                ),
                TableCell(format_top_volume_expiration(exp_value)),
                TableCell(
                    _format_price(opt.get("lastPrice"), pd_module=pd_module),
                    background=cell_backgrounds.get("price"),
                    sort_value=_numeric_sort_value(opt.get("lastPrice"), pd_module=pd_module),
                ),
                TableCell(
                    _format_volume(opt.get("volume", 0), pd_module=pd_module),
                    background=cell_backgrounds.get("volume"),
                    sort_value=_numeric_sort_value(opt.get("volume", 0), pd_module=pd_module),
                ),
            )
        )
    return rows


def build_chain_rows(
    data: Any,
    columns: Any,
    ranks: dict[int, int],
    details: dict[int, dict[str, Any]],
    *,
    strategy_tooltip: Callable[[int | None, dict[str, Any]], str],
    strategy_bg: Callable[[int | None], str | None],
    positive_color: str,
    negative_color: str,
    muted_color: str,
    pd_module: Any = None,
) -> list[TableRow]:
    """Return display rows for one calls or puts chain table."""
    if data is None or getattr(data, "empty", True):
        return []
    rows: list[TableRow] = []
    for row_index, (_, row) in enumerate(data.iterrows()):
        rank = ranks.get(row_index)
        detail = details.get(row_index, {})
        tooltip = strategy_tooltip(rank, detail)
        bg_color = strategy_bg(rank)
        cells = []
        for label, key, fmt in columns:
            foreground = None
            value = row.get(key)
            if label == "Chg":
                try:
                    foreground = positive_color if float(row.get("change", 0) or 0) >= 0 else negative_color
                except Exception:
                    foreground = None
            elif label == "IV":
                foreground = muted_color
            if label == "Strike" and rank:
                try:
                    strike_txt = fmt.format(float(row.get("strike", 0.0) or 0.0))
                except Exception:
                    strike_txt = str(row.get("strike", ""))
                display = f"{strike_txt}  #{rank}"
            else:
                display = format_chain_value(value, fmt, pd_module=pd_module)
            cells.append(
                TableCell(
                    display,
                    foreground=foreground,
                    background=bg_color,
                    tooltip=tooltip,
                )
            )
        rows.append(tuple(cells))
    return rows


def prepare_top_volume_records(
    chain_df: Any,
    *,
    ticker: str,
    expiry: str,
    option_type: str | None,
    pd_module: Any,
) -> list[dict[str, Any]]:
    """Normalize one chain and return top-volume records."""
    if chain_df is None or getattr(chain_df, "empty", True):
        return []
    prepared = chain_df.copy()
    if "ticker" not in prepared.columns:
        prepared["ticker"] = ticker
    if "type" not in prepared.columns:
        prepared["type"] = ""
    if "expiration" not in prepared.columns:
        prepared["expiration"] = expiry
    if option_type:
        target = option_type.lower()
        type_series = prepared["type"].astype(str).str.strip().str.lower()
        prepared = prepared[type_series.isin((target, f"{target}s"))].copy()
        if prepared.empty:
            return []
    for col in ("strike", "lastPrice", "volume", "openInterest"):
        if col not in prepared.columns:
            prepared[col] = 0.0
        prepared[col] = pd_module.to_numeric(prepared[col], errors="coerce")
    prepared["volume"] = prepared["volume"].fillna(0.0)
    prepared["openInterest"] = prepared["openInterest"].fillna(0.0)
    top_options = prepared.sort_values(by=["volume", "openInterest"], ascending=False, na_position="last").head(10)
    return top_options.to_dict("records")


def prepare_strike_records(
    chain_df: Any,
    *,
    ticker: str,
    expiry: str,
    selected_strike: float,
    tolerance: float,
    pd_module: Any,
) -> list[dict[str, Any]]:
    """Normalize one chain and return records matching a selected strike."""
    if chain_df is None or getattr(chain_df, "empty", True):
        return []
    prepared = chain_df.copy()
    if "ticker" not in prepared.columns:
        prepared["ticker"] = ticker
    if "type" not in prepared.columns:
        prepared["type"] = ""
    if "expiration" not in prepared.columns:
        prepared["expiration"] = expiry
    for col in ("strike", "lastPrice", "volume", "openInterest"):
        if col not in prepared.columns:
            prepared[col] = 0.0
        prepared[col] = pd_module.to_numeric(prepared[col], errors="coerce")
    strike_series = prepared["strike"]
    matches = prepared[(strike_series - float(selected_strike)).abs() <= float(tolerance)].copy()
    if matches.empty:
        return []
    matches["volume"] = matches["volume"].fillna(0.0)
    matches["openInterest"] = matches["openInterest"].fillna(0.0)
    type_order = {"Call": 0, "Put": 1}
    matches["_type_order"] = matches["type"].map(type_order).fillna(2)
    matches = matches.sort_values(
        by=["_type_order", "volume", "openInterest"],
        ascending=[True, False, False],
        na_position="last",
    )
    return matches.drop(columns=["_type_order"], errors="ignore").to_dict("records")
