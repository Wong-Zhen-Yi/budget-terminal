from __future__ import annotations

import json
import math
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from budget_terminal_app.paths import resource_path


class GlobalMarketMapWidget(QWidget):
    """Flat global map with market-index labels placed by lon/lat."""

    _GEOMETRY_ASSET = ("budget_terminal_app", "assets", "world_countries_50m.json")
    _WORLD_FEATURES: list[dict[str, Any]] = []
    _WORLD_FEATURES_LOADED = False

    _FALLBACK_LAND_POLYGONS = (
        [
            (-168, 72), (-150, 70), (-137, 60), (-128, 51), (-124, 41), (-117, 33), (-107, 24),
            (-96, 18), (-89, 19), (-82, 25), (-78, 33), (-72, 41), (-60, 48), (-52, 57),
            (-61, 64), (-76, 69), (-96, 72), (-124, 73), (-150, 72),
        ],
        [(-82, 12), (-76, 7), (-78, -4), (-73, -14), (-68, -25), (-71, -41), (-65, -55), (-53, -49), (-44, -24), (-38, -10), (-50, 3), (-63, 10)],
        [(-12, 36), (-9, 44), (-11, 51), (-4, 58), (10, 60), (24, 70), (41, 64), (33, 55), (47, 48), (40, 42), (27, 40), (14, 43), (4, 41)],
        [
            (28, 70), (51, 68), (72, 61), (96, 58), (122, 54), (143, 47), (161, 58),
            (178, 52), (162, 42), (146, 36), (137, 34), (126, 31), (121, 23), (108, 21),
            (101, 8), (82, 7), (72, 19), (55, 24), (43, 32), (35, 45),
        ],
        [(-18, 35), (5, 37), (24, 31), (34, 19), (45, 11), (51, -10), (42, -33), (30, -35), (19, -31), (9, -20), (0, -6), (-10, 6), (-17, 20)],
        [(109, -11), (154, -10), (154, -38), (132, -44), (113, -30)],
        [(-52, 74), (-24, 78), (-18, 66), (-42, 60)],
        [(-8, 58), (1, 59), (2, 51), (-6, 50)],
        [(131, 33), (141, 36), (145, 44), (139, 46), (132, 38)],
        [(166, -34), (178, -38), (174, -46), (168, -43)],
        [(47, -13), (50, -18), (48, -25), (44, -20)],
    )
    _FALLBACK_COUNTRY_LINES = (
        [(-125, 49), (-110, 49), (-95, 49), (-82, 46), (-67, 45)],
        [(-117, 32), (-106, 31), (-97, 26)],
        [(-103, 22), (-98, 18), (-94, 15)],
        [(-73, 6), (-62, 1), (-54, -11), (-57, -30)],
        [(-8, 43), (2, 43), (8, 46), (8, 50)],
        [(2, 51), (7, 49), (10, 47)],
        [(7, 45), (12, 42), (14, 37)],
        [(18, 47), (22, 42), (18, 39)],
        [(69, 36), (77, 32), (88, 27), (96, 29)],
        [(77, 32), (78, 8)],
        [(74, 38), (90, 40), (105, 38), (121, 40)],
        [(96, 29), (106, 23), (122, 23)],
        [(126, 38), (130, 35)],
        [(132, 33), (139, 35), (143, 39), (145, 44)],
        [(103, 1), (105, 1)],
        [(121, -18), (138, -18), (138, -35)],
    )

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._interval_label = "1D"
        self._label_rects: list[tuple[QRectF, dict[str, Any]]] = []
        self._world_features = self._load_world_features()
        self._world_path_cache_key: tuple[int, int, int, int] | None = None
        self._world_path_cache: list[QPainterPath] = []
        self._colors = {
            "background": "#08111d",
            "ocean": "#0d1b2a",
            "grid": "#22364c",
            "land": "#1d3443",
            "land_border": "#335367",
            "text": "#e6edf3",
            "muted": "#9aa4ad",
            "positive": "#27d37f",
            "negative": "#ff5c7a",
            "neutral": "#d6b25e",
            "label_bg": "#101a26",
            "label_border": "#33485d",
            "country_border": "#48657b",
            "pin": "#e6edf3",
        }
        self.setMouseTracking(True)
        self.setMinimumHeight(360)
        self.setMinimumWidth(720)

    @classmethod
    def _load_world_features(cls) -> list[dict[str, Any]]:
        if cls._WORLD_FEATURES_LOADED:
            return cls._WORLD_FEATURES
        cls._WORLD_FEATURES_LOADED = True
        try:
            path = resource_path(*cls._GEOMETRY_ASSET)
            payload = json.loads(path.read_text(encoding="utf-8"))
            features = payload.get("features") if isinstance(payload, dict) else None
            cls._WORLD_FEATURES = [feature for feature in list(features or []) if isinstance(feature, dict)]
        except Exception:
            cls._WORLD_FEATURES = []
        return cls._WORLD_FEATURES

    def set_colors(self, colors: dict[str, Any]) -> None:
        for key, value in dict(colors or {}).items():
            if key in self._colors and value:
                self._colors[key] = str(value)
        self.update()

    def set_data(self, rows: Any, interval_label: Any) -> None:
        self._rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
        self._interval_label = str(interval_label or "1D").upper().strip() or "1D"
        self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self._colors["background"]))
        map_rect = self._map_rect()
        painter.fillRect(map_rect, QColor(self._colors["ocean"]))
        self._draw_graticule(painter, map_rect)
        if self._world_features:
            self._draw_world_features(painter, map_rect)
        else:
            self._draw_fallback_land(painter, map_rect)
            self._draw_fallback_country_lines(painter, map_rect)
        self._draw_markers(painter, map_rect)
        painter.end()

    def mouseMoveEvent(self, event: Any) -> None:
        pos = event.position() if hasattr(event, "position") else event.pos()
        for rect, row in reversed(self._label_rects):
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos(), self._tooltip(row), self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: Any) -> None:
        QToolTip.hideText()
        return super().leaveEvent(event)

    def _map_rect(self) -> QRectF:
        margin = 12
        return QRectF(margin, margin, max(1, self.width() - margin * 2), max(1, self.height() - margin * 2))

    def _project(self, lat: Any, lon: Any, map_rect: QRectF) -> QPointF:
        try:
            lat_value = max(min(float(lat), 90.0), -90.0)
            lon_value = max(min(float(lon), 180.0), -180.0)
        except (TypeError, ValueError):
            lat_value = 0.0
            lon_value = 0.0
        x = map_rect.left() + (lon_value + 180.0) / 360.0 * map_rect.width()
        y = map_rect.top() + (90.0 - lat_value) / 180.0 * map_rect.height()
        return QPointF(x, y)

    def _draw_graticule(self, painter: QPainter, map_rect: QRectF) -> None:
        painter.setPen(QPen(QColor(self._colors["grid"]), 1))
        for lon in range(-150, 181, 30):
            p1 = self._project(-85, lon, map_rect)
            p2 = self._project(85, lon, map_rect)
            painter.drawLine(p1, p2)
        for lat in range(-60, 91, 30):
            p1 = self._project(lat, -180, map_rect)
            p2 = self._project(lat, 180, map_rect)
            painter.drawLine(p1, p2)
        painter.setPen(QPen(QColor(self._colors["land_border"]), 1))
        painter.drawRect(map_rect)

    def _draw_world_features(self, painter: QPainter, map_rect: QRectF) -> None:
        painter.setBrush(QColor(self._colors["land"]))
        border = QColor(self._colors["country_border"])
        border.setAlpha(135)
        painter.setPen(QPen(border, 1))
        for path in self._world_paths(map_rect):
            painter.drawPath(path)

    def _world_paths(self, map_rect: QRectF) -> list[QPainterPath]:
        cache_key = (round(map_rect.left()), round(map_rect.top()), round(map_rect.width()), round(map_rect.height()))
        if self._world_path_cache_key == cache_key:
            return self._world_path_cache
        paths: list[QPainterPath] = []
        for feature in self._world_features:
            for polygon in list(feature.get("polygons") or []):
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for ring in list(polygon or []):
                    points = list(ring or [])
                    if len(points) < 3:
                        continue
                    for index, coord in enumerate(points):
                        if not isinstance(coord, list | tuple) or len(coord) < 2:
                            continue
                        point = self._project(coord[1], coord[0], map_rect)
                        if index == 0:
                            path.moveTo(point)
                        else:
                            path.lineTo(point)
                    path.closeSubpath()
                if not path.isEmpty():
                    paths.append(path)
        self._world_path_cache_key = cache_key
        self._world_path_cache = paths
        return paths

    def _draw_fallback_land(self, painter: QPainter, map_rect: QRectF) -> None:
        painter.setBrush(QColor(self._colors["land"]))
        painter.setPen(QPen(QColor(self._colors["land_border"]), 1))
        for polygon in self._FALLBACK_LAND_POLYGONS:
            path = QPainterPath()
            for index, (lon, lat) in enumerate(polygon):
                point = self._project(lat, lon, map_rect)
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            path.closeSubpath()
            painter.drawPath(path)

    def _draw_fallback_country_lines(self, painter: QPainter, map_rect: QRectF) -> None:
        line_color = QColor(self._colors["country_border"])
        line_color.setAlpha(145)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line_color, 1))
        for line in self._FALLBACK_COUNTRY_LINES:
            self._draw_polyline(painter, map_rect, line)

    def _draw_polyline(self, painter: QPainter, map_rect: QRectF, points: Any) -> None:
        path = QPainterPath()
        for index, (lon, lat) in enumerate(points or []):
            point = self._project(lat, lon, map_rect)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.drawPath(path)

    def _draw_markers(self, painter: QPainter, map_rect: QRectF) -> None:
        self._label_rects = []
        layout = self._layout_labels(map_rect)
        for item in layout:
            if item.get("leader_visible", True):
                painter.setPen(QPen(QColor(item["change_color"]), 1))
                painter.drawLine(item["point"], item["leader_end"])
        for item in layout:
            rect = item["rect"]
            country = item["country"]
            label = item["label"]
            pct = item["pct"]
            status_text = item["status_text"]
            status_color = item["status_color"]
            show_status = item["show_status"]
            country_font = item["country_font"]
            title_font = item["title_font"]
            detail_font = item["detail_font"]
            country_metrics = item["country_metrics"]
            title_metrics = item["title_metrics"]
            detail_metrics = item["detail_metrics"]
            change_color = item["change_color"]
            painter.setBrush(QColor(self._colors["label_bg"]))
            painter.setPen(QPen(QColor(change_color), 1))
            painter.drawRoundedRect(rect, 4, 4)
            text_left = rect.left() + 7
            text_width = rect.width() - 14
            text_top = rect.top() + 4
            country_rect = QRectF(text_left, text_top, text_width, country_metrics.height() + 1)
            title_rect = QRectF(text_left, country_rect.bottom() - 1, text_width, title_metrics.height() + 1)
            pct_rect = QRectF(text_left, title_rect.bottom(), text_width, detail_metrics.height() + 1)
            painter.setFont(country_font)
            painter.setPen(QColor(self._colors["text"]))
            painter.drawText(country_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, country_metrics.elidedText(country, Qt.TextElideMode.ElideRight, int(text_width)))
            painter.setFont(title_font)
            painter.setPen(QColor(self._colors["text"]))
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title_metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(text_width)))
            painter.setFont(detail_font)
            if show_status:
                dot_color = QColor(status_color)
                painter.setBrush(dot_color)
                painter.setPen(QPen(dot_color, 1))
                dot_y = pct_rect.top() + max(5.0, detail_metrics.height() / 2.0)
                painter.drawEllipse(QPointF(pct_rect.left() + 4, dot_y), 3.5, 3.5)
                text_rect = QRectF(pct_rect.left() + 13, pct_rect.top(), max(1.0, pct_rect.width() - 13), pct_rect.height())
            else:
                text_rect = pct_rect
            painter.setPen(QColor(change_color))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, detail_metrics.elidedText(status_text, Qt.TextElideMode.ElideRight, int(text_rect.width())))
            self._label_rects.append((rect, item["row"]))
        for item in layout:
            painter.setBrush(QColor(item["change_color"]))
            painter.setPen(QPen(QColor(self._colors["background"]), 2))
            painter.drawEllipse(item["point"], 5, 5)

    def _layout_labels(self, map_rect: QRectF) -> list[dict[str, Any]]:
        base_font = QFont(self.font())
        if str(base_font.family() or "").strip().casefold() in {"", "sans serif"}:
            base_font.setFamily("Segoe UI")
        country_font = QFont(base_font)
        country_font.setPointSize(max(8, country_font.pointSize()))
        country_font.setBold(True)
        title_font = QFont(base_font)
        title_font.setPointSize(max(7, title_font.pointSize() - 1))
        title_font.setBold(False)
        detail_font = QFont(base_font)
        detail_font.setPointSize(max(7, detail_font.pointSize() - 1))
        country_metrics = QFontMetrics(country_font)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        occupied: list[QRectF] = []
        leader_segments: list[tuple[QPointF, QPointF]] = []
        layout: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for row_index, row in enumerate(self._rows):
            point = self._project(row.get("lat"), row.get("lon"), map_rect)
            items.append({"row": row, "point": point, "index": row_index})
        protected_pins = [self._pin_hit_rect(item["point"]) for item in items]
        for item in items:
            point = item["point"]
            item["crowding"] = sum(
                max(0.0, 1.0 - math.hypot(point.x() - other["point"].x(), point.y() - other["point"].y()) / 140.0)
                for other in items
                if other is not item
            )
        for item in sorted(items, key=lambda value: (-float(value.get("crowding", 0.0)), int(value.get("index", 0)))):
            row = item["row"]
            point = item["point"]
            change_color = self._row_color(row)
            country = str(row.get("country") or "--")
            label = str(row.get("short_name") or row.get("index") or row.get("symbol") or "--")
            pct = self._pct_text(row)
            status_text = self._status_line_text(row, pct)
            show_status = self._has_market_status(row)
            line_height = country_metrics.height() + title_metrics.height() + detail_metrics.height() + 12
            text_width = max(
                country_metrics.horizontalAdvance(country),
                title_metrics.horizontalAdvance(label),
                detail_metrics.horizontalAdvance(status_text) + (13 if show_status else 0),
            )
            width = min(max(text_width + 16, 70), 150)
            rect = self._place_label(point, width, line_height, row, map_rect, occupied, leader_segments, protected_pins)
            leader_end = self._leader_endpoint(point, rect)
            leader_visible = not self._leader_conflicts(rect, point, occupied, leader_segments, protected_pins)
            occupied.append(rect)
            if leader_visible:
                leader_segments.append((point, leader_end))
            layout.append(
                {
                    "row": row,
                    "point": point,
                    "rect": rect,
                    "leader_end": leader_end,
                    "leader_segment": (point, leader_end),
                    "leader_visible": leader_visible,
                    "country": country,
                    "label": label,
                    "pct": pct,
                    "status_text": status_text,
                    "status_color": self._market_status_color(row),
                    "show_status": show_status,
                    "change_color": change_color,
                    "country_font": country_font,
                    "title_font": title_font,
                    "detail_font": detail_font,
                    "country_metrics": country_metrics,
                    "title_metrics": title_metrics,
                    "detail_metrics": detail_metrics,
                }
            )
        return layout

    def _place_label(
        self,
        point: QPointF,
        width: float,
        height: float,
        row: dict[str, Any],
        map_rect: QRectF,
        occupied: list[QRectF],
        leader_segments: list[tuple[QPointF, QPointF]],
        protected_pins: list[QRectF],
    ) -> QRectF:
        candidates = self._label_candidates(point, width, height, row, map_rect)
        for rect in candidates:
            if not self._label_conflicts(rect, point, occupied, leader_segments, protected_pins):
                return rect
        for rect in candidates:
            if not self._label_collides(rect, occupied) and not self._label_covers_pin(rect, point, protected_pins):
                return rect
        for rect in candidates:
            if not self._label_intersects(rect, occupied) and not self._label_covers_pin(rect, point, protected_pins):
                return rect
        fallback = self._find_open_label_rect(point, width, height, map_rect, occupied, leader_segments, protected_pins, require_leader=True)
        if fallback is not None:
            return fallback
        fallback = self._find_open_label_rect(point, width, height, map_rect, occupied, leader_segments, protected_pins, require_leader=False)
        if fallback is not None:
            return fallback
        fallback = self._find_open_label_rect(point, width, height, map_rect, occupied, leader_segments, protected_pins, require_leader=False, tight=True)
        if fallback is not None:
            return fallback
        return self._stacked_label_rect(width, height, map_rect, len(occupied))

    def _label_candidates(self, point: QPointF, width: float, height: float, row: dict[str, Any], map_rect: QRectF) -> list[QRectF]:
        preferred_dx = int(row.get("label_dx", 12) or 12)
        preferred_dy = int(row.get("label_dy", -18) or -18)
        offsets: list[tuple[float, float]] = [(preferred_dx, preferred_dy)]
        for shift in (-60, 60, -120, 120, -180, 180):
            offsets.append((preferred_dx, preferred_dy + shift))
        offsets.extend(
            [
                (14, -height - 10),
                (14, 10),
                (14, -height / 2),
                (-width - 14, -height - 10),
                (-width - 14, 10),
                (-width - 14, -height / 2),
                (-width / 2, -height - 14),
                (-width / 2, 14),
                (46, -height - 18),
                (46, 18),
                (-width - 46, -height - 18),
                (-width - 46, 18),
            ]
        )
        for radius in (54, 78, 104, 132, 164, 198, 236, 276):
            for angle in (-165, -135, -105, -75, -45, -15, 15, 45, 75, 105, 135, 165, 180):
                radians = math.radians(angle)
                offsets.append((math.cos(radians) * radius - width / 2, math.sin(radians) * radius - height / 2))
        preferred = self._clamped_rect(point.x() + preferred_dx, point.y() + preferred_dy, width, height, map_rect)
        unique: dict[tuple[int, int], QRectF] = {}
        for dx, dy in offsets:
            rect = self._clamped_rect(point.x() + dx, point.y() + dy, width, height, map_rect)
            if rect.adjusted(-4, -4, 4, 4).contains(point):
                continue
            unique[(round(rect.x()), round(rect.y()))] = rect
        return sorted(unique.values(), key=lambda rect: self._label_score(rect, point, preferred, map_rect))

    def _find_open_label_rect(
        self,
        point: QPointF,
        width: float,
        height: float,
        map_rect: QRectF,
        occupied: list[QRectF],
        leader_segments: list[tuple[QPointF, QPointF]],
        protected_pins: list[QRectF],
        *,
        require_leader: bool,
        tight: bool = False,
    ) -> QRectF | None:
        best: tuple[float, QRectF] | None = None
        left = int(map_rect.left() + 4)
        right = int(map_rect.right() - width - 4)
        top = int(map_rect.top() + 4)
        bottom = int(map_rect.bottom() - height - 4)
        if right < left or bottom < top:
            return self._clamped_rect(map_rect.left() + 4, map_rect.top() + 4, width, height, map_rect)
        for y in range(top, bottom + 1, 5):
            for x in range(left, right + 1, 6):
                rect = QRectF(float(x), float(y), width, height)
                if rect.adjusted(-4, -4, 4, 4).contains(point):
                    continue
                if self._label_intersects(rect, occupied) if tight else self._label_collides(rect, occupied):
                    continue
                if self._label_covers_pin(rect, point, protected_pins):
                    continue
                if self._covers_existing_leader(rect, leader_segments):
                    continue
                if require_leader and self._leader_conflicts(rect, point, occupied, leader_segments, protected_pins):
                    continue
                score = abs(rect.center().x() - point.x()) + abs(rect.center().y() - point.y()) * 1.2
                if rect.left() <= map_rect.left() + 5 or rect.right() >= map_rect.right() - 5:
                    score += 24.0
                if rect.top() <= map_rect.top() + 5 or rect.bottom() >= map_rect.bottom() - 5:
                    score += 24.0
                if best is None or score < best[0]:
                    best = (score, rect)
        return best[1] if best is not None else None

    def _stacked_label_rect(self, width: float, height: float, map_rect: QRectF, index: int) -> QRectF:
        gap = 6
        columns = max(1, int((map_rect.width() - 8) // max(width + gap, 1)))
        column = index % columns
        row = index // columns
        x = map_rect.left() + 4 + column * (width + gap)
        y = map_rect.top() + 4 + row * (height + gap)
        return self._clamped_rect(x, y, width, height, map_rect)

    def _clamped_rect(self, x: float, y: float, width: float, height: float, map_rect: QRectF) -> QRectF:
        label_x = min(max(float(x), map_rect.left() + 4), map_rect.right() - width - 4)
        label_y = min(max(float(y), map_rect.top() + 4), map_rect.bottom() - height - 4)
        return QRectF(label_x, label_y, width, height)

    def _label_collides(self, rect: QRectF, occupied: list[QRectF]) -> bool:
        padded = rect.adjusted(-6, -6, 6, 6)
        return any(padded.intersects(other.adjusted(-6, -6, 6, 6)) for other in occupied)

    def _label_intersects(self, rect: QRectF, occupied: list[QRectF]) -> bool:
        return any(rect.intersects(other) for other in occupied)

    def _label_conflicts(
        self,
        rect: QRectF,
        point: QPointF,
        occupied: list[QRectF],
        leader_segments: list[tuple[QPointF, QPointF]],
        protected_pins: list[QRectF],
    ) -> bool:
        if self._label_collides(rect, occupied):
            return True
        if self._label_covers_pin(rect, point, protected_pins):
            return True
        return self._leader_conflicts(rect, point, occupied, leader_segments, protected_pins)

    def _label_covers_pin(self, rect: QRectF, point: QPointF, protected_pins: list[QRectF]) -> bool:
        label_rect = rect.adjusted(-1, -1, 1, 1)
        own_pin = self._pin_hit_rect(point)
        for pin_rect in protected_pins:
            if self._rects_nearly_equal(pin_rect, own_pin):
                continue
            if label_rect.intersects(pin_rect):
                return True
        return False

    def _leader_conflicts(
        self,
        rect: QRectF,
        point: QPointF,
        occupied: list[QRectF],
        leader_segments: list[tuple[QPointF, QPointF]],
        protected_pins: list[QRectF] | None = None,
    ) -> bool:
        leader = (point, self._leader_endpoint(point, rect))
        for other in occupied:
            if self._segment_intersects_rect(leader, other.adjusted(-2, -2, 2, 2)):
                return True
        padded_rect = rect.adjusted(-2, -2, 2, 2)
        for other_leader in leader_segments:
            if self._segment_intersects_rect(other_leader, padded_rect):
                return True
            if self._segments_intersect(leader[0], leader[1], other_leader[0], other_leader[1]):
                return True
        return False

    def _covers_existing_leader(self, rect: QRectF, leader_segments: list[tuple[QPointF, QPointF]]) -> bool:
        padded_rect = rect.adjusted(-2, -2, 2, 2)
        return any(self._segment_intersects_rect(leader, padded_rect) for leader in leader_segments)

    def _pin_hit_rect(self, point: QPointF) -> QRectF:
        radius = 8.0
        return QRectF(point.x() - radius, point.y() - radius, radius * 2.0, radius * 2.0)

    def _rects_nearly_equal(self, first: QRectF, second: QRectF) -> bool:
        return (
            abs(first.x() - second.x()) <= 0.001
            and abs(first.y() - second.y()) <= 0.001
            and abs(first.width() - second.width()) <= 0.001
            and abs(first.height() - second.height()) <= 0.001
        )

    def _leader_endpoint(self, point: QPointF, rect: QRectF) -> QPointF:
        x = min(max(point.x(), rect.left()), rect.right())
        y = min(max(point.y(), rect.top()), rect.bottom())
        return QPointF(x, y)

    def _segment_intersects_rect(self, segment: tuple[QPointF, QPointF], rect: QRectF) -> bool:
        start, end = segment
        if rect.contains(start) or rect.contains(end):
            return True
        top_left = QPointF(rect.left(), rect.top())
        top_right = QPointF(rect.right(), rect.top())
        bottom_right = QPointF(rect.right(), rect.bottom())
        bottom_left = QPointF(rect.left(), rect.bottom())
        edges = (
            (top_left, top_right),
            (top_right, bottom_right),
            (bottom_right, bottom_left),
            (bottom_left, top_left),
        )
        return any(self._segments_intersect(start, end, edge_start, edge_end) for edge_start, edge_end in edges)

    def _segments_intersect(self, first_start: QPointF, first_end: QPointF, second_start: QPointF, second_end: QPointF) -> bool:
        epsilon = 0.0001
        first_orientation = self._orientation(first_start, first_end, second_start)
        second_orientation = self._orientation(first_start, first_end, second_end)
        third_orientation = self._orientation(second_start, second_end, first_start)
        fourth_orientation = self._orientation(second_start, second_end, first_end)
        if first_orientation * second_orientation < -epsilon and third_orientation * fourth_orientation < -epsilon:
            return True
        if abs(first_orientation) <= epsilon and self._point_on_segment(second_start, first_start, first_end):
            return True
        if abs(second_orientation) <= epsilon and self._point_on_segment(second_end, first_start, first_end):
            return True
        if abs(third_orientation) <= epsilon and self._point_on_segment(first_start, second_start, second_end):
            return True
        if abs(fourth_orientation) <= epsilon and self._point_on_segment(first_end, second_start, second_end):
            return True
        return False

    def _orientation(self, first: QPointF, second: QPointF, third: QPointF) -> float:
        return (second.x() - first.x()) * (third.y() - first.y()) - (second.y() - first.y()) * (third.x() - first.x())

    def _point_on_segment(self, point: QPointF, segment_start: QPointF, segment_end: QPointF) -> bool:
        return (
            min(segment_start.x(), segment_end.x()) - 0.0001 <= point.x() <= max(segment_start.x(), segment_end.x()) + 0.0001
            and min(segment_start.y(), segment_end.y()) - 0.0001 <= point.y() <= max(segment_start.y(), segment_end.y()) + 0.0001
        )

    def _label_score(self, rect: QRectF, point: QPointF, preferred: QRectF, map_rect: QRectF) -> float:
        preferred_distance = abs(rect.x() - preferred.x()) + abs(rect.y() - preferred.y())
        leader = self._leader_endpoint(point, rect)
        leader_distance = math.hypot(leader.x() - point.x(), leader.y() - point.y())
        edge_penalty = 0.0
        if rect.left() <= map_rect.left() + 5 or rect.right() >= map_rect.right() - 5:
            edge_penalty += 24.0
        if rect.top() <= map_rect.top() + 5 or rect.bottom() >= map_rect.bottom() - 5:
            edge_penalty += 24.0
        return preferred_distance * 1.55 + leader_distance * 0.6 + edge_penalty

    def _interval_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        intervals = row.get("intervals", {})
        payload = intervals.get(self._interval_label) if isinstance(intervals, dict) else None
        return payload if isinstance(payload, dict) else {}

    def _row_color(self, row: dict[str, Any]) -> str:
        payload = self._interval_payload(row)
        if not payload.get("available"):
            return self._colors["muted"]
        try:
            value = float(payload.get("change_pct"))
        except (TypeError, ValueError):
            return self._colors["muted"]
        if value > 0.05:
            return self._colors["positive"]
        if value < -0.05:
            return self._colors["negative"]
        return self._colors["neutral"]

    def _pct_text(self, row: dict[str, Any]) -> str:
        payload = self._interval_payload(row)
        if not payload.get("available"):
            return f"{self._interval_label} --"
        try:
            value = float(payload.get("change_pct"))
        except (TypeError, ValueError):
            return f"{self._interval_label} --"
        sign = "+" if value > 0 else ""
        return f"{self._interval_label} {sign}{value:.2f}%"

    def _market_status_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("market_status", {})
        return payload if isinstance(payload, dict) else {}

    def _has_market_status(self, row: dict[str, Any]) -> bool:
        payload = self._market_status_payload(row)
        return bool(str(payload.get("market") or "").strip())

    def _status_line_text(self, row: dict[str, Any], pct_text: str) -> str:
        payload = self._market_status_payload(row)
        market = str(payload.get("market") or "").strip()
        if not market:
            return pct_text
        return f"{market} | {pct_text}"

    def _market_status_color(self, row: dict[str, Any]) -> str:
        state = str(self._market_status_payload(row).get("state") or "unknown").lower().strip()
        if state == "open":
            return self._colors["positive"]
        if state == "closed":
            return self._colors["negative"]
        return self._colors["muted"]

    def _tooltip(self, row: dict[str, Any]) -> str:
        payload = self._interval_payload(row)
        market_status = self._market_status_payload(row)
        parts = [
            f"{row.get('index', row.get('symbol', '--'))}",
            f"{row.get('country', '--')} | {row.get('symbol', '--')}",
            self._pct_text(row),
        ]
        if market_status:
            parts.append(str(market_status.get("session") or "Timing unavailable"))
            parts.append(f"Clock timezone: {market_status.get('clock_timezone') or '--'}")
            parts.append(f"Exchange timezone: {market_status.get('exchange_timezone') or '--'}")
        if payload.get("available"):
            parts.append(f"{payload.get('start_date', '--')} -> {payload.get('end_date', '--')}")
        return "\n".join(str(part) for part in parts)
