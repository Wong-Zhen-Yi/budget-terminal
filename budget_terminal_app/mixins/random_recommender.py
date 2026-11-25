from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.workers.random_recommender import RandomStockWorker


P18_METRICS = (
    ('Market cap', 'market_cap'),
    ('Revenue', 'revenue'),
    ('Profit margin', 'profit_margin'),
    ('Trailing P/E', 'trailing_pe'),
    ('Forward P/E', 'forward_pe'),
    ('Price/Sales', 'price_sales'),
    ('Beta', 'beta'),
    ('Dividend yield', 'dividend_yield'),
    ('52-week range', 'fifty_two_week_range'),
    ('Avg volume', 'average_volume'),
    ('Mean target', 'mean_target'),
    ('Target upside', 'target_upside'),
)
P18_HISTORY_LIMIT = 20


class RandomRecommenderMixin:

    def init_page18(self) -> None:
        self._p18_request_seq = 0
        self._p18_active_request = 0
        self._p18_loaded_payload = None
        self._p18_metric_labels = {}
        self._p18_metric_name_labels = []
        self._p18_metric_value_labels = []
        self._p18_panel_widgets = []
        self._p18_company_website_url = ''
        self._p18_ir_url = ''
        self._p18_roll_history = []
        self._p18_chart_line = None
        self._p18_badge_labels = []

        layout = QVBoxLayout(self.page18)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        top_frame = QFrame()
        self.set_theme_role(top_frame, 'panel')
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_layout.setSpacing(10)
        title_col = QVBoxLayout()
        self.p18_title_label = QLabel('Random Research Roll')
        self.set_theme_role(self.p18_title_label, 'page_title')
        self.p18_subtitle_label = QLabel('Ready to roll a liquid US stock from yfinance.')
        self.set_theme_role(self.p18_subtitle_label, 'muted')
        title_col.addWidget(self.p18_title_label)
        title_col.addWidget(self.p18_subtitle_label)
        top_layout.addLayout(title_col, 1)
        self.p18_roll_btn = QPushButton('Roll')
        self.p18_roll_btn.setMinimumHeight(36)
        self.p18_roll_btn.setMinimumWidth(130)
        self.set_theme_variant(self.p18_roll_btn, 'accent')
        self.p18_roll_btn.clicked.connect(self._p18_roll_stock)
        top_layout.addWidget(self.p18_roll_btn)
        self.p18_status_label = QLabel('Ready')
        self.set_theme_role(self.p18_status_label, 'status_muted')
        top_layout.addWidget(self.p18_status_label)
        layout.addWidget(top_frame)
        self._p18_panel_widgets.append(top_frame)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)
        layout.addWidget(body_splitter, 1)

        left_panel = QFrame()
        self.set_theme_role(left_panel, 'panel')
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(12)
        self.p18_symbol_label = QLabel('--')
        self.p18_symbol_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.p18_company_label = QLabel('Roll to reveal a research candidate.')
        self.p18_company_label.setWordWrap(True)
        self.p18_meta_label = QLabel('')
        self.p18_meta_label.setWordWrap(True)
        self.p18_price_label = QLabel('--')
        self.p18_change_label = QLabel('--')
        left_layout.addWidget(self.p18_symbol_label)
        left_layout.addWidget(self.p18_company_label)
        left_layout.addWidget(self.p18_meta_label)
        price_row = QHBoxLayout()
        price_row.addWidget(self.p18_price_label)
        price_row.addWidget(self.p18_change_label)
        price_row.addStretch()
        left_layout.addLayout(price_row)

        why_box = QGroupBox('Why This Rolled')
        self.set_theme_role(why_box, 'panel')
        why_layout = QVBoxLayout(why_box)
        why_layout.setContentsMargins(10, 14, 10, 10)
        why_layout.setSpacing(8)
        self.p18_why_summary = QLabel('Rolls use liquid US equities from yfinance.')
        self.p18_why_summary.setWordWrap(True)
        self.set_theme_role(self.p18_why_summary, 'muted')
        why_layout.addWidget(self.p18_why_summary)
        badge_grid = QGridLayout()
        badge_grid.setHorizontalSpacing(6)
        badge_grid.setVerticalSpacing(6)
        for index in range(6):
            badge = QLabel('--')
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setMinimumHeight(24)
            badge.setWordWrap(True)
            self._p18_badge_labels.append(badge)
            badge_grid.addWidget(badge, index // 2, index % 2)
        why_layout.addLayout(badge_grid)
        left_layout.addWidget(why_box)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(14)
        metrics_grid.setVerticalSpacing(8)
        for index, (label_text, key) in enumerate(P18_METRICS):
            name_label = QLabel(label_text)
            value_label = QLabel('N/A')
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            name_label.setMinimumHeight(20)
            value_label.setMinimumHeight(20)
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._p18_metric_name_labels.append(name_label)
            self._p18_metric_value_labels.append(value_label)
            self._p18_metric_labels[key] = value_label
            metrics_grid.addWidget(name_label, index, 0)
            metrics_grid.addWidget(value_label, index, 1)
        metrics_grid.setColumnStretch(1, 1)
        left_layout.addLayout(metrics_grid)

        action_box = QGroupBox('Research Actions')
        self.set_theme_role(action_box, 'panel')
        action_layout = QGridLayout(action_box)
        action_layout.setContentsMargins(10, 14, 10, 10)
        action_layout.setHorizontalSpacing(8)
        action_layout.setVerticalSpacing(8)
        self.p18_website_btn = QPushButton('Website')
        self.p18_ir_btn = QPushButton('Investor Relations')
        self.p18_stocks_btn = QPushButton('Load in Stocks')
        self.p18_charts_btn = QPushButton('Load in Charts')
        self.p18_fundamentals_btn = QPushButton('Load in Fundamentals')
        self.p18_options_btn = QPushButton('Load in Options')
        self.p18_save_btn = QPushButton('Save to Charts')
        for button in (
            self.p18_website_btn,
            self.p18_ir_btn,
            self.p18_stocks_btn,
            self.p18_charts_btn,
            self.p18_fundamentals_btn,
            self.p18_options_btn,
            self.p18_save_btn,
        ):
            button.setEnabled(False)
        self.p18_website_btn.clicked.connect(self._p18_open_website)
        self.p18_ir_btn.clicked.connect(self._p18_open_ir)
        self.p18_stocks_btn.clicked.connect(self._p18_load_in_stocks)
        self.p18_charts_btn.clicked.connect(self._p18_load_in_charts)
        self.p18_fundamentals_btn.clicked.connect(self._p18_load_in_fundamentals)
        self.p18_options_btn.clicked.connect(self._p18_load_in_options)
        self.p18_save_btn.clicked.connect(self._p18_save_to_charts_watchlist)
        action_layout.addWidget(self.p18_website_btn, 0, 0)
        action_layout.addWidget(self.p18_ir_btn, 0, 1)
        action_layout.addWidget(self.p18_stocks_btn, 1, 0)
        action_layout.addWidget(self.p18_charts_btn, 1, 1)
        action_layout.addWidget(self.p18_fundamentals_btn, 2, 0)
        action_layout.addWidget(self.p18_options_btn, 2, 1)
        action_layout.addWidget(self.p18_save_btn, 3, 0, 1, 2)
        left_layout.addWidget(action_box)
        left_layout.addStretch(1)
        body_splitter.addWidget(left_panel)
        self._p18_panel_widgets.extend([left_panel, why_box, action_box])

        research_splitter = QSplitter(Qt.Orientation.Horizontal)
        research_splitter.setChildrenCollapsible(False)
        left_research_panel = QSplitter(Qt.Orientation.Vertical)
        left_research_panel.setChildrenCollapsible(False)
        right_research_panel = QSplitter(Qt.Orientation.Vertical)
        right_research_panel.setChildrenCollapsible(False)

        chart_frame = QFrame()
        self.set_theme_role(chart_frame, 'panel')
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(14, 12, 14, 12)
        chart_layout.setSpacing(8)
        chart_title_row = QHBoxLayout()
        chart_title = QLabel('1Y Price Snapshot')
        self.set_theme_role(chart_title, 'section_title')
        self.p18_chart_status = QLabel('Roll a stock to load chart history.')
        self.set_theme_role(self.p18_chart_status, 'muted')
        chart_title_row.addWidget(chart_title)
        chart_title_row.addStretch()
        chart_title_row.addWidget(self.p18_chart_status)
        chart_layout.addLayout(chart_title_row)
        self.p18_chart_axis = DateAxisItem(orientation='bottom')
        self.p18_chart_plot = pg.PlotWidget(axisItems={'bottom': self.p18_chart_axis})
        self.p18_chart_plot.getPlotItem().hideButtons()
        self.p18_chart_plot.getPlotItem().setMenuEnabled(False)
        self.p18_chart_plot.getPlotItem().hideAxis('left')
        self.p18_chart_plot.getPlotItem().showAxis('right')
        self.p18_chart_plot.setMouseEnabled(x=False, y=False)
        self.p18_chart_plot.setMinimumHeight(170)
        chart_layout.addWidget(self.p18_chart_plot, 1)

        options_frame = QFrame()
        self.set_theme_role(options_frame, 'panel')
        options_layout = QVBoxLayout(options_frame)
        options_layout.setContentsMargins(14, 12, 14, 12)
        options_layout.setSpacing(8)
        options_title = QLabel('Top Options By Expiration')
        self.set_theme_role(options_title, 'section_title')
        self.p18_top_options_empty = QLabel('Roll a stock to inspect top-volume contracts by expiration.')
        self.p18_top_options_empty.setWordWrap(True)
        self.set_theme_role(self.p18_top_options_empty, 'muted')
        self.p18_top_options_table = QTableWidget(0, 7)
        self.p18_top_options_table.setHorizontalHeaderLabels(['Exp', 'Type', 'Strike', 'Last', 'Vol', 'OI', 'IV'])
        self.p18_top_options_table.verticalHeader().setVisible(False)
        self.p18_top_options_table.verticalHeader().setDefaultSectionSize(24)
        self.p18_top_options_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p18_top_options_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p18_top_options_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p18_top_options_table.setAlternatingRowColors(True)
        top_options_header = self.p18_top_options_table.horizontalHeader()
        top_options_header.setMinimumHeight(28)
        top_options_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        top_options_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        top_options_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        top_options_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        top_options_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        top_options_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        top_options_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.p18_top_options_table.setVisible(False)
        options_layout.addWidget(options_title)
        options_layout.addWidget(self.p18_top_options_empty)
        options_layout.addWidget(self.p18_top_options_table, 1)

        news_frame = QFrame()
        self.set_theme_role(news_frame, 'panel')
        news_layout = QVBoxLayout(news_frame)
        news_layout.setContentsMargins(14, 12, 14, 12)
        news_layout.setSpacing(8)
        news_title = QLabel('Recent Headlines')
        self.set_theme_role(news_title, 'section_title')
        self.p18_news_empty = QLabel('Roll a stock to inspect recent headlines.')
        self.p18_news_empty.setWordWrap(True)
        self.set_theme_role(self.p18_news_empty, 'muted')
        self.p18_news_table = self._make_news_table(self._open_news_link_table)
        self.p18_news_table.verticalHeader().setDefaultSectionSize(24)
        self.p18_news_table.horizontalHeader().setMinimumHeight(28)
        self.p18_news_table.setAlternatingRowColors(True)
        self.p18_news_table.setVisible(False)
        news_layout.addWidget(news_title)
        news_layout.addWidget(self.p18_news_empty)
        news_layout.addWidget(self.p18_news_table, 1)

        history_frame = QFrame()
        self.set_theme_role(history_frame, 'panel')
        history_layout = QVBoxLayout(history_frame)
        history_layout.setContentsMargins(14, 12, 14, 12)
        history_layout.setSpacing(8)
        history_title = QLabel('Roll History')
        self.set_theme_role(history_title, 'section_title')
        self.p18_history_empty = QLabel('Rolled stocks will appear here for quick revisits.')
        self.p18_history_empty.setWordWrap(True)
        self.set_theme_role(self.p18_history_empty, 'muted')
        self.p18_history_table = QTableWidget(0, 4)
        self.p18_history_table.setHorizontalHeaderLabels(['Ticker', 'Company', 'Sector', 'Rolled'])
        self.p18_history_table.verticalHeader().setVisible(False)
        self.p18_history_table.verticalHeader().setDefaultSectionSize(24)
        self.p18_history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p18_history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p18_history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p18_history_table.setAlternatingRowColors(True)
        history_header = self.p18_history_table.horizontalHeader()
        history_header.setMinimumHeight(28)
        history_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        history_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.p18_history_table.itemDoubleClicked.connect(self._p18_open_history_item)
        self.p18_history_table.setVisible(False)
        history_layout.addWidget(history_title)
        history_layout.addWidget(self.p18_history_empty)
        history_layout.addWidget(self.p18_history_table, 1)

        left_research_panel.addWidget(chart_frame)
        left_research_panel.addWidget(options_frame)
        left_research_panel.setStretchFactor(0, 2)
        left_research_panel.setStretchFactor(1, 3)

        right_research_panel.addWidget(news_frame)
        right_research_panel.addWidget(history_frame)
        right_research_panel.setStretchFactor(0, 3)
        right_research_panel.setStretchFactor(1, 2)

        research_splitter.addWidget(left_research_panel)
        research_splitter.addWidget(right_research_panel)
        research_splitter.setStretchFactor(0, 3)
        research_splitter.setStretchFactor(1, 2)

        body_splitter.addWidget(research_splitter)
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 5)
        self._p18_panel_widgets.extend([chart_frame, options_frame, news_frame, history_frame])
        self._apply_random_recommender_theme()

    def _p18_set_status(self, text: Any, status: str='muted', *, include_global: bool=True) -> None:
        self.set_status_text(self.p18_status_label, text, status=status)
        if include_global and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=status)

    def _p18_roll_stock(self, *_: Any, include_global_status: bool=True) -> None:
        self._p18_request_seq += 1
        request_id = self._p18_request_seq
        self._p18_active_request = request_id
        self.p18_roll_btn.setEnabled(False)
        self._p18_set_status('Rolling...', 'info', include_global=include_global_status)
        self.p18_worker = RandomStockWorker()
        self.p18_thread = QThread()
        self.p18_worker.moveToThread(self.p18_thread)
        self.p18_thread.started.connect(self.p18_worker.run)
        self.p18_worker.finished.connect(lambda payload, req=request_id: self._p18_handle_result(req, payload))
        self.p18_worker.finished.connect(self.p18_thread.quit)
        self.p18_worker.error.connect(lambda message, req=request_id: self._p18_handle_error(req, message))
        self.p18_worker.error.connect(self.p18_thread.quit)
        self.p18_thread.start()

    def _p18_handle_result(self, request_id: int, payload: dict[str, Any]) -> None:
        if request_id != getattr(self, '_p18_active_request', 0):
            return
        self.p18_roll_btn.setEnabled(True)
        self._p18_apply_payload(payload)
        symbol = self._p18_current_symbol()
        total = payload.get('universe_total')
        suffix = f' from {int(total):,} screened candidates' if isinstance(total, int) and total > 0 else ''
        self._p18_set_status(f'Rolled {symbol}{suffix}.', 'positive')

    def _p18_handle_error(self, request_id: int, message: Any) -> None:
        if request_id != getattr(self, '_p18_active_request', 0):
            return
        self.p18_roll_btn.setEnabled(True)
        self._p18_set_status(str(message or 'Random roll failed.'), 'negative')

    def _p18_session_snapshot(self) -> dict[str, Any] | None:
        payload = getattr(self, '_p18_loaded_payload', None)
        if not isinstance(payload, dict):
            return None
        symbol = str(payload.get('symbol', '') or '').upper().strip()
        if not symbol:
            return None
        return {
            'symbol': symbol,
            'payload': serialize_session_value(payload),
            'history': serialize_session_value(list(getattr(self, '_p18_roll_history', []))),
        }

    def _p18_save_session_snapshot(self, *, immediate: bool=False) -> None:
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('roll', self._p18_session_snapshot(), immediate=immediate)

    def _p18_restore_session_snapshot(self, snapshot: Any) -> bool:
        payload = snapshot if isinstance(snapshot, dict) else {}
        restored_payload = deserialize_session_value(payload.get('payload'))
        if not isinstance(restored_payload, dict):
            return False
        history = deserialize_session_value(payload.get('history'))
        self._p18_roll_history = [dict(item) for item in list(history or []) if isinstance(item, dict)][:P18_HISTORY_LIMIT]
        self._p18_apply_payload(restored_payload, save_snapshot=False)
        self._p18_render_history()
        self._p18_set_status(f"Restored last roll for {str(restored_payload.get('symbol', '') or '').upper().strip()}.", 'positive', include_global=False)
        return True

    def _p18_restore_startup_session(self, snapshot: Any) -> None:
        self._p18_restore_session_snapshot(snapshot)

    def _p18_apply_payload(self, payload: dict[str, Any], *, save_snapshot: bool=True) -> None:
        self._p18_loaded_payload = payload
        symbol = str(payload.get('symbol', '') or '').upper().strip()
        info = payload.get('info', {}) if isinstance(payload.get('info', {}), dict) else {}
        quote = payload.get('quote', {}) if isinstance(payload.get('quote', {}), dict) else {}
        name = self._p18_info_value(info, 'longName', 'shortName') or quote.get('longName') or quote.get('shortName') or symbol or 'N/A'
        exchange = self._p18_info_value(info, 'exchange', 'fullExchangeName') or quote.get('fullExchangeName') or quote.get('exchange') or 'N/A'
        sector = self._p18_info_value(info, 'sector') or 'N/A'
        industry = self._p18_info_value(info, 'industry') or 'N/A'
        currency = self._p18_info_value(info, 'currency', 'financialCurrency') or quote.get('currency') or 'USD'
        price = self._p18_info_value(info, 'regularMarketPrice', 'currentPrice') or quote.get('regularMarketPrice')
        previous_close = self._p18_info_value(info, 'previousClose', 'regularMarketPreviousClose') or quote.get('regularMarketPreviousClose')
        change = quote.get('regularMarketChange')
        change_pct = quote.get('regularMarketChangePercent')
        if change in (None, '', 'N/A') and price not in (None, '', 'N/A') and previous_close not in (None, '', 'N/A'):
            try:
                change = float(price) - float(previous_close)
                change_pct = change / float(previous_close) * 100.0 if float(previous_close) else None
            except Exception:
                change = None
                change_pct = None

        self.p18_symbol_label.setText(symbol or '--')
        self.p18_company_label.setText(str(name))
        self.p18_meta_label.setText(f'{exchange}  |  {sector}  |  {industry}  |  {currency}')
        self.p18_price_label.setText(self._p18_format_currency(price))
        self._p18_set_change_label(change, change_pct)
        self._p18_company_website_url = str(payload.get('website') or info.get('website') or '').strip()
        self._p18_ir_url = str(payload.get('ir_url') or info.get('irWebsite') or '').strip()
        if not self._p18_ir_url and symbol:
            self._p18_ir_url = f'https://www.google.com/search?q={symbol}+investor+relations'
        self._p18_update_metrics(info, quote, price)
        self._p18_update_why_panel(payload, info, quote)
        self._p18_render_chart(payload.get('chart_history') or {})
        self._p18_render_top_options(payload.get('top_options') or [], payload.get('top_options_status') or '')
        self._p18_render_news(payload.get('news') or [])
        self._p18_update_action_buttons()
        if save_snapshot:
            self._p18_record_history(payload)
            self._p18_save_session_snapshot()

    def _p18_update_metrics(self, info: dict[str, Any], quote: dict[str, Any], price: Any) -> None:
        market_cap = self._p18_info_value(info, 'marketCap') or quote.get('marketCap')
        revenue = self._p18_info_value(info, 'totalRevenue')
        profit_margin = self._p18_info_value(info, 'profitMargins', 'netMargins')
        target = self._p18_info_value(info, 'targetMeanPrice') or quote.get('targetMeanPrice')
        values = {
            'market_cap': self._p18_format_compact(market_cap, currency=True),
            'revenue': self._p18_format_compact(revenue, currency=True),
            'profit_margin': self._p18_format_percent(profit_margin),
            'trailing_pe': self._p18_format_ratio(self._p18_info_value(info, 'trailingPE') or quote.get('trailingPE')),
            'forward_pe': self._p18_format_ratio(self._p18_info_value(info, 'forwardPE') or quote.get('forwardPE')),
            'price_sales': self._p18_format_ratio(self._p18_info_value(info, 'priceToSalesTrailing12Months')),
            'beta': self._p18_format_decimal(self._p18_info_value(info, 'beta') or quote.get('beta')),
            'dividend_yield': self._p18_format_dividend_yield(self._p18_info_value(info, 'dividendYield', 'trailingAnnualDividendYield') or quote.get('dividendYield')),
            'fifty_two_week_range': self._p18_format_range(
                self._p18_info_value(info, 'fiftyTwoWeekLow') or quote.get('fiftyTwoWeekLow'),
                self._p18_info_value(info, 'fiftyTwoWeekHigh') or quote.get('fiftyTwoWeekHigh'),
            ),
            'average_volume': self._p18_format_integer(self._p18_info_value(info, 'averageVolume', 'averageDailyVolume3Month') or quote.get('averageDailyVolume3Month')),
            'mean_target': self._p18_format_currency(target),
            'target_upside': self._p18_target_upside(price, target),
        }
        for _label, key in P18_METRICS:
            self._p18_metric_labels[key].setText(str(values.get(key, 'N/A')))

    def _p18_update_why_panel(self, payload: dict[str, Any], info: dict[str, Any], quote: dict[str, Any]) -> None:
        total = payload.get('universe_total')
        total_text = f'{int(total):,}' if isinstance(total, int) and total > 0 else 'liquid'
        self.p18_why_summary.setText(
            f'Picked at random from {total_text} yfinance-screened US equities with market cap above $1B and 3-month average volume above 1M.'
        )
        market_cap = self._p18_info_value(info, 'marketCap') or quote.get('marketCap')
        avg_volume = self._p18_info_value(info, 'averageVolume', 'averageDailyVolume3Month') or quote.get('averageDailyVolume3Month')
        sector = self._p18_info_value(info, 'sector') or 'Sector N/A'
        exchange = self._p18_info_value(info, 'exchange', 'fullExchangeName') or quote.get('fullExchangeName') or quote.get('exchange') or 'Exchange N/A'
        badges = [
            'Liquid US equity',
            f'{self._p18_market_cap_tier(market_cap)} cap',
            f'Vol {self._p18_format_integer(avg_volume)}',
            str(sector),
            str(exchange),
            self._p18_valuation_badge(self._p18_info_value(info, 'trailingPE') or quote.get('trailingPE')),
        ]
        for index, label in enumerate(self._p18_badge_labels):
            label.setText(badges[index] if index < len(badges) else '--')

    def _p18_render_chart(self, history: Any) -> None:
        chart_history = history if isinstance(history, dict) else {}
        dates = list(chart_history.get('dates', []) or [])
        closes = list(chart_history.get('closes', []) or [])
        points = []
        clean_dates = []
        for date_value, close_value in zip(dates, closes):
            try:
                numeric = float(close_value)
            except Exception:
                continue
            if not math.isfinite(numeric):
                continue
            clean_dates.append(date_value)
            points.append(numeric)
        self.p18_chart_plot.clear()
        self._p18_chart_line = None
        if len(points) < 2:
            self.p18_chart_axis.set_dates([], '1d')
            self.p18_chart_status.setText('No chart history available.')
            return
        x_values = list(range(len(points)))
        color = self.theme_color('accent_positive' if points[-1] >= points[0] else 'accent_negative')
        self._p18_chart_line = self.p18_chart_plot.plot(x_values, points, pen=pg.mkPen(color=color, width=2.0), antialias=True)
        self.p18_chart_axis.set_dates(clean_dates, '1d')
        low_value = min(points)
        high_value = max(points)
        span = max(high_value - low_value, abs(high_value) * 0.02, 1.0)
        self.p18_chart_plot.setXRange(0, len(points) - 1, padding=0.02)
        self.p18_chart_plot.setYRange(low_value - span * 0.08, high_value + span * 0.08, padding=0)
        change_pct = ((points[-1] - points[0]) / points[0]) * 100.0 if points[0] else 0.0
        sign = '+' if change_pct >= 0 else ''
        self.p18_chart_status.setText(f'1Y {sign}{change_pct:.1f}%')

    def _p18_render_top_options(self, records: Any, status_text: str='') -> None:
        clean_records = [dict(record) for record in list(records or []) if isinstance(record, dict)]
        if not clean_records:
            self.p18_top_options_table.setRowCount(0)
            self.p18_top_options_table.setVisible(False)
            self.p18_top_options_empty.setVisible(True)
            self.p18_top_options_empty.setText(status_text or 'No options expirations were available for this ticker.')
            return
        self.p18_top_options_table.setRowCount(len(clean_records))
        for row_index, record in enumerate(clean_records):
            values = (
                str(record.get('expiration', '') or 'N/A'),
                str(record.get('type', '') or 'N/A'),
                self._p18_format_option_number(record.get('strike'), decimals=2),
                self._p18_format_option_number(record.get('lastPrice'), decimals=2),
                self._p18_format_integer(record.get('volume')),
                self._p18_format_integer(record.get('openInterest')),
                self._p18_format_iv(record.get('impliedVolatility')),
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 1:
                    option_type = value.casefold()
                    if option_type == 'call':
                        item.setForeground(self.theme_qcolor('accent_positive'))
                    elif option_type == 'put':
                        item.setForeground(self.theme_qcolor('accent_negative'))
                if col_index in (0, 1):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.p18_top_options_table.setItem(row_index, col_index, item)
        self.p18_top_options_empty.setVisible(False)
        self.p18_top_options_table.setVisible(True)

    def _p18_record_history(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get('symbol', '') or '').upper().strip()
        if not symbol:
            return
        history = [dict(item) for item in getattr(self, '_p18_roll_history', []) if isinstance(item, dict)]
        history = [item for item in history if str(item.get('symbol', '') or '').upper().strip() != symbol]
        info = payload.get('info', {}) if isinstance(payload.get('info', {}), dict) else {}
        history.insert(0, {
            'symbol': symbol,
            'company': self._p18_info_value(info, 'longName', 'shortName') or symbol,
            'sector': self._p18_info_value(info, 'sector') or 'N/A',
            'rolled_at': datetime.datetime.now().strftime('%H:%M'),
            'payload': payload,
        })
        self._p18_roll_history = history[:P18_HISTORY_LIMIT]
        self._p18_render_history()

    def _p18_render_history(self) -> None:
        history = [dict(item) for item in getattr(self, '_p18_roll_history', []) if isinstance(item, dict)]
        if not history:
            self.p18_history_table.setRowCount(0)
            self.p18_history_table.setVisible(False)
            self.p18_history_empty.setVisible(True)
            return
        self.p18_history_table.setRowCount(len(history))
        for row_index, item in enumerate(history):
            payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
            values = (
                str(item.get('symbol', '') or '').upper(),
                str(item.get('company', '') or 'N/A'),
                str(item.get('sector', '') or 'N/A'),
                str(item.get('rolled_at', '') or ''),
            )
            for col_index, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if col_index == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, payload)
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col_index == 3:
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.p18_history_table.setItem(row_index, col_index, table_item)
        self.p18_history_empty.setVisible(False)
        self.p18_history_table.setVisible(True)

    def _p18_open_history_item(self, item: Any) -> None:
        row = item.row() if hasattr(item, 'row') else -1
        if row < 0:
            return
        ticker_item = self.p18_history_table.item(row, 0)
        payload = ticker_item.data(Qt.ItemDataRole.UserRole) if ticker_item is not None else None
        if isinstance(payload, dict):
            self._p18_apply_payload(payload, save_snapshot=False)
            self._p18_set_status(f"Revisited {str(payload.get('symbol', '') or '').upper().strip()} from roll history.", 'positive')
            self._p18_save_session_snapshot()

    def _p18_render_news(self, articles: Any) -> None:
        clean_articles = [dict(article) for article in list(articles or []) if isinstance(article, dict)]
        if not clean_articles:
            self.p18_news_table.setRowCount(0)
            self.p18_news_table.setVisible(False)
            self.p18_news_empty.setVisible(True)
            self.p18_news_empty.setText('No recent headlines were available for this ticker.')
            return
        self._populate_news_table(self.p18_news_table, clean_articles)
        self.p18_news_empty.setVisible(False)
        self.p18_news_table.setVisible(True)

    def _p18_update_action_buttons(self) -> None:
        has_symbol = bool(self._p18_current_symbol())
        self.p18_website_btn.setEnabled(bool(self._p18_company_website_url))
        self.p18_ir_btn.setEnabled(bool(self._p18_ir_url))
        for button in (self.p18_stocks_btn, self.p18_charts_btn, self.p18_fundamentals_btn, self.p18_options_btn, self.p18_save_btn):
            button.setEnabled(has_symbol)

    def _p18_current_symbol(self) -> str:
        payload = getattr(self, '_p18_loaded_payload', None)
        if isinstance(payload, dict):
            return str(payload.get('symbol', '') or '').upper().strip()
        return ''

    def _p18_page_index(self, page_name: str, fallback_index: int) -> int:
        page = getattr(self, page_name, None)
        if page is not None and hasattr(self, 'stacked_widget'):
            try:
                page_index = self.stacked_widget.indexOf(page)
            except Exception:
                page_index = -1
            if page_index >= 0:
                return page_index
        return fallback_index

    def _p18_open_website(self) -> None:
        if self._p18_company_website_url:
            webbrowser.open(self._p18_company_website_url)

    def _p18_open_ir(self) -> None:
        if self._p18_ir_url:
            webbrowser.open(self._p18_ir_url)

    def _p18_load_in_stocks(self) -> None:
        symbol = self._p18_current_symbol()
        if not symbol:
            return
        page_index = self._p18_page_index('page12', 7)
        self.switch_page(page_index)
        if hasattr(self, 'stocks_symbol_input'):
            self.stocks_symbol_input.setText(symbol)
        if hasattr(self, '_stocks_load_from_input'):
            self._stocks_load_from_input()

    def _p18_load_in_charts(self) -> None:
        symbol = self._p18_current_symbol()
        if not symbol:
            return
        self.p10_symbol = symbol
        if isinstance(getattr(self, 'chart_page_state', None), dict):
            self.chart_page_state = {**self.chart_page_state, 'symbol': symbol}
        page_index = self._p18_page_index('page10', 9)
        self.switch_page(page_index)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(symbol)
        if hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()

    def _p18_load_in_fundamentals(self) -> None:
        symbol = self._p18_current_symbol()
        if not symbol:
            return
        self.switch_page(self._p18_page_index('page2', 8))
        if hasattr(self, 'p2_ticker_input'):
            self.p2_ticker_input.setText(symbol)
        if hasattr(self, 'analyze_stock_p2'):
            self.analyze_stock_p2()

    def _p18_load_in_options(self) -> None:
        symbol = self._p18_current_symbol()
        if not symbol:
            return
        self.switch_page(self._p18_page_index('page5', 11))
        if hasattr(self, 'p5_shared_ticker_input'):
            self.p5_shared_ticker_input.setText(symbol)
        if hasattr(self, '_p5_load_expiries'):
            self._p5_load_expiries()

    def _p18_save_to_charts_watchlist(self) -> None:
        symbol = self._p18_current_symbol()
        if not symbol:
            return
        state = dict(getattr(self, 'chart_page_state', load_chart_page_settings()) or {})
        watchlist = [str(item or '').upper().strip() for item in list(state.get('watchlist', []) or [])]
        watchlist = [item for item in watchlist if item]
        if symbol in watchlist:
            self._p18_set_status(f'{symbol} is already in the Charts watchlist.', 'warning')
            return
        watchlist.append(symbol)
        watchlist = sorted(dict.fromkeys(watchlist))
        state['watchlist'] = watchlist
        self.chart_page_state = save_chart_page_settings(state)
        self.p10_custom_watchlist = list(self.chart_page_state.get('watchlist', watchlist))
        if hasattr(self, '_p10_rebuild_watchlists') and self._page_initialized(page_attr='page10'):
            self._p10_rebuild_watchlists()
        self._p18_set_status(f'Saved {symbol} to the Charts watchlist.', 'positive')

    def _p18_info_value(self, info: dict[str, Any], *keys: str) -> Any:
        if not isinstance(info, dict):
            return None
        for key in keys:
            value = info.get(key)
            if value not in (None, '', 'N/A'):
                return value
        return None

    def _p18_format_compact(self, value: Any, *, currency: bool=False) -> str:
        try:
            text = fmt_num(float(value))
        except Exception:
            return 'N/A'
        return f'${text}' if currency else text

    def _p18_format_currency(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        return f'${fmt_num(numeric)}' if abs(numeric) >= 1000 else f'${numeric:,.2f}'

    def _p18_format_ratio(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        return f'{numeric:.2f}x' if math.isfinite(numeric) else 'N/A'

    def _p18_format_decimal(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        return f'{numeric:.2f}' if math.isfinite(numeric) else 'N/A'

    def _p18_format_percent(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        return f'{numeric * 100.0:.2f}%'

    def _p18_format_dividend_yield(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        if numeric > 1.0:
            return f'{numeric:.2f}%'
        return f'{numeric * 100.0:.2f}%'

    def _p18_format_range(self, low: Any, high: Any) -> str:
        low_text = self._p18_format_currency(low)
        high_text = self._p18_format_currency(high)
        if low_text == 'N/A' and high_text == 'N/A':
            return 'N/A'
        return f'{low_text} - {high_text}'

    def _p18_format_integer(self, value: Any) -> str:
        try:
            return f'{int(float(value)):,}'
        except Exception:
            return 'N/A'

    def _p18_format_option_number(self, value: Any, *, decimals: int=2) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        return f'{numeric:,.{int(decimals)}f}'

    def _p18_format_iv(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        return f'{numeric * 100.0:.1f}%'

    def _p18_market_cap_tier(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'Unknown'
        if numeric >= 200_000_000_000:
            return 'Mega'
        if numeric >= 10_000_000_000:
            return 'Large'
        if numeric >= 2_000_000_000:
            return 'Mid'
        return 'Small'

    def _p18_valuation_badge(self, pe_value: Any) -> str:
        try:
            numeric = float(pe_value)
        except Exception:
            return 'P/E N/A'
        if not math.isfinite(numeric) or numeric <= 0:
            return 'P/E N/A'
        if numeric < 15:
            return 'Lower P/E'
        if numeric <= 30:
            return 'Mid P/E'
        return 'High P/E'

    def _p18_target_upside(self, price: Any, target: Any) -> str:
        try:
            price_value = float(price)
            target_value = float(target)
        except Exception:
            return 'N/A'
        if not math.isfinite(price_value) or not math.isfinite(target_value) or price_value == 0:
            return 'N/A'
        return f'{((target_value - price_value) / price_value) * 100.0:.2f}%'

    def _p18_set_change_label(self, change: Any, change_pct: Any) -> None:
        try:
            change_value = float(change)
            pct_value = float(change_pct)
        except Exception:
            self.p18_change_label.setText('--')
            self.p18_change_label.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {self.theme_color("text_muted")};')
            return
        sign = '+' if change_value >= 0 else ''
        self.p18_change_label.setText(f'{sign}${change_value:,.2f} ({sign}{pct_value:.2f}%)')
        color = self.theme_color('accent_positive' if change_value >= 0 else 'accent_negative')
        self.p18_change_label.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {color};')

    def _apply_random_recommender_theme(self) -> None:
        if not hasattr(self, 'p18_roll_btn'):
            return
        for widget in getattr(self, '_p18_panel_widgets', []):
            self.set_theme_role(widget, 'panel')
        self.set_theme_variant(self.p18_roll_btn, 'accent')
        self.set_theme_variant(self.p18_save_btn, 'positive')
        self.set_status_text(self.p18_status_label, self.p18_status_label.text(), status=self.p18_status_label.property('bt_status') or 'muted')
        self.set_theme_role(self.p18_title_label, 'page_title')
        self.set_theme_role(self.p18_subtitle_label, 'muted')
        self.set_theme_role(self.p18_why_summary, 'muted')
        self.set_theme_role(self.p18_chart_status, 'muted')
        self.set_theme_role(self.p18_top_options_empty, 'muted')
        self.set_theme_role(self.p18_news_empty, 'muted')
        self.set_theme_role(self.p18_history_empty, 'muted')
        self.style_plot_widget(self.p18_chart_plot)
        self.p18_symbol_label.setStyleSheet(f'font-size: 32px; font-weight: bold; color: {self.theme_color("accent")};')
        self.p18_company_label.setStyleSheet(f'font-size: 16px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p18_meta_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        self.p18_price_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
        for label in self._p18_badge_labels:
            label.setStyleSheet(
                f'background: {self.theme_color("accent_soft")}; color: {self.theme_color("text_primary")}; '
                f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 4px; padding: 2px 5px; font-size: 11px;'
            )
        for label in self._p18_metric_name_labels:
            label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_muted")}; padding-bottom: 1px;')
        for label in self._p18_metric_value_labels:
            label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_primary")}; font-weight: bold; padding-bottom: 1px;')
        self.p18_news_table.setStyleSheet(
            f'QTableWidget {{ background: {self.theme_color("table_row_bg")}; color: {self.theme_color("text_primary")}; '
            f'gridline-color: {self.theme_color("panel_border")}; }}'
            f'QHeaderView::section {{ background: {self.theme_color("table_header_bg")}; color: {self.theme_color("text_primary")}; }}'
        )
        self.p18_top_options_table.setStyleSheet(
            f'QTableWidget {{ background: {self.theme_color("table_row_bg")}; color: {self.theme_color("text_primary")}; '
            f'gridline-color: {self.theme_color("panel_border")}; }}'
            f'QHeaderView::section {{ background: {self.theme_color("table_header_bg")}; color: {self.theme_color("text_primary")}; }}'
        )
        self.p18_history_table.setStyleSheet(
            f'QTableWidget {{ background: {self.theme_color("table_row_bg")}; color: {self.theme_color("text_primary")}; '
            f'gridline-color: {self.theme_color("panel_border")}; }}'
            f'QHeaderView::section {{ background: {self.theme_color("table_header_bg")}; color: {self.theme_color("text_primary")}; }}'
        )
        payload = getattr(self, '_p18_loaded_payload', None)
        if isinstance(payload, dict):
            self._p18_render_chart(payload.get('chart_history') or {})
            self._p18_render_top_options(payload.get('top_options') or [], payload.get('top_options_status') or '')
        if self.p18_change_label.text() not in ('', '--'):
            if isinstance(payload, dict):
                info = payload.get('info', {}) if isinstance(payload.get('info', {}), dict) else {}
                quote = payload.get('quote', {}) if isinstance(payload.get('quote', {}), dict) else {}
                price = self._p18_info_value(info, 'regularMarketPrice', 'currentPrice') or quote.get('regularMarketPrice')
                previous_close = self._p18_info_value(info, 'previousClose', 'regularMarketPreviousClose') or quote.get('regularMarketPreviousClose')
                change = quote.get('regularMarketChange')
                change_pct = quote.get('regularMarketChangePercent')
                if change in (None, '', 'N/A') and price not in (None, '', 'N/A') and previous_close not in (None, '', 'N/A'):
                    try:
                        change = float(price) - float(previous_close)
                        change_pct = change / float(previous_close) * 100.0 if float(previous_close) else None
                    except Exception:
                        pass
                self._p18_set_change_label(change, change_pct)
