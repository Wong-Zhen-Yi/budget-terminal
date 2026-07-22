from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.compat import CandlestickItem, pg
from budget_terminal_app.persistence import _normalize_chart_page_settings
from budget_terminal_app.widgets.chart_workspace import NativeChartDrawingController
from scripts.test_charts_startup_indicators import _build_window


def test_chart_workstation_state_normalization() -> None:
    legacy = _normalize_chart_page_settings({'timeframe_label': '15 Minutes'})
    assert legacy['interval_label'] == '15 Minutes'
    assert legacy['range_label'] == '1M'
    assert legacy['timeframe_label'] == '15 Minutes'

    normalized = _normalize_chart_page_settings({
        'interval_label': '1 Minute',
        'range_label': 'Max',
        'chart_type': 'bad',
        'poll_interval_seconds': 9,
        'sidebar_visible': 0,
        'splitter_sizes': [900, 300],
        'drawings_by_context': {
            'spy|1 Day': [
                {
                    'id': 'valid-trend',
                    'type': 'trend_line',
                    'anchors': [
                        {'time': '2026-01-02T00:00:00', 'price': 100},
                        {'time': '2026-01-05T00:00:00', 'price': 105},
                    ],
                    'style': {'width': 99},
                },
                {'id': 'bad-record', 'type': 'rectangle', 'anchors': []},
            ],
            'bad-context': [],
        },
    })
    assert normalized['range_label'] == '5D'
    assert normalized['chart_type'] == 'candles'
    assert normalized['poll_interval_seconds'] == 0
    assert normalized['sidebar_visible'] is False
    assert normalized['splitter_sizes'] == [900, 300]
    assert list(normalized['drawings_by_context']) == ['SPY|1 Day']
    assert normalized['drawings_by_context']['SPY|1 Day'][0]['style']['width'] == 5.0


def test_candlestick_picture_includes_wicks() -> None:
    item = CandlestickItem([(0, 10.0, 12.0, 5.0, 20.0)])
    bounds = item.boundingRect()
    assert bounds.top() <= 5.0
    assert bounds.bottom() >= 20.0


def test_native_drawing_controller_round_trip() -> None:
    from budget_terminal_app.main import QApplication

    app = QApplication.instance() or QApplication([])
    plot = pg.PlotWidget()
    dates = list(pd.bdate_range('2026-01-01', periods=80))
    changes: list[list[dict]] = []
    controller = NativeChartDrawingController(
        plot,
        dates=lambda: dates,
        theme_color=lambda token: '#5aa2ff' if token == 'accent' else '#ffbd5a',
        changed=lambda records: changes.append(records),
        request_text=lambda: 'Earnings gap',
    )
    for tool, anchors in (
        ('trend_line', ((5, 100), (30, 115))),
        ('horizontal_line', ((10, 108),)),
        ('horizontal_ray', ((15, 110),)),
        ('rectangle', ((20, 105), (40, 120))),
        ('text', ((25, 112),)),
        ('fib', ((2, 98), (60, 125))),
    ):
        controller.set_tool(tool)
        for x_value, price in anchors:
            assert controller.handle_click(x_value, price)
    assert len(controller.records) == 6
    assert len(controller.items) == 6
    assert controller.active_tool == 'cursor'
    assert all('T00:00:00' in anchor['time'] for record in controller.records for anchor in record['anchors'])
    assert controller.records[4]['text'] == 'Earnings gap'

    horizontal_id = next(record['id'] for record in controller.records if record['type'] == 'horizontal_line')
    horizontal_item = controller.items[horizontal_id]['primary']
    controller._begin_item_change()
    horizontal_item.setValue(111.5)
    controller._finish_item_change(horizontal_id)
    horizontal_record = next(record for record in controller.records if record['id'] == horizontal_id)
    assert horizontal_record['anchors'][0]['price'] == 111.5

    selected = controller.records[-1]['id']
    controller.select(selected)
    assert controller.delete_selected()
    assert len(controller.records) == 5
    assert controller.undo()
    assert len(controller.records) == 6
    assert controller.redo()
    assert len(controller.records) == 5
    assert changes

    payload = controller.records_payload()
    controller.set_records(payload)
    assert controller.records_payload() == payload

    outside = dict(payload[0])
    outside['id'] = 'outside-range'
    outside['anchors'] = [
        {'time': '2030-01-01T00:00:00', 'price': 100.0},
        {'time': '2030-01-02T00:00:00', 'price': 105.0},
    ]
    controller.set_records([outside])
    assert controller.records and not controller.items

    cancelled = NativeChartDrawingController(
        plot,
        dates=lambda: dates,
        theme_color=lambda _token: '#5aa2ff',
        changed=lambda _records: None,
        request_text=lambda: None,
    )
    cancelled.set_tool('text')
    assert cancelled.handle_click(10, 100)
    assert not cancelled.records and cancelled.active_tool == 'cursor'
    plot.close()
    plot.deleteLater()
    app.processEvents()


