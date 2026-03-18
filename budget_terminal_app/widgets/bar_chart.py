from __future__ import annotations
import math
from typing import Any
from ..dependencies import *


class BarChartWidget(QWidget):

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.items = []
        self.text_color = '#ffffff'
        self.use_log = True
        self.setMinimumWidth(200)
        self.setMinimumHeight(120)

    def set_theme(self, text_color: Any) -> None:
        self.text_color = str(text_color or '#ffffff')
        self.update()

    def set_data(self, items: list[tuple[str, float, str]]) -> None:
        """Accept list of (label, value, color) tuples."""
        self.items = sorted([(l, v, c) for l, v, c in items if v != 0], key=lambda x: abs(x[1]), reverse=True)
        self.update()

    def paintEvent(self, event: Any) -> None:
        from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics
        from PyQt6.QtCore import QRectF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.items:
            return
        w, h = self.width(), self.height()
        margin = 10
        font = QFont('Arial', 8)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text_height = fm.height()
        label_area = text_height * 2 + 4
        value_area = text_height + 2
        max_abs = max(abs(v) for _, v, _ in self.items)
        if max_abs == 0:
            return
        n = len(self.items)
        available_w = w - margin * 2
        gap = max(4, int(available_w * 0.02))
        col_w = max(12, (available_w - gap * (n - 1)) // n) if n > 0 else 12
        total_w = col_w * n + gap * (n - 1)
        x_start = margin + (available_w - total_w) / 2
        bar_top = margin + value_area + 4
        bar_bottom = h - margin - label_area
        bar_area_h = bar_bottom - bar_top
        if bar_area_h < 20:
            bar_area_h = 20
            bar_bottom = bar_top + bar_area_h
        x = x_start
        for label, value, color in self.items:
            if self.use_log:
                col_h = int((math.log1p(abs(value)) / math.log1p(max_abs)) * bar_area_h)
            else:
                col_h = int((abs(value) / max_abs) * bar_area_h)
            col_y = bar_bottom - col_h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, col_y, col_w, col_h), 3, 3)
            painter.setPen(QColor(self.text_color))
            val_text = f'${abs(value):,.0f}'
            painter.drawText(int(x), int(col_y - value_area - 2), int(col_w), int(value_area),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, val_text)
            label_rect_y = bar_bottom + 2
            lines = self._wrap_label(fm, label, col_w)
            for i, line in enumerate(lines[:2]):
                painter.drawText(int(x), int(label_rect_y + i * text_height), int(col_w), int(text_height),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
            x += col_w + gap

    @staticmethod
    def _wrap_label(fm: Any, text: str, max_w: int) -> list[str]:
        if fm.horizontalAdvance(text) <= max_w:
            return [text]
        words = text.split()
        lines = []
        current = ''
        for word in words:
            test = f'{current} {word}'.strip()
            if fm.horizontalAdvance(test) <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines if lines else [text]
