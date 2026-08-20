from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest

from budget_terminal_app.dependencies import QHBoxLayout, QLabel, QPushButton, QToolTip, Qt, QWidget, pd, pg
from budget_terminal_app.persistence import (
    P2_DEFAULT_GROWTH_BASIS,
    P2_DEFAULT_PERIODS,
    P2_GROWTH_BASIS_PRIOR_PERIOD,
    P2_GROWTH_BASIS_YEAR_AGO,
    P2_MAX_PERIODS,
    P2_MIN_PERIODS,
    _normalize_fundamentals_page_settings,
    fmt_num,
)


def _build_window():
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins import fundamentals_setup as fundamentals_mixin
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    app = QApplication.instance() or QApplication([])
    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    original_save = fundamentals_mixin.save_fundamentals_page_settings
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    fundamentals_mixin.save_fundamentals_page_settings = _normalize_fundamentals_page_settings
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window.fundamentals_page_state = _normalize_fundamentals_page_settings(
            {
                "last_ticker": "NVDA",
                "selected_configuration": "custom",
                "custom_selections_by_ticker": {"NVDA": {"financials": ["Total Revenue"]}},
            }
        )
        window._startup_session_restored_tabs.add("fundamentals")
        window._ensure_page_initialized(8)
        window._p2_save_session_snapshot = lambda **_: None
        size_text = str(os.environ.get("BT_FUNDAMENTALS_SIZE", "1440x820") or "1440x820").lower()
        width_text, _, height_text = size_text.partition("x")
        window.resize(int(width_text or 1440), int(height_text or 820))
        app.processEvents()
    except Exception:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        raise
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
    return app, window, fundamentals_mixin, original_save


def _statement_frame(rows: list[str], columns: list[str], start: float) -> object:
    values = {
        pd.Timestamp(column): [start + row_index * 10 + column_index for row_index in range(len(rows))]
        for column_index, column in enumerate(columns)
    }
    return pd.DataFrame(values, index=rows)


def _payload(ticker: str = "NVDA") -> dict[str, object]:
    annual_columns = [f"{year}-12-31" for year in range(2015, 2025)]
    quarterly_columns = [
        "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31",
        "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
        "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
        "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
    ]
    quarterly_financials = _statement_frame(
        [
            "Total Revenue",
            "Net Income",
            "Selling General And Administration",
            "Research And Development",
            "Selling General And Administrative Expense",
            "Research And Development Expense",
        ],
        quarterly_columns,
        25.0,
    )
    quarterly_financials.loc[
        ["Selling General And Administration", "Research And Development"],
        [pd.Timestamp(column) for column in quarterly_columns[:-5]],
    ] = pd.NA
    quarterly_balance_sheet = _statement_frame(
        [
            "Ordinary Shares Number",
            "Cash And Cash Equivalents",
            "Total Debt",
            "Common Stock Shares Outstanding",
            "Other Short Term Investments",
            "Available For Sale Securities",
        ],
        quarterly_columns,
        60.0,
    )
    quarterly_balance_sheet.loc[
        "Ordinary Shares Number",
        [pd.Timestamp(column) for column in quarterly_columns[:-5]],
    ] = pd.NA
    return {
        "ticker": ticker,
        "info": {
            "longName": f"{ticker} Test Company",
            "sector": "Technology",
            "industry": "Semiconductors",
            "exchange": "NMS",
            "currency": "USD",
            "totalRevenue": 1_000.0,
            "freeCashflow": 100.0,
            "totalCash": 500.0,
            "totalDebt": 100.0,
        },
        "financials": _statement_frame(
            [
                "Total Revenue",
                "Net Income",
                "Selling General And Administrative",
                "Research And Development",
            ],
            annual_columns,
            100.0,
        ),
        "quarterly_financials": quarterly_financials,
        "cashflow": _statement_frame(["Operating Cash Flow", "Free Cash Flow"], annual_columns, 40.0),
        "quarterly_cashflow": _statement_frame(
            ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"], quarterly_columns, 10.0
        ),
        "balance_sheet": _statement_frame(
            [
                "Ordinary Shares Number",
                "Cash And Cash Equivalents",
                "Total Debt",
                "Other Short Term Investments",
                "Available For Sale Securities",
            ],
            annual_columns,
            80.0,
        ),
        "quarterly_balance_sheet": quarterly_balance_sheet,
        "earnings_dates": pd.DataFrame(),
        "av_used": False,
        "statement_sources": {"primary": "SEC EDGAR", "fallback": "yfinance"},
        "sec": {
            "available": True,
            "statements_available": True,
            "ticker": ticker,
            "cik": "0001045810",
            "freshness": "fresh",
            "statement_freshness": "cached",
            "warnings": [],
            "provenance": {},
            "filings": [
                {
                    "form": "10-K",
                    "filed_date": "2025-02-20",
                    "report_period": "2024-12-31",
                    "description": "Annual report",
                    "items": "",
                    "accession_number": "0001045810-25-000023",
                    "document_url": "https://www.sec.gov/Archives/edgar/data/1045810/example10k.htm",
                },
                {
                    "form": "10-Q",
                    "filed_date": "2024-11-20",
                    "report_period": "2024-09-30",
                    "description": "Quarterly report",
                    "items": "",
                    "accession_number": "0001045810-24-000222",
                    "document_url": "https://www.sec.gov/Archives/edgar/data/1045810/example10q.htm",
                },
                {
                    "form": "8-K",
                    "filed_date": "2024-10-01",
                    "report_period": "2024-10-01",
                    "description": "Current report",
                    "items": "2.02,9.01",
                    "accession_number": "0001045810-24-000200",
                    "document_url": "https://www.sec.gov/Archives/edgar/data/1045810/example8k.htm",
                },
            ],
        },
    }


