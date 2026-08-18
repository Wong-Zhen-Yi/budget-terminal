from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QLineF
from PyQt6.QtGui import QImage

from budget_terminal_app.dependencies import QApplication
from budget_terminal_app.widgets.pie_chart import PieChartWidget


_QT_APP = None


REFERENCE_WEIGHTS = {
    "NFLX": 15.4,
    "ARM": 14.6,
    "AAPL": 9.9,
    "PANW": 9.6,
    "NET": 7.4,
    "ORCL": 6.1,
    "HIMS": 5.9,
    "VST": 5.4,
    "PLTR": 4.3,
    "ZS": 4.1,
    "MSTR": 3.7,
    "HOOD": 3.6,
    "GRAB": 3.6,
    "RIVN": 3.3,
    "SE": 3.0,
}

SCREENSHOT_WEIGHTS = {
    "META": 10.0,
    "IAU": 9.6,
    "NOC": 9.0,
    "CASH": 8.2,
    "NVDA": 7.3,
    "ISRG": 7.0,
    "PLTR": 6.7,
    "MSFT": 6.6,
    "MCD": 4.8,
    "CEG": 4.7,
    "AMZN": 4.2,
    "LOW": 3.8,
    "RTX": 3.2,
    "TMUS": 3.1,
    "SOFI": 3.1,
    "EQT": 2.6,
    "OTIS": 2.5,
    "T": 1.9,
    "DVN": 1.5,
}


def _qt_app() -> QApplication:
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _segment_intersects_rect(start, end, rect) -> bool:
    if rect.contains(start) or rect.contains(end):
        return True
    edges = (
        QLineF(rect.topLeft(), rect.topRight()),
        QLineF(rect.topRight(), rect.bottomRight()),
        QLineF(rect.bottomRight(), rect.bottomLeft()),
        QLineF(rect.bottomLeft(), rect.topLeft()),
    )
    segment = QLineF(start, end)
    return any(segment.intersects(edge)[0] == QLineF.IntersectionType.BoundedIntersection for edge in edges)


def _assert_no_callout_collisions(layout) -> None:
    items = layout["items"]
    for side in ("left", "right"):
        side_items = sorted(
            (item for item in items if item["side"] == side),
            key=lambda item: item["label_rect"].top(),
        )
        for earlier, later in zip(side_items, side_items[1:]):
            assert not earlier["label_rect"].intersects(later["label_rect"])
            separation = later["label_rect"].top() - earlier["label_rect"].bottom()
            assert separation >= 8.0 - 0.001

    for item in items:
        segments = (
            (item["anchor"], item["elbow"]),
            (item["elbow"], item["line_end"]),
        )
        for other in items:
            if other is item:
                continue
            assert not any(
                _segment_intersects_rect(start, end, other["label_rect"])
                for start, end in segments
            )


def test_callout_layout_keeps_every_slice() -> None:
    _qt_app()
    widget = PieChartWidget()
    widget.set_donut(True, hole_ratio=0.50)
    widget.set_callout_labels(True)
    widget.set_data(REFERENCE_WEIGHTS)

    layout = widget._build_callout_layout(900, 560)
    items = layout["items"]
    assert len(items) == len(REFERENCE_WEIGHTS)
    assert {item["label"] for item in items} == set(REFERENCE_WEIGHTS)
    assert {item["side"] for item in items} == {"left", "right"}
    assert widget._callout_labels_enabled is True
    assert widget._donut_enabled is True
    assert abs(widget._donut_hole_ratio - 0.50) < 0.001

    total = sum(REFERENCE_WEIGHTS.values())
    for item in items:
        expected = REFERENCE_WEIGHTS[item["label"]] / total * 100.0
        assert abs(item["percentage"] - expected) < 0.0001
        assert layout["top"] <= item["target_y"] <= layout["bottom"]
        if item["side"] == "left":
            assert item["line_end"].x() < item["anchor"].x()
            assert abs(item["line_end"].x() - 12.0) < 0.001
        else:
            assert item["line_end"].x() > item["anchor"].x()
            assert abs(item["line_end"].x() - 888.0) < 0.001

    for side in ("left", "right"):
        side_items = sorted(
            (item for item in items if item["side"] == side),
            key=lambda item: item["anchor"].y(),
        )
        target_ys = [item["target_y"] for item in side_items]
        assert target_ys == sorted(target_ys)
        assert all(
            later - earlier >= layout["row_gap"] - 0.001
            for earlier, later in zip(target_ys, target_ys[1:])
        )
    _assert_no_callout_collisions(layout)


def test_screenshot_density_uses_font_aware_spacing() -> None:
    _qt_app()
    widget = PieChartWidget()
    widget.setMinimumHeight(320)
    widget.set_callout_labels(True)
    widget.set_data(SCREENSHOT_WEIGHTS)

    assert widget.minimumHeight() == widget._required_callout_height()
    assert widget.minimumHeight() <= 700
    layout = widget._build_callout_layout(1860, 700)
    assert len(layout["items"]) == 19
    assert layout["row_gap"] == layout["label_block_height"] + 8.0
    _assert_no_callout_collisions(layout)


def test_dense_callouts_expand_height_then_contract() -> None:
    _qt_app()
    widget = PieChartWidget()
    widget.setMinimumHeight(320)
    widget.set_callout_labels(True)
    widget.set_data({f"T{i:02d}": 1.0 for i in range(48)})

    expanded_height = widget.minimumHeight()
    assert expanded_height == widget._required_callout_height()
    assert expanded_height > 320
    widget.resize(900, 240)
    assert widget.height() >= expanded_height
    dense_layout = widget._build_callout_layout(900, expanded_height)
    _assert_no_callout_collisions(dense_layout)

    widget.set_data({"ONLY": 100.0})
    assert widget.minimumHeight() == 320


def test_callout_mode_renders_without_changing_the_default() -> None:
    app = _qt_app()
    default_widget = PieChartWidget()
    assert default_widget._callout_labels_enabled is False

    widget = PieChartWidget()
    widget.resize(900, 560)
    widget.set_donut(True, hole_ratio=0.50)
    widget.set_callout_labels(True)
    widget.set_data(REFERENCE_WEIGHTS)
    widget.show()
    app.processEvents()

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    assert not image.isNull()
    assert image.width() == 900
    assert image.height() == 560
    widget.close()


def main() -> None:
    test_callout_layout_keeps_every_slice()
    test_screenshot_density_uses_font_aware_spacing()
    test_dense_callouts_expand_height_then_contract()
    test_callout_mode_renders_without_changing_the_default()
    print("pie chart callout smoke tests passed")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
