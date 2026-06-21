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
        self._callout_labels_enabled = False
        self._callout_base_minimum_height = 0
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
        self._update_callout_minimum_height()
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

    def set_callout_labels(self, enabled: bool=True) -> None:
        """Toggle Google Sheets-style external labels and leader lines."""
        enabled = bool(enabled)
        if enabled and not self._callout_labels_enabled:
            self._callout_base_minimum_height = max(int(self.minimumHeight()), 0)
        self._callout_labels_enabled = enabled
        if enabled:
            self._update_callout_minimum_height()
        else:
            self.setMinimumHeight(max(int(self._callout_base_minimum_height), 0))
        self.update()

    def set_data(self, weights: dict) -> None:
        """Handle set data."""
        colors = self.slice_colors or tuple(self.COLORS)
        self.slices = [(t, v, colors[i % len(colors)]) for i, (t, v) in enumerate(weights.items()) if v > 0]
        self._update_callout_minimum_height()
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Handle paintEvent."""
        from PyQt6.QtGui import QPainter, QColor, QFont
        from PyQt6.QtCore import QRectF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = (float(self.width()), float(self.height()))
        margin = 10
        callout_layout = self._build_callout_layout(w, h) if self._callout_labels_enabled else None
        if callout_layout is not None:
            rect = callout_layout['chart_rect']
            diameter = rect.width()
            cx = rect.center().x()
            cy = rect.center().y()
            has_legend = False
            legend_w = 0
            left = rect.left()
        else:
            has_legend = bool(self.slices)
            legend_w = 110 if has_legend else 0
            content_w = max(0, w - legend_w - margin * 3) if has_legend else max(0, w - margin * 2)
            diameter = min(content_w, h - margin * 2)
            block_w = diameter + (margin + legend_w if has_legend else 0)
            left = max(float(margin), (w - block_w) / 2)
            cx = left + diameter / 2
            cy = h / 2
            rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
        if diameter < 20:
            return
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
        if callout_layout is not None:
            self._draw_callout_labels(painter, callout_layout)
            return
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

    def _build_callout_layout(self, width: float, height: float) -> dict[str, Any]:
        """Return chart and external-label geometry for callout rendering."""
        from PyQt6.QtCore import QPointF, QRectF

        width = max(float(width), 1.0)
        height = max(float(height), 1.0)
        margin = 12.0
        max_side_width = max(30.0, (width - 80.0) / 2.0 - margin)
        side_width = min(max(80.0, width * 0.23), 220.0, max_side_width)
        content_width = max(20.0, width - (side_width + margin) * 2.0)
        diameter = max(20.0, min(content_width, height - margin * 2.0))
        cx = width / 2.0
        cy = height / 2.0
        chart_rect = QRectF(cx - diameter / 2.0, cy - diameter / 2.0, diameter, diameter)
        radius = diameter / 2.0
        total = sum(float(value or 0.0) for _label, value, _color in self.slices)
        items: list[dict[str, Any]] = []
        start_degrees = float(self._start_angle_degrees)
        if total > 0.0:
            for label, value, color in self.slices:
                value = float(value or 0.0)
                sweep_degrees = value / total * 360.0
                midpoint_degrees = start_degrees - sweep_degrees / 2.0
                midpoint_radians = math.radians(midpoint_degrees)
                direction_x = math.cos(midpoint_radians)
                direction_y = -math.sin(midpoint_radians)
                anchor = QPointF(cx + direction_x * radius, cy + direction_y * radius)
                items.append({
                    'label': str(label),
                    'value': value,
                    'percentage': value / total * 100.0,
                    'color': str(color),
                    'side': 'right' if direction_x >= 0.0 else 'left',
                    'anchor': anchor,
                    'direction_x': direction_x,
                    'direction_y': direction_y,
                })
                start_degrees -= sweep_degrees

        text_metrics = self._callout_text_metrics()
        font_size = float(text_metrics['font_size'])
        line_height = float(text_metrics['line_height'])
        label_block_height = float(text_metrics['label_block_height'])
        row_gap = float(text_metrics['row_gap'])
        top = margin + line_height + 2.0
        bottom = max(top, height - margin - line_height - 2.0)
        label_width = max(30.0, side_width - margin * 1.5)

        for side in ('left', 'right'):
            side_items = sorted(
                (item for item in items if item['side'] == side),
                key=lambda item: item['anchor'].y(),
            )
            target_ys = self._spread_callout_positions(side_items, top, bottom, row_gap)
            sign = -1.0 if side == 'left' else 1.0
            label_x = margin if side == 'left' else width - margin - label_width
            line_end_x = margin if side == 'left' else width - margin
            elbow_x = cx + sign * (radius + 12.0)
            for item, target_y in zip(side_items, target_ys):
                item['target_y'] = target_y
                item['elbow'] = QPointF(elbow_x, target_y)
                item['line_end'] = QPointF(line_end_x, target_y)
                item['label_x'] = label_x
                item['label_width'] = label_width
                item['ticker_rect'] = QRectF(
                    label_x,
                    target_y - line_height - 1.0,
                    label_width,
                    line_height,
                )
                item['percent_rect'] = QRectF(
                    label_x,
                    target_y + 1.0,
                    label_width,
                    line_height,
                )
                item['label_rect'] = QRectF(
                    label_x,
                    target_y - line_height - 1.0,
                    label_width,
                    label_block_height,
                )

        return {
            'chart_rect': chart_rect,
            'items': items,
            'font_size': font_size,
            'line_height': line_height,
            'label_block_height': label_block_height,
            'row_gap': row_gap,
            'top': top,
            'bottom': bottom,
            'required_height': self._required_callout_height(),
        }

    def _callout_text_metrics(self) -> dict[str, float]:
        """Return measured two-line callout dimensions and safe row spacing."""
        from PyQt6.QtGui import QFont, QFontMetrics

        font_size = 9.0
        label_font = QFont(self.font())
        label_font.setPointSizeF(font_size)
        label_font.setBold(False)
        line_height = max(float(QFontMetrics(label_font).height()), 8.0)
        label_block_height = line_height * 2.0 + 2.0
        return {
            'font_size': font_size,
            'line_height': line_height,
            'label_block_height': label_block_height,
            'row_gap': label_block_height + 8.0,
        }

    def _callout_side_counts(self) -> tuple[int, int]:
        """Return left and right callout counts for the current slice order."""
        total = sum(float(value or 0.0) for _label, value, _color in self.slices)
        if total <= 0.0:
            return 0, 0
        left = 0
        right = 0
        start_degrees = float(self._start_angle_degrees)
        for _label, value, _color in self.slices:
            value = float(value or 0.0)
            sweep_degrees = value / total * 360.0
            midpoint_degrees = start_degrees - sweep_degrees / 2.0
            if math.cos(math.radians(midpoint_degrees)) >= 0.0:
                right += 1
            else:
                left += 1
            start_degrees -= sweep_degrees
        return left, right

    def _required_callout_height(self) -> int:
        """Return the minimum height needed for non-overlapping callouts."""
        if not self._callout_labels_enabled or not self.slices:
            return max(int(self._callout_base_minimum_height), 0)
        text_metrics = self._callout_text_metrics()
        line_height = float(text_metrics['line_height'])
        row_gap = float(text_metrics['row_gap'])
        max_side_count = max(*self._callout_side_counts(), 1)
        edge_space = 2.0 * (12.0 + line_height + 2.0)
        required = edge_space + max(max_side_count - 1, 0) * row_gap
        return max(int(math.ceil(required)), int(self._callout_base_minimum_height), 0)

    def _update_callout_minimum_height(self) -> None:
        """Keep enough vertical space for all enabled callout labels."""
        if not self._callout_labels_enabled:
            return
        required_height = self._required_callout_height()
        if int(self.minimumHeight()) != required_height:
            self.setMinimumHeight(required_height)

    @staticmethod
    def _spread_callout_positions(items: list[dict[str, Any]], top: float, bottom: float, gap: float) -> list[float]:
        """Spread one side's labels vertically while preserving slice order."""
        if not items:
            return []
        if len(items) == 1:
            return [min(max(float(items[0]['anchor'].y()), top), bottom)]
        positions: list[float] = []
        for item in items:
            anchor_y = min(max(float(item['anchor'].y()), top), bottom)
            positions.append(max(anchor_y, positions[-1] + gap) if positions else anchor_y)
        overflow = max(positions[-1] - bottom, 0.0)
        if overflow:
            positions = [position - overflow for position in positions]
        for index in range(len(positions) - 2, -1, -1):
            positions[index] = min(positions[index], positions[index + 1] - gap)
        underflow = max(top - positions[0], 0.0)
        if underflow:
            positions = [position + underflow for position in positions]
        return positions

    def _draw_callout_labels(self, painter: Any, layout: dict[str, Any]) -> None:
        """Draw leader lines plus ticker and percentage labels."""
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen

        primary_color = QColor(self.legend_text_color)
        secondary_color = QColor(primary_color)
        secondary_color.setAlpha(160)
        line_color = QColor(primary_color)
        line_color.setAlpha(125)
        line_pen = QPen(line_color)
        line_pen.setWidthF(0.9)

        label_font = QFont(self.font())
        label_font.setPointSizeF(float(layout.get('font_size', 9.0)))
        label_font.setBold(False)
        metrics = QFontMetrics(label_font)
        alignments = {
            'left': Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            'right': Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        }

        for item in layout.get('items', []):
            painter.setPen(line_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(item['anchor'], item['elbow'])
            painter.drawLine(item['elbow'], item['line_end'])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(line_color)
            painter.drawEllipse(item['anchor'], 1.8, 1.8)

            side = str(item['side'])
            label_width = float(item['label_width'])
            ticker = metrics.elidedText(str(item['label']), Qt.TextElideMode.ElideRight, max(int(label_width), 1))

            painter.setFont(label_font)
            painter.setPen(primary_color)
            painter.drawText(item['ticker_rect'], alignments[side], ticker)
            painter.setPen(secondary_color)
            painter.drawText(item['percent_rect'], alignments[side], f"{float(item['percentage']):.1f}%")

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