def test_fundamentals_page() -> None:
    app, window, fundamentals_mixin, original_save = _build_window()
    try:
        assert window.fundamentals_page_state == {
            "last_ticker": "NVDA",
            "compare_ticker": "",
            "period_count": P2_DEFAULT_PERIODS,
            "indexed": False,
            "growth_basis": P2_DEFAULT_GROWTH_BASIS,
        }
        assert not hasattr(window, "p2_configuration_combo")
        assert not hasattr(window, "p2_configuration_buttons")
        assert not hasattr(window, "p2_configuration_group")
        assert not hasattr(window, "p2_custom_workspace")
        assert not hasattr(window, "p2_custom_editor_frame")
        assert window.p2_workspace_stack.currentWidget() is window.p2_default_workspace
        assert window.p2_workspace_stack.count() == 1
        assert window.page2.minimumSizeHint().width() <= 1280
        assert [
            window.p2_source_tabs.tabText(index)
            for index in range(window.p2_source_tabs.count())
        ] == ["Statements", "SEC Filings"]

        default_frames = tuple(window.p2_chart_frames)
        default_titles = tuple(label.text() for label in window.p2_simple_titles)
        assert default_titles == (
            "Revenue",
            "Net Income",
            "Cash Flow",
            "Shares Outstanding",
            "Cash and Bonds & Total Debt",
            "Operating Expenses",
        )
        assert len(window.p2_expand_buttons) == 6
        assert not any(button.isEnabled() for button in window.p2_expand_buttons)

        window.update_page2(_payload(), update_collection_info=False)
        assert all(
            "font-size: 17px" in value_label.styleSheet()
            for value_label in window.p2_metric_vals.values()
        )
        window._apply_fundamentals_theme()
        assert all(
            "font-size: 17px" in value_label.styleSheet()
            for value_label in window.p2_metric_vals.values()
        )
        window.stacked_widget.setCurrentIndex(8)
        window.show()
        app.processEvents()
        window._p2_relayout_charts()
        app.processEvents()
        frame_widths = [frame.width() for frame in window.p2_chart_frames]
        assert max(frame_widths) - min(frame_widths) <= 2
        window.p2_quarterly_btn.click()
        app.processEvents()
        window._p2_relayout_charts()
        app.processEvents()
        app.processEvents()
        app.processEvents()
        quarterly_count = window.p2_current_data["quarterly_financials"].shape[1]
        assert quarterly_count == 16
        assert all(len(model["labels"]) <= 12 for model in window.p2_chart_models)
        assert len(window.p2_simple_charts[0]._p2_bar_regions) == 12
        assert len(window.p2_simple_charts[3]._p2_bar_regions) == 12
        assert len(window.p2_simple_charts[5]._p2_bar_regions) == 24
        assert window._p2_tick_indices(12, 2) == [0, 2, 4, 6, 8, 11]
        expected_legends = {
            2: ["Operating CF", "Free CF"],
            4: ["Cash and Bonds", "Total Debt"],
            5: ["SG&A", "R&D"],
        }
        for plot_index, expected_text in expected_legends.items():
            legend_text = [
                label.text()
                for label in window.p2_simple_legend_bars[plot_index].findChildren(QLabel)
                if label.text()
            ]
            assert legend_text == expected_text, (plot_index, legend_text)
        def assert_compact_annotations(plot_index, plot):
            window._p2_layout_chart_annotations(plot)
            annotations = list(plot._p2_annotation_items)
            visible_bars = [region for region in plot._p2_bar_regions if region["value"] != 0]
            assert len(annotations) == len(visible_bars)
            assert all("\n" in entry["item"].toPlainText() for entry in annotations)
            annotation_rects = [
                entry["item"].sceneBoundingRect().adjusted(-1.0, -1.0, 1.0, 1.0)
                for entry in annotations
            ]
            plot_rect = plot.getPlotItem().vb.sceneBoundingRect()
            for entry in annotations:
                item_rect = entry["item"].sceneBoundingRect()
                assert plot_rect.contains(item_rect), (
                    f'{default_titles[plot_index]} label outside plot: plot={plot_rect}, label={item_rect}'
                )
            for left_index, left_rect in enumerate(annotation_rects):
                overlaps = [
                    right_rect
                    for right_rect in annotation_rects[left_index + 1:]
                    if left_rect.intersects(right_rect)
                ]
                assert not overlaps, (
                    f'{default_titles[plot_index]} overlapping labels: left={left_rect}, right={overlaps[0]}'
                )
            for entry in annotations:
                displaced = bool(entry.get("displaced"))
                assert entry["leader"].isVisible() is displaced
                if displaced:
                    continue
                region = entry["region"]
                base_scene = plot.getPlotItem().vb.mapViewToScene(
                    pg.QtCore.QPointF(region["x"], region["value"])
                )
                item_rect = entry["item"].sceneBoundingRect()
                bar_gap = (
                    base_scene.y() - item_rect.bottom()
                    if region["value"] >= 0
                    else item_rect.top() - base_scene.y()
                )
                assert 0.0 <= bar_gap <= 4.0
            if plot_index in {2, 4, 5}:
                assert any(entry.get("displaced") for entry in annotations)
                assert any(not entry.get("displaced") for entry in annotations)

        for plot_index, plot in enumerate(window.p2_simple_charts):
            assert_compact_annotations(plot_index, plot)
        # Quarterly growth defaults to year-over-year, so 2023-Q1 (29.00) measures against
        # 2022-Q1 (25.00) rather than the preceding quarter.
        revenue_annotations = window.p2_simple_charts[0]._p2_annotation_items
        assert revenue_annotations[0]["item"].toPlainText() == "29.00\n+16.0%"
        assert revenue_annotations[1]["item"].toPlainText() == "30.00\n+15.4%"
        assert all(button.isEnabled() for button in window.p2_expand_buttons)

        first_region, second_region = window.p2_simple_charts[0]._p2_bar_regions[:2]
        assert window._p2_bar_tooltip_text(first_region) == "2023-Q1\nRevenue: 29.00\nGrowth vs 2022-Q1: +16.0%"
        assert window._p2_bar_tooltip_text(second_region) == "2023-Q2\nRevenue: 30.00\nGrowth vs 2022-Q2: +15.4%"

        # Switching to QoQ measures against the preceding quarter instead.
        window.p2_qoq_btn.click()
        window._p2_apply_overview_controls()
        app.processEvents()
        qoq_annotations = window.p2_simple_charts[0]._p2_annotation_items
        assert qoq_annotations[0]["item"].toPlainText() == "29.00\n+3.6%"
        assert qoq_annotations[1]["item"].toPlainText() == "30.00\n+3.4%"
        qoq_first = window.p2_simple_charts[0]._p2_bar_regions[0]
        assert window._p2_bar_tooltip_text(qoq_first) == "2023-Q1\nRevenue: 29.00\nGrowth vs 2022-Q4: +3.6%"
        window.p2_yoy_btn.click()
        window._p2_apply_overview_controls()
        app.processEvents()
        revenue_annotations = window.p2_simple_charts[0]._p2_annotation_items
        assert revenue_annotations[0]["item"].toPlainText() == "29.00\n+16.0%"
        hover_plot = window.p2_simple_charts[0]
        hover_position = hover_plot.getPlotItem().vb.mapViewToScene(
            pg.QtCore.QPointF(second_region["x"], second_region["value"] / 2.0)
        )
        window._p2_on_chart_mouse_moved(hover_plot, hover_position)
        assert hover_plot._p2_hover_key == second_region["key"]
        assert "Revenue: 30.00" in QToolTip.text()
        outside_position = hover_plot.getPlotItem().vb.mapViewToScene(pg.QtCore.QPointF(100.0, 100.0))
        window._p2_on_chart_mouse_moved(hover_plot, outside_position)
        assert hover_plot._p2_hover_key is None
        grouped_region = next(
            region
            for region in window.p2_simple_charts[4]._p2_bar_regions
            if region["series"] == "Total Debt"
        )
        assert "Total Debt:" in window._p2_bar_tooltip_text(grouped_region)

        edge_model = window._p2_chart_model(
            "Edge Cases",
            "quarterly",
            [{
                "name": "Edge",
                "data": ([0.0, -5.0, 5.0], ["Q1", "Q2", "Q3"], [1, 2, 3]),
                "color": "#ffffff",
                "width": 0.7,
            }],
            # Pinned rather than inherited: these labels carry no year, and the point of the case
            # is the prior-period edge behavior around zero and negative baselines.
            growth_basis=P2_GROWTH_BASIS_PRIOR_PERIOD,
        )
        edge_points = edge_model["series"][0]["points"]
        assert [point["growth"] for point in edge_points] == [None, None, 200.0]
        assert [point["growth_baseline"] for point in edge_points] == ["", "", "Q2"]
        assert window._p2_growth_text(edge_points[0]["growth"]) == "—"
        edge_legend = QWidget()
        QHBoxLayout(edge_legend)
        edge_plot = pg.PlotWidget()
        edge_plot.resize(600, 240)
        edge_plot.show()
        window._p2_render_chart_model(edge_plot, edge_legend, edge_model)
        app.processEvents()
        window._p2_layout_chart_annotations(edge_plot)
        edge_annotations = list(edge_plot._p2_annotation_items)
        assert len(edge_annotations) == 2
        assert not any(entry["leader"].isVisible() for entry in edge_annotations)
        for entry in edge_annotations:
            region = entry["region"]
            base_scene = edge_plot.getPlotItem().vb.mapViewToScene(
                pg.QtCore.QPointF(region["x"], region["value"])
            )
            item_rect = entry["item"].sceneBoundingRect()
            if region["value"] >= 0:
                assert 0.0 <= base_scene.y() - item_rect.bottom() <= 4.0
            else:
                assert 0.0 <= item_rect.top() - base_scene.y() <= 4.0
        edge_plot.close()
        window.p2_annual_btn.click()
        app.processEvents()
        for plot_index, plot in enumerate(window.p2_simple_charts):
            assert_compact_annotations(plot_index, plot)
        workspace_bottom = window.p2_workspace_stack.contentsRect().bottom()
        for title, frame in zip(default_titles[3:], window.p2_chart_frames[3:]):
            frame_bottom = frame.mapTo(window.p2_workspace_stack, frame.rect().bottomRight()).y()
            assert frame_bottom <= workspace_bottom, f"{title} is clipped below the Fundamentals workspace"
        assert len(window.p2_chart_frames) == 6
        assert window.p2_current_data["financials"].shape[1] == 10
        assert window.p2_current_data["quarterly_financials"].shape[1] == 16
        assert "SEC cached + yfinance" in window.p2_status_lbl.text()
        fcf_margin_text = window.p2_metric_vals["fcf_margin"].text()
        assert fcf_margin_text == "87.0%", fcf_margin_text
        # Cash and Bonds sums cash, short term investments, and long term securities. The header
        # metric prefers the quarterly frame: 85 + 115 + 125 - 95 total debt.
        net_cash_text = window.p2_metric_vals["net_cash"].text()
        assert net_cash_text == "230.00", net_cash_text
        cash_series, debt_series = window.p2_chart_models[4]["series"]
        assert cash_series["name"] == "Cash and Bonds"
        assert debt_series["name"] == "Total Debt"
        # Annual frame is shown here: 99 cash + 119 short term + 129 long term.
        assert cash_series["points"][-1]["value"] == 347.0, cash_series["points"][-1]
        assert debt_series["points"][-1]["value"] == 109.0, debt_series["points"][-1]
        assert window.p2_filings_table.rowCount() == 3
        window.p2_filings_form_filter.setCurrentText("10-Q")
        app.processEvents()
        assert sum(not window.p2_filings_table.isRowHidden(row) for row in range(3)) == 1
        window.p2_filings_form_filter.setCurrentText("All")
        window.p2_filings_search.setText("2.02")
        app.processEvents()
        assert sum(not window.p2_filings_table.isRowHidden(row) for row in range(3)) == 1
        window.p2_filings_search.clear()
        screenshot_path = str(os.environ.get("BT_FUNDAMENTALS_SCREENSHOT", "") or "").strip()
        if not screenshot_path and "--screenshot" in sys.argv:
            screenshot_index = sys.argv.index("--screenshot")
            if screenshot_index + 1 < len(sys.argv):
                screenshot_path = sys.argv[screenshot_index + 1]
        if screenshot_path:
            window.stacked_widget.setCurrentIndex(8)
            previous_period = window._p2_period()
            screenshot_period = str(
                os.environ.get("BT_FUNDAMENTALS_SCREENSHOT_PERIOD", previous_period) or previous_period
            ).lower()
            if screenshot_period in {"annual", "quarterly"}:
                window._set_p2_period(screenshot_period)
            screenshot_tab = str(os.environ.get("BT_FUNDAMENTALS_SCREENSHOT_TAB", "statements") or "statements").lower()
            if screenshot_tab == "filings":
                window.p2_source_tabs.setCurrentIndex(1)
            else:
                window.p2_source_tabs.setCurrentIndex(0)
            app.processEvents()
            assert window.grab().save(screenshot_path)
            window.p2_source_tabs.setCurrentIndex(0)
            window._set_p2_period(previous_period)
        assert tuple(window.p2_chart_frames) == default_frames
        assert tuple(label.text() for label in window.p2_simple_titles) == default_titles

        first_dialog = None
        for chart_index, title in enumerate(default_titles):
            window._p2_open_fullscreen_chart(chart_index)
            app.processEvents()
            dialog = window.p2_fullscreen_dialog
            assert dialog is not None
            assert dialog.isFullScreen()
            assert title in dialog.windowTitle()
            assert "Annual" in dialog.windowTitle()
            assert any(
                button.text() == "Close"
                for button in dialog.findChildren(QPushButton)
            )
            if first_dialog is None:
                first_dialog = dialog
            annotations = list(dialog._p2_plot._p2_annotation_items)
            visible_bars = [
                region for region in dialog._p2_plot._p2_bar_regions
                if region["value"] != 0
            ]
            assert len(annotations) == len(visible_bars)
            assert all("\n" in entry["item"].toPlainText() for entry in annotations)
            dialog.close()
            app.processEvents()
            assert window.p2_fullscreen_dialog is None

        window._p2_open_fullscreen_chart(0)
        app.processEvents()
        replaced_dialog = window.p2_fullscreen_dialog
        window._p2_open_fullscreen_chart(1)
        app.processEvents()
        assert window.p2_fullscreen_dialog is not None
        assert window.p2_fullscreen_dialog is not replaced_dialog
        QTest.keyClick(window.p2_fullscreen_dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert window.p2_fullscreen_dialog is None

        window.p2_quarterly_btn.click()
        app.processEvents()
        window._p2_open_fullscreen_chart(4)
        app.processEvents()
        collision_dialog = window.p2_fullscreen_dialog
        assert collision_dialog is not None
        collision_dialog.showNormal()
        for fullscreen_size in ((1280, 720), (1920, 1080)):
            collision_dialog.resize(*fullscreen_size)
            app.processEvents()
            window._p2_layout_chart_annotations(collision_dialog._p2_plot)
            app.processEvents()
            annotation_items = [
                entry["item"]
                for entry in collision_dialog._p2_plot._p2_annotation_items
            ]
            annotation_rects = [
                item.sceneBoundingRect().adjusted(-1.0, -1.0, 1.0, 1.0)
                for item in annotation_items
            ]
            assert len(annotation_rects) == 24
            plot_rect = collision_dialog._p2_plot.getPlotItem().vb.sceneBoundingRect()
            assert all(plot_rect.contains(item.sceneBoundingRect()) for item in annotation_items)
            for left_index, left_rect in enumerate(annotation_rects):
                assert not any(
                    left_rect.intersects(right_rect)
                    for right_rect in annotation_rects[left_index + 1:]
                )
        screenshot_path = str(os.environ.get("BT_FUNDAMENTALS_FULLSCREEN_SCREENSHOT", "") or "").strip()
        if screenshot_path:
            assert collision_dialog.grab().save(screenshot_path)
        collision_dialog.close()
        app.processEvents()
        window.p2_annual_btn.click()
        app.processEvents()

        empty_model = window._p2_chart_model(
            "Revenue",
            "annual",
            [{
                "name": "Revenue",
                "data": ([], [], []),
                "color": "#ffffff",
            }],
        )
        saved_model = window.p2_chart_models[0]
        window.p2_chart_models[0] = empty_model
        window._p2_open_fullscreen_chart(0)
        app.processEvents()
        no_data_dialog = window.p2_fullscreen_dialog
        assert no_data_dialog is not None
        assert any(
            label.text() == "No data for this period." and label.isVisible()
            for label in no_data_dialog.findChildren(QLabel)
        )
        no_data_dialog.close()
        app.processEvents()
        window.p2_chart_models[0] = saved_model

        window.fundamentals_page_state = _normalize_fundamentals_page_settings(
            {
                "last_ticker": "NVDA",
                "selected_configuration": "custom",
                "custom_selections_by_ticker": {"NVDA": {"financials": ["Net Income"]}},
            }
        )
        window._p2_apply_runtime_state()
        app.processEvents()
        assert window.p2_ticker_input.text() == "NVDA"
        assert window.fundamentals_page_state == {
            "last_ticker": "NVDA",
            "compare_ticker": "",
            "period_count": P2_DEFAULT_PERIODS,
            "indexed": False,
            "growth_basis": P2_DEFAULT_GROWTH_BASIS,
        }

        wrong_typed_data = {
            "ticker": "NVDA",
            "info": {},
            "financials": [],
            "quarterly_financials": [],
            "cashflow": [],
            "quarterly_cashflow": [],
            "balance_sheet": [],
            "quarterly_balance_sheet": [],
        }
        for invalid_data in ({}, wrong_typed_data):
            invalid_snapshot = {
                "ticker": "NVDA",
                "data": invalid_data,
            }
            assert window._p2_restore_session_snapshot(invalid_snapshot) is False
            assert window.p2_ticker_input.text() == "NVDA"

        snapshot = window._p2_session_snapshot()
        assert snapshot is not None
        assert "configuration" not in snapshot
        assert window._p2_restore_session_snapshot(snapshot) is True
        app.processEvents()
        assert window.p2_workspace_stack.currentWidget() is window.p2_default_workspace

        yahoo_only = _payload("SPY")
        yahoo_only["sec"] = {
            "available": False,
            "statements_available": False,
            "filings": [],
            "warnings": ["No domestic SEC filer mapping was found; using Yahoo data only."],
        }
        window.update_page2(yahoo_only, update_collection_info=False)
        app.processEvents()
        assert "yfinance only" in window.p2_status_lbl.text()
        assert window.p2_filings_table.rowCount() == 0
        assert "Yahoo data only" in window.p2_filings_status.text()
    finally:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        window.close()
        app.processEvents()


def test_cash_and_bonds_series() -> None:
    from budget_terminal_app.mixins.simple_charts import SimpleChartsMixin

    class Resolver(SimpleChartsMixin):
        def theme_color(self, *_args) -> str:
            return "#000000"

        def theme_series_color(self, *_args) -> str:
            return "#000000"

    resolver = Resolver()
    columns = [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-06-30")]

    # Split rows: cash, short term investments, and long term securities all add up.
    split = pd.DataFrame(
        {columns[0]: [10.0, 20.0, 30.0], columns[1]: [11.0, 21.0, 31.0]},
        index=["Cash And Cash Equivalents", "Other Short Term Investments", "Available For Sale Securities"],
    )
    for period in ("annual", "quarterly"):
        values, _, _ = resolver._p2_cash_and_bonds_series(split, period)
        assert values == [60.0, 63.0], (period, values)

    # The combined row already bundles cash with short term investments, so a separate short
    # term row must not be added on top of it.
    combined = pd.DataFrame(
        {columns[0]: [30.0, 10.0, 20.0, 5.0], columns[1]: [32.0, 11.0, 21.0, 6.0]},
        index=[
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Other Short Term Investments",
            "Available For Sale Securities",
        ],
    )
    for period in ("annual", "quarterly"):
        values, _, _ = resolver._p2_cash_and_bonds_series(combined, period)
        assert values == [35.0, 38.0], (period, values)

    # Columns without any cash leg are skipped instead of emitting a securities-only bar.
    sparse = pd.DataFrame(
        {columns[0]: [pd.NA, 20.0], columns[1]: [11.0, 21.0]},
        index=["Cash And Cash Equivalents", "Available For Sale Securities"],
    )
    values, labels, _ = resolver._p2_cash_and_bonds_series(sparse, "quarterly")
    assert values == [32.0], values
    assert labels == ["2024-Q2"], labels

    assert resolver._p2_cash_and_bonds_series(pd.DataFrame(), "annual") == ([], [], [])


def _rekey_frame(frame: object, columns: list[str]) -> object:
    """Move one statement frame onto a different reporting calendar."""
    original = list(frame.columns)
    return frame.rename(columns=dict(zip(original, [pd.Timestamp(column) for column in columns])))


def _compare_payload(ticker: str = "AMD") -> dict[str, object]:
    """Build a compare payload on a deliberately different fiscal calendar.

    A June year end and Feb/May/Aug/Nov quarters guarantee that no raw statement column can ever
    match the primary ticker's, so the charts can only line up if alignment runs on the rendered
    period label.
    """
    payload = _payload(ticker)
    annual_columns = [f"{year}-06-30" for year in range(2015, 2025)]
    quarterly_columns = [
        "2022-02-28", "2022-05-31", "2022-08-31", "2022-11-30",
        "2023-02-28", "2023-05-31", "2023-08-31", "2023-11-30",
        "2024-02-29", "2024-05-31", "2024-08-31", "2024-11-30",
        "2025-02-28", "2025-05-31", "2025-08-31", "2025-11-30",
    ]
    for key in ("financials", "cashflow", "balance_sheet"):
        payload[key] = _rekey_frame(payload[key], annual_columns)
    for key in ("quarterly_financials", "quarterly_cashflow", "quarterly_balance_sheet"):
        payload[key] = _rekey_frame(payload[key], quarterly_columns)
    return payload


def test_fundamentals_growth_basis() -> None:
    app, window, fundamentals_mixin, original_save = _build_window()
    try:
        window.update_page2(_payload("NVDA"))
        app.processEvents()

        # Annual periods are already year-over-year, so the choice is not offered there and the
        # effective basis stays prior-period regardless of what is selected.
        assert window._p2_period() == "annual"
        assert window.p2_qoq_btn.isEnabled() is False
        assert window.p2_yoy_btn.isEnabled() is False
        assert window.p2_growth_lbl.isEnabled() is False
        assert "already year-over-year" in window.p2_qoq_btn.toolTip()
        assert window._p2_growth_basis() == P2_GROWTH_BASIS_PRIOR_PERIOD
        assert window._p2_selected_growth_basis() == P2_DEFAULT_GROWTH_BASIS
        annual_growth = [point["growth"] for point in window.p2_chart_models[0]["series"][0]["points"]]
        assert window.p2_chart_models[0]["growth_basis"] == P2_GROWTH_BASIS_PRIOR_PERIOD
        # Annual values are unchanged by the feature: each year against the previous one.
        assert annual_growth[0] is None
        assert abs(annual_growth[1] - 1.0) < 1e-9, annual_growth

        window.p2_quarterly_btn.click()
        app.processEvents()
        assert window.p2_qoq_btn.isEnabled() is True
        assert window.p2_yoy_btn.isEnabled() is True
        assert "seasonality" in window.p2_yoy_btn.toolTip()
        assert window.p2_yoy_btn.isChecked() is True, "year-over-year is the factory default"
        assert window._p2_growth_basis() == P2_GROWTH_BASIS_YEAR_AGO
        assert window.p2_chart_models[0]["growth_basis"] == P2_GROWTH_BASIS_YEAR_AGO

        # The first four visible quarters still have a year-ago baseline because growth is
        # computed before the period trim.
        points = window.p2_chart_models[0]["series"][0]["points"]
        assert points[0]["growth_baseline"] == "2022-Q1"
        assert all(point["growth"] is not None for point in points), "trimmed-away baselines are still used"

        window.p2_qoq_btn.click()
        window._p2_apply_overview_controls()
        app.processEvents()
        assert window.p2_yoy_btn.isChecked() is False
        assert window._p2_growth_basis() == P2_GROWTH_BASIS_PRIOR_PERIOD
        assert window.p2_chart_models[0]["series"][0]["points"][0]["growth_baseline"] == "2022-Q4"

        # A saved preference survives a trip through Annual mode untouched.
        window.p2_annual_btn.click()
        app.processEvents()
        assert window._p2_selected_growth_basis() == P2_GROWTH_BASIS_PRIOR_PERIOD
        window.p2_quarterly_btn.click()
        app.processEvents()
        assert window.p2_qoq_btn.isChecked() is True

        # Changing the basis then expanding must not serve a stale fullscreen chart.
        window.p2_yoy_btn.click()
        window._p2_apply_overview_controls()
        app.processEvents()
        window._p2_open_fullscreen_chart(0)
        app.processEvents()
        dialog = window.p2_fullscreen_dialog
        fullscreen_first = dialog._p2_plot._p2_bar_regions[0]
        assert fullscreen_first["growth_baseline"] == "2022-Q1"
        dialog.close()
        app.processEvents()

        # Settings and the session snapshot both carry the selection, not the effective basis.
        assert window._p2_settings_payload()["growth_basis"] == P2_GROWTH_BASIS_YEAR_AGO
        snapshot = window._p2_session_snapshot()
        assert snapshot["growth_basis"] == P2_GROWTH_BASIS_YEAR_AGO
        window._p2_apply_display_controls(
            P2_DEFAULT_PERIODS, False, "", P2_GROWTH_BASIS_PRIOR_PERIOD
        )
        assert window.p2_qoq_btn.isChecked() is True
        assert window._p2_restore_session_snapshot(snapshot) is True
        app.processEvents()
        assert window.p2_yoy_btn.isChecked() is True
    finally:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        window.close()
        app.processEvents()


def test_fundamentals_normalizer_bounds() -> None:
    assert _normalize_fundamentals_page_settings({"period_count": 99})["period_count"] == P2_MAX_PERIODS
    assert _normalize_fundamentals_page_settings({"period_count": 1})["period_count"] == P2_MIN_PERIODS
    assert _normalize_fundamentals_page_settings({"period_count": "x"})["period_count"] == P2_DEFAULT_PERIODS
    assert _normalize_fundamentals_page_settings({})["period_count"] == P2_DEFAULT_PERIODS
    # A stray string must fall back rather than becoming truthy.
    assert _normalize_fundamentals_page_settings({"indexed": "yes"})["indexed"] is False
    assert _normalize_fundamentals_page_settings({"indexed": True})["indexed"] is True
    assert _normalize_fundamentals_page_settings({"indexed": 1})["indexed"] is True
    assert _normalize_fundamentals_page_settings({"compare_ticker": "amd  "})["compare_ticker"] == "AMD"
    assert _normalize_fundamentals_page_settings({"compare_ticker": None})["compare_ticker"] == ""
    assert _normalize_fundamentals_page_settings({})["growth_basis"] == P2_DEFAULT_GROWTH_BASIS
    assert _normalize_fundamentals_page_settings({"growth_basis": "nonsense"})["growth_basis"] == P2_DEFAULT_GROWTH_BASIS
    assert _normalize_fundamentals_page_settings({"growth_basis": None})["growth_basis"] == P2_DEFAULT_GROWTH_BASIS
    assert (
        _normalize_fundamentals_page_settings({"growth_basis": "  Prior_Period "})["growth_basis"]
        == P2_GROWTH_BASIS_PRIOR_PERIOD
    )


def test_fundamentals_fetch_slots() -> None:
    """The two fetch slots must stay independent, and refresh must cover both tickers."""
    app, window, fundamentals_mixin, original_save = _build_window()
    try:
        started: list[tuple[str, str, bool]] = []

        def fake_start(ticker, slot, *, update_collection_info):
            started.append((ticker, slot, bool(update_collection_info)))
            window._p2_request_seq += 1
            window._p2_active_request_ids[slot] = window._p2_request_seq
            window._p2_request_contexts[window._p2_request_seq] = {
                "slot": slot,
                "update_collection_info": bool(update_collection_info),
            }
            return None

        window._p2_start_fetch = fake_start
        window.p2_ticker_input.setText("NVDA")

        # With no compare ticker the wrapper drives only the primary slot.
        window.analyze_stock_p2()
        assert started == [("NVDA", "primary", True)], started

        # With one set, a page refresh must cover both tickers, and the compare fetch must never
        # claim the global data-collection banner.
        started.clear()
        window.p2_compare_input.setText("AMD")
        window.analyze_stock_p2()
        assert started == [("NVDA", "primary", True), ("AMD", "compare", False)], started

        # A compare ticker equal to the primary is skipped rather than fetched twice.
        started.clear()
        window.p2_compare_input.setText("NVDA")
        window.analyze_stock_p2()
        assert started == [("NVDA", "primary", True)], started

        # A busy primary slot must still report False so the startup dispatcher does not count the
        # refresh, while a busy compare slot must not leak that False out of the wrapper.
        slot_results = {"primary": None, "compare": False}

        def recording_start(ticker, slot, *, update_collection_info):
            fake_start(ticker, slot, update_collection_info=update_collection_info)
            return slot_results[slot]

        window._p2_start_fetch = recording_start
        window.p2_compare_input.setText("AMD")
        assert window.analyze_stock_p2() is not False, "a busy compare slot must not block the refresh"
        slot_results["primary"] = False
        assert window.analyze_stock_p2() is False, "a busy primary slot must still report False"

        # The real guard short-circuits before a worker is ever constructed.
        del window._p2_start_fetch
        window.p2_fund_threads["compare"] = _RunningThread()
        assert window._p2_start_fetch("AMD", "compare", update_collection_info=False) is False
        window.p2_fund_threads["compare"] = None

        # A compare error must leave the primary status line and Analyze button untouched.
        window.p2_analyze_btn.setEnabled(True)
        window.set_status_text(window.p2_status_lbl, "NVDA  |  source: yfinance only", status="positive")
        compare_request = window._p2_request_seq + 1
        window._p2_request_seq = compare_request
        window._p2_active_request_ids["compare"] = compare_request
        window._p2_request_contexts[compare_request] = {"slot": "compare", "update_collection_info": False}
        window._page2_error(compare_request, "boom")
        assert "Compare error: boom" in window.p2_compare_status_lbl.text()
        assert window.p2_status_lbl.text() == "NVDA  |  source: yfinance only"
        assert window.p2_analyze_btn.isEnabled() is True

        # A stale response for either slot must be dropped rather than rendered.
        window.p2_current_data = None
        window._p2_active_request_ids["primary"] = 999
        window._p2_handle_result(998, _payload("STALE"))
        assert window.p2_current_data is None
    finally:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        window.close()
        app.processEvents()


class _RunningThread:
    """Stand-in for a QThread that reports itself busy."""

    def isRunning(self) -> bool:
        return True


def test_fundamentals_compare_and_periods() -> None:
    app, window, fundamentals_mixin, original_save = _build_window()
    try:
        window.update_page2(_payload("NVDA"))
        app.processEvents()

        # Single-ticker defaults must be exactly what the page had before compare existed.
        assert window.p2_compare_input.text() == ""
        assert window.p2_compare_metrics_widget.isHidden()
        assert window.p2_top_frame.height() == 66
        assert window.p2_periods_spin.value() == P2_DEFAULT_PERIODS
        assert window.p2_indexed_btn.isChecked() is False
        assert window.p2_compare_clear_btn.isEnabled() is False
        assert [series["name"] for series in window.p2_chart_models[0]["series"]] == ["Revenue"]
        assert window.p2_chart_models[0]["series"][0]["offset"] == 0.0
        assert window.p2_chart_models[0]["series"][0]["width"] == 0.7

        # A compare ticker matching the primary is rejected without starting a fetch.
        window.p2_compare_input.setText("NVDA")
        window._p2_apply_compare()
        app.processEvents()
        assert window.p2_compare_data is None
        assert "different ticker" in window.p2_compare_status_lbl.text()

        # Drive the overlay directly so the test never touches the network.
        window.p2_compare_input.setText("AMD")
        window._p2_handle_compare_result(_compare_payload("AMD"))
        app.processEvents()
        assert window.p2_compare_data is not None
        assert not window.p2_compare_metrics_widget.isHidden()
        assert window.p2_compare_clear_btn.isEnabled() is True
        assert window.p2_top_frame.height() > 66
        assert window.p2_metric_ticker_lbl.text() == "NVDA"
        assert window.p2_compare_metric_ticker_lbl.text() == "AMD"
        assert window.p2_compare_metric_vals["mktcap"].text() == window.p2_metric_vals["mktcap"].text()

        revenue_model = window.p2_chart_models[0]
        assert [series["name"] for series in revenue_model["series"]] == ["NVDA Revenue", "AMD Revenue"]
        assert [series["legend_name"] for series in revenue_model["series"]] == ["NVDA", "AMD"]
        # Solid primary, hollow compare: same hue, unmistakable fill difference.
        assert [series["filled"] for series in revenue_model["series"]] == [True, False]
        offsets = [series["offset"] for series in revenue_model["series"]]
        widths = [series["width"] for series in revenue_model["series"]]
        assert abs(sum(offsets)) < 1e-9, offsets
        assert abs(widths[0] - widths[1]) < 1e-9, widths
        opex_model = window.p2_chart_models[5]
        assert [series["name"] for series in opex_model["series"]] == [
            "NVDA SG&A",
            "AMD SG&A",
            "NVDA R&D",
            "AMD R&D",
        ], "compare series must interleave primary and compare per metric"

        # Two fiscal calendars that share no raw column still land on one set of period labels.
        assert revenue_model["labels"] == [str(year) for year in range(2015, 2025)]
        assert len(revenue_model["columns"]) == 10, "aligned columns must be the union, not the sum"
        assert len(window.p2_simple_charts[0]._p2_bar_regions) == 20

        # The lone 'Current' shares fallback is suppressed while comparing.
        shares_model = window.p2_chart_models[3]
        assert "Current" not in shares_model["labels"]

        # Compare charts must still fit inside the workspace with the second metrics row present.
        workspace_bottom = window.p2_workspace_stack.contentsRect().bottom()
        for index, frame in enumerate(window.p2_chart_frames[3:], start=3):
            frame_bottom = frame.mapTo(window.p2_workspace_stack, frame.rect().bottomRight()).y()
            assert frame_bottom <= workspace_bottom, f"compare chart {index} is clipped below the workspace"

        # Period count is presentation only: it trims, it never refetches.
        window.p2_periods_spin.setValue(6)
        window._p2_apply_overview_controls()
        app.processEvents()
        assert all(len(model["labels"]) <= 6 for model in window.p2_chart_models)
        assert window.p2_chart_models[0]["labels"] == [str(year) for year in range(2019, 2025)]
        assert window.p2_chart_models[0]["period_count"] == 6
        assert window.p2_chart_models[0]["available_columns"] == 10
        assert len(window.p2_simple_charts[0]._p2_bar_regions) == 12
        assert "10 years available" in window.p2_periods_spin.toolTip()

        window.p2_quarterly_btn.click()
        app.processEvents()
        window.p2_periods_spin.setValue(P2_MAX_PERIODS)
        window._p2_apply_overview_controls()
        app.processEvents()
        assert len(window.p2_chart_models[0]["labels"]) == 16
        assert window.p2_chart_models[0]["labels"][0] == "2022-Q1"
        # Four series over sixteen quarters exceeds what a compact card can label legibly, so the
        # value labels are dropped there and hover carries the detail.
        cash_flow_plot = window.p2_simple_charts[2]
        assert len(cash_flow_plot._p2_bar_regions) == 64
        assert cash_flow_plot._p2_annotation_items == []
        assert window.p2_simple_charts[0]._p2_annotation_items, "32 bars still fit labels"

        window.p2_annual_btn.click()
        window.p2_periods_spin.setValue(6)
        window._p2_apply_overview_controls()
        app.processEvents()

        # Indexed mode rebases to the oldest visible period and keeps the raw value for hover.
        raw_first = window.p2_chart_models[0]["series"][0]["points"][0]["value"]
        raw_annotation = window.p2_simple_charts[0]._p2_annotation_items[0]["item"].toPlainText()
        window.p2_indexed_btn.setChecked(True)
        window._p2_apply_overview_controls()
        app.processEvents()
        indexed_model = window.p2_chart_models[0]
        assert indexed_model["indexed"] is True
        for series in indexed_model["series"]:
            assert series["points"][0]["value"] == 100.0, series["name"]
            assert series["points"][0]["indexed"] is True
            assert series["indexed_base_period"] == "2019"
        assert indexed_model["series"][0]["points"][0]["raw_value"] == raw_first
        assert window.p2_simple_charts[0].getAxis("left").p2_index_mode is True
        indexed_annotation = window.p2_simple_charts[0]._p2_annotation_items[0]["item"].toPlainText()
        assert indexed_annotation.startswith("100\n"), indexed_annotation
        # Growth is scale invariant, so it must be identical raw and indexed.
        assert indexed_annotation.split("\n")[1] == raw_annotation.split("\n")[1]
        tooltip = window._p2_bar_tooltip_text(window.p2_simple_charts[0]._p2_bar_regions[0])
        assert "Index: 100 (2019 = 100)" in tooltip, tooltip
        assert str(fmt_num(raw_first)) in tooltip, tooltip

        # Fullscreen names both tickers and carries every series.
        window._p2_open_fullscreen_chart(5)
        app.processEvents()
        dialog = window.p2_fullscreen_dialog
        assert "NVDA vs AMD" in dialog.windowTitle(), dialog.windowTitle()
        assert "Indexed" in dialog.windowTitle(), dialog.windowTitle()
        assert dialog._p2_plot.getAxis("left").p2_index_mode is True
        assert len({region["series"] for region in dialog._p2_plot._p2_bar_regions}) == 4
        dialog.close()
        app.processEvents()

        # Toggling back must leave no indexed state behind in the model.
        window.p2_indexed_btn.setChecked(False)
        window._p2_apply_overview_controls()
        app.processEvents()
        assert window.p2_chart_models[0]["indexed"] is False
        assert window.p2_chart_models[0]["series"][0]["points"][0]["value"] == raw_first
        assert window.p2_simple_charts[0].getAxis("left").p2_index_mode is False
        assert window.p2_simple_charts[0]._p2_annotation_items[0]["item"].toPlainText() == raw_annotation

        # A loss-making compare ticker must index below zero, not above it.
        losses = _compare_payload("XYZ")
        losses["financials"] = losses["financials"] * -1.0
        window._p2_handle_compare_result(losses)
        window.p2_indexed_btn.setChecked(True)
        window._p2_apply_overview_controls()
        app.processEvents()
        loss_series = window.p2_chart_models[1]["series"][1]
        assert loss_series["name"] == "XYZ Net Income"
        assert loss_series["points"][0]["value"] == -100.0
        assert all(point["value"] < 0 for point in loss_series["points"])
        window.p2_indexed_btn.setChecked(False)
        window._p2_apply_overview_controls()
        app.processEvents()

        # The session snapshot carries the compare ticker, never its payload: an oversized
        # snapshot is discarded whole and would take the primary ticker's restore with it.
        window._p2_handle_compare_result(_compare_payload("AMD"))
        app.processEvents()
        snapshot = window._p2_session_snapshot()
        assert "compare_data" not in snapshot
        assert snapshot["compare_ticker"] == "AMD"
        assert snapshot["period_count"] == 6
        assert snapshot["indexed"] is False
        assert len(json.dumps(snapshot, default=str)) < 250_000

        window.p2_periods_spin.setValue(P2_DEFAULT_PERIODS)
        window.p2_indexed_btn.setChecked(True)
        window._p2_apply_overview_controls()
        app.processEvents()
        assert window._p2_restore_session_snapshot(snapshot) is True
        app.processEvents()
        assert window.p2_periods_spin.value() == 6
        assert window.p2_indexed_btn.isChecked() is False
        assert window.p2_compare_input.text() == "AMD"

        # Clearing compare returns the page to exactly its single-ticker layout.
        window._p2_clear_compare()
        app.processEvents()
        assert window.p2_compare_data is None
        assert window.p2_compare_input.text() == ""
        assert window.p2_compare_metrics_widget.isHidden()
        assert window.p2_compare_clear_btn.isEnabled() is False
        assert window.p2_top_frame.height() == 66
        assert [series["name"] for series in window.p2_chart_models[0]["series"]] == ["Revenue"]
        assert window.p2_chart_models[0]["series"][0]["width"] == 0.7
        assert window.p2_metric_ticker_lbl.isHidden()
    finally:
        fundamentals_mixin.save_fundamentals_page_settings = original_save
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_cash_and_bonds_series()
    test_fundamentals_normalizer_bounds()
    test_fundamentals_page()
    test_fundamentals_growth_basis()
    test_fundamentals_fetch_slots()
    test_fundamentals_compare_and_periods()
    print("fundamentals page smoke passed")
    sys.stdout.flush()
    os._exit(0)
