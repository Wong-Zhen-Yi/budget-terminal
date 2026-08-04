from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from budget_terminal_app.services.chart_pattern_catalog import (
    CHART_PATTERN_BIASES,
    CHART_PATTERN_CATALOG,
    CHART_PATTERN_FAMILIES,
    ChartPatternDefinition,
)


ThemeColor = Callable[[str], str]


class ChartPatternDiagramWidget(QWidget):
    """Render one deterministic chart-pattern diagram without a plotting engine."""

    ASPECT_WIDTH = 16
    ASPECT_HEIGHT = 9
    PREFERRED_WIDTH = 480
    MINIMUM_WIDTH = 320

    def __init__(self, pattern: ChartPatternDefinition, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pattern = pattern
        self._colors = {
            "background": "#10151d",
            "border": "#283241",
            "grid": "#334155",
            "text": "#94a3b8",
            "bullish": "#34d399",
            "bearish": "#fb7185",
            "neutral": "#60a5fa",
            "marker": "#fbbf24",
        }
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        size_policy.setHeightForWidth(True)
        self.setSizePolicy(size_policy)
        self.setAccessibleName(f"{pattern.name} schematic chart pattern")

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt virtual method
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt virtual method
        return round(max(0, int(width)) * self.ASPECT_HEIGHT / self.ASPECT_WIDTH)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method
        return QSize(self.PREFERRED_WIDTH, self.heightForWidth(self.PREFERRED_WIDTH))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method
        return QSize(self.MINIMUM_WIDTH, self.heightForWidth(self.MINIMUM_WIDTH))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        target_height = self.heightForWidth(event.size().width())
        if self.minimumHeight() != target_height or self.maximumHeight() != target_height:
            self.setFixedHeight(target_height)
        super().resizeEvent(event)

    @property
    def colors(self) -> dict[str, str]:
        return dict(self._colors)

    def set_colors(self, colors: dict[str, str]) -> None:
        self._colors.update({key: str(value) for key, value in colors.items() if key in self._colors})
        self.update()
    def _chart_point(self, point: tuple[float, float], rect: QRectF) -> QPointF:
        x_value, y_value = point
        return QPointF(
            rect.left() + float(x_value) * rect.width(),
            rect.bottom() - float(y_value) * rect.height(),
        )

    def _draw_arrow(self, painter: QPainter, start: QPointF, end: QPointF, color: QColor) -> None:
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, end)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 7.0
        for offset in (math.pi * 0.82, -math.pi * 0.82):
            head = QPointF(
                end.x() + math.cos(angle + offset) * size,
                end.y() + math.sin(angle + offset) * size,
            )
            painter.drawLine(end, head)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(self._colors["border"]), 1.0))
        painter.setBrush(QColor(self._colors["background"]))
        painter.drawRoundedRect(outer, 7.0, 7.0)

        chart_rect = outer.adjusted(13.0, 13.0, -14.0, -14.0)
        grid_color = QColor(self._colors["grid"])
        grid_color.setAlpha(58)
        painter.setPen(QPen(grid_color, 0.8, Qt.PenStyle.DotLine))
        for fraction in (0.25, 0.5, 0.75):
            y_value = chart_rect.top() + chart_rect.height() * fraction
            painter.drawLine(QPointF(chart_rect.left(), y_value), QPointF(chart_rect.right(), y_value))

        guide_font = QFont(painter.font())
        guide_font.setPointSizeF(max(7.0, guide_font.pointSizeF() - 2.0))
        painter.setFont(guide_font)
        for guide in self.pattern.guide_lines:
            color_key = "bullish" if guide.role == "support" else "bearish" if guide.role == "resistance" else "grid"
            guide_color = QColor(self._colors[color_key])
            guide_color.setAlpha(155)
            painter.setPen(QPen(guide_color, 1.1, Qt.PenStyle.DashLine))
            start = self._chart_point(guide.start, chart_rect)
            end = self._chart_point(guide.end, chart_rect)
            painter.drawLine(start, end)
            text_rect = QRectF(
                min(end.x() + 3.0, chart_rect.right() - 92.0),
                max(chart_rect.top(), min(end.y() - 15.0, chart_rect.bottom() - 15.0)),
                90.0,
                14.0,
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, guide.label)

        bias_key = self.pattern.bias.casefold()
        path_color = QColor(self._colors.get(bias_key, self._colors["neutral"]))
        path = QPainterPath()
        first = self._chart_point(self.pattern.price_path[0], chart_rect)
        path.moveTo(first)
        for point in self.pattern.price_path[1:]:
            path.lineTo(self._chart_point(point, chart_rect))
        painter.setPen(QPen(path_color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        marker = self._chart_point(self.pattern.breakout_marker, chart_rect)
        marker_color = QColor(self._colors["marker"])
        painter.setPen(QPen(marker_color, 1.2))
        painter.setBrush(marker_color)
        painter.drawEllipse(marker, 3.8, 3.8)

        horizontal_step = max(22.0, chart_rect.width() * 0.075)
        vertical_step = max(20.0, chart_rect.height() * 0.18)

        def clamped_end(y_delta: float) -> QPointF:
            return QPointF(
                min(chart_rect.right(), marker.x() + horizontal_step),
                max(chart_rect.top() + 3.0, min(chart_rect.bottom() - 3.0, marker.y() + y_delta)),
            )

        if self.pattern.direction == "up":
            self._draw_arrow(painter, marker, clamped_end(-vertical_step), path_color)
        elif self.pattern.direction == "down":
            self._draw_arrow(painter, marker, clamped_end(vertical_step), path_color)
        else:
            neutral = QColor(self._colors["neutral"])
            self._draw_arrow(painter, marker, clamped_end(-vertical_step * 0.8), neutral)
            self._draw_arrow(painter, marker, clamped_end(vertical_step * 0.8), neutral)
        painter.end()


class ChartPatternCard(QFrame):
    """A complete, always-expanded reference card for one classical pattern."""

    def __init__(self, pattern: ChartPatternDefinition, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pattern = pattern
        self.setObjectName("chartPatternCard")
        self.setProperty("bt_role", "panel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(340)
        self.setMinimumHeight(455)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(f"{pattern.name} chart pattern reference card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        self.title_label = QLabel(pattern.name)
        self.title_label.setProperty("bt_role", "section_title")
        self.title_label.setWordWrap(True)
        title_row.addWidget(self.title_label, 1)
        self.family_badge = QLabel(pattern.family)
        self.family_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bias_badge = QLabel(pattern.bias)
        self.bias_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.family_badge)
        title_row.addWidget(self.bias_badge)
        layout.addLayout(title_row)

        self.diagram = ChartPatternDiagramWidget(pattern, self)
        layout.addWidget(self.diagram)

        self.detail_labels: dict[str, QLabel] = {}
        for key, heading, value in (
            ("recognition", "Recognition", pattern.recognition),
            ("confirmation", "Confirmation", pattern.confirmation),
            ("invalidation", "Invalidation", pattern.invalidation),
            ("target", "Target", pattern.target),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            heading_label = QLabel(heading)
            heading_label.setProperty("bt_role", "muted")
            heading_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            heading_label.setFixedWidth(78)
            value_label = QLabel(value)
            value_label.setProperty("bt_role", "muted")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(heading_label)
            row.addWidget(value_label, 1)
            layout.addLayout(row)
            self.detail_labels[key] = value_label
        layout.addStretch(1)

    def apply_theme(self, theme_color: ThemeColor) -> None:
        bias_token = {
            "Bullish": "accent_positive",
            "Bearish": "accent_negative",
            "Neutral": "accent",
        }[self.pattern.bias]
        family_color = theme_color("text_secondary")
        bias_color = theme_color(bias_token)
        self.setStyleSheet(
            "QFrame#chartPatternCard {"
            f"background: {theme_color('panel_background')};"
            f"border: 1px solid {theme_color('panel_border')};"
            "border-radius: 8px;"
            "}"
        )
        self.family_badge.setStyleSheet(
            f"color: {family_color}; border: 1px solid {theme_color('panel_border')};"
            "border-radius: 8px; padding: 2px 6px; font-size: 10px;"
        )
        self.bias_badge.setStyleSheet(
            f"color: {bias_color}; border: 1px solid {bias_color};"
            "border-radius: 8px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )
        self.diagram.set_colors({
            "background": theme_color("chart_bg"),
            "border": theme_color("panel_border"),
            "grid": theme_color("chart_reference"),
            "text": theme_color("text_muted"),
            "bullish": theme_color("accent_positive"),
            "bearish": theme_color("accent_negative"),
            "neutral": theme_color("accent"),
            "marker": theme_color("warning"),
        })


class _PatternGridHost(QWidget):
    resized = pyqtSignal(int)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        super().resizeEvent(event)
        self.resized.emit(int(event.size().width()))


class ChartPatternCheatSheet(QWidget):
    """Offline searchable reference for the app's classical chart patterns."""

    status_changed = pyqtSignal(str)

    def __init__(self, theme_color: ThemeColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_color = theme_color
        self._catalog = CHART_PATTERN_CATALOG
        self._reflowing = False
        self.column_count = 1
        self._visible_patterns = list(self._catalog)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Chart Pattern Cheat Sheet")
        title.setProperty("bt_role", "page_title")
        layout.addWidget(title)
        subtitle = QLabel("24 major classical formations with deterministic diagrams and actionable reference rules.")
        subtitle.setProperty("bt_role", "muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(7)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search patterns...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Search chart patterns")
        controls.addWidget(self.search_input, 1)
        self.family_combo = QComboBox()
        self.family_combo.setAccessibleName("Filter chart patterns by family")
        self.family_combo.addItem("All families", "")
        for family in CHART_PATTERN_FAMILIES:
            self.family_combo.addItem(family, family)
        controls.addWidget(self.family_combo)
        self.bias_combo = QComboBox()
        self.bias_combo.setAccessibleName("Filter chart patterns by bias")
        self.bias_combo.addItem("All biases", "")
        for bias in CHART_PATTERN_BIASES:
            self.bias_combo.addItem(bias, bias)
        controls.addWidget(self.bias_combo)
        self.count_label = QLabel()
        self.count_label.setProperty("bt_role", "muted")
        self.count_label.setMinimumWidth(105)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.count_label)
        layout.addLayout(controls)

        self.notice_label = QLabel(
            "Educational reference only. Patterns are probabilistic, typical bias is not guaranteed, "
            "and confirmation and invalidation should be considered before use."
        )
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)

        self.status_label = QLabel()
        self.status_label.setProperty("bt_role", "muted")
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_host = _PatternGridHost()
        self.card_grid = QGridLayout(self.card_host)
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        self.card_grid.setHorizontalSpacing(10)
        self.card_grid.setVerticalSpacing(10)
        self.card_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.card_host)
        layout.addWidget(self.scroll, 1)

        self.cards = {
            pattern.pattern_id: ChartPatternCard(pattern, self.card_host)
            for pattern in self._catalog
        }
        self.empty_label = QLabel("No patterns match the current search and filters.", self.card_host)
        self.empty_label.setProperty("bt_role", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(120)

        self.search_input.textChanged.connect(self._apply_filters)
        self.family_combo.currentIndexChanged.connect(self._apply_filters)
        self.bias_combo.currentIndexChanged.connect(self._apply_filters)
        self.card_host.resized.connect(self._on_grid_width_changed)
        self.apply_theme()
        self._apply_filters()

    @property
    def catalog(self) -> tuple[ChartPatternDefinition, ...]:
        return self._catalog

    @property
    def status_text(self) -> str:
        return str(self.status_label.text())

    def visible_pattern_ids(self) -> tuple[str, ...]:
        return tuple(pattern.pattern_id for pattern in self._visible_patterns)

    @staticmethod
    def columns_for_width(width: int) -> int:
        numeric_width = max(0, int(width))
        if numeric_width < 900:
            return 1
        if numeric_width < 1400:
            return 2
        return 3

    def _pattern_matches(self, pattern: ChartPatternDefinition, query: str, family: str, bias: str) -> bool:
        if family and pattern.family != family:
            return False
        if bias and pattern.bias != bias:
            return False
        if not query:
            return True
        search_text = " ".join((
            pattern.name,
            *pattern.aliases,
            pattern.family,
            pattern.bias,
            pattern.recognition,
        )).casefold()
        return query in search_text

    def _apply_filters(self, *_args) -> None:
        query = str(self.search_input.text() or "").strip().casefold()
        family = str(self.family_combo.currentData() or "")
        bias = str(self.bias_combo.currentData() or "")
        self._visible_patterns = [
            pattern
            for pattern in self._catalog
            if self._pattern_matches(pattern, query, family, bias)
        ]
        shown = len(self._visible_patterns)
        total = len(self._catalog)
        self.count_label.setText(f"{shown} of {total} patterns")
        self.status_label.setText(f"Cheat Sheet · {shown} of {total} patterns · Offline reference")
        self._reflow_cards()
        self.status_changed.emit(self.status_label.text())

    def _on_grid_width_changed(self, width: int) -> None:
        target_columns = self.columns_for_width(width)
        if target_columns != self.column_count:
            self._reflow_cards(width=width)

    def _reflow_cards(self, *, width: int | None = None) -> None:
        if self._reflowing:
            return
        self._reflowing = True
        try:
            effective_width = int(width if width is not None else self.card_host.width())
            columns = self.columns_for_width(effective_width)
            while self.card_grid.count():
                self.card_grid.takeAt(0)
            visible_ids = {pattern.pattern_id for pattern in self._visible_patterns}
            for card_id, card in self.cards.items():
                card.setVisible(card_id in visible_ids)
            self.empty_label.setVisible(not self._visible_patterns)
            if not self._visible_patterns:
                self.card_grid.addWidget(self.empty_label, 0, 0, 1, columns)
            else:
                for index, pattern in enumerate(self._visible_patterns):
                    row, column = divmod(index, columns)
                    self.card_grid.addWidget(self.cards[pattern.pattern_id], row, column)
            for column in range(3):
                self.card_grid.setColumnStretch(column, 1 if column < columns else 0)
            self.column_count = columns
            self.card_host.updateGeometry()
        finally:
            self._reflowing = False

    def refresh_layout(self) -> None:
        self._reflow_cards(width=self.scroll.viewport().width())

    def apply_theme(self) -> None:
        self.notice_label.setStyleSheet(
            f"color: {self._theme_color('warning')};"
            f"background: {self._theme_color('warning_bg')};"
            f"border: 1px solid {self._theme_color('warning')};"
            "border-radius: 6px; padding: 6px 8px;"
        )
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        for card in self.cards.values():
            card.apply_theme(self._theme_color)
        self.empty_label.setStyleSheet(f"color: {self._theme_color('text_muted')};")
        self.update()
