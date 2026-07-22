from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.dataroma import DataromaWorker


_P24_SOURCE_ROLE = Qt.ItemDataRole.UserRole
_P24_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class _P24SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by an explicit numeric payload when present."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(_P24_SORT_ROLE))
            right = float(other.data(_P24_SORT_ROLE))
            return left < right
        except Exception:
            return super().__lt__(other)


class InstitutionsMixin:
    def init_page24(self) -> None:
        self._p24_thread: QThread | None = None
        self._p24_worker = None
        self._p24_payloads: dict[str, dict[str, Any]] = {}
        self._p24_tables: list[QTableWidget] = []
        self._p24_panels: list[QFrame] = []
        self._p24_loaded_once = False

        layout = QVBoxLayout(self.page24)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        toolbar = QFrame()
        self.set_theme_role(toolbar, 'panel')
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 6, 10, 6)
        toolbar_layout.setSpacing(6)
        self._p24_panels.append(toolbar)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title = QLabel('Institutions')
        self.set_theme_role(title, 'page_title')
        subtitle = QLabel('Latest DATAROMA superinvestor activity by quarter.')
        self.set_theme_role(subtitle, 'muted')
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        toolbar_layout.addLayout(title_col)

        toolbar_layout.addStretch()
        toolbar_layout.addWidget(QLabel('Quarter'))
        self.p24_quarter_combo = QComboBox()
        self.p24_quarter_combo.setMinimumWidth(110)
        toolbar_layout.addWidget(self.p24_quarter_combo)

        self.p24_quarter_btn = QPushButton('Load Quarter')
        self.p24_quarter_btn.clicked.connect(lambda *_: self._p24_refresh_activity(force=True))
        toolbar_layout.addWidget(self.p24_quarter_btn)

        self.p24_refresh_btn = QPushButton('Refresh')
        self.p24_refresh_btn.clicked.connect(lambda *_: self._p24_refresh_activity(force=True))
        toolbar_layout.addWidget(self.p24_refresh_btn)

        self.p24_export_activity_btn = QPushButton('Export Buys/Sells')
        self.set_theme_variant(self.p24_export_activity_btn, 'accent')
        self.p24_export_activity_btn.clicked.connect(self._p24_export_buys_sells)
        toolbar_layout.addWidget(self.p24_export_activity_btn)

        self.p24_export_managers_btn = QPushButton('Export Superinvestors')
        self.set_theme_variant(self.p24_export_managers_btn, 'accent')
        self.p24_export_managers_btn.clicked.connect(self._p24_export_superinvestors)
        toolbar_layout.addWidget(self.p24_export_managers_btn)

        self.p24_status_lbl = QLabel('Open the page to load institution activity.')
        self.p24_status_lbl.setMinimumWidth(360)
        self.p24_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p24_status_lbl, 'status_muted')
        toolbar_layout.addWidget(self.p24_status_lbl)
        layout.addWidget(toolbar)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        activity_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p24_buy_table = self._p24_new_table(
            ['Period', 'Symbol', 'Company', 'Manager', 'Activity', 'Approx Inflow $', 'Change to Portfolio'],
            stretch_columns=(2, 3),
        )
        activity_splitter.addWidget(self._p24_table_panel('Top Institutional Buying', self.p24_buy_table))
        self.p24_sell_table = self._p24_new_table(
            ['Period', 'Symbol', 'Company', 'Manager', 'Activity', 'Approx Outflow $', 'Change to Portfolio'],
            stretch_columns=(2, 3),
        )
        activity_splitter.addWidget(self._p24_table_panel('Top Institutional Selling', self.p24_sell_table))
        activity_splitter.setStretchFactor(0, 1)
        activity_splitter.setStretchFactor(1, 1)
        main_splitter.addWidget(activity_splitter)

        detail_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p24_manager_table = self._p24_new_table(
            ['Manager', 'ID', 'Period', 'Buys', 'Sells', 'Top Activity'],
            stretch_columns=(0, 5),
        )
        detail_splitter.addWidget(self._p24_table_panel('Superinvestors', self.p24_manager_table))
        self.p24_ticker_table = self._p24_new_table(
            ['Period', 'Manager', 'Activity', 'Share Change', 'Change to Portfolio'],
            stretch_columns=(1,),
        )
        detail_splitter.addWidget(self._p24_ticker_panel())
        detail_splitter.setStretchFactor(0, 1)
        detail_splitter.setStretchFactor(1, 1)
        main_splitter.addWidget(detail_splitter)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)
        layout.addWidget(main_splitter, 1)

    def _p24_table_panel(self, title: str, table: QTableWidget) -> QFrame:
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 6, 8, 6)
        panel_layout.setSpacing(4)
        label = QLabel(title)
        self.set_theme_role(label, 'section_title')
        panel_layout.addWidget(label)
        panel_layout.addWidget(table, 1)
        self._p24_panels.append(panel)
        return panel

    def _p24_ticker_panel(self) -> QFrame:
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 6, 8, 6)
        panel_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        label = QLabel('Ticker Activity')
        self.set_theme_role(label, 'section_title')
        header.addWidget(label)
        header.addStretch()
        self.p24_ticker_input = QLineEdit('MSFT')
        self.p24_ticker_input.setPlaceholderText('Ticker')
        self.p24_ticker_input.setFixedWidth(110)
        self.p24_ticker_input.returnPressed.connect(lambda: self._p24_refresh_ticker(force=True))
        header.addWidget(self.p24_ticker_input)
        self.p24_ticker_btn = QPushButton('Search Ticker')
        self.p24_ticker_btn.clicked.connect(lambda *_: self._p24_refresh_ticker(force=True))
        header.addWidget(self.p24_ticker_btn)

        panel_layout.addLayout(header)
        panel_layout.addWidget(self.p24_ticker_table, 1)
        self._p24_panels.append(panel)
        return panel

    def _p24_new_table(self, headers: list[str], *, stretch_columns: tuple[int, ...] = ()) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.cellDoubleClicked.connect(lambda row, _col, widget=table: self._p24_open_table_row_source(widget, row))
        header = table.horizontalHeader()
        header.setMinimumHeight(24)
        header.setStretchLastSection(False)
        for column in range(len(headers)):
            if column in stretch_columns:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._p24_tables.append(table)
        return table

    def _p24_on_show(self) -> None:
        if not getattr(self, '_p24_loaded_once', False):
            self._p24_refresh_activity(force=False)

    def _p24_refresh_current(self, *, force: bool = False) -> None:
        self._p24_refresh_activity(force=force)

    def _p24_refresh_activity(self, *, force: bool = False) -> None:
        quarter = str(self.p24_quarter_combo.currentData() or self.p24_quarter_combo.currentText() or '').strip()
        self._p24_start_worker(
            'institution_activity',
            force=force,
            message='Loading DATAROMA institution activity...',
            limit=50,
            quarter=quarter,
        )

    def _p24_refresh_ticker(self, *, force: bool = False) -> None:
        symbol = str(self.p24_ticker_input.text() or '').upper().strip()
        self.p24_ticker_input.setText(symbol)
        self._p24_start_worker(
            'institution_ticker_activity',
            force=force,
            message=f'Loading institution activity for {symbol or "ticker"}...',
            symbol=symbol,
        )

    def _p24_start_worker(self, facet: str, *, force: bool, message: str, **params: Any) -> None:
        if self._p24_thread is not None and self._p24_thread.isRunning():
            self._p24_set_status('DATAROMA institution request already running...', 'muted')
            return
        self._p24_set_busy(True)
        self._p24_set_status(message, 'muted')
        worker = DataromaWorker(facet, force=force, **params)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._p24_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p24_on_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._p24_on_thread_finished)
        self._p24_thread = thread
        self._p24_worker = worker
        thread.start()

    def _p24_on_data(self, payload: dict[str, Any]) -> None:
        facet = str(payload.get('facet') or '').lower().strip()
        self._p24_payloads[facet] = dict(payload)
        if facet == 'institution_activity':
            self._p24_loaded_once = True
            self._p24_render_activity(payload)
        elif facet == 'institution_ticker_activity':
            self._p24_render_ticker_activity(payload)
        row_count = self._p24_payload_row_count(payload)
        status = f'Institutions {facet or "data"} loaded: {row_count} row(s).'
        active_period = str(payload.get('active_period') or '').strip()
        if active_period:
            status = f'{status} Period: {active_period}.'
        if facet == 'institution_activity':
            status = f'{status} Approx $ uses share change x DATAROMA hold price.'
        if payload.get('from_cache'):
            status = f'{status} Cache used.'
        if payload.get('stale'):
            status = f'{status} Stale cache shown.'
        warnings = list(payload.get('warnings') or [])
        if warnings:
            status = f'{status} {warnings[-1]}'
        self._p24_set_status(status, 'warning' if payload.get('stale') or warnings else 'positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, status, status='warning' if payload.get('stale') or warnings else 'positive')

    def _p24_on_error(self, message: str) -> None:
        self._p24_set_status(f'Institutions refresh failed: {message}', 'negative')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Institutions refresh failed: {message}', status='negative')

    def _p24_on_thread_finished(self) -> None:
        self._p24_set_busy(False)
        if self._p24_worker is not None:
            self._p24_worker.deleteLater()
            self._p24_worker = None
        if self._p24_thread is not None:
            self._p24_thread.deleteLater()
            self._p24_thread = None

    def _p24_render_activity(self, payload: dict[str, Any]) -> None:
        self._p24_populate_quarter_combo(
            [str(period or '').strip() for period in list(payload.get('periods') or []) if str(period or '').strip()],
            str(payload.get('active_period') or '').strip(),
        )
        self._p24_set_rows(
            self.p24_buy_table,
            payload.get('buy_rows') or [],
            [
                ('Period', 'period'),
                ('Symbol', 'symbol'),
                ('Company', 'company'),
                ('Manager', 'manager'),
                ('Activity', 'activity'),
                ('Approx Inflow $', 'approx_flow'),
                ('Change to Portfolio', 'change_to_portfolio'),
            ],
        )
        self._p24_set_rows(
            self.p24_sell_table,
            payload.get('sell_rows') or [],
            [
                ('Period', 'period'),
                ('Symbol', 'symbol'),
                ('Company', 'company'),
                ('Manager', 'manager'),
                ('Activity', 'activity'),
                ('Approx Outflow $', 'approx_flow'),
                ('Change to Portfolio', 'change_to_portfolio'),
            ],
        )
        self._p24_set_rows(
            self.p24_manager_table,
            payload.get('manager_rows') or [],
            [
                ('Manager', 'manager'),
                ('ID', 'manager_id'),
                ('Period', 'period'),
                ('Buys', 'buy_count'),
                ('Sells', 'sell_count'),
                ('Top Activity', 'top_activity'),
            ],
        )

    def _p24_populate_quarter_combo(self, periods: list[str], active_period: str) -> None:
        current = active_period or str(self.p24_quarter_combo.currentData() or self.p24_quarter_combo.currentText() or '').strip()
        self.p24_quarter_combo.blockSignals(True)
        self.p24_quarter_combo.clear()
        for period in periods:
            self.p24_quarter_combo.addItem(period, period)
        if current:
            index = self.p24_quarter_combo.findData(current)
            if index < 0:
                self.p24_quarter_combo.addItem(current, current)
                index = self.p24_quarter_combo.findData(current)
            self.p24_quarter_combo.setCurrentIndex(max(index, 0))
        self.p24_quarter_combo.blockSignals(False)

    def _p24_render_ticker_activity(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get('symbol') or '').upper().strip()
        if symbol:
            self.p24_ticker_input.setText(symbol)
        rows = payload.get('activity_rows') or []
        self._p24_set_rows(
            self.p24_ticker_table,
            rows,
            [
                ('Period', 'period'),
                ('Manager', 'manager'),
                ('Activity', 'activity'),
                ('Share Change', 'share_change'),
                ('Change to Portfolio', 'change_to_portfolio'),
            ],
        )

    def _p24_set_rows(self, table: QTableWidget, rows: Any, columns: list[tuple[str, str]]) -> None:
        normalized_rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
        table.setSortingEnabled(False)
        table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            source_url = str(row.get('source_url') or row.get('history_url') or '').strip()
            for column_index, (_label, key) in enumerate(columns):
                value = self._p24_cell_value(row, key)
                sort_value = self._p24_sort_value(row, key)
                item = _P24SortableTableWidgetItem(value) if sort_value is not None else QTableWidgetItem(value)
                item.setData(_P24_SOURCE_ROLE, source_url)
                if sort_value is not None:
                    item.setData(_P24_SORT_ROLE, sort_value)
                if source_url:
                    item.setToolTip(source_url)
                if self._p24_is_numeric_key(key):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key in {'symbol', 'manager_id', 'period'}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column_index, item)
        table.setSortingEnabled(True)

    @staticmethod
    def _p24_cell_value(row: dict[str, Any], key: str) -> str:
        value = row.get(key)
        if isinstance(value, list):
            return ', '.join(str(item) for item in value if str(item or '').strip())
        return str(value or '')

    @staticmethod
    def _p24_sort_value(row: dict[str, Any], key: str) -> float | None:
        sort_keys = {
            'approx_flow': 'approx_flow_value',
            'change_to_portfolio': 'change_to_portfolio_pct',
            'share_change': 'share_change_value',
            'buy_count': 'buy_count',
            'sell_count': 'sell_count',
        }
        sort_key = sort_keys.get(key)
        if not sort_key:
            return None
        try:
            return float(row.get(sort_key))
        except Exception:
            return None

    @staticmethod
    def _p24_is_numeric_key(key: str) -> bool:
        lowered = str(key or '').lower()
        return any(token in lowered for token in ('count', 'change', 'portfolio', 'flow'))

    def _p24_open_table_row_source(self, table: QTableWidget, row: int) -> None:
        for column in range(table.columnCount()):
            item = table.item(row, column)
            url = str(item.data(_P24_SOURCE_ROLE) if item is not None else '' or '').strip()
            if url:
                webbrowser.open(url)
                return
        self._p24_set_status('No source URL is attached to that row.', 'warning')

    def _p24_export_buys_sells(self) -> None:
        payload = self._p24_payloads.get('institution_activity') or {}
        if not payload:
            self._p24_set_status('Load Institutions activity before exporting buys/sells.', 'warning')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Institutions export failed: no activity loaded.', status='warning')
            return
        text = self._p24_build_buys_sells_export(payload)
        QApplication.clipboard().setText(text)
        row_count = len(list(payload.get('buy_rows') or [])) + len(list(payload.get('sell_rows') or []))
        self._p24_set_status(f'Copied Institutions buys/sells export to clipboard: {row_count} row(s).', 'positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Institutions buys/sells export copied: {row_count} row(s).', status='positive')

    def _p24_export_superinvestors(self) -> None:
        payload = self._p24_payloads.get('institution_activity') or {}
        if not payload:
            self._p24_set_status('Load Institutions activity before exporting superinvestors.', 'warning')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Institutions export failed: no superinvestor data loaded.', status='warning')
            return
        text = self._p24_build_superinvestors_export(payload)
        QApplication.clipboard().setText(text)
        row_count = len(list(payload.get('manager_rows') or []))
        self._p24_set_status(f'Copied Institutions superinvestors export to clipboard: {row_count} row(s).', 'positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, f'Institutions superinvestors export copied: {row_count} row(s).', status='positive')

    def _p24_build_buys_sells_export(self, payload: dict[str, Any]) -> str:
        active_period = str(payload.get('active_period') or '').strip()
        lines = [
            '# Institutions Buys/Sells Export',
            f'Generated: {datetime.datetime.now().isoformat(timespec="seconds")}',
            f'Active quarter: {active_period or "N/A"}',
            '',
            'Approximate dollar flow uses share change multiplied by DATAROMA Hold Price. It is not an exact execution-dollar figure.',
            '',
        ]
        self._p24_append_export_rows(
            lines,
            'Top Institutional Buying',
            payload.get('buy_rows') or [],
            [
                ('period', 'period'),
                ('symbol', 'symbol'),
                ('company', 'company'),
                ('manager', 'manager'),
                ('activity', 'activity'),
                ('share_change', 'share_change'),
                ('approx_flow', 'approx_flow'),
                ('hold_price', 'hold_price'),
                ('change_to_portfolio', 'change_to_portfolio'),
                ('source_url', 'source_url'),
            ],
        )
        self._p24_append_export_rows(
            lines,
            'Top Institutional Selling',
            payload.get('sell_rows') or [],
            [
                ('period', 'period'),
                ('symbol', 'symbol'),
                ('company', 'company'),
                ('manager', 'manager'),
                ('activity', 'activity'),
                ('share_change', 'share_change'),
                ('approx_flow', 'approx_flow'),
                ('hold_price', 'hold_price'),
                ('change_to_portfolio', 'change_to_portfolio'),
                ('source_url', 'source_url'),
            ],
        )
        return '\n'.join(lines).strip() + '\n'

    def _p24_build_superinvestors_export(self, payload: dict[str, Any]) -> str:
        active_period = str(payload.get('active_period') or '').strip()
        lines = [
            '# Institutions Superinvestors Export',
            f'Generated: {datetime.datetime.now().isoformat(timespec="seconds")}',
            f'Active quarter: {active_period or "N/A"}',
            '',
        ]
        self._p24_append_export_rows(
            lines,
            'Superinvestors',
            payload.get('manager_rows') or [],
            [
                ('manager', 'manager'),
                ('id', 'manager_id'),
                ('period', 'period'),
                ('buys', 'buy_count'),
                ('sells', 'sell_count'),
                ('top_activity', 'top_activity'),
                ('source_url', 'source_url'),
            ],
        )
        return '\n'.join(lines).strip() + '\n'

    def _p24_append_export_rows(
        self,
        lines: list[str],
        title: str,
        rows: Any,
        columns: list[tuple[str, str]],
    ) -> None:
        normalized_rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
        lines.extend(['', f'## {title}'])
        headers = [label for label, _key in columns]
        lines.append(' | '.join(headers))
        lines.append(' | '.join(['---'] * len(headers)))
        if not normalized_rows:
            lines.append(' | '.join(['(no loaded rows)'] + [''] * (len(headers) - 1)))
            return
        for row in normalized_rows:
            values = [self._p24_export_value(row.get(key)) for _label, key in columns]
            lines.append(' | '.join(values))

    @staticmethod
    def _p24_export_value(value: Any) -> str:
        if isinstance(value, list):
            text = ', '.join(str(item) for item in value if str(item or '').strip())
        else:
            text = str(value or '')
        return text.replace('|', '/').replace('\r', ' ').replace('\n', ' ').strip()

    def _p24_set_busy(self, busy: bool) -> None:
        for button in (
            getattr(self, 'p24_refresh_btn', None),
            getattr(self, 'p24_quarter_btn', None),
            getattr(self, 'p24_ticker_btn', None),
            getattr(self, 'p24_export_activity_btn', None),
            getattr(self, 'p24_export_managers_btn', None),
        ):
            if button is not None:
                button.setEnabled(not busy)

    def _p24_set_status(self, text: Any, status: str = 'muted') -> None:
        self.set_status_text(self.p24_status_lbl, str(text or ''), status=status)

    @staticmethod
    def _p24_payload_row_count(payload: dict[str, Any]) -> int:
        count = 0
        for key in ('buy_rows', 'sell_rows', 'manager_rows', 'activity_rows'):
            value = payload.get(key)
            if isinstance(value, list):
                count += len(value)
        return count

    def _apply_institutions_theme(self) -> None:
        table_style = (
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        for table in getattr(self, '_p24_tables', []):
            table.setStyleSheet(table_style)
        label = getattr(self, 'p24_status_lbl', None)
        if label is not None:
            self.set_status_text(label, label.text(), status=label.property('bt_status') or 'muted')
        if hasattr(self, 'p24_ticker_input'):
            self.p24_ticker_input.setStyleSheet(
                f'background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
                f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 5px 8px;'
            )
        if hasattr(self, 'p24_quarter_combo'):
            self.p24_quarter_combo.setStyleSheet(
                f'background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
                f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 5px 8px;'
            )
