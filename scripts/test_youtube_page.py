from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QWidget

import budget_terminal_app.mixins.youtube as youtube_module
from budget_terminal_app.mixins.youtube import YouTubeMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class YouTubeHarness(QWidget, YouTubeMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page16 = QWidget(self)

    def set_theme_role(self, widget, role):
        widget.setProperty('bt_role', role)
        return widget

    def set_theme_variant(self, widget, variant):
        widget.setProperty('bt_variant', variant)
        return widget

    def theme_color(self, token):
        return {
            'accent': '#5b9dff',
            'panel_background': '#111a29',
            'panel_border': '#34425a',
            'text_primary': '#edf2f7',
            'text_muted': '#7f8a9a',
        }.get(token, '#b8c0cc')

    def set_status_text(self, label, text, status='muted'):
        label.setText(text)
        label.setProperty('bt_status', status)

    def _p16_request_thumbnail(self, item):
        self.p16_thumbnail_lbl.setText('Thumbnail test placeholder')


def _videos() -> list[dict]:
    return [
        {
            'ticker': 'AAA',
            'title': 'Alpha outlook',
            'channel': 'Market Desk',
            'view_count': 12_000,
            'published_text': '2026-07-19',
            'duration_text': '8:30',
            'description_snippet': 'Alpha earnings discussion',
            'url': 'https://www.youtube.com/watch?v=alpha123',
        },
        {
            'ticker': 'BBB',
            'title': 'Beta deep dive',
            'channel': 'Research Room',
            'view_count': 88_000,
            'published_text': '2026-07-15',
            'duration_text': '15:10',
            'description_snippet': 'Beta product analysis',
            'url': 'https://www.youtube.com/watch?v=beta123',
        },
        {
            'ticker': 'CCC',
            'title': 'Gamma interview',
            'channel': 'Market Desk',
            'view_count': 3_000,
            'published_text': '2026-07-10',
            'duration_text': '1:02:03',
            'description_snippet': 'Gamma management interview',
            'url': 'https://www.youtube.com/watch?v=gamma123',
        },
    ]


def test_controls_filter_sort_and_busy_state(app: QApplication) -> None:
    saved_states: list[dict] = []
    original_load = youtube_module.load_youtube_settings
    original_save = youtube_module.save_youtube_settings
    youtube_module.load_youtube_settings = lambda: {'sort_column': -1, 'sort_descending': False}
    youtube_module.save_youtube_settings = lambda state: saved_states.append(dict(state)) or dict(state)
    try:
        harness = YouTubeHarness()
        harness.init_page16()
        harness.page16.resize(1280, 760)
        harness.page16.show()
        app.processEvents()

        _assert(harness.p16_search_input.placeholderText().startswith('Filter ticker'), 'The feed should expose a local filter')
        _assert(harness.p16_refresh_btn.text() == 'Refresh Videos', 'The page should expose an explicit refresh action')
        _assert(not harness.p16_watch_btn.isEnabled(), 'Watch should be disabled until a video is selected')

        harness._p16_items = harness._p16_sorted_items(_videos())
        harness._p16_render_table()
        app.processEvents()

        _assert(harness.p16_table.rowCount() == 3, 'All loaded videos should render by default')
        _assert(harness.p16_result_count_lbl.text() == '3 videos', 'The toolbar should summarize the loaded feed')
        _assert(harness.p16_table.item(0, 0).text() == 'AAA', 'Default order should put the newest video first')
        _assert(harness.p16_watch_btn.isEnabled(), 'A selected video with a URL should enable Watch')

        harness.p16_search_input.setText('research room')
        app.processEvents()
        _assert(harness.p16_table.rowCount() == 1, 'Filtering should match channel text')
        _assert(harness.p16_table.item(0, 0).text() == 'BBB', 'Filtering should retain the matching video')
        _assert(harness.p16_result_count_lbl.text() == '1 of 3 videos', 'Filtered count should retain total context')

        harness.p16_search_input.setText('no match')
        app.processEvents()
        _assert(harness.p16_table.rowCount() == 0, 'A nonmatching filter should empty the visible feed')
        _assert(harness.p16_video_title_lbl.text() == 'No matching videos', 'The empty state should explain the filter result')
        _assert(not harness.p16_watch_btn.isEnabled(), 'Watch should disable when no row is visible')

        harness.p16_search_input.clear()
        harness._p16_sort_by_column(3)
        app.processEvents()
        _assert(harness.p16_table.item(0, 0).text() == 'BBB', 'Views should sort highest-first on first click')
        _assert(saved_states[-1] == {'sort_column': 3, 'sort_descending': True}, 'Sort choice should be persisted')

        harness._p16_sort_by_column(3)
        app.processEvents()
        _assert(harness.p16_table.item(0, 0).text() == 'CCC', 'A second Views click should reverse the order')
        _assert(saved_states[-1] == {'sort_column': 3, 'sort_descending': False}, 'Reversed sort should be persisted')

        harness._p16_set_busy(True)
        _assert(not harness.p16_refresh_btn.isEnabled(), 'Refresh should disable while work is running')
        _assert(harness.p16_refresh_btn.text() == 'Refreshing...', 'Busy state should be visible on the control')
        harness._p16_set_busy(False)
        _assert(harness.p16_refresh_btn.isEnabled(), 'Refresh should re-enable after work completes')

        harness.close()
        app.processEvents()
    finally:
        youtube_module.load_youtube_settings = original_load
        youtube_module.save_youtube_settings = original_save


def main() -> None:
    app = QApplication.instance() or QApplication([])
    test_controls_filter_sort_and_busy_state(app)
    print('YouTube page smoke tests passed')


if __name__ == '__main__':
    main()
