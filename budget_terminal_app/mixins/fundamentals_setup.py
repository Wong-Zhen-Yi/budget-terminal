from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.paths import user_data_path
from budget_terminal_app.workers.fundamentals import FundamentalsWorker


class FundamentalsSetupMixin:
    _P2_CONFIG_PATH = user_data_path('fundamentals_config.json')
    _P2_CUSTOM_FAMILIES = (
        ('financials', 'Income Statement'),
        ('cashflow', 'Cash Flow'),
        ('balance_sheet', 'Balance Sheet'),
    )

    def _p2_legacy_last_ticker(self) -> str:
        """Read the historical standalone Fundamentals config as a migration fallback."""
        try:
            with self._P2_CONFIG_PATH.open() as handle:
                payload = json.load(handle)
        except Exception:
            return ''
        return str((payload or {}).get('last_ticker', '') or '').upper().strip()

    def _p2_current_ticker(self) -> str:
        """Return the active Fundamentals ticker key for persisted custom selections."""
        if isinstance(getattr(self, 'p2_current_data', None), dict):
            ticker = str(self.p2_current_data.get('ticker', '') or '').upper().strip()
            if ticker:
                return ticker
        if hasattr(self, 'p2_ticker_input'):
            return str(self.p2_ticker_input.text() or '').upper().strip()
        return str(getattr(self, 'p2_last_ticker', '') or '').upper().strip()

    def _p2_settings_payload(self) -> dict[str, Any]:
        """Build the persisted Fundamentals page settings payload."""
        return {
            'last_ticker': str(self.p2_ticker_input.text() if hasattr(self, 'p2_ticker_input') else getattr(self, 'p2_last_ticker', '')).upper().strip(),
            'selected_configuration': str(
                getattr(self, 'p2_selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
                or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
            ).strip().lower(),
            'custom_selections_by_ticker': dict(getattr(self, 'p2_custom_selections_by_ticker', {})),
        }

    def _p2_persist_settings(self) -> None:
        """Persist Fundamentals page settings to the main user-data document."""
        self.fundamentals_page_state = save_fundamentals_page_settings(self._p2_settings_payload())

    def init_page2(self, layout: Any) -> None:
        """Build the Fundamentals page UI."""
        self._p2_request_seq = 0
        self._p2_active_request_id = 0
        self._p2_request_contexts = {}
        self._p2_checklist_sync_guard = False
        self.p2_website_url = ''
        self.p2_ir_url = ''
        self.fundamentals_page_state = getattr(self, 'fundamentals_page_state', load_fundamentals_page_settings())
        migrated_ticker = self._p2_legacy_last_ticker()
        if (not self.fundamentals_page_state.get('last_ticker')) and migrated_ticker:
            self.fundamentals_page_state = save_fundamentals_page_settings({
                **self.fundamentals_page_state,
                'last_ticker': migrated_ticker,
            })
        self.p2_selected_configuration = str(
            self.fundamentals_page_state.get('selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
            or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
        ).strip().lower()
        if self.p2_selected_configuration not in {'default', 'custom'}:
            self.p2_selected_configuration = DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
        self.p2_custom_selections_by_ticker = dict(
            self.fundamentals_page_state.get('custom_selections_by_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['custom_selections_by_ticker'])
        )
        self.p2_last_ticker = str(self.fundamentals_page_state.get('last_ticker', '') or '').upper().strip()
        self.p2_custom_available_rows = {family: [] for family, _ in self._P2_CUSTOM_FAMILIES}
        self.p2_custom_checkboxes = {family: {} for family, _ in self._P2_CUSTOM_FAMILIES}
        self.p2_custom_panel_descriptors = []
        self.p2_custom_panel_widgets = []

        search_row = QHBoxLayout()
        self.p2_ticker_input = QLineEdit(self.p2_last_ticker)
        self.p2_ticker_input.setPlaceholderText('Enter any ticker (e.g. NVDA, MSFT, META)')
        self.p2_ticker_input.setFixedWidth(240)
        self.p2_ticker_input.returnPressed.connect(self.analyze_stock_p2)
        self.p2_analyze_btn = QPushButton('Analyze')
        self.p2_analyze_btn.clicked.connect(self.analyze_stock_p2)
        self.p2_status_lbl = QLabel('Enter a ticker above to begin the analysis.')
        self.set_theme_role(self.p2_status_lbl, 'status_muted')
        search_row.addWidget(self.p2_ticker_input)
        search_row.addWidget(self.p2_analyze_btn)
        search_row.addStretch()
        layout.addLayout(search_row)
        layout.addWidget(self.p2_status_lbl)

        self.p2_content_widget = QWidget()
        self.p2_content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.p2_content_layout = QVBoxLayout(self.p2_content_widget)
        self.p2_content_layout.setSpacing(4)
        self.p2_content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.p2_content_widget, 1)

        self.p2_top_frame = QFrame()
        self.p2_top_frame.setFixedHeight(36)
        self.set_theme_role(self.p2_top_frame, 'panel')
        top_row = QHBoxLayout(self.p2_top_frame)
        top_row.setContentsMargins(10, 0, 0, 10)
        top_row.setSpacing(12)
        self.p2_name_lbl = QLabel('—')
        self.p2_info_lbl = QLabel('—')
        top_row.addWidget(self.p2_name_lbl)
        top_row.addWidget(self.p2_info_lbl)
        self.p2_website_btn = QPushButton('Website')
        self.p2_website_btn.setFixedHeight(22)
        self.set_theme_variant(self.p2_website_btn, 'accent')
        self.p2_website_btn.setVisible(False)
        self.p2_website_btn.clicked.connect(self._open_p2_website)
        self.p2_ir_btn = QPushButton('IR')
        self.p2_ir_btn.setFixedHeight(22)
        self.set_theme_variant(self.p2_ir_btn, 'accent')
        self.p2_ir_btn.setVisible(False)
        self.p2_ir_btn.clicked.connect(self._open_p2_ir)
        top_row.addWidget(self.p2_website_btn)
        top_row.addWidget(self.p2_ir_btn)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f'color: {self.theme_color("panel_border")};')
        top_row.addWidget(divider)
        metric_defs = [
            ('P/E', 'pe'),
            ('Fwd P/E', 'fpe'),
            ('P/S', 'ps'),
            ('PEG', 'peg'),
            ('FCF Mgn', 'fcf_margin'),
            ('EV/Rev', 'ev_rev'),
            ('EV/EBITDA', 'ev_ebitda'),
            ('Net Cash', 'net_cash'),
            ('Beta', 'beta'),
            ('Mkt Cap', 'mktcap'),
        ]
        self.p2_metric_vals = {}
        for label_text, key in metric_defs:
            pair = QHBoxLayout()
            pair.setSpacing(4)
            title_label = QLabel(f'{label_text}:')
            title_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
            value_label = QLabel('—')
            pair.addWidget(title_label)
            pair.addWidget(value_label)
            top_row.addLayout(pair)
            self.p2_metric_vals[key] = value_label
        top_row.addStretch()
        self.p2_content_layout.addWidget(self.p2_top_frame)

        self.p2_period_widget = QWidget()
        self.p2_period_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.p2_period_widget.setMinimumHeight(36)
        period_row = QHBoxLayout(self.p2_period_widget)
        period_row.setContentsMargins(14, 6, 12, 6)
        period_row.setSpacing(0)
        self.p2_annual_btn = QPushButton('Annual')
        self.p2_quarterly_btn = QPushButton('Quarterly')
        for button in (self.p2_annual_btn, self.p2_quarterly_btn):
            button.setCheckable(True)
            button.setFixedHeight(24)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(74)
            button.setStyleSheet('padding-left: 3px; padding-right: 3px;')
        self.p2_annual_btn.setChecked(True)
        self.p2_annual_btn.clicked.connect(partial(self._set_p2_period, 'annual'))
        self.p2_quarterly_btn.clicked.connect(partial(self._set_p2_period, 'quarterly'))
        period_row.addWidget(self.p2_annual_btn)
        period_row.addSpacing(8)
        period_row.addWidget(self.p2_quarterly_btn)
        period_row.addSpacing(18)
        config_label = QLabel('Configuration')
        self.set_theme_role(config_label, 'muted')
        period_row.addWidget(config_label)
        period_row.addSpacing(8)
        self.p2_configuration_combo = QComboBox()
        self.p2_configuration_combo.addItem('Default', 'default')
        self.p2_configuration_combo.addItem('Custom', 'custom')
        self.p2_configuration_combo.currentIndexChanged.connect(self._p2_on_configuration_changed)
        self.p2_configuration_combo.setMinimumWidth(140)
        period_row.addWidget(self.p2_configuration_combo)
        period_row.addStretch()
        self.p2_content_layout.addWidget(self.p2_period_widget)

        self.p2_workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p2_workspace_splitter.setChildrenCollapsible(False)
        self.p2_workspace_stack = QStackedWidget()
        self.p2_workspace_splitter.addWidget(self.p2_workspace_stack)

        self.p2_default_workspace = QWidget()
        default_layout = QVBoxLayout(self.p2_default_workspace)
        default_layout.setContentsMargins(0, 0, 0, 0)
        default_layout.setSpacing(0)
        self.p2_charts_box = QGroupBox('Financial Overview')
        self.set_theme_role(self.p2_charts_box, 'panel')
        self.p2_charts_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.p2_charts_grid = QGridLayout(self.p2_charts_box)
        self.p2_charts_grid.setContentsMargins(12, 18, 12, 12)
        self.p2_charts_grid.setSpacing(12)
        self.p2_simple_charts = []
        self.p2_simple_titles = []
        self.p2_simple_legend_bars = []
        self.p2_chart_frames = []
        for title in ['Revenue', 'Net Income', 'Cash Flow', 'Shares Outstanding', 'Cash & Total Debt', 'Operating Expenses']:
            card = self._p2_create_chart_card(title)
            self.p2_chart_frames.append(card['frame'])
            self.p2_simple_titles.append(card['title'])
            self.p2_simple_legend_bars.append(card['legend'])
            self.p2_simple_charts.append(card['plot'])
        default_layout.addWidget(self.p2_charts_box, 1)
        self.p2_workspace_stack.addWidget(self.p2_default_workspace)

        self.p2_custom_workspace = QWidget()
        custom_layout = QVBoxLayout(self.p2_custom_workspace)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(0)
        self.p2_custom_box = QGroupBox('Custom Overview')
        self.set_theme_role(self.p2_custom_box, 'panel')
        custom_box_layout = QVBoxLayout(self.p2_custom_box)
        custom_box_layout.setContentsMargins(12, 18, 12, 12)
        custom_box_layout.setSpacing(8)
        self.p2_custom_scroll = QScrollArea()
        self.p2_custom_scroll.setWidgetResizable(True)
        self.p2_custom_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p2_custom_grid_widget = QWidget()
        self.p2_custom_grid_layout = QGridLayout(self.p2_custom_grid_widget)
        self.p2_custom_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.p2_custom_grid_layout.setHorizontalSpacing(12)
        self.p2_custom_grid_layout.setVerticalSpacing(12)
        self.p2_custom_scroll.setWidget(self.p2_custom_grid_widget)
        custom_box_layout.addWidget(self.p2_custom_scroll, 1)
        custom_layout.addWidget(self.p2_custom_box, 1)
        self.p2_workspace_stack.addWidget(self.p2_custom_workspace)

        self.p2_custom_editor_frame = QFrame()
        self.set_theme_role(self.p2_custom_editor_frame, 'panel')
        self.p2_custom_editor_frame.setMinimumWidth(320)
        self.p2_custom_editor_frame.setMaximumWidth(360)
        editor_layout = QVBoxLayout(self.p2_custom_editor_frame)
        editor_layout.setContentsMargins(14, 14, 14, 14)
        editor_layout.setSpacing(10)
        editor_title = QLabel('Available Data')
        self.set_theme_role(editor_title, 'section_title')
        self.p2_custom_editor_hint = QLabel('Load a ticker to see available data.')
        self.p2_custom_editor_hint.setWordWrap(True)
        self.set_theme_role(self.p2_custom_editor_hint, 'muted')
        self.p2_custom_editor_scroll = QScrollArea()
        self.p2_custom_editor_scroll.setWidgetResizable(True)
        self.p2_custom_editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p2_custom_editor_content = QWidget()
        self.p2_custom_editor_content_layout = QVBoxLayout(self.p2_custom_editor_content)
        self.p2_custom_editor_content_layout.setContentsMargins(0, 0, 0, 0)
        self.p2_custom_editor_content_layout.setSpacing(10)
        self.p2_custom_editor_scroll.setWidget(self.p2_custom_editor_content)
        editor_layout.addWidget(editor_title)
        editor_layout.addWidget(self.p2_custom_editor_hint)
        editor_layout.addWidget(self.p2_custom_editor_scroll, 1)
        self.p2_workspace_splitter.addWidget(self.p2_custom_editor_frame)
        self.p2_workspace_splitter.setStretchFactor(0, 5)
        self.p2_workspace_splitter.setStretchFactor(1, 2)
        self.p2_content_layout.addWidget(self.p2_workspace_splitter, 1)

        combo_index = self.p2_configuration_combo.findData(self.p2_selected_configuration)
        self.p2_configuration_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        self._p2_rebuild_custom_checklist()
        self._p2_rebuild_custom_panels()
        self._apply_fundamentals_theme()
        self._p2_relayout_charts()

    def _p2_create_chart_card(self, title: str, *, include_status: bool=False) -> dict[str, Any]:
        """Create one reusable Fundamentals chart card."""
        frame = QFrame()
        self.set_theme_role(frame, 'panel')
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_label = QLabel(title)
        legend_bar = QWidget()
        legend_bar.setStyleSheet('background: transparent;')
        legend_layout = QHBoxLayout(legend_bar)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.setSpacing(6)
        title_row.addWidget(title_label)
        title_row.addStretch()
        title_row.addWidget(legend_bar)
        plot_widget = pg.PlotWidget(axisItems={'left': FmtAxisItem(orientation='left')})
        plot_widget.getPlotItem().hideButtons()
        plot_widget.getPlotItem().setMenuEnabled(False)
        plot_widget.setMouseEnabled(x=False, y=False)
        plot_widget.showGrid(x=False, y=True, alpha=0.15)
        self.style_plot_widget(plot_widget)
        frame_layout.addLayout(title_row)
        status_label = QLabel('')
        status_label.setWordWrap(True)
        self.set_theme_role(status_label, 'muted')
        status_label.setVisible(False)
        if include_status:
            frame_layout.addWidget(status_label)
        frame_layout.addWidget(plot_widget)
        return {
            'frame': frame,
            'title': title_label,
            'legend': legend_bar,
            'plot': plot_widget,
            'status': status_label,
        }

    def _p2_current_custom_selection(self, ticker: Any=None) -> dict[str, list[str]]:
        """Return the normalized per-family selection for one ticker."""
        ticker_key = str(ticker or self._p2_current_ticker() or '').upper().strip()
        raw = {}
        if ticker_key:
            raw = dict(getattr(self, 'p2_custom_selections_by_ticker', {}).get(ticker_key, {}))
        return {
            'financials': list(raw.get('financials', [])) if isinstance(raw.get('financials', []), list) else [],
            'cashflow': list(raw.get('cashflow', [])) if isinstance(raw.get('cashflow', []), list) else [],
            'balance_sheet': list(raw.get('balance_sheet', [])) if isinstance(raw.get('balance_sheet', []), list) else [],
        }

    def _p2_store_custom_selection(self, selection: Any, *, ticker: Any=None) -> None:
        """Persist one ticker's checklist selection into the in-memory Fundamentals state."""
        ticker_key = str(ticker or self._p2_current_ticker() or '').upper().strip()
        if not ticker_key:
            return
        cleaned = {
            family: list(selection.get(family, [])) if isinstance(selection.get(family, []), list) else []
            for family, _ in self._P2_CUSTOM_FAMILIES
        }
        if any(cleaned.values()):
            self.p2_custom_selections_by_ticker[ticker_key] = cleaned
        else:
            self.p2_custom_selections_by_ticker.pop(ticker_key, None)

    def _p2_rebuild_custom_checklist(self) -> None:
        """Rebuild the right-side checklist from the currently loaded ticker data."""
        while self.p2_custom_editor_content_layout.count():
            item = self.p2_custom_editor_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.p2_custom_checkboxes = {family: {} for family, _ in self._P2_CUSTOM_FAMILIES}
        self.p2_custom_available_rows = {family: [] for family, _ in self._P2_CUSTOM_FAMILIES}
        ticker = self._p2_current_ticker()
        if not isinstance(self.p2_current_data, dict) or not ticker:
            prompt = QLabel('Load a ticker to see available data.')
            prompt.setWordWrap(True)
            self.set_theme_role(prompt, 'muted')
            self.p2_custom_editor_content_layout.addWidget(prompt)
            self.p2_custom_editor_content_layout.addStretch(1)
            self.p2_custom_editor_hint.setText('Load a ticker to see available data.')
            self._p2_update_custom_panel_descriptors()
            return
        selection = self._p2_current_custom_selection(ticker)
        selection_changed = False
        has_rows = False
        self._p2_checklist_sync_guard = True
        try:
            for family, label in self._P2_CUSTOM_FAMILIES:
                rows = self._p2_statement_rows_for_family(self.p2_current_data, family)
                self.p2_custom_available_rows[family] = list(rows)
                if not rows:
                    continue
                has_rows = True
                cleaned_rows = [row for row in selection.get(family, []) if row in rows]
                if cleaned_rows != selection.get(family, []):
                    selection[family] = cleaned_rows
                    selection_changed = True
                group_box = QGroupBox(label)
                self.set_theme_role(group_box, 'panel')
                group_layout = QVBoxLayout(group_box)
                group_layout.setContentsMargins(10, 12, 10, 10)
                group_layout.setSpacing(6)
                selected_rows = set(selection.get(family, []))
                for row in rows:
                    checkbox = QCheckBox(row)
                    checkbox.setChecked(row in selected_rows)
                    checkbox.toggled.connect(partial(self._p2_on_custom_metric_toggled, family, row))
                    self.p2_custom_checkboxes[family][row] = checkbox
                    group_layout.addWidget(checkbox)
                self.p2_custom_editor_content_layout.addWidget(group_box)
            if not has_rows:
                prompt = QLabel('No fundamentals statement rows are available for this ticker.')
                prompt.setWordWrap(True)
                self.set_theme_role(prompt, 'muted')
                self.p2_custom_editor_content_layout.addWidget(prompt)
            self.p2_custom_editor_content_layout.addStretch(1)
        finally:
            self._p2_checklist_sync_guard = False
        self.p2_custom_editor_hint.setText('Tick data points to show or hide them in the Custom view.')
        if selection_changed:
            self._p2_store_custom_selection(selection, ticker=ticker)
            self._p2_persist_settings()
        self._p2_update_custom_panel_descriptors()

    def _p2_update_custom_panel_descriptors(self) -> None:
        """Flatten the current ticker selection into renderable custom chart descriptors."""
        ticker = self._p2_current_ticker()
        selection = self._p2_current_custom_selection(ticker)
        descriptors = []
        for family, _ in self._P2_CUSTOM_FAMILIES:
            selected_rows = set(selection.get(family, []))
            for row in self.p2_custom_available_rows.get(family, []):
                if row in selected_rows:
                    descriptors.append({'family': family, 'row': row, 'title': row})
        self.p2_custom_panel_descriptors = descriptors

    def _p2_rebuild_custom_panels(self) -> None:
        """Recreate the visible custom chart cards from the current ticker selection."""
        self.p2_custom_panel_widgets = []
        while self.p2_custom_grid_layout.count():
            item = self.p2_custom_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if not self.p2_custom_panel_descriptors:
            message = 'Load a ticker to see available data.' if self.p2_current_data is None else 'Tick data points on the right to add them to Custom.'
            empty_label = QLabel(message)
            empty_label.setWordWrap(True)
            self.set_theme_role(empty_label, 'muted')
            self.p2_custom_grid_layout.addWidget(empty_label, 0, 0)
            return
        for descriptor in self.p2_custom_panel_descriptors:
            card = self._p2_create_chart_card(str(descriptor.get('title', '') or 'Custom'), include_status=True)
            self.p2_custom_panel_widgets.append(card)
        self._p2_relayout_custom_panels()
        if self.p2_current_data is not None:
            self._p2_render_custom_charts(self.p2_current_data, self._p2_period())

    def _p2_relayout_custom_panels(self) -> None:
        """Lay out custom panels as one or two columns depending on available width."""
        while self.p2_custom_grid_layout.count():
            item = self.p2_custom_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.p2_custom_grid_widget)
        if not self.p2_custom_panel_widgets:
            if self.p2_custom_grid_layout.count() == 0:
                message = 'Load a ticker to see available data.' if self.p2_current_data is None else 'Tick data points on the right to add them to Custom.'
                empty_label = QLabel(message)
                empty_label.setWordWrap(True)
                self.set_theme_role(empty_label, 'muted')
                self.p2_custom_grid_layout.addWidget(empty_label, 0, 0)
            return
        available_width = max(self.p2_custom_box.width(), self.page2.contentsRect().width() - 420 if hasattr(self, 'page2') else 0)
        columns = 2 if available_width >= 980 else 1
        for index, widget_info in enumerate(self.p2_custom_panel_widgets):
            frame = widget_info['frame']
            chart_height = 228 if columns == 2 else 246
            plot_height = 150 if columns == 2 else 164
            frame.setFixedHeight(chart_height)
            frame.layout().setContentsMargins(8, 6, 8, 6)
            widget_info['plot'].setMinimumHeight(plot_height)
            widget_info['plot'].setMaximumHeight(plot_height)
            self.p2_custom_grid_layout.addWidget(frame, index // columns, index % columns)
        for column in range(columns):
            self.p2_custom_grid_layout.setColumnStretch(column, 1)

    def _p2_relayout_charts(self) -> None:
        """Resize and reflow the Default and Custom Fundamentals grids."""
        if hasattr(self, 'p2_charts_grid'):
            frames = getattr(self, 'p2_chart_frames', [])
            if frames:
                page_width = self.page2.contentsRect().width() if hasattr(self, 'page2') else 0
                available_width = max(self.p2_charts_box.width(), page_width - 20)
                content_height = self.p2_content_widget.contentsRect().height() if hasattr(self, 'p2_content_widget') else 0
                spacing = self.p2_content_layout.spacing() if hasattr(self, 'p2_content_layout') else 0
                controls_height = self.p2_top_frame.height() + self.p2_period_widget.height() + spacing * 2
                available_height = max(240, content_height - controls_height)
                columns = 3 if available_width >= 1200 else 2
                rows = max(1, math.ceil(len(frames) / columns))
                spacing = 12 if available_width >= 1200 and available_height >= 700 else 8
                chrome_height = 40
                min_chart_height = 160 if columns == 3 else 140
                grid_height = max(min_chart_height * rows + max(0, rows - 1) * spacing, available_height - chrome_height)
                chart_height = max(min_chart_height, int((grid_height - max(0, rows - 1) * spacing) / rows))
                plot_height = max(96, chart_height - 52)
                box_height = chrome_height + rows * chart_height + max(0, rows - 1) * spacing
                self.p2_charts_grid.setHorizontalSpacing(spacing)
                self.p2_charts_grid.setVerticalSpacing(spacing)
                self.p2_charts_box.setMinimumHeight(box_height)
                while self.p2_charts_grid.count():
                    item = self.p2_charts_grid.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.setParent(self.p2_charts_box)
                for index, frame in enumerate(frames):
                    frame.setFixedHeight(chart_height)
                    frame.layout().setContentsMargins(8, 6, 8, 6)
                    self.p2_simple_charts[index].setMinimumHeight(plot_height)
                    self.p2_simple_charts[index].setMaximumHeight(plot_height)
                    self.p2_charts_grid.addWidget(frame, index // columns, index % columns)
                for column in range(columns):
                    self.p2_charts_grid.setColumnStretch(column, 1)
        if hasattr(self, 'p2_custom_grid_layout'):
            self._p2_relayout_custom_panels()

    def _p2_status_text_for_payload(self, data: Any, *, restored: bool=False) -> str:
        """Build the user-facing status text for a Fundamentals payload."""
        payload = data if isinstance(data, dict) else {}
        ticker = str(payload.get('ticker', '') or self.p2_ticker_input.text() or '').upper().strip()
        source = 'Alpha Vantage' if payload.get('av_used') else 'yfinance'
        if restored and ticker:
            return f'Restored last session for {ticker} | source: {source}'
        if ticker:
            return f'{ticker}  |  source: {source}'
        return f'Source: {source}'

    def _p2_session_snapshot(self) -> dict[str, Any] | None:
        """Return the current Fundamentals workspace snapshot when data is loaded."""
        if not isinstance(getattr(self, 'p2_current_data', None), dict):
            return None
        ticker = str(self.p2_current_data.get('ticker', '') or '').upper().strip()
        if not ticker:
            return None
        return {
            'ticker': ticker,
            'period': self._p2_period() if hasattr(self, 'p2_annual_btn') else 'annual',
            'configuration': str(getattr(self, 'p2_selected_configuration', 'default') or 'default').strip().lower(),
            'data': serialize_session_value(self.p2_current_data),
        }

    def _p2_save_session_snapshot(self, *, immediate: bool=False) -> None:
        """Persist the latest Fundamentals workspace snapshot."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('fundamentals', self._p2_session_snapshot(), immediate=immediate)

    def _p2_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Restore the Fundamentals workspace from a cached session snapshot."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        if ticker:
            self.p2_ticker_input.setText(ticker)
        configuration = str(payload.get('configuration', '') or '').strip().lower()
        if configuration in {'default', 'custom'}:
            self.p2_selected_configuration = configuration
        restored_data = deserialize_session_value(payload.get('data'))
        if not isinstance(restored_data, dict):
            return False
        self.update_page2(
            restored_data,
            update_collection_info=False,
            status_text=self._p2_status_text_for_payload(restored_data, restored=True),
        )
        period = str(payload.get('period', 'annual') or 'annual').strip().lower()
        if period in {'annual', 'quarterly'}:
            self._set_p2_period(period)
        return True

    def _p2_restore_startup_session(self, snapshot: Any) -> None:
        """Hydrate Fundamentals from the last session, then refresh it in the background."""
        restored = self._p2_restore_session_snapshot(snapshot)
        ticker = str(getattr(self, 'p2_ticker_input', None).text() if hasattr(self, 'p2_ticker_input') else '').upper().strip()
        if restored and ticker:
            self.analyze_stock_p2(update_collection_info=False)

    def _p2_apply_runtime_state(self) -> None:
        """Apply the persisted Fundamentals state to the live page widgets."""
        state = getattr(self, 'fundamentals_page_state', load_fundamentals_page_settings())
        self.p2_selected_configuration = str(
            state.get('selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
            or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
        ).strip().lower()
        if self.p2_selected_configuration not in {'default', 'custom'}:
            self.p2_selected_configuration = DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
        self.p2_custom_selections_by_ticker = dict(
            state.get('custom_selections_by_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['custom_selections_by_ticker'])
        )
        self.p2_last_ticker = str(state.get('last_ticker', '') or '').upper().strip()
        if hasattr(self, 'p2_ticker_input'):
            self.p2_ticker_input.setText(self.p2_last_ticker)
        if hasattr(self, 'p2_configuration_combo'):
            index = self.p2_configuration_combo.findData(self.p2_selected_configuration)
            self.p2_configuration_combo.blockSignals(True)
            self.p2_configuration_combo.setCurrentIndex(index if index >= 0 else 0)
            self.p2_configuration_combo.blockSignals(False)
        self._p2_rebuild_custom_checklist()
        self._p2_rebuild_custom_panels()
        self._p2_refresh_workspace_mode()
        if self.p2_current_data is not None:
            self._p2_render_active_configuration()
        self._p2_relayout_charts()

    def analyze_stock_p2(self, *_: Any, update_collection_info: bool=True) -> None:
        """Load Fundamentals for the requested ticker."""
        ticker = self.p2_ticker_input.text().upper().strip()
        if not ticker:
            return
        self.p2_last_ticker = ticker
        self._p2_persist_settings()
        self._p2_request_seq += 1
        request_id = self._p2_request_seq
        self._p2_active_request_id = request_id
        self._p2_request_contexts[request_id] = {
            'update_collection_info': bool(update_collection_info),
        }
        self.p2_analyze_btn.setEnabled(False)
        self.set_status_text(self.p2_status_lbl, f'Loading {ticker}...', status='warning')
        self.p2_fund_worker = FundamentalsWorker(ticker)
        self.p2_fund_thread = QThread()
        self.p2_fund_worker.moveToThread(self.p2_fund_thread)
        self.p2_fund_thread.started.connect(self.p2_fund_worker.run)
        self.p2_fund_worker.finished.connect(lambda data, req=request_id: self._p2_handle_result(req, data))
        self.p2_fund_worker.finished.connect(self.p2_fund_thread.quit)
        self.p2_fund_worker.error.connect(lambda msg, req=request_id: self._page2_error(req, msg))
        self.p2_fund_worker.error.connect(self.p2_fund_thread.quit)
        self.p2_fund_thread.start()

    def _p2_handle_result(self, request_id: int, data: Any) -> None:
        """Apply one Fundamentals response only when it is still current."""
        context = self._p2_request_contexts.pop(request_id, {})
        if request_id != getattr(self, '_p2_active_request_id', 0):
            return
        self.update_page2(
            data,
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _page2_error(self, request_id: Any, msg: Any=None) -> None:
        """Handle Fundamentals fetch errors."""
        error_text = msg if msg is not None else request_id
        current_request_id = request_id if msg is not None else getattr(self, '_p2_active_request_id', 0)
        try:
            numeric_request_id = int(current_request_id)
        except (TypeError, ValueError):
            numeric_request_id = int(getattr(self, '_p2_active_request_id', 0) or 0)
        self._p2_request_contexts.pop(numeric_request_id, None)
        if numeric_request_id != getattr(self, '_p2_active_request_id', 0):
            return
        self.set_status_text(self.p2_status_lbl, f'Error: {error_text}', status='negative')
        self.p2_analyze_btn.setEnabled(True)

    def _open_p2_website(self, *_: Any) -> None:
        """Open the company's website when available."""
        if self.p2_website_url:
            webbrowser.open(self.p2_website_url)

    def _open_p2_ir(self, *_: Any) -> None:
        """Open the investor-relations page when available."""
        if self.p2_ir_url:
            webbrowser.open(self.p2_ir_url)

    def _p2_period(self) -> str:
        """Return the active statement period."""
        return 'annual' if self.p2_annual_btn.isChecked() else 'quarterly'

    def _set_p2_period(self, period: Any, *_: Any) -> None:
        """Switch the visible Fundamentals period."""
        self.p2_annual_btn.setChecked(period == 'annual')
        self.p2_quarterly_btn.setChecked(period == 'quarterly')
        self._on_period_toggle()

    def _p2_refresh_workspace_mode(self) -> None:
        """Toggle the visible workspace and checklist editor for the selected configuration."""
        is_custom = str(getattr(self, 'p2_selected_configuration', 'default') or 'default').strip().lower() == 'custom'
        self.p2_workspace_stack.setCurrentWidget(self.p2_custom_workspace if is_custom else self.p2_default_workspace)
        self.p2_custom_editor_frame.setVisible(is_custom)
        if is_custom:
            self.p2_workspace_splitter.setSizes([900, 340])
        else:
            self.p2_workspace_splitter.setSizes([1, 0])

    def _p2_render_active_configuration(self) -> None:
        """Render the currently selected Fundamentals configuration."""
        if self.p2_current_data is None:
            return
        self._p2_rebuild_custom_checklist()
        self._p2_rebuild_custom_panels()
        period = self._p2_period()
        self._render_simple_charts(self.p2_current_data, period)
        self._p2_render_custom_charts(self.p2_current_data, period)

    def _on_period_toggle(self) -> None:
        """Handle Annual / Quarterly toggles."""
        if self.p2_current_data is None:
            return
        self._p2_render_active_configuration()
        self._p2_relayout_charts()
        self._p2_save_session_snapshot()

    def _p2_on_configuration_changed(self, _: int) -> None:
        """Persist and apply a configuration switch between Default and Custom."""
        config = str(self.p2_configuration_combo.currentData() or 'default').strip().lower()
        self.p2_selected_configuration = config if config in {'default', 'custom'} else 'default'
        self._p2_refresh_workspace_mode()
        self._p2_persist_settings()
        if self.p2_current_data is not None:
            self._p2_render_active_configuration()
        self._p2_save_session_snapshot()

    def _p2_on_custom_metric_toggled(self, family: str, row: str, checked: bool) -> None:
        """Handle ticking or unticking one raw statement row in the Custom checklist."""
        if self._p2_checklist_sync_guard:
            return
        ticker = self._p2_current_ticker()
        if not ticker:
            return
        selection = self._p2_current_custom_selection(ticker)
        rows = [value for value in selection.get(family, []) if value in self.p2_custom_available_rows.get(family, [])]
        if checked:
            rows.append(row)
        else:
            rows = [value for value in rows if value != row]
        ordered_rows = [value for value in self.p2_custom_available_rows.get(family, []) if value in rows]
        selection[family] = ordered_rows
        self._p2_store_custom_selection(selection, ticker=ticker)
        self._p2_persist_settings()
        self._p2_update_custom_panel_descriptors()
        self._p2_rebuild_custom_panels()
        if self.p2_current_data is not None:
            self._p2_render_custom_charts(self.p2_current_data, self._p2_period())
            self._p2_relayout_charts()

    def _apply_fundamentals_theme(self) -> None:
        """Refresh Fundamentals colors when the active theme changes."""
        self.p2_name_lbl.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p2_info_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.set_status_text(self.p2_status_lbl, self.p2_status_lbl.text(), status=self.p2_status_lbl.property('bt_status') or 'muted')
        for label in list(getattr(self, 'p2_simple_titles', [])) + [item.get('title') for item in list(getattr(self, 'p2_custom_panel_widgets', []))]:
            if label is not None:
                label.setStyleSheet(f'font-size: 14px; font-weight: bold; color: {self.theme_color("text_primary")}; background: transparent;')
        for value_label in getattr(self, 'p2_metric_vals', {}).values():
            value_label.setStyleSheet(f'font-size: 14px; font-weight: bold; color: {self.theme_color("text_primary")};')
        for plot_widget in getattr(self, 'p2_simple_charts', []):
            self.style_plot_widget(plot_widget)
        for widget_info in list(getattr(self, 'p2_custom_panel_widgets', [])):
            self.style_plot_widget(widget_info['plot'])
        if self.p2_current_data is not None:
            self.update_page2(self.p2_current_data, update_collection_info=False, status_text=self.p2_status_lbl.text())
