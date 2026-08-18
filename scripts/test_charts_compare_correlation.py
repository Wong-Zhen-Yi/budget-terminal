from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pandas as pd


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.compare_presenters import build_correlation_headers, build_correlation_rows
from budget_terminal_app.persistence import _normalize_chart_page_settings
from budget_terminal_app.services.compare_analysis import build_compare_correlation_matrix, mix_hex_color
from scripts.test_charts_startup_indicators import _build_window


COLORS = {
    'positive': '#3bc27c',
    'negative': '#ff5a5a',
    'neutral': '#171b24',
    'header': '#12151c',
    'text_primary': '#e6e9ef',
    'muted': '#8a90a0',
    'contrast_text': '#0d1017',
}


def _cumulative_percent(returns: list[float], index: pd.DatetimeIndex) -> pd.Series:
    """Turn per-interval returns into the cumulative-percent series Compare stores."""
    values = []
    level = 1.0
    for step in returns:
        level *= 1.0 + step
        values.append((level - 1.0) * 100.0)
    return pd.Series(values, index=index, dtype=float)


def _sample_frame(periods: int = 24) -> pd.DataFrame:
    index = pd.bdate_range('2026-01-05', periods=periods)
    steps = [0.0, 0.01, -0.005, 0.012, -0.002, 0.007] * (periods // 6 + 1)
    steps = steps[:periods]
    mirrored = [-step for step in steps]
    return pd.DataFrame({
        'AAA': _cumulative_percent(steps, index),
        'BBB': _cumulative_percent(steps, index),
        'CCC': _cumulative_percent(mirrored, index),
    })


def test_correlation_matrix_math() -> None:
    payload = build_compare_correlation_matrix(_sample_frame(), min_observations=5)

    assert payload['symbols'] == ['AAA', 'BBB', 'CCC']
    matrix = payload['matrix']
    assert round(matrix[0][0], 6) == 1.0
    assert round(matrix[0][1], 6) == 1.0
    assert round(matrix[0][2], 6) == -1.0
    assert round(matrix[2][2], 6) == 1.0
    assert payload['observations'][0][1] == 23
    assert payload['message'] == ''


def test_correlation_matrix_guards() -> None:
    frame = _sample_frame()
    single = build_compare_correlation_matrix(frame[['AAA']])
    assert single['matrix'] == []
    assert 'two tickers' in single['message']

    assert build_compare_correlation_matrix(None)['matrix'] == []
    assert build_compare_correlation_matrix(pd.DataFrame())['matrix'] == []

    short = build_compare_correlation_matrix(frame.head(4), min_observations=10)
    assert short['matrix'] == [] or all(value is None for row in short['matrix'] for value in row)
    assert short['message']


def test_correlation_matrix_tolerates_gaps_and_bad_values() -> None:
    index = pd.bdate_range('2026-01-05', periods=8)
    frame = pd.DataFrame({
        'AAA': [0.0, 1.0, math.nan, 2.0, 3.0, 4.0, 5.0, 6.0],
        'BBB': [0.0, 1.0, 2.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        'CCC': ['x', 'y', 'z', 'w', 'v', 'u', 't', 's'],
    }, index=index)
    payload = build_compare_correlation_matrix(frame, min_observations=3)

    assert payload['symbols'] == ['AAA', 'BBB']
    assert all(math.isfinite(float(value)) for row in payload['matrix'] for value in row if value is not None)


def test_correlation_presenter_colors_and_text() -> None:
    payload = build_compare_correlation_matrix(_sample_frame(), min_observations=5)
    rows = build_correlation_rows(payload, colors=COLORS, series_colors=['#4f8cff', '#3bc27c', '#f5c451'])

    assert build_correlation_headers(payload['symbols']) == ('', 'AAA', 'BBB', 'CCC')
    assert [row[0].text for row in rows] == ['AAA', 'BBB', 'CCC']
    assert rows[0][0].foreground == '#4f8cff'
    assert rows[0][1].text == '1.00'
    assert rows[0][1].background == COLORS['neutral']
    assert rows[0][2].text == '1.00'
    assert rows[0][3].text == '-1.00'
    assert rows[0][2].background != rows[0][3].background
    assert 'r = 1.000' in rows[0][2].tooltip
    assert mix_hex_color('#000000', '#ffffff', 0.5) == '#808080'
    assert mix_hex_color('#000000', '#ffffff', 5.0) == '#ffffff'
    assert mix_hex_color('nonsense', '#ffffff', None) == '#000000'


def test_correlation_setting_normalization() -> None:
    assert _normalize_chart_page_settings({})['compare_correlation_visible'] is True
    assert _normalize_chart_page_settings({'compare_correlation_visible': False})['compare_correlation_visible'] is False
    assert _normalize_chart_page_settings({'compare_correlation_visible': 0})['compare_correlation_visible'] is False
    assert _normalize_chart_page_settings({'compare_correlation_visible': 'false'})['compare_correlation_visible'] is True


def test_correlation_panel_renders_offscreen() -> None:
    state = _normalize_chart_page_settings({'compare_symbols': ['AAA', 'BBB', 'CCC']})
    app, window = _build_window(state)
    try:
        frame = _sample_frame()
        window.p10_compare_df = frame.copy()
        window.p10_compare_interval = '1d'
        window._p10_render_compare_chart(frame, '1d', force=True)
        app.processEvents()

        table = window.p10_compare_corr_table
        assert window.p10_compare_corr_panel.isVisibleTo(window.p10_compare_tab)
        assert window.p10_compare_correlation_btn.isChecked()
        assert table.rowCount() == 3
        assert table.columnCount() == 4
        assert [table.horizontalHeaderItem(column).text() for column in range(4)] == ['', 'AAA', 'BBB', 'CCC']
        assert table.item(0, 0).text() == 'AAA'
        assert table.item(0, 2).text() == '1.00'
        assert table.item(0, 3).text() == '-1.00'

        saved_states = []
        window._p10_save_state = lambda: saved_states.append(window.p10_compare_correlation_visible)
        window._p10_toggle_compare_correlation(False)
        app.processEvents()
        assert saved_states[-1] is False
        assert not window.p10_compare_correlation_btn.isChecked()
        assert not window.p10_compare_corr_panel.isVisibleTo(window.p10_compare_tab)
        assert set(window._p10_compare_plot_items) == {'AAA', 'BBB', 'CCC'}

        window._p10_toggle_compare_correlation(True)
        app.processEvents()
        assert saved_states[-1] is True
        assert window.p10_compare_corr_panel.isVisibleTo(window.p10_compare_tab)
        assert window.p10_compare_corr_table.rowCount() == 3
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_correlation_clears_with_single_symbol() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'compare_symbols': ['AAA']}))
    try:
        frame = _sample_frame()[['AAA']]
        window._p10_render_compare_chart(frame, '1d', force=True)
        app.processEvents()

        assert window.p10_compare_corr_table.rowCount() == 0
        assert window.p10_compare_corr_table.isHidden()
        assert 'two tickers' in window.p10_compare_corr_message.text()

        window._p10_render_compare_chart(None, '1d', force=True)
        app.processEvents()
        assert window.p10_compare_corr_table.rowCount() == 0
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_correlation_survives_theme_reapply() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'compare_symbols': ['AAA', 'BBB', 'CCC']}))
    try:
        frame = _sample_frame()
        window.p10_compare_df = frame.copy()
        window._p10_render_compare_chart(frame, '1d', force=True)
        app.processEvents()

        window._apply_charts_page_theme()
        app.processEvents()
        assert window.p10_compare_corr_table.rowCount() == 3
        assert window.p10_compare_corr_table.item(0, 3).text() == '-1.00'
        assert window.p10_compare_correlation_btn.isChecked()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_correlation_persisted_off_state() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'compare_correlation_visible': False}))
    try:
        assert window.p10_compare_correlation_visible is False
        assert not window.p10_compare_correlation_btn.isChecked()
        assert not window.p10_compare_corr_panel.isVisibleTo(window.p10_compare_tab)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    test_correlation_matrix_math()
    test_correlation_matrix_guards()
    test_correlation_matrix_tolerates_gaps_and_bad_values()
    test_correlation_presenter_colors_and_text()
    test_correlation_setting_normalization()
    test_correlation_panel_renders_offscreen()
    test_correlation_clears_with_single_symbol()
    test_correlation_survives_theme_reapply()
    test_correlation_persisted_off_state()
    print('charts compare correlation tests passed')
