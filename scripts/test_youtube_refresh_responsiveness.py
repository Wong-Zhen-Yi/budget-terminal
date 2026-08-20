"""Smoke-test responsive YouTube result application without network access."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

import budget_terminal_app.mixins.youtube as youtube_module
from budget_terminal_app.mixins.youtube import YouTubeMixin


class _YouTubeProbe(QWidget, YouTubeMixin):
    def __init__(self, *, visible: bool, row_delay: float = 0.0) -> None:
        super().__init__()
        self.page16 = QWidget(self)
        self.current_page_visible = visible
        self.row_delay = row_delay
        self.render_count = 0
        self.thumbnail_count = 0
        self.refresh_count = 0
        self.init_page16()
        self._p16_loaded_once = True

    def _is_current_page(self, _page) -> bool:
        return self.current_page_visible

    def set_theme_role(self, widget, role):
        widget.setProperty("bt_role", role)
        return widget

    def set_theme_variant(self, widget, variant):
        widget.setProperty("bt_variant", variant)
        return widget

    def theme_color(self, token):
        return {
            "accent": "#5b9dff",
            "panel_background": "#111a29",
            "panel_border": "#34425a",
            "text_primary": "#edf2f7",
            "text_muted": "#7f8a9a",
        }.get(token, "#b8c0cc")

    def set_status_text(self, label, text, status="muted") -> None:
        label.setText(str(text))
        label.setProperty("bt_status", status)

    def _p16_refresh(self, **_kwargs) -> None:
        self.refresh_count += 1

    def _p16_render_table(self, **kwargs) -> None:
        self.render_count += 1
        super()._p16_render_table(**kwargs)

    def _p16_append_table_row(self, item) -> None:
        if self.row_delay:
            time.sleep(self.row_delay)
        super()._p16_append_table_row(item)

    def _p16_request_thumbnail(self, _item) -> None:
        self.thumbnail_count += 1


def _videos(count: int) -> list[dict]:
    return [
        {
            "ticker": f"T{index:03d}",
            "title": f"Video {index:03d}",
            "channel": "Test Channel",
            "view_count": 10_000 + index,
            "published_text": "2026-07-30",
            "duration_text": "8:30",
            "description_snippet": "Responsiveness probe",
            "url": f"https://www.youtube.com/watch?v=test{index:03d}",
        }
        for index in range(count)
    ]


def _payload(count: int) -> dict:
    return {
        "items": _videos(count),
        "warnings": [],
        "tickers_total": count,
        "from_cache_count": 0,
        "fetched_count": count,
    }


def _wait_until(app: QApplication, predicate, *, timeout: float = 5.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("Timed out waiting for the batched YouTube render")


def test_hidden_result_applies_once_without_refetch(app: QApplication) -> None:
    probe = _YouTubeProbe(visible=False)
    probe._p16_on_data(_payload(80))
    app.processEvents()

    assert probe.render_count == 0
    assert probe.p16_table.rowCount() == 0
    assert probe.thumbnail_count == 0
    assert probe._p16_render_pending

    probe.current_page_visible = True
    probe._p16_on_show()
    first_handle = probe._budget_terminal_batched_render_handles["youtube-table"]
    _wait_until(app, lambda: first_handle.finished)

    assert probe.render_count == 1
    assert probe.p16_table.rowCount() == 80
    assert probe.thumbnail_count == 1
    assert probe.refresh_count == 0
    assert not probe._p16_render_pending

    probe._p16_on_show()
    app.processEvents()
    assert probe.render_count == 1
    assert probe.thumbnail_count == 1
    assert probe.refresh_count == 0
    probe.close()


def test_visible_items_coalesce_and_bulk_render_keeps_heartbeat(app: QApplication) -> None:
    probe = _YouTubeProbe(visible=True, row_delay=0.0005)
    for item in _videos(30):
        probe._p16_on_item_ready(item)
    assert probe.render_count == 0
    _wait_until(app, lambda: probe.p16_table.rowCount() == 30)
    assert probe.render_count == 1
    assert probe.thumbnail_count == 1

    probe.render_count = 0
    probe.thumbnail_count = 0
    beats = [time.perf_counter()]
    heartbeat = QTimer(probe)
    heartbeat.setInterval(1)
    heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
    heartbeat.start()

    probe._p16_on_data(_payload(240))
    handle = probe._budget_terminal_batched_render_handles["youtube-table"]
    _wait_until(app, lambda: handle.finished)
    beats.append(time.perf_counter())
    heartbeat.stop()

    assert handle.completed
    assert handle.batch_count > 1
    assert probe.render_count == 1
    assert probe.p16_table.rowCount() == 240
    assert probe.thumbnail_count == 1
    assert len(beats) > 2
    assert max(later - earlier for earlier, later in zip(beats, beats[1:])) < 0.2
    probe.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    original_load = youtube_module.load_youtube_settings
    youtube_module.load_youtube_settings = lambda: {
        "sort_column": -1,
        "sort_descending": False,
    }
    try:
        test_hidden_result_applies_once_without_refetch(app)
        test_visible_items_coalesce_and_bulk_render_keeps_heartbeat(app)
    finally:
        youtube_module.load_youtube_settings = original_load
    print("YouTube refresh responsiveness smokes passed.")


if __name__ == "__main__":
    main()
