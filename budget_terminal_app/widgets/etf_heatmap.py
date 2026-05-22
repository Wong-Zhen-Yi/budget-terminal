from __future__ import annotations

from typing import Any

from ..dependencies import *


class EtfHeatmapWidget(QWidget):
    holdingSelected = pyqtSignal(dict)
    holdingActivated = pyqtSignal(str)
    _LEFT_DRAG_THRESHOLD = 4.0

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._tile_rects: list[tuple[Any, dict[str, Any]]] = []
        self._selected_symbol = ""
        self._empty_message = "Load ETF holdings to render the heatmap"
        self._zoom_scale = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._panning = False
        self._last_pan_pos: Any = None
        self._left_press_pos: Any = None
        self._left_last_pan_pos: Any = None
        self._left_drag_active = False
        self._colors = {
            "background": "#101418",
            "panel": "#171d24",
            "border": "#2a3340",
            "text": "#f2f5f7",
            "muted": "#9aa6b2",
            "up": "#4caf50",
            "down": "#f44336",
            "neutral": "#2b333d",
            "accent": "#42a5f5",
        }
        self.setMouseTracking(True)
        self.setMinimumHeight(300)
        self.setMinimumWidth(640)

    def set_empty_message(self, message: Any) -> None:
        """Set the centered message shown when no heatmap rows are available."""
        self._empty_message = str(message or "").strip() or "No heatmap data available"
        self.update()

    def set_theme(
        self,
        *,
        background: str,
        panel: str,
        border: str,
        text: str,
        muted: str,
        up: str,
        down: str,
        accent: str,
    ) -> None:
        self._colors.update({
            "background": background,
            "panel": panel,
            "border": border,
            "text": text,
            "muted": muted,
            "up": up,
            "down": down,
            "neutral": panel,
            "accent": accent,
        })
        self.update()

    def set_data(self, rows: list[dict[str, Any]], *, reset_view: bool = True) -> None:
        self._rows = [
            dict(row)
            for row in rows
            if str(row.get("symbol", "") or "").strip() and self._positive_weight(row.get("weight")) > 0
        ]
        if self._selected_symbol and not any(row.get("symbol") == self._selected_symbol for row in self._rows):
            self._selected_symbol = ""
        if reset_view:
            self._reset_view()
        self.update()

    def selected_symbol(self) -> str:
        return self._selected_symbol

    def paintEvent(self, event: Any) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._colors["background"]))
        self._tile_rects = []
        if not self._rows:
            painter.setPen(QColor(self._colors["muted"]))
            painter.setFont(QFont("Arial", 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_message)
            return

        self._clamp_view()
        viewport = QRectF(0, 0, max(1, self.width()), max(1, self.height()))
        outer = QRectF(8, 8, max(1, self.width() - 16), max(1, self.height() - 16))
        sector_groups: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows:
            sector = str(row.get("sector") or "Unclassified").strip() or "Unclassified"
            sector_groups.setdefault(sector, []).append(row)
        sector_items = sorted(
            ((sector, rows, sum(self._positive_weight(row.get("weight")) for row in rows)) for sector, rows in sector_groups.items()),
            key=lambda item: item[2],
            reverse=True,
        )
        sector_layout = self._binary_layout(
            [(sector, rows, total) for sector, rows, total in sector_items if total > 0],
            outer,
            lambda item: item[2],
        )

        title_font = QFont("Arial", 9)
        title_font.setBold(True)
        tile_font = QFont("Arial", 9)
        tile_font.setBold(True)
        small_font = QFont("Arial", 8)

        for sector_rect, sector_payload in sector_layout:
            visible_sector_rect = self._visible_rect(sector_rect)
            if not visible_sector_rect.intersects(viewport):
                continue
            sector, rows, total_weight = sector_payload
            if visible_sector_rect.width() < 3 or visible_sector_rect.height() < 3:
                continue
            painter.setPen(QPen(QColor(self._colors["border"]), 1))
            painter.setBrush(QColor(self._colors["panel"]))
            painter.drawRoundedRect(visible_sector_rect, 4, 4)

            header_h = 22 if sector_rect.height() >= 58 and sector_rect.width() >= 90 else 0
            if header_h:
                painter.setPen(QColor(self._colors["text"]))
                painter.setFont(title_font)
                sector_label = f"{sector} {total_weight * 100:.1f}%"
                visible_header = self._visible_rect(
                    QRectF(sector_rect.left(), sector_rect.top(), sector_rect.width(), header_h)
                )
                painter.drawText(
                    visible_header.adjusted(6, 2, -6, -2),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    sector_label,
                )
            inner = sector_rect.adjusted(3, 3 + header_h, -3, -3)
            if inner.width() <= 1 or inner.height() <= 1:
                continue
            tile_layout = self._binary_layout(
                sorted(rows, key=lambda row: self._positive_weight(row.get("weight")), reverse=True),
                inner,
                lambda row: self._positive_weight(row.get("weight")),
            )
            for tile_rect, row in tile_layout:
                draw_rect = self._visible_rect(tile_rect.adjusted(1, 1, -1, -1))
                if not draw_rect.intersects(viewport):
                    continue
                if draw_rect.width() < 1 or draw_rect.height() < 1:
                    continue
                self._tile_rects.append((draw_rect, row))
                color = self._heat_color(row.get("change_pct"), row)
                painter.setPen(QPen(QColor(self._colors["background"]), 1))
                painter.setBrush(color)
                painter.drawRoundedRect(draw_rect, 3, 3)
                if str(row.get("symbol") or "") == self._selected_symbol:
                    painter.setPen(QPen(QColor(self._colors["accent"]), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(draw_rect.adjusted(1, 1, -1, -1), 3, 3)
                self._draw_tile_labels(painter, draw_rect, row, tile_font, small_font)

    def mouseMoveEvent(self, event: Any) -> None:
        from PyQt6.QtWidgets import QToolTip

        if self._panning and self._zoom_scale > 1.0:
            if not (event.buttons() & Qt.MouseButton.RightButton):
                self._panning = False
                self._last_pan_pos = None
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                return super().mouseMoveEvent(event)
            pos = self._event_position(event)
            self._pan_from_positions(pos, self._last_pan_pos)
            self._last_pan_pos = pos
            QToolTip.hideText()
            event.accept()
            return

        if self._left_press_pos is not None and self._zoom_scale > 1.0:
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                self._clear_left_drag()
                return super().mouseMoveEvent(event)
            pos = self._event_position(event)
            if not self._left_drag_active and self._drag_distance(pos, self._left_press_pos) >= self._LEFT_DRAG_THRESHOLD:
                self._left_drag_active = True
                self._left_last_pan_pos = self._left_press_pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._left_drag_active:
                self._pan_from_positions(pos, self._left_last_pan_pos)
                self._left_last_pan_pos = pos
                QToolTip.hideText()
                event.accept()
                return

        row = self._row_at(self._event_position(event))
        if not row:
            QToolTip.hideText()
            return
        tooltip = self._tooltip(row)
        global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
        QToolTip.showText(global_pos, tooltip, self)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._zoom_scale > 1.0:
            self._panning = True
            self._last_pan_pos = self._event_position(event)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if self._zoom_scale > 1.0:
            self._left_press_pos = self._event_position(event)
            self._left_last_pan_pos = self._left_press_pos
            self._left_drag_active = False
            event.accept()
            return
        row = self._row_at(self._event_position(event))
        if row:
            self._selected_symbol = str(row.get("symbol") or "")
            self.holdingSelected.emit(dict(row))
            self.update()

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        if self._left_drag_active:
            self._clear_left_drag()
            event.accept()
            return
        self._clear_left_drag()
        row = self._row_at(self._event_position(event))
        symbol = str((row or {}).get("symbol") or "").upper().strip()
        if symbol:
            self.holdingActivated.emit(symbol)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._panning:
            self._panning = False
            self._last_pan_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._zoom_scale > 1.0 else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._left_press_pos is not None:
            was_drag = self._left_drag_active
            self._clear_left_drag()
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._zoom_scale > 1.0 else Qt.CursorShape.ArrowCursor)
            if not was_drag:
                row = self._row_at(self._event_position(event))
                if row:
                    self._selected_symbol = str(row.get("symbol") or "")
                    self.holdingSelected.emit(dict(row))
                    self.update()
            event.accept()
            return
        return super().mouseReleaseEvent(event)

    def wheelEvent(self, event: Any) -> None:
        if not self._rows:
            return super().wheelEvent(event)
        delta = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
        if not delta and hasattr(event, "pixelDelta"):
            delta = event.pixelDelta().y()
        if not delta:
            return super().wheelEvent(event)
        factor = 1.15 ** (float(delta) / 120.0)
        self._set_zoom_at(self._zoom_scale * factor, self._event_position(event))
        event.accept()

    def resizeEvent(self, event: Any) -> None:
        self._clamp_view()
        return super().resizeEvent(event)

    def leaveEvent(self, event: Any) -> None:
        from PyQt6.QtWidgets import QToolTip

        QToolTip.hideText()
        return super().leaveEvent(event)

    def _reset_view(self) -> None:
        self._zoom_scale = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._panning = False
        self._last_pan_pos = None
        self._clear_left_drag()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _set_zoom_at(self, scale: float, anchor: Any) -> None:
        old_scale = self._zoom_scale
        new_scale = max(1.0, min(6.0, float(scale)))
        if not math.isfinite(new_scale):
            return
        x, y = self._point_xy(anchor)
        virtual_x = (x + self._pan_x) / old_scale
        virtual_y = (y + self._pan_y) / old_scale
        self._zoom_scale = new_scale
        self._pan_x = virtual_x * new_scale - x
        self._pan_y = virtual_y * new_scale - y
        self._clamp_view()
        if self._zoom_scale <= 1.0:
            self._panning = False
            self._last_pan_pos = None
            self._clear_left_drag()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif not self._panning:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def _clear_left_drag(self) -> None:
        self._left_press_pos = None
        self._left_last_pan_pos = None
        self._left_drag_active = False

    def _pan_from_positions(self, current: Any, previous: Any) -> None:
        if previous is None:
            return
        x, y = self._point_xy(current)
        last_x, last_y = self._point_xy(previous)
        self._pan_x -= x - last_x
        self._pan_y -= y - last_y
        self._clamp_view()
        self.update()

    def _drag_distance(self, current: Any, start: Any) -> float:
        x, y = self._point_xy(current)
        start_x, start_y = self._point_xy(start)
        return math.hypot(x - start_x, y - start_y)

    def _clamp_view(self) -> None:
        if self._zoom_scale <= 1.0:
            self._zoom_scale = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
            return
        virtual_width = max(1.0, float(self.width())) * self._zoom_scale
        virtual_height = max(1.0, float(self.height())) * self._zoom_scale
        max_pan_x = max(0.0, virtual_width - max(1.0, float(self.width())))
        max_pan_y = max(0.0, virtual_height - max(1.0, float(self.height())))
        self._pan_x = max(0.0, min(max_pan_x, self._pan_x))
        self._pan_y = max(0.0, min(max_pan_y, self._pan_y))

    def _visible_rect(self, rect: Any) -> Any:
        from PyQt6.QtCore import QRectF

        return QRectF(
            rect.left() * self._zoom_scale - self._pan_x,
            rect.top() * self._zoom_scale - self._pan_y,
            rect.width() * self._zoom_scale,
            rect.height() * self._zoom_scale,
        )

    def _draw_tile_labels(self, painter: Any, draw_rect: Any, row: dict[str, Any], tile_font: Any, small_font: Any) -> None:
        from PyQt6.QtGui import QColor, QFontMetrics

        if draw_rect.width() < 34 or draw_rect.height() < 22:
            return
        painter.setPen(QColor(self._colors["text"]))
        painter.setFont(tile_font)
        tile_metrics = QFontMetrics(tile_font)
        small_metrics = QFontMetrics(small_font)
        symbol = str(row.get("symbol") or "")
        change = row.get("change_pct")
        pct_text = self._format_pct(change, signed=True) if isinstance(change, (int, float)) else "--"
        interval_label = str(row.get("interval_label") or "").strip()
        change_text = f"{interval_label} {pct_text}".strip() if interval_label else pct_text
        name = str(row.get("name") or "").strip()
        text_width = max(1, int(draw_rect.width()) - 8)
        label = tile_metrics.elidedText(symbol, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(draw_rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
        if draw_rect.height() >= 40 and draw_rect.width() >= 46:
            painter.setFont(small_font)
            painter.drawText(
                draw_rect.adjusted(4, 18, -4, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                small_metrics.elidedText(change_text, Qt.TextElideMode.ElideRight, text_width),
            )
        if name and self._zoom_scale >= 1.35 and draw_rect.height() >= 58 and draw_rect.width() >= 90:
            painter.setFont(small_font)
            painter.drawText(
                draw_rect.adjusted(4, 32, -4, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                small_metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_width),
            )

    def _row_at(self, point: Any) -> dict[str, Any] | None:
        try:
            x = float(point.x())
            y = float(point.y())
        except (AttributeError, TypeError, ValueError):
            return None
        for rect, row in reversed(self._tile_rects):
            if rect.contains(x, y):
                return row
        return None

    @staticmethod
    def _event_position(event: Any) -> Any:
        return event.position() if hasattr(event, "position") else event.pos()

    @staticmethod
    def _point_xy(point: Any) -> tuple[float, float]:
        try:
            return float(point.x()), float(point.y())
        except (AttributeError, TypeError, ValueError):
            return 0.0, 0.0

    def _tooltip(self, row: dict[str, Any]) -> str:
        symbol = str(row.get("symbol") or "--")
        name = str(row.get("name") or "").strip()
        sector = str(row.get("sector") or "Unclassified")
        price = row.get("price")
        price_text = f"${float(price):,.2f}" if isinstance(price, (int, float)) else "--"
        change_label = str(row.get("change_label") or "Change")
        return "\n".join([
            f"{symbol} - {name}" if name else symbol,
            f"Sector: {sector}",
            f"Weight: {self._format_weight_pct(row.get('weight'))}",
            f"Price: {price_text}",
            f"{change_label}: {self._format_pct(row.get('change_pct'), signed=True)}",
        ])

    @staticmethod
    def _positive_weight(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number) or number <= 0:
            return 0.0
        return number

    @staticmethod
    def _format_pct(value: Any, *, signed: bool = False) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        sign = "+" if signed and number >= 0 else ""
        return f"{sign}{number:.2f}%"

    @staticmethod
    def _format_weight_pct(value: Any) -> str:
        try:
            number = float(value) * 100.0
        except (TypeError, ValueError):
            return "--"
        return f"{number:.2f}%"

    def _heat_color(self, change_pct: Any, row: Any = None) -> Any:
        from PyQt6.QtGui import QColor

        neutral = QColor(self._colors["neutral"])
        if isinstance(row, dict) and row.get("neutral_heat"):
            return neutral
        try:
            change = float(change_pct)
        except (TypeError, ValueError):
            return neutral
        if not math.isfinite(change):
            return neutral
        target = QColor(self._colors["up"] if change >= 0 else self._colors["down"])
        strength = min(abs(change) / 4.0, 1.0)
        return self._mix_color(neutral, target, 0.35 + 0.65 * strength)

    @staticmethod
    def _mix_color(left: Any, right: Any, amount: float) -> Any:
        from PyQt6.QtGui import QColor

        mix = max(0.0, min(1.0, amount))
        return QColor(
            int(left.red() + (right.red() - left.red()) * mix),
            int(left.green() + (right.green() - left.green()) * mix),
            int(left.blue() + (right.blue() - left.blue()) * mix),
        )

    def _binary_layout(self, items: list[Any], rect: Any, value_fn: Any) -> list[tuple[Any, Any]]:
        from PyQt6.QtCore import QRectF

        positive = [item for item in items if value_fn(item) > 0]
        if not positive:
            return []
        if len(positive) == 1:
            return [(QRectF(rect), positive[0])]
        total = sum(value_fn(item) for item in positive)
        half = total / 2.0
        running = 0.0
        split_index = 1
        best_delta = total
        for index, item in enumerate(positive[:-1], start=1):
            running += value_fn(item)
            delta = abs(half - running)
            if delta < best_delta:
                best_delta = delta
                split_index = index
        left_items = positive[:split_index]
        right_items = positive[split_index:]
        left_total = sum(value_fn(item) for item in left_items)
        if rect.width() >= rect.height():
            left_width = rect.width() * (left_total / total)
            left_rect = QRectF(rect.left(), rect.top(), left_width, rect.height())
            right_rect = QRectF(rect.left() + left_width, rect.top(), rect.width() - left_width, rect.height())
        else:
            top_height = rect.height() * (left_total / total)
            left_rect = QRectF(rect.left(), rect.top(), rect.width(), top_height)
            right_rect = QRectF(rect.left(), rect.top() + top_height, rect.width(), rect.height() - top_height)
        return self._binary_layout(left_items, left_rect, value_fn) + self._binary_layout(right_items, right_rect, value_fn)
