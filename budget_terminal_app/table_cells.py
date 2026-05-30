from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableCell:
    text: str = ""
    alignment: str = "center"
    foreground: str | None = None
    background: str | None = None
    tooltip: str = ""
    editable: bool = False
    selectable: bool = True
    enabled: bool = True
    sort_value: float | None = None
    data_roles: tuple[tuple[object, object], ...] = ()


TableRow = tuple[TableCell, ...]
