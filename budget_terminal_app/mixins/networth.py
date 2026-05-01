from __future__ import annotations
from typing import Any
from ..compat import *

class NetWorthMixin:
    CASH_LINE_COLOR = '#2e7d32'
    PORTFOLIO_LINE_COLORS = ['#1565c0', '#1e88e5', '#42a5f5', '#64b5f6', '#90caf9']
    DEBT_LINE_COLOR = '#c62828'
    _P6_PROGRESS_ANIMATION_INTERVAL_MS = 33
    _P6_PROGRESS_ANIMATION_DURATION_MS = 3000

    def _p6_portfolio_breakdown(self) -> Any:
        """Return per-portfolio stock/options values using saved portfolio names."""
        portfolio_quotes = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        breakdown = []
        all_state = getattr(self, 'all_portfolios_state', {})
        portfolios = all_state.get('portfolios', {}) if isinstance(all_state, dict) else {}
        portfolio_order = all_state.get('portfolio_order', list(portfolios.keys())) if isinstance(all_state, dict) else []
        for portfolio_id in portfolio_order:
            entry = portfolios.get(portfolio_id, {})
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id))
            tickers = list(entry.get('portfolio', []))
            tracker_data = dict(entry.get('portfolio_tracker', {})) if isinstance(entry.get('portfolio_tracker', {}), dict) else {}
            options_data = list(entry.get('options_tracker', [])) if isinstance(entry.get('options_tracker', []), list) else []
            stock_mv = sum((tracker_data.get(ticker, {}).get('shares', 0) * portfolio_quotes.get(ticker, {}).get('price', 0) for ticker in tickers))
            options_equity = 0.0
            for pos in options_data:
                strategy = pos.get('strategy', 'Calls')
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                premium = pos.get('premium', 0)
                current = pos.get('current_price', 0)
                qty = pos.get('contracts', 1)
                if is_seller:
                    options_equity += (premium - current) * qty * 100
                else:
                    options_equity += current * qty * 100
            breakdown.append({'id': portfolio_id, 'name': name, 'stocks': stock_mv, 'options': options_equity})
        return breakdown

    ASSET_COLORS = ['#66bb6a', '#81c784', '#a5d6a7', '#c8e6c9', '#4caf50', '#43a047']
    DEBT_COLORS = ['#ef5350', '#e57373', '#ef9a9a', '#f44336', '#d32f2f', '#c62828']

    def _p6_table_for(self, category: Any) -> Any:
        """Return the QTableWidget for a given net-worth category."""
        if category == 'cash':
            return self.p6_cash_table
        return self.p6_debt_table

    def init_page6(self) -> None:
        """Build the Personal Finance page UI."""
        layout = QVBoxLayout(self.page6)
        layout.setContentsMargins(10, 2, 10, 10)
        layout.setSpacing(8)
        tables_splitter = QSplitter(Qt.Orientation.Horizontal)
        cash_widget = QWidget()
        cash_layout = QVBoxLayout(cash_widget)
        cash_layout.setContentsMargins(0, 0, 0, 2)
        cash_layout.setSpacing(6)
        cash_hdr = QHBoxLayout()
        cash_hdr.setContentsMargins(0, 0, 0, 2)
        cash_hdr.setSpacing(8)
        cash_lbl = QLabel('<b>CASH</b>')
        self.set_theme_role(cash_lbl, 'section_title')
        add_cash_btn = QPushButton('+ Add')
        add_cash_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_cash_btn, 'positive')
        add_cash_btn.clicked.connect(lambda: self._p6_add_row('cash'))
        remove_cash_btn = QPushButton('Remove')
        remove_cash_btn.setMinimumSize(72, 24)
        self.set_theme_variant(remove_cash_btn, 'danger')
        remove_cash_btn.clicked.connect(lambda: self._p6_remove_selected_row('cash'))
        cash_hdr.addWidget(cash_lbl)
        cash_hdr.addStretch()
        cash_hdr.addWidget(add_cash_btn)
        cash_hdr.addWidget(remove_cash_btn)
        self.p6_cash_table = QTableWidget(0, 2)
        self.p6_cash_table.setHorizontalHeaderLabels(['Description', 'Amount ($)'])
        self.p6_cash_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_cash_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p6_cash_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p6_cash_table.itemChanged.connect(lambda: self._p6_on_data_changed('cash'))
        cash_layout.addLayout(cash_hdr)
        cash_layout.addWidget(self.p6_cash_table)
        tables_splitter.addWidget(cash_widget)
        debt_widget = QWidget()
        debt_layout = QVBoxLayout(debt_widget)
        debt_layout.setContentsMargins(0, 2, 0, 0)
        debt_layout.setSpacing(6)
        debt_hdr = QHBoxLayout()
        debt_hdr.setContentsMargins(0, 0, 0, 2)
        debt_hdr.setSpacing(8)
        debt_lbl = QLabel('<b>DEBT</b>')
        self.set_theme_role(debt_lbl, 'section_title')
        add_debt_btn = QPushButton('+ Add')
        add_debt_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_debt_btn, 'danger')
        add_debt_btn.clicked.connect(lambda: self._p6_add_row('debt'))
        remove_debt_btn = QPushButton('Remove')
        remove_debt_btn.setMinimumSize(72, 24)
        self.set_theme_variant(remove_debt_btn, 'danger')
        remove_debt_btn.clicked.connect(lambda: self._p6_remove_selected_row('debt'))
        debt_hdr.addWidget(debt_lbl)
        debt_hdr.addStretch()
        debt_hdr.addWidget(add_debt_btn)
        debt_hdr.addWidget(remove_debt_btn)
        self.p6_debt_table = QTableWidget(0, 2)
        self.p6_debt_table.setHorizontalHeaderLabels(['Description', 'Amount ($)'])
        self.p6_debt_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_debt_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p6_debt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p6_debt_table.itemChanged.connect(lambda: self._p6_on_data_changed('debt'))
        debt_layout.addLayout(debt_hdr)
        debt_layout.addWidget(self.p6_debt_table)
        tables_splitter.addWidget(debt_widget)
        self.p6_progress_box = QGroupBox('Totals')
        self.set_theme_role(self.p6_progress_box, 'panel')
        self.p6_progress_box.setMinimumWidth(260)
        progress_inner = QVBoxLayout(self.p6_progress_box)
        progress_inner.setContentsMargins(10, 12, 10, 10)
        progress_inner.setSpacing(6)
        progress_hdr = QHBoxLayout()
        progress_hdr.setContentsMargins(0, 0, 0, 0)
        progress_hdr.setSpacing(8)
        self.p6_progress_legend = QWidget()
        self.p6_progress_legend.setStyleSheet('background: transparent;')
        progress_legend_layout = QHBoxLayout(self.p6_progress_legend)
        progress_legend_layout.setContentsMargins(0, 0, 0, 0)
        progress_legend_layout.setSpacing(8)
        progress_hdr.addWidget(self.p6_progress_legend)
        progress_hdr.addStretch()
        self.p6_show_animation_btn = QPushButton('Show Animation')
        self.p6_show_animation_btn.setMinimumHeight(24)
        self.set_theme_variant(self.p6_show_animation_btn, 'accent')
        self.p6_show_animation_btn.clicked.connect(self._p6_replay_progress_animation)
        progress_hdr.addWidget(self.p6_show_animation_btn)
        progress_inner.addLayout(progress_hdr)
        self.p6_progress_plot = pg.PlotWidget(
            axisItems={
                'left': FmtAxisItem(orientation='left'),
            }
        )
        progress_plot_item = self.p6_progress_plot.getPlotItem()
        progress_plot_item.setMenuEnabled(False)
        progress_plot_item.hideButtons()
        progress_plot_item.showAxis('left')
        progress_plot_item.hideAxis('right')
        self.p6_progress_plot.setMouseEnabled(x=False, y=False)
        self.p6_progress_plot.setMinimumHeight(150)
        progress_inner.addWidget(self.p6_progress_plot, 1)
        self._p6_progress_series = []
        self._p6_progress_legend_signature = []
        self._p6_progress_plot_signature = []
        self._p6_progress_plot_items = []
        self._p6_progress_anim_progress = 1.0
        self._p6_progress_autoplay_done = False
        self._p6_progress_anim_timer = QTimer(self)
        self._p6_progress_anim_timer.setInterval(self._P6_PROGRESS_ANIMATION_INTERVAL_MS)
        self._p6_progress_anim_timer.timeout.connect(self._p6_step_progress_animation)
        tables_splitter.addWidget(self.p6_progress_box)
        tables_splitter.setStretchFactor(0, 3)
        tables_splitter.setStretchFactor(1, 3)
        tables_splitter.setStretchFactor(2, 2)
        layout.addWidget(tables_splitter, 1)
        silo_box = QGroupBox('Personal Finance Silos')
        self.set_theme_role(silo_box, 'panel')
        silo_inner = QVBoxLayout(silo_box)
        silo_inner.setContentsMargins(6, 6, 6, 6)
        silo_inner.setSpacing(4)
        silo_toolbar = QHBoxLayout()
        silo_toolbar.addStretch()
        self.p6_scale_btn = QPushButton('Log')
        self.p6_scale_btn.setCheckable(True)
        self.p6_scale_btn.setChecked(True)
        self.p6_scale_btn.setFixedSize(52, 24)
        self.set_theme_variant(self.p6_scale_btn, 'accent')
        self.p6_scale_btn.clicked.connect(self._p6_toggle_scale)
        silo_toolbar.addWidget(self.p6_scale_btn)
        silo_inner.addLayout(silo_toolbar)
        self.p6_silo_bar = BarChartWidget()
        self.p6_silo_bar.setMinimumHeight(120)
        self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
        silo_inner.addWidget(self.p6_silo_bar, 1)
        layout.addWidget(silo_box, 1)
        self._p6_style_progress_plot()
        self._p6_populate_tables()

    def _p6_clear_progress_legend(self) -> None:
        """Remove all progress-chart legend widgets."""
        legend_layout = self.p6_progress_legend.layout() if hasattr(self, 'p6_progress_legend') else None
        if legend_layout is None:
            return
        for index in reversed(range(legend_layout.count())):
            widget = legend_layout.itemAt(index).widget()
            if widget is not None:
                widget.deleteLater()

    def _p6_style_progress_plot(self) -> None:
        """Apply theme-aware styling to the current-totals progress plot."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        plot_item = self.p6_progress_plot.getPlotItem()
        self.style_plot_widget(self.p6_progress_plot, show_y_grid=True)
        self.p6_progress_plot.showGrid(x=False, y=True, alpha=0.18)
        plot_item.getAxis('bottom').setTextPen(self.theme_color('chart_axis'))
        plot_item.getAxis('bottom').setTicks([[(0, '0'), (1, 'Current')]])
        plot_item.getAxis('bottom').setStyle(tickTextOffset=8, tickFont=pg.QtGui.QFont('Arial', 8))
        plot_item.getAxis('left').setTextPen(self.theme_color('chart_axis'))
        plot_item.getAxis('left').setStyle(tickTextOffset=8)
        try:
            plot_item.getAxis('left').setWidth(58)
        except Exception:
            pass
        plot_item.getViewBox().setDefaultPadding(0.08)

    def _p6_add_progress_legend_item(self, color: Any, label: str) -> None:
        """Append one inline legend chip for the progress plot."""
        legend_layout = self.p6_progress_legend.layout() if hasattr(self, 'p6_progress_legend') else None
        if legend_layout is None:
            return
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(f'background: {color}; border-radius: 5px;')
        text = QLabel(str(label or ''))
        text.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 11px; background: transparent;')
        legend_layout.addWidget(swatch)
        legend_layout.addWidget(text)

    def _p6_sync_progress_legend(self, series: list[dict[str, Any]]) -> None:
        """Rebuild the inline legend for the current-totals plot."""
        signature = [
            (
                str(entry.get('label', '') or ''),
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
            )
            for entry in series
        ]
        if signature == list(getattr(self, '_p6_progress_legend_signature', [])):
            return
        self._p6_clear_progress_legend()
        self._p6_progress_legend_signature = list(signature)
        for entry in series:
            self._p6_add_progress_legend_item(
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
                str(entry.get('label', '') or ''),
            )

    def _p6_sync_progress_plot_items(self, series: list[dict[str, Any]]) -> None:
        """Create persistent plot and counter items only when the series catalog changes."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        signature = [
            (
                str(entry.get('label', '') or ''),
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
            )
            for entry in series
        ]
        if signature == list(getattr(self, '_p6_progress_plot_signature', [])):
            return
        plot_item = self.p6_progress_plot.getPlotItem()
        plot_item.clear()
        self._p6_progress_plot_signature = list(signature)
        self._p6_progress_plot_items = []
        plot_item.getAxis('bottom').setTicks([[(0, '0'), (1, 'Current')]])
        for _label, color in signature:
            line_item = plot_item.plot(
                [],
                [],
                pen=pg.mkPen(color=color, width=2),
                symbol='o',
                symbolSize=7,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color=color, width=1),
                antialias=True,
            )
            counter_item = pg.TextItem('', color=self.theme_color('text_primary'), anchor=(0.0, 0.5))
            counter_item.setFont(pg.QtGui.QFont('Arial', 8, pg.QtGui.QFont.Weight.Bold))
            plot_item.addItem(counter_item)
            self._p6_progress_plot_items.append({'line': line_item, 'counter': counter_item})

    def _p6_current_total_series(self) -> list[dict[str, Any]]:
        """Build current-total line series for cash, portfolios, and debt."""
        series = []
        cash_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('cash', []))
        if cash_total > 0:
            series.append({'label': 'Cash', 'value': cash_total, 'color': self.CASH_LINE_COLOR})
        for index, item in enumerate(self._p6_portfolio_breakdown()):
            total_value = float(item.get('stocks', 0.0) or 0.0) + float(item.get('options', 0.0) or 0.0)
            if total_value == 0:
                continue
            series.append({
                'label': str(item.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                'value': total_value,
                'color': self.PORTFOLIO_LINE_COLORS[index % len(self.PORTFOLIO_LINE_COLORS)],
            })
        debt_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('debt', []))
        if debt_total > 0:
            series.append({'label': 'Debt', 'value': debt_total, 'color': self.DEBT_LINE_COLOR})
        return series

    def _p6_replay_progress_animation(self) -> None:
        """Replay the current-totals line animation when page 6 becomes visible."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        if hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.stop()
        self._p6_progress_anim_progress = 0.0
        self._p6_update_progress_chart(self._p6_progress_series, progress=0.0)
        if self._p6_progress_series and hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.start()

    def _p6_step_progress_animation(self) -> None:
        """Advance the current-totals line animation."""
        step = self._P6_PROGRESS_ANIMATION_INTERVAL_MS / max(float(self._P6_PROGRESS_ANIMATION_DURATION_MS), 1.0)
        self._p6_progress_anim_progress = min(1.0, float(self._p6_progress_anim_progress) + step)
        self._p6_update_progress_chart(self._p6_progress_series, progress=self._p6_progress_anim_progress)
        if self._p6_progress_anim_progress >= 1.0 and hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.stop()

    def _p6_progress_counter_text(self, value: float) -> str:
        """Format one animated line counter label."""
        return f'${value:,.0f}'

    def _p6_progress_counter_positions(self, labels: list[dict[str, Any]], y_min: float, y_max: float) -> dict[int, float]:
        """Nudge right-side counter labels apart when values are close together."""
        if not labels:
            return {}
        span = max(float(y_max) - float(y_min), 1.0)
        gap = max(span * 0.08, 1.0)
        margin = gap * 0.6
        ordered = sorted(labels, key=lambda item: float(item.get('desired_y', 0.0)))
        placed = []
        next_floor = float(y_min) + margin
        for item in ordered:
            value = max(float(item.get('desired_y', 0.0)), next_floor)
            placed.append({'index': int(item.get('index', 0)), 'y': value})
            next_floor = value + gap
        upper_limit = float(y_max) - margin
        if placed and placed[-1]['y'] > upper_limit:
            shift = placed[-1]['y'] - upper_limit
            for item in placed:
                item['y'] -= shift
        lower_limit = float(y_min) + margin
        if placed and placed[0]['y'] < lower_limit:
            shift = lower_limit - placed[0]['y']
            for item in placed:
                item['y'] += shift
        return {int(item['index']): float(item['y']) for item in placed}

    def _p6_update_progress_chart(self, series: list[dict[str, Any]], *, progress: float=1.0) -> None:
        """Render the current-totals line chart."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        plot_item = self.p6_progress_plot.getPlotItem()
        self._p6_sync_progress_legend(series)
        self._p6_sync_progress_plot_items(series)
        current_progress = min(max(float(progress), 0.0), 1.0)
        values = [0.0]
        label_specs = []
        for index, entry in enumerate(series):
            value = float(entry.get('value', 0.0) or 0.0)
            animated_value = value * current_progress
            values.append(value)
            item_bundle = self._p6_progress_plot_items[index] if index < len(self._p6_progress_plot_items) else None
            if item_bundle is not None:
                item_bundle['line'].setData(
                    [0.0, current_progress],
                    [0.0, animated_value],
                )
            label_specs.append({'index': index, 'desired_y': animated_value, 'value': animated_value})
        for stale_item in self._p6_progress_plot_items[len(series):]:
            stale_item['line'].setData([], [])
            stale_item['counter'].setText('')
        if len(values) == 1:
            plot_item.setXRange(-0.02, 1.24, padding=0)
            plot_item.setYRange(0, 1, padding=0)
            for item_bundle in self._p6_progress_plot_items:
                item_bundle['line'].setData([], [])
                item_bundle['counter'].setText('')
            return
        y_min = min(values)
        y_max = max(values)
        if y_min == y_max:
            baseline = abs(y_max) if y_max != 0 else 1.0
            y_min -= baseline * 0.2
            y_max += baseline * 0.2
        else:
            span = y_max - y_min
            y_min -= span * 0.12
            y_max += span * 0.12
        label_positions = self._p6_progress_counter_positions(label_specs, y_min, y_max)
        label_x = min(current_progress + 0.05, 1.16)
        for label in label_specs:
            index = int(label.get('index', 0))
            if index >= len(self._p6_progress_plot_items):
                continue
            counter = self._p6_progress_plot_items[index]['counter']
            counter.setText(self._p6_progress_counter_text(float(label.get('value', 0.0))), color=self.theme_color('text_primary'))
            counter.setPos(label_x, label_positions.get(index, float(label.get('desired_y', 0.0))))
        plot_item.setXRange(-0.02, 1.24, padding=0)
        plot_item.setYRange(y_min, y_max, padding=0)
        self.p6_progress_plot.update()

    def _p6_on_show(self) -> None:
        """Autoplay the current-totals animation only once per app session."""
        if not getattr(self, '_p6_progress_autoplay_done', False):
            self._p6_progress_autoplay_done = True
            self._p6_replay_progress_animation()

    def _p6_populate_tables(self, *, force_progress_rebuild: bool=False) -> None:
        """Handle p6 populate tables."""
        for category in ['cash', 'debt']:
            table = self._p6_table_for(category)
            data_list = sorted(self.networth_data.get(category, []), key=lambda x: x.get('amount', 0.0), reverse=True)
            table.blockSignals(True)
            table.setRowCount(0)
            for item in data_list:
                self._p6_insert_row_ui(table, category, item.get('desc', ''), item.get('amount', 0.0))
            table.blockSignals(False)
        self._p6_update_total(force_progress_rebuild=force_progress_rebuild)

    def _p6_insert_row_ui(self, table: Any, category: Any, desc: Any, amount: Any) -> None:
        """Handle p6 insert row ui."""
        row = table.rowCount()
        table.insertRow(row)
        desc_item = QTableWidgetItem(desc)
        amt_item = QTableWidgetItem(f'{amount:.2f}')
        amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, 0, desc_item)
        table.setItem(row, 1, amt_item)

    def _p6_add_row(self, category: Any) -> None:
        """Handle p6 add row."""
        table = self._p6_table_for(category)
        table.blockSignals(True)
        self._p6_insert_row_ui(table, category, 'New Item', 0.0)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_remove_selected_row(self, category: Any) -> None:
        """Remove only the currently selected row from the chosen finance table."""
        table = self._p6_table_for(category)
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row < 0 or row >= table.rowCount():
            return
        table.blockSignals(True)
        table.removeRow(row)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_on_data_changed(self, category: Any) -> None:
        """Handle p6 on data changed."""
        table = self._p6_table_for(category)
        new_data = []
        for r in range(table.rowCount()):
            d_item = table.item(r, 0)
            a_item = table.item(r, 1)
            if d_item and a_item:
                try:
                    amt = float(a_item.text().replace('$', '').replace(',', ''))
                except:
                    amt = 0.0
                new_data.append({'desc': d_item.text(), 'amount': amt})
        new_data.sort(key=lambda x: x.get('amount', 0.0), reverse=True)
        self.networth_data[category] = new_data
        save_networth_data(self.networth_data)
        self._p6_populate_tables(force_progress_rebuild=True)

    def _p6_update_total(self, *, force_progress_rebuild: bool=False) -> None:
        """Handle p6 update total."""
        portfolio_breakdown = self._p6_portfolio_breakdown()
        progress_series = self._p6_current_total_series()
        self._p6_progress_series = progress_series
        if force_progress_rebuild:
            self._p6_progress_legend_signature = []
            self._p6_progress_plot_signature = []
        bar_data = []
        asset_idx = 0
        for ci in self.networth_data.get('cash', []):
            amt = ci.get('amount', 0.0)
            if amt > 0:
                bar_data.append((ci.get('desc', 'Cash'), amt, self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]))
                asset_idx += 1
        for item in portfolio_breakdown:
            if item['stocks'] > 0:
                bar_data.append((f"{item['name']} Stocks", item['stocks'], self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]))
                asset_idx += 1
            if item['options'] != 0:
                color = self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)] if item['options'] > 0 else self.DEBT_COLORS[0]
                bar_data.append((f"{item['name']} Options", abs(item['options']), color))
                asset_idx += 1
        debt_idx = 0
        for di in self.networth_data.get('debt', []):
            amt = di.get('amount', 0.0)
            if amt > 0:
                bar_data.append((di.get('desc', 'Debt'), amt, self.DEBT_COLORS[debt_idx % len(self.DEBT_COLORS)]))
                debt_idx += 1
        self.p6_silo_bar.set_data(bar_data)
        current_progress = self._p6_progress_anim_progress if hasattr(self, '_p6_progress_anim_timer') and self._p6_progress_anim_timer.isActive() else 1.0
        self._p6_update_progress_chart(progress_series, progress=current_progress)

    def _p6_toggle_scale(self) -> None:
        """Toggle between log and linear scale for the silo bar chart."""
        use_log = self.p6_scale_btn.isChecked()
        self.p6_scale_btn.setText('Log' if use_log else 'Linear')
        self.set_theme_variant(self.p6_scale_btn, 'accent' if use_log else None)
        self.p6_scale_btn.setProperty('bt_checked', 'true' if use_log else 'false')
        self._repolish_widget(self.p6_scale_btn)
        self.p6_silo_bar.use_log = use_log
        self.p6_silo_bar.update()

    def _apply_networth_theme(self) -> None:
        """Refresh Personal Finance theme surfaces."""
        if hasattr(self, 'p6_silo_bar'):
            self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
            self._p6_progress_legend_signature = []
            self._p6_progress_plot_signature = []
            self._p6_style_progress_plot()
            self._p6_update_total()
