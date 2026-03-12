from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    background_primary: str
    background_secondary: str
    panel_background: str
    panel_border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_soft: str
    accent_positive: str
    accent_positive_bg: str
    accent_negative: str
    accent_negative_bg: str
    warning: str
    warning_bg: str
    info: str
    info_bg: str
    gridline: str
    table_header_bg: str
    table_row_bg: str
    table_row_alt_bg: str
    selected_bg: str
    hover_bg: str
    button_bg: str
    button_hover_bg: str
    button_checked_bg: str
    button_checked_border: str
    input_bg: str
    input_border: str
    input_focus_border: str
    chart_bg: str
    chart_axis: str
    chart_grid: str
    chart_up_candle: str
    chart_down_candle: str
    chart_volume_up: str
    chart_volume_down: str
    chart_ma: str
    chart_rsi: str
    chart_reference: str
    pie_palette: tuple[str, ...] = field(default_factory=tuple)
    series_palette: tuple[str, ...] = field(default_factory=tuple)
    sector_palette: tuple[str, ...] = field(default_factory=tuple)

    def color(self, token: str) -> str:
        return getattr(self, token)
