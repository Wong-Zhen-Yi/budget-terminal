from __future__ import annotations

import copy
import uuid
from typing import Any, Callable

from ..dependencies import QColor, pd, pg


DRAWING_TOOLS = (
    'cursor',
    'trend_line',
    'horizontal_line',
    'horizontal_ray',
    'rectangle',
    'text',
    'fib',
)


class NativeChartDrawingController:
    """Manage editable, timestamp-backed drawings on one pyqtgraph price plot."""

    def __init__(
        self,
        plot: Any,
        *,
        dates: Callable[[], list[Any]],
        theme_color: Callable[[str], Any],
        changed: Callable[[list[dict[str, Any]]], None],
        request_text: Callable[[], str | None],
        tool_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.plot = plot
        self._dates = dates
        self._theme_color = theme_color
        self._changed = changed
        self._request_text = request_text
        self._tool_changed = tool_changed
        self.records: list[dict[str, Any]] = []
        self.items: dict[str, dict[str, Any]] = {}
        self.active_tool = 'cursor'
        self.pending_anchor: dict[str, Any] | None = None
        self.selected_id: str | None = None
        self._undo: list[list[dict[str, Any]]] = []
        self._redo: list[list[dict[str, Any]]] = []
        self._change_snapshot: list[dict[str, Any]] | None = None

    @property
    def is_creating(self) -> bool:
        return self.active_tool != 'cursor' and self.pending_anchor is not None

    def set_tool(self, tool: Any) -> None:
        clean = str(tool or 'cursor').strip().lower()
        if clean not in DRAWING_TOOLS:
            clean = 'cursor'
        self.active_tool = clean
        self.pending_anchor = None
        if self._tool_changed is not None:
            self._tool_changed(clean)

    def cancel(self) -> bool:
        had_pending = self.active_tool != 'cursor' or self.pending_anchor is not None
        self.set_tool('cursor')
        return had_pending

    def set_records(self, records: Any) -> None:
        self.records = copy.deepcopy(list(records or []))
        self.selected_id = None
        self.pending_anchor = None
        self._undo.clear()
        self._redo.clear()
        self.render()

    def records_payload(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.records)

    def add_record(self, record: dict[str, Any], *, persist: bool = True) -> None:
        if persist:
            self._push_history()
        self.records.append(copy.deepcopy(record))
        self.selected_id = str(record.get('id') or '') or None
        self.render()
        if persist:
            self._emit_changed()

    def select(self, drawing_id: Any) -> None:
        clean = str(drawing_id or '').strip()
        self.selected_id = clean if any(str(record.get('id')) == clean for record in self.records) else None
        self._refresh_selection_pens()

    def delete_selected(self) -> bool:
        if not self.selected_id:
            return False
        before = len(self.records)
        self._push_history()
        self.records = [record for record in self.records if str(record.get('id')) != self.selected_id]
        if len(self.records) == before:
            self._undo.pop()
            return False
        self.selected_id = None
        self.render()
        self._emit_changed()
        return True

    def clear(self) -> bool:
        if not self.records:
            return False
        self._push_history()
        self.records = []
        self.selected_id = None
        self.render()
        self._emit_changed()
        return True

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.records))
        self.records = self._undo.pop()
        self.selected_id = None
        self.render()
        self._emit_changed()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.records))
        self.records = self._redo.pop()
        self.selected_id = None
        self.render()
        self._emit_changed()
        return True

    def handle_click(self, x_value: Any, price: Any) -> bool:
        """Consume one chart click when a drawing tool is active."""
        if self.active_tool == 'cursor':
            return False
        anchor = self._anchor_from_point(x_value, price)
        if anchor is None:
            return True
        tool = self.active_tool
        if tool == 'text':
            text = self._request_text()
            if not text:
                self.set_tool('cursor')
                return True
            self._create_record(tool, [anchor], text=str(text).strip())
            return True
        if tool in {'horizontal_line', 'horizontal_ray'}:
            self._create_record(tool, [anchor])
            return True
        if self.pending_anchor is None:
            self.pending_anchor = anchor
            return True
        self._create_record(tool, [self.pending_anchor, anchor])
        return True

    def render(self) -> None:
        self._clear_items()
        for record in self.records:
            if self._record_visible(record):
                self._render_record(record)
        self._refresh_selection_pens()

    def apply_theme(self) -> None:
        self.render()

    def _create_record(self, drawing_type: str, anchors: list[dict[str, Any]], *, text: str = '') -> None:
        record = {
            'id': uuid.uuid4().hex,
            'type': drawing_type,
            'anchors': copy.deepcopy(anchors),
            'text': text,
            'style': {'width': 1.5},
        }
        self._push_history()
        self.records.append(record)
        self.selected_id = record['id']
        self.pending_anchor = None
        self.active_tool = 'cursor'
        if self._tool_changed is not None:
            self._tool_changed('cursor')
        self.render()
        self._emit_changed()

    def _push_history(self) -> None:
        self._undo.append(copy.deepcopy(self.records))
        self._undo = self._undo[-50:]
        self._redo.clear()

    def _begin_item_change(self, *_: Any) -> None:
        if self._change_snapshot is None:
            self._change_snapshot = copy.deepcopy(self.records)

    def _finish_item_change(self, drawing_id: str, *_: Any) -> None:
        wrapper = self.items.get(drawing_id)
        record = self._record(drawing_id)
        if wrapper is None or record is None:
            self._change_snapshot = None
            return
        self._update_record_from_item(record, wrapper)
        if self._change_snapshot is not None and self._change_snapshot != self.records:
            self._undo.append(self._change_snapshot)
            self._undo = self._undo[-50:]
            self._redo.clear()
            self._emit_changed()
        self._change_snapshot = None
        self.render()

    def _emit_changed(self) -> None:
        self._changed(self.records_payload())

    def _record(self, drawing_id: str) -> dict[str, Any] | None:
        return next((record for record in self.records if str(record.get('id')) == drawing_id), None)

    def _clear_items(self) -> None:
        for wrapper in self.items.values():
            for item in [wrapper.get('primary'), *list(wrapper.get('extras', []))]:
                if item is not None:
                    try:
                        self.plot.removeItem(item)
                    except Exception:
                        pass
        self.items = {}

    def _render_record(self, record: dict[str, Any]) -> None:
        drawing_id = str(record.get('id') or '')
        drawing_type = str(record.get('type') or '')
        anchors = record.get('anchors', [])
        points = [self._point_from_anchor(anchor) for anchor in anchors]
        if not drawing_id or any(point is None for point in points):
            return
        points = [point for point in points if point is not None]
        pen = self._record_pen(record)
        primary = None
        extras: list[Any] = []
        if drawing_type == 'trend_line' and len(points) >= 2:
            primary = pg.LineSegmentROI(points[:2], pen=pen, movable=True, removable=False)
            self.plot.addItem(primary)
            self._wire_roi(primary, drawing_id)
        elif drawing_type == 'rectangle' and len(points) >= 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            primary = pg.RectROI(
                [min(x1, x2), min(y1, y2)],
                [max(abs(x2 - x1), 0.5), max(abs(y2 - y1), 0.01)],
                pen=pen,
                movable=True,
                rotatable=False,
                resizable=True,
            )
            self.plot.addItem(primary)
            self._wire_roi(primary, drawing_id)
        elif drawing_type == 'horizontal_line':
            primary = pg.InfiniteLine(pos=points[0][1], angle=0, pen=pen, movable=True)
            self.plot.addItem(primary)
            self._wire_infinite_line(primary, drawing_id)
        elif drawing_type == 'horizontal_ray':
            x, y = points[0]
            x_end = max(float(len(self._dates()) - 1), x + 1.0)
            line = self.plot.plot([x, x_end], [y, y], pen=pen, antialias=True)
            primary = pg.TargetItem(pos=(x, y), size=10, symbol='o', pen=pen, brush=self._record_color(record), movable=True)
            self.plot.addItem(primary)
            extras.append(line)
            self._wire_target(primary, drawing_id)
            primary.sigPositionChanged.connect(lambda *_args, did=drawing_id: self._update_target_extras(did))
        elif drawing_type == 'text':
            x, y = points[0]
            primary = pg.TargetItem(
                pos=(x, y),
                size=9,
                symbol='o',
                pen=pen,
                brush=self._record_color(record),
                movable=True,
                label=str(record.get('text') or ''),
                labelOpts={'color': self._record_color(record), 'anchor': (0, 1)},
            )
            self.plot.addItem(primary)
            self._wire_target(primary, drawing_id)
        elif drawing_type == 'fib' and len(points) >= 2:
            primary = pg.LineSegmentROI(points[:2], pen=pen, movable=True, removable=False)
            self.plot.addItem(primary)
            self._wire_roi(primary, drawing_id)
            extras.extend(self._fib_lines(points[0], points[1], pen))
        if primary is not None:
            self.items[drawing_id] = {'primary': primary, 'extras': extras, 'type': drawing_type}

    def _wire_roi(self, item: Any, drawing_id: str) -> None:
        item.sigClicked.connect(lambda *_args, did=drawing_id: self.select(did))
        item.sigRegionChangeStarted.connect(self._begin_item_change)
        item.sigRegionChanged.connect(lambda *_args, did=drawing_id: self._update_roi_extras(did))
        item.sigRegionChangeFinished.connect(lambda *_args, did=drawing_id: self._finish_item_change(did))

    def _wire_infinite_line(self, item: Any, drawing_id: str) -> None:
        item.sigClicked.connect(lambda *_args, did=drawing_id: self.select(did))
        item.sigDragged.connect(self._begin_item_change)
        item.sigPositionChangeFinished.connect(lambda *_args, did=drawing_id: self._finish_item_change(did))

    def _wire_target(self, item: Any, drawing_id: str) -> None:
        item.sigPositionChanged.connect(lambda *_args, did=drawing_id: self.select(did))
        item.sigPositionChanged.connect(self._begin_item_change)
        item.sigPositionChangeFinished.connect(lambda *_args, did=drawing_id: self._finish_item_change(did))

    def _update_target_extras(self, drawing_id: str) -> None:
        wrapper = self.items.get(drawing_id)
        if wrapper is None or not wrapper.get('extras'):
            return
        primary = wrapper.get('primary')
        pos = primary.pos()
        x = float(pos.x())
        y = float(pos.y())
        x_end = max(float(len(self._dates()) - 1), x + 1.0)
        wrapper['extras'][0].setData([x, x_end], [y, y])

    def _update_roi_extras(self, drawing_id: str) -> None:
        wrapper = self.items.get(drawing_id)
        if wrapper is None or wrapper.get('type') != 'fib':
            return
        points = self._roi_points(wrapper.get('primary'))
        if len(points) < 2:
            return
        ratios = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
        x1, y1 = points[0]
        x2, y2 = points[1]
        for line, ratio in zip(wrapper.get('extras', []), ratios):
            y = y1 + (y2 - y1) * ratio
            line.setData([x1, x2], [y, y])

    def _fib_lines(self, start: tuple[float, float], end: tuple[float, float], pen: Any) -> list[Any]:
        ratios = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
        items = []
        for ratio in ratios:
            y = start[1] + (end[1] - start[1]) * ratio
            line = self.plot.plot([start[0], end[0]], [y, y], pen=pen, antialias=True)
            items.append(line)
        return items

    def _update_record_from_item(self, record: dict[str, Any], wrapper: dict[str, Any]) -> None:
        drawing_type = str(record.get('type') or '')
        primary = wrapper.get('primary')
        if drawing_type in {'trend_line', 'fib'}:
            points = self._roi_points(primary)
            if len(points) >= 2:
                record['anchors'] = [self._anchor_from_point(*point) for point in points[:2]]
        elif drawing_type == 'rectangle':
            pos = primary.pos()
            size = primary.size()
            points = [
                (float(pos.x()), float(pos.y())),
                (float(pos.x() + size.x()), float(pos.y() + size.y())),
            ]
            record['anchors'] = [self._anchor_from_point(*point) for point in points]
        elif drawing_type == 'horizontal_line':
            anchor = dict(record.get('anchors', [{}])[0])
            anchor['price'] = float(primary.value())
            record['anchors'] = [anchor]
        elif drawing_type in {'horizontal_ray', 'text'}:
            pos = primary.pos()
            record['anchors'] = [self._anchor_from_point(float(pos.x()), float(pos.y()))]
        record['anchors'] = [anchor for anchor in record.get('anchors', []) if anchor is not None]

    def _roi_points(self, item: Any) -> list[tuple[float, float]]:
        points = []
        try:
            for _handle, scene_pos in item.getSceneHandlePositions():
                mapped = self.plot.getPlotItem().vb.mapSceneToView(scene_pos)
                points.append((float(mapped.x()), float(mapped.y())))
        except Exception:
            pass
        return points

    def _refresh_selection_pens(self) -> None:
        for drawing_id, wrapper in self.items.items():
            record = self._record(drawing_id)
            if record is None:
                continue
            selected = drawing_id == self.selected_id
            pen = self._record_pen(record, selected=selected)
            primary = wrapper.get('primary')
            try:
                primary.setPen(pen)
            except Exception:
                pass
            for extra in wrapper.get('extras', []):
                try:
                    extra.setPen(pen)
                except Exception:
                    pass

    def _record_pen(self, record: dict[str, Any], *, selected: bool = False) -> Any:
        width = float(record.get('style', {}).get('width', 1.5) or 1.5) + (0.8 if selected else 0.0)
        color = self._theme_color('accent') if selected else self._record_color(record)
        return pg.mkPen(color, width=width)

    def _record_color(self, record: dict[str, Any]) -> Any:
        raw = str(record.get('style', {}).get('color') or '').strip()
        if raw and QColor(raw).isValid():
            return raw
        return self._theme_color('warning')

    def _anchor_from_point(self, x_value: Any, price: Any) -> dict[str, Any] | None:
        dates = self._dates()
        if not dates:
            return None
        try:
            index = max(0, min(int(round(float(x_value))), len(dates) - 1))
            clean_price = float(price)
        except (TypeError, ValueError):
            return None
        if not pd.notna(clean_price):
            return None
        timestamp = pd.Timestamp(dates[index])
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return {'time': timestamp.isoformat(), 'price': clean_price}

    def _point_from_anchor(self, anchor: dict[str, Any]) -> tuple[float, float] | None:
        dates = self._dates()
        if not dates:
            return None
        try:
            target = pd.Timestamp(anchor.get('time'))
            if target.tzinfo is not None:
                target = target.tz_localize(None)
            date_index = pd.DatetimeIndex(pd.to_datetime(dates))
            if date_index.tz is not None:
                date_index = date_index.tz_localize(None)
            deltas = abs(date_index - target)
            index = int(deltas.argmin())
            return float(index), float(anchor.get('price'))
        except Exception:
            return None

    def _record_visible(self, record: dict[str, Any]) -> bool:
        if str(record.get('type') or '') == 'horizontal_line':
            return True
        dates = self._dates()
        if not dates:
            return False
        try:
            date_index = pd.DatetimeIndex(pd.to_datetime(dates))
            if date_index.tz is not None:
                date_index = date_index.tz_localize(None)
            lower = date_index.min()
            upper = date_index.max()
            for anchor in record.get('anchors', []):
                target = pd.Timestamp(anchor.get('time'))
                if target.tzinfo is not None:
                    target = target.tz_localize(None)
                if target < lower or target > upper:
                    return False
            return True
        except Exception:
            return False
