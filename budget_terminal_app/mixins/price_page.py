from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.widgets.batched_render import LABEL_MAX_ITEMS, run_batched
from budget_terminal_app.workers.price_screen import PriceScreenWorker


_P30_HEADERS = ('#', 'Ticker', 'Company', 'Exchange', 'Price', 'Market Cap')
_P30_NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole
_P30_RESULT_LIMIT = 100


class _P30NumericTableWidgetItem(QTableWidgetItem):
    """Table item that sorts by its raw numeric value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.data(_P30_NUMERIC_SORT_ROLE)) < float(other.data(_P30_NUMERIC_SORT_ROLE))
        except Exception:
            return super().__lt__(other)


class _P30MarketCapAxisItem(pg.AxisItem):
    """Render log10 market-cap coordinates as compact dollar values."""

    def tickStrings(self, values: Any, scale: Any, spacing: Any) -> list[str]:
        labels = []
        for value in values:
            try:
                raw_value = 10 ** float(value)
            except (TypeError, ValueError, OverflowError):
                labels.append('')
                continue
            labels.append(PricePageMixin._p30_format_compact_currency(raw_value))
        return labels


class PricePageMixin:
    def _p30_has_page_visibility_api(self) -> bool:
        """Return whether the host provides the real window visibility guard."""
        return callable(getattr(self, '_is_current_page', None))

    def _p30_page_is_visible(self) -> bool:
        """Treat small standalone probes as visible while guarding the real app."""
        checker = getattr(self, '_is_current_page', None)
        if callable(checker):
            return bool(checker(getattr(self, 'page30', None)))
        return True

    def init_page30(self) -> None:
        """Build the Price market-screener page."""
        self._p30_fetching = False
        self._p30_worker = None
        self._p30_rows: list[dict[str, Any]] = []
        self._p30_scatter = None
        self._p30_selection_scatter = None
        self._p30_label_items: list[Any] = []
        self._p30_plot_points: list[tuple[float, float, str]] = []
        self._p30_render_generation = 0

        layout = QVBoxLayout(self.page30)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel('<b>Price</b>')
        self.set_theme_role(title, 'page_title')
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        minimum_label = QLabel('Minimum price')
        maximum_label = QLabel('Maximum price')
        self.set_theme_role(minimum_label, 'status_muted')
        self.set_theme_role(maximum_label, 'status_muted')
        self.p30_minimum_price_spin = self._p30_price_input(100.0)
        self.p30_maximum_price_spin = self._p30_price_input(200.0)
        self.p30_fetch_btn = QPushButton('Fetch')
        self.set_theme_variant(self.p30_fetch_btn, 'accent')
        self.p30_fetch_btn.clicked.connect(self._p30_fetch)
        self.p30_minimum_price_spin.editingFinished.connect(self._p30_validate_inputs)
        self.p30_maximum_price_spin.editingFinished.connect(self._p30_validate_inputs)
        self.p30_status_lbl = QLabel('Enter a price range and select Fetch.')
        self.set_theme_role(self.p30_status_lbl, 'status_muted')
        self.p30_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(minimum_label)
        controls.addWidget(self.p30_minimum_price_spin)
        controls.addWidget(maximum_label)
        controls.addWidget(self.p30_maximum_price_spin)
        controls.addWidget(self.p30_fetch_btn)
        controls.addStretch()
        controls.addWidget(self.p30_status_lbl, 1)
        panel_layout.addLayout(controls)

        self.p30_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p30_body_splitter.setChildrenCollapsible(False)

        self.p30_table = QTableWidget(0, len(_P30_HEADERS))
        self.p30_table.setHorizontalHeaderLabels(list(_P30_HEADERS))
        self.p30_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p30_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p30_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p30_table.setAlternatingRowColors(True)
        self.p30_table.verticalHeader().setVisible(False)
        self.p30_table.verticalHeader().setDefaultSectionSize(24)
        table_header = self.p30_table.horizontalHeader()
        table_header.setMinimumHeight(28)
        table_header.setSectionsMovable(True)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.p30_table.setColumnWidth(0, 48)
        self.p30_table.setColumnWidth(1, 90)
        self.p30_table.setColumnWidth(4, 105)
        self.p30_table.setColumnWidth(5, 135)
        self.p30_table.setSortingEnabled(True)
        self.p30_table.itemSelectionChanged.connect(self._p30_on_table_selection_changed)
        self.p30_body_splitter.addWidget(self.p30_table)

        plot_pane = QWidget()
        plot_layout = QVBoxLayout(plot_pane)
        plot_layout.setContentsMargins(8, 0, 0, 0)
        plot_layout.setSpacing(6)
        plot_title = QLabel('<b>Price vs Market Cap</b>')
        self.set_theme_role(plot_title, 'section_title')
        plot_layout.addWidget(plot_title)
        self.p30_plot_empty_lbl = QLabel('Fetch a price range to plot matching companies.')
        self.set_theme_role(self.p30_plot_empty_lbl, 'status_muted')
        self.p30_plot_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plot_layout.addWidget(self.p30_plot_empty_lbl)
        self.p30_plot = pg.PlotWidget(axisItems={
            'left': _P30MarketCapAxisItem(orientation='left'),
        })
        self.p30_plot.setMinimumWidth(360)
        self.p30_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if hasattr(self, 'style_plot_widget'):
            self.style_plot_widget(self.p30_plot, show_y_grid=True)
        self.p30_plot.showAxis('left', True)
        self.p30_plot.showAxis('right', False)
        self.p30_plot.setMouseEnabled(x=True, y=True)
        self.p30_plot.setMenuEnabled(False)
        self.p30_plot.getPlotItem().hideButtons()
        self.p30_plot.setLabel('bottom', 'Price ($)')
        self.p30_plot.setLabel('left', 'Market Cap')
        plot_layout.addWidget(self.p30_plot, 1)
        self.p30_body_splitter.addWidget(plot_pane)
        self.p30_body_splitter.setStretchFactor(0, 1)
        self.p30_body_splitter.setStretchFactor(1, 1)
        self.p30_body_splitter.setSizes([600, 600])
        panel_layout.addWidget(self.p30_body_splitter, 1)
        layout.addWidget(panel, 1)

    def _p30_price_input(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(0.01, 1_000_000.0)
        spin.setSingleStep(1.0)
        spin.setPrefix('$')
        spin.setGroupSeparatorShown(True)
        spin.setValue(value)
        spin.setMinimumWidth(125)
        return spin

    def _p30_validate_inputs(self) -> bool:
        minimum_price = float(self.p30_minimum_price_spin.value())
        maximum_price = float(self.p30_maximum_price_spin.value())
        if minimum_price > maximum_price:
            self.set_status_text(
                self.p30_status_lbl,
                'Minimum price cannot exceed maximum price.',
                status='negative',
            )
            return False
        return True

    def _p30_fetch(self, *_: Any) -> bool:
        """Fetch the current inclusive price range without overlapping requests."""
        if getattr(self, '_p30_fetching', False) or not self._p30_validate_inputs():
            return False
        minimum_price = float(self.p30_minimum_price_spin.value())
        maximum_price = float(self.p30_maximum_price_spin.value())
        worker = PriceScreenWorker(minimum_price, maximum_price, limit=_P30_RESULT_LIMIT)
        worker.error.connect(self._p30_on_error)
        self._p30_worker = worker
        launched = self._launch_worker(worker, self._p30_on_ready, '_p30_fetching')
        if not launched:
            self._p30_worker = None
            return False
        self._p30_set_controls_enabled(False)
        self.set_status_text(
            self.p30_status_lbl,
            f'Loading ${minimum_price:,.2f} to ${maximum_price:,.2f}...',
            status='muted',
        )
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, 'Loading Price market screen...', status='muted')
        return True

    def _p30_set_controls_enabled(self, enabled: bool) -> None:
        for widget_name in ('p30_minimum_price_spin', 'p30_maximum_price_spin', 'p30_fetch_btn'):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(bool(enabled))

    def _p30_on_ready(self, payload: Any) -> None:
        self._p30_fetching = False
        self._p30_worker = None
        self._p30_set_controls_enabled(True)
        data = payload if isinstance(payload, dict) else {}
        rows = [dict(row) for row in list(data.get('rows') or []) if isinstance(row, dict)]
        rows.sort(key=lambda row: (-self._p30_numeric_value(row.get('market_cap')), self._p30_numeric_value(row.get('price'))))
        self._p30_rows = rows[:_P30_RESULT_LIMIT]
        self._p30_render_rows()
        source = str(data.get('source') or 'Yahoo Finance').strip()
        as_of = str(data.get('as_of') or '').strip()
        try:
            candidate_count = max(0, int(data.get('candidate_count') or 0))
        except (TypeError, ValueError):
            candidate_count = 0
        if self._p30_rows:
            count_text = f'{len(self._p30_rows)} largest matching companies'
            if candidate_count:
                count_text = f'{count_text} from {candidate_count:,} candidates'
            status_text = f'Showing {count_text}'
            if source:
                status_text = f'{status_text} via {source}'
            if as_of:
                status_text = f'{status_text} at {as_of}'
            self.set_status_text(self.p30_status_lbl, status_text, status='positive')
        else:
            self.set_status_text(self.p30_status_lbl, 'No qualifying companies found in this price range.', status='warning')
        if hasattr(self, 'status_bar'):
            status = 'positive' if self._p30_rows else 'warning'
            self.set_status_text(self.status_bar, self.p30_status_lbl.text(), status=status)

    def _p30_on_error(self, message: Any) -> None:
        self._p30_fetching = False
        self._p30_worker = None
        self._p30_set_controls_enabled(True)
        error_text = str(message or 'Price screen unavailable').strip()
        self.set_status_text(self.p30_status_lbl, f'Error: {error_text}', status='negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Price screen failed: {error_text}', status='negative')

    def _p30_render_rows(self) -> None:
        if not self._p30_page_is_visible():
            return
        table = self.p30_table
        self._p30_render_generation += 1
        generation = self._p30_render_generation
        previous_updates = True
        previous_signals = False
        sorting_enabled = False
        prepared = False
        selected_ticker = ''
        selected_row = table.currentRow()
        if selected_row >= 0 and table.item(selected_row, 1) is not None:
            selected_ticker = table.item(selected_row, 1).text()

        def _prepare() -> None:
            nonlocal previous_updates, previous_signals, sorting_enabled, prepared
            previous_updates = table.updatesEnabled()
            previous_signals = table.blockSignals(True)
            sorting_enabled = bool(table.isSortingEnabled())
            prepared = True
            table.setSortingEnabled(False)
            table.setUpdatesEnabled(False)
            table.clearContents()
            table.setRowCount(len(self._p30_rows))

        def _apply(row_index: int, row: dict[str, Any]) -> None:
            rank = row_index + 1
            price = self._p30_numeric_value(row.get('price'))
            market_cap = self._p30_numeric_value(row.get('market_cap'))
            table.setItem(row_index, 0, self._p30_numeric_item(str(rank), rank))
            table.setItem(row_index, 1, QTableWidgetItem(str(row.get('ticker') or '')))
            table.setItem(row_index, 2, QTableWidgetItem(str(row.get('name') or row.get('ticker') or '')))
            table.setItem(row_index, 3, QTableWidgetItem(str(row.get('exchange') or 'N/A')))
            table.setItem(row_index, 4, self._p30_numeric_item(f'${price:,.2f}', price))
            table.setItem(row_index, 5, self._p30_numeric_item(self._p30_format_compact_currency(market_cap), market_cap))

        def _finish() -> None:
            if not prepared:
                return
            table.setUpdatesEnabled(previous_updates)
            if sorting_enabled:
                table.setSortingEnabled(True)
                table.sortItems(5, Qt.SortOrder.DescendingOrder)
            table.blockSignals(previous_signals)
            render_current = generation == self._p30_render_generation and self._p30_page_is_visible()
            if render_current:
                self._p30_render_plot()
            if selected_ticker:
                for row_index in range(table.rowCount()):
                    ticker_item = table.item(row_index, 1)
                    if ticker_item is not None and ticker_item.text() == selected_ticker:
                        table.selectRow(row_index)
                        break
            if previous_updates:
                table.viewport().update()

        if not self._p30_has_page_visibility_api():
            _prepare()
            try:
                for row_index, row in enumerate(self._p30_rows):
                    _apply(row_index, row)
            finally:
                _finish()
            return

        run_batched(
            self,
            'price-table',
            list(self._p30_rows),
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            is_current=lambda value: value == self._p30_render_generation,
            is_visible=self._p30_page_is_visible,
        )

    def _p30_on_show(self) -> None:
        """Render the latest cached screen once when returning to Price."""
        if self._p30_rows:
            self._p30_render_rows()

    @staticmethod
    def _p30_numeric_item(text: str, value: float) -> _P30NumericTableWidgetItem:
        item = _P30NumericTableWidgetItem(text)
        item.setData(_P30_NUMERIC_SORT_ROLE, float(value))
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        return item

    def _p30_render_plot(self) -> None:
        plot = self.p30_plot
        plot.clear()
        self._p30_scatter = None
        self._p30_selection_scatter = None
        self._p30_label_items = []
        self._p30_plot_points = []
        spots = []
        for row in self._p30_rows:
            ticker = str(row.get('ticker') or '').strip()
            price = self._p30_numeric_value(row.get('price'))
            market_cap = self._p30_numeric_value(row.get('market_cap'))
            if not ticker or price <= 0 or market_cap <= 0:
                continue
            log_market_cap = math.log10(market_cap)
            point_data = dict(row)
            spots.append({
                'pos': (price, log_market_cap),
                'size': 8,
                'brush': self.theme_brush('accent') if hasattr(self, 'theme_brush') else pg.mkBrush('#4ea1ff'),
                'pen': self.theme_pen('chart_reference', width=0.7) if hasattr(self, 'theme_pen') else pg.mkPen('#9aa4b2', width=0.7),
                'data': point_data,
            })
            self._p30_plot_points.append((price, log_market_cap, ticker))
        if not spots:
            self.p30_plot_empty_lbl.setText(
                'No qualifying companies found in this price range.'
                if self._p30_rows else 'Fetch a price range to plot matching companies.'
            )
            self.p30_plot_empty_lbl.setVisible(True)
            plot.setXRange(0, 1, padding=0)
            plot.setYRange(0, 1, padding=0)
            return
        self.p30_plot_empty_lbl.setVisible(False)
        scatter = pg.ScatterPlotItem(
            spots=spots,
            hoverable=True,
            tip=lambda x, y, data: self._p30_point_tooltip(data),
        )
        scatter.sigClicked.connect(self._p30_on_scatter_clicked)
        plot.addItem(scatter)
        self._p30_scatter = scatter
        label_color = self.theme_color('text_primary') if hasattr(self, 'theme_color') else '#e5e7eb'
        def _apply_label(_index: int, point: tuple[float, float, str]) -> None:
            price, log_market_cap, ticker = point
            label = pg.TextItem(text=ticker, color=label_color, anchor=(0.5, 1.15))
            label.setPos(price, log_market_cap)
            label.setZValue(5)
            plot.addItem(label)
            self._p30_label_items.append(label)
        if self._p30_has_page_visibility_api():
            run_batched(
                self,
                'price-labels',
                list(self._p30_plot_points),
                _apply_label,
                generation=self._p30_render_generation,
                is_current=lambda value: value == self._p30_render_generation,
                is_visible=self._p30_page_is_visible,
                max_items=LABEL_MAX_ITEMS,
            )
        else:
            for point_index, point in enumerate(self._p30_plot_points):
                _apply_label(point_index, point)
        self._p30_selection_scatter = pg.ScatterPlotItem(
            size=15,
            brush=pg.mkBrush(0, 0, 0, 0),
            pen=self.theme_pen('warning', width=2.0) if hasattr(self, 'theme_pen') else pg.mkPen('#f5c542', width=2.0),
        )
        self._p30_selection_scatter.setZValue(10)
        plot.addItem(self._p30_selection_scatter)
        xs = [point[0] for point in self._p30_plot_points]
        ys = [point[1] for point in self._p30_plot_points]
        x_padding = max((max(xs) - min(xs)) * 0.06, 0.5)
        y_padding = max((max(ys) - min(ys)) * 0.10, 0.08)
        plot.setXRange(min(xs) - x_padding, max(xs) + x_padding, padding=0)
        plot.setYRange(min(ys) - y_padding, max(ys) + y_padding, padding=0)

    def _p30_point_tooltip(self, data: Any) -> str:
        row = data if isinstance(data, dict) else {}
        ticker = str(row.get('ticker') or 'N/A')
        company = str(row.get('name') or ticker)
        price = self._p30_numeric_value(row.get('price'))
        market_cap = self._p30_numeric_value(row.get('market_cap'))
        return (
            f'{ticker} — {company}\n'
            f'Price: ${price:,.2f}\n'
            f'Market Cap: {self._p30_format_compact_currency(market_cap)}'
        )

    def _p30_on_scatter_clicked(self, _: Any, points: Any, *args: Any) -> None:
        point_list = list(points or [])
        if not point_list:
            return
        data = point_list[0].data()
        ticker = str(data.get('ticker') or '') if isinstance(data, dict) else ''
        if not ticker:
            return
        for row_index in range(self.p30_table.rowCount()):
            item = self.p30_table.item(row_index, 1)
            if item is not None and item.text() == ticker:
                self.p30_table.selectRow(row_index)
                self.p30_table.scrollToItem(item)
                return

    def _p30_on_table_selection_changed(self) -> None:
        selection = getattr(self, '_p30_selection_scatter', None)
        if selection is None:
            return
        selected_ranges = self.p30_table.selectedRanges()
        if not selected_ranges:
            selection.setData(spots=[])
            return
        row_index = selected_ranges[0].topRow()
        ticker_item = self.p30_table.item(row_index, 1)
        ticker = ticker_item.text() if ticker_item is not None else ''
        point = next((item for item in self._p30_plot_points if item[2] == ticker), None)
        if point is None:
            selection.setData(spots=[])
            return
        selection.setData(spots=[{'pos': (point[0], point[1]), 'data': ticker}])

    @staticmethod
    def _p30_numeric_value(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return numeric if math.isfinite(numeric) else 0.0

    @staticmethod
    def _p30_format_compact_currency(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        sign = '-' if numeric < 0 else ''
        numeric = abs(numeric)
        for divisor, suffix in (
            (1_000_000_000_000, 'T'),
            (1_000_000_000, 'B'),
            (1_000_000, 'M'),
            (1_000, 'K'),
        ):
            if numeric >= divisor:
                return f'{sign}${numeric / divisor:,.2f}{suffix}'
        return f'{sign}${numeric:,.2f}'
