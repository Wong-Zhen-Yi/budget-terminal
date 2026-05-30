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

Row = namedtuple('Row', 'Open High Low Close Volume')


def _row(open_value: float, high: float, low: float, close: float, volume: float) -> Row:
    return Row(Open=open_value, High=high, Low=low, Close=close, Volume=volume)


def _text_item_text(item: Any) -> str:
    if hasattr(item, 'toPlainText'):
        return str(item.toPlainText())
    if hasattr(item, 'text') and callable(item.text):
        return str(item.text())
    text_item = getattr(item, 'textItem', None)
    if text_item is not None and hasattr(text_item, 'toPlainText'):
        return str(text_item.toPlainText())
    return str(getattr(item, 'text', '') or '')


def _build_window():
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
        window.resize(1200, 800)
        window.show()
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def _seed_indicator_values(window: Any) -> None:
    window.dashboard_active_indicators = ['Volume', 'RSI', '200 MA']
    window.dashboard_chart_rows = [
        _row(100.0, 110.0, 95.0, 105.0, 1000.0),
        _row(105.0, 115.0, 101.0, 112.0, 2500.0),
        _row(112.0, 120.0, 108.0, 118.0, 5000.0),
    ]
    window.dashboard_chart_ma200 = pd.Series([float('nan'), 101.0, 102.5])
    window.dashboard_rsi_series = pd.Series([float('nan'), 55.5, 62.0])
    window.dashboard_rsi_ma_series = pd.Series([float('nan'), 50.0, 58.0])
    window.dashboard_main_plot.setXRange(0, 3, padding=0)
    window.dashboard_main_plot.setYRange(95, 125, padding=0)
    window.dashboard_volume_plot.setYRange(0, 6000, padding=0)
    window.dashboard_rsi_plot.setYRange(0, 100, padding=0)


def _close_window(app: Any, window: Any) -> None:
    window.dashboard_crosshair_proxy = None
    window.close()
    window.deleteLater()
    app.processEvents()


def _readable_font_size(item: Any) -> bool:
    font = item.font()
    return font.pointSize() >= 8 or font.pixelSize() >= 11


def test_dashboard_indicator_overlays_are_readable_and_stable() -> None:
    app, window = _build_window()
    try:
        _seed_indicator_values(window)
        window._dashboard_update_indicator_panel_labels()
        app.processEvents()

        ma_item = window.dashboard_overlay_items.get('ma200')
        rsi_item = window.dashboard_overlay_items.get('rsi')
        rsi_ma_item = window.dashboard_overlay_items.get('rsi_ma')
        volume_item = window.dashboard_overlay_items.get('volume')

        assert _text_item_text(ma_item) == 'MA200 $102.50'
        assert _text_item_text(rsi_item) == 'RSI(14) 62.00'
        assert _text_item_text(rsi_ma_item) == 'RSI MA(14) 58.00'
        assert _text_item_text(volume_item) == 'Vol 5.0K'

        for item in (ma_item, rsi_item, rsi_ma_item, volume_item):
            assert item.isVisible(), 'indicator label should render as a visible widget overlay'
            assert item.width() > 0 and item.height() >= 14, 'indicator label should have readable compact dimensions'
            assert item.height() <= 24, 'indicator label should stay compact'
            assert item.text(), 'indicator label should keep visible text'
            assert item.font().bold(), 'indicator label should use bold text'
            assert _readable_font_size(item), 'indicator label should use a readable font size'
            style = item.styleSheet()
            assert 'background:' in style
            assert 'border: 2px solid' not in style
            assert 'border: none' in style
            assert item.x() >= 0 and item.y() >= 0, 'indicator label should stay inside the plot widget'

        assert ma_item.x() <= 24, 'MA200 label should sit on the left side of the chart'
        assert volume_item.x() <= 24, 'Volume label should sit on the left side of the chart'
        assert rsi_item.x() <= 24, 'RSI label should sit on the left side of the chart'
        assert abs(rsi_ma_item.y() - rsi_item.y()) <= 2, 'RSI labels should share one row'
        assert rsi_ma_item.x() >= rsi_item.x() + rsi_item.width() + 4, 'RSI labels should be side by side'

        window.dashboard_active_indicators = []
        window._dashboard_update_indicator_panel_labels()
        assert not any(key in window.dashboard_overlay_items for key in ('ma200', 'volume', 'rsi', 'rsi_ma'))
    finally:
        _close_window(app, window)


def test_dashboard_indicator_overlay_theme_refresh_keeps_compact_style() -> None:
    app, window = _build_window()
    try:
        _seed_indicator_values(window)
        window._dashboard_update_indicator_panel_labels()
        window._apply_dashboard_theme()
        app.processEvents()

        for key in ('ma200', 'volume', 'rsi', 'rsi_ma'):
            item = window.dashboard_overlay_items.get(key)
            assert item is not None, f'missing themed overlay: {key}'
            assert item.isVisible()
            assert item.font().bold()
            assert _readable_font_size(item)
            assert 'background:' in item.styleSheet()
            assert 'border: 2px solid' not in item.styleSheet()
            assert 'border: none' in item.styleSheet()
    finally:
        _close_window(app, window)


if __name__ == '__main__':
    test_dashboard_indicator_overlays_are_readable_and_stable()
    test_dashboard_indicator_overlay_theme_refresh_keeps_compact_style()
    print('dashboard chart indicator tests passed')
