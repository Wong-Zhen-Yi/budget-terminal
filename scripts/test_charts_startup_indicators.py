from __future__ import annotations

import os
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

import pandas as pd

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.persistence import _normalize_chart_page_settings
from budget_terminal_app.mixins.charts_page import P10_FIB_RETRACEMENT_LABEL
from budget_terminal_app.compat import Qt

Row = namedtuple('Row', 'Open High Low Close Volume')


def _row(open_value: float, high: float, low: float, close: float, volume: float) -> Row:
    return Row(Open=open_value, High=high, Low=low, Close=close, Volume=volume)


def _text_item_text(item: Any) -> str:
    if hasattr(item, 'toPlainText'):
        return str(item.toPlainText())
    text_item = getattr(item, 'textItem', None)
    if text_item is not None and hasattr(text_item, 'toPlainText'):
        return str(text_item.toPlainText())
    return str(getattr(item, 'text', '') or '')


def test_chart_indicator_persistence_normalization() -> None:
    default_indicators = ['Volume', '200 MA', 'Avg Price']

    assert _normalize_chart_page_settings({})['indicators'] == default_indicators
    assert _normalize_chart_page_settings({'indicators': ['Volume']})['indicators'] == ['Volume']
    assert _normalize_chart_page_settings({'indicators': []})['indicators'] == []
    assert _normalize_chart_page_settings({'indicators': ['bad']})['indicators'] == default_indicators


def _build_window(chart_state: dict[str, Any]):
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window.chart_page_state = chart_state
        window._ensure_page_initialized(9)
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_offscreen_chart_startup_indicators_honor_subset() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'indicators': ['Volume']}))
    try:
        assert window.p10_active_indicators == ['Volume']
        assert not window._p10_indicator_buttons['200 MA'].isChecked()
        assert window._p10_indicator_buttons['Volume'].isChecked()
    finally:
        window.close()
        app.processEvents()


def test_offscreen_chart_startup_indicators_honor_empty_selection() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'indicators': []}))
    try:
        assert window.p10_active_indicators == []
        for button in window._p10_indicator_buttons.values():
            assert not button.isChecked()
    finally:
        window.close()
        app.processEvents()


def test_chart_indicator_toggle_persists_without_forcing_ma200() -> None:
    import budget_terminal_app.mixins.charts_page as charts_page_module

    saved_states: list[dict[str, Any]] = []

    def fake_save_chart_page_settings(settings: Any) -> dict[str, Any]:
        state = _normalize_chart_page_settings(settings)
        saved_states.append(state)
        return state

    original_save_chart_page_settings = charts_page_module.save_chart_page_settings
    charts_page_module.save_chart_page_settings = fake_save_chart_page_settings
    try:
        app, window = _build_window(_normalize_chart_page_settings({}))
        try:
            window._p10_set_status('Ready', 'muted')
            window._p10_toggle_indicator('200 MA', False)
            assert saved_states, 'indicator toggle should persist Charts page settings'
            assert '200 MA' not in saved_states[-1]['indicators']
            assert window.p10_status_label.text() == 'Ready'
            assert 'Startup indicators saved' not in window.p10_status_label.text()

            reloaded_state = _normalize_chart_page_settings(saved_states[-1])
        finally:
            window.close()
            app.processEvents()

        app, window = _build_window(reloaded_state)
        try:
            assert '200 MA' not in window.p10_active_indicators
            assert not window._p10_indicator_buttons['200 MA'].isChecked()
        finally:
            window.close()
            app.processEvents()
    finally:
        charts_page_module.save_chart_page_settings = original_save_chart_page_settings


def test_chart_indicator_values_render_in_ohlc_header() -> None:
    app, window = _build_window(_normalize_chart_page_settings({
        'indicators': ['Volume', 'RSI', '200 MA', 'Avg Price', 'Support/Resistance', P10_FIB_RETRACEMENT_LABEL],
    }))
    try:
        assert hasattr(window, 'p10_indicator_values_label'), 'Charts header should expose indicator readout label'
        window._p10_chart_rows = [
            _row(100.0, 108.0, 98.0, 104.0, 1000.0),
            _row(95.0, 101.0, 90.0, 96.0, 2500.0),
            _row(110.0, 130.0, 108.0, 125.0, 3000.0),
            _row(125.0, 150.0, 122.0, 140.0, 3500.0),
        ]
        window.p10_chart_stats = {'close': 140.0}
        window.p10_ma200_series = pd.Series([90.0, 95.0, 100.0, 105.0])
        window.p10_rsi_series = pd.Series([45.0, 55.5, 60.0, 62.0])
        window.p10_rsi_ma_series = pd.Series([44.0, 50.0, 58.0, 59.0])
        window._p10_portfolio_avg_price = lambda _symbol: 100.0

        window._p10_refresh_support_resistance_lines()
        window._p10_refresh_fib_retracement()
        window._p10_show_row_details(1)

        ohlc_text = window.p10_ohlc_label.text()
        indicator_text = window.p10_indicator_values_label.text()
        assert 'O 95.00' in ohlc_text and 'C 96.00' in ohlc_text
        assert 'Vol' not in ohlc_text, 'Volume should move out of the OHLC label'
        assert window.p10_indicator_values_label.alignment() & Qt.AlignmentFlag.AlignLeft
        assert window.p10_indicator_values_label.minimumWidth() <= 260
        for expected in (
            'S $',
            'R $',
            'Fib 0%',
            'Fib 23.6%',
            'Fib 38.2%',
            'Fib 50%',
            'Fib 61.8%',
            'Fib 78.6%',
            'Fib 100%',
            'MA200 $95.00',
            'Avg $100.00 Gain -4.00%',
            'Vol',
            'RSI 55.50',
            'RSI MA 50.00',
        ):
            assert expected in indicator_text, f'missing header indicator value: {expected}'
        assert window.p10_indicator_values_label.toolTip() == indicator_text
    finally:
        window.close()
        app.processEvents()


