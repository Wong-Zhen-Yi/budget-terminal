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
        self.setMinimumWidth(200)

    def set_data(self, weights: dict) -> None:
        """Handle set data."""
        colors = self.COLORS
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
        legend_w = 110
        diameter = min(w - legend_w - margin * 3, h - margin * 2)
        if diameter < 20 or not self.slices:
            return
        cx = margin + diameter / 2
        cy = h / 2
        rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
        total = sum((v for _, v, _ in self.slices))
        if total == 0:
            return
        angle = 90 * 16
        for label, val, color in self.slices:
            span = int(-(val / total) * 360 * 16)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(rect, angle, span)
            angle += span
        lx = int(cx + diameter / 2 + margin)
        ly = margin
        painter.setFont(QFont('Arial', 8))
        for label, val, color in self.slices:
            painter.fillRect(lx, ly, 10, 10, QColor(color))
            painter.setPen(QColor('white'))
            painter.drawText(lx + 14, ly + 10, f'{label} {val:.1f}%')
            ly += 16
            if ly > h - margin:
                break
