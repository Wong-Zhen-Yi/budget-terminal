from __future__ import annotations
from typing import Any
from PySide6.QtWidgets import QAbstractItemView, QStyle
from ..compat import *
from budget_terminal_app.paths import user_data_path
from budget_terminal_app.workers.fundamentals import FundamentalsWorker


class _FundamentalsFullscreenDialog(QDialog):
    """Fullscreen Fundamentals chart surface with resize notifications."""

    resized = Signal()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class FundamentalsSetupMixin:
    _P2_CONFIG_PATH = user_data_path('fundamentals_config.json')

    def _p2_legacy_last_ticker(self) -> str:
        """Read the historical standalone Fundamentals config as a migration fallback."""
        try:
            with self._P2_CONFIG_PATH.open() as handle:
                payload = json.load(handle)
        except Exception:
            return ''
        return str((payload or {}).get('last_ticker', '') or '').upper().strip()

    def _p2_settings_payload(self) -> dict[str, Any]:
        """Build the persisted Fundamentals page settings payload."""
        return {
            'last_ticker': str(
                self.p2_ticker_input.text()
                if hasattr(self, 'p2_ticker_input')
                else getattr(self, 'p2_last_ticker', '')
            ).upper().strip(),
            'compare_ticker': str(
                self.p2_compare_input.text()
                if hasattr(self, 'p2_compare_input')
                else getattr(self, 'p2_compare_ticker', '')
            ).upper().strip(),
            'period_count': self._p2_period_count(),
            'indexed': self._p2_indexed_enabled(),
            'growth_basis': self._p2_selected_growth_basis(),
        }

    def _p2_persist_settings(self) -> None:
        """Persist Fundamentals page settings to the main user-data document."""
        self.fundamentals_page_state = save_fundamentals_page_settings(self._p2_settings_payload())

    def init_page2(self, layout: Any) -> None:
        """Build the Fundamentals page UI."""
        self._p2_request_seq = 0
        self._p2_active_request_ids = {'primary': 0, 'compare': 0}
        self._p2_request_contexts = {}
        self._p2_pending_results = {}
        self.p2_fund_threads = {'primary': None, 'compare': None}
        self.p2_fund_workers = {'primary': None, 'compare': None}
        self.p2_compare_data = None
        self._p2_overview_refresh_timer = None
        self.p2_website_url = ''
        self.p2_ir_url = ''
        self.fundamentals_page_state = getattr(self, 'fundamentals_page_state', load_fundamentals_page_settings())
        migrated_ticker = self._p2_legacy_last_ticker()
        if (not self.fundamentals_page_state.get('last_ticker')) and migrated_ticker:
            self.fundamentals_page_state = save_fundamentals_page_settings({
                **self.fundamentals_page_state,
                'last_ticker': migrated_ticker,
            })
        self.p2_last_ticker = str(self.fundamentals_page_state.get('last_ticker', '') or '').upper().strip()
        self.p2_compare_ticker = str(self.fundamentals_page_state.get('compare_ticker', '') or '').upper().strip()
        self.p2_period_count = int(self.fundamentals_page_state.get('period_count', P2_DEFAULT_PERIODS))
        self.p2_indexed = bool(self.fundamentals_page_state.get('indexed', False))
        self.p2_growth_basis = str(
            self.fundamentals_page_state.get('growth_basis', P2_DEFAULT_GROWTH_BASIS) or P2_DEFAULT_GROWTH_BASIS
        )

        search_row = QHBoxLayout()
        self.p2_ticker_input = QLineEdit(self.p2_last_ticker)
        self.p2_ticker_input.setPlaceholderText('Enter any ticker (e.g. NVDA, MSFT, META)')
        self.p2_ticker_input.setFixedWidth(240)
        self.p2_ticker_input.returnPressed.connect(self.analyze_stock_p2)
        self.p2_analyze_btn = QPushButton('Analyze')
        self.p2_analyze_btn.clicked.connect(self.analyze_stock_p2)
        self.p2_compare_input = QLineEdit(self.p2_compare_ticker)
        self.p2_compare_input.setPlaceholderText('vs ticker (optional)')
        self.p2_compare_input.setFixedWidth(170)
        self.p2_compare_input.setToolTip(
            'Overlay a second company on every chart.\n'
            'Periods are aligned by calendar year or quarter, not by fiscal year.'
        )
        self.p2_compare_input.returnPressed.connect(self._p2_apply_compare)
        self.p2_compare_btn = QPushButton('Compare')
        self.set_theme_variant(self.p2_compare_btn, 'accent')
        self.p2_compare_btn.clicked.connect(self._p2_apply_compare)
        self.p2_compare_clear_btn = QPushButton('Clear')
        self.p2_compare_clear_btn.setEnabled(False)
        self.p2_compare_clear_btn.clicked.connect(self._p2_clear_compare)
        self.p2_status_lbl = QLabel('Enter a ticker above to begin the analysis.')
        self.set_theme_role(self.p2_status_lbl, 'status_muted')
        # Compare keeps its own status line: _apply_fundamentals_theme replays p2_status_lbl's text
        # back through update_page2, so a compare error written there would become sticky.
        self.p2_compare_status_lbl = QLabel('')
        self.set_theme_role(self.p2_compare_status_lbl, 'status_muted')
        search_row.addWidget(self.p2_ticker_input)
        search_row.addWidget(self.p2_analyze_btn)
        search_row.addSpacing(16)
        search_row.addWidget(self.p2_compare_input)
        search_row.addWidget(self.p2_compare_btn)
        search_row.addWidget(self.p2_compare_clear_btn)
        search_row.addStretch()
        layout.addLayout(search_row)
        status_row = QHBoxLayout()
        status_row.addWidget(self.p2_status_lbl)
        status_row.addSpacing(16)
        status_row.addWidget(self.p2_compare_status_lbl)
        status_row.addStretch()
        layout.addLayout(status_row)

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
        self.p2_metrics_widget, self.p2_metric_ticker_lbl, self.p2_metric_vals = self._p2_build_metrics_row()
        self.p2_compare_metrics_widget, self.p2_compare_metric_ticker_lbl, self.p2_compare_metric_vals = (
            self._p2_build_metrics_row()
        )
        self.p2_compare_metrics_widget.setVisible(False)
        top_layout.addWidget(self.p2_metrics_widget)
        top_layout.addWidget(self.p2_compare_metrics_widget)
        self._p2_sync_top_frame_height()
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
        period_row.addStretch()
        self.p2_growth_lbl = QLabel('Growth')
        self.set_theme_role(self.p2_growth_lbl, 'muted')
        self.p2_qoq_btn = QPushButton('QoQ')
        self.p2_yoy_btn = QPushButton('YoY')
        for button in (self.p2_qoq_btn, self.p2_yoy_btn):
            button.setCheckable(True)
            button.setFixedHeight(24)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(56)
            button.setStyleSheet('padding-left: 3px; padding-right: 3px;')
        self.p2_qoq_btn.setChecked(self.p2_growth_basis == P2_GROWTH_BASIS_PRIOR_PERIOD)
        self.p2_yoy_btn.setChecked(self.p2_growth_basis == P2_GROWTH_BASIS_YEAR_AGO)
        self.p2_qoq_btn.clicked.connect(partial(self._set_p2_growth_basis, P2_GROWTH_BASIS_PRIOR_PERIOD))
        self.p2_yoy_btn.clicked.connect(partial(self._set_p2_growth_basis, P2_GROWTH_BASIS_YEAR_AGO))
        self.p2_periods_lbl = QLabel('Periods')
        self.set_theme_role(self.p2_periods_lbl, 'muted')
        self.p2_periods_spin = QSpinBox()
        self.p2_periods_spin.setRange(P2_MIN_PERIODS, P2_MAX_PERIODS)
        self.p2_periods_spin.setValue(self.p2_period_count)
        self.p2_periods_spin.setFixedHeight(24)
        self.p2_periods_spin.setMinimumWidth(64)
        self.p2_periods_spin.setToolTip('How many years or quarters the overview charts show.')
        self.p2_periods_spin.valueChanged.connect(self._p2_on_period_count_changed)
        self.p2_indexed_btn = QPushButton('Indexed')
        self.p2_indexed_btn.setCheckable(True)
        self.p2_indexed_btn.setChecked(self.p2_indexed)
        self.p2_indexed_btn.setFixedHeight(24)
        self.p2_indexed_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.p2_indexed_btn.setMinimumWidth(74)
        self.p2_indexed_btn.setStyleSheet('padding-left: 3px; padding-right: 3px;')
        self.p2_indexed_btn.setToolTip(
            'Rebase every series so the oldest visible period reads 100.\n'
            'Use it when comparing companies whose absolute figures differ by orders of magnitude,\n'
            'where the smaller one would otherwise be crushed into the axis.'
        )
        self.p2_indexed_btn.clicked.connect(self._p2_on_indexed_toggle)
        period_row.addWidget(self.p2_growth_lbl)
        period_row.addSpacing(6)
        period_row.addWidget(self.p2_qoq_btn)
        period_row.addSpacing(4)
        period_row.addWidget(self.p2_yoy_btn)
        period_row.addSpacing(16)
        period_row.addWidget(self.p2_periods_lbl)
        period_row.addSpacing(6)
        period_row.addWidget(self.p2_periods_spin)
        period_row.addSpacing(10)
        period_row.addWidget(self.p2_indexed_btn)
        self._p2_sync_growth_controls()
        self.p2_statements_layout.addWidget(self.p2_period_widget)

        self.p2_workspace_stack = QStackedWidget()

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
        self.p2_chart_cards = []
        self.p2_expand_buttons = []
        self.p2_chart_models = []
        self.p2_chart_hover_proxies = []
        self.p2_fullscreen_dialog = None
        for chart_index, title in enumerate(
            ['Revenue', 'Net Income', 'Cash Flow', 'Shares Outstanding', 'Cash and Bonds & Total Debt', 'Operating Expenses']
        ):
            card = self._p2_create_chart_card(title, chart_index)
            self.p2_chart_cards.append(card)
            self.p2_chart_frames.append(card['frame'])
            self.p2_simple_titles.append(card['title'])
            self.p2_simple_legend_bars.append(card['legend'])
            self.p2_simple_charts.append(card['plot'])
            self.p2_expand_buttons.append(card['expand'])
        default_layout.addWidget(self.p2_charts_box, 1)
        self.p2_workspace_stack.addWidget(self.p2_default_workspace)
        self.p2_statements_layout.addWidget(self.p2_workspace_stack, 1)

        self._apply_fundamentals_theme()
        self._p2_relayout_charts()

    def _p2_build_metrics_row(self) -> tuple[Any, Any, dict[str, Any]]:
        """Build one headline-metric row plus its ticker chip.

        A widget rather than a bare layout so the compare row can be hidden; QHBoxLayout has no
        setVisible.
        """
        row_widget = QWidget()
        row_widget.setStyleSheet('background: transparent;')
        metrics_row = QHBoxLayout(row_widget)
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(10)
        ticker_label = QLabel('')
        ticker_label.setVisible(False)
        metrics_row.addWidget(ticker_label)
        metric_defs = [
            ('P/E', 'pe'),
            ('Fwd P/E', 'fpe'),
            ('P/S', 'ps'),
            ('PEG', 'peg'),
            ('FCF Mgn', 'fcf_margin'),
            ('EV/Rev', 'ev_rev'),
            ('EV/EBITDA', 'ev_ebitda'),
            ('Net Cash & Bonds', 'net_cash'),
            ('Beta', 'beta'),
            ('Mkt Cap', 'mktcap'),
        ]
        metric_vals = {}
        for label_text, key in metric_defs:
            pair = QHBoxLayout()
            pair.setSpacing(4)
            title_label = QLabel(f'{label_text}:')
            title_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
            value_label = QLabel('—')
            pair.addWidget(title_label)
            pair.addWidget(value_label)
            metrics_row.addLayout(pair)
            metric_vals[key] = value_label
        metrics_row.addStretch()
        return (row_widget, ticker_label, metric_vals)

    def _p2_set_metrics_ticker(self, label: Any, ticker: Any, slot: str) -> None:
        """Label one metrics row with its ticker, shown only while comparing."""
        text = str(ticker or '').upper().strip()
        label.setText(text)
        label.setVisible(bool(text) and self._p2_compare_active())
        color = self.theme_series_color(0) if slot == 'primary' else self.theme_series_color(1)
        label.setStyleSheet(f'font-size: 12px; font-weight: bold; color: {color};')

    def _p2_compare_active(self) -> bool:
        """Return whether a compare payload is currently overlaid."""
        return isinstance(getattr(self, 'p2_compare_data', None), dict)

    def _p2_sync_top_frame_height(self) -> None:
        """Size the header for one or two metric rows."""
        self.p2_top_frame.setFixedHeight(92 if self._p2_compare_active() else 66)

    def _p2_period_count(self) -> int:
        """Return how many statement periods the overview charts should show."""
        if hasattr(self, 'p2_periods_spin'):
            return int(self.p2_periods_spin.value())
        return int(getattr(self, 'p2_period_count', P2_DEFAULT_PERIODS) or P2_DEFAULT_PERIODS)

    def _p2_indexed_enabled(self) -> bool:
        """Return whether the overview charts are rebased to 100."""
        if hasattr(self, 'p2_indexed_btn'):
            return bool(self.p2_indexed_btn.isChecked())
        return bool(getattr(self, 'p2_indexed', False))

    def _p2_selected_growth_basis(self) -> str:
        """Return the growth basis the user has selected, ignoring the active period."""
        if hasattr(self, 'p2_yoy_btn'):
            return P2_GROWTH_BASIS_YEAR_AGO if self.p2_yoy_btn.isChecked() else P2_GROWTH_BASIS_PRIOR_PERIOD
        basis = str(getattr(self, 'p2_growth_basis', P2_DEFAULT_GROWTH_BASIS) or '')
        return basis if basis in P2_GROWTH_BASES else P2_DEFAULT_GROWTH_BASIS

    def _p2_growth_basis(self) -> str:
        """Return the growth basis the charts should actually use.

        Annual periods are already year-over-year, so the selection is ignored there. Forcing the
        prior-period basis keeps annual growth identical to what it has always been, and leaves a
        saved year-ago preference untouched by a trip through Annual mode.
        """
        if self._p2_period() == 'annual':
            return P2_GROWTH_BASIS_PRIOR_PERIOD
        return self._p2_selected_growth_basis()

    def _p2_sync_growth_controls(self) -> None:
        """Offer the growth basis only where it means something."""
        if not hasattr(self, 'p2_qoq_btn'):
            return
        quarterly = self._p2_period() == 'quarterly'
        tooltip = (
            'Measure each bar against the previous quarter (QoQ) or the same quarter a year\n'
            'earlier (YoY). Year-over-year is the basis that survives seasonality.'
            if quarterly
            else 'Annual periods are already year-over-year.'
        )
        for widget in (self.p2_growth_lbl, self.p2_qoq_btn, self.p2_yoy_btn):
            widget.setEnabled(quarterly)
            widget.setToolTip(tooltip)

    def _set_p2_growth_basis(self, basis: Any, *_: Any) -> None:
        """Switch which period each bar's growth figure is measured against."""
        resolved = str(basis or '')
        if resolved not in P2_GROWTH_BASES:
            resolved = P2_DEFAULT_GROWTH_BASIS
        self.p2_qoq_btn.setChecked(resolved == P2_GROWTH_BASIS_PRIOR_PERIOD)
        self.p2_yoy_btn.setChecked(resolved == P2_GROWTH_BASIS_YEAR_AGO)
        self.p2_growth_basis = resolved
        self._p2_schedule_overview_refresh()

    def _p2_schedule_overview_refresh(self) -> None:
        """Coalesce rapid control changes into one overview rerender.

        A spinbox emits per arrow click and per keystroke, and each rerender rebuilds six models and
        runs the superlinear annotation layout, so the trailing edge is the only one worth drawing.
        """
        timer = getattr(self, '_p2_overview_refresh_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(self._p2_apply_overview_controls)
            self._p2_overview_refresh_timer = timer
        timer.start()

    def _p2_apply_overview_controls(self) -> None:
        """Rerender the overview for the current display controls, then persist."""
        self.p2_period_count = self._p2_period_count()
        self.p2_indexed = self._p2_indexed_enabled()
        self.p2_growth_basis = self._p2_selected_growth_basis()
        if self.p2_current_data is not None:
            self._render_simple_charts(self.p2_current_data, self._p2_period())
            self._p2_relayout_charts()
        self._p2_persist_settings()
        self._p2_save_session_snapshot()

    def _p2_on_period_count_changed(self, _value: Any=None) -> None:
        """Handle a Periods change. Presentation only, so no refetch."""
        self._p2_schedule_overview_refresh()

    def _p2_on_indexed_toggle(self, *_: Any) -> None:
        """Handle the Indexed toggle."""
        self._p2_schedule_overview_refresh()

    def _p2_sync_periods_availability(self) -> None:
        """Report how many periods the loaded payloads actually offer.

        The spinbox range is shared across Annual and Quarterly deliberately: clamping the maximum
        per period mode would silently rewrite the saved value on every toggle.
        """
        if not hasattr(self, 'p2_periods_spin'):
            return
        available = max(
            (int(model.get('available_columns', 0) or 0) for model in getattr(self, 'p2_chart_models', [])),
            default=0,
        )
        period_word = 'years' if self._p2_period() == 'annual' else 'quarters'
        if available:
            self.p2_periods_spin.setToolTip(
                f'How many years or quarters the overview charts show.\n'
                f'{available} {period_word} available for the loaded data.'
            )
        else:
            self.p2_periods_spin.setToolTip('How many years or quarters the overview charts show.')

    def _p2_create_chart_card(self, title: str, chart_index: int) -> dict[str, Any]:
        """Create one reusable Fundamentals chart card."""
        frame = QFrame()
        self.set_theme_role(frame, 'panel')
        frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        frame.setMinimumWidth(0)
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
        expand_button = QToolButton()
        expand_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        expand_button.setFixedSize(24, 24)
        expand_button.setEnabled(False)
        expand_button.setToolTip(f'Open {title} fullscreen')
        expand_button.setAccessibleName(f'Open {title} fullscreen')
        expand_button.clicked.connect(partial(self._p2_open_fullscreen_chart, chart_index))
        title_row.addWidget(expand_button)
        plot_widget = pg.PlotWidget(axisItems={'left': FmtAxisItem(orientation='left')})
        plot_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        plot_widget.setMinimumWidth(0)
        plot_widget.getPlotItem().hideButtons()
        plot_widget.getPlotItem().setMenuEnabled(False)
        plot_widget.setMouseEnabled(x=False, y=False)
        plot_widget.showGrid(x=False, y=True, alpha=0.15)
        self.style_plot_widget(plot_widget)
        self._p2_register_chart_hover(plot_widget)
        frame_layout.addLayout(title_row)
        frame_layout.addWidget(plot_widget)
        return {
            'frame': frame,
            'title': title_label,
            'legend': legend_bar,
            'plot': plot_widget,
            'expand': expand_button,
        }

    def _p2_open_fullscreen_chart(self, chart_index: int, *_: Any) -> None:
        """Open one of the six Fundamentals overviews on the current screen."""
        data = getattr(self, 'p2_current_data', None)
        if not isinstance(data, dict):
            return
        period = self._p2_period()
        period_count = self._p2_period_count()
        indexed = self._p2_indexed_enabled()
        growth_basis = self._p2_growth_basis()
        compare_ticker = str(getattr(self, 'p2_compare_ticker', '') or '').upper().strip() if self._p2_compare_active() else ''
        models = list(getattr(self, 'p2_chart_models', []))
        stale = len(models) != 6 or any(
            model.get('period') != period
            or model.get('period_count') != period_count
            or bool(model.get('indexed')) != indexed
            or model.get('growth_basis') != growth_basis
            for model in models
        )
        if stale or compare_ticker != getattr(self, '_p2_rendered_compare_ticker', ''):
            self._render_simple_charts(data, period)
            models = list(getattr(self, 'p2_chart_models', []))
        if not 0 <= chart_index < len(models):
            return

        active_dialog = getattr(self, 'p2_fullscreen_dialog', None)
        if active_dialog is not None:
            active_dialog.close()

        model = models[chart_index]
        ticker = str(data.get('ticker', '') or self.p2_ticker_input.text() or '').upper().strip()
        if compare_ticker:
            ticker = f'{ticker} vs {compare_ticker}'
        period_label = 'Annual' if period == 'annual' else 'Quarterly'
        if indexed:
            period_label = f'{period_label}, Indexed'
        dialog = _FundamentalsFullscreenDialog(self)
        dialog.setWindowTitle(f'{ticker} - {model["title"]} ({period_label})')
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setModal(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title_label = QLabel(f'{ticker} - {model["title"]}')
        title_label.setStyleSheet(
            f'font-size: 20px; font-weight: bold; color: {self.theme_color("text_primary")};'
        )
        context_label = QLabel(period_label)
        self.set_theme_role(context_label, 'muted')
        legend_bar = QWidget()
        legend_layout = QHBoxLayout(legend_bar)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.setSpacing(6)
        close_button = QPushButton('Close')
        close_button.setFixedHeight(28)
        close_button.clicked.connect(dialog.close)
        header.addWidget(title_label)
        header.addWidget(context_label)
        header.addStretch()
        header.addWidget(legend_bar)
        header.addSpacing(12)
        header.addWidget(close_button)
        layout.addLayout(header)

        no_data_label = QLabel('No data for this period.')
        no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(no_data_label, 'muted')
        no_data_label.setVisible(not self._p2_chart_model_has_data(model))
        layout.addWidget(no_data_label)
        plot_widget = pg.PlotWidget(axisItems={'left': FmtAxisItem(orientation='left')})
        plot_widget.getPlotItem().hideButtons()
        plot_widget.getPlotItem().setMenuEnabled(False)
        plot_widget.setMouseEnabled(x=False, y=False)
        plot_widget.showGrid(x=False, y=True, alpha=0.15)
        self.style_plot_widget(plot_widget)
        self._p2_register_chart_hover(plot_widget, owner=dialog)
        layout.addWidget(plot_widget, 1)

        escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog)
        escape_shortcut.activated.connect(dialog.close)
        dialog._p2_escape_shortcut = escape_shortcut
        dialog._p2_plot = plot_widget
        dialog._p2_model = model
        self._p2_render_chart_model(plot_widget, legend_bar, model, fullscreen=True)
        dialog.resized.connect(lambda: QTimer.singleShot(0, partial(self._p2_layout_chart_annotations, plot_widget)))
        dialog.finished.connect(lambda *_: self._p2_clear_fullscreen_dialog(dialog))
        self.p2_fullscreen_dialog = dialog

        dialog.create()
        handle = dialog.windowHandle()
        current_screen = self.windowHandle().screen() if self.windowHandle() is not None else self.screen()
        if handle is not None and current_screen is not None:
            handle.setScreen(current_screen)
        dialog.showFullScreen()
        QTimer.singleShot(0, partial(self._p2_layout_chart_annotations, plot_widget))

    def _p2_clear_fullscreen_dialog(self, dialog: Any) -> None:
        """Release the tracked fullscreen dialog after it closes."""
        if getattr(self, 'p2_fullscreen_dialog', None) is dialog:
            self.p2_fullscreen_dialog = None

    def _p2_relayout_charts(self) -> None:
        """Resize and reflow the Fundamentals chart grid."""
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
        self._p2_schedule_chart_density_refresh()

    def _p2_schedule_chart_density_refresh(self) -> None:
        """Coalesce resize-driven rerenders so label density follows the final chart widths."""
        if getattr(self, '_p2_chart_density_refresh_pending', False):
            return
        self._p2_chart_density_refresh_pending = True
        QTimer.singleShot(0, self._p2_refresh_chart_density)

    def _p2_refresh_chart_density(self) -> None:
        """Rerender chart annotations after layout geometry has settled."""
        self._p2_chart_density_refresh_pending = False
        data = getattr(self, 'p2_current_data', None)
        if data is None:
            return
        period = self._p2_period()
        self._render_simple_charts(data, period)

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
            # Only the compare ticker, never its payload: the fundamentals session budget is
            # 250_000 chars and an oversized snapshot is discarded whole, taking the primary
            # ticker's restore with it. analyze_stock_p2 re-fetches the overlay on restore.
            'compare_ticker': str(getattr(self, 'p2_compare_ticker', '') or '').upper().strip(),
            'period_count': self._p2_period_count(),
            'indexed': self._p2_indexed_enabled(),
            'growth_basis': self._p2_selected_growth_basis(),
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
        # Restore the display controls with signals blocked so the debounced rerender does not fire
        # against half-applied state; update_page2 below draws once with everything in place.
        self._p2_apply_display_controls(
            payload.get('period_count'),
            payload.get('indexed'),
            str(payload.get('compare_ticker', '') or ''),
            payload.get('growth_basis'),
        )
        self.update_page2(
            restored_data,
            update_collection_info=False,
            status_text=self._p2_status_text_for_payload(restored_data, restored=True),
        )
        period = str(payload.get('period', 'annual') or 'annual').strip().lower()
        if period in {'annual', 'quarterly'}:
            self._set_p2_period(period)
        return True

    def _p2_apply_display_controls(
        self,
        period_count: Any,
        indexed: Any,
        compare_ticker: Any,
        growth_basis: Any=None,
    ) -> None:
        """Push persisted display settings onto the widgets without triggering a rerender."""
        try:
            resolved_count = int(period_count)
        except (TypeError, ValueError):
            resolved_count = self._p2_period_count()
        resolved_count = max(P2_MIN_PERIODS, min(P2_MAX_PERIODS, resolved_count))
        resolved_indexed = bool(indexed) if isinstance(indexed, bool | int) else self._p2_indexed_enabled()
        resolved_compare = str(compare_ticker or '').upper().strip()[:12]
        resolved_basis = str(growth_basis or '').lower().strip()
        if resolved_basis not in P2_GROWTH_BASES:
            resolved_basis = self._p2_selected_growth_basis()
        self.p2_period_count = resolved_count
        self.p2_indexed = resolved_indexed
        self.p2_compare_ticker = resolved_compare
        self.p2_growth_basis = resolved_basis
        for widget, setter, value in (
            (getattr(self, 'p2_periods_spin', None), 'setValue', resolved_count),
            (getattr(self, 'p2_indexed_btn', None), 'setChecked', resolved_indexed),
            (getattr(self, 'p2_compare_input', None), 'setText', resolved_compare),
            (getattr(self, 'p2_qoq_btn', None), 'setChecked', resolved_basis == P2_GROWTH_BASIS_PRIOR_PERIOD),
            (getattr(self, 'p2_yoy_btn', None), 'setChecked', resolved_basis == P2_GROWTH_BASIS_YEAR_AGO),
        ):
            if widget is None:
                continue
            widget.blockSignals(True)
            try:
                getattr(widget, setter)(value)
            finally:
                widget.blockSignals(False)

    def _p2_restore_startup_session(self, snapshot: Any) -> None:
        """Hydrate Fundamentals from the last session, then refresh it in the background."""
        restored = self._p2_restore_session_snapshot(snapshot)
        ticker = str(getattr(self, 'p2_ticker_input', None).text() if hasattr(self, 'p2_ticker_input') else '').upper().strip()
        if restored and ticker:
            self.analyze_stock_p2(update_collection_info=False)

    def _p2_apply_runtime_state(self) -> None:
        """Apply the persisted Fundamentals state to the live page widgets."""
        state = getattr(self, 'fundamentals_page_state', load_fundamentals_page_settings())
        saved_last_ticker = str(state.get('last_ticker', '') or '').upper().strip()
        loaded_ticker = ''
        if isinstance(getattr(self, 'p2_current_data', None), dict):
            loaded_ticker = str(self.p2_current_data.get('ticker', '') or '').upper().strip()
        self.p2_last_ticker = loaded_ticker or saved_last_ticker
        if hasattr(self, 'p2_ticker_input'):
            self.p2_ticker_input.setText(self.p2_last_ticker)
        loaded_compare = ''
        if isinstance(getattr(self, 'p2_compare_data', None), dict):
            loaded_compare = str(self.p2_compare_data.get('ticker', '') or '').upper().strip()
        self._p2_apply_display_controls(
            state.get('period_count', P2_DEFAULT_PERIODS),
            state.get('indexed', False),
            loaded_compare or str(state.get('compare_ticker', '') or ''),
            state.get('growth_basis', P2_DEFAULT_GROWTH_BASIS),
        )
        self._p2_sync_growth_controls()
        if self.p2_current_data is not None:
            self._render_simple_charts(self.p2_current_data, self._p2_period())
        self._p2_relayout_charts()

    def analyze_stock_p2(self, *_: Any, update_collection_info: bool=True) -> bool | None:
        """Load Fundamentals for the requested ticker, refreshing any compare overlay with it."""
        ticker = self.p2_ticker_input.text().upper().strip()
        if not ticker:
            return
        self.p2_last_ticker = ticker
        self._p2_persist_settings()
        result = self._p2_start_fetch(ticker, 'primary', update_collection_info=bool(update_collection_info))
        compare_ticker = str(self.p2_compare_input.text() or '').upper().strip()
        if compare_ticker and compare_ticker != ticker:
            # A busy compare slot must not leak False: the startup dispatcher counts a dispatch only
            # when the call does not return False, and this refresh is about the primary ticker.
            self._p2_start_fetch(compare_ticker, 'compare', update_collection_info=False)
        return result

    def _p2_start_fetch(self, ticker: str, slot: str, *, update_collection_info: bool) -> bool | None:
        """Start one Fundamentals fetch in the named slot, or report that slot busy."""
        thread = self.p2_fund_threads.get(slot)
        if thread is not None and thread.isRunning():
            return False
        self._p2_request_seq += 1
        request_id = self._p2_request_seq
        self._p2_active_request_ids[slot] = request_id
        self._p2_request_contexts[request_id] = {
            'slot': slot,
            'update_collection_info': bool(update_collection_info),
        }
        if slot == 'primary':
            self.p2_analyze_btn.setEnabled(False)
            self.set_status_text(self.p2_status_lbl, f'Loading {ticker}...', status='warning')
        else:
            self.set_status_text(self.p2_compare_status_lbl, f'Loading {ticker}...', status='warning')
        worker = FundamentalsWorker(ticker)
        thread = QThread()
        self.p2_fund_workers[slot] = worker
        self.p2_fund_threads[slot] = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda data, req=request_id: self._p2_handle_result(req, data))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda msg, req=request_id: self._page2_error(req, msg))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # The slot travels through the lambda because _p2_handle_result pops the request context
        # before thread.finished fires, so it cannot be recovered from there.
        thread.finished.connect(
            lambda s=slot, req=request_id, w=worker, t=thread: self._p2_cleanup_worker_refs(s, req, w, t)
        )
        thread.start()

    def _p2_apply_compare(self, *_: Any) -> None:
        """Load the typed compare ticker as an overlay on the current charts."""
        ticker = str(self.p2_compare_input.text() or '').upper().strip()
        self.p2_compare_input.setText(ticker)
        if not ticker:
            self._p2_clear_compare()
            return
        if ticker == str(self.p2_ticker_input.text() or '').upper().strip():
            self.set_status_text(
                self.p2_compare_status_lbl,
                'Pick a different ticker to compare against.',
                status='warning',
            )
            return
        self._p2_start_fetch(ticker, 'compare', update_collection_info=False)

    def _p2_clear_compare(self, *_: Any) -> None:
        """Drop the compare overlay and return the page to its single-ticker layout."""
        self.p2_compare_data = None
        self.p2_compare_ticker = ''
        self._p2_pending_results.pop('compare', None)
        self.p2_compare_input.clear()
        self.p2_compare_clear_btn.setEnabled(False)
        self.p2_compare_metrics_widget.setVisible(False)
        self.p2_compare_status_lbl.clear()
        self._p2_set_metrics_ticker(self.p2_metric_ticker_lbl, self.p2_last_ticker, 'primary')
        self._p2_sync_top_frame_height()
        if self.p2_current_data is not None:
            self._render_simple_charts(self.p2_current_data, self._p2_period())
        self._p2_relayout_charts()
        self._p2_persist_settings()
        self._p2_save_session_snapshot()

    def _p2_handle_compare_result(self, data: Any) -> None:
        """Overlay one compare payload onto the loaded primary ticker."""
        payload = data if isinstance(data, dict) else {}
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        self.p2_compare_data = payload
        self.p2_compare_ticker = ticker
        self.p2_compare_clear_btn.setEnabled(True)
        self.set_status_text(
            self.p2_compare_status_lbl,
            f'vs {ticker}  |  source: {self._p2_source_label(payload)}',
            status='positive',
        )
        self._p2_apply_headline_metrics(
            self._p2_compute_headline_metrics(payload),
            self.p2_compare_metric_vals,
        )
        self.p2_compare_metrics_widget.setVisible(True)
        self._p2_set_metrics_ticker(self.p2_compare_metric_ticker_lbl, ticker, 'compare')
        primary_data = self.p2_current_data if isinstance(self.p2_current_data, dict) else {}
        self._p2_set_metrics_ticker(
            self.p2_metric_ticker_lbl,
            str(primary_data.get('ticker', '') or self.p2_last_ticker),
            'primary',
        )
        self._p2_sync_top_frame_height()
        # Compare is an overlay, so with no primary payload there is nothing to draw it against.
        if self.p2_current_data is not None:
            self._render_simple_charts(self.p2_current_data, self._p2_period())
        self._p2_relayout_charts()
        self._p2_persist_settings()
        self._p2_save_session_snapshot()

    def _p2_cleanup_worker_refs(self, slot: str, request_id: int, worker: Any, thread: Any) -> None:
        """Clear stale Fundamentals worker references after Qt has finished the thread."""
        if self.p2_fund_workers.get(slot) is worker:
            self.p2_fund_workers[slot] = None
        if self.p2_fund_threads.get(slot) is thread:
            self.p2_fund_threads[slot] = None
        self._p2_request_contexts.pop(request_id, None)

    def _p2_handle_result(self, request_id: int, data: Any) -> None:
        """Apply one Fundamentals response only when it is still current."""
        context = self._p2_request_contexts.pop(request_id, {})
        slot = str(context.get('slot', 'primary'))
        if request_id != self._p2_active_request_ids.get(slot, 0):
            return
        if not self._p2_page_is_visible():
            self._p2_pending_results[slot] = (data, context)
            if slot == 'primary':
                self.p2_analyze_btn.setEnabled(True)
            return
        self._p2_deliver_result(slot, data, context)

    def _p2_deliver_result(self, slot: str, data: Any, context: dict[str, Any]) -> None:
        """Route one settled response to the primary page render or to the compare overlay."""
        if slot == 'compare':
            self._p2_handle_compare_result(data)
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
        # Primary first: the compare overlay renders against the primary payload.
        for slot in ('primary', 'compare'):
            pending = self._p2_pending_results.pop(slot, None)
            if isinstance(pending, tuple) and len(pending) == 2:
                data, context = pending
                self._p2_deliver_result(slot, data, context)
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
        current_request_id = request_id if msg is not None else self._p2_active_request_ids.get('primary', 0)
        try:
            numeric_request_id = int(current_request_id)
        except (TypeError, ValueError):
            numeric_request_id = int(self._p2_active_request_ids.get('primary', 0) or 0)
        context = self._p2_request_contexts.pop(numeric_request_id, {})
        slot = str(context.get('slot', 'primary'))
        if numeric_request_id != self._p2_active_request_ids.get(slot, 0):
            return
        if slot == 'compare':
            # A failed compare fetch must leave the primary charts and status untouched.
            self.set_status_text(self.p2_compare_status_lbl, f'Compare error: {error_text}', status='negative')
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
        self._p2_sync_growth_controls()
        self._on_period_toggle()

    def _on_period_toggle(self) -> None:
        """Handle Annual / Quarterly toggles."""
        if self.p2_current_data is None:
            return
        self._render_simple_charts(self.p2_current_data, self._p2_period())
        self._p2_relayout_charts()
        self._p2_save_session_snapshot()

    def _apply_fundamentals_theme(self) -> None:
        """Refresh Fundamentals colors when the active theme changes."""
        self.p2_name_lbl.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p2_info_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.set_status_text(self.p2_status_lbl, self.p2_status_lbl.text(), status=self.p2_status_lbl.property('bt_status') or 'muted')
        self.set_status_text(
            self.p2_compare_status_lbl,
            self.p2_compare_status_lbl.text(),
            status=self.p2_compare_status_lbl.property('bt_status') or 'muted',
        )
        self.set_theme_role(self.p2_periods_lbl, 'muted')
        self.set_theme_role(self.p2_growth_lbl, 'muted')
        for label in getattr(self, 'p2_simple_titles', []):
            if label is not None:
                label.setStyleSheet(f'font-size: 14px; font-weight: bold; color: {self.theme_color("text_primary")}; background: transparent;')
        for metric_vals in (getattr(self, 'p2_metric_vals', {}), getattr(self, 'p2_compare_metric_vals', {})):
            for value_label in metric_vals.values():
                value_label.setStyleSheet(f'font-size: 17px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self._p2_set_metrics_ticker(self.p2_metric_ticker_lbl, self.p2_metric_ticker_lbl.text(), 'primary')
        self._p2_set_metrics_ticker(self.p2_compare_metric_ticker_lbl, self.p2_compare_metric_ticker_lbl.text(), 'compare')
        for plot_widget in getattr(self, 'p2_simple_charts', []):
            self.style_plot_widget(plot_widget)
        if self.p2_current_data is not None:
            self.update_page2(self.p2_current_data, update_collection_info=False, status_text=self.p2_status_lbl.text())
