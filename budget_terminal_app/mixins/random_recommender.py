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
P18_WHY_METRICS = (
    ('Rank', 'rank'),
    ('Score', 'score'),
    ('Setup', 'setup'),
    ('Pattern', 'pattern'),
    ('Resistance', 'resistance'),
    ('MA stack', 'ma_stack'),
    ('RSI', 'rsi'),
    ('MACD', 'macd'),
    ('Volume', 'volume'),
    ('Timeframes', 'timeframes'),
)


class RandomRecommenderMixin:

    def init_page18(self) -> None:
        self._p18_request_seq = 0
        self._p18_active_request = 0
        self._p18_loaded_payload = None
        self._p18_metric_labels = {}
        self._p18_metric_name_labels = []
        self._p18_metric_value_labels = []
        self._p18_why_metric_labels = {}
        self._p18_why_metric_name_labels = []
        self._p18_why_metric_value_labels = []
        self._p18_panel_widgets = []
        self._p18_company_website_url = ''
        self._p18_ir_url = ''
        self._p18_roll_history = []
        self._p18_candidate_pool = []
        self._p18_chart_line = None
        self._p18_chart_candle_item = None
        self._p18_badge_labels = []

        layout = QVBoxLayout(self.page18)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top_frame = QFrame()
        self.set_theme_role(top_frame, 'panel')
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(6)
        title_col = QVBoxLayout()
        self.p18_title_label = QLabel('Random Research Roll')
        self.set_theme_role(self.p18_title_label, 'page_title')
        self.p18_subtitle_label = QLabel('Ready to roll a liquid US stock from yfinance.')
        self.set_theme_role(self.p18_subtitle_label, 'muted')
        title_col.addWidget(self.p18_title_label)
        title_col.addWidget(self.p18_subtitle_label)
        top_layout.addLayout(title_col)
        self.p18_roll_btn = QPushButton('Roll')
        self.p18_roll_btn.setMinimumHeight(30)
        self.p18_roll_btn.setMinimumWidth(130)
        self.set_theme_variant(self.p18_roll_btn, 'accent')
        self.p18_roll_btn.clicked.connect(self._p18_roll_stock)
        roll_controls_layout = QHBoxLayout()
        roll_controls_layout.setContentsMargins(0, 0, 0, 0)
        roll_controls_layout.setSpacing(6)
        roll_controls_layout.addWidget(self.p18_roll_btn)
        self.p18_breakout_checkbox = QCheckBox('Breakout setup')
        self.p18_consolidation_checkbox = QCheckBox('Consolidation')
        self.p18_downtrend_checkbox = QCheckBox('Downtrend')
        self.p18_double_bottom_checkbox = QCheckBox('Double bottom')
        self.p18_bullish_flag_checkbox = QCheckBox('Bullish flag')
        self.p18_bullish_rsi_divergence_checkbox = QCheckBox('Bullish RSI divergence')
        for checkbox in (
            self.p18_breakout_checkbox,
            self.p18_consolidation_checkbox,
            self.p18_downtrend_checkbox,
            self.p18_double_bottom_checkbox,
            self.p18_bullish_flag_checkbox,
            self.p18_bullish_rsi_divergence_checkbox,
        ):
            checkbox.setToolTip('Filter Roll candidates using daily technical patterns and indicator confirmation.')
            roll_controls_layout.addWidget(checkbox)
        top_layout.addLayout(roll_controls_layout)
        top_layout.addStretch(1)
        self.p18_status_label = QLabel('Ready')
        self.p18_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.p18_status_label.setMinimumWidth(180)
        self.p18_status_label.setMaximumWidth(360)
        self.p18_status_label.setWordWrap(False)
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
        left_layout.setContentsMargins(10, 8, 10, 8)
        left_layout.setSpacing(6)
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
        why_layout.setContentsMargins(8, 10, 8, 8)
        why_layout.setSpacing(5)
        self.p18_why_summary = QLabel('Rolls use liquid US equities from yfinance.')
        self.p18_why_summary.setWordWrap(True)
        self.set_theme_role(self.p18_why_summary, 'muted')
        why_layout.addWidget(self.p18_why_summary)
        why_metric_grid = QGridLayout()
        why_metric_grid.setHorizontalSpacing(10)
        why_metric_grid.setVerticalSpacing(4)
        for index, (label_text, key) in enumerate(P18_WHY_METRICS):
            name_label = QLabel(label_text)
            value_label = QLabel('--')
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            name_label.setMinimumHeight(16)
            value_label.setMinimumHeight(16)
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._p18_why_metric_name_labels.append(name_label)
            self._p18_why_metric_value_labels.append(value_label)
            self._p18_why_metric_labels[key] = value_label
            row = index // 2
            col = (index % 2) * 2
            why_metric_grid.addWidget(name_label, row, col)
            why_metric_grid.addWidget(value_label, row, col + 1)
        why_metric_grid.setColumnStretch(1, 1)
        why_metric_grid.setColumnStretch(3, 1)
        why_layout.addLayout(why_metric_grid)
        badge_grid = QGridLayout()
        badge_grid.setHorizontalSpacing(6)
        badge_grid.setVerticalSpacing(6)
        for index in range(6):
            badge = QLabel('--')
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setMinimumHeight(20)
            badge.setWordWrap(True)
            self._p18_badge_labels.append(badge)
            badge_grid.addWidget(badge, index // 2, index % 2)
        why_layout.addLayout(badge_grid)
        left_layout.addWidget(why_box)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(14)
        metrics_grid.setVerticalSpacing(4)
        for index, (label_text, key) in enumerate(P18_METRICS):
            name_label = QLabel(label_text)
            value_label = QLabel('N/A')
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            name_label.setMinimumHeight(17)
            value_label.setMinimumHeight(17)
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._p18_metric_name_labels.append(name_label)
            self._p18_metric_value_labels.append(value_label)
            self._p18_metric_labels[key] = value_label
            row = index // 2
            col = (index % 2) * 2
            metrics_grid.addWidget(name_label, row, col)
            metrics_grid.addWidget(value_label, row, col + 1)
        metrics_grid.setColumnStretch(1, 1)
        metrics_grid.setColumnStretch(3, 1)
        left_layout.addLayout(metrics_grid)

        action_box = QGroupBox('Research Actions')
        self.set_theme_role(action_box, 'panel')
        action_layout = QGridLayout(action_box)
        action_layout.setContentsMargins(8, 10, 8, 8)
        action_layout.setHorizontalSpacing(8)
        action_layout.setVerticalSpacing(5)
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
        chart_layout.setContentsMargins(10, 8, 10, 8)
        chart_layout.setSpacing(5)
        chart_title_row = QHBoxLayout()
        chart_title = QLabel('1Y Price Snapshot')
        self.set_theme_role(chart_title, 'section_title')
        self.p18_chart_status = QLabel('Roll a stock to load chart history.')
        self.set_theme_role(self.p18_chart_status, 'muted')
        chart_title_row.addWidget(chart_title)
        chart_title_row.addStretch()
        self.p18_chart_indicators_checkbox = QCheckBox('Indicators')
        self.p18_chart_indicators_checkbox.setToolTip('Show candlesticks with daily moving averages, volume, RSI, and MACD.')
        self.p18_chart_indicators_checkbox.toggled.connect(lambda _checked: self._p18_refresh_chart())
        chart_title_row.addWidget(self.p18_chart_indicators_checkbox)
        self.p18_chart_zoom_in_btn = QPushButton('+')
        self.p18_chart_zoom_in_btn.setToolTip('Zoom in on the 1Y snapshot.')
        self.p18_chart_zoom_in_btn.setFixedWidth(28)
        self.p18_chart_zoom_in_btn.clicked.connect(lambda: self._p18_zoom_chart(0.72))
        self.p18_chart_zoom_out_btn = QPushButton('-')
        self.p18_chart_zoom_out_btn.setToolTip('Zoom out on the 1Y snapshot.')
        self.p18_chart_zoom_out_btn.setFixedWidth(28)
        self.p18_chart_zoom_out_btn.clicked.connect(lambda: self._p18_zoom_chart(1.38))
        self.p18_chart_zoom_reset_btn = QPushButton('Reset')
        self.p18_chart_zoom_reset_btn.setToolTip('Reset the 1Y snapshot zoom.')
        self.p18_chart_zoom_reset_btn.setFixedWidth(54)
        self.p18_chart_zoom_reset_btn.clicked.connect(self._p18_reset_chart_zoom)
        chart_title_row.addWidget(self.p18_chart_zoom_in_btn)
        chart_title_row.addWidget(self.p18_chart_zoom_out_btn)
        chart_title_row.addWidget(self.p18_chart_zoom_reset_btn)
        chart_title_row.addWidget(self.p18_chart_status)
        chart_layout.addLayout(chart_title_row)
        self.p18_chart_axis = DateAxisItem(orientation='bottom')
        self.p18_chart_plot = pg.PlotWidget(axisItems={'bottom': self.p18_chart_axis})
        self.p18_chart_plot.getPlotItem().hideButtons()
        self.p18_chart_plot.getPlotItem().setMenuEnabled(False)
        self.p18_chart_plot.getPlotItem().hideAxis('left')
        self.p18_chart_plot.getPlotItem().showAxis('right')
        self.p18_chart_plot.setMouseEnabled(x=True, y=True)
        self.p18_chart_plot.setMinimumHeight(130)
        chart_layout.addWidget(self.p18_chart_plot, 1)
        self.p18_chart_rsi_axis = DateAxisItem(orientation='bottom')
        self.p18_chart_rsi_plot = pg.PlotWidget(axisItems={'bottom': self.p18_chart_rsi_axis})
        self.p18_chart_rsi_plot.getPlotItem().hideButtons()
        self.p18_chart_rsi_plot.getPlotItem().setMenuEnabled(False)
        self.p18_chart_rsi_plot.getPlotItem().hideAxis('left')
        self.p18_chart_rsi_plot.getPlotItem().showAxis('right')
        self.p18_chart_rsi_plot.setMouseEnabled(x=True, y=False)
        self.p18_chart_rsi_plot.setMinimumHeight(58)
        self.p18_chart_rsi_plot.setMaximumHeight(64)
        self.p18_chart_rsi_plot.setVisible(False)
        chart_layout.addWidget(self.p18_chart_rsi_plot)
        self.p18_chart_macd_axis = DateAxisItem(orientation='bottom')
        self.p18_chart_macd_plot = pg.PlotWidget(axisItems={'bottom': self.p18_chart_macd_axis})
        self.p18_chart_macd_plot.getPlotItem().hideButtons()
        self.p18_chart_macd_plot.getPlotItem().setMenuEnabled(False)
        self.p18_chart_macd_plot.getPlotItem().hideAxis('left')
        self.p18_chart_macd_plot.getPlotItem().showAxis('right')
        self.p18_chart_macd_plot.setMouseEnabled(x=True, y=True)
        self.p18_chart_macd_plot.setMinimumHeight(58)
        self.p18_chart_macd_plot.setMaximumHeight(64)
        self.p18_chart_macd_plot.setVisible(False)
        chart_layout.addWidget(self.p18_chart_macd_plot)
        try:
            self.p18_chart_rsi_plot.setXLink(self.p18_chart_plot)
            self.p18_chart_macd_plot.setXLink(self.p18_chart_plot)
        except Exception:
            pass

        options_frame = QFrame()
        self.set_theme_role(options_frame, 'panel')
        options_layout = QVBoxLayout(options_frame)
        options_layout.setContentsMargins(10, 8, 10, 8)
        options_layout.setSpacing(5)
        options_title = QLabel('Top Options By Expiration')
        self.set_theme_role(options_title, 'section_title')
        self.p18_top_options_empty = QLabel('Roll a stock to inspect top-volume contracts by expiration.')
        self.p18_top_options_empty.setWordWrap(True)
        self.set_theme_role(self.p18_top_options_empty, 'muted')
        self.p18_top_options_table = QTableWidget(0, 7)
        self.p18_top_options_table.setHorizontalHeaderLabels(['Exp', 'Type', 'Strike', 'Last', 'Vol', 'OI', 'IV'])
        self.p18_top_options_table.verticalHeader().setVisible(False)
        self.p18_top_options_table.verticalHeader().setDefaultSectionSize(22)
        self.p18_top_options_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p18_top_options_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p18_top_options_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p18_top_options_table.setAlternatingRowColors(True)
        top_options_header = self.p18_top_options_table.horizontalHeader()
        top_options_header.setMinimumHeight(24)
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

        candidates_frame = QFrame()
        self.set_theme_role(candidates_frame, 'panel')
        candidates_layout = QVBoxLayout(candidates_frame)
        candidates_layout.setContentsMargins(10, 8, 10, 8)
        candidates_layout.setSpacing(5)
        candidates_title = QLabel('Scored Candidates')
        self.set_theme_role(candidates_title, 'section_title')
        self.p18_candidates_empty = QLabel('Roll to see ranked ticker candidates.')
        self.p18_candidates_empty.setWordWrap(True)
        self.set_theme_role(self.p18_candidates_empty, 'muted')
        self.p18_candidates_table = QTableWidget(0, 10)
        self.p18_candidates_table.setHorizontalHeaderLabels(['Rank', 'Ticker', 'Score', 'Setup', 'Pattern', 'Sector', 'Day %', '1Y %', 'Avg Vol', 'Reason'])
        self.p18_candidates_table.verticalHeader().setVisible(False)
        self.p18_candidates_table.verticalHeader().setDefaultSectionSize(22)
        self.p18_candidates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p18_candidates_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p18_candidates_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p18_candidates_table.setAlternatingRowColors(True)
        candidates_header = self.p18_candidates_table.horizontalHeader()
        candidates_header.setMinimumHeight(24)
        candidates_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)
        self.p18_candidates_table.setVisible(False)
        candidates_layout.addWidget(candidates_title)
        candidates_layout.addWidget(self.p18_candidates_empty)
        candidates_layout.addWidget(self.p18_candidates_table, 1)

        news_frame = QFrame()
        self.set_theme_role(news_frame, 'panel')
        news_layout = QVBoxLayout(news_frame)
        news_layout.setContentsMargins(10, 8, 10, 8)
        news_layout.setSpacing(5)
        news_title = QLabel('Recent Headlines')
        self.set_theme_role(news_title, 'section_title')
        self.p18_news_empty = QLabel('Roll a stock to inspect recent headlines.')
        self.p18_news_empty.setWordWrap(True)
        self.set_theme_role(self.p18_news_empty, 'muted')
        self.p18_news_table = self._make_news_table(self._open_news_link_table)
        self.p18_news_table.verticalHeader().setDefaultSectionSize(22)
        self.p18_news_table.horizontalHeader().setMinimumHeight(24)
        self.p18_news_table.setAlternatingRowColors(True)
        self.p18_news_table.setVisible(False)
        news_layout.addWidget(news_title)
        news_layout.addWidget(self.p18_news_empty)
        news_layout.addWidget(self.p18_news_table, 1)

        history_frame = QFrame()
        self.set_theme_role(history_frame, 'panel')
        history_layout = QVBoxLayout(history_frame)
        history_layout.setContentsMargins(10, 8, 10, 8)
        history_layout.setSpacing(5)
        history_title = QLabel('Roll History')
        self.set_theme_role(history_title, 'section_title')
        self.p18_history_empty = QLabel('Rolled stocks will appear here for quick revisits.')
        self.p18_history_empty.setWordWrap(True)
        self.set_theme_role(self.p18_history_empty, 'muted')
        self.p18_history_table = QTableWidget(0, 4)
        self.p18_history_table.setHorizontalHeaderLabels(['Ticker', 'Company', 'Sector', 'Rolled'])
        self.p18_history_table.verticalHeader().setVisible(False)
        self.p18_history_table.verticalHeader().setDefaultSectionSize(22)
        self.p18_history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p18_history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p18_history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p18_history_table.setAlternatingRowColors(True)
        history_header = self.p18_history_table.horizontalHeader()
        history_header.setMinimumHeight(24)
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
        left_research_panel.addWidget(candidates_frame)
        left_research_panel.setStretchFactor(0, 2)
        left_research_panel.setStretchFactor(1, 3)

        right_research_panel.addWidget(options_frame)
        right_research_panel.addWidget(news_frame)
        right_research_panel.addWidget(history_frame)
        right_research_panel.setStretchFactor(0, 2)
        right_research_panel.setStretchFactor(1, 3)
        right_research_panel.setStretchFactor(2, 2)

        research_splitter.addWidget(left_research_panel)
        research_splitter.addWidget(right_research_panel)
        research_splitter.setStretchFactor(0, 3)
        research_splitter.setStretchFactor(1, 2)

        body_splitter.addWidget(research_splitter)
        body_splitter.setStretchFactor(0, 2)
        body_splitter.setStretchFactor(1, 5)
        self._p18_panel_widgets.extend([chart_frame, options_frame, candidates_frame, news_frame, history_frame])
        self._apply_random_recommender_theme()

    def _p18_set_status(self, text: Any, status: str='muted', *, include_global: bool=True) -> None:
        self.set_status_text(self.p18_status_label, text, status=status)
        if include_global and hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=status)

    def _p18_roll_stock(self, *_: Any, include_global_status: bool=True, target_symbol: Any='') -> None:
        self._p18_request_seq += 1
        request_id = self._p18_request_seq
        self._p18_active_request = request_id
        self.p18_roll_btn.setEnabled(False)
        target = str(target_symbol or '').upper().strip()
        pattern_modes = self._p18_selected_pattern_modes()
        loading_text = f'Loading {target}...' if target else ('Scanning patterns...' if pattern_modes else 'Scoring candidates...')
        self._p18_set_status(loading_text, 'info', include_global=include_global_status)
        worker = RandomStockWorker(
            exclude_symbols=self._p18_excluded_symbols(),
            history_symbols=self._p18_history_symbols(),
            target_symbol=target,
            pattern_modes=pattern_modes,
        )
        thread = QThread()
        self.p18_worker = worker
        self.p18_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda payload, req=request_id: self._p18_handle_result(req, payload))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(lambda message, req=request_id: self._p18_handle_error(req, message))
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda req=request_id, w=worker, t=thread: self._p18_cleanup_worker_refs(req, w, t))
        thread.start()

    def _p18_excluded_symbols(self) -> list[str]:
        symbols = []
        if hasattr(self, '_get_fetch_tickers'):
            try:
                symbols.extend(list(self._get_fetch_tickers() or []))
            except Exception:
                pass
        return self._p18_unique_symbols(symbols)

    def _p18_history_symbols(self) -> list[str]:
        symbols = []
        for item in list(getattr(self, '_p18_roll_history', []) or []):
            if isinstance(item, dict):
                symbols.append(item.get('symbol'))
        return self._p18_unique_symbols(symbols)

    def _p18_unique_symbols(self, values: Any) -> list[str]:
        seen = set()
        result = []
        for value in list(values or []):
            symbol = str(value or '').upper().strip()
            if symbol and symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        return result

    def _p18_selected_pattern_modes(self) -> list[str]:
        modes = []
        if getattr(self, 'p18_breakout_checkbox', None) is not None and self.p18_breakout_checkbox.isChecked():
            modes.append('breakout')
        if getattr(self, 'p18_consolidation_checkbox', None) is not None and self.p18_consolidation_checkbox.isChecked():
            modes.append('consolidation')
        if getattr(self, 'p18_downtrend_checkbox', None) is not None and self.p18_downtrend_checkbox.isChecked():
            modes.append('downtrend')
        if getattr(self, 'p18_double_bottom_checkbox', None) is not None and self.p18_double_bottom_checkbox.isChecked():
            modes.append('double_bottom')
        if getattr(self, 'p18_bullish_flag_checkbox', None) is not None and self.p18_bullish_flag_checkbox.isChecked():
            modes.append('bullish_flag')
        if getattr(self, 'p18_bullish_rsi_divergence_checkbox', None) is not None and self.p18_bullish_rsi_divergence_checkbox.isChecked():
            modes.append('bullish_rsi_divergence')
        return modes

    def _p18_cleanup_worker_refs(self, request_id: int, worker: Any, thread: Any) -> None:
        if getattr(self, 'p18_worker', None) is worker:
            self.p18_worker = None
        if getattr(self, 'p18_thread', None) is thread:
            self.p18_thread = None

    def _p18_handle_result(self, request_id: int, payload: dict[str, Any]) -> None:
        if request_id != getattr(self, '_p18_active_request', 0):
            return
        self.p18_roll_btn.setEnabled(True)
        self._p18_apply_payload(payload)
        symbol = self._p18_current_symbol()
        score = payload.get('candidate_score')
        score_text = f' score {float(score):.1f}' if isinstance(score, (int, float)) else ''
        pool_count = len(payload.get('candidate_pool') or []) if isinstance(payload.get('candidate_pool'), list) else 0
        suffix = f' from {pool_count} scored candidates' if pool_count else ''
        pattern_type = str(payload.get('pattern_type') or '').strip()
        pattern_text = f' ({pattern_type} setup)' if pattern_type and pattern_type != 'None' else ''
        fallback_reason = str(payload.get('pattern_fallback_reason') or '').strip()
        if fallback_reason:
            self._p18_set_status(f'{fallback_reason} Loaded {symbol}{score_text}{suffix}.', 'warning')
        else:
            self._p18_set_status(f'Loaded {symbol}{score_text}{pattern_text}{suffix}.', 'positive')

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
        self._p18_render_candidates(payload.get('candidate_pool') or [])
        self._p18_render_chart(payload.get('chart_history') or {})
        self._p18_render_top_options(payload.get('top_options') or [], payload.get('top_options_status') or '')
        self._p18_render_news(payload.get('news') or [])
        self._p18_update_action_buttons()
        if save_snapshot:
            self._p18_record_history(payload)
            self._p18_save_session_snapshot()

    def _p18_render_candidates(self, candidates: Any) -> None:
        clean_candidates = [dict(candidate) for candidate in list(candidates or []) if isinstance(candidate, dict)]
        self._p18_candidate_pool = clean_candidates
        if not clean_candidates:
            self.p18_candidates_table.setRowCount(0)
            self.p18_candidates_table.setVisible(False)
            self.p18_candidates_empty.setVisible(True)
            self.p18_candidates_empty.setText('No scored candidates were returned for this roll.')
            return
        self.p18_candidates_table.setRowCount(len(clean_candidates))
        current_symbol = self._p18_current_symbol()
        pattern_active = bool(self._p18_payload_pattern_modes(getattr(self, '_p18_loaded_payload', None)))
        for row_index, candidate in enumerate(clean_candidates):
            symbol = str(candidate.get('symbol', '') or '').upper().strip()
            rank_value = candidate.get('rank')
            rank_text = 'Selected' if str(rank_value) == '0' else self._p18_format_integer(rank_value or row_index + 1)
            setup_text = str(candidate.get('pattern_type') or 'Balanced')
            if setup_text == 'None':
                setup_text = 'Balanced'
            pattern_score = candidate.get('pattern_score')
            reason_text = self._p18_pattern_reason_text(candidate) if pattern_active else self._p18_candidate_reason_text(candidate)
            values = (
                rank_text,
                symbol,
                self._p18_format_score(candidate.get('score')),
                setup_text,
                self._p18_format_score(pattern_score) if candidate.get('pattern_match') else 'N/A',
                str(candidate.get('sector', '') or 'N/A'),
                self._p18_format_signed_percent_value(candidate.get('day_change_pct')),
                self._p18_format_signed_percent_value(candidate.get('fifty_two_week_change_pct')),
                self._p18_format_integer(candidate.get('average_volume')),
                reason_text,
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index == 1:
                    item.setData(Qt.ItemDataRole.UserRole, symbol)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if symbol == current_symbol:
                        item.setForeground(self.theme_qcolor('accent'))
                elif col_index in (0, 2, 4, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.p18_candidates_table.setItem(row_index, col_index, item)
        self.p18_candidates_empty.setVisible(False)
        self.p18_candidates_table.setVisible(True)

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
        score = payload.get('candidate_score')
        rank = payload.get('candidate_rank')
        reasons = [str(reason or '').strip() for reason in list(payload.get('candidate_reasons') or []) if str(reason or '').strip()]
        pattern_modes = self._p18_payload_pattern_modes(payload)
        pattern_type = str(payload.get('pattern_type') or '').strip()
        pattern_reasons = [str(reason or '').strip() for reason in list(payload.get('pattern_reasons') or []) if str(reason or '').strip()]
        pattern_score = payload.get('pattern_score')
        score_text = f'{float(score):.1f}/100' if isinstance(score, (int, float)) else 'N/A'
        rank_text = f'#{int(rank)}' if isinstance(rank, int) and rank > 0 else 'ranked'
        reason_text = ', '.join(reasons[:3]) if reasons else 'balanced liquidity, momentum, and metadata quality'
        if pattern_type and pattern_type != 'None':
            pattern_score_text = f'{float(pattern_score):.1f}/100' if isinstance(pattern_score, (int, float)) else 'N/A'
            reason_text = f'{pattern_type} setup {pattern_score_text}: ' + (', '.join(pattern_reasons[:3]) if pattern_reasons else 'technical setup matched')
            technical_text = self._p18_technical_snapshot_text(payload)
            if technical_text:
                reason_text = f'{reason_text}; {technical_text}'
        elif pattern_modes:
            reason_text = 'pattern history unavailable; showing balanced scored candidates'
        self._p18_update_why_metrics(payload, info, quote, score_text, rank_text, pattern_type, pattern_score)
        summary = str(payload.get('screening_summary') or '').strip()
        if summary:
            self.p18_why_summary.setText(f'{summary} Selected {rank_text} with a {score_text} score: {reason_text}.')
        else:
            self.p18_why_summary.setText(
                f'Picked {rank_text} with a {score_text} score from {total_text} yfinance-screened US equities: {reason_text}.'
            )
        market_cap = self._p18_info_value(info, 'marketCap') or quote.get('marketCap')
        avg_volume = self._p18_info_value(info, 'averageVolume', 'averageDailyVolume3Month') or quote.get('averageDailyVolume3Month')
        sector = self._p18_info_value(info, 'sector') or 'Sector N/A'
        exchange = self._p18_info_value(info, 'exchange', 'fullExchangeName') or quote.get('fullExchangeName') or quote.get('exchange') or 'Exchange N/A'
        badges = [
            f'Score {score_text}',
            f'{self._p18_market_cap_tier(market_cap)} cap',
            f'Vol {self._p18_format_integer(avg_volume)}',
            str(sector),
            str(exchange),
            pattern_type if pattern_type and pattern_type != 'None' else (reasons[0] if reasons else self._p18_valuation_badge(self._p18_info_value(info, 'trailingPE') or quote.get('trailingPE'))),
        ]
        for index, label in enumerate(self._p18_badge_labels):
            label.setText(badges[index] if index < len(badges) else '--')

    def _p18_update_why_metrics(
        self,
        payload: dict[str, Any],
        info: dict[str, Any],
        quote: dict[str, Any],
        score_text: str,
        rank_text: str,
        pattern_type: str,
        pattern_score: Any,
    ) -> None:
        snapshot = payload.get('technical_snapshot') if isinstance(payload, dict) else {}
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        breakout = snapshot.get('breakout') if isinstance(snapshot.get('breakout'), dict) else {}
        consolidation = snapshot.get('consolidation') if isinstance(snapshot.get('consolidation'), dict) else {}
        downtrend = snapshot.get('downtrend') if isinstance(snapshot.get('downtrend'), dict) else {}
        double_bottom = snapshot.get('double_bottom') if isinstance(snapshot.get('double_bottom'), dict) else {}
        bullish_flag = snapshot.get('bullish_flag') if isinstance(snapshot.get('bullish_flag'), dict) else {}
        bullish_rsi = snapshot.get('bullish_rsi_divergence') if isinstance(snapshot.get('bullish_rsi_divergence'), dict) else {}
        pattern_score_text = self._p18_format_score(pattern_score) if pattern_score not in (None, '', 'N/A') else 'N/A'
        setup_text = str(pattern_type or '').strip()
        if not setup_text or setup_text == 'None':
            setup_text = 'Balanced'
        values = {
            'rank': rank_text,
            'score': score_text,
            'setup': setup_text,
            'pattern': pattern_score_text if setup_text != 'Balanced' else 'N/A',
            'resistance': 'N/A',
            'ma_stack': 'N/A',
            'rsi': 'N/A',
            'macd': 'N/A',
            'volume': self._p18_format_integer(
                self._p18_info_value(info, 'averageVolume', 'averageDailyVolume3Month')
                or quote.get('averageDailyVolume3Month')
            ),
            'timeframes': 'N/A',
        }
        if breakout:
            distance = breakout.get('distance_to_resistance_pct')
            if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
                values['resistance'] = f'{float(distance):+.2f}%'
            ma_stack = str(breakout.get('daily_ma_stack') or '').strip()
            if ma_stack:
                values['ma_stack'] = ma_stack.title()
            rsi = breakout.get('rsi14')
            rsi_state = str(breakout.get('rsi_state') or '').replace('RSI ', '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)):
                values['rsi'] = f'{float(rsi):.1f}' + (f' {rsi_state}' if rsi_state else '')
            macd_state = str(breakout.get('macd_state') or '').strip()
            if macd_state:
                values['macd'] = macd_state.title()
            volume_state = str(breakout.get('volume_state') or '').strip()
            if volume_state:
                values['volume'] = volume_state.title()
            timeframe_agreement = str(breakout.get('timeframe_agreement') or '').strip()
            if timeframe_agreement:
                values['timeframes'] = timeframe_agreement
        elif consolidation:
            range_pct = consolidation.get('range_pct')
            atr20 = consolidation.get('atr20')
            atr60 = consolidation.get('atr60')
            volume20 = consolidation.get('volume20')
            volume60 = consolidation.get('volume60')
            if isinstance(range_pct, (int, float)) and math.isfinite(float(range_pct)):
                values['resistance'] = f'Range {float(range_pct):.2f}%'
            if isinstance(atr20, (int, float)) and isinstance(atr60, (int, float)) and float(atr60):
                values['ma_stack'] = f'ATR {float(atr20) / float(atr60):.2f}x'
            if isinstance(volume20, (int, float)) and isinstance(volume60, (int, float)) and float(volume60):
                values['volume'] = f'Vol {float(volume20) / float(volume60):.2f}x'
            values['rsi'] = 'Volatility contracted'
            values['macd'] = 'Inside range'
            values['timeframes'] = '20D / 60D'
        elif double_bottom:
            distance = double_bottom.get('distance_to_neckline_pct')
            bottom_gap = double_bottom.get('bottom_gap_pct')
            rebound = double_bottom.get('rebound_from_second_pct')
            if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
                values['resistance'] = f'Neckline {float(distance):+.2f}%'
            if isinstance(bottom_gap, (int, float)) and math.isfinite(float(bottom_gap)):
                values['ma_stack'] = f'Gap {float(bottom_gap):.2f}%'
            elif isinstance(rebound, (int, float)) and math.isfinite(float(rebound)):
                values['ma_stack'] = f'Rebound {float(rebound):.2f}%'
            rsi = double_bottom.get('rsi14')
            rsi_state = str(double_bottom.get('rsi_state') or '').replace('RSI ', '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)):
                values['rsi'] = f'{float(rsi):.1f}' + (f' {rsi_state}' if rsi_state else '')
            macd_state = str(double_bottom.get('macd_state') or '').strip()
            if macd_state:
                values['macd'] = macd_state.title()
            volume_state = str(double_bottom.get('volume_state') or '').strip()
            if volume_state:
                values['volume'] = volume_state.title()
            timeframe_agreement = str(double_bottom.get('timeframe_agreement') or '').strip()
            if timeframe_agreement:
                values['timeframes'] = timeframe_agreement
        elif bullish_flag:
            distance = bullish_flag.get('distance_to_flag_resistance_pct')
            pullback = bullish_flag.get('pullback_pct')
            flag_days = bullish_flag.get('flag_days')
            if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
                values['resistance'] = f'Flag {float(distance):+.2f}%'
            if isinstance(pullback, (int, float)) and math.isfinite(float(pullback)):
                values['ma_stack'] = f'Pullback {float(pullback):.2f}%'
            elif isinstance(flag_days, (int, float)) and math.isfinite(float(flag_days)):
                values['ma_stack'] = f'{int(float(flag_days))}D flag'
            rsi = bullish_flag.get('rsi14')
            rsi_state = str(bullish_flag.get('rsi_state') or '').replace('RSI ', '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)):
                values['rsi'] = f'{float(rsi):.1f}' + (f' {rsi_state}' if rsi_state else '')
            macd_state = str(bullish_flag.get('macd_state') or '').strip()
            if macd_state:
                values['macd'] = macd_state.title()
            volume_state = str(bullish_flag.get('volume_state') or '').strip()
            if volume_state:
                values['volume'] = volume_state.title()
            timeframe_agreement = str(bullish_flag.get('timeframe_agreement') or '').strip()
            if timeframe_agreement:
                values['timeframes'] = timeframe_agreement
        elif bullish_rsi:
            trigger_distance = bullish_rsi.get('trigger_distance_pct')
            rsi_points = bullish_rsi.get('rsi_divergence_points')
            price_change = bullish_rsi.get('price_low_change_pct')
            if isinstance(trigger_distance, (int, float)) and math.isfinite(float(trigger_distance)):
                values['resistance'] = f'Trigger {float(trigger_distance):+.2f}%'
            if isinstance(rsi_points, (int, float)) and math.isfinite(float(rsi_points)):
                values['ma_stack'] = f'RSI +{float(rsi_points):.1f}'
            elif isinstance(price_change, (int, float)) and math.isfinite(float(price_change)):
                values['ma_stack'] = f'Low {float(price_change):+.2f}%'
            first_rsi = bullish_rsi.get('first_rsi')
            second_rsi = bullish_rsi.get('second_rsi')
            if isinstance(first_rsi, (int, float)) and isinstance(second_rsi, (int, float)):
                values['rsi'] = f'{float(first_rsi):.1f} -> {float(second_rsi):.1f}'
            macd_state = str(bullish_rsi.get('macd_state') or '').strip()
            if macd_state:
                values['macd'] = macd_state.title()
            volume_state = str(bullish_rsi.get('volume_state') or '').strip()
            if volume_state:
                values['volume'] = volume_state.title()
            timeframe_agreement = str(bullish_rsi.get('timeframe_agreement') or '').strip()
            if timeframe_agreement:
                values['timeframes'] = timeframe_agreement
        elif downtrend:
            decline_20d = downtrend.get('decline_20d_pct')
            distance_sma50 = downtrend.get('distance_to_sma50_pct')
            if isinstance(decline_20d, (int, float)) and math.isfinite(float(decline_20d)):
                values['resistance'] = f'20D {float(decline_20d):+.2f}%'
            elif isinstance(distance_sma50, (int, float)) and math.isfinite(float(distance_sma50)):
                values['resistance'] = f'SMA50 {float(distance_sma50):+.2f}%'
            ma_stack = str(downtrend.get('daily_ma_stack') or '').strip()
            if ma_stack:
                values['ma_stack'] = ma_stack.title()
            rsi = downtrend.get('rsi14')
            rsi_state = str(downtrend.get('rsi_state') or '').replace('RSI ', '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)):
                values['rsi'] = f'{float(rsi):.1f}' + (f' {rsi_state}' if rsi_state else '')
            macd_state = str(downtrend.get('macd_state') or '').strip()
            if macd_state:
                values['macd'] = macd_state.title()
            volume_state = str(downtrend.get('volume_state') or '').strip()
            if volume_state:
                values['volume'] = volume_state.title()
            timeframe_agreement = str(downtrend.get('timeframe_agreement') or '').strip()
            if timeframe_agreement:
                values['timeframes'] = timeframe_agreement
        elif isinstance(payload, dict):
            quote_reasons = [str(reason or '').strip() for reason in list(payload.get('candidate_reasons') or []) if str(reason or '').strip()]
            values['resistance'] = self._p18_format_signed_percent_value(quote.get('regularMarketChangePercent'))
            values['ma_stack'] = self._p18_format_signed_percent_value(quote.get('fiftyTwoWeekChangePercent'))
            values['rsi'] = quote_reasons[0] if len(quote_reasons) > 0 else 'N/A'
            values['macd'] = quote_reasons[1] if len(quote_reasons) > 1 else 'N/A'
            values['timeframes'] = quote_reasons[2] if len(quote_reasons) > 2 else 'N/A'
        for key, label in self._p18_why_metric_labels.items():
            label.setText(str(values.get(key, 'N/A')))

    def _p18_technical_snapshot_text(self, payload: dict[str, Any]) -> str:
        snapshot = payload.get('technical_snapshot') if isinstance(payload, dict) else {}
        if not isinstance(snapshot, dict):
            return ''
        breakout = snapshot.get('breakout')
        downtrend = snapshot.get('downtrend')
        double_bottom = snapshot.get('double_bottom')
        bullish_flag = snapshot.get('bullish_flag')
        bullish_rsi = snapshot.get('bullish_rsi_divergence')
        if (
            not isinstance(breakout, dict)
            and not isinstance(downtrend, dict)
            and not isinstance(double_bottom, dict)
            and not isinstance(bullish_flag, dict)
            and not isinstance(bullish_rsi, dict)
        ):
            return ''
        parts = []
        if isinstance(bullish_flag, dict):
            distance = bullish_flag.get('distance_to_flag_resistance_pct')
            flagpole_gain = bullish_flag.get('flagpole_gain_pct')
            pullback = bullish_flag.get('pullback_pct')
            if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
                parts.append(f'{float(distance):+.2f}% vs flag resistance')
            if isinstance(flagpole_gain, (int, float)) and isinstance(pullback, (int, float)):
                parts.append(f'{float(flagpole_gain):.1f}% pole, {float(pullback):.1f}% pullback')
            rsi = bullish_flag.get('rsi14')
            rsi_state = str(bullish_flag.get('rsi_state') or '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)) and rsi_state:
                parts.append(f'RSI {float(rsi):.1f} {rsi_state}')
            macd_state = str(bullish_flag.get('macd_state') or '').strip()
            if macd_state:
                parts.append(f'MACD {macd_state}')
            volume_state = str(bullish_flag.get('volume_state') or '').strip()
            timeframe_agreement = str(bullish_flag.get('timeframe_agreement') or '').strip()
            if volume_state and timeframe_agreement:
                parts.append(f'{volume_state}, {timeframe_agreement} timeframes')
            elif volume_state:
                parts.append(volume_state)
            elif timeframe_agreement:
                parts.append(f'{timeframe_agreement} timeframes')
            return '; '.join(parts[:3])
        if isinstance(bullish_rsi, dict):
            trigger_distance = bullish_rsi.get('trigger_distance_pct')
            price_change = bullish_rsi.get('price_low_change_pct')
            rsi_points = bullish_rsi.get('rsi_divergence_points')
            if isinstance(trigger_distance, (int, float)) and math.isfinite(float(trigger_distance)):
                parts.append(f'{float(trigger_distance):+.2f}% vs trigger')
            if isinstance(price_change, (int, float)) and isinstance(rsi_points, (int, float)):
                parts.append(f'{float(price_change):+.2f}% low, +{float(rsi_points):.1f} RSI')
            rebound = bullish_rsi.get('rebound_from_second_pct')
            if isinstance(rebound, (int, float)) and math.isfinite(float(rebound)):
                parts.append(f'{float(rebound):.2f}% rebound')
            macd_state = str(bullish_rsi.get('macd_state') or '').strip()
            if macd_state:
                parts.append(f'MACD {macd_state}')
            volume_state = str(bullish_rsi.get('volume_state') or '').strip()
            timeframe_agreement = str(bullish_rsi.get('timeframe_agreement') or '').strip()
            if volume_state and timeframe_agreement:
                parts.append(f'{volume_state}, {timeframe_agreement} timeframes')
            elif volume_state:
                parts.append(volume_state)
            elif timeframe_agreement:
                parts.append(f'{timeframe_agreement} timeframes')
            return '; '.join(parts[:3])
        if isinstance(double_bottom, dict):
            distance = double_bottom.get('distance_to_neckline_pct')
            bottom_gap = double_bottom.get('bottom_gap_pct')
            rebound = double_bottom.get('rebound_from_second_pct')
            if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
                parts.append(f'{float(distance):+.2f}% vs neckline')
            if isinstance(bottom_gap, (int, float)) and math.isfinite(float(bottom_gap)):
                parts.append(f'{float(bottom_gap):.2f}% bottom gap')
            elif isinstance(rebound, (int, float)) and math.isfinite(float(rebound)):
                parts.append(f'{float(rebound):.2f}% rebound')
            rsi = double_bottom.get('rsi14')
            rsi_state = str(double_bottom.get('rsi_state') or '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)) and rsi_state:
                parts.append(f'RSI {float(rsi):.1f} {rsi_state}')
            macd_state = str(double_bottom.get('macd_state') or '').strip()
            if macd_state:
                parts.append(f'MACD {macd_state}')
            volume_state = str(double_bottom.get('volume_state') or '').strip()
            timeframe_agreement = str(double_bottom.get('timeframe_agreement') or '').strip()
            if volume_state and timeframe_agreement:
                parts.append(f'{volume_state}, {timeframe_agreement} timeframes')
            elif volume_state:
                parts.append(volume_state)
            elif timeframe_agreement:
                parts.append(f'{timeframe_agreement} timeframes')
            return '; '.join(parts[:3])
        if isinstance(downtrend, dict):
            decline_20d = downtrend.get('decline_20d_pct')
            distance_sma50 = downtrend.get('distance_to_sma50_pct')
            if isinstance(decline_20d, (int, float)) and math.isfinite(float(decline_20d)):
                parts.append(f'{float(decline_20d):+.2f}% over 20D')
            elif isinstance(distance_sma50, (int, float)) and math.isfinite(float(distance_sma50)):
                parts.append(f'{float(distance_sma50):+.2f}% vs SMA50')
            rsi = downtrend.get('rsi14')
            rsi_state = str(downtrend.get('rsi_state') or '').strip()
            if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)) and rsi_state:
                parts.append(f'RSI {float(rsi):.1f} {rsi_state}')
            macd_state = str(downtrend.get('macd_state') or '').strip()
            if macd_state:
                parts.append(f'MACD {macd_state}')
            volume_state = str(downtrend.get('volume_state') or '').strip()
            timeframe_agreement = str(downtrend.get('timeframe_agreement') or '').strip()
            if volume_state and timeframe_agreement:
                parts.append(f'{volume_state}, {timeframe_agreement} timeframes')
            elif volume_state:
                parts.append(volume_state)
            elif timeframe_agreement:
                parts.append(f'{timeframe_agreement} timeframes')
            return '; '.join(parts[:3])
        distance = breakout.get('distance_to_resistance_pct')
        if isinstance(distance, (int, float)) and math.isfinite(float(distance)):
            parts.append(f'{float(distance):+.2f}% vs resistance')
        rsi = breakout.get('rsi14')
        rsi_state = str(breakout.get('rsi_state') or '').strip()
        if isinstance(rsi, (int, float)) and math.isfinite(float(rsi)) and rsi_state:
            parts.append(f'RSI {float(rsi):.1f} {rsi_state}')
        macd_state = str(breakout.get('macd_state') or '').strip()
        if macd_state:
            parts.append(f'MACD {macd_state}')
        volume_state = str(breakout.get('volume_state') or '').strip()
        timeframe_agreement = str(breakout.get('timeframe_agreement') or '').strip()
        if volume_state and timeframe_agreement:
            parts.append(f'{volume_state} volume, {timeframe_agreement} timeframes')
        elif volume_state:
            parts.append(f'{volume_state} volume')
        elif timeframe_agreement:
            parts.append(f'{timeframe_agreement} timeframes')
        return '; '.join(parts[:3])

    def _p18_refresh_chart(self) -> None:
        payload = getattr(self, '_p18_loaded_payload', None)
        if isinstance(payload, dict):
            self._p18_render_chart(payload.get('chart_history') or {})

    def _p18_zoom_chart(self, factor: float) -> None:
        if not hasattr(self, 'p18_chart_plot'):
            return
        try:
            view_box = self.p18_chart_plot.getPlotItem().getViewBox()
            view_box.scaleBy((float(factor), float(factor)))
        except Exception:
            return

    def _p18_reset_chart_zoom(self) -> None:
        payload = getattr(self, '_p18_loaded_payload', None)
        if isinstance(payload, dict):
            self._p18_render_chart(payload.get('chart_history') or {})

    def _p18_chart_rows(self, history: Any) -> tuple[list[str], list[float], list[float], list[float], list[float], list[float]]:
        chart_history = history if isinstance(history, dict) else {}
        dates = list(chart_history.get('dates', []) or [])
        opens = list(chart_history.get('opens', []) or [])
        highs = list(chart_history.get('highs', []) or [])
        lows = list(chart_history.get('lows', []) or [])
        closes = list(chart_history.get('closes', []) or [])
        volumes = list(chart_history.get('volumes', []) or [])
        clean_dates = []
        clean_opens = []
        clean_highs = []
        clean_lows = []
        clean_closes = []
        clean_volumes = []
        for index, close_value in enumerate(closes):
            try:
                close_numeric = float(close_value)
            except Exception:
                continue
            if not math.isfinite(close_numeric):
                continue
            date_value = dates[index] if index < len(dates) else str(index + 1)
            open_value = opens[index] if index < len(opens) else close_numeric
            high_value = highs[index] if index < len(highs) else close_numeric
            low_value = lows[index] if index < len(lows) else close_numeric
            volume_value = volumes[index] if index < len(volumes) else 0.0
            try:
                open_numeric = float(open_value)
                high_numeric = float(high_value)
                low_numeric = float(low_value)
                volume_numeric = float(volume_value or 0.0)
            except Exception:
                open_numeric = close_numeric
                high_numeric = close_numeric
                low_numeric = close_numeric
                volume_numeric = 0.0
            if not all(math.isfinite(value) for value in (open_numeric, high_numeric, low_numeric)):
                open_numeric = close_numeric
                high_numeric = close_numeric
                low_numeric = close_numeric
            clean_dates.append(date_value)
            clean_opens.append(open_numeric)
            clean_highs.append(max(high_numeric, open_numeric, close_numeric))
            clean_lows.append(min(low_numeric, open_numeric, close_numeric))
            clean_closes.append(close_numeric)
            clean_volumes.append(volume_numeric if math.isfinite(volume_numeric) else 0.0)
        return clean_dates, clean_opens, clean_highs, clean_lows, clean_closes, clean_volumes

    def _p18_rsi_series(self, closes: list[float], period: int=14) -> Any:
        series = pd.Series(closes, dtype='float64')
        delta = series.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.where(avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(avg_loss != 0, 100.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return rsi.fillna(50.0).clip(lower=0, upper=100)

    def _p18_series_values(self, series: Any) -> list[float]:
        values = []
        raw_values = series.tolist() if hasattr(series, 'tolist') else list(series or [])
        for value in raw_values:
            try:
                numeric = float(value)
            except Exception:
                numeric = float('nan')
            values.append(numeric if math.isfinite(numeric) else float('nan'))
        return values

    def _p18_render_chart(self, history: Any) -> None:
        clean_dates, opens, highs, lows, closes, volumes = self._p18_chart_rows(history)
        self.p18_chart_plot.clear()
        self.p18_chart_rsi_plot.clear()
        self.p18_chart_macd_plot.clear()
        self.p18_chart_rsi_plot.setVisible(False)
        self.p18_chart_macd_plot.setVisible(False)
        self._p18_chart_line = None
        self._p18_chart_candle_item = None
        if len(closes) < 2:
            self.p18_chart_axis.set_dates([], '1d')
            self.p18_chart_rsi_axis.set_dates([], '1d')
            self.p18_chart_macd_axis.set_dates([], '1d')
            self.p18_chart_status.setText('No chart history available.')
            return
        if self.p18_chart_indicators_checkbox.isChecked() and len(opens) == len(closes):
            self._p18_render_technical_chart(clean_dates, opens, highs, lows, closes, volumes)
            return
        self._p18_render_line_chart(clean_dates, closes)

    def _p18_render_line_chart(self, dates: list[str], closes: list[float]) -> None:
        x_values = list(range(len(closes)))
        color = self.theme_color('accent_positive' if closes[-1] >= closes[0] else 'accent_negative')
        self._p18_chart_line = self.p18_chart_plot.plot(x_values, closes, pen=pg.mkPen(color=color, width=2.0), antialias=True)
        self.p18_chart_axis.set_dates(dates, '1d')
        self.p18_chart_rsi_axis.set_dates(dates, '1d')
        self.p18_chart_macd_axis.set_dates(dates, '1d')
        low_value = min(closes)
        high_value = max(closes)
        span = max(high_value - low_value, abs(high_value) * 0.02, 1.0)
        self.p18_chart_plot.setXRange(0, len(closes) - 1, padding=0.02)
        self.p18_chart_plot.setYRange(low_value - span * 0.08, high_value + span * 0.08, padding=0)
        change_pct = ((closes[-1] - closes[0]) / closes[0]) * 100.0 if closes[0] else 0.0
        sign = '+' if change_pct >= 0 else ''
        self.p18_chart_status.setText(f'1Y {sign}{change_pct:.1f}%')

    def _p18_render_technical_chart(
        self,
        dates: list[str],
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
    ) -> None:
        x_values = list(range(len(closes)))
        candle_points = [(index, opens[index], closes[index], lows[index], highs[index]) for index in x_values]
        candle_item = CandlestickItem(
            candle_points,
            up_color=self.theme_color('chart_up_candle'),
            down_color=self.theme_color('chart_down_candle'),
        )
        self._p18_chart_candle_item = candle_item
        self.p18_chart_plot.addItem(candle_item)

        close_series = pd.Series(closes, dtype='float64')
        sma20 = close_series.rolling(20, min_periods=20).mean()
        sma50 = close_series.rolling(50, min_periods=50).mean()
        ema21 = close_series.ewm(span=21, min_periods=21, adjust=False).mean()
        self.p18_chart_plot.plot(x_values, self._p18_series_values(sma20), pen=pg.mkPen(self.theme_color('chart_ma'), width=1.6), antialias=True)
        self.p18_chart_plot.plot(x_values, self._p18_series_values(sma50), pen=pg.mkPen(self.theme_color('chart_rsi'), width=1.2), antialias=True)
        self.p18_chart_plot.plot(x_values, self._p18_series_values(ema21), pen=pg.mkPen(self.theme_color('accent'), width=1.2, style=Qt.PenStyle.DashLine), antialias=True)

        low_value = min(lows)
        high_value = max(highs)
        span = max(high_value - low_value, abs(high_value) * 0.02, 1.0)
        volume_base = low_value - span * 0.14
        max_volume = max([value for value in volumes if value > 0] or [1.0])
        volume_heights = [(value / max_volume) * span * 0.16 for value in volumes]
        volume_brushes = []
        for open_value, close_value in zip(opens, closes):
            qcolor = self.theme_qcolor('chart_volume_up' if close_value >= open_value else 'chart_volume_down')
            qcolor.setAlpha(72)
            volume_brushes.append(pg.mkBrush(qcolor))
        self.p18_chart_plot.addItem(pg.BarGraphItem(x=x_values, y0=volume_base, height=volume_heights, width=0.65, brushes=volume_brushes))

        rsi = self._p18_rsi_series(closes)
        rsi_ma = rsi.rolling(10, min_periods=5).mean()
        self.p18_chart_rsi_plot.setVisible(True)
        self.p18_chart_rsi_plot.plot(x_values, self._p18_series_values(rsi), pen=pg.mkPen(self.theme_color('chart_rsi'), width=1.5), antialias=True)
        self.p18_chart_rsi_plot.plot(x_values, self._p18_series_values(rsi_ma), pen=pg.mkPen(self.theme_color('chart_reference'), width=1.0, style=Qt.PenStyle.DashLine), antialias=True)
        for level in (30, 50, 70):
            self.p18_chart_rsi_plot.addItem(pg.InfiniteLine(pos=level, angle=0, pen=pg.mkPen(self.theme_color('chart_reference'), width=0.8, style=Qt.PenStyle.DotLine)))
        self.p18_chart_rsi_plot.setYRange(0, 100, padding=0)

        ema12 = close_series.ewm(span=12, min_periods=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, min_periods=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, min_periods=9, adjust=False).mean()
        histogram = macd - signal
        histogram_values = self._p18_series_values(histogram.fillna(0.0))
        macd_brushes = [pg.mkBrush(self.theme_qcolor('chart_volume_up' if value >= 0 else 'chart_volume_down')) for value in histogram_values]
        self.p18_chart_macd_plot.setVisible(True)
        self.p18_chart_macd_plot.addItem(pg.BarGraphItem(x=x_values, y0=0, height=histogram_values, width=0.65, brushes=macd_brushes))
        self.p18_chart_macd_plot.plot(x_values, self._p18_series_values(macd), pen=pg.mkPen(self.theme_color('accent'), width=1.4), antialias=True)
        self.p18_chart_macd_plot.plot(x_values, self._p18_series_values(signal), pen=pg.mkPen(self.theme_color('warning'), width=1.1, style=Qt.PenStyle.DashLine), antialias=True)
        self.p18_chart_macd_plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(self.theme_color('chart_reference'), width=0.8, style=Qt.PenStyle.DotLine)))

        self.p18_chart_axis.set_dates(dates, '1d')
        self.p18_chart_rsi_axis.set_dates(dates, '1d')
        self.p18_chart_macd_axis.set_dates(dates, '1d')
        self.p18_chart_plot.setXRange(0, len(closes) - 1, padding=0.02)
        self.p18_chart_rsi_plot.setXRange(0, len(closes) - 1, padding=0.02)
        self.p18_chart_macd_plot.setXRange(0, len(closes) - 1, padding=0.02)
        self.p18_chart_plot.setYRange(volume_base, high_value + span * 0.08, padding=0)
        macd_values = [value for value in self._p18_series_values(pd.concat([macd, signal, histogram], ignore_index=True)) if math.isfinite(value)]
        if macd_values:
            macd_low = min(macd_values)
            macd_high = max(macd_values)
            macd_span = max(macd_high - macd_low, 1.0)
            self.p18_chart_macd_plot.setYRange(macd_low - macd_span * 0.12, macd_high + macd_span * 0.12, padding=0)
        change_pct = ((closes[-1] - closes[0]) / closes[0]) * 100.0 if closes[0] else 0.0
        sign = '+' if change_pct >= 0 else ''
        self.p18_chart_status.setText(f'1Y {sign}{change_pct:.1f}% | Candles + MA/Vol/RSI/MACD')

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

    def _p18_format_score(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        return f'{numeric:.1f}' if math.isfinite(numeric) else 'N/A'

    def _p18_format_signed_percent_value(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return 'N/A'
        if not math.isfinite(numeric):
            return 'N/A'
        sign = '+' if numeric >= 0 else ''
        return f'{sign}{numeric:.2f}%'

    def _p18_candidate_reason_text(self, candidate: dict[str, Any]) -> str:
        reasons = [str(reason or '').strip() for reason in list(candidate.get('reasons') or []) if str(reason or '').strip()]
        return ', '.join(reasons) if reasons else 'scored candidate'

    def _p18_pattern_reason_text(self, candidate: dict[str, Any]) -> str:
        fallback_reason = str(candidate.get('pattern_fallback_reason') or '').strip()
        if fallback_reason:
            return fallback_reason
        reasons = [str(reason or '').strip() for reason in list(candidate.get('pattern_reasons') or []) if str(reason or '').strip()]
        if reasons:
            return ', '.join(reasons)
        return self._p18_candidate_reason_text(candidate)

    def _p18_payload_pattern_modes(self, payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            return []
        return [str(mode or '').strip() for mode in list(payload.get('pattern_modes') or []) if str(mode or '').strip()]

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
        self.set_theme_role(self.p18_candidates_empty, 'muted')
        self.set_theme_role(self.p18_news_empty, 'muted')
        self.set_theme_role(self.p18_history_empty, 'muted')
        self.style_plot_widget(self.p18_chart_plot)
        self.style_plot_widget(self.p18_chart_rsi_plot)
        self.style_plot_widget(self.p18_chart_macd_plot)
        self.p18_symbol_label.setStyleSheet(f'font-size: 32px; font-weight: bold; color: {self.theme_color("accent")};')
        self.p18_company_label.setStyleSheet(f'font-size: 16px; font-weight: bold; color: {self.theme_color("text_primary")};')
        self.p18_meta_label.setStyleSheet(f'font-size: 12px; color: {self.theme_color("text_secondary")};')
        self.p18_price_label.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {self.theme_color("text_primary")};')
        for label in self._p18_badge_labels:
            label.setStyleSheet(
                f'background: transparent; color: {self.theme_color("text_secondary")}; '
                f'border: none; padding: 0 2px; font-size: 11px; font-weight: 600;'
            )
        for label in self._p18_why_metric_name_labels:
            label.setStyleSheet(f'font-size: 11px; color: {self.theme_color("text_muted")}; padding-bottom: 1px;')
        for label in self._p18_why_metric_value_labels:
            label.setStyleSheet(f'font-size: 11px; color: {self.theme_color("text_primary")}; font-weight: bold; padding-bottom: 1px;')
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
        self.p18_candidates_table.setStyleSheet(
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
            self._p18_render_candidates(payload.get('candidate_pool') or [])
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
