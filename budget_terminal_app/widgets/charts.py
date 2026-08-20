from __future__ import annotations
from typing import Any
from ..dependencies import *
from ..persistence import fmt_num


def _coerce_axis_datetime(value: Any) -> Any:
    """Return a datetime-like value for chart axis labels when possible."""
    if hasattr(value, 'strftime'):
        return value
    try:
        parsed = pd.to_datetime(value, errors='coerce')
        if not pd.isna(parsed) and hasattr(parsed, 'strftime'):
            return parsed
    except Exception:
        pass
    return None

class CandlestickItem(pg.GraphicsObject):

    def __init__(self, data: Any, up_color: Any='#4caf50', down_color: Any='#f44336') -> None:
        """Initialize the object."""
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.up_color = up_color
        self.down_color = down_color
        self.generatePicture()

    def set_colors(self, up_color: Any, down_color: Any) -> None:
        """Update the candlestick palette and repaint."""
        self.up_color = up_color
        self.down_color = down_color
        self.generatePicture()
        self.update()

    def generatePicture(self) -> None:
        """Handle generatePicture."""
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        w = 0.6
        for t, open, close, min, max in self.data:
            color = self.down_color if open > close else self.up_color
            p.setPen(pg.mkPen(color, width=1))
            p.setBrush(pg.mkBrush(color))
            p.drawLine(pg.QtCore.QPointF(t, min), pg.QtCore.QPointF(t, max))
            body_top = open if open < close else close
            body_height = abs(close - open)
            if body_height < 0.000001:
                body_height = 0.000001
            p.drawRect(pg.QtCore.QRectF(t - w / 2, body_top, w, body_height))
        p.end()

    def paint(self, p: Any, *args: Any) -> None:
        """Handle paint."""
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self) -> Any:
        """Handle boundingRect."""
        return pg.QtCore.QRectF(self.picture.boundingRect())

class DateAxisItem(pg.AxisItem):
    """Dynamic X-axis that maps integer index positions to date/time labels.
    Regenerates labels on every zoom/pan so the axis never disappears."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the object."""
        super().__init__(*args, **kwargs)
        self.dates = []
        self.date_interval = '1d'

    def set_dates(self, dates: Any, interval: Any) -> None:
        """Handle set dates."""
        self.dates = dates
        self.date_interval = interval

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> Any:
        """Handle tickStrings."""
        strings = []
        for v in values:
            idx = int(round(v))
            if 0 <= idx < len(self.dates):
                d = _coerce_axis_datetime(self.dates[idx])
                if d is None:
                    strings.append(str(self.dates[idx])[:10])
                    continue
                if self.date_interval in ('1d', '1wk', '1mo'):
                    strings.append(d.strftime('%m/%d/%y'))
                else:
                    strings.append(d.strftime('%H:%M'))
            else:
                strings.append('')
        return strings

class FmtAxisItem(pg.AxisItem):

    # Set per instance (never on the class) to render plain integers instead of magnitude-suffixed
    # numbers. Only the Fundamentals overview uses it, for its rebased-to-100 mode; this axis is
    # shared app-wide, so a class-level assignment would reformat every other page.
    p2_index_mode = False

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> Any:
        """Handle tickStrings."""
        if getattr(self, 'p2_index_mode', False):
            return [f'{float(v):.0f}' for v in values]
        return [fmt_num(v) for v in values]


class PercentAxisItem(pg.AxisItem):

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> Any:
        """Render axis values as percentages."""
        strings = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                strings.append('')
                continue
            sign = '+' if number > 0 else ''
            strings.append(f'{sign}{number:.1f}%')
        return strings


class CompareIntervalLabelsItem(pg.GraphicsObject):
    """Paint many fixed-size compare interval labels as one graphics item."""

    def __init__(self, points: Any=None, color: Any='#ffffff') -> None:
        super().__init__()
        self.points: list[tuple[float, float, str, bool]] = []
        self.color = QColor(color)
        self._bounds = pg.QtCore.QRectF()
        self.set_data(points or [], color=color)

    def set_data(self, points: Any, *, color: Any=None) -> None:
        """Replace the label payload and repaint without adding scene children."""
        normalized = []
        for raw_point in list(points or []):
            try:
                x_value, y_value, text, above = raw_point
                x_value = float(x_value)
                y_value = float(y_value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(x_value) or not math.isfinite(y_value):
                continue
            text_value = str(text or '').strip()
            if not text_value:
                continue
            normalized.append((x_value, y_value, text_value, bool(above)))
        if color is not None:
            self.color = QColor(color)
        self.prepareGeometryChange()
        self.points = normalized
        if not normalized:
            self._bounds = pg.QtCore.QRectF()
        else:
            x_values = [point[0] for point in normalized]
            y_values = [point[1] for point in normalized]
            x_span = max(x_values) - min(x_values)
            y_span = max(y_values) - min(y_values)
            x_padding = max(1.0, x_span * 0.01)
            y_padding = max(10.0, y_span * 0.10)
            self._bounds = pg.QtCore.QRectF(
                min(x_values) - x_padding,
                min(y_values) - y_padding,
                max((max(x_values) - min(x_values)) + (x_padding * 2.0), 1.0),
                max((max(y_values) - min(y_values)) + (y_padding * 2.0), 1.0),
            )
        self.update()

    def paint(self, painter: Any, *_: Any) -> None:
        """Draw labels in device coordinates so zooming does not scale the text."""
        if not self.points:
            return
        transform = painter.worldTransform()
        font = pg.QtGui.QFont(painter.font())
        font.setPointSizeF(18.75)
        metrics = pg.QtGui.QFontMetricsF(font)
        painter.save()
        painter.resetTransform()
        painter.setFont(font)
        painter.setPen(pg.mkPen(self.color))
        for x_value, y_value, text, above in self.points:
            device_point = transform.map(pg.QtCore.QPointF(x_value, y_value))
            text_width = metrics.horizontalAdvance(text)
            text_height = metrics.height()
            text_left = device_point.x() - (text_width / 2.0)
            text_top = device_point.y() - text_height - 3.0 if above else device_point.y() + 3.0
            painter.drawText(
                pg.QtCore.QPointF(text_left, text_top + metrics.ascent()),
                text,
            )
        painter.restore()

    def boundingRect(self) -> Any:
        """Return data bounds used for scene invalidation and viewport culling."""
        return pg.QtCore.QRectF(self._bounds)
