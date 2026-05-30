from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.valuation import (
    DEFAULT_VALUATION_ASSUMPTIONS,
    ValuationWorker,
    calculate_valuation_scenarios,
    normalize_valuation_assumptions,
)


class ValuationMixin:
    _VALUATION_METRIC_DEFS = (
        ('P/E', 'pe', 'ratio'),
        ('Forward P/E', 'forward_pe', 'ratio'),
        ('P/S', 'ps', 'ratio'),
        ('P/B', 'pb', 'ratio'),
        ('EV/EBITDA', 'ev_ebitda', 'ratio'),
        ('FCF Yield', 'fcf_yield', 'pct'),
        ('Earnings Yield', 'earnings_yield', 'pct'),
        ('PEG', 'peg', 'ratio'),
        ('Dividend Yield', 'dividend_yield', 'pct'),
    )

    def init_page23(self) -> None:
        """Build the Valuation page UI."""
        self.valuation_page_state = getattr(self, 'valuation_page_state', load_valuation_page_settings())
        self._valuation_request_seq = 0
        self._valuation_active_request_id = 0
        self._valuation_request_contexts = {}
        self._valuation_assumption_guard = False
        self._valuation_notes_guard = False
        self.valuation_current_data = None
        self.valuation_loaded_ticker = ''
        self.valuation_current_scenarios = None

        layout = QVBoxLayout(self.page23)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QFrame()
        self.set_theme_role(header, 'panel')
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(10)
        self.valuation_ticker_input = QLineEdit(str(self.valuation_page_state.get('last_ticker', 'NVDA') or 'NVDA').upper())
        self.valuation_ticker_input.setPlaceholderText('Ticker')
        self.valuation_ticker_input.setFixedWidth(130)
        self.valuation_ticker_input.returnPressed.connect(self.load_valuation_data)
        self.valuation_load_btn = QPushButton('Load')
        self.set_theme_variant(self.valuation_load_btn, 'accent')
        self.valuation_load_btn.clicked.connect(self.load_valuation_data)
        self.valuation_recalc_btn = QPushButton('Recalculate')
        self.valuation_recalc_btn.clicked.connect(self._valuation_recalculate_from_controls)
        self.valuation_company_label = QLabel('Valuation')
        self.set_theme_role(self.valuation_company_label, 'page_title')
        self.valuation_price_label = QLabel('Price --')
        self.valuation_market_cap_label = QLabel('Market cap --')
        self.valuation_sector_label = QLabel('Sector --')
        self.valuation_refresh_label = QLabel('Last refreshed --')
        for label in (self.valuation_price_label, self.valuation_market_cap_label, self.valuation_sector_label, self.valuation_refresh_label):
            self.set_theme_role(label, 'muted')
        header_layout.addWidget(QLabel('Ticker'))
        header_layout.addWidget(self.valuation_ticker_input)
        header_layout.addWidget(self.valuation_load_btn)
        header_layout.addWidget(self.valuation_recalc_btn)
        header_layout.addSpacing(12)
        header_layout.addWidget(self.valuation_company_label, 2)
        header_layout.addWidget(self.valuation_price_label)
        header_layout.addWidget(self.valuation_market_cap_label)
        header_layout.addWidget(self.valuation_sector_label)
        header_layout.addWidget(self.valuation_refresh_label)
        layout.addWidget(header)

        verdict = QFrame()
        self.set_theme_role(verdict, 'panel')
        verdict_layout = QGridLayout(verdict)
        verdict_layout.setContentsMargins(10, 8, 10, 8)
        verdict_layout.setHorizontalSpacing(16)
        verdict_layout.setVerticalSpacing(4)
        verdict_items = (
            ('Verdict', 'valuation_verdict_value'),
            ('Estimated Fair Value', 'valuation_fair_value_label'),
            ('Upside / Downside', 'valuation_upside_label'),
            ('Margin of Safety', 'valuation_margin_label'),
            ('Confidence', 'valuation_confidence_label'),
            ('Buy Below / Trim Above', 'valuation_band_label'),
        )
        for column, (title, attr_name) in enumerate(verdict_items):
            title_label = QLabel(title)
            self.set_theme_role(title_label, 'muted')
            value_label = QLabel('--')
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_label.setMinimumHeight(26)
            setattr(self, attr_name, value_label)
            verdict_layout.addWidget(title_label, 0, column)
            verdict_layout.addWidget(value_label, 1, column)
            verdict_layout.setColumnStretch(column, 1)
        layout.addWidget(verdict)

        self.valuation_detail_tabs = QTabWidget()
        self.valuation_detail_tabs.setDocumentMode(True)
        self.valuation_detail_tabs.setTabPosition(QTabWidget.TabPosition.North)
        layout.addWidget(self.valuation_detail_tabs, 1)

        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        primary_splitter = QSplitter(Qt.Orientation.Horizontal)
        primary_splitter.setHandleWidth(6)
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        primary_splitter.addWidget(left_column)
        primary_splitter.addWidget(right_column)
        primary_splitter.setStretchFactor(0, 2)
        primary_splitter.setStretchFactor(1, 5)
        main_layout.addWidget(primary_splitter, 1)

        metrics_frame = QFrame()
        self.set_theme_role(metrics_frame, 'panel')
        metrics_layout = QGridLayout(metrics_frame)
        metrics_layout.setContentsMargins(10, 8, 10, 8)
        metrics_layout.setSpacing(6)
        self.valuation_metric_values = {}
        for index, (label, key, _kind) in enumerate(self._VALUATION_METRIC_DEFS):
            card = QFrame()
            self.set_theme_role(card, 'panel')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(2)
            title = QLabel(label)
            self.set_theme_role(title, 'muted')
            value = QLabel('--')
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub = QLabel('computed')
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.set_theme_role(sub, 'muted')
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            card_layout.addWidget(sub)
            metrics_layout.addWidget(card, index // 3, index % 3)
            self.valuation_metric_values[key] = (value, sub)
        left_layout.addWidget(metrics_frame)

        model_frame = QFrame()
        self.set_theme_role(model_frame, 'panel')
        model_layout = QFormLayout(model_frame)
        model_layout.setContentsMargins(10, 8, 10, 8)
        model_layout.setSpacing(6)
        model_header = QWidget()
        model_header_layout = QHBoxLayout(model_header)
        model_header_layout.setContentsMargins(0, 0, 0, 2)
        model_header_layout.setSpacing(8)
        model_title = QLabel('Fair Value Assumptions')
        self.set_theme_role(model_title, 'section_title')
        self.valuation_auto_fill_toggle = QCheckBox('Auto-fill')
        self.valuation_auto_fill_toggle.setToolTip('Keep company-only growth and risk assumptions auto-filled from loaded valuation data')
        self.valuation_auto_fill_toggle.toggled.connect(self._valuation_on_auto_fill_toggled)
        model_header_layout.addWidget(model_title)
        model_header_layout.addStretch()
        model_header_layout.addWidget(self.valuation_auto_fill_toggle)
        model_layout.addRow(model_header)
        self.valuation_basis_type_combo = QComboBox()
        self.valuation_basis_type_combo.addItems(['FCF', 'EPS'])
        self.valuation_basis_value_spin = self._valuation_double_spin(0.0, 100000.0, '$', 2)
        self.valuation_growth_1_5_spin = self._valuation_double_spin(-50.0, 100.0, '', 1, suffix=' %')
        self.valuation_growth_6_10_spin = self._valuation_double_spin(-50.0, 100.0, '', 1, suffix=' %')
        self.valuation_discount_spin = self._valuation_double_spin(0.1, 50.0, '', 1, suffix=' %')
        self.valuation_terminal_growth_spin = self._valuation_double_spin(-10.0, 20.0, '', 1, suffix=' %')
        self.valuation_exit_multiple_spin = self._valuation_double_spin(1.0, 100.0, '', 1, suffix=' x')
        self.valuation_projection_years_spin = QSpinBox()
        self.valuation_projection_years_spin.setRange(1, 15)
        self.valuation_projection_years_spin.setSuffix(' years')
        self.valuation_margin_spin = self._valuation_double_spin(0.0, 90.0, '', 1, suffix=' %')
        self.valuation_basis_type_combo.currentIndexChanged.connect(self._valuation_on_basis_type_changed)
        controls = (
            self.valuation_basis_value_spin,
            self.valuation_growth_1_5_spin,
            self.valuation_growth_6_10_spin,
            self.valuation_discount_spin,
            self.valuation_terminal_growth_spin,
            self.valuation_exit_multiple_spin,
            self.valuation_projection_years_spin,
            self.valuation_margin_spin,
        )
        for control in controls:
            signal = getattr(control, 'valueChanged', None) or getattr(control, 'currentIndexChanged', None)
            if signal is not None:
                signal.connect(self._valuation_recalculate_from_controls)
        model_layout.addRow('Basis type', self.valuation_basis_type_combo)
        model_layout.addRow('Basis value', self.valuation_basis_value_spin)
        model_layout.addRow('Growth years 1-5', self.valuation_growth_1_5_spin)
        model_layout.addRow('Growth years 6-10', self.valuation_growth_6_10_spin)
        model_layout.addRow('Discount rate', self.valuation_discount_spin)
        model_layout.addRow('Terminal growth', self.valuation_terminal_growth_spin)
        model_layout.addRow('Exit multiple', self.valuation_exit_multiple_spin)
        model_layout.addRow('Projection years', self.valuation_projection_years_spin)
        model_layout.addRow('Margin of safety', self.valuation_margin_spin)
        left_layout.addWidget(model_frame)

        self.valuation_scenario_table = self._valuation_table(['Scenario', 'Fair Value', 'Upside', 'Assumptions'])
        self.valuation_scenario_table.setMinimumHeight(320)

        self.valuation_risk_table = self._valuation_table(['Metric', 'Value', 'Notes'])
        self.valuation_risk_table.setMinimumHeight(320)

        self.valuation_notes_edit = QPlainTextEdit(self.page23)
        self.valuation_notes_edit.setPlaceholderText('Thesis, key risk, or source notes for this ticker')
        self.valuation_notes_edit.textChanged.connect(self._valuation_store_notes_from_editor)
        self.valuation_notes_edit.hide()

        self.valuation_fair_value_plot = self._valuation_plot('Price vs Fair Value Band')
        self.valuation_fair_value_plot.setMinimumHeight(360)
        right_layout.addWidget(self.valuation_fair_value_plot, 1)

        self.valuation_pe_plot = self._valuation_plot('Historical P/E')
        self.valuation_pe_plot.setMinimumHeight(260)
        self.valuation_trend_plot = self._valuation_plot('Revenue / EPS / FCF Trend')
        self.valuation_trend_plot.setMinimumHeight(260)

        self.valuation_peer_table = self._valuation_table(['Company', 'Market Cap', 'Rev Growth', 'Net Margin', 'P/E', 'Forward P/E', 'EV/EBITDA', 'FCF Yield'])
        self.valuation_peer_table.setMinimumHeight(340)

        self.valuation_source_table = self._valuation_table(['Source', 'Detail'])
        self.valuation_source_table.setMinimumHeight(190)
        self.valuation_source_table.setParent(self.page23)
        self.valuation_source_table.hide()

        self.valuation_detail_tabs.addTab(main_tab, 'Main')
        self.valuation_detail_tabs.addTab(self._valuation_detail_page(self.valuation_scenario_table), 'Scenarios')
        self.valuation_detail_tabs.addTab(self._valuation_detail_page(self.valuation_peer_table), 'Peers')
        self.valuation_detail_tabs.addTab(self._valuation_detail_page(self.valuation_risk_table), 'Risk')
        trends_page = QWidget()
        trends_layout = QVBoxLayout(trends_page)
        trends_layout.setContentsMargins(6, 6, 6, 6)
        trends_layout.setSpacing(6)
        trends_layout.addWidget(self.valuation_pe_plot, 1)
        trends_layout.addWidget(self.valuation_trend_plot, 1)
        self.valuation_detail_tabs.addTab(trends_page, 'Trends')
        self.valuation_detail_tabs.setCurrentIndex(0)
        primary_splitter.setSizes([520, 1250])

        self.valuation_status_label = QLabel('Enter a ticker and load valuation data.')
        self.set_theme_role(self.valuation_status_label, 'status_muted')
        layout.addWidget(self.valuation_status_label)
        self._valuation_apply_assumptions_to_controls(self.valuation_page_state.get('assumptions', DEFAULT_VALUATION_ASSUMPTIONS))
        self._apply_valuation_theme()

    def _valuation_detail_page(self, widget: Any) -> Any:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        page_layout.setSpacing(6)
        page_layout.addWidget(widget, 1)
        return page

    def _valuation_double_spin(self, minimum: float, maximum: float, prefix: str = '', decimals: int = 1, *, suffix: str = '') -> Any:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(0.5 if decimals else 1.0)
        if prefix:
            spin.setPrefix(prefix)
        if suffix:
            spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def _valuation_table(self, headers: list[str]) -> Any:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.horizontalHeader().setMinimumHeight(24)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setMinimumHeight(180)
        return table

    def _valuation_plot(self, title: str) -> Any:
        plot = pg.PlotWidget()
        plot.setMinimumHeight(180)
        plot.getPlotItem().setTitle(title)
        plot.getPlotItem().hideButtons()
        plot.getPlotItem().setMenuEnabled(False)
        plot.showGrid(x=True, y=True, alpha=0.15)
        return plot

    def _valuation_current_ticker(self) -> str:
        if hasattr(self, 'valuation_ticker_input'):
            return str(self.valuation_ticker_input.text() or '').upper().strip()
        return str(getattr(self, 'valuation_loaded_ticker', '') or '').upper().strip()

    def _valuation_notes_for_ticker(self, ticker: str) -> dict[str, str]:
        notes = dict(getattr(self, 'valuation_page_state', {}).get('notes_by_ticker', {}).get(ticker, {}))
        return {
            'thesis': str(notes.get('thesis', '') or ''),
            'risk': str(notes.get('risk', '') or ''),
            'sources': str(notes.get('sources', '') or ''),
        }

    def _valuation_settings_payload(self) -> dict[str, Any]:
        return {
            'last_ticker': self._valuation_current_ticker() or 'NVDA',
            'assumptions': self._valuation_assumptions_from_controls() if hasattr(self, 'valuation_basis_type_combo') else getattr(self, 'valuation_page_state', {}).get('assumptions', DEFAULT_VALUATION_ASSUMPTIONS),
            'notes_by_ticker': dict(getattr(self, 'valuation_page_state', {}).get('notes_by_ticker', {})),
        }

    def _valuation_persist_settings(self) -> None:
        self.valuation_page_state = save_valuation_page_settings(self._valuation_settings_payload())

    def _valuation_assumptions_from_controls(self) -> dict[str, Any]:
        return normalize_valuation_assumptions({
            'basis_type': self.valuation_basis_type_combo.currentText(),
            'basis_value': self.valuation_basis_value_spin.value(),
            'growth_1_5': self.valuation_growth_1_5_spin.value(),
            'growth_6_10': self.valuation_growth_6_10_spin.value(),
            'discount_rate': self.valuation_discount_spin.value(),
            'terminal_growth': self.valuation_terminal_growth_spin.value(),
            'exit_multiple': self.valuation_exit_multiple_spin.value(),
            'projection_years': self.valuation_projection_years_spin.value(),
            'margin_of_safety': self.valuation_margin_spin.value(),
        })

    def _valuation_metric_basis_value(self, basis_type: Any) -> float | None:
        payload = getattr(self, 'valuation_current_data', None) if isinstance(getattr(self, 'valuation_current_data', None), dict) else {}
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        key = 'eps' if str(basis_type or '').upper().strip() == 'EPS' else 'fcf_per_share'
        value = self._valuation_float(metrics.get(key))
        return value if value is not None and value > 0 else None

    def _valuation_on_basis_type_changed(self, *_: Any) -> None:
        if getattr(self, '_valuation_assumption_guard', False):
            return
        basis_value = self._valuation_metric_basis_value(self.valuation_basis_type_combo.currentText())
        if basis_value is not None:
            self._valuation_assumption_guard = True
            try:
                self.valuation_basis_value_spin.setValue(float(basis_value))
            finally:
                self._valuation_assumption_guard = False
        if getattr(self, 'valuation_auto_fill_toggle', None) is not None and self.valuation_auto_fill_toggle.isChecked():
            if self._valuation_apply_auto_fill_estimates(show_status=False):
                return
        self._valuation_recalculate_from_controls()

    def _valuation_clamp(self, value: Any, minimum: float, maximum: float) -> float | None:
        numeric = self._valuation_float(value)
        if numeric is None:
            return None
        return min(max(numeric, minimum), maximum)

    def _valuation_series_cagr(self, values: Any) -> float | None:
        numeric_values = [
            numeric
            for numeric in (self._valuation_float(value) for value in list(values or []))
            if numeric is not None and numeric > 0
        ]
        if len(numeric_values) < 2:
            return None
        start = numeric_values[0]
        end = numeric_values[-1]
        years = len(numeric_values) - 1
        if start <= 0 or end <= 0 or years <= 0:
            return None
        try:
            return ((end / start) ** (1.0 / years) - 1.0) * 100.0
        except (OverflowError, ZeroDivisionError, ValueError):
            return None

    def _valuation_estimate_near_growth(self, metrics: dict[str, Any], trends: dict[str, Any]) -> float | None:
        basis_type = str(self.valuation_basis_type_combo.currentText() or '').upper().strip()
        basis_key = 'eps' if basis_type == 'EPS' else 'fcf'
        growth = self._valuation_series_cagr(trends.get(basis_key))
        if growth is None:
            growth = self._valuation_series_cagr(trends.get('revenue'))
        if growth is None:
            growth = self._valuation_float(metrics.get('revenue_growth'))
        return self._valuation_clamp(growth, -10.0, 35.0)

    def _valuation_estimate_discount_rate(self, metrics: dict[str, Any]) -> float | None:
        discount = float(DEFAULT_VALUATION_ASSUMPTIONS['discount_rate'])
        has_signal = False
        beta = self._valuation_float(metrics.get('beta'))
        if beta is not None:
            discount += (beta - 1.0) * 2.0
            has_signal = True
        free_cash_flow = self._valuation_float(metrics.get('free_cash_flow'))
        if free_cash_flow is not None:
            has_signal = True
            if free_cash_flow <= 0:
                discount += 1.5
        net_debt = self._valuation_float(metrics.get('net_debt'))
        market_cap = self._valuation_float(metrics.get('market_cap'))
        if net_debt is not None and market_cap is not None and market_cap > 0:
            has_signal = True
            leverage = net_debt / market_cap
            if leverage > 0.5:
                discount += 2.0
            elif leverage > 0.2:
                discount += 1.0
        return self._valuation_clamp(discount, 6.0, 18.0) if has_signal else None

    def _valuation_auto_assumptions_from_payload(self) -> dict[str, float]:
        payload = getattr(self, 'valuation_current_data', None) if isinstance(getattr(self, 'valuation_current_data', None), dict) else {}
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        trends = payload.get('trends', {}) if isinstance(payload.get('trends'), dict) else {}
        estimates: dict[str, float] = {}
        near_growth = self._valuation_estimate_near_growth(metrics, trends)
        if near_growth is not None:
            estimates['growth_1_5'] = near_growth
            outer_growth = self._valuation_clamp(near_growth * 0.5, -5.0, 15.0)
            if outer_growth is not None:
                estimates['growth_6_10'] = outer_growth
                terminal_growth = self._valuation_clamp(outer_growth * 0.5, 0.0, 4.0)
                if terminal_growth is not None:
                    estimates['terminal_growth'] = terminal_growth
        discount_rate = self._valuation_estimate_discount_rate(metrics)
        if discount_rate is not None:
            estimates['discount_rate'] = discount_rate
        return estimates

    def _valuation_apply_auto_fill_estimates(self, *, show_status: bool = True, persist: bool = True) -> bool:
        payload = getattr(self, 'valuation_current_data', None) if isinstance(getattr(self, 'valuation_current_data', None), dict) else {}
        if not payload:
            if show_status:
                self.set_status_text(self.valuation_status_label, 'Load a ticker before auto-filling valuation assumptions.', status='warning')
            return False
        estimates = self._valuation_auto_assumptions_from_payload()
        if not estimates:
            if show_status:
                self.set_status_text(self.valuation_status_label, 'No company-only assumption inputs were available for auto-fill.', status='warning')
            return False
        self._valuation_assumption_guard = True
        try:
            if 'growth_1_5' in estimates:
                self.valuation_growth_1_5_spin.setValue(float(estimates['growth_1_5']))
            if 'growth_6_10' in estimates:
                self.valuation_growth_6_10_spin.setValue(float(estimates['growth_6_10']))
            if 'discount_rate' in estimates:
                self.valuation_discount_spin.setValue(float(estimates['discount_rate']))
            if 'terminal_growth' in estimates:
                self.valuation_terminal_growth_spin.setValue(float(estimates['terminal_growth']))
        finally:
            self._valuation_assumption_guard = False
        self._valuation_recalculate_from_controls(persist=persist)
        if show_status:
            self.set_status_text(self.valuation_status_label, 'Applied company-only auto-fill assumptions from loaded valuation data.', status='positive')
        return True

    def _valuation_on_auto_fill_toggled(self, enabled: bool) -> None:
        if enabled:
            self._valuation_apply_auto_fill_estimates(show_status=True)
        else:
            self._valuation_recalculate_from_controls()
            self.set_status_text(self.valuation_status_label, 'Auto-fill assumptions off; manual assumptions stay editable.', status='muted')

    def _valuation_apply_assumptions_to_controls(self, assumptions: Any) -> None:
        values = normalize_valuation_assumptions(assumptions)
        self._valuation_assumption_guard = True
        try:
            self.valuation_basis_type_combo.setCurrentText(str(values['basis_type']))
            self.valuation_basis_value_spin.setValue(float(values['basis_value']))
            self.valuation_growth_1_5_spin.setValue(float(values['growth_1_5']))
            self.valuation_growth_6_10_spin.setValue(float(values['growth_6_10']))
            self.valuation_discount_spin.setValue(float(values['discount_rate']))
            self.valuation_terminal_growth_spin.setValue(float(values['terminal_growth']))
            self.valuation_exit_multiple_spin.setValue(float(values['exit_multiple']))
            self.valuation_projection_years_spin.setValue(int(values['projection_years']))
            self.valuation_margin_spin.setValue(float(values['margin_of_safety']))
        finally:
            self._valuation_assumption_guard = False

    def _valuation_apply_payload_basis(self, payload: dict[str, Any]) -> None:
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        basis_value = metrics.get('basis_value')
        if basis_value is None or basis_value <= 0:
            return
        current_ticker = str(payload.get('ticker', '') or '').upper().strip()
        previous_ticker = str(getattr(self, 'valuation_loaded_ticker', '') or '').upper().strip()
        current_basis = self.valuation_basis_value_spin.value()
        if current_ticker != previous_ticker or current_basis <= 0:
            values = self._valuation_assumptions_from_controls()
            values['basis_type'] = metrics.get('basis_type') or values['basis_type']
            values['basis_value'] = float(basis_value)
            self._valuation_apply_assumptions_to_controls(values)

    def load_valuation_data(self, *_: Any, update_collection_info: bool = True) -> bool | None:
        ticker = self._valuation_current_ticker()
        if not ticker:
            return
        thread = getattr(self, 'valuation_thread', None)
        if thread is not None and thread.isRunning():
            return False
        self.valuation_page_state = {
            **getattr(self, 'valuation_page_state', load_valuation_page_settings()),
            'last_ticker': ticker,
        }
        self._valuation_persist_settings()
        self._valuation_request_seq += 1
        request_id = self._valuation_request_seq
        self._valuation_active_request_id = request_id
        self._valuation_request_contexts[request_id] = {'update_collection_info': bool(update_collection_info)}
        self.valuation_load_btn.setEnabled(False)
        self.set_status_text(self.valuation_status_label, f'Loading {ticker} valuation data...', status='warning')
        worker = ValuationWorker(ticker)
        thread = QThread()
        self.valuation_worker = worker
        self.valuation_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda payload, req=request_id: self._valuation_handle_result(req, payload))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda message, req=request_id: self._valuation_handle_error(req, message))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda req=request_id, w=worker, t=thread: self._valuation_cleanup_worker_refs(req, w, t))
        thread.start()

    def _valuation_cleanup_worker_refs(self, request_id: int, worker: Any, thread: Any) -> None:
        if getattr(self, 'valuation_worker', None) is worker:
            self.valuation_worker = None
        if getattr(self, 'valuation_thread', None) is thread:
            self.valuation_thread = None
        self._valuation_request_contexts.pop(request_id, None)

    def _valuation_handle_result(self, request_id: int, payload: Any) -> None:
        context = self._valuation_request_contexts.pop(request_id, {})
        if request_id != getattr(self, '_valuation_active_request_id', 0):
            return
        self.update_valuation_page(
            payload if isinstance(payload, dict) else {},
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _valuation_handle_error(self, request_id: int, message: Any) -> None:
        self._valuation_request_contexts.pop(request_id, None)
        if request_id != getattr(self, '_valuation_active_request_id', 0):
            return
        self.valuation_load_btn.setEnabled(True)
        self.set_status_text(self.valuation_status_label, f'Valuation load failed: {message}', status='negative')

    def update_valuation_page(self, payload: dict[str, Any], *, update_collection_info: bool = True, status_text: str | None = None) -> None:
        self.valuation_current_data = payload
        ticker = str(payload.get('ticker') or self._valuation_current_ticker() or 'NVDA').upper().strip()
        self.valuation_ticker_input.setText(ticker)
        self._valuation_apply_payload_basis(payload)
        auto_applied = False
        if getattr(self, 'valuation_auto_fill_toggle', None) is not None and self.valuation_auto_fill_toggle.isChecked():
            auto_applied = self._valuation_apply_auto_fill_estimates(show_status=False, persist=False)
        self.valuation_loaded_ticker = ticker
        self._valuation_render_snapshot(payload)
        self._valuation_render_metrics(payload)
        self._valuation_load_notes_for_ticker(ticker)
        if not auto_applied:
            self._valuation_recalculate_from_controls(persist=False)
        self._valuation_render_peer_table(payload)
        self._valuation_render_risk_table(payload)
        self._valuation_render_source_table(payload)
        self._valuation_render_trend_chart(payload)
        self._valuation_render_historical_pe_chart(payload)
        self.valuation_load_btn.setEnabled(True)
        if update_collection_info:
            self._set_data_collection_info(['yfinance'])
        self.set_status_text(self.valuation_status_label, status_text or f'Loaded valuation data for {ticker}.', status='positive')
        self._valuation_persist_settings()
        self._valuation_save_session_snapshot()

    def _valuation_render_snapshot(self, payload: dict[str, Any]) -> None:
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        ticker = str(payload.get('ticker') or '').upper().strip()
        company = str(metrics.get('company_name') or ticker or 'Valuation')
        sector = str(metrics.get('sector') or 'N/A')
        industry = str(metrics.get('industry') or '')
        fetched_at = self._valuation_format_timestamp(payload.get('fetched_at'))
        self.valuation_company_label.setText(company)
        price = metrics.get('price')
        previous = metrics.get('previous_close')
        change_text = ''
        if price is not None and previous:
            change = float(price) - float(previous)
            pct = change / float(previous) * 100.0
            change_text = f' ({change:+.2f}, {pct:+.2f}%)'
        self.valuation_price_label.setText(f'Price {self._valuation_money(price)}{change_text}')
        self.valuation_market_cap_label.setText(f'Market cap {self._valuation_compact_money(metrics.get("market_cap"))}')
        self.valuation_sector_label.setText(f'{sector}' + (f' / {industry}' if industry else ''))
        self.valuation_refresh_label.setText(f'Last refreshed {fetched_at}')

    def _valuation_render_metrics(self, payload: dict[str, Any]) -> None:
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        for _label, key, kind in self._VALUATION_METRIC_DEFS:
            value_label, sub_label = self.valuation_metric_values[key]
            if kind == 'pct':
                value_label.setText(self._valuation_pct(metrics.get(key)))
            else:
                value_label.setText(self._valuation_ratio(metrics.get(key)))
            sub_label.setText('computed' if key in {'pe', 'ps', 'ev_ebitda', 'fcf_yield', 'earnings_yield'} else 'quote/statements')

    def _valuation_recalculate_from_controls(self, *_: Any, persist: bool = True) -> None:
        if getattr(self, '_valuation_assumption_guard', False):
            return
        payload = getattr(self, 'valuation_current_data', None) if isinstance(getattr(self, 'valuation_current_data', None), dict) else {}
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        price = metrics.get('price')
        scenarios = calculate_valuation_scenarios(price, self._valuation_assumptions_from_controls())
        self.valuation_current_scenarios = scenarios
        self._valuation_render_verdict(scenarios, price)
        self._valuation_render_scenarios(scenarios)
        self._valuation_render_fair_value_chart(payload, scenarios)
        if persist:
            self._valuation_persist_settings()
            self._valuation_save_session_snapshot()

    def _valuation_render_verdict(self, scenarios: dict[str, Any], price: Any) -> None:
        verdict = scenarios.get('verdict', 'Too uncertain')
        base_value = scenarios.get('base_fair_value')
        price_value = self._valuation_float(price)
        upside = (base_value / price_value - 1.0) * 100.0 if base_value is not None and price_value else None
        self.valuation_verdict_value.setText(str(verdict))
        self.valuation_verdict_value.setStyleSheet(f'font-size: 15px; font-weight: 800; color: {self._valuation_verdict_color(verdict)};')
        self.valuation_fair_value_label.setText(self._valuation_money(base_value))
        self.valuation_upside_label.setText(self._valuation_pct(upside))
        self.valuation_margin_label.setText(self._valuation_pct(self._valuation_assumptions_from_controls().get('margin_of_safety')))
        confidence = 'High' if base_value is not None and price_value else 'Low'
        self.valuation_confidence_label.setText(confidence)
        self.valuation_band_label.setText(f'{self._valuation_money(scenarios.get("buy_below"))} / {self._valuation_money(scenarios.get("trim_above"))}')

    def _valuation_render_scenarios(self, scenarios: dict[str, Any]) -> None:
        rows = list(scenarios.get('scenarios', []))
        self.valuation_scenario_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            assumptions = row.get('assumptions', {})
            assumption_text = (
                f"{assumptions.get('growth_1_5', 0):.1f}%/{assumptions.get('growth_6_10', 0):.1f}% growth, "
                f"{assumptions.get('discount_rate', 0):.1f}% discount, "
                f"{assumptions.get('exit_multiple', 0):.1f}x exit"
            )
            values = [
                str(row.get('name', 'Scenario')),
                self._valuation_money(row.get('fair_value')),
                self._valuation_pct(row.get('upside_pct')),
                assumption_text,
            ]
            for column, value in enumerate(values):
                self.valuation_scenario_table.setItem(row_index, column, self._valuation_item(value, align_right=column in {1, 2}))
        self.valuation_scenario_table.resizeRowsToContents()

    def _valuation_render_fair_value_chart(self, payload: dict[str, Any], scenarios: dict[str, Any]) -> None:
        plot = self.valuation_fair_value_plot
        plot.clear()
        self.style_plot_widget(plot)
        history = payload.get('price_history')
        if not isinstance(history, pd.DataFrame) or history.empty or 'Close' not in history.columns:
            return
        closes = pd.to_numeric(history['Close'], errors='coerce').dropna()
        if closes.empty:
            return
        x_values = list(range(len(closes)))
        y_values = [float(value) for value in closes.tolist()]
        plot.plot(x_values, y_values, pen=self.theme_pen('info', width=2.0))
        for value, token in (
            (scenarios.get('base_fair_value'), 'warning'),
            (scenarios.get('buy_below'), 'accent_positive'),
            (scenarios.get('trim_above'), 'accent_negative'),
        ):
            numeric = self._valuation_float(value)
            if numeric is not None:
                plot.plot(x_values, [numeric] * len(x_values), pen=self.theme_pen(token, width=1.4, style=Qt.PenStyle.DashLine))
        plot.enableAutoRange()

    def _valuation_render_historical_pe_chart(self, payload: dict[str, Any]) -> None:
        plot = self.valuation_pe_plot
        plot.clear()
        self.style_plot_widget(plot)
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        eps = self._valuation_float(metrics.get('eps'))
        history = payload.get('price_history')
        if eps is None or eps <= 0 or not isinstance(history, pd.DataFrame) or history.empty or 'Close' not in history.columns:
            return
        closes = pd.to_numeric(history['Close'], errors='coerce').dropna()
        pe_values = [float(value) / eps for value in closes.tolist()]
        plot.plot(list(range(len(pe_values))), pe_values, pen=self.theme_pen('info', width=2.0))
        current_pe = self._valuation_float(metrics.get('pe'))
        if current_pe is not None:
            plot.plot(list(range(len(pe_values))), [current_pe] * len(pe_values), pen=self.theme_pen('warning', width=1.3, style=Qt.PenStyle.DashLine))
        plot.enableAutoRange()

    def _valuation_render_trend_chart(self, payload: dict[str, Any]) -> None:
        plot = self.valuation_trend_plot
        plot.clear()
        self.style_plot_widget(plot)
        trends = payload.get('trends', {}) if isinstance(payload.get('trends'), dict) else {}
        labels = list(trends.get('labels', []) or [])
        if not labels:
            return
        x_values = list(range(len(labels)))
        revenue = [self._valuation_float(value / 1_000_000_000.0 if value is not None else None) for value in list(trends.get('revenue', []) or [])]
        fcf = [self._valuation_float(value / 1_000_000_000.0 if value is not None else None) for value in list(trends.get('fcf', []) or [])]
        eps = [self._valuation_float(value) for value in list(trends.get('eps', []) or [])]
        if revenue:
            plot.plot(x_values[:len(revenue)], revenue, pen=self.theme_pen('accent_positive', width=2.0), name='Revenue B')
        if fcf:
            plot.plot(x_values[:len(fcf)], fcf, pen=self.theme_pen('warning', width=2.0), name='FCF B')
        if eps:
            plot.plot(x_values[:len(eps)], eps, pen=self.theme_pen('info', width=2.0), name='EPS')
        plot.enableAutoRange()

    def _valuation_render_peer_table(self, payload: dict[str, Any]) -> None:
        rows = list(payload.get('peer_rows', []) or [])
        self.valuation_peer_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                f"{row.get('company') or row.get('ticker')} ({row.get('ticker')})",
                self._valuation_compact_money(row.get('market_cap')),
                self._valuation_pct(row.get('revenue_growth')),
                self._valuation_pct(row.get('net_margin')),
                self._valuation_ratio(row.get('pe')),
                self._valuation_ratio(row.get('forward_pe')),
                self._valuation_ratio(row.get('ev_ebitda')),
                self._valuation_pct(row.get('fcf_yield')),
            ]
            for column, value in enumerate(values):
                self.valuation_peer_table.setItem(row_index, column, self._valuation_item(value, align_right=column > 0))
        self.valuation_peer_table.resizeRowsToContents()

    def _valuation_render_risk_table(self, payload: dict[str, Any]) -> None:
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        cash = metrics.get('cash')
        debt = metrics.get('debt')
        net_debt = metrics.get('net_debt')
        rows = [
            ('Cash & equivalents', self._valuation_compact_money(cash), 'Liquidity'),
            ('Total debt', self._valuation_compact_money(debt), 'Leverage'),
            ('Net debt', self._valuation_compact_money(net_debt), 'Negative means net cash'),
            ('Revenue growth', self._valuation_pct(metrics.get('revenue_growth')), 'Latest available'),
            ('Net margin', self._valuation_pct(metrics.get('net_margin')), 'Profitability'),
            ('Beta', self._valuation_ratio(metrics.get('beta')), 'Market sensitivity'),
        ]
        self.valuation_risk_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                self.valuation_risk_table.setItem(row_index, column, self._valuation_item(value, align_right=column == 1))
        self.valuation_risk_table.resizeRowsToContents()

    def _valuation_render_source_table(self, payload: dict[str, Any]) -> None:
        sources = payload.get('sources', {}) if isinstance(payload.get('sources'), dict) else {}
        rows = [
            ('Live quote', sources.get('quote', 'yfinance quote/history')),
            ('Statements', sources.get('statements', 'yfinance financial statements')),
            ('Computed ratios', sources.get('computed', 'Computed from quote, statements, and assumptions')),
            ('Last updated', self._valuation_format_timestamp(payload.get('fetched_at'))),
        ]
        self.valuation_source_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                self.valuation_source_table.setItem(row_index, column, self._valuation_item(value))
        self.valuation_source_table.resizeRowsToContents()

    def _valuation_load_notes_for_ticker(self, ticker: str) -> None:
        notes = self._valuation_notes_for_ticker(ticker)
        text = '\n'.join(part for part in (
            f"Thesis: {notes.get('thesis', '')}" if notes.get('thesis') else '',
            f"Key Risk: {notes.get('risk', '')}" if notes.get('risk') else '',
            f"Sources: {notes.get('sources', '')}" if notes.get('sources') else '',
        ) if part)
        self._valuation_notes_guard = True
        try:
            self.valuation_notes_edit.setPlainText(text)
        finally:
            self._valuation_notes_guard = False

    def _valuation_store_notes_from_editor(self) -> None:
        if getattr(self, '_valuation_notes_guard', False):
            return
        ticker = self._valuation_current_ticker()
        if not ticker:
            return
        text = self.valuation_notes_edit.toPlainText().strip()
        notes = {'thesis': text, 'risk': '', 'sources': ''}
        state = dict(getattr(self, 'valuation_page_state', load_valuation_page_settings()))
        notes_by_ticker = dict(state.get('notes_by_ticker', {}))
        if text:
            notes_by_ticker[ticker] = notes
        else:
            notes_by_ticker.pop(ticker, None)
        state['notes_by_ticker'] = notes_by_ticker
        self.valuation_page_state = state
        self._valuation_persist_settings()

    def _valuation_session_snapshot(self) -> dict[str, Any] | None:
        ticker = self._valuation_current_ticker()
        if not ticker:
            return None
        return {
            'ticker': ticker,
            'assumptions': self._valuation_assumptions_from_controls() if hasattr(self, 'valuation_basis_type_combo') else {},
            'notes': self.valuation_notes_edit.toPlainText() if hasattr(self, 'valuation_notes_edit') else '',
            'data': serialize_session_value(getattr(self, 'valuation_current_data', None)),
        }

    def _valuation_save_session_snapshot(self, *, immediate: bool = False) -> None:
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('valuation', self._valuation_session_snapshot(), immediate=immediate)

    def _valuation_restore_session_snapshot(self, snapshot: Any) -> bool:
        payload = snapshot if isinstance(snapshot, dict) else {}
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        if ticker:
            self.valuation_ticker_input.setText(ticker)
        assumptions = payload.get('assumptions')
        if isinstance(assumptions, dict):
            self._valuation_apply_assumptions_to_controls(assumptions)
        restored_data = deserialize_session_value(payload.get('data'))
        if isinstance(restored_data, dict) and restored_data:
            self.update_valuation_page(restored_data, update_collection_info=False, status_text=f'Restored last valuation session for {ticker or restored_data.get("ticker", "")}.')
            return True
        notes = str(payload.get('notes', '') or '')
        if notes:
            self._valuation_notes_guard = True
            try:
                self.valuation_notes_edit.setPlainText(notes)
            finally:
                self._valuation_notes_guard = False
        return False

    def _valuation_restore_startup_session(self, snapshot: Any) -> None:
        restored = self._valuation_restore_session_snapshot(snapshot)
        ticker = self._valuation_current_ticker()
        if restored and ticker:
            self.load_valuation_data(update_collection_info=False)

    def _valuation_on_show(self) -> None:
        if not isinstance(getattr(self, 'valuation_current_data', None), dict) or not getattr(self, 'valuation_current_data', None):
            if getattr(self, 'valuation_thread', None) is None:
                self.load_valuation_data(update_collection_info=True)
        for plot in (
            getattr(self, 'valuation_fair_value_plot', None),
            getattr(self, 'valuation_pe_plot', None),
            getattr(self, 'valuation_trend_plot', None),
        ):
            if plot is not None:
                plot.enableAutoRange()

    def _apply_valuation_theme(self) -> None:
        if not hasattr(self, 'valuation_status_label'):
            return
        self.set_status_text(self.valuation_status_label, self.valuation_status_label.text(), status=self.valuation_status_label.property('bt_status') or 'muted')
        if hasattr(self, 'valuation_company_label'):
            self.valuation_company_label.setStyleSheet(f'font-size: 15px; font-weight: 800; color: {self.theme_color("text_primary")};')
        for value_label, _sub_label in getattr(self, 'valuation_metric_values', {}).values():
            value_label.setStyleSheet(f'font-size: 18px; font-weight: 800; color: {self.theme_color("text_primary")};')
        for plot in (
            getattr(self, 'valuation_fair_value_plot', None),
            getattr(self, 'valuation_pe_plot', None),
            getattr(self, 'valuation_trend_plot', None),
        ):
            if plot is not None:
                self.style_plot_widget(plot)
        if isinstance(getattr(self, 'valuation_current_data', None), dict):
            self._valuation_recalculate_from_controls(persist=False)

    def _valuation_item(self, text: Any, *, align_right: bool = False) -> Any:
        item = QTableWidgetItem(str(text))
        alignment = Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _valuation_float(self, value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def _valuation_money(self, value: Any) -> str:
        numeric = self._valuation_float(value)
        return '--' if numeric is None else f'${numeric:,.2f}'

    def _valuation_compact_money(self, value: Any) -> str:
        numeric = self._valuation_float(value)
        return '--' if numeric is None else f'${fmt_num(numeric)}'

    def _valuation_pct(self, value: Any) -> str:
        numeric = self._valuation_float(value)
        return '--' if numeric is None else f'{numeric:+.1f}%' if numeric < 0 else f'{numeric:.1f}%'

    def _valuation_ratio(self, value: Any) -> str:
        numeric = self._valuation_float(value)
        return '--' if numeric is None else f'{numeric:.2f}x'

    def _valuation_format_timestamp(self, value: Any) -> str:
        text = str(value or '').strip()
        if not text:
            return '--'
        try:
            parsed = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
        except Exception:
            return text
        return parsed.strftime('%Y-%m-%d %H:%M')

    def _valuation_verdict_color(self, verdict: Any) -> str:
        text = str(verdict or '').lower()
        if 'under' in text:
            return self.theme_color('accent_positive')
        if 'over' in text:
            return self.theme_color('accent_negative')
        if 'fair' in text:
            return self.theme_color('warning')
        return self.theme_color('text_muted')
