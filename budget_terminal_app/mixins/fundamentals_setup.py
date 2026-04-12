from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.paths import user_data_path
from budget_terminal_app.workers.fundamentals import FundamentalsWorker

class FundamentalsSetupMixin:
    _P2_CONFIG_PATH = user_data_path('fundamentals_config.json')

    def init_page2(self, layout: Any) -> None:
        """Build the Deep Dive page UI (called once during init_ui)."""
        self._p2_request_seq = 0
        self._p2_active_request_id = 0
        self._p2_request_contexts = {}
        self.p2_website_url = ''
        self.p2_ir_url = ''
        search_row = QHBoxLayout()
        self.p2_ticker_input = QLineEdit()
        self.p2_ticker_input.setPlaceholderText('Enter any ticker (e.g. NVDA, MSFT, META)')
        self.p2_ticker_input.setFixedWidth(240)
        self.p2_ticker_input.returnPressed.connect(self.analyze_stock_p2)
        try:
            with self._P2_CONFIG_PATH.open() as _f:
                _cfg = json.load(_f)
            if _cfg.get('last_ticker'):
                self.p2_ticker_input.setText(_cfg['last_ticker'])
        except Exception:
            pass
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
        self.p2_name_lbl.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {self.theme_color("text_primary")};')
        top_row.addWidget(self.p2_name_lbl)
        self.p2_info_lbl = QLabel('—')
        self.p2_info_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
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
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f'color: {self.theme_color("panel_border")};')
        top_row.addWidget(div)
        metric_defs = [('P/E', 'pe'), ('Fwd P/E', 'fpe'), ('P/S', 'ps'), ('PEG', 'peg'), ('FCF Mgn', 'fcf_margin'), ('EV/Rev', 'ev_rev'), ('EV/EBITDA', 'ev_ebitda'), ('Net Cash', 'net_cash'), ('Beta', 'beta'), ('Mkt Cap', 'mktcap')]
        self.p2_metric_vals = {}
        for label, key in metric_defs:
            pair = QHBoxLayout()
            pair.setSpacing(4)
            lbl = QLabel(f'{label}:')
            lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
            val_lbl = QLabel('—')
            val_lbl.setStyleSheet(f'font-size: 14px; font-weight: bold; color: {self.theme_color("text_primary")};')
            pair.addWidget(lbl)
            pair.addWidget(val_lbl)
            top_row.addLayout(pair)
            self.p2_metric_vals[key] = val_lbl
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
        for btn in (self.p2_annual_btn, self.p2_quarterly_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(74)
            btn.setStyleSheet('padding-left: 3px; padding-right: 3px;')
        self.p2_annual_btn.setChecked(True)
        self.p2_annual_btn.clicked.connect(partial(self._set_p2_period, 'annual'))
        self.p2_quarterly_btn.clicked.connect(partial(self._set_p2_period, 'quarterly'))
        period_row.addWidget(self.p2_annual_btn)
        period_row.addSpacing(8)
        period_row.addWidget(self.p2_quarterly_btn)
        period_row.addSpacing(20)
        period_row.addStretch()
        self.p2_content_layout.addWidget(self.p2_period_widget)
        self.p2_charts_box = QGroupBox('Financial Overview')
        self.set_theme_role(self.p2_charts_box, 'panel')
        self.p2_charts_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.p2_charts_grid = QGridLayout(self.p2_charts_box)
        self.p2_charts_grid.setContentsMargins(12, 18, 12, 12)
        self.p2_charts_grid.setSpacing(12)
        simple_chart_titles = ['Revenue', 'Net Income', 'Cash Flow', 'Shares Outstanding', 'Cash & Total Debt', 'Operating Expenses']
        self.p2_simple_charts = []
        self.p2_simple_titles = []
        self.p2_simple_legend_bars = []
        self.p2_chart_frames = []
        for idx, title in enumerate(simple_chart_titles):
            frame = QFrame()
            self.set_theme_role(frame, 'panel')
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(10, 8, 10, 8)
            frame_layout.setSpacing(4)
            title_row = QHBoxLayout()
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(f'font-size: 14px; font-weight: bold; color: {self.theme_color("text_primary")}; background: transparent;')
            legend_bar = QWidget()
            legend_bar.setStyleSheet('background: transparent;')
            l_layout = QHBoxLayout(legend_bar)
            l_layout.setContentsMargins(0, 0, 0, 0)
            l_layout.setSpacing(6)
            title_row.addWidget(title_lbl)
            title_row.addStretch()
            title_row.addWidget(legend_bar)
            pw = pg.PlotWidget(axisItems={'left': FmtAxisItem(orientation='left')})
            pw.getPlotItem().hideButtons()
            pw.getPlotItem().setMenuEnabled(False)
            pw.setMouseEnabled(x=False, y=False)
            pw.showGrid(x=False, y=True, alpha=0.15)
            self.style_plot_widget(pw)
            frame_layout.addLayout(title_row)
            frame_layout.addWidget(pw)
            self.p2_simple_charts.append(pw)
            self.p2_simple_titles.append(title_lbl)
            self.p2_simple_legend_bars.append(legend_bar)
            self.p2_chart_frames.append(frame)
        self.p2_content_layout.addWidget(self.p2_charts_box, 1)
        self._p2_relayout_charts()

    def _p2_relayout_charts(self) -> None:
        """Resize and reflow fundamentals charts to keep all six visible."""
        if not hasattr(self, 'p2_charts_grid'):
            return
        frames = getattr(self, 'p2_chart_frames', [])
        if not frames:
            return
        page_width = self.page2.contentsRect().width() if hasattr(self, 'page2') else 0
        available_width = max(self.p2_charts_box.width(), page_width - 20)
        content_height = self.p2_content_widget.contentsRect().height() if hasattr(self, 'p2_content_widget') else 0
        spacing = self.p2_content_layout.spacing() if hasattr(self, 'p2_content_layout') else 0
        controls_height = self.p2_top_frame.height() + self.p2_period_widget.height() + spacing * 2
        available_height = max(240, content_height - controls_height)
        chart_count = len(frames)
        columns = 3 if available_width >= 1200 else 2
        rows = max(1, math.ceil(chart_count / columns))
        spacing = 12 if available_width >= 1200 and available_height >= 700 else 8
        chrome_height = 40
        min_chart_height = 160 if columns == 3 else 140
        grid_height = max(
            min_chart_height * rows + max(0, rows - 1) * spacing,
            available_height - chrome_height,
        )
        chart_height = max(
            min_chart_height,
            int((grid_height - max(0, rows - 1) * spacing) / rows),
        )
        plot_height = max(96, chart_height - 52)
        box_height = chrome_height + rows * chart_height + max(0, rows - 1) * spacing
        self.p2_charts_grid.setHorizontalSpacing(spacing)
        self.p2_charts_grid.setVerticalSpacing(spacing)
        self.p2_charts_box.setMinimumHeight(box_height)
        for col in range(3):
            self.p2_charts_grid.setColumnStretch(col, 0)
        while self.p2_charts_grid.count():
            item = self.p2_charts_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.p2_charts_box)
        for idx, frame in enumerate(frames):
            row_pos = idx // columns
            col_pos = idx % columns
            frame.setFixedHeight(chart_height)
            frame.layout().setContentsMargins(8, 6, 8, 6)
            self.p2_simple_charts[idx].setMinimumHeight(plot_height)
            self.p2_simple_charts[idx].setMaximumHeight(plot_height)
            self.p2_charts_grid.addWidget(frame, row_pos, col_pos)
        for col in range(columns):
            self.p2_charts_grid.setColumnStretch(col, 1)

    def _p2_status_text_for_payload(self, data: Any, *, restored: bool=False) -> str:
        """Build the user-facing status text for a fundamentals payload."""
        payload = data if isinstance(data, dict) else {}
        ticker = str(payload.get('ticker', '') or self.p2_ticker_input.text() or '').upper().strip()
        source = 'Alpha Vantage' if payload.get('av_used') else 'yfinance'
        if restored and ticker:
            return f'Restored last session for {ticker} | source: {source}'
        if ticker:
            return f'{ticker}  |  source: {source}'
        return f'Source: {source}'

    def _p2_session_snapshot(self) -> dict[str, Any] | None:
        """Return the current fundamentals workspace snapshot when data is loaded."""
        if not isinstance(getattr(self, 'p2_current_data', None), dict):
            return None
        ticker = str(self.p2_current_data.get('ticker', '') or '').upper().strip()
        if not ticker:
            return None
        return {
            'ticker': ticker,
            'period': self._p2_period() if hasattr(self, 'p2_annual_btn') else 'annual',
            'data': serialize_session_value(self.p2_current_data),
        }

    def _p2_save_session_snapshot(self, *, immediate: bool=False) -> None:
        """Persist the latest fundamentals workspace snapshot."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('fundamentals', self._p2_session_snapshot(), immediate=immediate)

    def _p2_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Restore the fundamentals workspace from a cached session snapshot."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        if ticker:
            self.p2_ticker_input.setText(ticker)
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
        """Hydrate fundamentals from the last session, then refresh it in the background."""
        restored = self._p2_restore_session_snapshot(snapshot)
        ticker = str(getattr(self, 'p2_ticker_input', None).text() if hasattr(self, 'p2_ticker_input') else '').upper().strip()
        if restored and ticker:
            self.analyze_stock_p2(update_collection_info=False)

    def analyze_stock_p2(self, *_: Any, update_collection_info: bool=True) -> None:
        """Handle analyze stock p2."""
        ticker = self.p2_ticker_input.text().upper().strip()
        if not ticker:
            return
        try:
            try:
                with self._P2_CONFIG_PATH.open() as _f:
                    _cfg = json.load(_f)
            except Exception:
                _cfg = {}
            _cfg['last_ticker'] = ticker
            with self._P2_CONFIG_PATH.open('w') as _f:
                json.dump(_cfg, _f)
        except Exception:
            pass
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
        """Apply one fundamentals response only when it is still current."""
        context = self._p2_request_contexts.pop(request_id, {})
        if request_id != getattr(self, '_p2_active_request_id', 0):
            return
        self.update_page2(
            data,
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _page2_error(self, request_id: Any, msg: Any=None) -> None:
        """Handle page2 error."""
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

    def _p2_period(self) -> Any:
        """Handle p2 period."""
        return 'annual' if self.p2_annual_btn.isChecked() else 'quarterly'

    def _set_p2_period(self, period: Any, *_: Any) -> None:
        """Handle set p2 period."""
        self.p2_annual_btn.setChecked(period == 'annual')
        self.p2_quarterly_btn.setChecked(period == 'quarterly')
        self._on_period_toggle()

    def _on_period_toggle(self) -> None:
        """Handle period toggle."""
        if self.p2_current_data is None:
            return
        period = self._p2_period()
        self._render_simple_charts(self.p2_current_data, period)
        self._p2_relayout_charts()
        self._p2_save_session_snapshot()

    def _apply_fundamentals_theme(self) -> None:
        """Refresh fundamentals colors when the active theme changes."""
        self.p2_name_lbl.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p2_info_lbl.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.set_status_text(self.p2_status_lbl, self.p2_status_lbl.text(), status=self.p2_status_lbl.property('bt_status') or 'muted')
        for pw in getattr(self, 'p2_simple_charts', []):
            self.style_plot_widget(pw)
