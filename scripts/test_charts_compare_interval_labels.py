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

from budget_terminal_app.mixins.charts_page import ChartsPageMixin
from budget_terminal_app.persistence import _normalize_chart_page_settings
from scripts.test_charts_startup_indicators import _build_window


def _text_item_text(item) -> str:
    if hasattr(item, 'toPlainText'):
        return str(item.toPlainText())
    text_item = getattr(item, 'textItem', None)
    if text_item is not None and hasattr(text_item, 'toPlainText'):
        return str(text_item.toPlainText())
    return str(getattr(item, 'text', '') or '')


def test_compare_interval_label_setting_normalization() -> None:
    assert _normalize_chart_page_settings({})['compare_interval_labels_enabled'] is True
    assert _normalize_chart_page_settings({'compare_interval_labels_enabled': False})['compare_interval_labels_enabled'] is False
    assert _normalize_chart_page_settings({'compare_interval_labels_enabled': 0})['compare_interval_labels_enabled'] is False
    assert _normalize_chart_page_settings({'compare_interval_labels_enabled': 'false'})['compare_interval_labels_enabled'] is True


def test_compare_interval_change_calculation_uses_previous_valid_point() -> None:
    dates = pd.bdate_range('2026-01-05', periods=6)
    cumulative = pd.Series([0.0, 10.0, math.nan, math.inf, -1.0, -1.0], index=dates)
    changes = ChartsPageMixin._p10_calculate_compare_interval_changes(object(), cumulative)

    assert list(changes.index) == [dates[1], dates[4], dates[5]]
    assert round(float(changes.loc[dates[1]]), 6) == 10.0
    assert round(float(changes.loc[dates[4]]), 6) == -10.0
    assert round(float(changes.loc[dates[5]]), 6) == 0.0


def test_compare_interval_labels_render_toggle_and_cleanup_offscreen() -> None:
    state = _normalize_chart_page_settings({
        'compare_symbols': ['AAPL', 'MSFT'],
        'compare_interval_labels_enabled': True,
    })
    app, window = _build_window(state)
    try:
        dates = pd.bdate_range('2026-01-05', periods=4)
        frame = pd.DataFrame({
            'AAPL': [0.0, 10.0, math.nan, -1.0],
            'MSFT': [0.0, math.nan, 20.0, 20.0],
        }, index=dates)
        window.p10_compare_df = frame.copy()
        window.p10_compare_interval = '1d'
        window._p10_render_compare_chart(frame, '1d', force=True)
        app.processEvents()

        assert window.p10_compare_interval_labels_btn.isChecked()
        assert set(window._p10_compare_plot_items) == {'AAPL', 'MSFT'}
        assert set(window._p10_compare_label_items) == {'AAPL', 'MSFT'}
        assert set(window._p10_compare_interval_label_items) == {'AAPL', 'MSFT'}
        assert [point[2] for point in window._p10_compare_interval_label_items['AAPL'].points] == ['+10.0%', '-10.0%']
        assert [point[2] for point in window._p10_compare_interval_label_items['MSFT'].points] == ['+20.0%', '0.0%']
        assert window._p10_compare_interval_label_items['AAPL'].points[0][3] is True
        assert window._p10_compare_interval_label_items['AAPL'].points[1][3] is False
        assert 'AAPL -1.0%' in _text_item_text(window._p10_compare_label_items['AAPL'])
        assert not window.p10_compare_plot.grab().isNull()

        saved_states = []
        original_plot_items = dict(window._p10_compare_plot_items)
        window._p10_save_state = lambda: saved_states.append(window.p10_compare_interval_labels_enabled)
        window._p10_toggle_compare_interval_labels(False)
        app.processEvents()
        assert saved_states[-1] is False
        assert not window.p10_compare_interval_labels_btn.isChecked()
        assert window._p10_compare_interval_label_items == {}
        assert window._p10_compare_plot_items == original_plot_items

        window._p10_toggle_compare_interval_labels(True)
        app.processEvents()
        assert saved_states[-1] is True
        assert set(window._p10_compare_interval_label_items) == {'AAPL', 'MSFT'}

        window._p10_render_compare_chart(frame[['AAPL']], '1d', force=True)
        app.processEvents()
        assert set(window._p10_compare_plot_items) == {'AAPL'}
        assert set(window._p10_compare_label_items) == {'AAPL'}
        assert set(window._p10_compare_interval_label_items) == {'AAPL'}
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_compare_interval_labels_honor_persisted_off_state() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'compare_interval_labels_enabled': False}))
    try:
        assert window.p10_compare_interval_labels_enabled is False
        assert not window.p10_compare_interval_labels_btn.isChecked()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    test_compare_interval_label_setting_normalization()
    test_compare_interval_change_calculation_uses_previous_valid_point()
    test_compare_interval_labels_render_toggle_and_cleanup_offscreen()
    test_compare_interval_labels_honor_persisted_off_state()
    print('charts compare interval label tests passed')
