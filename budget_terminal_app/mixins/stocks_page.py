from __future__ import annotations

import math
from typing import Any

from ..compat import *


STOCKS_CHART_PERIOD = '3y'
STOCKS_CHART_INTERVAL = '1d'
STOCKS_DEFAULT_VISIBLE_BARS = 120
STOCKS_NEWS_LIMIT = 20
STOCKS_AUTO_ANCHOR = 0.85
STOCKS_MIN_REUSABLE_SPAN = 10.0
STOCKS_MFI_PERIOD = 14
STOCKS_MFI_OVERBOUGHT = 80
STOCKS_MFI_OVERSOLD = 20
STOCKS_FUNDAMENTAL_FIELDS = (
    ('Market cap', 'market_cap'),
    ('Revenue', 'revenue'),
    ('Net Income', 'net_income'),
    ('EPS', 'eps'),
    ('Gross Margin', 'gross_margin'),
    ('Operating Margin', 'operating_margin'),
    ('Net Margin', 'net_margin'),
    ('Shares outstanding', 'shares_outstanding'),
    ('PE', 'pe'),
    ('Forward PE', 'forward_pe'),
    ('Dividend', 'dividend'),
    ('Ex-Dividend date', 'ex_dividend_date'),
    ('Volume', 'volume'),
    ('Beta', 'beta'),
    ('Earnings date', 'earnings_date'),
)
STOCKS_PRICE_TARGET_FIELDS = (
    ('Mean', 'mean_target'),
    ('Upside', 'upside_to_mean'),
)


