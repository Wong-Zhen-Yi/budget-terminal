from __future__ import annotations

import re
from typing import Any

import pandas as pd


def safe_year(value: Any) -> int | None:
    if value is None:
        return None
    if hasattr(value, "year"):
        return int(value.year)
    try:
        parsed = pd.to_datetime(str(value))
        if hasattr(parsed, "year"):
            return int(parsed.year)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(20\d{2})", str(value))
    return int(match.group(1)) if match else None


def fiscal_year(value: Any, fiscal_year_end_month: Any) -> int | None:
    if fiscal_year_end_month is None or fiscal_year_end_month == 12:
        return safe_year(value)
    if hasattr(value, "month") and hasattr(value, "year"):
        month, year = int(value.month), int(value.year)
    else:
        try:
            parsed = pd.to_datetime(str(value))
            month, year = int(parsed.month), int(parsed.year)
        except (TypeError, ValueError):
            return safe_year(value)
    return year + 1 if month > int(fiscal_year_end_month) else year


# Compatibility names retained for callers that used the old private helpers.
_safe_get_year = safe_year
_get_fiscal_year = fiscal_year
