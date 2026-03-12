from __future__ import annotations
from typing import Any
from ..dependencies import *
from ..persistence import fmt_num

class CandlestickItem(pg.GraphicsObject):

    def __init__(self, data: Any) -> None:
        """Initialize the object."""
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()

    def generatePicture(self) -> None:
        """Handle generatePicture."""
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        p.setPen(Qt.PenStyle.NoPen)
        w = 0.6
        for t, open, close, min, max in self.data:
            if open > close:
                p.setBrush(pg.mkBrush('r'))
            else:
                p.setBrush(pg.mkBrush('g'))
            p.drawLine(pg.QtCore.QPointF(t, min), pg.QtCore.QPointF(t, max))
            p.drawRect(pg.QtCore.QRectF(t - w / 2, open, w, close - open))
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
                d = self.dates[idx]
                if self.date_interval in ('1d', '1wk', '1mo'):
                    strings.append(d.strftime('%m/%d/%y'))
                else:
                    strings.append(d.strftime('%H:%M'))
            else:
                strings.append('')
        return strings

class FmtAxisItem(pg.AxisItem):

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> Any:
        """Handle tickStrings."""
        return [fmt_num(v) for v in values]
