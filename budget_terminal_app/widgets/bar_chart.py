from __future__ import annotations
import math
from typing import Any
from ..dependencies import *


class BarChartWidget(QWidget):

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.items = []
        self.text_color = '#ffffff'
        self.value_prefix = '$'
        self.use_log = True
        self.setMinimumWidth(200)
        self.setMinimumHeight(120)

    def set_theme(self, text_color: Any) -> None:
        self.text_color = str(text_color or '#ffffff')
        self.update()

    def set_value_prefix(self, prefix: Any) -> None:
        """Set the currency/value prefix used for bar labels."""
        self.value_prefix = str(prefix or '$')
        self.update()

    def set_data(self, items: list[Any]) -> None:
        """Accept flat bars or stacked bars."""
        normalized = []
        for item in items:
            normalized_item = self._normalize_item(item)
            if normalized_item is not None:
                normalized.append(normalized_item)
        self.items = sorted(normalized, key=lambda item: abs(item['value']), reverse=True)
        self.update()

    def _normalize_item(self, item: Any) -> Any:
        """Normalize one chart item into label, value, and segment metadata."""
        if isinstance(item, dict):
            label = str(item.get('label', '') or '')
            raw_segments = item.get('segments', [])
            segments = []
            for segment in raw_segments if isinstance(raw_segments, (list, tuple)) else []:
                if isinstance(segment, dict):
                    value = segment.get('value', 0.0)
                    color = segment.get('color', '#888888')
                elif isinstance(segment, (tuple, list)) and len(segment) >= 2:
                    value, color = segment[0], segment[1]
                else:
                    continue
                try:
                    amount = abs(float(value or 0.0))
                except (TypeError, ValueError):
                    amount = 0.0
                if amount > 0:
                    segments.append({'value': amount, 'color': str(color or '#888888')})
            total = sum(segment['value'] for segment in segments)
            return {'label': label, 'value': total, 'segments': segments} if total > 0 else None
        if isinstance(item, (tuple, list)) and len(item) >= 3:
            label, value, color = item[0], item[1], item[2]
            try:
                amount = float(value or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            if amount == 0:
                return None
            return {
                'label': str(label or ''),
                'value': abs(amount),
                'segments': [{'value': abs(amount), 'color': str(color or '#888888')}],
            }
        return None

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
        max_abs = max(abs(item['value']) for item in self.items)
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
        for item in self.items:
            label = item['label']
            value = item['value']
            segments = item['segments']
            if self.use_log:
                col_h = int((math.log1p(abs(value)) / math.log1p(max_abs)) * bar_area_h)
            else:
                col_h = int((abs(value) / max_abs) * bar_area_h)
            if col_h <= 0:
                col_h = 1
            col_y = bar_bottom - col_h
            painter.setPen(Qt.PenStyle.NoPen)
            segment_y = bar_bottom
            remaining_h = col_h
            total_segment_value = sum(segment['value'] for segment in segments)
            for index, segment in enumerate(segments):
                if remaining_h <= 0 or total_segment_value <= 0:
                    break
                if index == len(segments) - 1:
                    segment_h = remaining_h
                else:
                    future_segments = len(segments) - index - 1
                    segment_h = int(round(col_h * (segment['value'] / total_segment_value)))
                    segment_h = min(max(segment_h, 1), max(remaining_h - future_segments, 1))
                segment_y -= segment_h
                painter.setBrush(QColor(segment['color']))
                painter.drawRoundedRect(QRectF(x, segment_y, col_w, segment_h), 3, 3)
                remaining_h -= segment_h
            painter.setPen(QColor(self.text_color))
            val_text = f'{self.value_prefix}{abs(value):,.0f}'
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
