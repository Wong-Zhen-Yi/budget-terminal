from __future__ import annotations
from typing import Any
from ..dependencies import *
from ..persistence import fmt_num

class PieChartWidget(QWidget):
    COLORS = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990', '#dcbeff', '#9a6324', '#fffac8', '#800000', '#aaffc3']

    def __init__(self, parent: Any=None) -> None:
        """Initialize the object."""
        super().__init__(parent)
        self.slices = []
        self.slice_colors = tuple(self.COLORS)
        self.legend_text_color = '#ffffff'
        self._donut_enabled = False
        self._donut_hole_ratio = 0.56
        self._center_text = ''
        self._center_subtext = ''
        self._start_angle_degrees = 90.0
        self._animation_progress = 1.0
        self.setMinimumWidth(200)

    def set_theme(self, slice_colors: Any, legend_text_color: Any) -> None:
        """Apply a theme-aware color palette to the pie chart."""
        if isinstance(slice_colors, (list, tuple)) and slice_colors:
            self.slice_colors = tuple(str(color) for color in slice_colors)
        self.legend_text_color = str(legend_text_color or '#ffffff')
        if self.slices:
            self.slices = [
                (label, value, self.slice_colors[index % len(self.slice_colors)])
                for index, (label, value, _color) in enumerate(self.slices)
            ]
        self.update()

    def set_donut(self, enabled: bool=True, hole_ratio: float=0.56) -> None:
        """Toggle donut rendering and control the hole size."""
        self._donut_enabled = bool(enabled)
        self._donut_hole_ratio = max(0.2, min(0.85, float(hole_ratio)))
        self.update()

    def set_center_text(self, text: str='', subtext: str='') -> None:
        """Update the text shown in the donut center."""
        self._center_text = str(text or '')
        self._center_subtext = str(subtext or '')
        self.update()

    def set_start_angle(self, degrees: float=90.0) -> None:
        """Set the pie start angle in degrees, where 0 is the right side."""
        try:
            value = float(degrees)
        except (TypeError, ValueError):
            value = 90.0
        self._start_angle_degrees = value % 360.0
        self.update()

    def set_animation_progress(self, progress: float=1.0) -> None:
        """Set how much of the pie sweep is visible, from 0.0 to 1.0."""
        try:
            value = float(progress)
        except (TypeError, ValueError):
            value = 1.0
        self._animation_progress = max(0.0, min(1.0, value))
        self.update()

    def set_data(self, weights: dict) -> None:
        """Handle set data."""
        colors = self.slice_colors or tuple(self.COLORS)
        self.slices = [(t, v, colors[i % len(colors)]) for i, (t, v) in enumerate(weights.items()) if v > 0]
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Handle paintEvent."""
        from PyQt6.QtGui import QPainter, QColor, QFont
        from PyQt6.QtCore import QRectF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = (self.width(), self.height())
        margin = 10
        has_legend = bool(self.slices)
        legend_w = 110 if has_legend else 0
        content_w = max(0, w - legend_w - margin * 3) if has_legend else max(0, w - margin * 2)
        diameter = min(content_w, h - margin * 2)
        if diameter < 20:
            return
        block_w = diameter + (margin + legend_w if has_legend else 0)
        left = max(float(margin), (w - block_w) / 2)
        cx = left + diameter / 2
        cy = h / 2
        rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
        total = sum((v for _, v, _ in self.slices))
        if not self.slices or total == 0:
            if self._donut_enabled:
                outer_color = self.palette().color(QPalette.ColorRole.Mid)
                painter.setBrush(outer_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(rect)
                self._draw_donut_center(painter, cx, cy, diameter)
            return
        angle = int(self._start_angle_degrees * 16)
        remaining_span = int(360 * 16 * max(0.0, min(1.0, self._animation_progress)))
        for label, val, color in self.slices:
            if remaining_span <= 0:
                break
            full_span = int((val / total) * 360 * 16)
            visible_span = min(full_span, remaining_span)
            span = -visible_span
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(rect, angle, span)
            angle += span
            remaining_span -= visible_span
        if self._donut_enabled:
            self._draw_donut_center(painter, cx, cy, diameter)
        lx = int(left + diameter + margin)
        visible_items = min(len(self.slices), max(1, int((h - margin * 2) / 16)))
        legend_h = visible_items * 16
        ly = max(margin, int(cy - legend_h / 2))
        painter.setFont(QFont('Arial', 8))
        for label, val, color in self.slices:
            pct = (val / total) * 100 if total else 0
            painter.fillRect(lx, ly, 10, 10, QColor(color))
            painter.setPen(QColor(self.legend_text_color))
            painter.drawText(lx + 14, ly + 10, f'{label} {pct:.1f}%')
            ly += 16
            if ly > h - margin:
                break

    def _draw_donut_center(self, painter: Any, cx: float, cy: float, diameter: float) -> None:
        """Render the hollow center and optional center text."""
        from PyQt6.QtGui import QColor, QFont
        from PyQt6.QtCore import QRectF
        inner_diameter = diameter * self._donut_hole_ratio
        inner_rect = QRectF(
            cx - inner_diameter / 2,
            cy - inner_diameter / 2,
            inner_diameter,
            inner_diameter,
        )
        painter.setBrush(self.palette().color(QPalette.ColorRole.Window))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(inner_rect)

        painter.setPen(QColor(self.legend_text_color))
        value_font = QFont('Arial', 10)
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.drawText(inner_rect.adjusted(8, 20, -8, -2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._center_text)

        if self._center_subtext:
            sub_font = QFont('Arial', 8)
            painter.setFont(sub_font)
            painter.drawText(inner_rect.adjusted(8, 2, -8, -20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self._center_subtext)
