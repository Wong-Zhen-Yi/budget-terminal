from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QMimeData, QPoint, Qt
from PyQt6.QtGui import QColor, QDrag, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..dependencies import pg


STRATEGY_CARD_MIME = "application/x-budget-terminal-strategy-card"


class _StrategyDragHandle(QLabel):
    def __init__(self, card_id: str, parent: QWidget | None = None) -> None:
        super().__init__("::", parent)
        self.card_id = card_id
        self._press_pos = QPoint()
        self.setToolTip("Drag to reorder this card")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(24)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(STRATEGY_CARD_MIME, self.card_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class StrategyCardWidget(QFrame):
    """One compact strategy summary card with a filled performance plot."""

    def __init__(
        self,
        model: dict[str, Any],
        *,
        interval_key: str,
        on_interval: Callable[[str, str], None],
        on_action: Callable[[str], None],
        on_remove: Callable[[str], None] | None,
        on_hide: Callable[[str], None] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = dict(model)
        self.card_id = str(model.get("id", ""))
        self._line_color = "#4da3ff"
        self._positive_color = "#2ecc71"
        self._negative_color = "#ff5f56"
        self.setObjectName("strategyCard")
        self.setProperty("bt_role", "panel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(250)
        self.setMinimumHeight(330)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        self.title_label = QLabel(str(model.get("name", "Strategy")))
        self.title_label.setProperty("bt_role", "section_title")
        self.title_label.setWordWrap(False)
        header.addWidget(self.title_label, 1)
        self.drag_handle = _StrategyDragHandle(self.card_id, self)
        header.addWidget(self.drag_handle)
        layout.addLayout(header)

        self.meta_label = QLabel(str(model.get("meta", "Equal weight")))
        self.meta_label.setProperty("bt_role", "muted")
        self.meta_label.setWordWrap(False)
        layout.addWidget(self.meta_label)
        symbols = list(model.get("symbols", []))
        configured_weights = model.get("weights", {}) if isinstance(model.get("weights"), dict) else {}
        preview_parts = []
        for symbol in symbols[:6]:
            weight = configured_weights.get(symbol)
            preview_parts.append(f"{symbol} {float(weight):.0f}%" if isinstance(weight, (int, float)) else symbol)
        preview = ", ".join(preview_parts)
        if len(symbols) > 6:
            preview += f" +{len(symbols) - 6}"
        self.symbols_label = QLabel(preview or "No holdings")
        self.symbols_label.setProperty("bt_role", "muted")
        self.symbols_label.setToolTip(", ".join(symbols))
        layout.addWidget(self.symbols_label)

        summary = QHBoxLayout()
        self.return_label = QLabel("Performance --")
        self.return_label.setProperty("bt_role", "section_title")
        self.source_label = QLabel("Loading...")
        self.source_label.setProperty("bt_role", "muted")
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.return_label)
        summary.addStretch()
        summary.addWidget(self.source_label)
        layout.addLayout(summary)

        self.plot = pg.PlotWidget()
        self.plot.setFixedHeight(130)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.getPlotItem().hideButtons()
        layout.addWidget(self.plot)

        intervals = QHBoxLayout()
        intervals.setSpacing(5)
        self.interval_buttons: dict[str, QPushButton] = {}
        for key, label in (("1d", "1 Day"), ("30d", "30D"), ("1y", "1Y")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(27)
            button.clicked.connect(lambda _checked=False, selected=key: on_interval(self.card_id, selected))
            self.interval_buttons[key] = button
            intervals.addWidget(button)
        layout.addLayout(intervals)

        actions = QHBoxLayout()
        self.action_button = QPushButton(str(model.get("action_label", "Open Basket")))
        self.action_button.setProperty("bt_variant", "accent")
        self.action_button.clicked.connect(lambda: on_action(self.card_id))
        actions.addWidget(self.action_button, 1)
        if on_hide is not None:
            hide_button = QPushButton("Hide")
            hide_button.clicked.connect(lambda: on_hide(self.card_id))
            actions.addWidget(hide_button)
        if on_remove is not None:
            remove_button = QPushButton("Remove")
            remove_button.setProperty("bt_variant", "danger")
            remove_button.clicked.connect(lambda: on_remove(self.card_id))
            actions.addWidget(remove_button)
        layout.addLayout(actions)
        self.set_active_interval(interval_key)
        self.set_loading()

    def set_active_interval(self, interval_key: str) -> None:
        for key, button in self.interval_buttons.items():
            button.setChecked(key == interval_key)

    def set_loading(self) -> None:
        self.return_label.setText("Performance --")
        self.source_label.setText("Loading...")

    def set_error(self, message: Any) -> None:
        self.plot.clear()
        self.return_label.setText("Performance unavailable")
        self.return_label.setStyleSheet(f"color: {self._negative_color};")
        self.source_label.setText("No data")
        self.source_label.setToolTip(str(message or "Performance data unavailable."))

    def set_performance(self, payload: dict[str, Any]) -> None:
        values = [float(value) for value in payload.get("values", [])]
        if len(values) < 2:
            self.set_error("Not enough data points were returned.")
            return
        return_pct = float(payload.get("return_pct", values[-1]) or 0.0)
        color = self._positive_color if return_pct >= 0.0 else self._negative_color
        self.plot.clear()
        self.plot.plot(
            list(range(len(values))),
            values,
            pen=pg.mkPen(color, width=2),
            fillLevel=0.0,
            brush=pg.mkBrush(QColor(color).red(), QColor(color).green(), QColor(color).blue(), 55),
        )
        low = min(values)
        high = max(values)
        padding = max((high - low) * 0.12, 0.15)
        self.plot.setYRange(low - padding, high + padding, padding=0.0)
        sign = "+" if return_pct > 0.0 else ""
        self.return_label.setText(f"Performance {sign}{return_pct:.2f}%")
        self.return_label.setStyleSheet(f"color: {color};")
        missing = list(payload.get("missing_symbols", []))
        self.source_label.setText("Partial" if missing else str(payload.get("source", "Market data")))
        weighting_label = str(payload.get("weighting_label", "") or "")
        meta_prefix = str(self.model.get("meta_prefix", "") or "")
        if meta_prefix and weighting_label:
            self.meta_label.setText(f"{meta_prefix} | {weighting_label}")
        tooltip_parts = [f"Weighting: {weighting_label}" if weighting_label else ""]
        if missing:
            tooltip_parts.append(f"Missing: {', '.join(missing)}")
        self.source_label.setToolTip(" | ".join(part for part in tooltip_parts if part))

    def set_colors(self, *, background: str, border: str, muted: str, positive: str, negative: str) -> None:
        self._positive_color = positive
        self._negative_color = negative
        self.plot.setBackground(background)
        self.setStyleSheet(
            f"QFrame#strategyCard {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}"
        )
        self.meta_label.setStyleSheet(f"color: {muted}; border: none;")
        self.symbols_label.setStyleSheet(f"color: {muted}; border: none;")
        self.source_label.setStyleSheet(f"color: {muted}; border: none;")


class StrategyGridWidget(QWidget):
    """Fixed four-column drag target for strategy cards."""

    COLUMN_COUNT = 4

    def __init__(self, on_reorder: Callable[[str, int], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_reorder = on_reorder
        self.cards: list[StrategyCardWidget] = []
        self.setAcceptDrops(True)
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setHorizontalSpacing(10)
        self.layout.setVerticalSpacing(10)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for column in range(self.COLUMN_COUNT):
            self.layout.setColumnStretch(column, 1)
        self.setMinimumWidth(self.COLUMN_COUNT * 250 + (self.COLUMN_COUNT - 1) * 10)

    def set_cards(self, cards: list[StrategyCardWidget]) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.cards = list(cards)
        for index, card in enumerate(self.cards):
            self.layout.addWidget(card, index // self.COLUMN_COUNT, index % self.COLUMN_COUNT)
            card.show()
        self.layout.activate()
        self.updateGeometry()

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(STRATEGY_CARD_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(STRATEGY_CARD_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        if not event.mimeData().hasFormat(STRATEGY_CARD_MIME):
            return
        card_id = bytes(event.mimeData().data(STRATEGY_CARD_MIME)).decode("utf-8", errors="ignore")
        position = event.position().toPoint()
        target_index = len(self.cards) - 1
        for index, card in enumerate(self.cards):
            center = card.geometry().center()
            if position.y() < center.y() or (position.y() <= card.geometry().bottom() and position.x() < center.x()):
                target_index = index
                break
        self._on_reorder(card_id, max(target_index, 0))
        event.acceptProposedAction()
