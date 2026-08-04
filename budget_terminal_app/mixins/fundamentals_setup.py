from __future__ import annotations
from typing import Any
from PyQt6.QtWidgets import QAbstractItemView
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
        self.p2_custom_group_boxes = {}
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

        self.p2_source_tabs = QTabWidget()
        self.p2_source_tabs.setDocumentMode(True)
        self.p2_statements_tab = QWidget()
        self.p2_statements_layout = QVBoxLayout(self.p2_statements_tab)
        self.p2_statements_layout.setContentsMargins(0, 0, 0, 0)
        self.p2_statements_layout.setSpacing(4)
        self.p2_filings_tab = self._p2_build_filings_tab()
        self.p2_source_tabs.addTab(self.p2_statements_tab, 'Statements')
        self.p2_source_tabs.addTab(self.p2_filings_tab, 'SEC Filings')
        self.p2_content_layout.addWidget(self.p2_source_tabs, 1)

        self.p2_top_frame = QFrame()
        self.p2_top_frame.setFixedHeight(66)
        self.set_theme_role(self.p2_top_frame, 'panel')
        top_layout = QVBoxLayout(self.p2_top_frame)
        top_layout.setContentsMargins(10, 4, 10, 4)
        top_layout.setSpacing(2)
        identity_row = QHBoxLayout()
        identity_row.setSpacing(10)
        self.p2_name_lbl = QLabel('—')
        self.p2_info_lbl = QLabel('—')
        identity_row.addWidget(self.p2_name_lbl)
        identity_row.addWidget(self.p2_info_lbl)
        identity_row.addStretch()
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
        identity_row.addWidget(self.p2_website_btn)
        identity_row.addWidget(self.p2_ir_btn)
        top_layout.addLayout(identity_row)
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
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
            metrics_row.addLayout(pair)
            self.p2_metric_vals[key] = value_label
        metrics_row.addStretch()
        top_layout.addLayout(metrics_row)
        self.p2_statements_layout.addWidget(self.p2_top_frame)

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
        self.p2_configuration_group = QButtonGroup(self)
        self.p2_configuration_group.setExclusive(True)
        self.p2_configuration_buttons = {}
        for configuration, label in (('default', 'Default'), ('custom', 'Custom')):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFixedHeight(24)
            button.setMinimumWidth(82)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(partial(self._p2_on_configuration_changed, configuration))
            self.p2_configuration_group.addButton(button)
            self.p2_configuration_buttons[configuration] = button
            period_row.addWidget(button)
            if configuration == 'default':
                period_row.addSpacing(8)
        period_row.addStretch()
        self.p2_statements_layout.addWidget(self.p2_period_widget)

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
        self.p2_custom_editor_frame.setMinimumWidth(340)
        self.p2_custom_editor_frame.setMaximumWidth(420)
        editor_layout = QVBoxLayout(self.p2_custom_editor_frame)
        editor_layout.setContentsMargins(14, 14, 14, 14)
        editor_layout.setSpacing(10)
        editor_header = QHBoxLayout()
        editor_header.setContentsMargins(0, 0, 0, 0)
        editor_header.setSpacing(8)
        editor_title = QLabel('Custom Configuration')
        self.set_theme_role(editor_title, 'section_title')
        self.p2_custom_selection_count = QLabel('0 selected')
        self.set_theme_role(self.p2_custom_selection_count, 'muted')
        editor_header.addWidget(editor_title)
        editor_header.addStretch()
        editor_header.addWidget(self.p2_custom_selection_count)
        self.p2_custom_editor_hint = QLabel('Load a ticker to see available data.')
        self.p2_custom_editor_hint.setWordWrap(True)
        self.set_theme_role(self.p2_custom_editor_hint, 'muted')
        self.p2_custom_filter_input = QLineEdit()
        self.p2_custom_filter_input.setPlaceholderText('Search statement metrics')
        self.p2_custom_filter_input.setClearButtonEnabled(True)
        self.p2_custom_filter_input.setAccessibleName('Filter custom Fundamentals metrics')
        self.p2_custom_filter_input.textChanged.connect(self._p2_apply_custom_filter)
        custom_filter_row = QHBoxLayout()
        custom_filter_row.setContentsMargins(0, 0, 0, 0)
        custom_filter_row.setSpacing(8)
        self.p2_custom_selected_only_cb = QCheckBox('Selected only')
        self.p2_custom_selected_only_cb.toggled.connect(self._p2_apply_custom_filter)
        self.p2_custom_clear_btn = QPushButton('Clear selection')
        self.p2_custom_clear_btn.setToolTip('Remove every metric from this ticker\'s Custom view')
        self.p2_custom_clear_btn.clicked.connect(self._p2_clear_custom_selection)
        custom_filter_row.addWidget(self.p2_custom_selected_only_cb)
        custom_filter_row.addStretch()
        custom_filter_row.addWidget(self.p2_custom_clear_btn)
        self.p2_custom_editor_scroll = QScrollArea()
        self.p2_custom_editor_scroll.setWidgetResizable(True)
        self.p2_custom_editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p2_custom_editor_content = QWidget()
        self.p2_custom_editor_content_layout = QVBoxLayout(self.p2_custom_editor_content)
        self.p2_custom_editor_content_layout.setContentsMargins(0, 0, 0, 0)
        self.p2_custom_editor_content_layout.setSpacing(10)
        self.p2_custom_editor_scroll.setWidget(self.p2_custom_editor_content)
        editor_layout.addLayout(editor_header)
        editor_layout.addWidget(self.p2_custom_editor_hint)
        editor_layout.addWidget(self.p2_custom_filter_input)
        editor_layout.addLayout(custom_filter_row)
        editor_layout.addWidget(self.p2_custom_editor_scroll, 1)
        self.p2_custom_editor_frame.setVisible(self.p2_selected_configuration == 'custom')
        self.p2_workspace_splitter.addWidget(self.p2_custom_editor_frame)
        self.p2_workspace_splitter.setStretchFactor(0, 5)
        self.p2_workspace_splitter.setStretchFactor(1, 2)
        self.p2_statements_layout.addWidget(self.p2_workspace_splitter, 1)

        self._p2_sync_configuration_buttons()
        self._p2_rebuild_custom_checklist()
        self._p2_rebuild_custom_panels()
        self._p2_refresh_workspace_mode()
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

    def _p2_sync_configuration_buttons(self) -> None:
        """Keep the visible Default / Custom options aligned with persisted state."""
        buttons = getattr(self, 'p2_configuration_buttons', {})
        if not buttons:
            return
        configuration = str(getattr(self, 'p2_selected_configuration', 'default') or 'default').strip().lower()
        if configuration not in buttons:
            configuration = 'default'
            self.p2_selected_configuration = configuration
        for button in buttons.values():
            button.blockSignals(True)
        try:
            buttons[configuration].setChecked(True)
            for key, button in buttons.items():
                if key != configuration:
                    button.setChecked(False)
        finally:
            for button in buttons.values():
                button.blockSignals(False)

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

    def _p2_update_custom_editor_summary(self) -> None:
        """Refresh selection counts, family counts, and Custom editor availability."""
        available_total = sum(len(rows) for rows in getattr(self, 'p2_custom_available_rows', {}).values())
        selected_total = sum(
            1
            for family_boxes in getattr(self, 'p2_custom_checkboxes', {}).values()
            for checkbox in family_boxes.values()
            if checkbox.isChecked()
        )
        ticker = self._p2_current_ticker()
        has_data = isinstance(getattr(self, 'p2_current_data', None), dict) and bool(ticker)
        if hasattr(self, 'p2_custom_selection_count'):
            if available_total:
                self.p2_custom_selection_count.setText(f'{selected_total} / {available_total} selected')
            else:
                self.p2_custom_selection_count.setText('0 selected')
        if hasattr(self, 'p2_custom_editor_hint'):
            if not has_data:
                self.p2_custom_editor_hint.setText('Load a ticker to see available data.')
            elif not available_total:
                self.p2_custom_editor_hint.setText(f'No statement metrics are available for {ticker}.')
            else:
                self.p2_custom_editor_hint.setText(
                    f'{ticker} selections are saved separately. Search or tick metrics to build this view.'
                )
        for family, label in self._P2_CUSTOM_FAMILIES:
            group_box = getattr(self, 'p2_custom_group_boxes', {}).get(family)
            if group_box is None:
                continue
            family_boxes = getattr(self, 'p2_custom_checkboxes', {}).get(family, {})
            family_selected = sum(1 for checkbox in family_boxes.values() if checkbox.isChecked())
            group_box.setTitle(f'{label}  ·  {family_selected} / {len(family_boxes)} selected')
        controls_enabled = has_data and available_total > 0
        if hasattr(self, 'p2_custom_filter_input'):
            self.p2_custom_filter_input.setEnabled(controls_enabled)
        if hasattr(self, 'p2_custom_selected_only_cb'):
            self.p2_custom_selected_only_cb.setEnabled(controls_enabled)
        if hasattr(self, 'p2_custom_clear_btn'):
            self.p2_custom_clear_btn.setEnabled(controls_enabled and selected_total > 0)

    def _p2_apply_custom_filter(self, *_: Any) -> None:
        """Filter the Custom checklist without changing any saved selection."""
        query = ''
        if hasattr(self, 'p2_custom_filter_input'):
            query = str(self.p2_custom_filter_input.text() or '').strip().casefold()
        selected_only = bool(
            hasattr(self, 'p2_custom_selected_only_cb') and self.p2_custom_selected_only_cb.isChecked()
        )
        visible_count = 0
        for family, _ in self._P2_CUSTOM_FAMILIES:
            group_visible = False
            for row, checkbox in getattr(self, 'p2_custom_checkboxes', {}).get(family, {}).items():
                matches_query = not query or query in str(row or '').casefold()
                visible = matches_query and (not selected_only or checkbox.isChecked())
                checkbox.setVisible(visible)
                group_visible = group_visible or visible
                visible_count += int(visible)
            group_box = getattr(self, 'p2_custom_group_boxes', {}).get(family)
            if group_box is not None:
                group_box.setVisible(group_visible)
        no_matches_label = getattr(self, 'p2_custom_no_matches_label', None)
        if no_matches_label is not None:
            no_matches_label.setText(
                'No selected metrics yet.' if selected_only and not query else 'No metrics match this search.'
            )
            no_matches_label.setVisible(visible_count == 0)

    def _p2_clear_custom_selection(self, *_: Any) -> None:
        """Remove all metrics from the current ticker's Custom view."""
        ticker = self._p2_current_ticker()
        if not ticker or not any(self._p2_current_custom_selection(ticker).values()):
            return
        self._p2_checklist_sync_guard = True
        try:
            for family_boxes in self.p2_custom_checkboxes.values():
                for checkbox in family_boxes.values():
                    checkbox.setChecked(False)
        finally:
            self._p2_checklist_sync_guard = False
        self._p2_store_custom_selection(
            {family: [] for family, _ in self._P2_CUSTOM_FAMILIES},
            ticker=ticker,
        )
        self._p2_persist_settings()
        self._p2_update_custom_panel_descriptors()
        self._p2_rebuild_custom_panels()
        self._p2_update_custom_editor_summary()
        self._p2_apply_custom_filter()
        self._p2_relayout_charts()

    def _p2_rebuild_custom_checklist(self) -> None:
        """Rebuild the right-side checklist from the currently loaded ticker data."""
        while self.p2_custom_editor_content_layout.count():
            item = self.p2_custom_editor_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.p2_custom_checkboxes = {family: {} for family, _ in self._P2_CUSTOM_FAMILIES}
        self.p2_custom_available_rows = {family: [] for family, _ in self._P2_CUSTOM_FAMILIES}
        self.p2_custom_group_boxes = {}
        self.p2_custom_no_matches_label = None
        ticker = self._p2_current_ticker()
        if not isinstance(self.p2_current_data, dict) or not ticker:
            prompt = QLabel('Load a ticker to see available data.')
            prompt.setWordWrap(True)
            self.set_theme_role(prompt, 'muted')
            self.p2_custom_editor_content_layout.addWidget(prompt)
            self.p2_custom_editor_content_layout.addStretch(1)
            self._p2_update_custom_panel_descriptors()
            self._p2_update_custom_editor_summary()
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
                self.p2_custom_group_boxes[family] = group_box
                selected_rows = set(selection.get(family, []))
                for row in rows:
                    checkbox = QCheckBox(row)
                    checkbox.setToolTip(row)
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
            else:
                self.p2_custom_no_matches_label = QLabel('No metrics match this search.')
                self.p2_custom_no_matches_label.setWordWrap(True)
                self.set_theme_role(self.p2_custom_no_matches_label, 'muted')
                self.p2_custom_no_matches_label.setVisible(False)
                self.p2_custom_editor_content_layout.addWidget(self.p2_custom_no_matches_label)
            self.p2_custom_editor_content_layout.addStretch(1)
        finally:
            self._p2_checklist_sync_guard = False
        if selection_changed:
            self._p2_store_custom_selection(selection, ticker=ticker)
            self._p2_persist_settings()
        self._p2_update_custom_panel_descriptors()
        self._p2_update_custom_editor_summary()
        self._p2_apply_custom_filter()

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
            message = (
                'Load a ticker to see available data.'
                if self.p2_current_data is None
                else 'Select metrics in Custom Configuration to add charts.'
            )
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
                message = (
                    'Load a ticker to see available data.'
                    if self.p2_current_data is None
                    else 'Select metrics in Custom Configuration to add charts.'
                )
                empty_label = QLabel(message)
                empty_label.setWordWrap(True)
                self.set_theme_role(empty_label, 'muted')
                self.p2_custom_grid_layout.addWidget(empty_label, 0, 0)
            return
        available_width = max(self.p2_custom_box.width(), self.page2.contentsRect().width() - 420 if hasattr(self, 'page2') else 0)
        columns = 2 if available_width >= 980 else 1
        for index, widget_info in enumerate(self.p2_custom_panel_widgets):
            frame = widget_info['frame']
            chart_height = 188 if columns == 2 else 204
            plot_height = 112 if columns == 2 else 124
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
                workspace_height = self.p2_workspace_stack.contentsRect().height() if hasattr(self, 'p2_workspace_stack') else 0
                if workspace_height <= 0:
                    content_height = self.p2_content_widget.contentsRect().height() if hasattr(self, 'p2_content_widget') else 0
                    spacing = self.p2_content_layout.spacing() if hasattr(self, 'p2_content_layout') else 0
                    controls_height = self.p2_top_frame.height() + self.p2_period_widget.height() + spacing * 2
                    workspace_height = content_height - controls_height
                available_height = max(180, workspace_height)
                columns = 3 if available_width >= 1200 else 2
                rows = max(1, math.ceil(len(frames) / columns))
                spacing = 10 if available_width >= 1200 and available_height >= 700 else 6
                chrome_height = 34
                min_chart_height = 124 if columns == 3 else 112
                grid_height = max(min_chart_height * rows + max(0, rows - 1) * spacing, available_height - chrome_height)
                chart_height = max(min_chart_height, int((grid_height - max(0, rows - 1) * spacing) / rows))
                plot_height = max(72, chart_height - 46)
                box_height = chrome_height + rows * chart_height + max(0, rows - 1) * spacing
                box_height = min(box_height, max(180, available_height))
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
        source = self._p2_source_label(payload)
        if restored and ticker:
            return f'Restored last session for {ticker} | source: {source}'
        if ticker:
            return f'{ticker}  |  source: {source}'
        return f'Source: {source}'

    def _p2_source_label(self, data: Any) -> str:
        """Return the compact source label for a Fundamentals payload."""
        payload = data if isinstance(data, dict) else {}
        sec = payload.get('sec') if isinstance(payload.get('sec'), dict) else {}
        if not sec.get('statements_available'):
            return 'yfinance only'
        freshness = str(sec.get('statement_freshness') or sec.get('freshness') or '').strip().lower()
        if freshness in {'cached', 'stale'}:
            return 'SEC cached + yfinance'
        return 'SEC EDGAR + yfinance'

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
        restored_data = deserialize_session_value(payload.get('data'))
        required_data_keys = {
            'ticker',
            'info',
            'financials',
            'quarterly_financials',
            'cashflow',
            'quarterly_cashflow',
            'balance_sheet',
            'quarterly_balance_sheet',
        }
        if not isinstance(restored_data, dict) or not required_data_keys.issubset(restored_data):
            return False
        statement_keys = required_data_keys - {'ticker', 'info'}
        if not isinstance(restored_data.get('info'), dict):
            return False
        for key in statement_keys:
            frame = restored_data.get(key)
            if frame is not None and not all(hasattr(frame, attr) for attr in ('empty', 'index', 'columns')):
                return False
        ticker = str(restored_data.get('ticker', '') or '').upper().strip()
        if not ticker:
            return False
        self.p2_ticker_input.setText(ticker)
        configuration = str(payload.get('configuration', '') or '').strip().lower()
        if configuration in {'default', 'custom'}:
            self.p2_selected_configuration = configuration
            if hasattr(self, 'p2_workspace_stack'):
                self._p2_refresh_workspace_mode()
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
        saved_last_ticker = str(state.get('last_ticker', '') or '').upper().strip()
        loaded_ticker = ''
        if isinstance(getattr(self, 'p2_current_data', None), dict):
            loaded_ticker = str(self.p2_current_data.get('ticker', '') or '').upper().strip()
        self.p2_last_ticker = loaded_ticker or saved_last_ticker
        if hasattr(self, 'p2_ticker_input'):
            self.p2_ticker_input.setText(self.p2_last_ticker)
        self._p2_sync_configuration_buttons()
        self._p2_rebuild_custom_checklist()
        self._p2_rebuild_custom_panels()
        self._p2_refresh_workspace_mode()
        if self.p2_current_data is not None:
            self._p2_render_active_configuration()
        self._p2_relayout_charts()

    def analyze_stock_p2(self, *_: Any, update_collection_info: bool=True) -> bool | None:
        """Load Fundamentals for the requested ticker."""
        ticker = self.p2_ticker_input.text().upper().strip()
        if not ticker:
            return
        thread = getattr(self, 'p2_fund_thread', None)
        if thread is not None and thread.isRunning():
            return False
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
        worker = FundamentalsWorker(ticker)
        thread = QThread()
        self.p2_fund_worker = worker
        self.p2_fund_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda data, req=request_id: self._p2_handle_result(req, data))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda msg, req=request_id: self._page2_error(req, msg))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda req=request_id, w=worker, t=thread: self._p2_cleanup_worker_refs(req, w, t))
        thread.start()

    def _p2_cleanup_worker_refs(self, request_id: int, worker: Any, thread: Any) -> None:
        """Clear stale Fundamentals worker references after Qt has finished the thread."""
        if getattr(self, 'p2_fund_worker', None) is worker:
            self.p2_fund_worker = None
        if getattr(self, 'p2_fund_thread', None) is thread:
            self.p2_fund_thread = None
        self._p2_request_contexts.pop(request_id, None)

    def _p2_handle_result(self, request_id: int, data: Any) -> None:
        """Apply one Fundamentals response only when it is still current."""
        context = self._p2_request_contexts.pop(request_id, {})
        if request_id != getattr(self, '_p2_active_request_id', 0):
            return
        if not self._p2_page_is_visible():
            self._p2_pending_result = (data, context)
            self.p2_analyze_btn.setEnabled(True)
            return
        self.update_page2(
            data,
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _p2_page_is_visible(self) -> bool:
        page = getattr(self, 'page2', None)
        page_check = getattr(self, '_is_current_page', None)
        if page is None or not callable(page_check):
            return True
        try:
            return bool(page_check(page))
        except (AttributeError, RuntimeError):
            return False

    def _p2_on_show(self) -> None:
        pending = getattr(self, '_p2_pending_result', None)
        if isinstance(pending, tuple) and len(pending) == 2:
            self._p2_pending_result = None
            data, context = pending
            self.update_page2(
                data,
                update_collection_info=bool(context.get('update_collection_info', True)),
            )
        self._p2_relayout_charts()

    def _p2_build_filings_tab(self) -> Any:
        """Build the searchable SEC filing browser without changing the statement workspace."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.p2_filings_search = QLineEdit()
        self.p2_filings_search.setPlaceholderText('Search form, date, description, item, or accession')
        self.p2_filings_search.setClearButtonEnabled(True)
        self.p2_filings_search.textChanged.connect(self._p2_filter_filings)
        self.p2_filings_form_filter = QComboBox()
        self.p2_filings_form_filter.addItems(['All', '10-K', '10-Q', '8-K'])
        self.p2_filings_form_filter.currentTextChanged.connect(self._p2_filter_filings)
        self.p2_open_filing_btn = QPushButton('Open Filing')
        self.p2_open_filing_btn.setEnabled(False)
        self.p2_open_filing_btn.clicked.connect(self._p2_open_selected_filing)
        controls.addWidget(self.p2_filings_search, 1)
        controls.addWidget(self.p2_filings_form_filter)
        controls.addWidget(self.p2_open_filing_btn)
        layout.addLayout(controls)

        self.p2_filings_status = QLabel('Load a domestic US ticker to retrieve recent SEC filings.')
        self.p2_filings_status.setWordWrap(True)
        self.set_theme_role(self.p2_filings_status, 'muted')
        layout.addWidget(self.p2_filings_status)
        self.p2_filings_table = QTableWidget(0, 5)
        self.p2_filings_table.setHorizontalHeaderLabels(['Form', 'Filed', 'Report Period', 'Description / Items', 'Accession'])
        self.p2_filings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.p2_filings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.p2_filings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.p2_filings_table.setAlternatingRowColors(True)
        self.p2_filings_table.setSortingEnabled(True)
        self.p2_filings_table.verticalHeader().setVisible(False)
        header = self.p2_filings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.p2_filings_table.itemSelectionChanged.connect(self._p2_sync_open_filing_button)
        self.p2_filings_table.itemDoubleClicked.connect(lambda *_: self._p2_open_selected_filing())
        layout.addWidget(self.p2_filings_table, 1)
        self.p2_filings = []
        return page

    def _p2_filter_filings(self, *_: Any) -> None:
        """Apply the text and form filters to the current SEC filing rows."""
        if not hasattr(self, 'p2_filings_table'):
            return
        query = str(self.p2_filings_search.text() or '').casefold().strip()
        form_filter = str(self.p2_filings_form_filter.currentText() or 'All').upper()
        for row in range(self.p2_filings_table.rowCount()):
            form_item = self.p2_filings_table.item(row, 0)
            form = str(form_item.text() if form_item is not None else '').upper()
            values = [
                str(self.p2_filings_table.item(row, column).text() if self.p2_filings_table.item(row, column) else '')
                for column in range(self.p2_filings_table.columnCount())
            ]
            form_matches = form_filter == 'ALL' or form.startswith(form_filter)
            text_matches = not query or query in ' '.join(values).casefold()
            self.p2_filings_table.setRowHidden(row, not (form_matches and text_matches))
        self._p2_sync_open_filing_button()

    def _p2_selected_filing_url(self) -> str:
        """Return the official SEC URL stored on the selected filing row."""
        if not hasattr(self, 'p2_filings_table'):
            return ''
        row = self.p2_filings_table.currentRow()
        if row < 0 or self.p2_filings_table.isRowHidden(row):
            return ''
        item = self.p2_filings_table.item(row, 0)
        if item is None:
            return ''
        return str(item.data(Qt.ItemDataRole.UserRole) or '').strip()

    def _p2_sync_open_filing_button(self) -> None:
        """Enable the filing action only when a visible row has an official URL."""
        if hasattr(self, 'p2_open_filing_btn'):
            self.p2_open_filing_btn.setEnabled(bool(self._p2_selected_filing_url()))

    def _p2_open_selected_filing(self, *_: Any) -> None:
        """Open the selected filing on SEC.gov."""
        url = self._p2_selected_filing_url()
        if url:
            webbrowser.open(url)

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
        self._p2_sync_configuration_buttons()
        self.p2_workspace_stack.setCurrentWidget(self.p2_custom_workspace if is_custom else self.p2_default_workspace)
        self.p2_custom_editor_frame.setVisible(is_custom)
        if is_custom:
            self.p2_workspace_splitter.setSizes([860, 380])
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

    def _p2_on_configuration_changed(self, configuration: Any, _: bool=False) -> None:
        """Persist and apply a configuration switch between Default and Custom."""
        config = str(configuration or 'default').strip().lower()
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
        self._p2_update_custom_editor_summary()
        self._p2_apply_custom_filter()
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