def _sample_frame() -> pd.DataFrame:
    dates = pd.bdate_range('2025-01-01', periods=320)
    close = pd.Series([100.0 + index * 0.15 for index in range(len(dates))], index=dates)
    return pd.DataFrame({
        'Open': close - 0.5,
        'High': close + 1.5,
        'Low': close - 1.5,
        'Close': close,
        'Volume': [1_000_000 + index * 1000 for index in range(len(dates))],
    }, index=dates)


def test_offscreen_main_workstation_smoke() -> None:
    state = _normalize_chart_page_settings({
        'interval_label': '1 Day',
        'range_label': '3M',
        'chart_type': 'candles',
        'indicators': ['Volume', 'RSI'],
        'sidebar_visible': True,
        'splitter_sizes': [900, 300],
    })
    app, window = _build_window(state)
    try:
        frame = _sample_frame()
        window.p10_chart_df = frame
        window._p10_chart_rows = list(frame.itertuples())
        window.p10_rsi_series = pd.Series([50.0] * len(frame), index=frame.index)
        window.p10_rsi_ma_series = pd.Series([48.0] * len(frame), index=frame.index)
        window.p10_ma200_series = frame['Close'].rolling(200, min_periods=1).mean()
        stats = {
            'close': float(frame['Close'].iloc[-1]),
            'change_value': 0.15,
            'change_pct': 0.1,
        }
        window.p10_chart_stats = stats
        window._p10_render_main_chart(
            stats,
            '1d',
            window.p10_rsi_series,
            window.p10_rsi_ma_series,
            window.p10_ma200_series,
        )
        window._p10_apply_selected_range()
        x_range = window._p10_get_current_x_range()
        assert x_range[0] > 200

        window.p10_fib_manual_by_context['SPY|1 Day'] = {
            'start_index': 10,
            'start_price': 101.0,
            'start_role': 'low',
            'end_index': 40,
            'end_price': 110.0,
            'end_role': 'high',
        }
        original_save_state = window._p10_save_state
        window._p10_save_state = lambda: None
        window._p10_migrate_legacy_fib_drawing()
        window._p10_save_state = original_save_state
        migrated = window.p10_drawings_by_context['SPY|1 Day']
        assert migrated[0]['type'] == 'fib'
        assert 'SPY|1 Day' not in window.p10_fib_manual_by_context

        window.p10_chart_type = 'line'
        window._p10_refresh_chart_presentation()
        assert window.p10_close_line_item.isVisible()
        assert not window.p10_candle_item.isVisible()
        window.p10_chart_type = 'area'
        window._p10_refresh_chart_presentation()
        assert window.p10_area_item.isVisible()
        assert window.p10_area_item.opts['fillLevel'] != 0

        candle_before_error = window.p10_candle_item
        row_count_before_error = len(window._p10_chart_rows)
        window._p10_handle_chart_error(window._p10_active_request, 'temporary provider failure')
        assert window.p10_candle_item is candle_before_error
        assert len(window._p10_chart_rows) == row_count_before_error
        assert window.p10_playback_btn.isEnabled()

        scene_pos = window.p10_main_plot.getPlotItem().vb.mapViewToScene(pg.QtCore.QPointF(300, 145))
        window._p10_on_mouse_moved(window.p10_main_plot, [scene_pos])
        assert all(line.isVisible() for line in window.p10_crosshair_v_lines)
        assert window.p10_crosshair_h_line.isVisible()
        assert window.p10_crosshair_time_label.isVisible()

        window.stacked_widget.setCurrentWidget(window.page10)
        window.show()
        app.processEvents()
        calls = []
        original_refresh = window._p10_refresh_chart
        window._p10_refresh_chart = lambda force_refresh=False: calls.append(bool(force_refresh))
        window.p10_poll_interval_seconds = 15
        window._p10_poll_tick()
        assert calls == [True]
        window.p10_load_btn.setEnabled(False)
        window._p10_poll_tick()
        assert calls == [True]
        window.p10_load_btn.setEnabled(True)
        window.p10_drawing_controller.set_tool('trend_line')
        window.p10_drawing_controller.handle_click(10, 100)
        window._p10_poll_tick()
        assert calls == [True]
        window.p10_drawing_controller.cancel()
        window._p10_playback_running = True
        window._p10_poll_tick()
        assert calls == [True]
        window._p10_playback_running = False
        window._p10_refresh_chart = original_refresh

        window._p10_update_data_status({
            '_market_data_meta': {
                'source': 'yfinance',
                'freshness': 'stale',
                'fetched_at': '2026-07-10T04:00:00+00:00',
            }
        })
        assert 'Yahoo · stale' in window.p10_data_status_label.text()

        window._p10_toggle_focus_mode(True)
        assert window.p10_tabs.tabBar().isHidden()
        assert window.p10_sidebar_widget.isHidden()
        window._p10_toggle_focus_mode(False)
        assert not window.p10_tabs.tabBar().isHidden()

        window.page10.resize(1280, 720)
        window.page10.show()
        app.processEvents()
        assert window.p10_main_plot.width() > 400
        assert window.p10_sidebar_widget.width() <= 380
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    test_chart_workstation_state_normalization()
    test_candlestick_picture_includes_wicks()
    test_native_drawing_controller_round_trip()
    test_offscreen_main_workstation_smoke()
    print('charts workstation tests passed')
