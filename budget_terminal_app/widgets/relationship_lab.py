from __future__ import annotations

import math
from functools import partial
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from budget_terminal_app.dependencies import pd, pg
from budget_terminal_app.widgets.charts import DateAxisItem


ThemeColor = Callable[[str], str]
PlotStyler = Callable[[Any], None]


class RelationshipLabWidget(QWidget):
    """Two-security relationship analysis controls, metrics, and plots."""

    analyze_requested = pyqtSignal()
    settings_changed = pyqtSignal()

    def __init__(self, theme_color: ThemeColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_color = theme_color
        self._analysis: dict[str, Any] | None = None
        self._symbols = ("QQQ", "SPY")
        self._metric_values: dict[str, QLabel] = {}
        self._crosshair_lines: list[Any] = []
        self._mouse_proxies: list[Any] = []
        self._date_positions: dict[Any, int] = {}
        self._scatter_highlight = None
        self._build_ui()
        self.apply_theme()

    @property
    def plots(self) -> tuple[Any, ...]:
        return (
            self.indexed_plot,
            self.ratio_plot,
            self.correlation_plot,
            self.scatter_plot,
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        title = QLabel("<b>Relationship Lab</b>")
        title.setProperty("bt_role", "page_title")
        toolbar.addWidget(title)
        toolbar.addSpacing(8)

        self.left_input = QLineEdit("QQQ")
        self.left_input.setPlaceholderText("Left ticker")
        self.left_input.setFixedWidth(105)
        self.left_input.returnPressed.connect(self.analyze_requested.emit)
        toolbar.addWidget(self.left_input)

        self.swap_button = QPushButton("Swap")
        self.swap_button.setToolTip("Swap the left and right securities")
        self.swap_button.clicked.connect(self._swap_symbols)
        toolbar.addWidget(self.swap_button)

        self.right_input = QLineEdit("SPY")
        self.right_input.setPlaceholderText("Right ticker")
        self.right_input.setFixedWidth(105)
        self.right_input.returnPressed.connect(self.analyze_requested.emit)
        toolbar.addWidget(self.right_input)

        self.range_combo = QComboBox()
        self.range_combo.setToolTip("Adjusted daily price history range")
        for label, period in (("1M", "1mo"), ("3M", "3mo"), ("6M", "6mo"), ("1Y", "1y"), ("5Y", "5y"), ("Max", "max")):
            self.range_combo.addItem(label, period)
        self.range_combo.setCurrentText("1Y")
        self.range_combo.currentIndexChanged.connect(self.settings_changed.emit)
        toolbar.addWidget(self.range_combo)

        self.window_combo = QComboBox()
        self.window_combo.setToolTip("Maximum trading-day lookback for rolling correlation")
        for window in (30, 60, 120, 252):
            self.window_combo.addItem(f"{window}D corr", window)
        self.window_combo.setCurrentIndex(self.window_combo.findData(120))
        self.window_combo.currentIndexChanged.connect(self.settings_changed.emit)
        toolbar.addWidget(self.window_combo)

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setProperty("bt_variant", "accent")
        self.analyze_button.clicked.connect(self.analyze_requested.emit)
        toolbar.addWidget(self.analyze_button)
        toolbar.addStretch(1)

        self.status_label = QLabel("Open Relationship to analyze two securities.")
        self.status_label.setProperty("bt_role", "muted")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self.status_label, 1)
        layout.addLayout(toolbar)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(6)
        metric_specs = (
            ("ratio", "Latest ratio"),
            ("rolling_correlation", "Rolling correlation"),
            ("beta", "Beta"),
            ("alpha", "Daily alpha"),
            ("r", "R"),
            ("r_squared", "R²"),
            ("std_error", "Std. error"),
            ("observations", "Observations"),
        )
        for index, (key, label_text) in enumerate(metric_specs):
            card = QFrame()
            card.setProperty("bt_role", "panel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(1)
            label = QLabel(label_text)
            label.setProperty("bt_role", "muted")
            value = QLabel("--")
            value.setProperty("bt_role", "section_title")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            metrics.addWidget(card, index // 4, index % 4)
            self._metric_values[key] = value
        layout.addLayout(metrics)

        self.detail_label = QLabel("Move across a time-series chart to inspect a shared trading date.")
        self.detail_label.setProperty("bt_role", "muted")
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_label)

        plots_layout = QGridLayout()
        plots_layout.setSpacing(8)
        self.indexed_plot, self.indexed_axis = self._new_time_plot("Indexed adjusted performance (start = 100)")
        self.indexed_legend = self.indexed_plot.addLegend(offset=(8, 8))
        self.ratio_plot, self.ratio_axis = self._new_time_plot("Price ratio")
        self.correlation_plot, self.correlation_axis = self._new_time_plot("Rolling return correlation")
        self.scatter_plot = self._new_scatter_plot()
        plots_layout.addWidget(self.indexed_plot, 0, 0)
        plots_layout.addWidget(self.ratio_plot, 0, 1)
        plots_layout.addWidget(self.correlation_plot, 1, 0)
        plots_layout.addWidget(self.scatter_plot, 1, 1)
        plots_layout.setRowStretch(0, 1)
        plots_layout.setRowStretch(1, 1)
        plots_layout.setColumnStretch(0, 1)
        plots_layout.setColumnStretch(1, 1)
        layout.addLayout(plots_layout, 1)

        self.ratio_plot.setXLink(self.indexed_plot)
        self.correlation_plot.setXLink(self.indexed_plot)
        for plot in (self.indexed_plot, self.ratio_plot, self.correlation_plot):
            proxy = pg.SignalProxy(
                plot.scene().sigMouseMoved,
                rateLimit=30,
                slot=partial(self._on_time_plot_mouse_moved, plot),
            )
            self._mouse_proxies.append(proxy)

    def _new_time_plot(self, title: str) -> tuple[Any, DateAxisItem]:
        axis = DateAxisItem(orientation="bottom")
        plot = pg.PlotWidget(axisItems={"bottom": axis})
        plot.setMinimumHeight(190)
        plot.getPlotItem().setMenuEnabled(False)
        plot.getPlotItem().hideAxis("left")
        plot.getPlotItem().showAxis("right")
        plot.getPlotItem().setTitle(title)
        return plot, axis

    def _new_scatter_plot(self) -> Any:
        plot = pg.PlotWidget()
        plot.setMinimumHeight(190)
        plot.getPlotItem().setMenuEnabled(False)
        plot.getPlotItem().hideAxis("left")
        plot.getPlotItem().showAxis("right")
        plot.getPlotItem().setTitle("Daily return regression")
        return plot

    def settings(self) -> dict[str, Any]:
        return {
            "symbols": [self.left_input.text(), self.right_input.text()],
            "range_label": self.range_combo.currentText(),
            "period": self.range_combo.currentData(),
            "window": self.window_combo.currentData(),
        }

    def set_settings(self, symbols: Any, range_label: str, rolling_window: int) -> None:
        values = [str(value or "").upper().strip() for value in list(symbols or [])]
        if len(values) == 2:
            self.left_input.setText(values[0])
            self.right_input.setText(values[1])
        self.range_combo.blockSignals(True)
        self.window_combo.blockSignals(True)
        try:
            range_index = self.range_combo.findText(str(range_label or "1Y"))
            self.range_combo.setCurrentIndex(range_index if range_index >= 0 else self.range_combo.findText("1Y"))
            window_index = self.window_combo.findData(int(rolling_window))
            self.window_combo.setCurrentIndex(window_index if window_index >= 0 else self.window_combo.findData(120))
        finally:
            self.range_combo.blockSignals(False)
            self.window_combo.blockSignals(False)

    def _swap_symbols(self) -> None:
        left = self.left_input.text()
        self.left_input.setText(self.right_input.text())
        self.right_input.setText(left)
        self.settings_changed.emit()

    def set_busy(self, busy: bool) -> None:
        enabled = not bool(busy)
        for widget in (
            self.left_input,
            self.right_input,
            self.swap_button,
            self.range_combo,
            self.window_combo,
            self.analyze_button,
        ):
            widget.setEnabled(enabled)
        self.analyze_button.setText("Analyzing..." if busy else "Analyze")

    def clear_analysis(self) -> None:
        self._analysis = None
        for plot in self.plots:
            plot.clear()
        self._crosshair_lines = []
        self._scatter_highlight = None
        for label in self._metric_values.values():
            label.setText("--")
        self.detail_label.setText("No relationship analysis is currently displayed.")

    @staticmethod
    def _format_number(value: Any, decimals: int = 3, suffix: str = "") -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        if not math.isfinite(number):
            return "--"
        return f"{number:.{decimals}f}{suffix}"

    def render_analysis(self, symbols: tuple[str, str], analysis: dict[str, Any]) -> None:
        self._symbols = tuple(symbols)
        self._analysis = analysis
        aligned = analysis.get("aligned")
        indexed = analysis.get("indexed")
        ratio = analysis.get("ratio")
        rolling = analysis.get("rolling_correlation")
        scatter = analysis.get("scatter")
        regression = analysis.get("regression_line")
        stats = analysis.get("stats", {})
        if not isinstance(aligned, pd.DataFrame) or aligned.empty:
            self.clear_analysis()
            return

        for plot in self.plots:
            plot.clear()
        dates = list(aligned.index)
        self._date_positions = {date: index for index, date in enumerate(dates)}
        for axis in (self.indexed_axis, self.ratio_axis, self.correlation_axis):
            axis.set_dates(dates, "1d")
        x_values = list(range(len(dates)))
        left_color = self._theme_color("accent_positive")
        right_color = self._theme_color("accent")
        ratio_color = self._theme_color("info")
        correlation_color = self._theme_color("warning")
        regression_color = self._theme_color("chart_reference")

        self.indexed_plot.plot(x_values, indexed["left"].tolist(), pen=pg.mkPen(left_color, width=2), name=symbols[0])
        self.indexed_plot.plot(x_values, indexed["right"].tolist(), pen=pg.mkPen(right_color, width=2), name=symbols[1])
        self.ratio_plot.plot(x_values, ratio.tolist(), pen=pg.mkPen(ratio_color, width=2))

        rolling_values = rolling.dropna() if isinstance(rolling, pd.Series) else pd.Series(dtype=float)
        rolling_x = [self._date_positions[date] for date in rolling_values.index if date in self._date_positions]
        rolling_y = [float(rolling_values.loc[date]) for date in rolling_values.index if date in self._date_positions]
        self.correlation_plot.plot(rolling_x, rolling_y, pen=pg.mkPen(correlation_color, width=2))
        self.correlation_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen(regression_color, width=1, style=Qt.PenStyle.DashLine))
        )
        self.correlation_plot.setYRange(-1.05, 1.05, padding=0)

        scatter_x = scatter["x"].tolist() if isinstance(scatter, pd.DataFrame) and not scatter.empty else []
        scatter_y = scatter["y"].tolist() if isinstance(scatter, pd.DataFrame) and not scatter.empty else []
        scatter_color = QColor(right_color)
        scatter_color.setAlpha(120)
        self.scatter_plot.addItem(
            pg.ScatterPlotItem(
                x=scatter_x,
                y=scatter_y,
                size=6,
                pen=pg.mkPen(right_color, width=1),
                brush=pg.mkBrush(scatter_color),
            )
        )
        if isinstance(regression, pd.DataFrame) and not regression.empty:
            self.scatter_plot.plot(
                regression["x"].tolist(),
                regression["y"].tolist(),
                pen=pg.mkPen(regression_color, width=1.5, style=Qt.PenStyle.DashLine),
            )
        self._scatter_highlight = pg.ScatterPlotItem(
            x=[], y=[], size=12, pen=pg.mkPen(correlation_color, width=2), brush=pg.mkBrush(correlation_color)
        )
        self.scatter_plot.addItem(self._scatter_highlight)
        self.scatter_plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen(regression_color, width=1)))
        self.scatter_plot.addItem(pg.InfiniteLine(pos=0.0, angle=90, pen=pg.mkPen(regression_color, width=1)))
        self.scatter_plot.getPlotItem().setLabel("bottom", f"{symbols[1]} daily return", units="%")
        self.scatter_plot.getPlotItem().setLabel("right", f"{symbols[0]} daily return", units="%")

        self._crosshair_lines = []
        for plot in (self.indexed_plot, self.ratio_plot, self.correlation_plot):
            line = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen(regression_color, width=1, style=Qt.PenStyle.DashLine),
            )
            plot.addItem(line, ignoreBounds=True)
            self._crosshair_lines.append(line)

        self._metric_values["ratio"].setText(self._format_number(analysis.get("latest_ratio"), 4))
        correlation_text = self._format_number(analysis.get("latest_correlation"), 3)
        sample = int(analysis.get("latest_correlation_sample", 0) or 0)
        if correlation_text != "--":
            correlation_text = f"{correlation_text} (n={sample})"
        self._metric_values["rolling_correlation"].setText(correlation_text)
        self._metric_values["beta"].setText(self._format_number(stats.get("beta"), 3))
        self._metric_values["alpha"].setText(self._format_number(stats.get("alpha_daily_pct"), 3, "%"))
        self._metric_values["r"].setText(self._format_number(stats.get("r"), 3))
        self._metric_values["r_squared"].setText(self._format_number(stats.get("r_squared"), 3))
        self._metric_values["std_error"].setText(self._format_number(stats.get("std_error_pct"), 3, "%"))
        self._metric_values["observations"].setText(str(int(stats.get("observations", 0) or 0)))

        self.indexed_plot.enableAutoRange()
        self.ratio_plot.enableAutoRange()
        self.scatter_plot.enableAutoRange()
        self._select_date_index(len(dates) - 1)
        self.apply_theme(rerender=False)

    def _on_time_plot_mouse_moved(self, plot: Any, event: Any) -> None:
        if not self._analysis:
            return
        position = event[0] if isinstance(event, (tuple, list)) else event
        if not plot.sceneBoundingRect().contains(position):
            return
        point = plot.getPlotItem().vb.mapSceneToView(position)
        aligned = self._analysis.get("aligned")
        if not isinstance(aligned, pd.DataFrame) or aligned.empty:
            return
        index = max(0, min(int(round(point.x())), len(aligned) - 1))
        self._select_date_index(index)

    def _select_date_index(self, index: int) -> None:
        if not self._analysis:
            return
        aligned = self._analysis.get("aligned")
        indexed = self._analysis.get("indexed")
        ratio = self._analysis.get("ratio")
        rolling = self._analysis.get("rolling_correlation")
        scatter = self._analysis.get("scatter")
        if not isinstance(aligned, pd.DataFrame) or aligned.empty:
            return
        position = max(0, min(int(index), len(aligned) - 1))
        date = aligned.index[position]
        for line in self._crosshair_lines:
            line.setPos(position)
        correlation = rolling.get(date, float("nan")) if isinstance(rolling, pd.Series) else float("nan")
        correlation_text = self._format_number(correlation, 3)
        self.detail_label.setText(
            f"{pd.Timestamp(date).date().isoformat()}  |  "
            f"{self._symbols[0]} {float(indexed.loc[date, 'left']):.2f}  |  "
            f"{self._symbols[1]} {float(indexed.loc[date, 'right']):.2f}  |  "
            f"Ratio {float(ratio.loc[date]):.4f}  |  Rolling r {correlation_text}"
        )
        if self._scatter_highlight is not None:
            if isinstance(scatter, pd.DataFrame) and date in scatter.index:
                self._scatter_highlight.setData(
                    x=[float(scatter.loc[date, "x"])],
                    y=[float(scatter.loc[date, "y"])],
                )
            else:
                self._scatter_highlight.setData(x=[], y=[])

    def apply_theme(self, *, rerender: bool = True) -> None:
        chart_bg = self._theme_color("chart_bg")
        chart_axis = self._theme_color("chart_axis")
        border = self._theme_color("panel_border")
        for plot in self.plots:
            plot.setBackground(chart_bg)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setStyleSheet(f"border: 1px solid {border}; border-radius: 6px;")
            for axis_name in ("left", "right", "bottom"):
                plot.getPlotItem().getAxis(axis_name).setTextPen(chart_axis)
        if rerender and self._analysis:
            self.render_analysis(self._symbols, self._analysis)
