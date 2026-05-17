from __future__ import annotations
from typing import TYPE_CHECKING, Any
from ..compat import *

if TYPE_CHECKING:
    from budget_terminal_app.etf_holdings import EtfHoldingsResult

_P13_AUM_PAGE_SIZE = 250
_P13_MAX_NAMED_SLICES = 12
_P13_MIN_REMAINDER_WEIGHT = 0.001


class _AumTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by its raw numeric AUM value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(Qt.ItemDataRole.UserRole))
            right = float(other.data(Qt.ItemDataRole.UserRole))
            return left < right
        except Exception:
            return super().__lt__(other)


class EtfAnalyserMixin:
    def _p13_build_service(self) -> Any:
        """Import and construct the ETF holdings service only when the page is initialized."""
        from budget_terminal_app.etf_holdings import EtfHoldingsService

        return EtfHoldingsService()

    def init_page13(self) -> None:
        """Build the ETF analyser page UI."""
        self._p13_request_seq = 0
        self._p13_active_request_id = 0
        self._p13_request_contexts = {}
        self._p13_rows: list[dict[str, Any]] = []
        self._p13_last_result = None
        self._p13_service = self._p13_build_service()
        self._p13_aum_cache: dict[str, float] = {}
        self._p13_aum_fetch_in_progress: bool = False
        self._p13_aum_missing_count: int = 0
        self._p13_aum_total_count: int = 0

        outer_layout = QHBoxLayout(self.page13)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.p13_left_panel = self._p13_build_aum_panel()
        splitter.addWidget(self.p13_left_panel)

        right_widget = QWidget()
        layout = QVBoxLayout(right_widget)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer_layout.addWidget(splitter)

        title_row = QHBoxLayout()
        self.p13_title_lbl = QLabel('<b>ETF</b>')
        self.set_theme_role(self.p13_title_lbl, 'page_title')
        title_row.addWidget(self.p13_title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        self.p13_controls_frame = QFrame()
        controls_layout = QHBoxLayout(self.p13_controls_frame)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        controls_layout.setSpacing(10)

        self.p13_symbol_lbl = QLabel('ETF:')
        self.p13_etf_input = QLineEdit()
        self.p13_etf_input.setPlaceholderText('Enter ETF ticker (e.g. SPY, QQQ, VOO)')
        self.p13_etf_input.setMinimumWidth(220)
        self.p13_etf_input.returnPressed.connect(self._p13_load_etf)
        self.p13_load_btn = QPushButton('Load Holdings')
        self.set_theme_variant(self.p13_load_btn, 'accent')
        self.p13_load_btn.clicked.connect(self._p13_load_etf)
        controls_layout.addWidget(self.p13_symbol_lbl)
        controls_layout.addWidget(self.p13_etf_input)
        self.p13_export_btn = QPushButton('Export')
        self.p13_export_btn.clicked.connect(self._p13_export_clipboard)
        controls_layout.addWidget(self.p13_load_btn)
        controls_layout.addWidget(self.p13_export_btn)
        controls_layout.addStretch()
        layout.addWidget(self.p13_controls_frame)

        self.p13_summary_frame = QFrame()
        summary_layout = QGridLayout(self.p13_summary_frame)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(8)

        self.p13_name_lbl = QLabel('Fund: --')
        self.p13_category_lbl = QLabel('Issuer: --')
        self.p13_family_lbl = QLabel('As Of: --')
        self.p13_expense_lbl = QLabel('Expense Ratio: --')
        self.p13_assets_lbl = QLabel('Net Assets: --')
        self.p13_count_lbl = QLabel('Holdings Loaded: 0')
        for label in (
            self.p13_name_lbl,
            self.p13_category_lbl,
            self.p13_family_lbl,
            self.p13_expense_lbl,
            self.p13_assets_lbl,
            self.p13_count_lbl,
        ):
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        summary_layout.addWidget(self.p13_name_lbl, 0, 0)
        summary_layout.addWidget(self.p13_category_lbl, 0, 1)
        summary_layout.addWidget(self.p13_family_lbl, 0, 2)
        summary_layout.addWidget(self.p13_expense_lbl, 1, 0)
        summary_layout.addWidget(self.p13_assets_lbl, 1, 1)
        summary_layout.addWidget(self.p13_count_lbl, 1, 2)
        layout.addWidget(self.p13_summary_frame)

        self.p13_sectors_lbl = QLabel('')
        self.p13_sectors_lbl.setWordWrap(True)
        self.p13_sectors_lbl.setVisible(False)
        layout.addWidget(self.p13_sectors_lbl)

        self.p13_status_lbl = QLabel('Enter an ETF ticker to load holdings from supported official issuer sources.')
        self.set_theme_role(self.p13_status_lbl, 'status_muted')
        layout.addWidget(self.p13_status_lbl)

        self.p13_chart_frame = QFrame()
        chart_layout = QVBoxLayout(self.p13_chart_frame)
        chart_layout.setContentsMargins(12, 10, 12, 10)
        chart_layout.setSpacing(8)
        self.p13_chart_title_lbl = QLabel('Holdings Breakdown')
        self.set_theme_role(self.p13_chart_title_lbl, 'card_title')
        chart_layout.addWidget(self.p13_chart_title_lbl)
        self.p13_holdings_pie = PieChartWidget()
        self.p13_holdings_pie.setMinimumHeight(240)
        self.p13_holdings_pie.set_donut(True, hole_ratio=0.58)
        chart_layout.addWidget(self.p13_holdings_pie, 1)
        self.p13_chart_frame.setVisible(True)
        self.p13_chart_frame.setMinimumWidth(360)

        self.p13_table = QTableWidget(0, 3)
        self.p13_table.setHorizontalHeaderLabels(['Ticker', 'Name', 'Weight'])
        hh = self.p13_table.horizontalHeader()
        hh.setMinimumHeight(28)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionsMovable(True)
        self.p13_table.verticalHeader().setVisible(False)
        self.p13_table.verticalHeader().setDefaultSectionSize(28)
        self.p13_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p13_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p13_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p13_table.setAlternatingRowColors(True)
        self.p13_table.setSortingEnabled(True)
        self.p13_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.p13_holdings_row = QHBoxLayout()
        self.p13_holdings_row.setSpacing(10)
        self.p13_holdings_row.addWidget(self.p13_table, 3)
        self.p13_holdings_row.addWidget(self.p13_chart_frame, 2)
        layout.addLayout(self.p13_holdings_row, 1)

        self._apply_etf_theme()
        self._p13_show_holdings_chart_placeholder()

        self._p13_fetch_aum_universe()

    def _p13_result_to_snapshot(self, result: Any) -> dict[str, Any] | None:
        """Convert one ETF result into a JSON-safe session snapshot."""
        if result is None:
            return None
        holdings = []
        for holding in list(getattr(result, 'holdings', []) or []):
            holdings.append({
                'symbol': str(getattr(holding, 'symbol', '') or '').upper().strip(),
                'name': str(getattr(holding, 'name', '') or '').strip(),
                'weight': getattr(holding, 'weight', None),
                'sector': str(getattr(holding, 'sector', '') or '').strip(),
            })
        return {
            'ticker': str(getattr(result, 'ticker', '') or '').upper().strip(),
            'fund_name': str(getattr(result, 'fund_name', '') or '').strip(),
            'issuer': str(getattr(result, 'issuer', '') or '').strip(),
            'as_of_date': str(getattr(result, 'as_of_date', '') or '').strip(),
            'expense_ratio': str(getattr(result, 'expense_ratio', '--') or '--').strip(),
            'net_assets': str(getattr(result, 'net_assets', '--') or '--').strip(),
            'sector_breakdown': serialize_session_value(getattr(result, 'sector_breakdown', {}) or {}),
            'source_url': str(getattr(result, 'source_url', '') or '').strip(),
            'is_partial': bool(getattr(result, 'is_partial', False)),
            'coverage_note': str(getattr(result, 'coverage_note', '') or '').strip(),
            'holdings': serialize_session_value(holdings),
        }

    def _p13_snapshot_to_result(self, snapshot: Any) -> Any:
        """Rebuild one ETF holdings result from cached session data."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        if not ticker:
            return None
        from budget_terminal_app.etf_holdings import EtfHolding, EtfHoldingsResult

        holdings = []
        for holding in deserialize_session_value(payload.get('holdings')) or []:
            if not isinstance(holding, dict):
                continue
            holdings.append(EtfHolding(
                symbol=str(holding.get('symbol', '') or '').upper().strip(),
                name=str(holding.get('name', '') or '').strip(),
                weight=holding.get('weight'),
                sector=str(holding.get('sector', '') or '').strip(),
            ))
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=str(payload.get('fund_name', '') or '').strip(),
            issuer=str(payload.get('issuer', '') or '').strip(),
            as_of_date=str(payload.get('as_of_date', '') or '').strip(),
            expense_ratio=str(payload.get('expense_ratio', '--') or '--').strip(),
            net_assets=str(payload.get('net_assets', '--') or '--').strip(),
            holdings=holdings,
            sector_breakdown=deserialize_session_value(payload.get('sector_breakdown')) or {},
            source_url=str(payload.get('source_url', '') or '').strip(),
            is_partial=bool(payload.get('is_partial', False)),
            coverage_note=str(payload.get('coverage_note', '') or '').strip(),
        )

    def _p13_session_snapshot(self) -> dict[str, Any] | None:
        """Return the current ETF workspace snapshot when data is loaded."""
        result = getattr(self, '_p13_last_result', None)
        payload = self._p13_result_to_snapshot(result)
        if not isinstance(payload, dict):
            return None
        payload['input_ticker'] = str(self.p13_etf_input.text() or payload.get('ticker', '') or '').upper().strip()
        return payload

    def _p13_save_session_snapshot(self, *, immediate: bool=False) -> None:
        """Persist the latest ETF workspace snapshot."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('etf', self._p13_session_snapshot(), immediate=immediate)

    def _p13_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Restore the ETF workspace from cached session data."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        input_ticker = str(payload.get('input_ticker', '') or payload.get('ticker', '') or '').upper().strip()
        if input_ticker:
            self.p13_etf_input.setText(input_ticker)
        result = self._p13_snapshot_to_result(payload)
        if result is None:
            return False
        self._p13_apply_result(
            result,
            update_collection_info=False,
            status_text=f'Restored last session for {result.ticker}.',
        )
        return True

    def _p13_restore_startup_session(self, snapshot: Any) -> None:
        """Hydrate ETF from the last session, then refresh it in the background."""
        restored = self._p13_restore_session_snapshot(snapshot)
        ticker = str(self.p13_etf_input.text() or '').upper().strip()
        if restored and ticker:
            self._p13_load_etf(update_collection_info=False)

    def _p13_load_etf(self, *_: Any, update_collection_info: bool=True) -> None:
        """Fetch ETF holdings data using supported official issuer sources."""
        ticker = self.p13_etf_input.text().upper().strip()
        if not ticker:
            self.set_status_text(self.p13_status_lbl, 'Enter an ETF ticker first.', status='warning')
            return
        self._p13_request_seq += 1
        request_id = self._p13_request_seq
        self._p13_active_request_id = request_id
        self._p13_request_contexts[request_id] = {
            'update_collection_info': bool(update_collection_info),
        }
        self._p13_show_holdings_chart_placeholder('Loading', 'Breakdown')
        self.set_status_text(self.p13_status_lbl, f'Loading ETF holdings for {ticker} from official issuer sources...', status='warning')
        self.p13_load_btn.setEnabled(False)

        def _run() -> None:
            """Fetch fund metadata and holdings off the UI thread."""
            try:
                result = self._p13_service.load(ticker)
                self._invoke_main.emit(lambda r=result, rid=request_id: self._p13_handle_loaded_result(rid, r))
            except Exception as exc:
                logger.error(f'ETF analyser load failed for {ticker}: {exc}')
                self._invoke_main.emit(lambda t=ticker, err=str(exc), rid=request_id: self._p13_handle_error(rid, t, err))

        threading.Thread(target=_run, daemon=True).start()

    def _p13_handle_loaded_result(self, request_id: int, result: 'EtfHoldingsResult') -> None:
        """Apply one ETF response only when it is still current."""
        context = self._p13_request_contexts.pop(request_id, {})
        if request_id != getattr(self, '_p13_active_request_id', 0):
            return
        self._p13_apply_result(
            result,
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _p13_apply_result(
        self,
        result: 'EtfHoldingsResult',
        *,
        update_collection_info: bool=True,
        status_text: str | None=None,
    ) -> None:
        """Render ETF summary and holdings into the page table."""
        self._p13_last_result = result
        self._p13_update_holdings_chart(result.holdings)
        rows = [
            {
                'symbol': holding.symbol,
                'name': holding.name,
                'weight': holding.weight,
            }
            for holding in result.holdings
        ]
        self._p13_rows = rows
        self.p13_table.setSortingEnabled(False)
        self.p13_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            ticker_item = QTableWidgetItem(row.get('symbol', ''))
            ticker_item.setForeground(self.theme_qcolor('text_primary'))
            name_item = QTableWidgetItem(row.get('name', ''))
            name_item.setForeground(self.theme_qcolor('text_secondary'))
            weight_value = row.get('weight')
            weight_text = '--' if weight_value is None else f'{weight_value * 100:.2f}%'
            weight_item = QTableWidgetItem(weight_text)
            weight_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            weight_item.setForeground(self.theme_qcolor('accent_positive'))
            self.p13_table.setItem(row_index, 0, ticker_item)
            self.p13_table.setItem(row_index, 1, name_item)
            self.p13_table.setItem(row_index, 2, weight_item)
        self.p13_table.setSortingEnabled(True)
        self.p13_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.p13_name_lbl.setText(f'Fund: {result.fund_name or result.ticker}')
        self.p13_category_lbl.setText(f'Issuer: {result.issuer or "Unknown"}')
        self.p13_family_lbl.setText(f'As Of: {result.as_of_date or "--"}')
        self.p13_expense_lbl.setText(f'Expense Ratio: {result.expense_ratio or "--"}')
        self.p13_assets_lbl.setText(f'Net Assets: {result.net_assets or "--"}')
        self.p13_count_lbl.setText(f'Holdings Loaded: {len(rows)}')
        if result.sector_breakdown:
            parts = [f'{name} {pct:.1f}%' for name, pct in result.sector_breakdown.items()]
            self.p13_sectors_lbl.setText(f'<b>Sectors:</b>  {" | ".join(parts)}')
            self.p13_sectors_lbl.setVisible(True)
        else:
            self.p13_sectors_lbl.setVisible(False)
        if rows and result.is_partial:
            self.set_status_text(
                self.p13_status_lbl,
                f'Loaded {len(rows)} top holdings for {result.ticker} via Yahoo Finance fallback. This is not the full holdings list.',
                status='warning',
            )
        elif rows:
            self.set_status_text(
                self.p13_status_lbl,
                f'Loaded {len(rows)} holdings for {result.ticker} from {result.issuer}.',
                status='positive',
            )
        else:
            self.set_status_text(
                self.p13_status_lbl,
                f'No holdings were returned by the official issuer source for {result.ticker}.',
                status='warning',
            )
        if status_text:
            self.set_status_text(self.p13_status_lbl, status_text, status='positive')
        if update_collection_info:
            self._set_data_collection_info([result.issuer or 'official issuer source'])
        self.p13_load_btn.setEnabled(True)
        self._p13_save_session_snapshot()

    def _p13_export_clipboard(self) -> None:
        """Copy holdings to clipboard in tab-separated format for spreadsheet pasting."""
        if not self._p13_rows:
            self.set_status_text(self.p13_status_lbl, 'No holdings to export.', status='warning')
            return
        lines = ['Ticker\tName\tWeight']
        for row in self._p13_rows:
            weight = row.get('weight')
            weight_text = '' if weight is None else f'{weight * 100:.2f}%'
            lines.append(f'{row.get("symbol", "")}\t{row.get("name", "")}\t{weight_text}')
        QApplication.clipboard().setText('\n'.join(lines))
        self.set_status_text(self.p13_status_lbl, f'Copied {len(self._p13_rows)} holdings to clipboard.', status='positive')

    def _p13_handle_error(self, request_id: int, ticker: str, exc: Any) -> None:
        """Show a user-facing error for ETF loads."""
        self._p13_request_contexts.pop(request_id, None)
        if request_id != getattr(self, '_p13_active_request_id', 0):
            return
        self._p13_show_holdings_chart_placeholder('Load ETF', 'Breakdown')
        self.p13_load_btn.setEnabled(True)
        self.set_status_text(self.p13_status_lbl, f'Failed to load {ticker}: {exc}', status='negative')
        if hasattr(self, '_record_data_health_exception'):
            self._record_data_health_exception('ETF holdings', exc, symbols=[ticker])

    def _p13_update_holdings_chart(self, holdings: list[Any]) -> None:
        """Render a readable donut chart for the ETF holdings basket."""
        ranked: list[tuple[str, float]] = []
        loaded_total = 0.0
        for holding in holdings:
            weight = getattr(holding, 'weight', None)
            try:
                weight_value = float(weight)
            except (TypeError, ValueError):
                continue
            if weight_value <= 0:
                continue
            label = str(getattr(holding, 'symbol', '') or getattr(holding, 'name', '') or 'Unknown').strip()
            ranked.append((label, weight_value))
            loaded_total += weight_value
        if not ranked:
            self._p13_show_holdings_chart_placeholder('No Holdings', 'Breakdown')
            return
        ranked.sort(key=lambda item: item[1], reverse=True)

        chart_weights: dict[str, float] = {}
        for label, weight in ranked[:_P13_MAX_NAMED_SLICES]:
            chart_weights[label] = chart_weights.get(label, 0.0) + weight

        others_weight = sum(weight for _label, weight in ranked[_P13_MAX_NAMED_SLICES:])
        uncovered_weight = max(0.0, 1.0 - loaded_total)
        if uncovered_weight >= _P13_MIN_REMAINDER_WEIGHT:
            others_weight += uncovered_weight
        if others_weight > 0:
            chart_weights['Others'] = chart_weights.get('Others', 0.0) + others_weight

        if not chart_weights:
            self._p13_show_holdings_chart_placeholder('No Holdings', 'Breakdown')
            return

        chart_total = sum(chart_weights.values())
        if others_weight > 0 and chart_total > 0:
            self.p13_holdings_pie.set_start_angle((others_weight / chart_total) * 180.0)
        else:
            self.p13_holdings_pie.set_start_angle(90.0)
        coverage_pct = min(max(loaded_total, 0.0), 1.0) * 100.0
        self.p13_holdings_pie.set_data(chart_weights)
        self.p13_holdings_pie.set_center_text(f'{coverage_pct:.1f}%', 'Coverage')
        self.p13_chart_frame.setVisible(True)

    def _p13_show_holdings_chart_placeholder(self, text: str='Load ETF', subtext: str='Breakdown') -> None:
        """Show the ETF donut in its placeholder state instead of hiding it."""
        if not hasattr(self, 'p13_holdings_pie'):
            return
        self.p13_holdings_pie.set_start_angle(90.0)
        self.p13_holdings_pie.set_data({})
        self.p13_holdings_pie.set_center_text(text, subtext)
        if hasattr(self, 'p13_chart_frame'):
            self.p13_chart_frame.setVisible(True)

    # ── AUM left panel ──────────────────────────────────────────────

    def _p13_build_aum_panel(self) -> QWidget:
        """Build the left-side 'ETF by AUM' panel."""
        panel = QWidget()
        panel.setMinimumWidth(240)
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        self._p13_aum_title_lbl = QLabel('<b>ETF by AUM</b>')
        vbox.addWidget(self._p13_aum_title_lbl)

        self._p13_aum_refresh_btn = QPushButton('Refresh AUM')
        self._p13_aum_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._p13_aum_refresh_btn.clicked.connect(lambda: self._p13_fetch_aum_universe(force=True))
        vbox.addWidget(self._p13_aum_refresh_btn)

        self._p13_aum_status_lbl = QLabel('')
        self._p13_aum_status_lbl.setWordWrap(True)
        vbox.addWidget(self._p13_aum_status_lbl)

        self._p13_aum_note_lbl = QLabel('Note: Vanguard ETFs may show total fund AUM across all share classes, not ETF-only.')
        self._p13_aum_note_lbl.setWordWrap(True)
        vbox.addWidget(self._p13_aum_note_lbl)

        self._p13_aum_table = QTableWidget(0, 2)
        self._p13_aum_table.setHorizontalHeaderLabels(['Ticker', 'AUM'])
        hh = self._p13_aum_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._p13_aum_table.verticalHeader().setVisible(False)
        self._p13_aum_table.verticalHeader().setDefaultSectionSize(26)
        self._p13_aum_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._p13_aum_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._p13_aum_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._p13_aum_table.setAlternatingRowColors(True)
        self._p13_aum_table.setSortingEnabled(True)
        self._p13_aum_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._p13_aum_table.cellClicked.connect(self._p13_on_aum_etf_clicked)
        vbox.addWidget(self._p13_aum_table, 1)

        return panel

    def _p13_fetch_aum_universe(self, *, force: bool=False) -> None:
        """Fetch the broad US ETF AUM universe from Yahoo Finance."""
        if self._p13_aum_cache and not force:
            self._p13_render_aum_table()
            return

        if self._p13_aum_fetch_in_progress:
            return

        if force:
            self._p13_aum_cache = {}
            self._p13_aum_missing_count = 0
            self._p13_aum_total_count = 0
            self._p13_aum_table.setRowCount(0)

        self._p13_aum_fetch_in_progress = True
        self._p13_aum_refresh_btn.setEnabled(False)
        self._p13_aum_status_lbl.setText('Fetching ETF AUM...')

        def _fetch() -> None:
            cache: dict[str, float] = {}
            total = 0
            try:
                etf_query = getattr(yf, 'ETFQuery', None)
                if etf_query is None:
                    raise RuntimeError('Installed yfinance does not support ETF screener queries.')
                query = etf_query('and', [
                    etf_query('gt', ['fundnetassets', 0]),
                    etf_query('eq', ['region', 'us']),
                ])
                offset = 0
                while True:
                    with YF_LOCK:
                        response = yf.screen(
                            query,
                            offset=offset,
                            size=_P13_AUM_PAGE_SIZE,
                            count=_P13_AUM_PAGE_SIZE,
                            sortField='fundnetassets',
                            sortAsc=False,
                        )
                    if not isinstance(response, dict):
                        raise RuntimeError('Yahoo Finance returned an unexpected ETF screener response.')
                    quotes = list(response.get('quotes') or [])
                    total = EtfAnalyserMixin._p13_positive_int(response.get('total')) or total
                    if not quotes:
                        break
                    for quote in quotes:
                        if not isinstance(quote, dict):
                            continue
                        ticker = str(quote.get('symbol') or '').upper().strip()
                        aum = EtfAnalyserMixin._p13_positive_float(
                            quote.get('netAssets') or quote.get('fundnetassets')
                        )
                        if ticker and aum is not None:
                            cache[ticker] = aum
                    loaded = offset + len(quotes)
                    display_total = total or loaded
                    progress_msg = f'Fetching ETF AUM... {min(loaded, display_total)}/{display_total} loaded'
                    self._invoke_main.emit(lambda m=progress_msg: self._p13_aum_status_lbl.setText(m))
                    offset += len(quotes)
                    if total and offset >= total:
                        break
                    if len(quotes) < _P13_AUM_PAGE_SIZE:
                        break
                self._invoke_main.emit(
                    lambda c=cache, t=total: self._p13_on_aum_data_ready(c, t)
                )
            except Exception as exc:
                logger.warning('ETF AUM screener fetch failed: %s', exc)
                self._invoke_main.emit(lambda e=str(exc): self._p13_on_aum_data_error(e))

        threading.Thread(target=_fetch, daemon=True).start()

    def _p13_on_aum_data_ready(
        self,
        cache: dict[str, float],
        total_count: int | None=None,
    ) -> None:
        """Store AUM cache and render the broad US ETF AUM table."""
        self._p13_aum_cache = cache
        total = total_count if total_count is not None else len(cache)
        self._p13_aum_total_count = max(0, int(total or 0))
        self._p13_aum_missing_count = max(0, self._p13_aum_total_count - len(cache))
        self._p13_aum_fetch_in_progress = False
        self._p13_aum_refresh_btn.setEnabled(True)
        self._p13_render_aum_table()

    def _p13_on_aum_data_error(self, message: str) -> None:
        """Show a user-facing error when the ETF AUM screener fails."""
        self._p13_aum_fetch_in_progress = False
        self._p13_aum_refresh_btn.setEnabled(True)
        self._p13_aum_status_lbl.setText(f'ETF AUM unavailable: {message}')

    def _p13_render_aum_table(self) -> None:
        """Display every loaded US ETF by AUM, largest first."""
        rows = sorted(self._p13_aum_cache.items(), key=lambda x: x[1], reverse=True)

        self._p13_aum_table.setSortingEnabled(False)
        self._p13_aum_table.setRowCount(len(rows))
        for row, (ticker, aum) in enumerate(rows):
            t_item = QTableWidgetItem(ticker)
            t_item.setData(Qt.ItemDataRole.UserRole, ticker)
            t_item.setData(Qt.ItemDataRole.UserRole + 1, aum)
            t_item.setForeground(self.theme_qcolor('text_primary'))
            a_item = _AumTableWidgetItem(self._p13_format_aum(aum))
            a_item.setData(Qt.ItemDataRole.UserRole, aum)
            a_item.setData(Qt.ItemDataRole.UserRole + 1, ticker)
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            a_item.setForeground(self.theme_qcolor('accent_positive'))
            self._p13_aum_table.setItem(row, 0, t_item)
            self._p13_aum_table.setItem(row, 1, a_item)
        self._p13_aum_table.setSortingEnabled(True)
        self._p13_aum_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        if not self._p13_aum_cache:
            self._p13_aum_status_lbl.setText('No US ETF AUM data returned by Yahoo Finance.')
        elif self._p13_aum_missing_count:
            self._p13_aum_status_lbl.setText(
                f'Loaded AUM for {len(rows)}/{self._p13_aum_total_count} US ETFs; '
                f'{self._p13_aum_missing_count} unavailable.'
            )
        else:
            self._p13_aum_status_lbl.setText(f'Loaded AUM for {len(rows)} US ETFs.')

    @staticmethod
    def _p13_positive_int(value: Any) -> int | None:
        """Return a positive integer or None for missing Yahoo counts."""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        return number

    @staticmethod
    def _p13_positive_float(value: Any) -> float | None:
        """Return a positive finite float or None for missing Yahoo values."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number

    def _apply_etf_theme(self) -> None:
        """Refresh ETF page colors and chart styling after a theme change."""
        panel_style = (
            f'background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px;'
        )
        table_style = (
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; '
            f'color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; '
            f'gridline-color: {self.theme_color("panel_border")}; '
            f'alternate-background-color: {self.theme_color("background_secondary")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; '
            f'color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        input_style = (
            f'background-color: {self.theme_color("panel_background")}; '
            f'color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 6px; padding: 6px 10px;'
        )
        self.p13_left_panel.setStyleSheet(
            f'background: {self.theme_color("panel_background")}; '
            f'border-right: 1px solid {self.theme_color("panel_border")};'
        )
        self.p13_controls_frame.setStyleSheet(panel_style)
        self.p13_summary_frame.setStyleSheet(panel_style)
        self.p13_chart_frame.setStyleSheet(panel_style)
        self.p13_symbol_lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p13_etf_input.setStyleSheet(input_style)
        for label in (
            self.p13_name_lbl,
            self.p13_category_lbl,
            self.p13_family_lbl,
            self.p13_expense_lbl,
            self.p13_assets_lbl,
            self.p13_count_lbl,
            self._p13_aum_title_lbl,
        ):
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self._p13_aum_status_lbl.setStyleSheet(
            f'color: {self.theme_color("text_secondary")}; border: none; font-size: 11px;'
        )
        self._p13_aum_note_lbl.setStyleSheet(
            f'color: {self.theme_color("warning")}; border: none; font-size: 10px; font-style: italic;'
        )
        self.p13_sectors_lbl.setStyleSheet(
            f'color: {self.theme_color("text_secondary")}; '
            f'background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 6px; padding: 8px 12px;'
        )
        self.set_status_text(
            self.p13_status_lbl,
            self.p13_status_lbl.text(),
            status=self.p13_status_lbl.property('bt_status') or 'muted',
        )
        self.p13_table.setStyleSheet(table_style)
        self._p13_aum_table.setStyleSheet(table_style)
        for row_index in range(self.p13_table.rowCount()):
            ticker_item = self.p13_table.item(row_index, 0)
            name_item = self.p13_table.item(row_index, 1)
            weight_item = self.p13_table.item(row_index, 2)
            if ticker_item is not None:
                ticker_item.setForeground(self.theme_qcolor('text_primary'))
            if name_item is not None:
                name_item.setForeground(self.theme_qcolor('text_secondary'))
            if weight_item is not None:
                weight_item.setForeground(self.theme_qcolor('accent_positive'))
        for row_index in range(self._p13_aum_table.rowCount()):
            ticker_item = self._p13_aum_table.item(row_index, 0)
            value_item = self._p13_aum_table.item(row_index, 1)
            if ticker_item is not None:
                ticker_item.setForeground(self.theme_qcolor('text_primary'))
            if value_item is not None:
                value_item.setForeground(self.theme_qcolor('accent_positive'))
        self.p13_holdings_pie.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))

    def _p13_on_aum_etf_clicked(self, row: int, _col: int) -> None:
        """Load the clicked ETF's holdings in the main view."""
        item = self._p13_aum_table.item(row, 0)
        if item:
            self.p13_etf_input.setText(item.text())
            self._p13_load_etf()

    @staticmethod
    def _p13_format_aum(value: float) -> str:
        """Format AUM value as human-readable string."""
        if value >= 1_000_000_000_000:
            return f'${value / 1_000_000_000_000:.1f}T'
        if value >= 1_000_000_000:
            return f'${value / 1_000_000_000:.1f}B'
        if value >= 1_000_000:
            return f'${value / 1_000_000:.0f}M'
        return f'${value:,.0f}'