def test_chart_indicator_value_update_clears_legacy_plot_overlays() -> None:
    app, window = _build_window(_normalize_chart_page_settings({
        'indicators': ['Volume', 'RSI', '200 MA', 'Support/Resistance'],
    }))
    try:
        for key, plot in (
            ('ma200', window.p10_main_plot),
            ('avg_cost', window.p10_main_plot),
            ('volume', window.p10_volume_plot),
            ('rsi', window.p10_rsi_plot),
            ('rsi_ma', window.p10_rsi_plot),
        ):
            window._p10_set_overlay_text(key, plot, key, window.theme_color('text_secondary'))
        assert window._p10_overlay_items, 'test setup should create legacy plot overlays'

        window._p10_update_indicator_panel_labels()

        for key in ('ma200', 'avg_cost', 'volume', 'rsi', 'rsi_ma', 'support', 'resistance', 'fib'):
            assert key not in window._p10_overlay_items, f'legacy overlay should be removed: {key}'
    finally:
        window.close()
        app.processEvents()


def test_chart_support_resistance_values_render_after_ohlc() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'indicators': ['Support/Resistance']}))
    try:
        window.p10_active_indicators = ['Support/Resistance']
        window._p10_chart_rows = [
            _row(100.0, 110.0, 95.0, 105.0, 1000.0),
            _row(106.0, 120.0, 104.0, 118.0, 2500.0),
            _row(119.0, 125.0, 112.0, 122.0, 3000.0),
        ]
        window.p10_support_label_item = window._p10_line_label_item(
            None,
            window.p10_main_plot,
            'Support $100.00',
            window.theme_color('accent_positive'),
        )
        window.p10_resistance_label_item = window._p10_line_label_item(
            None,
            window.p10_main_plot,
            'Resistance $120.00',
            window.theme_color('accent_negative'),
        )

        window._p10_refresh_support_resistance_lines()
        window._p10_refresh_overlay_positions()

        assert window.p10_support_line is not None, 'Support line should render'
        assert window.p10_resistance_line is not None, 'Resistance line should render'
        assert window.p10_support_label_item is None, 'Support value text should render after OHLC, not on the line'
        assert window.p10_resistance_label_item is None, 'Resistance value text should render after OHLC, not on the line'
        assert 'S $' in window.p10_indicator_values_label.text()
        assert 'R $' in window.p10_indicator_values_label.text()
    finally:
        window.close()
        app.processEvents()


def test_chart_fibonacci_values_render_after_ohlc() -> None:
    app, window = _build_window(_normalize_chart_page_settings({'indicators': [P10_FIB_RETRACEMENT_LABEL]}))
    try:
        window.p10_active_indicators = [P10_FIB_RETRACEMENT_LABEL]
        window._p10_chart_rows = [
            _row(100.0, 108.0, 98.0, 104.0, 1000.0),
            _row(95.0, 101.0, 90.0, 96.0, 1000.0),
            _row(110.0, 130.0, 108.0, 125.0, 1000.0),
            _row(125.0, 150.0, 122.0, 140.0, 1000.0),
        ]
        window.p10_fib_label_items = [
            window._p10_line_label_item(
                None,
                window.p10_main_plot,
                'Fib 50% $120.00',
                window.theme_color('warning'),
            )
        ]
        window._p10_refresh_fib_retracement()
        window._p10_refresh_overlay_positions()

        assert window.p10_fib_line_items, 'Fib should still render horizontal level lines'
        assert window.p10_fib_levels, 'Fib levels should remain available for header values'
        assert window.p10_fib_label_items == [], 'Fib value text should render after OHLC, not on chart lines'
        indicator_text = window.p10_indicator_values_label.text()
        for expected in ('Fib 0%', 'Fib 23.6%', 'Fib 38.2%', 'Fib 50%', 'Fib 61.8%', 'Fib 78.6%', 'Fib 100%'):
            assert expected in indicator_text, f'missing header Fibonacci value: {expected}'
        assert 'Fib 0-100%' not in indicator_text, 'Fib should render level values, not the old compact summary'
    finally:
        window.close()
        app.processEvents()


if __name__ == '__main__':
    test_chart_indicator_persistence_normalization()
    test_offscreen_chart_startup_indicators_honor_subset()
    test_offscreen_chart_startup_indicators_honor_empty_selection()
    test_chart_indicator_toggle_persists_without_forcing_ma200()
    test_chart_indicator_values_render_in_ohlc_header()
    test_chart_indicator_value_update_clears_legacy_plot_overlays()
    test_chart_support_resistance_values_render_after_ohlc()
    test_chart_fibonacci_values_render_after_ohlc()
    print('charts startup indicator tests passed')
