from __future__ import annotations

from typing import Any

from budget_terminal_app.compat import *
from budget_terminal_app.themes import ThemeManager


class ThemeSupportMixin:

    def init_theme_system(self, *, apply: bool=True) -> None:
        """Create the shared theme manager and apply the default theme."""
        if not hasattr(self, 'theme_manager'):
            app = QApplication.instance()
            self.theme_manager = ThemeManager(app)
            self.theme_manager.theme_changed.connect(self._on_theme_changed)
        self.current_theme_id = self.theme_manager.load_initial_theme_id()
        self.current_theme = self.theme_manager.theme(self.current_theme_id)
        if apply:
            self.theme_manager.apply_theme(self.current_theme_id)

    def _on_theme_changed(self, theme_id: str) -> None:
        """Refresh page-specific theme surfaces after a theme switch."""
        self.current_theme_id = theme_id
        self.current_theme = self.theme_manager.current_theme
        for name, page_attr in (
            ("_apply_window_theme", None),
            ("_apply_dashboard_theme", None),
            ("_apply_portfolio_theme", "page4"),
            ("_apply_calendar_theme", "page7"),
            ("_apply_news_theme", "page3"),
            ("_apply_networth_theme", "page6"),
            ("_apply_sectors_theme", "page8"),
            ("_apply_spy_heatmap_theme", "page17"),
            ("_apply_random_recommender_theme", "page18"),
            ("_apply_ipo_theme", "page21"),
            ("_apply_settings_page_theme", "page9"),
            ("_apply_charts_page_theme", "page10"),
            ("_apply_backtest_theme", "page25"),
            ("_apply_global_page_theme", "page26"),
            ("_apply_stocks_theme", "page12"),
            ("_apply_valuation_theme", "page23"),
            ("_apply_etf_theme", "page13"),
            ("_apply_fundamentals_theme", "page2"),
            ("_apply_options_chain_theme", "page5"),
            ("_apply_crypto_theme", "page19"),
            ("_apply_politics_theme", "page15"),
            ("_apply_dataroma_theme", "page22"),
            ("_apply_institutions_theme", "page24"),
            ("_apply_youtube_theme", "page16"),
        ):
            if page_attr and not self._page_initialized(page_attr=page_attr):
                continue
            fn = getattr(self, name, None)
            if callable(fn):
                fn()

    def theme(self) -> Any:
        """Return the currently active theme tokens."""
        return getattr(self, "current_theme", self.theme_manager.current_theme)

    def theme_color(self, token: str) -> str:
        """Resolve a semantic theme token into a color string."""
        return self.theme().color(token)

    def theme_qcolor(self, token: str) -> QColor:
        """Resolve a semantic theme token into QColor."""
        return QColor(self.theme_color(token))

    def set_theme_role(self, widget: Any, role: str | None) -> Any:
        """Apply a semantic widget role used by the global stylesheet."""
        widget.setProperty("bt_role", role)
        self._repolish_widget(widget)
        return widget

    def set_theme_variant(self, widget: Any, variant: str | None) -> Any:
        """Apply a semantic button variant used by the global stylesheet."""
        widget.setProperty("bt_variant", variant)
        self._repolish_widget(widget)
        return widget

    def set_theme_status(self, widget: Any, status: str) -> None:
        """Store a semantic status role on a widget."""
        widget.setProperty("bt_status", status)
        self._repolish_widget(widget)

    def set_status_text(self, widget: Any, text: Any, *, status: str = "muted") -> None:
        """Update a status label using semantic status colors."""
        display_text = str(text)
        widget.setText(display_text)
        if hasattr(widget, 'setToolTip'):
            widget.setToolTip(display_text)
        color = self.status_color(status)
        widget.setStyleSheet(f"color: {color}; font-size: 11px;")
        widget.setProperty("bt_status", status)

    def status_color(self, status: str) -> str:
        """Map a semantic status name to the active theme."""
        return {
            "positive": self.theme_color("accent_positive"),
            "negative": self.theme_color("accent_negative"),
            "warning": self.theme_color("warning"),
            "info": self.theme_color("info"),
            "accent": self.theme_color("accent"),
            "secondary": self.theme_color("text_secondary"),
            "muted": self.theme_color("text_muted"),
        }.get(status, self.theme_color("text_muted"))

    def style_plot_widget(self, plot: Any, *, show_y_grid: bool = True) -> None:
        """Apply the active theme to a pyqtgraph plot widget."""
        plot.setBackground(self.theme_color("chart_bg"))
        plot.showGrid(x=True, y=show_y_grid, alpha=0.18)
        right_axis = plot.getPlotItem().getAxis("right")
        bottom_axis = plot.getPlotItem().getAxis("bottom")
        right_axis.setTextPen(self.theme_color("chart_axis"))
        bottom_axis.setTextPen(self.theme_color("chart_axis"))
        right_axis.setStyle(tickTextOffset=8)
        bottom_axis.setStyle(tickTextOffset=8)
        try:
            right_axis.setWidth(52)
        except Exception:
            pass
        try:
            bottom_axis.setHeight(32)
        except Exception:
            pass
        plot.setStyleSheet(
            f"border: 1px solid {self.theme_color('panel_border')}; border-radius: 6px;"
        )

    def theme_pen(self, token: str, *, width: float = 1.0, style: Any = Qt.PenStyle.SolidLine) -> Any:
        """Create a themed pyqtgraph pen."""
        return pg.mkPen(self.theme_color(token), width=width, style=style)

    def theme_brush(self, token: str) -> Any:
        """Create a themed pyqtgraph brush."""
        return pg.mkBrush(self.theme_color(token))

    def _repolish_widget(self, widget: Any) -> None:
        """Refresh stylesheet-polished widgets after property changes."""
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def update_checked_button_state(self, button_map: dict[Any, Any], active_key: Any) -> None:
        """Flag a group of buttons for checked-state styling."""
        for key, button in button_map.items():
            button.setProperty("bt_checked", "true" if key == active_key else "false")
            self._repolish_widget(button)

    def theme_series_color(self, index: int) -> str:
        """Return a deterministic theme series color."""
        palette = self.theme().series_palette or (self.theme_color("accent"),)
        return palette[index % len(palette)]

    def theme_sector_color(self, index: int) -> str:
        """Return a deterministic theme sector color."""
        palette = self.theme().sector_palette or self.theme().series_palette
        return palette[index % len(palette)]

    def theme_pie_palette(self) -> tuple[str, ...]:
        """Return the active palette for pie/donut legends."""
        return self.theme().pie_palette or self.theme().series_palette or (self.theme_color("accent"),)