class StocksPageMixin:

    def init_page12(self) -> None:
        state = getattr(self, 'stocks_page_state', load_stocks_page_settings())
        self.stocks_symbol = str(state.get('symbol', 'SPY') or 'SPY').upper().strip()
        self.stocks_page_state = dict(state) if isinstance(state, dict) else {}
        self.stocks_page_state['symbol'] = self.stocks_symbol
        self._stocks_request_seq = 0
        self._stocks_active_request = 0
        self._stocks_request_contexts = {}
        self._stocks_loaded_once = False
        self._stocks_loaded_payload = None
        self._stocks_chart_df = None
        self._stocks_chart_rows = []
        self._stocks_chart_stats = {}
        self._stocks_chart_interval = STOCKS_CHART_INTERVAL
        self._stocks_loaded_symbol = ''
        self._stocks_loaded_news = []
        self._stocks_loaded_institutional_rows = []
        self._stocks_loaded_insider_rows = []
        self._stocks_info = {}
        self._stocks_metric_name_labels = []
        self._stocks_metric_value_labels = []
        self._stocks_metric_row_lines = []
        self._stocks_target_name_labels = []
        self._stocks_target_value_labels = []
        self.stocks_auto_follow = bool(state.get('auto', True))
        self.stocks_mfi_enabled = bool(state.get('mfi_enabled', False))
        self._stocks_view_change_guard = False
        self._stocks_manual_x_range = None
        self._stocks_pending_x_range = None
        self._stocks_candle_item = None
        self._stocks_last_price_line = None
        self._stocks_mfi_series = None
        self._stocks_mfi_line_item = None
        self._stocks_mfi_upper_line = None
        self._stocks_mfi_lower_line = None
        self._stocks_mfi_label_item = None
        self.stocks_metric_labels = {}
        self.stocks_target_labels = {}

        layout = QHBoxLayout(self.page12)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)

        left_column = QWidget()
        left_column.setMinimumWidth(300)
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        ticker_frame = QFrame()
        self.set_theme_role(ticker_frame, 'panel')
        ticker_frame.setMinimumHeight(132)
        ticker_layout = QVBoxLayout(ticker_frame)
        ticker_layout.setContentsMargins(10, 8, 10, 8)
        ticker_layout.setSpacing(5)
        self.stocks_symbol_input = QLineEdit(self.stocks_symbol)
        self.stocks_symbol_input.setPlaceholderText('Stock ticker')
        self.stocks_symbol_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stocks_symbol_input.setMinimumHeight(32)
        self.stocks_symbol_input.returnPressed.connect(self._stocks_load_from_input)
        ticker_layout.addWidget(self.stocks_symbol_input)
        ticker_actions = QGridLayout()
        ticker_actions.setContentsMargins(0, 0, 0, 0)
        ticker_actions.setHorizontalSpacing(6)
        ticker_actions.setVerticalSpacing(6)
        self.stocks_load_btn = QPushButton('Load')
        self.set_theme_variant(self.stocks_load_btn, 'accent')
        self.stocks_load_btn.clicked.connect(self._stocks_load_from_input)
        self.stocks_go_to_charts_btn = QPushButton('Go to Charts')
        self.stocks_go_to_charts_btn.clicked.connect(self._stocks_go_to_charts)
        self.stocks_go_to_fundamentals_btn = QPushButton('Go to Fundamentals')
        self.stocks_go_to_fundamentals_btn.clicked.connect(self._stocks_go_to_fundamentals)
        self.stocks_go_to_options_btn = QPushButton('Go to Options')
        self.stocks_go_to_options_btn.clicked.connect(self._stocks_go_to_options)
        self.stocks_go_to_valuation_btn = QPushButton('Go to Valuation')
        self.stocks_go_to_valuation_btn.clicked.connect(self._stocks_go_to_valuation)
        self.stocks_export_btn = QPushButton('Export for LLM')
        self.set_theme_variant(self.stocks_export_btn, 'positive')
        self.stocks_export_btn.clicked.connect(self._stocks_export_for_llm)
        ticker_actions.addWidget(self.stocks_load_btn, 0, 0)
        ticker_actions.addWidget(self.stocks_go_to_charts_btn, 0, 1)
        ticker_actions.addWidget(self.stocks_go_to_fundamentals_btn, 1, 0)
        ticker_actions.addWidget(self.stocks_go_to_options_btn, 1, 1)
        ticker_actions.setColumnStretch(0, 1)
        ticker_actions.setColumnStretch(1, 1)
        ticker_layout.addLayout(ticker_actions)
        ticker_handoff_row = QHBoxLayout()
        ticker_handoff_row.setContentsMargins(0, 0, 0, 0)
        ticker_handoff_row.setSpacing(6)
        ticker_handoff_row.addWidget(self.stocks_go_to_valuation_btn, 1)
        ticker_handoff_row.addWidget(self.stocks_export_btn, 1)
        ticker_layout.addLayout(ticker_handoff_row)
        left_layout.addWidget(ticker_frame)

        fundamentals_frame = QFrame()
        self.set_theme_role(fundamentals_frame, 'panel')
        fundamentals_layout = QVBoxLayout(fundamentals_frame)
        fundamentals_layout.setContentsMargins(10, 8, 10, 8)
        fundamentals_layout.setSpacing(5)
        self.stocks_company_label = QLabel('—')
        self.stocks_company_label.setWordWrap(True)
        fundamentals_layout.addWidget(self.stocks_company_label)
        fundamentals_grid = QGridLayout()
        fundamentals_grid.setHorizontalSpacing(12)
        fundamentals_grid.setVerticalSpacing(2)
        for row_index, (label_text, field_key) in enumerate(STOCKS_FUNDAMENTAL_FIELDS):
            grid_row = row_index * 2
            name_label = QLabel(label_text)
            value_label = QLabel('—')
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._stocks_metric_name_labels.append(name_label)
            self._stocks_metric_value_labels.append(value_label)
            self.stocks_metric_labels[field_key] = value_label
            if field_key == 'description':
                value_label.setWordWrap(True)
                value_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            else:
                value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            fundamentals_grid.addWidget(name_label, grid_row, 0, 1, 1)
            fundamentals_grid.addWidget(value_label, grid_row, 1, 1, 1)
            if row_index < len(STOCKS_FUNDAMENTAL_FIELDS) - 1:
                row_line = QFrame()
                row_line.setFrameShape(QFrame.Shape.HLine)
                row_line.setFrameShadow(QFrame.Shadow.Plain)
                row_line.setFixedHeight(1)
                self._stocks_metric_row_lines.append(row_line)
                fundamentals_grid.addWidget(row_line, grid_row + 1, 0, 1, 2)
        fundamentals_grid.setColumnStretch(1, 1)
        fundamentals_layout.addLayout(fundamentals_grid)
        price_targets_frame = QFrame()
        self.set_theme_role(price_targets_frame, 'panel')
        targets_layout = QVBoxLayout(price_targets_frame)
        targets_layout.setContentsMargins(10, 8, 10, 8)
        targets_layout.setSpacing(5)
        targets_title = QLabel('Price Targets')
        self.set_theme_role(targets_title, 'section_title')
        targets_layout.addWidget(targets_title)
        targets_grid = QGridLayout()
        targets_grid.setHorizontalSpacing(12)
        targets_grid.setVerticalSpacing(3)
        for row_index, (label_text, field_key) in enumerate(STOCKS_PRICE_TARGET_FIELDS):
            name_label = QLabel(label_text)
            value_label = QLabel('—')
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._stocks_target_name_labels.append(name_label)
            self._stocks_target_value_labels.append(value_label)
            self.stocks_target_labels[field_key] = value_label
            targets_grid.addWidget(name_label, row_index, 0, 1, 1)
            targets_grid.addWidget(value_label, row_index, 1, 1, 1)
        targets_grid.setColumnStretch(1, 1)
        targets_layout.addLayout(targets_grid)

        news_frame = QFrame()
        self.set_theme_role(news_frame, 'panel')
        news_layout = QVBoxLayout(news_frame)
        news_layout.setContentsMargins(10, 8, 10, 8)
        news_layout.setSpacing(5)
        news_title = QLabel('News')
        self.set_theme_role(news_title, 'section_title')
        news_layout.addWidget(news_title)
        self.stocks_news_empty = QLabel('Load a ticker to inspect recent headlines.')
        self.stocks_news_empty.setWordWrap(True)
        news_layout.addWidget(self.stocks_news_empty)
        self.stocks_news_table = self._make_news_table(self._open_news_link_table)
        self.stocks_news_table.verticalHeader().setDefaultSectionSize(22)
        self.stocks_news_table.horizontalHeader().setMinimumHeight(24)
        self.stocks_news_table.setAlternatingRowColors(True)
        self.stocks_news_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stocks_news_table.setVisible(False)
        news_layout.addWidget(self.stocks_news_table, 1)

        institutional_frame = QFrame()
        self.set_theme_role(institutional_frame, 'panel')
        institutional_layout = QVBoxLayout(institutional_frame)
        institutional_layout.setContentsMargins(10, 8, 10, 8)
        institutional_layout.setSpacing(5)
        institutional_title = QLabel('Top Institutional holders')
        self.set_theme_role(institutional_title, 'section_title')
        institutional_layout.addWidget(institutional_title)
        self.stocks_institutional_empty = QLabel('Load a ticker to inspect top institutional holders.')
        self.stocks_institutional_empty.setWordWrap(True)
        institutional_layout.addWidget(self.stocks_institutional_empty)
        self.stocks_institutional_table = QTableWidget(0, 6)
        self.stocks_institutional_table.setHorizontalHeaderLabels(['Holder', '% Held', 'Shares', 'Value', 'Change', 'Reported'])
        self.stocks_institutional_table.verticalHeader().setVisible(False)
        self.stocks_institutional_table.verticalHeader().setDefaultSectionSize(22)
        self.stocks_institutional_table.setAlternatingRowColors(True)
        self.stocks_institutional_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stocks_institutional_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.stocks_institutional_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        institutional_header = self.stocks_institutional_table.horizontalHeader()
        institutional_header.setMinimumHeight(24)
        institutional_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        institutional_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        institutional_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        institutional_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        institutional_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        institutional_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.stocks_institutional_table.setVisible(False)
        institutional_layout.addWidget(self.stocks_institutional_table, 1)

        description_frame = QFrame()
        self.set_theme_role(description_frame, 'panel')
        description_layout = QVBoxLayout(description_frame)
        description_layout.setContentsMargins(10, 8, 10, 8)
        description_layout.setSpacing(5)
        description_title = QLabel('Description')
        self.set_theme_role(description_title, 'section_title')
        description_layout.addWidget(description_title)
        self.stocks_description_output = QPlainTextEdit()
        self.stocks_description_output.setReadOnly(True)
        self.stocks_description_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.stocks_description_output.setMinimumHeight(80)
        description_layout.addWidget(self.stocks_description_output, 1)

        insider_frame = QFrame()
        self.set_theme_role(insider_frame, 'panel')
        insider_layout = QVBoxLayout(insider_frame)
        insider_layout.setContentsMargins(10, 8, 10, 8)
        insider_layout.setSpacing(5)
        insider_title = QLabel('Insider transactions')
        self.set_theme_role(insider_title, 'section_title')
        insider_layout.addWidget(insider_title)
        self.stocks_insider_empty = QLabel('Load a ticker to inspect insider transactions.')
        self.stocks_insider_empty.setWordWrap(True)
        insider_layout.addWidget(self.stocks_insider_empty)
        self.stocks_insider_table = QTableWidget(0, 6)
        self.stocks_insider_table.setHorizontalHeaderLabels(['Date', 'Insider', 'Title/Relation', 'Transaction', 'Shares', 'Value'])
        self.stocks_insider_table.verticalHeader().setVisible(False)
        self.stocks_insider_table.verticalHeader().setDefaultSectionSize(22)
        self.stocks_insider_table.setAlternatingRowColors(True)
        self.stocks_insider_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stocks_insider_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.stocks_insider_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        insider_header = self.stocks_insider_table.horizontalHeader()
        insider_header.setMinimumHeight(24)
        insider_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        insider_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        insider_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        insider_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        insider_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        insider_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.stocks_insider_table.setVisible(False)
        insider_layout.addWidget(self.stocks_insider_table, 1)

        chart_frame = QFrame()
        self.set_theme_role(chart_frame, 'panel')
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(10, 8, 10, 8)
        chart_layout.setSpacing(5)
        chart_title_row = QHBoxLayout()
        self.stocks_chart_title = QLabel('Stock Chart')
        self.set_theme_role(self.stocks_chart_title, 'page_title')
        self.stocks_auto_btn = QPushButton('Auto')
        self.stocks_auto_btn.setCheckable(True)
        self.stocks_auto_btn.clicked.connect(self._stocks_toggle_auto_follow)
        self.stocks_mfi_btn = QPushButton('MFI')
        self.stocks_mfi_btn.setCheckable(True)
        self.stocks_mfi_btn.clicked.connect(self._stocks_toggle_mfi_enabled)
        self.stocks_status_label = QLabel('Ready')
        self.set_theme_role(self.stocks_status_label, 'status_muted')
        chart_title_row.addWidget(self.stocks_chart_title)
        chart_title_row.addStretch()
        chart_title_row.addWidget(self.stocks_auto_btn)
        chart_title_row.addWidget(self.stocks_mfi_btn)
        chart_title_row.addWidget(self.stocks_status_label)
        chart_layout.addLayout(chart_title_row)
        chart_quote_row = QHBoxLayout()
        self.stocks_chart_symbol_label = QLabel(self.stocks_symbol)
        self.stocks_chart_price_label = QLabel('--')
        self.stocks_chart_change_label = QLabel('--')
        chart_quote_row.addWidget(self.stocks_chart_symbol_label)
        chart_quote_row.addWidget(self.stocks_chart_price_label)
        chart_quote_row.addWidget(self.stocks_chart_change_label)
        chart_quote_row.addStretch()
        chart_layout.addLayout(chart_quote_row)
        self.stocks_chart_ohlc_label = QLabel('O --  H --  L --  C --')
        chart_layout.addWidget(self.stocks_chart_ohlc_label)
        self.stocks_chart_axis = DateAxisItem(orientation='bottom')
        self.stocks_plot = pg.PlotWidget(axisItems={'bottom': self.stocks_chart_axis})
        self.stocks_plot.showGrid(x=True, y=True, alpha=0.15)
        self.stocks_plot.getPlotItem().setMenuEnabled(False)
        self.stocks_plot.getPlotItem().hideAxis('left')
        self.stocks_plot.getPlotItem().showAxis('right')
        self.stocks_plot.getPlotItem().hideButtons()
        self.stocks_plot.getPlotItem().vb.sigXRangeChanged.connect(self._stocks_on_x_range_changed)
        self.stocks_plot.getPlotItem().vb.sigRangeChanged.connect(self._stocks_refresh_mfi_overlay_position)
        chart_layout.addWidget(self.stocks_plot, 1)
        self.stocks_mfi_axis = DateAxisItem(orientation='bottom')
        self.stocks_mfi_plot = pg.PlotWidget(axisItems={'bottom': self.stocks_mfi_axis})
        self.stocks_mfi_plot.showGrid(x=True, y=True, alpha=0.1)
        self.stocks_mfi_plot.getPlotItem().setMenuEnabled(False)
        self.stocks_mfi_plot.getPlotItem().hideAxis('left')
        self.stocks_mfi_plot.getPlotItem().showAxis('right')
        self.stocks_mfi_plot.setMaximumHeight(120)
        self.stocks_mfi_plot.setXLink(self.stocks_plot)
        self.stocks_mfi_plot.getPlotItem().vb.sigRangeChanged.connect(self._stocks_refresh_mfi_overlay_position)
        chart_layout.addWidget(self.stocks_mfi_plot)
        self._stocks_update_indicator_panel_visibility()

        self.stocks_left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.stocks_left_splitter.setHandleWidth(6)
        self.stocks_left_splitter.addWidget(fundamentals_frame)
        self.stocks_left_splitter.addWidget(price_targets_frame)
        self.stocks_left_splitter.addWidget(description_frame)
        self.stocks_left_splitter.setStretchFactor(0, 4)
        self.stocks_left_splitter.setStretchFactor(1, 2)
        self.stocks_left_splitter.setStretchFactor(2, 3)
        left_layout.addWidget(self.stocks_left_splitter, 1)

        middle_column = QWidget()
        middle_column.setMinimumWidth(300)
        middle_layout = QVBoxLayout(middle_column)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)
        self.stocks_middle_splitter = QSplitter(Qt.Orientation.Vertical)
        self.stocks_middle_splitter.setHandleWidth(6)
        self.stocks_middle_splitter.addWidget(news_frame)
        self.stocks_middle_splitter.addWidget(institutional_frame)
        self.stocks_middle_splitter.addWidget(insider_frame)
        self.stocks_middle_splitter.setStretchFactor(0, 2)
        self.stocks_middle_splitter.setStretchFactor(1, 2)
        self.stocks_middle_splitter.setStretchFactor(2, 3)
        middle_layout.addWidget(self.stocks_middle_splitter, 1)

        right_column = QWidget()
        right_column.setMinimumWidth(360)
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(chart_frame, 1)

        self.stocks_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.stocks_main_splitter.setHandleWidth(6)
        self.stocks_main_splitter.addWidget(left_column)
        self.stocks_main_splitter.addWidget(middle_column)
        self.stocks_main_splitter.addWidget(right_column)
        self.stocks_main_splitter.setStretchFactor(0, 3)
        self.stocks_main_splitter.setStretchFactor(1, 3)
        self.stocks_main_splitter.setStretchFactor(2, 5)

        layout.addWidget(self.stocks_main_splitter, 1)
        self._stocks_apply_splitter_sizes()
        self.stocks_left_splitter.splitterMoved.connect(self._stocks_on_splitter_moved)
        self.stocks_middle_splitter.splitterMoved.connect(self._stocks_on_splitter_moved)
        self.stocks_main_splitter.splitterMoved.connect(self._stocks_on_splitter_moved)
        self.stocks_crosshair_proxy = pg.SignalProxy(self.stocks_plot.scene().sigMouseMoved, rateLimit=30, slot=self._stocks_on_mouse_moved)
        self._apply_stocks_theme()

    def _stocks_on_show(self) -> None:
        if not self._stocks_loaded_once:
            self._stocks_loaded_once = True
            self._stocks_load_from_input()

    def _stocks_session_snapshot(self) -> dict[str, Any] | None:
        """Return the current Stocks workspace snapshot when data is loaded."""
        payload = getattr(self, '_stocks_loaded_payload', None)
        if not isinstance(payload, dict):
            return None
        symbol = str(payload.get('symbol', '') or '').upper().strip()
        if not symbol:
            return None
        return {
            'symbol': symbol,
            'payload': serialize_session_value(payload),
        }

    def _stocks_save_session_snapshot(self, *, immediate: bool=False) -> None:
        """Persist the latest Stocks workspace snapshot."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('stocks', self._stocks_session_snapshot(), immediate=immediate)

    def _stocks_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Restore the Stocks workspace from cached session data."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        restored_payload = deserialize_session_value(payload.get('payload'))
        if not isinstance(restored_payload, dict):
            return False
        self._stocks_loaded_once = True
        self._stocks_apply_payload_to_ui(
            restored_payload,
            include_global_status=False,
            update_collection_info=False,
            status_text=f"Restored last session for {str(restored_payload.get('symbol', '') or self.stocks_symbol).upper().strip()}.",
        )
        return True

    def _stocks_restore_startup_session(self, snapshot: Any) -> None:
        """Hydrate Stocks from the last session, then refresh it in the background."""
        restored = self._stocks_restore_session_snapshot(snapshot)
        symbol = str(self.stocks_symbol_input.text() or self.stocks_symbol or '').upper().strip()
        if restored and symbol:
            self._stocks_load_from_input(include_global_status=False, update_collection_info=False)

    def _stocks_save_state(self) -> None:
        self.stocks_page_state = save_stocks_page_settings({
            **getattr(self, 'stocks_page_state', {}),
            'symbol': self.stocks_symbol,
            'auto': self.stocks_auto_follow,
            'mfi_enabled': self.stocks_mfi_enabled,
            'main_splitter_sizes': self._stocks_current_splitter_sizes('stocks_main_splitter', 3, 'main_splitter_sizes'),
            'left_splitter_sizes': self._stocks_current_splitter_sizes('stocks_left_splitter', 3, 'left_splitter_sizes'),
            'middle_splitter_sizes': self._stocks_current_splitter_sizes('stocks_middle_splitter', 3, 'middle_splitter_sizes'),
        })

    def _stocks_current_splitter_sizes(self, splitter_name: str, expected_count: int, state_key: str) -> list[int]:
        splitter = getattr(self, splitter_name, None)
        if splitter is not None:
            sizes = [int(size) for size in splitter.sizes() if int(size) > 0]
            if len(sizes) == expected_count:
                return sizes
        saved = getattr(self, 'stocks_page_state', {})
        fallback = saved.get(state_key, DEFAULT_STOCKS_PAGE_SETTINGS.get(state_key, [])) if isinstance(saved, dict) else DEFAULT_STOCKS_PAGE_SETTINGS.get(state_key, [])
        return [int(size) for size in list(fallback)[:expected_count]]

    def _stocks_apply_splitter_sizes(self) -> None:
        state = load_stocks_page_settings() if not isinstance(getattr(self, 'stocks_page_state', None), dict) else self.stocks_page_state
        self.stocks_page_state = dict(state)
        if hasattr(self, 'stocks_left_splitter'):
            self.stocks_left_splitter.setSizes([int(size) for size in self.stocks_page_state.get('left_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['left_splitter_sizes'])])
        if hasattr(self, 'stocks_middle_splitter'):
            self.stocks_middle_splitter.setSizes([int(size) for size in self.stocks_page_state.get('middle_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['middle_splitter_sizes'])])
        if hasattr(self, 'stocks_main_splitter'):
            self.stocks_main_splitter.setSizes([int(size) for size in self.stocks_page_state.get('main_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['main_splitter_sizes'])])

    def _stocks_on_splitter_moved(self, *_: Any) -> None:
        self._stocks_save_state()

    def _stocks_set_status(self, text: Any, status: Any='muted', *, include_global: bool=True) -> None:
        self.set_status_text(self.stocks_status_label, text, status=str(status))
        if include_global and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _stocks_update_auto_button_style(self) -> None:
        self.stocks_auto_btn.blockSignals(True)
        self.stocks_auto_btn.setChecked(self.stocks_auto_follow)
        self.stocks_auto_btn.blockSignals(False)
        self.set_theme_variant(self.stocks_auto_btn, 'accent' if self.stocks_auto_follow else None)
        self.stocks_auto_btn.setProperty('bt_checked', 'true' if self.stocks_auto_follow else 'false')
        self._repolish_widget(self.stocks_auto_btn)

    def _stocks_update_mfi_button_style(self) -> None:
        self.stocks_mfi_btn.blockSignals(True)
        self.stocks_mfi_btn.setChecked(self.stocks_mfi_enabled)
        self.stocks_mfi_btn.blockSignals(False)
        self.set_theme_variant(self.stocks_mfi_btn, 'positive' if self.stocks_mfi_enabled else None)
        self.stocks_mfi_btn.setProperty('bt_checked', 'true' if self.stocks_mfi_enabled else 'false')
        self._repolish_widget(self.stocks_mfi_btn)

    def _stocks_update_indicator_panel_visibility(self) -> None:
        self.stocks_mfi_plot.setVisible(bool(self.stocks_mfi_enabled and self._stocks_chart_rows))

    def _stocks_toggle_auto_follow(self, checked: Any=False) -> None:
        self.stocks_auto_follow = bool(checked)
        if not self.stocks_auto_follow:
            self._stocks_manual_x_range = self._stocks_get_current_x_range()
        self._stocks_update_auto_button_style()
        self._stocks_save_state()
        if self.stocks_auto_follow and self._stocks_chart_rows:
            self._stocks_apply_auto_x_range(self._stocks_get_current_x_range())

    def _stocks_toggle_mfi_enabled(self, checked: Any=False) -> None:
        self.stocks_mfi_enabled = bool(checked)
        self._stocks_update_mfi_button_style()
        self._stocks_render_mfi_panel()
        self._stocks_save_state()

    def _stocks_get_current_x_range(self) -> Any:
        try:
            return tuple(self.stocks_plot.getPlotItem().vb.viewRange()[0])
        except Exception:
            return None

    def _stocks_set_x_range(self, x_range: Any) -> None:
        if not x_range:
            return
        left, right = x_range
        if right <= left:
            return
        self._stocks_view_change_guard = True
        try:
            self.stocks_plot.setXRange(float(left), float(right), padding=0)
        finally:
            self._stocks_view_change_guard = False

    def _stocks_normalize_x_range(self, x_range: Any) -> Any:
        if not x_range or not self._stocks_chart_rows:
            return None
        left, right = (float(x_range[0]), float(x_range[1]))
        span = max(2.0, right - left)
        latest_index = max(0.0, float(len(self._stocks_chart_rows) - 1))
        center = max(0.0, min((left + right) / 2.0, latest_index))
        return (center - span / 2.0, center + span / 2.0)

    def _stocks_is_reusable_x_range(self, x_range: Any) -> bool:
        if not x_range:
            return False
        try:
            left = float(x_range[0])
            right = float(x_range[1])
        except Exception:
            return False
        return right > left and (right - left) >= STOCKS_MIN_REUSABLE_SPAN

    def _stocks_apply_auto_x_range(self, source_range: Any=None) -> None:
        if not self._stocks_chart_rows:
            return
        latest_index = float(len(self._stocks_chart_rows) - 1)
        if self._stocks_is_reusable_x_range(source_range):
            span = max(STOCKS_MIN_REUSABLE_SPAN, float(source_range[1]) - float(source_range[0]))
        else:
            span = max(20.0, min(float(STOCKS_DEFAULT_VISIBLE_BARS), float(len(self._stocks_chart_rows))))
        right_padding = span * (1.0 - STOCKS_AUTO_ANCHOR)
        anchored = (latest_index - span * STOCKS_AUTO_ANCHOR, latest_index + right_padding)
        self._stocks_set_x_range(anchored)
        self._stocks_apply_auto_y_range(anchored)

    def _stocks_get_visible_rows(self, x_range: Any=None) -> list[Any]:
        if not self._stocks_chart_rows:
            return []
        active_range = x_range or self._stocks_get_current_x_range()
        if not active_range:
            return list(self._stocks_chart_rows)
        left = max(0, int(math.floor(float(active_range[0]))))
        right = min(len(self._stocks_chart_rows) - 1, int(math.ceil(float(active_range[1]))))
        if right < left:
            return []
        return self._stocks_chart_rows[left:right + 1]

    def _stocks_apply_auto_y_range(self, x_range: Any=None) -> None:
        visible_rows = self._stocks_get_visible_rows(x_range)
        if not visible_rows:
            return
        low_value = min(float(getattr(row, 'Low')) for row in visible_rows)
        high_value = max(float(getattr(row, 'High')) for row in visible_rows)
        span = high_value - low_value
        padding = max(span * 0.08, max(abs(high_value) * 0.02, 1.0))
        self.stocks_plot.setYRange(low_value - padding, high_value + padding, padding=0)

    def _stocks_restore_manual_x_range(self) -> None:
        x_range = self._stocks_pending_x_range or self._stocks_manual_x_range
        normalized = self._stocks_normalize_x_range(x_range)
        if normalized:
            self._stocks_set_x_range(normalized)
            self._stocks_manual_x_range = normalized

    def _stocks_on_x_range_changed(self, *_: Any) -> None:
        if self._stocks_view_change_guard or not self._stocks_chart_rows:
            return
        current_range = self._stocks_get_current_x_range()
        if not current_range:
            return
        if self.stocks_auto_follow:
            self._stocks_apply_auto_x_range(current_range)
            self._stocks_apply_auto_y_range(self._stocks_get_current_x_range())
        else:
            self._stocks_manual_x_range = current_range

    def _stocks_load_from_input(self, *_: Any, include_global_status: bool=True, update_collection_info: bool=True) -> None:
        symbol = str(self.stocks_symbol_input.text() or self.stocks_symbol or 'SPY').upper().strip() or 'SPY'
        self.stocks_symbol = symbol
        self.stocks_symbol_input.setText(symbol)
        self._stocks_save_state()
        if self.stocks_auto_follow:
            self._stocks_pending_x_range = self._stocks_get_current_x_range()
        else:
            self._stocks_pending_x_range = self._stocks_get_current_x_range() or self._stocks_manual_x_range
        self._stocks_request_seq += 1
        request_id = self._stocks_request_seq
        self._stocks_active_request = request_id
        self._stocks_request_contexts[request_id] = {
            'include_global_status': bool(include_global_status),
            'update_collection_info': bool(update_collection_info),
        }
        self.stocks_load_btn.setEnabled(False)
        self._stocks_set_status(f'Loading {symbol}...', 'info', include_global=include_global_status)

        def _run() -> None:
            try:
                payload = self._stocks_fetch_payload(symbol)
                self._invoke_main.emit(lambda data=payload, req=request_id: self._stocks_apply_payload(req, data))
            except Exception as exc:
                self._invoke_main.emit(lambda msg=str(exc), req=request_id: self._stocks_handle_error(req, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _stocks_fetch_payload(self, symbol: str) -> dict[str, Any]:
        chart_payload = self._chart_fetch_payload(symbol, period=STOCKS_CHART_PERIOD, interval=STOCKS_CHART_INTERVAL, timeframe_label='3 Years', include_rsi=False, include_ma200=False)
        ticker_obj = yf.Ticker(symbol)
        try:
            info = ticker_obj.info or {}
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks metadata for %s; continuing with chart data.', symbol)
            else:
                logger.info('Stocks metadata fetch failed for %s: %s', symbol, exc)
            info = {}
        if not isinstance(info, dict):
            info = {}
        try:
            financials = ticker_obj.financials
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks financials for %s.', symbol)
            financials = None
        try:
            quarterly_financials = ticker_obj.quarterly_financials
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks quarterly financials for %s.', symbol)
            quarterly_financials = None
        try:
            balance_sheet = ticker_obj.balance_sheet
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks balance sheet for %s.', symbol)
            balance_sheet = None
        try:
            quarterly_balance_sheet = ticker_obj.quarterly_balance_sheet
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks quarterly balance sheet for %s.', symbol)
            quarterly_balance_sheet = None
        try:
            earnings_dates = ticker_obj.earnings_dates
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused optional stocks earnings dates for %s.', symbol)
            earnings_dates = None
        return {
            'symbol': symbol,
            'chart': chart_payload,
            'info': info,
            'financials': financials,
            'quarterly_financials': quarterly_financials,
            'balance_sheet': balance_sheet,
            'quarterly_balance_sheet': quarterly_balance_sheet,
            'earnings_dates': earnings_dates,
            'news': self._stocks_fetch_news_items(ticker_obj, symbol),
            'institutional_rows': self._stocks_fetch_institutional_rows(ticker_obj),
            'insider_rows': self._stocks_fetch_insider_rows(ticker_obj),
        }

    def _stocks_fetch_institutional_rows(self, ticker_obj: Any) -> list[dict[str, Any]]:
        raw_rows = None
        getter = getattr(ticker_obj, 'get_institutional_holders', None)
        if callable(getter):
            try:
                raw_rows = getter()
            except Exception:
                raw_rows = None
        if raw_rows is None:
            try:
                raw_rows = getattr(ticker_obj, 'institutional_holders', None)
            except Exception:
                raw_rows = None
        if raw_rows is None:
            return []
        if not isinstance(raw_rows, pd.DataFrame):
            try:
                raw_rows = pd.DataFrame(raw_rows)
            except Exception:
                return []
        return self._stocks_normalize_institutional_rows(raw_rows)

    def _stocks_fetch_insider_rows(self, ticker_obj: Any) -> list[dict[str, Any]]:
        raw_rows = None
        getter = getattr(ticker_obj, 'get_insider_transactions', None)
        if callable(getter):
            try:
                raw_rows = getter()
            except Exception:
                raw_rows = None
        if raw_rows is None:
            try:
                raw_rows = getattr(ticker_obj, 'insider_transactions', None)
            except Exception:
                raw_rows = None
        if raw_rows is None:
            return []
        if not isinstance(raw_rows, pd.DataFrame):
            try:
                raw_rows = pd.DataFrame(raw_rows)
            except Exception:
                return []
        return self._stocks_normalize_insider_rows(raw_rows)

    def _stocks_fetch_news_items(self, ticker_obj: Any, symbol: str) -> list[dict[str, Any]]:
        try:
            news_items = list(getattr(ticker_obj, 'news', []) or [])[:STOCKS_NEWS_LIMIT]
        except Exception:
            return []
        articles = []
        for item in news_items:
            article = self._stocks_parse_news_item(item, symbol)
            if article is not None:
                articles.append(article)
        return articles

    def _stocks_apply_payload_to_ui(
        self,
        payload: dict[str, Any],
        *,
        include_global_status: bool=True,
        update_collection_info: bool=True,
        status_text: str | None=None,
    ) -> None:
        """Apply one fetched or restored Stocks payload to the UI."""
        chart_payload = payload.get('chart', {})
        self._stocks_info = payload.get('info', {}) if isinstance(payload.get('info', {}), dict) else {}
        self.stocks_symbol = str(payload.get('symbol') or self.stocks_symbol).upper().strip()
        self._stocks_loaded_symbol = self.stocks_symbol
        self._stocks_loaded_payload = payload
        self.stocks_symbol_input.setText(self.stocks_symbol)
        self._stocks_save_state()
        self._stocks_chart_df = chart_payload.get('df')
        self._stocks_chart_stats = chart_payload.get('stats', {}) or {}
        self._stocks_chart_interval = str(chart_payload.get('interval') or STOCKS_CHART_INTERVAL)
        self._stocks_chart_rows = list(self._stocks_chart_df.itertuples()) if self._stocks_chart_df is not None else []
        self._stocks_mfi_series = self._stocks_calculate_mfi(self._stocks_chart_df)
        self._stocks_render_chart()
        if self.stocks_auto_follow:
            self._stocks_apply_auto_x_range(self._stocks_pending_x_range)
        else:
            self._stocks_restore_manual_x_range()
            self._stocks_apply_auto_y_range(self._stocks_get_current_x_range() or self._stocks_pending_x_range or self._stocks_manual_x_range)
        self._stocks_update_quote_header(self._stocks_chart_stats)
        self._stocks_show_row_details(len(self._stocks_chart_rows) - 1)
        self._stocks_render_fundamentals(payload)
        self._stocks_loaded_news = [dict(article) for article in list(payload.get('news', []) or []) if isinstance(article, dict)]
        self._stocks_loaded_institutional_rows = [dict(row) for row in list(payload.get('institutional_rows', []) or []) if isinstance(row, dict)]
        self._stocks_loaded_insider_rows = [dict(row) for row in list(payload.get('insider_rows', []) or []) if isinstance(row, dict)]
        self._stocks_render_news_rows(self._stocks_loaded_news)
        self._stocks_render_institutional_rows(self._stocks_loaded_institutional_rows)
        self._stocks_render_insider_rows(self._stocks_loaded_insider_rows)
        self.stocks_load_btn.setEnabled(True)
        self._stocks_pending_x_range = None
        if update_collection_info:
            self._set_data_collection_info(['yfinance'])
        self._stocks_set_status(status_text or f'Loaded {self.stocks_symbol}.', 'positive', include_global=include_global_status)
        self._stocks_save_session_snapshot()

    def _stocks_apply_payload(self, request_id: int, payload: dict[str, Any]) -> None:
        if request_id != self._stocks_active_request:
            self._stocks_request_contexts.pop(request_id, None)
            return
        context = self._stocks_request_contexts.pop(request_id, {})
        self._stocks_apply_payload_to_ui(
            payload,
            include_global_status=bool(context.get('include_global_status', True)),
            update_collection_info=bool(context.get('update_collection_info', True)),
        )

    def _stocks_handle_error(self, request_id: int, message: str) -> None:
        if request_id != self._stocks_active_request:
            self._stocks_request_contexts.pop(request_id, None)
            return
        context = self._stocks_request_contexts.pop(request_id, {})
        self.stocks_load_btn.setEnabled(True)
        self._stocks_pending_x_range = None
        self._stocks_set_status(
            f'Stocks load failed: {message}',
            'negative',
            include_global=bool(context.get('include_global_status', True)),
        )

    def _stocks_render_chart(self) -> None:
        self.style_plot_widget(self.stocks_plot)
        if not self._stocks_chart_rows:
            self.stocks_plot.clear()
            self._stocks_candle_item = None
            self._stocks_last_price_line = None
            self._stocks_clear_mfi_panel()
            self._stocks_update_indicator_panel_visibility()
            return
        points = []
        for idx, row in enumerate(self._stocks_chart_rows):
            points.append((idx, float(getattr(row, 'Open')), float(getattr(row, 'Close')), float(getattr(row, 'Low')), float(getattr(row, 'High'))))
        candle_item = CandlestickItem(points, up_color=self.theme_color('chart_up_candle'), down_color=self.theme_color('chart_down_candle'))
        if self._stocks_candle_item is not None:
            try:
                self.stocks_plot.removeItem(self._stocks_candle_item)
            except Exception:
                pass
        self._stocks_candle_item = candle_item
        self.stocks_plot.addItem(candle_item)
        last_close = float(self._stocks_chart_stats.get('close', 0.0))
        if self._stocks_last_price_line is None:
            self._stocks_last_price_line = pg.InfiniteLine(pos=last_close, angle=0, pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
            self.stocks_plot.addItem(self._stocks_last_price_line)
        self._stocks_last_price_line.setValue(last_close)
        self._stocks_last_price_line.setPen(self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
        self.stocks_chart_axis.set_dates(self._stocks_chart_df.index.to_list(), self._stocks_chart_interval)
        self._stocks_render_mfi_panel()

    def _stocks_update_quote_header(self, stats: Any) -> None:
        if not stats:
            self.stocks_chart_price_label.setText('--')
            self.stocks_chart_change_label.setText('--')
            return
        close_value = float(stats.get('close', 0.0))
        change_value = float(stats.get('change_value', 0.0))
        change_pct = float(stats.get('change_pct', 0.0))
        change_color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        sign = '+' if change_value >= 0 else ''
        self.stocks_chart_price_label.setText(f'${close_value:,.2f}')
        self.stocks_chart_change_label.setText(f'{sign}${change_value:,.2f} ({sign}{change_pct:.2f}%)')
        self.stocks_chart_change_label.setStyleSheet(f'font-size: 13px; font-weight: bold; color: {change_color};')

    def _stocks_show_row_details(self, row_index: Any) -> None:
        if not self._stocks_chart_rows:
            self.stocks_chart_ohlc_label.setText('O --  H --  L --  C --')
            return
        row_index = max(0, min(int(row_index), len(self._stocks_chart_rows) - 1))
        row = self._stocks_chart_rows[row_index]
        open_value = float(getattr(row, 'Open'))
        high_value = float(getattr(row, 'High'))
        low_value = float(getattr(row, 'Low'))
        close_value = float(getattr(row, 'Close'))
        volume_value = float(getattr(row, 'Volume', 0.0) or 0.0)
        self.stocks_chart_ohlc_label.setText(f'O {open_value:,.2f}   H {high_value:,.2f}   L {low_value:,.2f}   C {close_value:,.2f}   Vol {fmt_num(volume_value)}')

    def _stocks_on_mouse_moved(self, event: Any) -> None:
        if not self._stocks_chart_rows:
            return
        pos = event[0]
        if not self.stocks_plot.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.stocks_plot.getPlotItem().vb.mapSceneToView(pos)
        self._stocks_show_row_details(int(round(mouse_point.x())))

    def _stocks_calculate_mfi(self, df: Any, period: int=STOCKS_MFI_PERIOD) -> Any:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.Series(dtype=float)
        required = ('High', 'Low', 'Close', 'Volume')
        if any(column not in df.columns for column in required):
            return pd.Series(index=df.index, dtype=float)
        high = pd.Series(df['High'], index=df.index).astype(float)
        low = pd.Series(df['Low'], index=df.index).astype(float)
        close = pd.Series(df['Close'], index=df.index).astype(float)
        volume = pd.Series(df['Volume'], index=df.index).fillna(0.0).astype(float)
        typical_price = (high + low + close) / 3.0
        raw_money_flow = typical_price * volume
        price_delta = typical_price.diff()
        positive_flow = raw_money_flow.where(price_delta > 0, 0.0)
        negative_flow = raw_money_flow.where(price_delta < 0, 0.0).abs()
        positive_sum = positive_flow.rolling(period, min_periods=period).sum()
        negative_sum = negative_flow.rolling(period, min_periods=period).sum()
        money_ratio = positive_sum / negative_sum.replace(0.0, float('nan'))
        mfi = 100.0 - (100.0 / (1.0 + money_ratio))
        mfi = pd.Series(mfi, index=df.index, dtype=float)
        mfi = mfi.where(~((negative_sum == 0) & (positive_sum > 0)), 100.0)
        mfi = mfi.where(~((positive_sum == 0) & (negative_sum > 0)), 0.0)
        mfi = mfi.where(~((positive_sum == 0) & (negative_sum == 0)), 50.0)
        return mfi.clip(lower=0.0, upper=100.0)

    def _stocks_remove_chart_item(self, plot: Any, item: Any) -> None:
        if item is None:
            return
        try:
            plot.removeItem(item)
        except Exception:
            pass

    def _stocks_clear_mfi_panel(self) -> None:
        self._stocks_remove_chart_item(self.stocks_mfi_plot, self._stocks_mfi_line_item)
        self._stocks_remove_chart_item(self.stocks_mfi_plot, self._stocks_mfi_upper_line)
        self._stocks_remove_chart_item(self.stocks_mfi_plot, self._stocks_mfi_lower_line)
        self._stocks_remove_chart_item(self.stocks_mfi_plot, self._stocks_mfi_label_item)
        self._stocks_mfi_line_item = None
        self._stocks_mfi_upper_line = None
        self._stocks_mfi_lower_line = None
        self._stocks_mfi_label_item = None

    def _stocks_set_mfi_overlay_text(self, text: str) -> None:
        if not text:
            self._stocks_remove_chart_item(self.stocks_mfi_plot, self._stocks_mfi_label_item)
            self._stocks_mfi_label_item = None
            return
        if self._stocks_mfi_label_item is None:
            self._stocks_mfi_label_item = pg.TextItem(color=self.theme_color('chart_rsi'), anchor=(1, 0))
            try:
                self._stocks_mfi_label_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            except Exception:
                pass
            self.stocks_mfi_plot.addItem(self._stocks_mfi_label_item, ignoreBounds=True)
        self._stocks_mfi_label_item.setText(text, color=self.theme_color('chart_rsi'))

    def _stocks_refresh_mfi_overlay_position(self, *_: Any) -> None:
        if self._stocks_mfi_label_item is None:
            return
        try:
            x_range, y_range = self.stocks_mfi_plot.getPlotItem().vb.viewRange()
        except Exception:
            return
        x_left, x_right = x_range
        y_bottom, y_top = y_range
        x_pos = float(x_right) - (float(x_right) - float(x_left)) * 0.02
        y_pos = float(y_top) - (float(y_top) - float(y_bottom)) * 0.04
        self._stocks_mfi_label_item.setPos(x_pos, y_pos)

    def _stocks_render_mfi_panel(self) -> None:
        self._stocks_update_indicator_panel_visibility()
        if not self.stocks_mfi_enabled or not self._stocks_chart_rows or self._stocks_mfi_series is None or len(self._stocks_mfi_series) == 0:
            self._stocks_clear_mfi_panel()
            return
        self.style_plot_widget(self.stocks_mfi_plot)
        x_values = list(range(len(self._stocks_mfi_series)))
        y_values = [float(value) if not pd.isna(value) else float('nan') for value in self._stocks_mfi_series]
        if self._stocks_mfi_line_item is None:
            self._stocks_mfi_line_item = self.stocks_mfi_plot.plot([], [], pen=self.theme_pen('chart_rsi', width=2.0), antialias=True)
        self._stocks_mfi_line_item.setData(x_values, y_values)
        self._stocks_mfi_line_item.setPen(self.theme_pen('chart_rsi', width=2.0))
        if self._stocks_mfi_upper_line is None:
            self._stocks_mfi_upper_line = pg.InfiniteLine(pos=STOCKS_MFI_OVERBOUGHT, angle=0, pen=self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine))
            self.stocks_mfi_plot.addItem(self._stocks_mfi_upper_line)
        if self._stocks_mfi_lower_line is None:
            self._stocks_mfi_lower_line = pg.InfiniteLine(pos=STOCKS_MFI_OVERSOLD, angle=0, pen=self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine))
            self.stocks_mfi_plot.addItem(self._stocks_mfi_lower_line)
        self._stocks_mfi_upper_line.setPen(self.theme_pen('warning', width=1, style=Qt.PenStyle.DashLine))
        self._stocks_mfi_lower_line.setPen(self.theme_pen('accent_positive', width=1, style=Qt.PenStyle.DashLine))
        self.stocks_mfi_axis.set_dates(self._stocks_chart_df.index.to_list(), self._stocks_chart_interval)
        self.stocks_mfi_plot.setYRange(0, 100, padding=0.02)
        latest_mfi = None
        for value in reversed(list(self._stocks_mfi_series)):
            if not pd.isna(value):
                latest_mfi = float(value)
                break
        label_text = f'MFI({STOCKS_MFI_PERIOD}) {latest_mfi:.2f}' if latest_mfi is not None else f'MFI({STOCKS_MFI_PERIOD}) --'
        self._stocks_set_mfi_overlay_text(label_text)
        self._stocks_refresh_mfi_overlay_position()

    def _stocks_render_fundamentals(self, payload: dict[str, Any]) -> None:
        info = payload.get('info', {}) if isinstance(payload.get('info', {}), dict) else {}
        financials = payload.get('financials')
        quarterly_financials = payload.get('quarterly_financials')
        balance_sheet = payload.get('balance_sheet')
        quarterly_balance_sheet = payload.get('quarterly_balance_sheet')
        chart_stats = payload.get('chart', {}).get('stats', {}) if isinstance(payload.get('chart', {}), dict) else {}
        symbol = str(payload.get('symbol') or self.stocks_symbol)
        company_name = str(info.get('longName') or info.get('shortName') or symbol).strip() or symbol
        subtitle = ' | '.join(part for part in (str(info.get('exchange') or '').strip(), str(info.get('sector') or '').strip(), str(info.get('industry') or '').strip()) if part)
        self.stocks_company_label.setText(company_name if not subtitle else f'{company_name}\n{subtitle}')
        self.stocks_chart_symbol_label.setText(symbol)
        metrics = {
            'market_cap': self._stocks_format_compact_value(self._stocks_info_value(info, 'marketCap')),
            'revenue': self._stocks_format_compact_value(self._stocks_info_value(info, 'totalRevenue') or self._stocks_extract_statement_value((quarterly_financials, financials), ('total revenue', 'revenue'))),
            'net_income': self._stocks_format_compact_value(self._stocks_info_value(info, 'netIncomeToCommon', 'netIncome') or self._stocks_extract_statement_value((quarterly_financials, financials), ('net income',))),
            'eps': self._stocks_format_decimal(self._stocks_info_value(info, 'trailingEps', 'currentEps') or self._stocks_extract_statement_value((quarterly_financials, financials), ('diluted eps', 'basic eps', 'net income per share'))),
            'gross_margin': self._stocks_format_percentage(self._stocks_extract_margin_ratio(
                info,
                info_keys=('grossMargins',),
                numerator_aliases=('gross profit',),
                denominator_aliases=('total revenue', 'revenue'),
                quarterly_frame=quarterly_financials,
                annual_frame=financials,
            )),
            'operating_margin': self._stocks_format_percentage(self._stocks_extract_margin_ratio(
                info,
                info_keys=('operatingMargins',),
                numerator_aliases=('operating income', 'ebit'),
                denominator_aliases=('total revenue', 'revenue'),
                quarterly_frame=quarterly_financials,
                annual_frame=financials,
            )),
            'net_margin': self._stocks_format_percentage(self._stocks_extract_margin_ratio(
                info,
                info_keys=('profitMargins', 'netMargins'),
                numerator_aliases=('net income',),
                denominator_aliases=('total revenue', 'revenue'),
                quarterly_frame=quarterly_financials,
                annual_frame=financials,
            )),
            'shares_outstanding': self._stocks_format_compact_value(self._stocks_info_value(info, 'sharesOutstanding') or self._stocks_extract_statement_value((quarterly_balance_sheet, balance_sheet), ('ordinary shares number', 'shares outstanding', 'common stock shares outstanding'))),
            'pe': self._stocks_format_ratio(self._stocks_info_value(info, 'trailingPE')),
            'forward_pe': self._stocks_format_ratio(self._stocks_info_value(info, 'forwardPE')),
            'dividend': self._stocks_format_dividend(info),
            'ex_dividend_date': self._stocks_format_date(self._stocks_info_value(info, 'exDividendDate')),
            'volume': self._stocks_format_compact_value(self._stocks_info_value(info, 'volume', 'regularMarketVolume') or chart_stats.get('volume')),
            'beta': self._stocks_format_decimal(self._stocks_info_value(info, 'beta')),
            'earnings_date': self._stocks_extract_earnings_date(info, payload.get('earnings_dates')),
        }
        for _, field_key in STOCKS_FUNDAMENTAL_FIELDS:
            self.stocks_metric_labels[field_key].setText(str(metrics.get(field_key, 'N/A')))
        self._stocks_render_price_targets(info, chart_stats)
        description_text = str(self._stocks_info_value(info, 'longBusinessSummary', 'description') or '').strip()
        self.stocks_description_output.setPlainText(description_text or 'No company description available.')

    def _stocks_render_price_targets(self, info: dict[str, Any], chart_stats: dict[str, Any]) -> None:
        current_price = self._stocks_info_value(info, 'currentPrice', 'regularMarketPrice') or chart_stats.get('close')
        mean_target = self._stocks_info_value(info, 'targetMeanPrice')
        upside_to_mean = self._stocks_calculate_target_upside(current_price, mean_target)
        values = {
            'mean_target': self._stocks_format_currency(mean_target),
            'upside_to_mean': upside_to_mean,
        }
        for _, field_key in STOCKS_PRICE_TARGET_FIELDS:
            self.stocks_target_labels[field_key].setText(str(values.get(field_key, 'N/A')))

    def _stocks_render_news_rows(self, articles: list[dict[str, Any]]) -> None:
        if not articles:
            self.stocks_news_table.setRowCount(0)
            self.stocks_news_table.setVisible(False)
            self.stocks_news_empty.setVisible(True)
            self.stocks_news_empty.setText('No recent headlines were available for this ticker.')
            return
        self._populate_news_table(self.stocks_news_table, articles)
        self.stocks_news_empty.setVisible(False)
        self.stocks_news_table.setVisible(True)

    def _stocks_render_institutional_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self.stocks_institutional_table.setRowCount(0)
            self.stocks_institutional_table.setVisible(False)
            self.stocks_institutional_empty.setVisible(True)
            self.stocks_institutional_empty.setText('No institutional holder rows were available for this ticker.')
            return
        self.stocks_institutional_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, key in enumerate(('holder', 'pct_held', 'shares', 'value', 'pct_change', 'reported')):
                item = QTableWidgetItem(str(row.get(key, '—') or '—'))
                if col_index in (1, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.stocks_institutional_table.setItem(row_index, col_index, item)
        self.stocks_institutional_empty.setVisible(False)
        self.stocks_institutional_table.setVisible(True)

    def _stocks_render_insider_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self.stocks_insider_table.setRowCount(0)
            self.stocks_insider_table.setVisible(False)
            self.stocks_insider_empty.setVisible(True)
            self.stocks_insider_empty.setText('No insider transaction rows were available for this ticker.')
            return
        self.stocks_insider_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, key in enumerate(('date', 'insider', 'title', 'transaction', 'shares', 'value')):
                item = QTableWidgetItem(str(row.get(key, '—') or '—'))
                if col_index in (4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.stocks_insider_table.setItem(row_index, col_index, item)
        self.stocks_insider_empty.setVisible(False)
        self.stocks_insider_table.setVisible(True)

    def _stocks_current_symbol(self) -> str:
        symbol = str(self.stocks_symbol_input.text() or self.stocks_symbol or 'SPY').upper().strip() or 'SPY'
        self.stocks_symbol = symbol
        self.stocks_symbol_input.setText(symbol)
        self._stocks_save_state()
        return symbol

    def _stocks_page_index(self, page_name: str, fallback_index: int) -> int:
        page = getattr(self, page_name, None)
        if page is not None and hasattr(self, 'stacked_widget'):
            try:
                page_index = self.stacked_widget.indexOf(page)
            except Exception:
                page_index = -1
            if page_index >= 0:
                return page_index
        return fallback_index

    def _stocks_go_to_charts(self) -> None:
        symbol = self._stocks_current_symbol()
        if not symbol:
            return
        self.p10_symbol = symbol
        if isinstance(getattr(self, 'chart_page_state', None), dict):
            self.chart_page_state = {
                **self.chart_page_state,
                'symbol': symbol,
            }
        page_index = self._stocks_page_index('page10', 9)
        page_ready = self._page_initialized(index=page_index)
        self.switch_page(page_index)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(symbol)
        if page_ready and hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()

    def _stocks_go_to_fundamentals(self) -> None:
        symbol = self._stocks_current_symbol()
        if not symbol:
            return
        self.switch_page(self._stocks_page_index('page2', 8))
        if hasattr(self, 'p2_ticker_input'):
            self.p2_ticker_input.setText(symbol)
        if hasattr(self, 'analyze_stock_p2'):
            self.analyze_stock_p2()

    def _stocks_go_to_options(self) -> None:
        symbol = self._stocks_current_symbol()
        if not symbol:
            return
        self.switch_page(self._stocks_page_index('page5', 11))
        if hasattr(self, 'p5_shared_ticker_input'):
            self.p5_shared_ticker_input.setText(symbol)
        if hasattr(self, '_p5_load_expiries'):
            self._p5_load_expiries()

    def _stocks_go_to_valuation(self) -> None:
        symbol = self._stocks_current_symbol()
        if not symbol:
            return
        page_index = self._stocks_page_index('page23', 22)
        if isinstance(getattr(self, 'valuation_page_state', None), dict):
            self.valuation_page_state = {
                **self.valuation_page_state,
                'last_ticker': symbol,
            }
        if hasattr(self, 'valuation_ticker_input'):
            self.valuation_ticker_input.setText(symbol)
        self.switch_page(page_index)
        if hasattr(self, 'valuation_ticker_input'):
            self.valuation_ticker_input.setText(symbol)
        if hasattr(self, 'load_valuation_data'):
            self.load_valuation_data(update_collection_info=True)

    def _stocks_export_escape(self, value: Any) -> str:
        text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
        return text.replace('|', '\\|')

    def _stocks_latest_mfi_value(self) -> Any:
        if self._stocks_mfi_series is None or len(self._stocks_mfi_series) == 0:
            return None
        for value in reversed(list(self._stocks_mfi_series)):
            if not pd.isna(value):
                return float(value)
        return None

    def _stocks_build_llm_export(self) -> str:
        symbol = str(self._stocks_loaded_symbol or self.stocks_chart_symbol_label.text() or self.stocks_symbol or 'SPY').upper().strip() or 'SPY'
        info = self._stocks_info if isinstance(self._stocks_info, dict) else {}
        company_name = str(info.get('longName') or info.get('shortName') or symbol).strip() or symbol
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        description_text = str(self.stocks_description_output.toPlainText() or '').strip()
        if not description_text:
            description_text = 'No company description available.'
        latest_mfi = self._stocks_latest_mfi_value() if self.stocks_mfi_enabled else None
        chart_df = self._stocks_chart_df.copy()
        include_mfi_column = bool(self.stocks_mfi_enabled and self._stocks_mfi_series is not None and len(self._stocks_mfi_series) == len(chart_df.index))
        lines = [
            f'# Stocks Export - {symbol}',
            '',
            f'- Symbol: {symbol}',
            f'- Company: {company_name}',
            f'- Exported at: {exported_at}',
            f'- Chart period: {STOCKS_CHART_PERIOD}',
            f'- Chart interval: {self._stocks_chart_interval or STOCKS_CHART_INTERVAL}',
            f'- Auto: {"On" if self.stocks_auto_follow else "Off"}',
            f'- MFI: {"On" if self.stocks_mfi_enabled else "Off"}',
        ]
        if self.stocks_mfi_enabled:
            lines.append(f'- Latest MFI({STOCKS_MFI_PERIOD}): {latest_mfi:.2f}' if latest_mfi is not None else f'- Latest MFI({STOCKS_MFI_PERIOD}): N/A')
        lines.extend([
            f'- Chart rows exported: {len(chart_df)}',
            '',
            '## Latest Quote Snapshot',
            '',
            f'- Open: {self._stocks_format_currency(self._stocks_chart_stats.get("open"))}',
            f'- High: {self._stocks_format_currency(self._stocks_chart_stats.get("high"))}',
            f'- Low: {self._stocks_format_currency(self._stocks_chart_stats.get("low"))}',
            f'- Close: {self._stocks_format_currency(self._stocks_chart_stats.get("close"))}',
            f'- Volume: {self._stocks_format_integer(self._stocks_chart_stats.get("volume"))}',
        ])
        try:
            change_value = float(self._stocks_chart_stats.get('change_value', 0.0))
            change_pct = float(self._stocks_chart_stats.get('change_pct', 0.0))
            sign = '+' if change_value >= 0 else ''
            lines.append(f'- Change: {sign}${change_value:,.2f} ({sign}{change_pct:.2f}%)')
        except Exception:
            lines.append('- Change: N/A')
        lines.extend([
            '',
            '## Overview',
            '',
        ])
        for label_text, field_key in STOCKS_FUNDAMENTAL_FIELDS:
            value_label = self.stocks_metric_labels.get(field_key)
            value_text = value_label.text().strip() if value_label is not None else 'N/A'
            lines.append(f'- {label_text}: {value_text or "N/A"}')
        lines.extend([
            '',
            '## Price Targets',
            '',
        ])
        for label_text, field_key in STOCKS_PRICE_TARGET_FIELDS:
            value_label = self.stocks_target_labels.get(field_key)
            value_text = value_label.text().strip() if value_label is not None else 'N/A'
            lines.append(f'- {label_text}: {value_text or "N/A"}')
        lines.extend([
            '',
            '## Description',
            '',
            description_text,
            '',
            '## News',
            '',
        ])
        news_rows = list(getattr(self, '_stocks_loaded_news', []) or [])
        if not news_rows:
            lines.append('(no news loaded)')
        else:
            lines.extend([
                '| Headline | Ticker | Source | Time | URL |',
                '| --- | --- | --- | --- | --- |',
            ])
            news_items = self._sort_articles_by_newest(news_rows) if hasattr(self, '_sort_articles_by_newest') else news_rows
            for article in news_items:
                lines.append(
                    '| {headline} | {ticker} | {source} | {time} | {url} |'.format(
                        headline=self._stocks_export_escape(article.get('title', '')),
                        ticker=self._stocks_export_escape(article.get('ticker', '')),
                        source=self._stocks_export_escape(article.get('source', '')),
                        time=self._stocks_export_escape(article.get('time', '')),
                        url=self._stocks_export_escape(article.get('url', '')),
                    )
                )
        lines.extend([
            '',
            '## Top Institutional Holders',
            '',
        ])
        institutional_rows = list(getattr(self, '_stocks_loaded_institutional_rows', []) or [])
        if not institutional_rows:
            lines.append('(no institutional holders loaded)')
        else:
            lines.extend([
                '| Holder | % Held | Shares | Value | Change | Reported |',
                '| --- | ---: | ---: | ---: | ---: | --- |',
            ])
            for row in institutional_rows:
                lines.append(
                    '| {holder} | {pct_held} | {shares} | {value} | {pct_change} | {reported} |'.format(
                        holder=self._stocks_export_escape(row.get('holder', '')),
                        pct_held=self._stocks_export_escape(row.get('pct_held', '')),
                        shares=self._stocks_export_escape(row.get('shares', '')),
                        value=self._stocks_export_escape(row.get('value', '')),
                        pct_change=self._stocks_export_escape(row.get('pct_change', '')),
                        reported=self._stocks_export_escape(row.get('reported', '')),
                    )
                )
        lines.extend([
            '',
            '## Insider Transactions',
            '',
        ])
        insider_rows = list(getattr(self, '_stocks_loaded_insider_rows', []) or [])
        if not insider_rows:
            lines.append('(no insider transactions loaded)')
        else:
            lines.extend([
                '| Date | Insider | Title/Relation | Transaction | Shares | Value |',
                '| --- | --- | --- | --- | ---: | ---: |',
            ])
            for row in insider_rows:
                lines.append(
                    '| {date} | {insider} | {title} | {transaction} | {shares} | {value} |'.format(
                        date=self._stocks_export_escape(row.get('date', '')),
                        insider=self._stocks_export_escape(row.get('insider', '')),
                        title=self._stocks_export_escape(row.get('title', '')),
                        transaction=self._stocks_export_escape(row.get('transaction', '')),
                        shares=self._stocks_export_escape(row.get('shares', '')),
                        value=self._stocks_export_escape(row.get('value', '')),
                    )
                )
        lines.extend([
            '',
            '## Chart History',
            '',
        ])
        header_columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        if include_mfi_column:
            header_columns.append(f'MFI{STOCKS_MFI_PERIOD}')
        lines.append('| ' + ' | '.join(header_columns) + ' |')
        lines.append('| --- | ---: | ---: | ---: | ---: | ---: |' + (' ---: |' if include_mfi_column else ''))
        mfi_series = self._stocks_mfi_series.reindex(chart_df.index) if include_mfi_column else None
        for idx, row in chart_df.iterrows():
            date_text = pd.Timestamp(idx).strftime('%Y-%m-%d')
            row_values = [
                date_text,
                f'{float(row["Open"]):,.2f}',
                f'{float(row["High"]):,.2f}',
                f'{float(row["Low"]):,.2f}',
                f'{float(row["Close"]):,.2f}',
                self._stocks_format_integer(row.get('Volume')),
            ]
            if include_mfi_column:
                mfi_value = mfi_series.loc[idx]
                row_values.append('' if pd.isna(mfi_value) else f'{float(mfi_value):.2f}')
            lines.append('| ' + ' | '.join(row_values) + ' |')
        return '\n'.join(lines).rstrip() + '\n'

    def _stocks_export_for_llm(self) -> None:
        if not isinstance(self._stocks_chart_df, pd.DataFrame) or self._stocks_chart_df.empty:
            self._stocks_set_status('Export failed: no stocks data is currently loaded.', 'warning')
            QMessageBox.warning(self, 'Export Failed', 'No Stocks data is currently loaded. Load a ticker and try again.')
            return
        symbol = str(self._stocks_loaded_symbol or self.stocks_symbol or 'SPY').upper().strip() or 'SPY'
        try:
            QApplication.clipboard().setText(self._stocks_build_llm_export())
        except Exception as exc:
            self._stocks_set_status(f'Export failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Export Failed', f'Unable to copy Stocks data to the clipboard.\n\n{exc}')
            return
        self._stocks_set_status(f'Stocks export copied to clipboard for {symbol}', 'positive')

    def _stocks_normalize_institutional_rows(self, raw_rows: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_rows, pd.DataFrame) or raw_rows.empty:
            return []
        frame = raw_rows.copy()
        frame.columns = [str(column or '').strip() for column in frame.columns]
        lower_map = {str(column).casefold(): column for column in frame.columns}

        def find_column(*aliases: str) -> Any:
            for alias in aliases:
                alias_key = str(alias).casefold()
                for lowered, original in lower_map.items():
                    if alias_key in lowered:
                        return original
            return None

        holder_column = find_column('holder', 'institution', 'name')
        pct_held_column = find_column('pctheld', 'pct held', '% held', 'held')
        shares_column = find_column('shares')
        value_column = find_column('value')
        pct_change_column = find_column('pctchange', 'pct change', '% change', 'change')
        reported_column = find_column('date reported', 'reported', 'date')
        if holder_column is None:
            return []

        sort_columns = [column for column in (pct_held_column, value_column, shares_column) if column is not None]
        if sort_columns:
            frame['_sort_score'] = pd.to_numeric(frame[sort_columns[0]], errors='coerce')
            frame = frame.sort_values(by='_sort_score', ascending=False, na_position='last')

        rows = []
        for _, row in frame.head(25).iterrows():
            holder_value = row.get(holder_column)
            if holder_value is None or pd.isna(holder_value):
                continue
            holder_text = str(holder_value or '').strip()
            if not holder_text:
                continue
            rows.append({
                'holder': holder_text,
                'pct_held': self._stocks_format_holder_percentage(row.get(pct_held_column)) if pct_held_column else 'N/A',
                'shares': self._stocks_format_shares(row.get(shares_column)) if shares_column else 'N/A',
                'value': self._stocks_format_currency(row.get(value_column)) if value_column else 'N/A',
                'pct_change': self._stocks_format_holder_change(row.get(pct_change_column)) if pct_change_column else 'N/A',
                'reported': self._stocks_format_date(row.get(reported_column)) if reported_column else 'N/A',
            })
        return rows

    def _stocks_normalize_insider_rows(self, raw_rows: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_rows, pd.DataFrame) or raw_rows.empty:
            return []
        frame = raw_rows.copy()
        frame.columns = [str(column or '').strip() for column in frame.columns]
        lower_map = {str(column).casefold(): column for column in frame.columns}

        def find_column(*aliases: str) -> Any:
            for alias in aliases:
                alias_key = str(alias).casefold()
                for lowered, original in lower_map.items():
                    if alias_key in lowered:
                        return original
            return None

        date_column = find_column('start date', 'transaction date', 'date')
        insider_column = find_column('insider', 'name')
        title_column = find_column('position', 'title', 'relation')
        transaction_text_column = find_column('text')
        transaction_column = find_column('transaction', 'description')
        shares_column = find_column('shares')
        value_column = find_column('value')
        if date_column is None and not isinstance(frame.index, pd.DatetimeIndex):
            return []
        frame['_sort_date'] = pd.to_datetime(frame[date_column], errors='coerce') if date_column is not None else pd.to_datetime(frame.index, errors='coerce')
        frame = frame.sort_values(by='_sort_date', ascending=False, na_position='last')
        rows = []
        for _, row in frame.head(25).iterrows():
            insider_value = row.get(insider_column) if insider_column else None
            title_value = row.get(title_column) if title_column else None
            transaction_text_value = row.get(transaction_text_column) if transaction_text_column else None
            transaction_value = row.get(transaction_column) if transaction_column else None
            insider_text = '—' if insider_value is None or pd.isna(insider_value) else str(insider_value or '—').strip()
            title_text = '—' if title_value is None or pd.isna(title_value) else str(title_value or '—').strip()
            transaction_text = '—'
            if transaction_text_value is not None and not pd.isna(transaction_text_value):
                transaction_text = str(transaction_text_value or '—').strip() or '—'
            elif transaction_value is not None and not pd.isna(transaction_value):
                transaction_text = str(transaction_value or '—').strip() or '—'
            shares_text = self._stocks_format_shares(row.get(shares_column)) if shares_column else '—'
            value_text = self._stocks_format_currency(row.get(value_column)) if value_column else '—'
            if not any(text not in ('', '—', 'N/A') for text in (insider_text, title_text, transaction_text, shares_text, value_text)):
                continue
            rows.append({
                'date': self._stocks_format_date(row.get('_sort_date')),
                'insider': insider_text or '—',
                'title': title_text or '—',
                'transaction': transaction_text or '—',
                'shares': shares_text,
                'value': value_text,
            })
        return rows

    def _stocks_info_value(self, info: dict[str, Any], *keys: str) -> Any:
        if not isinstance(info, dict):
            return None
        for key in keys:
            value = info.get(key)
            if value not in (None, '', 'N/A'):
                return value
        return None

    def _stocks_extract_statement_value(self, frames: Any, aliases: tuple[str, ...]) -> Any:
        for frame in tuple(frames or ()):
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            for index_label in frame.index:
                label = str(index_label or '').strip().casefold()
                if not any(alias in label for alias in aliases):
                    continue
                series = frame.loc[index_label]
                if isinstance(series, pd.Series):
                    non_null = series.dropna()
                    if not non_null.empty:
                        return non_null.iloc[0]
                elif pd.notna(series):
                    return series
        return None

    def _stocks_extract_margin_ratio(
        self,
        info: dict[str, Any],
        *,
        info_keys: tuple[str, ...],
        numerator_aliases: tuple[str, ...],
        denominator_aliases: tuple[str, ...],
        quarterly_frame: Any,
        annual_frame: Any,
    ) -> Any:
        ratio = self._stocks_info_value(info, *info_keys)
        if ratio not in (None, '', 'N/A'):
            return ratio
        numerator = self._stocks_extract_statement_value((quarterly_frame, annual_frame), numerator_aliases)
        denominator = self._stocks_extract_statement_value((quarterly_frame, annual_frame), denominator_aliases)
        try:
            numerator_value = float(numerator)
            denominator_value = float(denominator)
        except Exception:
            return None
        if not math.isfinite(numerator_value) or not math.isfinite(denominator_value) or denominator_value == 0:
            return None
        return numerator_value / denominator_value

    def _stocks_extract_earnings_date(self, info: dict[str, Any], earnings_dates: Any) -> str:
        candidates = []
        if isinstance(earnings_dates, pd.DataFrame) and not earnings_dates.empty:
            if isinstance(earnings_dates.index, pd.DatetimeIndex):
                candidates.extend(list(earnings_dates.index))
            for column in earnings_dates.columns:
                if 'date' in str(column).casefold() or 'earnings' in str(column).casefold():
                    parsed = pd.to_datetime(earnings_dates[column], errors='coerce')
                    candidates.extend([value for value in parsed.tolist() if not pd.isna(value)])
        for key in ('earningsDate', 'earningsTimestampStart', 'earningsTimestampEnd', 'earningsTimestamp'):
            raw_value = info.get(key)
            if isinstance(raw_value, list):
                candidates.extend(raw_value)
            elif raw_value not in (None, '', 'N/A'):
                candidates.append(raw_value)
        normalized = []
        for value in candidates:
            parsed = self._stocks_parse_datetime(value)
            if parsed is not None:
                normalized.append(parsed)
        if not normalized:
            return 'N/A'
        now = datetime.datetime.now().astimezone()
        future_dates = [value for value in normalized if value >= now]
        return self._stocks_format_date(min(future_dates) if future_dates else min(normalized))

    def _stocks_parse_datetime(self, value: Any) -> Any:
        if value in (None, '', 'N/A'):
            return None
        if isinstance(value, datetime.datetime):
            parsed = value
        else:
            try:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    parsed = datetime.datetime.fromtimestamp(float(value), tz=datetime.timezone.utc)
                else:
                    timestamp = pd.to_datetime(value, errors='coerce')
                    if pd.isna(timestamp):
                        return None
                    parsed = timestamp.to_pydatetime()
            except Exception:
                return None
        if isinstance(parsed, pd.Timestamp):
            parsed = parsed.to_pydatetime()
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=datetime.timezone.utc).astimezone(local_tz)
        return parsed.astimezone(local_tz)

    def _stocks_format_date(self, value: Any) -> str:
        parsed = self._stocks_parse_datetime(value)
        return parsed.strftime('%b %d, %Y') if parsed is not None else 'N/A'

    def _stocks_parse_news_item(self, item: Any, symbol: str) -> Any:
        if not isinstance(item, dict):
            return None
        content = item.get('content') or {}
        title = str(content.get('title') or item.get('title') or '').strip()
        if not title:
            return None
        source = str(content.get('provider', {}).get('displayName') or item.get('publisher') or 'N/A').strip() or 'N/A'
        pub_date = content.get('pubDate') or item.get('providerPublishTime') or ''
        time_text = '--:--'
        ts = 0.0
        if isinstance(pub_date, (int, float)) and not isinstance(pub_date, bool):
            ts = float(pub_date)
            try:
                time_text = datetime.datetime.fromtimestamp(float(pub_date)).strftime('%H:%M')
            except Exception:
                pass
        elif pub_date:
            try:
                parsed = datetime.datetime.fromisoformat(str(pub_date).replace('Z', '+00:00'))
                time_text = parsed.strftime('%H:%M')
                ts = parsed.timestamp()
            except Exception:
                time_text = str(pub_date)[:10]
        url_data = content.get('canonicalUrl') or content.get('clickThroughUrl') or item.get('link') or ''
        url = url_data.get('url', '') if isinstance(url_data, dict) else str(url_data or '')
        return {
            'ticker': symbol,
            'title': title,
            'source': source,
            'time': time_text,
            'url': url,
            'category': 'stock',
            '_ts': ts,
        }

    def _stocks_format_ratio(self, value: Any) -> str:
        try:
            return f'{float(value):.2f}x'
        except Exception:
            return 'N/A'

    def _stocks_format_decimal(self, value: Any) -> str:
        try:
            return f'{float(value):.2f}'
        except Exception:
            return 'N/A'

    def _stocks_format_percentage(self, value: Any) -> str:
        try:
            numeric = float(value) * 100.0
        except Exception:
            return 'N/A'
        return f'{numeric:.2f}%'

    def _stocks_format_holder_percentage(self, value: Any, *, signed: bool=False) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        percentage = numeric if abs(numeric) > 1.0 else numeric * 100.0
        sign = '+' if signed and percentage > 0 else ''
        return f'{sign}{percentage:.2f}%'

    def _stocks_format_holder_change(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        percentage = numeric * 100.0
        sign = '+' if percentage > 0 else ''
        return f'{sign}{percentage:.2f}%'

    def _stocks_format_compact_value(self, value: Any) -> str:
        try:
            return fmt_num(float(value))
        except Exception:
            return 'N/A'

    def _stocks_format_currency(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        return f'${fmt_num(numeric)}' if math.isfinite(numeric) and abs(numeric) >= 1000 else f'${numeric:,.2f}'

    def _stocks_format_integer(self, value: Any) -> str:
        try:
            return f'{int(float(value)):,}'
        except Exception:
            return 'N/A'

    def _stocks_calculate_target_upside(self, current_price: Any, mean_target: Any) -> str:
        try:
            current_value = float(current_price)
            target_value = float(mean_target)
        except Exception:
            return 'N/A'
        if not current_value:
            return 'N/A'
        upside_pct = (target_value - current_value) / current_value * 100.0
        sign = '+' if upside_pct >= 0 else ''
        return f'{sign}{upside_pct:.2f}%'

    def _stocks_format_shares(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        return fmt_num(numeric) if abs(numeric) >= 1000 else f'{numeric:,.0f}'

    def _stocks_format_dividend(self, info: dict[str, Any]) -> str:
        rate = self._stocks_info_value(info, 'dividendRate', 'trailingAnnualDividendRate')
        dividend_yield = self._stocks_info_value(info, 'dividendYield', 'trailingAnnualDividendYield')
        rate_text = self._stocks_format_currency(rate) if rate not in (None, '', 'N/A') else ''
        yield_text = ''
        try:
            if dividend_yield not in (None, '', 'N/A'):
                yield_text = f'{float(dividend_yield) * 100:.2f}%'
        except Exception:
            yield_text = ''
        if rate_text and yield_text:
            return f'{rate_text} ({yield_text})'
        return rate_text or yield_text or 'N/A'

    def _apply_stocks_theme(self) -> None:
        self.style_plot_widget(self.stocks_plot)
        self.style_plot_widget(self.stocks_mfi_plot)
        if self._stocks_candle_item is not None:
            self._stocks_candle_item.set_colors(self.theme_color('chart_up_candle'), self.theme_color('chart_down_candle'))
        if self._stocks_last_price_line is not None:
            self._stocks_last_price_line.setPen(self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine))
        splitter_style = f'QSplitter::handle {{ background: {self.theme_color("panel_border")}; border-radius: 2px; }}'
        for splitter_name in ('stocks_main_splitter', 'stocks_left_splitter', 'stocks_middle_splitter'):
            splitter = getattr(self, splitter_name, None)
            if splitter is not None:
                splitter.setStyleSheet(splitter_style)
        self.stocks_symbol_input.setStyleSheet(
            f'background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 6px 12px 8px 12px; '
            'font-size: 22px; font-weight: bold;'
        )
        self.stocks_company_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 14px; font-weight: bold;')
        self.stocks_chart_symbol_label.setStyleSheet(f'font-size: 18px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.stocks_chart_price_label.setStyleSheet(f'font-size: 18px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.stocks_chart_ohlc_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        self._stocks_update_auto_button_style()
        self._stocks_update_mfi_button_style()
        self.set_status_text(self.stocks_status_label, self.stocks_status_label.text(), status=self.stocks_status_label.property('bt_status') or 'muted')
        self.stocks_news_empty.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.stocks_institutional_empty.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.stocks_insider_empty.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        self.stocks_description_output.setStyleSheet(
            f'background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; padding: 8px;'
        )
        for label in self._stocks_metric_name_labels:
            label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 12px;')
        for label in self._stocks_metric_value_labels:
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px;')
        for line in self._stocks_metric_row_lines:
            line.setStyleSheet(f'background-color: {self.theme_color("panel_border")}; border: 0;')
        for label in self._stocks_target_name_labels:
            label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 12px;')
        for label in self._stocks_target_value_labels:
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px;')
        self.stocks_insider_table.setStyleSheet(
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        self.stocks_institutional_table.setStyleSheet(
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        self.stocks_news_table.setStyleSheet(
            f'QTableWidget {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_primary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; }} '
            f'QHeaderView::section {{ background-color: {self.theme_color("panel_background")}; color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; padding: 4px; }}'
        )
        self._stocks_render_mfi_panel()
        if self._stocks_chart_rows:
            self._stocks_update_quote_header(self._stocks_chart_stats)
