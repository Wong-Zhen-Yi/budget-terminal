from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.services.backtest import (
    BACKTEST_INTERVALS,
    BACKTEST_RANGES,
    BacktestDataService,
)


P25_DEFAULT_ROWS = [{"symbol": "SPY", "weight": 100.0}]
P25_DEFAULT_SPLITTER_SIZES = [2, 5]
P25_TABLE_COLUMNS = ("Symbol", "Weight %")
P25_MAX_WORKERS = 2


class BacktestPageMixin:
    def _get_backtest_data_service(self) -> BacktestDataService:
        """Return the window-scoped backtest data service."""
        service = getattr(self, "_backtest_data_service", None)
        if service is None:
            service = BacktestDataService()
            self._backtest_data_service = service
        return service

    def init_page25(self) -> None:
        """Build the standalone Backtest page."""
        state = getattr(self, "backtest_page_state", load_backtest_page_settings())
        self.p25_rows = list(state.get("rows", P25_DEFAULT_ROWS))
        self.p25_compare_symbol = str(state.get("compare_symbol", "SPY") or "SPY").upper().strip()
        self.p25_interval_label = str(state.get("interval_label", "1D") or "1D").upper().strip()
        if self.p25_interval_label not in BACKTEST_INTERVALS:
            self.p25_interval_label = "1D"
        self.p25_range_label = str(state.get("range_label", "Max") or "Max").strip()
        if self.p25_range_label.upper() not in {str(value).upper() for value in BACKTEST_RANGES}:
            self.p25_range_label = "Max"
        self.p25_splitter_sizes = list(state.get("splitter_sizes", P25_DEFAULT_SPLITTER_SIZES))
        self._p25_request_seq = 0
        self._p25_active_request = 0
        self._p25_table_sync = False
        self._p25_interval_buttons = {}
        self._p25_range_buttons = {}
        self._p25_interval_group = QButtonGroup(self)
        self._p25_interval_group.setExclusive(True)
        self._p25_range_group = QButtonGroup(self)
        self._p25_range_group.setExclusive(True)

        layout = QVBoxLayout(self.page25)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("<b>Backtest</b>")
        self.set_theme_role(title, "page_title")
        self.p25_status_label = QLabel("Ready")
        self.p25_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p25_status_label, "status_muted")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.p25_status_label)
        layout.addLayout(header)

        self.p25_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p25_splitter.splitterMoved.connect(lambda *_: self._p25_save_state())
        self._p25_build_left_panel()
        self._p25_build_chart_panel()
        self.p25_splitter.setStretchFactor(0, 2)
        self.p25_splitter.setStretchFactor(1, 5)
        try:
            self.p25_splitter.setSizes([int(value) for value in self.p25_splitter_sizes])
        except Exception:
            self.p25_splitter.setSizes(P25_DEFAULT_SPLITTER_SIZES)
        layout.addWidget(self.p25_splitter, 1)

        self._p25_populate_table(self.p25_rows)
        self._p25_update_weight_total()
        self._p25_update_button_styles()
        self._apply_backtest_theme()

    def _p25_build_left_panel(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        controls = QHBoxLayout()
        self.p25_add_btn = QPushButton("Add")
        self.p25_add_btn.clicked.connect(self._p25_add_row)
        self.p25_remove_btn = QPushButton("Remove")
        self.p25_remove_btn.clicked.connect(self._p25_remove_selected_row)
        self.p25_normalize_btn = QPushButton("Normalize")
        self.p25_normalize_btn.clicked.connect(self._p25_normalize_table_weights)
        controls.addWidget(self.p25_add_btn)
        controls.addWidget(self.p25_remove_btn)
        controls.addWidget(self.p25_normalize_btn)
        controls.addStretch()
        left_layout.addLayout(controls)

        self.p25_table = QTableWidget(0, len(P25_TABLE_COLUMNS))
        self.p25_table.setHorizontalHeaderLabels(P25_TABLE_COLUMNS)
        self.p25_table.verticalHeader().setVisible(False)
        self.p25_table.setAlternatingRowColors(True)
        self.p25_table.horizontalHeader().setStretchLastSection(True)
        self.p25_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p25_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.p25_table.itemChanged.connect(self._p25_on_table_item_changed)
        left_layout.addWidget(self.p25_table, 1)

        self.p25_weight_label = QLabel("Weight total: --")
        self.set_theme_role(self.p25_weight_label, "muted")
        left_layout.addWidget(self.p25_weight_label)

        actions = QHBoxLayout()
        self.p25_load_main_btn = QPushButton("Load Main Portfolio")
        self.p25_load_main_btn.clicked.connect(self._p25_load_main_portfolio)
        self.p25_run_btn = QPushButton("Run Backtest")
        self.set_theme_variant(self.p25_run_btn, "accent")
        self.p25_run_btn.clicked.connect(self._p25_run_backtest)
        actions.addWidget(self.p25_load_main_btn)
        actions.addWidget(self.p25_run_btn)
        left_layout.addLayout(actions)
        self.p25_splitter.addWidget(left)

    def _p25_build_chart_panel(self) -> None:
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        compare_label = QLabel("Compare")
        self.set_theme_role(compare_label, "muted")
        self.p25_compare_input = QLineEdit(self.p25_compare_symbol)
        self.p25_compare_input.setPlaceholderText("Optional ticker")
        self.p25_compare_input.setFixedWidth(130)
        self.p25_compare_input.editingFinished.connect(self._p25_on_compare_changed)
        toolbar.addWidget(compare_label)
        toolbar.addWidget(self.p25_compare_input)
        toolbar.addSpacing(12)
        interval_label = QLabel("Interval")
        self.set_theme_role(interval_label, "muted")
        toolbar.addWidget(interval_label)
        for label in BACKTEST_INTERVALS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(partial(self._p25_set_interval, label))
            self._p25_interval_buttons[label] = button
            self._p25_interval_group.addButton(button)
            toolbar.addWidget(button)
        toolbar.addSpacing(12)
        range_label = QLabel("Range")
        self.set_theme_role(range_label, "muted")
        toolbar.addWidget(range_label)
        for label in BACKTEST_RANGES:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(partial(self._p25_set_range, label))
            self._p25_range_buttons[label] = button
            self._p25_range_group.addButton(button)
            toolbar.addWidget(button)
        toolbar.addStretch()
        right_layout.addLayout(toolbar)

        summary = QHBoxLayout()
        self.p25_window_label = QLabel("Window --")
        self.p25_return_label = QLabel("Return --")
        self.p25_cagr_label = QLabel("CAGR --")
        self.p25_drawdown_label = QLabel("Max DD --")
        self.p25_final_label = QLabel("Final $--")
        for label in (
            self.p25_window_label,
            self.p25_return_label,
            self.p25_cagr_label,
            self.p25_drawdown_label,
            self.p25_final_label,
        ):
            label.setMinimumHeight(24)
            self.set_theme_role(label, "muted")
            summary.addWidget(label)
        summary.addStretch()
        right_layout.addLayout(summary)

        self.p25_empty_label = QLabel("Run a backtest to plot normalized portfolio performance.")
        self.set_theme_role(self.p25_empty_label, "muted")
        self.p25_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.p25_empty_label)

        self.p25_axis = DateAxisItem(orientation="bottom")
        self.p25_percent_axis = PercentAxisItem(orientation="right")
        self.p25_plot = pg.PlotWidget(axisItems={"bottom": self.p25_axis, "right": self.p25_percent_axis})
        self.p25_plot.getPlotItem().setMenuEnabled(False)
        self.p25_plot.getPlotItem().hideAxis("left")
        self.p25_plot.getPlotItem().showAxis("right")
        self.p25_plot.showGrid(x=True, y=True, alpha=0.15)
        self.p25_legend = self.p25_plot.getPlotItem().addLegend(offset=(8, 8))
        self._p25_style_legend()
        right_layout.addWidget(self.p25_plot, 1)
        self.p25_splitter.addWidget(right)

    def _p25_on_show(self) -> None:
        """Refresh light UI state when the Backtest page is shown."""
        self._p25_update_weight_total()
        self._p25_update_button_styles()
        self._p25_sync_status_bar()

    def _p25_set_status(self, text: Any, status: str = "muted") -> None:
        self.set_status_text(self.p25_status_label, text, status=status)
        if hasattr(self, "status_bar"):
            self.set_status_text(self.status_bar, text, status=status)

    def _p25_sync_status_bar(self) -> None:
        if hasattr(self, "status_bar") and hasattr(self, "p25_status_label"):
            self.set_status_text(
                self.status_bar,
                self.p25_status_label.text(),
                status=str(self.p25_status_label.property("bt_status") or "muted"),
            )

    def _p25_update_button_styles(self) -> None:
        self.update_checked_button_state(self._p25_interval_buttons, self.p25_interval_label)
        self.update_checked_button_state(self._p25_range_buttons, self.p25_range_label)
        for label, button in self._p25_interval_buttons.items():
            button.setChecked(label == self.p25_interval_label)
        for label, button in self._p25_range_buttons.items():
            button.setChecked(label == self.p25_range_label)

    def _p25_populate_table(self, rows: Any) -> None:
        self._p25_table_sync = True
        try:
            self.p25_table.setRowCount(0)
            for row in list(rows or P25_DEFAULT_ROWS):
                self._p25_insert_row(row)
        finally:
            self._p25_table_sync = False

    def _p25_insert_row(self, row: Any = None) -> None:
        payload = row if isinstance(row, dict) else {}
        symbol = str(payload.get("symbol", "") or "").upper().strip()
        weight = payload.get("weight", 0.0)
        row_index = self.p25_table.rowCount()
        self.p25_table.insertRow(row_index)
        symbol_item = QTableWidgetItem(symbol)
        weight_item = QTableWidgetItem(self._p25_format_weight(weight))
        self.p25_table.setItem(row_index, 0, symbol_item)
        self.p25_table.setItem(row_index, 1, weight_item)

    def _p25_format_weight(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        if abs(number - round(number)) < 0.0001:
            return str(int(round(number)))
        return f"{number:.2f}".rstrip("0").rstrip(".")

    def _p25_table_rows(self) -> list[dict[str, Any]]:
        rows = []
        for row in range(self.p25_table.rowCount()):
            symbol_item = self.p25_table.item(row, 0)
            weight_item = self.p25_table.item(row, 1)
            symbol = str(symbol_item.text() if symbol_item is not None else "").upper().strip()
            try:
                weight = float(str(weight_item.text() if weight_item is not None else "0").strip() or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            if symbol:
                rows.append({"symbol": symbol, "weight": weight})
        return rows

    def _p25_on_table_item_changed(self, item: Any) -> None:
        if getattr(self, "_p25_table_sync", False):
            return
        if item is not None and item.column() == 0:
            clean = str(item.text() or "").upper().strip()
            if item.text() != clean:
                self._p25_table_sync = True
                item.setText(clean)
                self._p25_table_sync = False
        self._p25_update_weight_total()
        self._p25_save_state()

    def _p25_update_weight_total(self) -> None:
        total = 0.0
        for row in self._p25_table_rows():
            try:
                total += float(row.get("weight", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
        text = f"Weight total: {total:.2f}%"
        if abs(total - 100.0) <= 0.01:
            self.set_status_text(self.p25_weight_label, text, status="positive")
        else:
            self.set_status_text(self.p25_weight_label, f"{text} (will normalize on run)", status="warning")

    def _p25_add_row(self) -> None:
        self._p25_insert_row({"symbol": "", "weight": 0.0})
        self._p25_update_weight_total()
        self._p25_save_state()

    def _p25_remove_selected_row(self) -> None:
        row = self.p25_table.currentRow()
        if row < 0:
            return
        self.p25_table.removeRow(row)
        if self.p25_table.rowCount() == 0:
            self._p25_insert_row(P25_DEFAULT_ROWS[0])
        self._p25_update_weight_total()
        self._p25_save_state()

    def _p25_normalize_table_weights(self) -> None:
        weighted_rows = []
        for row_index in range(self.p25_table.rowCount()):
            symbol_item = self.p25_table.item(row_index, 0)
            weight_item = self.p25_table.item(row_index, 1)
            symbol = str(symbol_item.text() if symbol_item is not None else "").strip()
            try:
                weight = float(str(weight_item.text() if weight_item is not None else "0").strip() or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            if symbol and weight > 0.0:
                weighted_rows.append((row_index, weight))
        total = sum(weight for _, weight in weighted_rows)
        if total <= 0:
            self._p25_set_status("Normalize failed: total weight is zero.", "warning")
            return
        self._p25_table_sync = True
        try:
            for row_index, weight in weighted_rows:
                item = self.p25_table.item(row_index, 1)
                if item is not None:
                    item.setText(self._p25_format_weight(weight / total * 100.0))
        finally:
            self._p25_table_sync = False
        self._p25_update_weight_total()
        self._p25_save_state()
        self._p25_set_status("Weights normalized to 100%.", "positive")

    def _p25_load_main_portfolio(self) -> None:
        symbols = [str(symbol or "").upper().strip() for symbol in getattr(self, "tickers", []) if str(symbol or "").strip()]
        if not symbols:
            self._p25_set_status("Main portfolio has no stock tickers to load.", "warning")
            return
        portfolio = getattr(self, "last_data", {}).get("portfolio", {}) if isinstance(getattr(self, "last_data", None), dict) else {}
        tracker = getattr(self, "tracker_data", {}) if isinstance(getattr(self, "tracker_data", None), dict) else {}
        market_values = {}
        for symbol in symbols:
            entry = tracker.get(symbol, {}) if isinstance(tracker.get(symbol, {}), dict) else {}
            quote = portfolio.get(symbol, {}) if isinstance(portfolio.get(symbol, {}), dict) else {}
            try:
                shares = float(entry.get("shares", 0.0) or 0.0)
                price = float(quote.get("price", 0.0) or 0.0)
            except (TypeError, ValueError):
                shares = 0.0
                price = 0.0
            value = shares * price
            if value > 0.0:
                market_values[symbol] = value
        total = sum(market_values.values())
        if total > 0.0:
            rows = [{"symbol": symbol, "weight": market_values[symbol] / total * 100.0} for symbol in symbols if symbol in market_values]
        else:
            equal = 100.0 / len(symbols)
            rows = [{"symbol": symbol, "weight": equal} for symbol in symbols]
        self._p25_populate_table(rows)
        self._p25_update_weight_total()
        self._p25_save_state()
        self._p25_set_status(f"Loaded {len(rows)} ticker(s) from Main Portfolio.", "positive")

    def _p25_on_compare_changed(self) -> None:
        self.p25_compare_symbol = str(self.p25_compare_input.text() or "").upper().strip()
        if self.p25_compare_input.text() != self.p25_compare_symbol:
            self.p25_compare_input.setText(self.p25_compare_symbol)
        self._p25_save_state()

    def _p25_set_interval(self, label: Any, *_: Any) -> None:
        text = str(label or "").upper().strip()
        if text not in BACKTEST_INTERVALS:
            return
        self.p25_interval_label = text
        self._p25_update_button_styles()
        self._p25_save_state()

    def _p25_set_range(self, label: Any, *_: Any) -> None:
        text = str(label or "Max").strip()
        valid = {str(value).upper(): str(value) for value in BACKTEST_RANGES}
        key = text.upper()
        if key not in valid:
            return
        self.p25_range_label = valid[key]
        self._p25_update_button_styles()
        self._p25_save_state()

    def _p25_save_state(self) -> None:
        if not hasattr(self, "p25_table"):
            return
        self.backtest_page_state = save_backtest_page_settings({
            "rows": self._p25_table_rows(),
            "compare_symbol": str(getattr(self, "p25_compare_symbol", "") or "").upper().strip(),
            "interval_label": getattr(self, "p25_interval_label", "1D"),
            "range_label": getattr(self, "p25_range_label", "Max"),
            "splitter_sizes": self.p25_splitter.sizes() if hasattr(self, "p25_splitter") else P25_DEFAULT_SPLITTER_SIZES,
        })

    def _p25_run_backtest(self) -> None:
        self._p25_on_compare_changed()
        rows = self._p25_table_rows()
        if not rows:
            self._p25_set_status("Add at least one ticker before running a backtest.", "warning")
            return
        self._p25_save_state()
        self._p25_request_seq += 1
        request_id = self._p25_request_seq
        self._p25_active_request = request_id
        interval = BACKTEST_INTERVALS.get(self.p25_interval_label, "1d")
        range_key = self.p25_range_label
        compare_symbol = self.p25_compare_symbol
        self.p25_run_btn.setEnabled(False)
        self._p25_set_status(f"Loading {len(rows)} ticker(s) for {range_key} {self.p25_interval_label} backtest...", "info")

        def _run() -> None:
            try:
                result = self._get_backtest_data_service().run_backtest(
                    rows,
                    compare_symbol=compare_symbol,
                    interval=interval,
                    range_key=range_key,
                )
                self._invoke_main.emit(lambda payload=result, req=request_id: self._p25_apply_result(req, payload))
            except Exception as exc:
                self._invoke_main.emit(lambda message=str(exc), req=request_id: self._p25_handle_error(req, message))

        executor = getattr(self, "_p25_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=P25_MAX_WORKERS)
            self._p25_executor = executor
        executor.submit(_run)

    def _p25_apply_result(self, request_id: Any, result: Any) -> None:
        if int(request_id) != int(getattr(self, "_p25_active_request", 0)):
            return
        self.p25_run_btn.setEnabled(True)
        self._p25_render_result(result)
        stats = result.get("stats", {}) if isinstance(result, dict) else {}
        compare_error = str(result.get("compare_error", "") or "") if isinstance(result, dict) else ""
        if compare_error:
            self._p25_set_status(f"Backtest loaded. {compare_error}", "warning")
        else:
            start = stats.get("start")
            end = stats.get("end")
            self._p25_set_status(f"Backtest loaded from {self._p25_date_text(start)} to {self._p25_date_text(end)}.", "positive")

    def _p25_handle_error(self, request_id: Any, message: Any) -> None:
        if int(request_id) != int(getattr(self, "_p25_active_request", 0)):
            return
        self.p25_run_btn.setEnabled(True)
        self._p25_set_status(f"Backtest failed: {message}", "negative")

    def _p25_render_result(self, result: dict[str, Any]) -> None:
        portfolio_return = result.get("portfolio_return")
        if portfolio_return is None or getattr(portfolio_return, "empty", True):
            self.p25_empty_label.show()
            self.p25_plot.clear()
            return
        dates = list(portfolio_return.index)
        x_values = list(range(len(dates)))
        self.p25_axis.set_dates(dates, BACKTEST_INTERVALS.get(self.p25_interval_label, "1d"))
        self.p25_plot.clear()
        self.p25_plot.plot(
            x_values,
            [float(value) for value in portfolio_return.values],
            pen=self.theme_pen("accent", width=2.4),
            name="Backtest Portfolio",
        )
        compare_return = result.get("compare_return")
        if compare_return is not None and not getattr(compare_return, "empty", True):
            compare_values = compare_return.reindex(portfolio_return.index).ffill()
            self.p25_plot.plot(
                x_values,
                [float(value) for value in compare_values.values],
                pen=self.theme_pen("chart_reference", width=2.0, style=Qt.PenStyle.DashLine),
                name=str(result.get("compare_symbol") or "Compare"),
            )
        zero_line = pg.InfiniteLine(pos=0, angle=0, pen=self.theme_pen("chart_reference", width=1, style=Qt.PenStyle.DotLine))
        self.p25_plot.addItem(zero_line)
        if x_values:
            self.p25_plot.setXRange(0, max(1, len(x_values) - 1), padding=0.02)
        y_values = [float(value) for value in portfolio_return.values]
        if compare_return is not None and not getattr(compare_return, "empty", True):
            y_values.extend(float(value) for value in compare_return.reindex(portfolio_return.index).ffill().dropna().values)
        if y_values:
            low = min(y_values)
            high = max(y_values)
            padding = max((high - low) * 0.08, 1.0)
            self.p25_plot.setYRange(low - padding, high + padding, padding=0)
        self.p25_empty_label.hide()
        self._p25_update_summary(result.get("stats", {}))

    def _p25_update_summary(self, stats: dict[str, Any]) -> None:
        self.p25_window_label.setText(f"{self._p25_date_text(stats.get('start'))} -> {self._p25_date_text(stats.get('end'))}")
        self.p25_return_label.setText(f"Return {self._p25_pct(stats.get('total_return_pct'))}")
        self.p25_cagr_label.setText(f"CAGR {self._p25_pct(stats.get('cagr_pct'))}")
        self.p25_drawdown_label.setText(f"Max DD {self._p25_pct(stats.get('max_drawdown_pct'))}")
        try:
            final_value = float(stats.get("final_value", 0.0) or 0.0)
        except (TypeError, ValueError):
            final_value = 0.0
        self.p25_final_label.setText(f"Final ${final_value:,.2f}")

    def _p25_date_text(self, value: Any) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return "--"

    def _p25_pct(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.2f}%"

    def _apply_backtest_theme(self) -> None:
        if hasattr(self, "p25_plot"):
            self.style_plot_widget(self.p25_plot)
            self._p25_style_legend()
        if hasattr(self, "p25_status_label"):
            self.set_status_text(
                self.p25_status_label,
                self.p25_status_label.text(),
                status=str(self.p25_status_label.property("bt_status") or "muted"),
            )
        if hasattr(self, "p25_weight_label"):
            self._p25_update_weight_total()

    def _p25_style_legend(self) -> None:
        legend = getattr(self, "p25_legend", None)
        if legend is None:
            return
        legend.setLabelTextColor(self.theme_color("text_primary"))
        legend.setBrush(pg.mkBrush(QColor(self.theme_color("chart_bg"))))
        legend.setPen(pg.mkPen(self.theme_color("panel_border"), width=1))
