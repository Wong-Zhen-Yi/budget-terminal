from __future__ import annotations
from typing import Any
from ..compat import *


class NetWorthFxWorker(QObject):
    finished = pyqtSignal(dict)

    def _rate_from_fast_info(self, ticker_obj: Any) -> float | None:
        fast_info = getattr(ticker_obj, 'fast_info', {}) or {}
        for key in ('lastPrice', 'last_price', 'regularMarketPrice', 'regular_market_price'):
            try:
                value = fast_info.get(key) if hasattr(fast_info, 'get') else getattr(fast_info, key)
            except Exception:
                value = None
            rate = self._normalize_rate(value)
            if rate is not None:
                return rate
        return None

    def _rate_from_history(self, ticker_obj: Any) -> float | None:
        history = ticker_obj.history(period='1d', interval='1m')
        if history is None or getattr(history, 'empty', True) or 'Close' not in history:
            return None
        closes = history['Close'].dropna()
        if closes.empty:
            return None
        return self._normalize_rate(closes.iloc[-1])

    def _rate_from_yahoo_chart(self) -> float | None:
        response = requests.get(
            'https://query1.finance.yahoo.com/v8/finance/chart/SGD=X?range=1d&interval=1m',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        result = (payload.get('chart', {}).get('result') or [{}])[0]
        meta_rate = self._normalize_rate(result.get('meta', {}).get('regularMarketPrice'))
        if meta_rate is not None:
            return meta_rate
        quote = ((result.get('indicators', {}).get('quote') or [{}])[0])
        closes = quote.get('close') or []
        for value in reversed(closes):
            rate = self._normalize_rate(value)
            if rate is not None:
                return rate
        return None

    @staticmethod
    def _normalize_rate(value: Any) -> float | None:
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return None
        if math.isfinite(rate) and rate > 0:
            return rate
        return None

    def run(self) -> None:
        """Fetch the latest USD/SGD quote without blocking the UI thread."""
        errors = []
        rate = None
        try:
            with YF_LOCK:
                ticker_obj = yf.Ticker('SGD=X')
                rate = self._rate_from_fast_info(ticker_obj)
                if rate is None:
                    rate = self._rate_from_history(ticker_obj)
        except Exception as exc:
            errors.append(str(exc))
        if rate is None:
            try:
                rate = self._rate_from_yahoo_chart()
            except Exception as exc:
                errors.append(str(exc))
        collected_at = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if rate is not None:
            self.finished.emit({
                'ok': True,
                'usd_sgd': rate,
                'source': 'Yahoo Finance SGD=X',
                'collected_at': collected_at,
            })
            return
        self.finished.emit({
            'ok': False,
            'error': '; '.join(error for error in errors if error) or 'Unable to fetch USD/SGD rate.',
            'collected_at': collected_at,
        })


class NetWorthGoalWidget(QWidget):
    """A compact premium progress display for the Personal Finance goal."""

    def __init__(self, parent: Any=None) -> None:
        super().__init__(parent)
        self.current_value = 0.0
        self.target_value = 0.0
        self.currency = 'SGD'
        self.prefix = 'S$'
        self.status_text = 'Set a target'
        self.available = True
        self.animation_progress = 1.0
        self.accent_color = '#d6b15f'
        self.text_color = '#ffffff'
        self.muted_color = '#9aa4b2'
        self.track_color = '#2a2f38'
        self.setMinimumHeight(150)
        self.setMinimumWidth(220)

    def set_theme(self, accent: Any, text: Any, muted: Any, track: Any) -> None:
        self.accent_color = str(accent or '#d6b15f')
        self.text_color = str(text or '#ffffff')
        self.muted_color = str(muted or '#9aa4b2')
        self.track_color = str(track or '#2a2f38')
        self.update()

    def set_state(
        self,
        *,
        current_value: Any,
        target_value: Any,
        currency: Any,
        prefix: Any,
        status_text: str,
        available: bool,
        animation_progress: float,
    ) -> None:
        try:
            self.current_value = float(current_value or 0.0)
        except (TypeError, ValueError):
            self.current_value = 0.0
        try:
            self.target_value = float(target_value or 0.0)
        except (TypeError, ValueError):
            self.target_value = 0.0
        self.currency = str(currency or 'SGD')
        self.prefix = str(prefix or '$')
        self.status_text = str(status_text or '')
        self.available = bool(available)
        try:
            self.animation_progress = max(0.0, min(1.0, float(animation_progress)))
        except (TypeError, ValueError):
            self.animation_progress = 1.0
        self.update()

    def paintEvent(self, event: Any) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        margin = 12
        diameter = min(width - margin * 2, height - margin * 2, 150)
        if diameter < 40:
            return
        left = (width - diameter) / 2
        top = margin + max(0, height - margin * 2 - diameter) * 0.44
        rect = QRectF(left, top, diameter, diameter)

        track = QColor(self.track_color)
        accent = QColor(self.accent_color)
        text = QColor(self.text_color)
        muted = QColor(self.muted_color)
        if not self.available:
            accent = muted
        progress = 0.0
        if self.available and self.target_value > 0:
            progress = max(0.0, min(1.0, self.current_value / self.target_value))
        display_progress = progress * self.animation_progress

        glow_pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 34), 13)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawArc(rect.adjusted(6, 6, -6, -6), 90 * 16, int(-360 * 16 * display_progress))

        track_pen = QPen(track, 7)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect.adjusted(8, 8, -8, -8), 90 * 16, -360 * 16)

        progress_pen = QPen(accent, 7)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        painter.drawArc(rect.adjusted(8, 8, -8, -8), 90 * 16, int(-360 * 16 * display_progress))

        painter.setPen(text)
        value_font = QFont('Arial', 12)
        value_font.setBold(True)
        painter.setFont(value_font)
        center_value = 'FX required' if not self.available else f'{self.prefix}{self.current_value:,.0f}'
        painter.drawText(rect.adjusted(10, diameter * 0.32, -10, -diameter * 0.42), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, center_value)

        painter.setPen(muted)
        meta_font = QFont('Arial', 8)
        painter.setFont(meta_font)
        target_text = f'of {self.prefix}{self.target_value:,.0f} {self.currency}' if self.target_value > 0 else f'{self.currency} target'
        painter.drawText(rect.adjusted(10, diameter * 0.52, -10, -diameter * 0.22), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, target_text)

        status_font = QFont('Arial', 8)
        painter.setFont(status_font)
        fm = QFontMetrics(status_font)
        status = fm.elidedText(self.status_text, Qt.TextElideMode.ElideRight, max(20, width - margin * 2))
        painter.drawText(margin, height - margin - fm.height(), width - margin * 2, fm.height() + 2, Qt.AlignmentFlag.AlignHCenter, status)


class NetWorthMixin:
    CASH_LINE_COLOR = '#2e7d32'
    BROKERAGE_CASH_BAR_COLOR = '#f9a825'
    BROKERAGE_OPTIONS_BAR_COLOR = '#7e57c2'
    PORTFOLIO_LINE_COLORS = ['#1565c0', '#1e88e5', '#42a5f5', '#64b5f6', '#90caf9']
    DEBT_LINE_COLOR = '#c62828'
    _P6_PROGRESS_ANIMATION_INTERVAL_MS = 33
    _P6_PROGRESS_ANIMATION_DURATION_MS = 1000
    _P6_GOAL_ANIMATION_INTERVAL_MS = 33
    _P6_GOAL_ANIMATION_DURATION_MS = 900

    def _p6_portfolio_breakdown(self) -> Any:
        """Return per-portfolio stock, cash, and options values using saved portfolio names."""
        portfolio_quotes = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        breakdown = []
        all_state = getattr(self, 'all_portfolios_state', {})
        portfolios = all_state.get('portfolios', {}) if isinstance(all_state, dict) else {}
        portfolio_order = all_state.get('portfolio_order', list(portfolios.keys())) if isinstance(all_state, dict) else []
        for portfolio_id in portfolio_order:
            entry = portfolios.get(portfolio_id, {})
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id))
            tickers = list(entry.get('portfolio', []))
            tracker_data = dict(entry.get('portfolio_tracker', {})) if isinstance(entry.get('portfolio_tracker', {}), dict) else {}
            options_data = list(entry.get('options_tracker', [])) if isinstance(entry.get('options_tracker', []), list) else []
            stock_mv = sum((tracker_data.get(ticker, {}).get('shares', 0) * portfolio_quotes.get(ticker, {}).get('price', 0) for ticker in tickers))
            try:
                cash_balance = float(entry.get('cash_balance', 0.0) or 0.0)
            except (TypeError, ValueError):
                cash_balance = 0.0
            if not math.isfinite(cash_balance):
                cash_balance = 0.0
            cash_balance = max(cash_balance, 0.0)
            options_equity = 0.0
            for pos in options_data:
                strategy = pos.get('strategy', 'Calls')
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                premium = pos.get('premium', 0)
                current = pos.get('current_price', 0)
                qty = pos.get('contracts', 1)
                if is_seller:
                    options_equity += (premium - current) * qty * 100
                else:
                    options_equity += current * qty * 100
            breakdown.append({'id': portfolio_id, 'name': name, 'stocks': stock_mv, 'cash': cash_balance, 'options': options_equity})
        return breakdown

    ASSET_COLORS = ['#66bb6a', '#81c784', '#a5d6a7', '#c8e6c9', '#4caf50', '#43a047']
    DEBT_COLORS = ['#ef5350', '#e57373', '#ef9a9a', '#f44336', '#d32f2f', '#c62828']

    def _p6_table_for(self, category: Any) -> Any:
        """Return the QTableWidget for a given net-worth category."""
        if category == 'cash':
            return self.p6_cash_table
        if category == 'recurring_bills':
            return self.p6_bills_table
        return self.p6_debt_table

    def init_page6(self) -> None:
        """Build the Personal Finance page UI."""
        self._p6_usd_sgd_rate = getattr(self, '_p6_usd_sgd_rate', None)
        self._p6_fx_collected_at = getattr(self, '_p6_fx_collected_at', None)
        self._p6_fx_source = getattr(self, '_p6_fx_source', '')
        self._p6_fx_error = ''
        self._p6_fx_loading = False
        self._p6_totals_currency = self._p6_normalize_totals_currency(self.networth_data.get('totals_currency', 'SGD'))
        self.networth_data['totals_currency'] = self._p6_totals_currency
        self._p6_goal_data = self._p6_normalize_goal_data(self.networth_data.get('goal', {}))
        self.networth_data['goal'] = dict(self._p6_goal_data)
        layout = QVBoxLayout(self.page6)
        layout.setContentsMargins(10, 2, 10, 10)
        layout.setSpacing(8)
        tables_splitter = QSplitter(Qt.Orientation.Horizontal)
        cash_widget = QWidget()
        cash_layout = QVBoxLayout(cash_widget)
        cash_layout.setContentsMargins(0, 0, 0, 2)
        cash_layout.setSpacing(6)
        cash_hdr = QHBoxLayout()
        cash_hdr.setContentsMargins(0, 0, 0, 2)
        cash_hdr.setSpacing(8)
        cash_lbl = QLabel('<b>CASH (SGD)</b>')
        self.set_theme_role(cash_lbl, 'section_title')
        add_cash_btn = QPushButton('+ Add')
        add_cash_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_cash_btn, 'positive')
        add_cash_btn.clicked.connect(lambda: self._p6_add_row('cash'))
        remove_cash_btn = QPushButton('Remove')
        remove_cash_btn.setMinimumSize(72, 24)
        self.set_theme_variant(remove_cash_btn, 'danger')
        remove_cash_btn.clicked.connect(lambda: self._p6_remove_selected_row('cash'))
        cash_hdr.addWidget(cash_lbl)
        cash_hdr.addStretch()
        cash_hdr.addWidget(add_cash_btn)
        cash_hdr.addWidget(remove_cash_btn)
        self.p6_cash_table = QTableWidget(0, 2)
        self.p6_cash_table.setHorizontalHeaderLabels(['Description', 'Amount (SGD)'])
        self.p6_cash_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_cash_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p6_cash_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p6_cash_table.itemChanged.connect(lambda: self._p6_on_data_changed('cash'))
        cash_layout.addLayout(cash_hdr)
        cash_layout.addWidget(self.p6_cash_table)
        tables_splitter.addWidget(cash_widget)
        debt_widget = QWidget()
        debt_layout = QVBoxLayout(debt_widget)
        debt_layout.setContentsMargins(0, 2, 0, 0)
        debt_layout.setSpacing(6)
        debt_hdr = QHBoxLayout()
        debt_hdr.setContentsMargins(0, 0, 0, 2)
        debt_hdr.setSpacing(8)
        debt_lbl = QLabel('<b>DEBT (SGD)</b>')
        self.set_theme_role(debt_lbl, 'section_title')
        add_debt_btn = QPushButton('+ Add')
        add_debt_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_debt_btn, 'danger')
        add_debt_btn.clicked.connect(lambda: self._p6_add_row('debt'))
        remove_debt_btn = QPushButton('Remove')
        remove_debt_btn.setMinimumSize(72, 24)
        self.set_theme_variant(remove_debt_btn, 'danger')
        remove_debt_btn.clicked.connect(lambda: self._p6_remove_selected_row('debt'))
        debt_hdr.addWidget(debt_lbl)
        debt_hdr.addStretch()
        debt_hdr.addWidget(add_debt_btn)
        debt_hdr.addWidget(remove_debt_btn)
        self.p6_debt_table = QTableWidget(0, 2)
        self.p6_debt_table.setHorizontalHeaderLabels(['Description', 'Amount (SGD)'])
        self.p6_debt_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_debt_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p6_debt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p6_debt_table.itemChanged.connect(lambda: self._p6_on_data_changed('debt'))
        debt_layout.addLayout(debt_hdr)
        debt_layout.addWidget(self.p6_debt_table)
        tables_splitter.addWidget(debt_widget)
        self.p6_bills_box = QGroupBox('Recurring Bills')
        self.set_theme_role(self.p6_bills_box, 'panel')
        self.p6_bills_box.setMinimumWidth(340)
        bills_layout = QVBoxLayout(self.p6_bills_box)
        bills_layout.setContentsMargins(8, 8, 8, 8)
        bills_layout.setSpacing(6)
        bills_hdr = QHBoxLayout()
        bills_hdr.setContentsMargins(0, 0, 0, 2)
        bills_hdr.setSpacing(8)
        bills_lbl = QLabel('<b>RECURRING BILLS</b>')
        self.set_theme_role(bills_lbl, 'section_title')
        add_bill_btn = QPushButton('+ Add')
        add_bill_btn.setMinimumSize(58, 24)
        self.set_theme_variant(add_bill_btn, 'accent')
        add_bill_btn.clicked.connect(lambda: self._p6_add_row('recurring_bills'))
        remove_bill_btn = QPushButton('Remove')
        remove_bill_btn.setMinimumSize(72, 24)
        self.set_theme_variant(remove_bill_btn, 'danger')
        remove_bill_btn.clicked.connect(lambda: self._p6_remove_selected_row('recurring_bills'))
        bills_hdr.addWidget(bills_lbl)
        bills_hdr.addStretch()
        bills_hdr.addWidget(add_bill_btn)
        bills_hdr.addWidget(remove_bill_btn)
        self.p6_bills_table = QTableWidget(0, 4)
        self.p6_bills_table.setHorizontalHeaderLabels(['Description', 'Amount', 'Cycle', 'Currency'])
        self.p6_bills_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.p6_bills_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.p6_bills_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.p6_bills_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.p6_bills_table.setColumnWidth(2, 88)
        self.p6_bills_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p6_bills_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p6_bills_table.itemChanged.connect(lambda: self._p6_on_data_changed('recurring_bills'))
        bills_layout.addLayout(bills_hdr)
        bills_layout.addWidget(self.p6_bills_table, 1)
        self.p6_bills_total_label = QLabel('')
        self.p6_bills_total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.p6_bills_total_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px; font-weight: 600; background: transparent;')
        bills_layout.addWidget(self.p6_bills_total_label)
        tables_splitter.addWidget(self.p6_bills_box)
        self.p6_progress_box = QGroupBox('Totals')
        self.set_theme_role(self.p6_progress_box, 'panel')
        self.p6_progress_box.setMinimumWidth(320)
        progress_inner = QVBoxLayout(self.p6_progress_box)
        progress_inner.setContentsMargins(10, 12, 10, 10)
        progress_inner.setSpacing(6)
        progress_hdr = QHBoxLayout()
        progress_hdr.setContentsMargins(0, 0, 0, 0)
        progress_hdr.setSpacing(8)
        self.p6_progress_legend = QWidget()
        self.p6_progress_legend.setStyleSheet('background: transparent;')
        progress_legend_layout = QHBoxLayout(self.p6_progress_legend)
        progress_legend_layout.setContentsMargins(0, 0, 0, 0)
        progress_legend_layout.setSpacing(8)
        progress_hdr.addWidget(self.p6_progress_legend)
        progress_hdr.addStretch()
        view_label = QLabel('Currency')
        view_label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
        progress_hdr.addWidget(view_label)
        self.p6_totals_currency_combo = QComboBox()
        self.p6_totals_currency_combo.addItem('SGD', 'SGD')
        self.p6_totals_currency_combo.addItem('USD', 'USD')
        currency_index = self.p6_totals_currency_combo.findData(self._p6_totals_currency)
        self.p6_totals_currency_combo.setCurrentIndex(currency_index if currency_index >= 0 else 0)
        self.p6_totals_currency_combo.setFixedWidth(74)
        self.p6_totals_currency_combo.currentIndexChanged.connect(self._p6_on_totals_currency_changed)
        progress_hdr.addWidget(self.p6_totals_currency_combo)
        self.p6_show_animation_btn = QPushButton('Show Animation')
        self.p6_show_animation_btn.setMinimumHeight(24)
        self.set_theme_variant(self.p6_show_animation_btn, 'accent')
        self.p6_show_animation_btn.clicked.connect(self._p6_replay_progress_animation)
        progress_hdr.addWidget(self.p6_show_animation_btn)
        progress_inner.addLayout(progress_hdr)
        self.p6_fx_label = QLabel('')
        self.p6_fx_label.setWordWrap(True)
        self.p6_fx_label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
        progress_inner.addWidget(self.p6_fx_label)
        self.p6_currency_note = QLabel('Cash and debt are SGD. Investments and brokerage accounts are USD.')
        self.p6_currency_note.setWordWrap(True)
        self.p6_currency_note.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
        progress_inner.addWidget(self.p6_currency_note)
        self.p6_progress_plot = PieChartWidget()
        self.p6_progress_plot.set_donut(True, 0.54)
        self.p6_progress_plot.set_start_angle(90.0)
        self.p6_progress_plot.setMinimumHeight(150)
        progress_inner.addWidget(self.p6_progress_plot, 1)
        self._p6_progress_series = []
        self._p6_progress_legend_signature = []
        self._p6_progress_plot_signature = []
        self._p6_progress_plot_items = []
        self._p6_progress_anim_progress = 1.0
        self._p6_progress_autoplay_done = False
        self._p6_progress_anim_timer = QTimer(self)
        self._p6_progress_anim_timer.setInterval(self._P6_PROGRESS_ANIMATION_INTERVAL_MS)
        self._p6_progress_anim_timer.timeout.connect(self._p6_step_progress_animation)
        tables_splitter.addWidget(self.p6_progress_box)
        self.p6_goal_box = QGroupBox('Goal')
        self.set_theme_role(self.p6_goal_box, 'panel')
        self.p6_goal_box.setMinimumWidth(300)
        goal_inner = QVBoxLayout(self.p6_goal_box)
        goal_inner.setContentsMargins(10, 12, 10, 10)
        goal_inner.setSpacing(8)
        goal_title_row = QHBoxLayout()
        goal_title_row.setContentsMargins(0, 0, 0, 0)
        goal_title_row.setSpacing(8)
        self.p6_goal_title_input = QLineEdit(str(self._p6_goal_data.get('title', 'Net Worth Goal') or 'Net Worth Goal'))
        self.p6_goal_title_input.setMaxLength(64)
        self.p6_goal_title_input.setMinimumHeight(24)
        self.p6_goal_title_input.textEdited.connect(self._p6_on_goal_controls_changed)
        self.p6_goal_title_input.editingFinished.connect(self._p6_on_goal_controls_changed)
        goal_title_row.addWidget(self.p6_goal_title_input, 1)
        goal_inner.addLayout(goal_title_row)
        goal_target_row = QHBoxLayout()
        goal_target_row.setContentsMargins(0, 0, 0, 0)
        goal_target_row.setSpacing(8)
        self.p6_goal_target_label = QLabel('Target')
        self.p6_goal_target_label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
        goal_target_row.addWidget(self.p6_goal_target_label)
        self.p6_goal_target_input = QDoubleSpinBox()
        self.p6_goal_target_input.setRange(0.0, 999999999999.99)
        self.p6_goal_target_input.setDecimals(2)
        self.p6_goal_target_input.setSingleStep(10000.0)
        self.p6_goal_target_input.setValue(float(self._p6_goal_data.get('target_amount', 0.0) or 0.0))
        self.p6_goal_target_input.setPrefix(self._p6_goal_prefix(self._p6_goal_data.get('currency', self._p6_totals_currency)))
        if hasattr(self.p6_goal_target_input, 'setGroupSeparatorShown'):
            self.p6_goal_target_input.setGroupSeparatorShown(True)
        self.p6_goal_target_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.p6_goal_target_input.setKeyboardTracking(False)
        self.p6_goal_target_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.p6_goal_target_input.setMinimumHeight(24)
        self.p6_goal_target_input.editingFinished.connect(self._p6_on_goal_controls_changed)
        self.p6_goal_target_input.valueChanged.connect(self._p6_on_goal_target_value_changed)
        goal_target_row.addWidget(self.p6_goal_target_input, 1)
        self.p6_goal_currency_label = QLabel('Currency')
        self.p6_goal_currency_label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
        goal_target_row.addWidget(self.p6_goal_currency_label)
        self.p6_goal_currency_combo = QComboBox()
        self.p6_goal_currency_combo.addItem('SGD', 'SGD')
        self.p6_goal_currency_combo.addItem('USD', 'USD')
        self.p6_goal_currency_combo.setToolTip('Currency denomination for the goal target')
        goal_currency_index = self.p6_goal_currency_combo.findData(str(self._p6_goal_data.get('currency', self._p6_totals_currency)))
        self.p6_goal_currency_combo.setCurrentIndex(goal_currency_index if goal_currency_index >= 0 else 0)
        self.p6_goal_currency_combo.setFixedWidth(74)
        self.p6_goal_currency_combo.currentIndexChanged.connect(self._p6_on_goal_controls_changed)
        goal_target_row.addWidget(self.p6_goal_currency_combo)
        goal_inner.addLayout(goal_target_row)
        self.p6_goal_visual = NetWorthGoalWidget()
        self.p6_goal_visual.set_theme(self.theme_color('accent'), self.theme_color('text_primary'), self.theme_color('text_secondary'), self.theme_color('panel_border'))
        goal_inner.addWidget(self.p6_goal_visual, 1)
        self._p6_goal_anim_progress = 1.0
        self._p6_goal_anim_timer = QTimer(self)
        self._p6_goal_anim_timer.setInterval(self._P6_GOAL_ANIMATION_INTERVAL_MS)
        self._p6_goal_anim_timer.timeout.connect(self._p6_step_goal_animation)
        tables_splitter.addWidget(self.p6_goal_box)
        tables_splitter.setStretchFactor(0, 3)
        tables_splitter.setStretchFactor(1, 3)
        tables_splitter.setStretchFactor(2, 2)
        tables_splitter.setStretchFactor(3, 2)
        tables_splitter.setStretchFactor(4, 2)
        layout.addWidget(tables_splitter, 1)
        self.p6_silo_box = QGroupBox(f'Personal Finance Silos ({self._p6_totals_currency})')
        self.set_theme_role(self.p6_silo_box, 'panel')
        silo_inner = QVBoxLayout(self.p6_silo_box)
        silo_inner.setContentsMargins(6, 6, 6, 6)
        silo_inner.setSpacing(4)
        silo_toolbar = QHBoxLayout()
        silo_toolbar.addStretch()
        self.p6_scale_btn = QPushButton('Log')
        self.p6_scale_btn.setCheckable(True)
        self.p6_scale_btn.setChecked(True)
        self.p6_scale_btn.setFixedSize(52, 24)
        self.set_theme_variant(self.p6_scale_btn, 'accent')
        self.p6_scale_btn.clicked.connect(self._p6_toggle_scale)
        silo_toolbar.addWidget(self.p6_scale_btn)
        silo_inner.addLayout(silo_toolbar)
        self.p6_silo_bar = BarChartWidget()
        self.p6_silo_bar.setMinimumHeight(120)
        self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
        silo_inner.addWidget(self.p6_silo_bar, 1)
        layout.addWidget(self.p6_silo_box, 1)
        self._p6_fx_refresh_timer = QTimer(self)
        self._p6_fx_refresh_timer.setInterval(300000)
        self._p6_fx_refresh_timer.timeout.connect(self._p6_refresh_fx_rate)
        self._p6_fx_refresh_timer.start()
        self._p6_style_progress_plot()
        self._p6_populate_tables()
        self._p6_refresh_fx_label()
        QTimer.singleShot(0, self._p6_refresh_fx_rate)

    def _p6_normalize_totals_currency(self, currency: Any) -> str:
        text = str(currency or 'SGD').upper().strip()
        return text if text in ('SGD', 'USD') else 'SGD'

    def _p6_selected_totals_currency(self) -> str:
        combo = getattr(self, 'p6_totals_currency_combo', None)
        if combo is not None:
            return self._p6_normalize_totals_currency(combo.currentData() or combo.currentText())
        return self._p6_normalize_totals_currency(getattr(self, '_p6_totals_currency', 'SGD'))

    def _p6_currency_prefix(self) -> str:
        return 'S$' if self._p6_selected_totals_currency() == 'SGD' else '$'

    def _p6_goal_prefix(self, currency: Any=None) -> str:
        return 'S$' if self._p6_normalize_totals_currency(currency or self._p6_goal_currency()) == 'SGD' else '$'

    def _p6_bill_frequency(self, frequency: Any) -> str:
        text = str(frequency or 'monthly').strip().lower()
        return text if text in ('monthly', 'yearly') else 'monthly'

    def _p6_bill_annual_amount(self, amount: Any, frequency: Any) -> float:
        try:
            value = float(amount or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        return max(value, 0.0) * (12.0 if self._p6_bill_frequency(frequency) == 'monthly' else 1.0)

    def _p6_recurring_bills_annual_total(self, display_currency: Any=None) -> tuple[float, bool]:
        display = self._p6_normalize_totals_currency(display_currency or self._p6_selected_totals_currency())
        total = 0.0
        for bill in self.networth_data.get('recurring_bills', []):
            bill_data = bill if isinstance(bill, dict) else {}
            native = self._p6_normalize_totals_currency(bill_data.get('currency', display))
            annual_amount = self._p6_bill_annual_amount(
                bill_data.get('amount', 0.0),
                bill_data.get('frequency', 'monthly'),
            )
            if annual_amount <= 0:
                continue
            if native != display and self._p6_valid_usd_sgd_rate() is None:
                return 0.0, False
            total += self._p6_convert_amount(annual_amount, native, display)
        return total, True

    def _p6_update_recurring_bills_total(self) -> None:
        label = getattr(self, 'p6_bills_total_label', None)
        if label is None:
            return
        display_currency = self._p6_selected_totals_currency()
        total, available = self._p6_recurring_bills_annual_total(display_currency)
        if not available:
            label.setText(f'Annual total ({display_currency}): FX required')
            return
        prefix = self._p6_goal_prefix(display_currency)
        label.setText(f'Annual total ({display_currency}): {prefix}{total:,.2f}')

    def _p6_normalize_goal_data(self, payload: Any) -> dict[str, Any]:
        goal = payload if isinstance(payload, dict) else {}
        title = str(goal.get('title', 'Net Worth Goal') or 'Net Worth Goal').strip()[:64] or 'Net Worth Goal'
        currency = self._p6_normalize_totals_currency(goal.get('currency', self._p6_selected_totals_currency()))
        try:
            target_amount = float(goal.get('target_amount', 0.0) or 0.0)
        except (TypeError, ValueError):
            target_amount = 0.0
        if not math.isfinite(target_amount):
            target_amount = 0.0
        return {
            'title': title,
            'target_amount': max(target_amount, 0.0),
            'currency': currency,
        }

    def _p6_goal_currency(self) -> str:
        combo = getattr(self, 'p6_goal_currency_combo', None)
        if combo is not None:
            return self._p6_normalize_totals_currency(combo.currentData() or combo.currentText())
        goal = getattr(self, '_p6_goal_data', {}) if isinstance(getattr(self, '_p6_goal_data', {}), dict) else {}
        return self._p6_normalize_totals_currency(goal.get('currency', self._p6_selected_totals_currency()))

    def _p6_on_goal_target_value_changed(self, *_: Any) -> None:
        self._p6_on_goal_controls_changed()

    def _p6_on_goal_controls_changed(self, *_: Any) -> None:
        title_widget = getattr(self, 'p6_goal_title_input', None)
        target_widget = getattr(self, 'p6_goal_target_input', None)
        title = str(title_widget.text() if title_widget is not None else 'Net Worth Goal').strip()[:64] or 'Net Worth Goal'
        currency = self._p6_goal_currency()
        if target_widget is not None and hasattr(target_widget, 'interpretText'):
            target_widget.interpretText()
        try:
            target_amount = float(target_widget.value() if target_widget is not None else 0.0)
        except (TypeError, ValueError):
            target_amount = 0.0
        self._p6_goal_data = self._p6_normalize_goal_data({
            'title': title,
            'target_amount': target_amount,
            'currency': currency,
        })
        self.networth_data['goal'] = dict(self._p6_goal_data)
        if title_widget is not None and title_widget.text() != self._p6_goal_data['title']:
            title_widget.setText(self._p6_goal_data['title'])
        if target_widget is not None:
            target_widget.setPrefix(self._p6_goal_prefix(currency))
        save_networth_data(self.networth_data)
        if self._p6_valid_usd_sgd_rate() is None:
            self._p6_refresh_fx_rate()
        self._p6_replay_goal_animation()

    def _p6_sync_goal_controls(self) -> None:
        goal = self._p6_normalize_goal_data(self.networth_data.get('goal', getattr(self, '_p6_goal_data', {})))
        self._p6_goal_data = dict(goal)
        title_widget = getattr(self, 'p6_goal_title_input', None)
        if title_widget is not None:
            title_widget.blockSignals(True)
            title_widget.setText(str(goal.get('title', 'Net Worth Goal') or 'Net Worth Goal'))
            title_widget.blockSignals(False)
        currency_widget = getattr(self, 'p6_goal_currency_combo', None)
        if currency_widget is not None:
            currency_widget.blockSignals(True)
            index = currency_widget.findData(goal.get('currency', self._p6_selected_totals_currency()))
            currency_widget.setCurrentIndex(index if index >= 0 else 0)
            currency_widget.blockSignals(False)
        target_widget = getattr(self, 'p6_goal_target_input', None)
        if target_widget is not None:
            target_widget.blockSignals(True)
            target_widget.setPrefix(self._p6_goal_prefix(goal.get('currency', self._p6_selected_totals_currency())))
            target_widget.setValue(float(goal.get('target_amount', 0.0) or 0.0))
            target_widget.blockSignals(False)

    def _p6_valid_usd_sgd_rate(self) -> float | None:
        try:
            rate = float(getattr(self, '_p6_usd_sgd_rate', 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if math.isfinite(rate) and rate > 0:
            return rate
        return None

    def _p6_convert_amount(self, amount: Any, native_currency: Any, display_currency: Any=None) -> float:
        try:
            value = float(amount or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        native = self._p6_normalize_totals_currency(native_currency)
        display = self._p6_normalize_totals_currency(display_currency or self._p6_selected_totals_currency())
        if native == display:
            return value
        rate = self._p6_valid_usd_sgd_rate()
        if rate is None:
            return 0.0
        if native == 'USD' and display == 'SGD':
            return value * rate
        if native == 'SGD' and display == 'USD':
            return value / rate
        return value

    def _p6_on_totals_currency_changed(self, *_: Any) -> None:
        currency = self._p6_selected_totals_currency()
        self._p6_totals_currency = currency
        self.networth_data['totals_currency'] = currency
        save_networth_data(self.networth_data)
        if self._p6_valid_usd_sgd_rate() is None:
            self._p6_refresh_fx_rate()
        self._p6_refresh_fx_label()
        self._p6_update_total(force_progress_rebuild=True)

    def _p6_refresh_fx_rate(self, *, force: bool=False) -> None:
        if getattr(self, '_p6_fx_loading', False):
            return
        if not force and self._p6_valid_usd_sgd_rate() is not None:
            try:
                age_seconds = datetime.datetime.now(datetime.timezone.utc).timestamp() - float(getattr(self, '_p6_fx_collected_at', 0.0) or 0.0)
            except (TypeError, ValueError):
                age_seconds = 999999.0
            if age_seconds < 300.0:
                return
        self._p6_fx_loading = True
        self._p6_fx_error = ''
        self._p6_refresh_fx_label()
        thread = QThread()
        worker = NetWorthFxWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._p6_on_fx_rate_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, '_p6_fx_thread', None))
        self._p6_fx_thread = thread
        self._p6_fx_worker = worker
        thread.start()

    def _p6_on_fx_rate_result(self, payload: dict[str, Any]) -> None:
        self._p6_fx_loading = False
        if isinstance(payload, dict) and payload.get('ok'):
            self._p6_usd_sgd_rate = payload.get('usd_sgd')
            self._p6_fx_collected_at = payload.get('collected_at')
            self._p6_fx_source = str(payload.get('source', '') or '')
            self._p6_fx_error = ''
        else:
            self._p6_fx_error = str((payload or {}).get('error', 'Unable to fetch USD/SGD rate.') if isinstance(payload, dict) else 'Unable to fetch USD/SGD rate.')
        self._p6_refresh_fx_label()
        self._p6_update_total(force_progress_rebuild=True)

    def _p6_refresh_fx_label(self) -> None:
        label = getattr(self, 'p6_fx_label', None)
        if label is None:
            return
        rate = self._p6_valid_usd_sgd_rate()
        if getattr(self, '_p6_fx_loading', False):
            label.setText('FX: loading USD/SGD; converted values pending')
            return
        if rate is None:
            detail = f' ({self._p6_fx_error})' if getattr(self, '_p6_fx_error', '') else ''
            label.setText(f'FX: USD/SGD unavailable; converted values hidden{detail}')
            return
        try:
            ts = float(getattr(self, '_p6_fx_collected_at', 0.0) or 0.0)
            collected = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts else ''
        except (TypeError, ValueError, OSError):
            collected = ''
        suffix = f' at {collected}' if collected else ''
        label.setText(f'FX: 1 USD = {rate:.4f} SGD{suffix}')

    def _p6_clear_progress_legend(self) -> None:
        """Remove all progress-chart legend widgets."""
        legend_layout = self.p6_progress_legend.layout() if hasattr(self, 'p6_progress_legend') else None
        if legend_layout is None:
            return
        for index in reversed(range(legend_layout.count())):
            widget = legend_layout.itemAt(index).widget()
            if widget is not None:
                widget.deleteLater()

    def _p6_style_progress_plot(self) -> None:
        """Apply theme-aware styling to the current-totals pie chart."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        slice_colors = [
            str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent'))
            for entry in getattr(self, '_p6_progress_series', [])
        ]
        self.p6_progress_plot.set_theme(slice_colors or PieChartWidget.COLORS, self.theme_color('text_primary'))
        self.p6_progress_plot.set_donut(True, 0.54)

    def _p6_add_progress_legend_item(self, color: Any, label: str) -> None:
        """Append one inline legend chip for the totals chart."""
        legend_layout = self.p6_progress_legend.layout() if hasattr(self, 'p6_progress_legend') else None
        if legend_layout is None:
            return
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(f'background: {color}; border-radius: 5px;')
        text = QLabel(str(label or ''))
        text.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 11px; background: transparent;')
        legend_layout.addWidget(swatch)
        legend_layout.addWidget(text)

    def _p6_sync_progress_legend(self, series: list[dict[str, Any]]) -> None:
        """Rebuild the inline legend for the current-totals chart."""
        signature = [
            (
                str(entry.get('label', '') or ''),
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
            )
            for entry in series
        ]
        if signature == list(getattr(self, '_p6_progress_legend_signature', [])):
            return
        self._p6_clear_progress_legend()
        self._p6_progress_legend_signature = list(signature)
        for entry in series:
            self._p6_add_progress_legend_item(
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
                str(entry.get('label', '') or ''),
            )

    def _p6_sync_progress_plot_items(self, series: list[dict[str, Any]]) -> None:
        """Store the current totals signature for theme refreshes."""
        self._p6_progress_plot_signature = [
            (
                str(entry.get('label', '') or ''),
                str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')),
            )
            for entry in series
        ]

    def _p6_current_total_series(self) -> list[dict[str, Any]]:
        """Build current-total pie series for cash, portfolios, and debt."""
        series = []
        cash_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('cash', []))
        if cash_total > 0:
            series.append({'label': 'Cash', 'value': self._p6_convert_amount(cash_total, 'SGD'), 'color': self.CASH_LINE_COLOR})
        for index, item in enumerate(self._p6_portfolio_breakdown()):
            total_value = (
                float(item.get('stocks', 0.0) or 0.0)
                + float(item.get('cash', 0.0) or 0.0)
                + float(item.get('options', 0.0) or 0.0)
            )
            if total_value == 0:
                continue
            series.append({
                'label': str(item.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                'value': self._p6_convert_amount(total_value, 'USD'),
                'color': self.PORTFOLIO_LINE_COLORS[index % len(self.PORTFOLIO_LINE_COLORS)],
            })
        debt_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('debt', []))
        if debt_total > 0:
            series.append({'label': 'Debt', 'value': self._p6_convert_amount(debt_total, 'SGD'), 'color': self.DEBT_LINE_COLOR})
        return series

    def _p6_goal_net_worth(self, currency: Any=None) -> tuple[float, bool]:
        """Return current net worth in goal currency plus availability."""
        display_currency = self._p6_normalize_totals_currency(currency or self._p6_goal_currency())
        cash_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('cash', []))
        debt_total = sum(max(float(item.get('amount', 0.0) or 0.0), 0.0) for item in self.networth_data.get('debt', []))
        portfolio_total = 0.0
        for item in self._p6_portfolio_breakdown():
            portfolio_total += (
                float(item.get('stocks', 0.0) or 0.0)
                + float(item.get('cash', 0.0) or 0.0)
                + float(item.get('options', 0.0) or 0.0)
            )
        requires_fx = (
            (display_currency == 'SGD' and abs(portfolio_total) > 0.0001)
            or (display_currency == 'USD' and (cash_total > 0.0001 or debt_total > 0.0001))
        )
        if requires_fx and self._p6_valid_usd_sgd_rate() is None:
            return 0.0, False
        current = (
            self._p6_convert_amount(cash_total, 'SGD', display_currency)
            + self._p6_convert_amount(portfolio_total, 'USD', display_currency)
            - self._p6_convert_amount(debt_total, 'SGD', display_currency)
        )
        return current, True

    def _p6_goal_status_text(self, current_value: float, target_value: float, currency: str, available: bool) -> str:
        if not available:
            return 'FX required to value mixed currencies'
        prefix = self._p6_goal_prefix(currency)
        if target_value <= 0:
            return 'Set a target to start tracking'
        remaining = target_value - current_value
        if remaining <= 0:
            return 'Goal reached'
        progress = max(0.0, min(100.0, current_value / target_value * 100.0)) if target_value > 0 else 0.0
        return f'{prefix}{remaining:,.0f} remaining | {progress:.1f}% complete'

    def _p6_update_goal_panel(self, *, animation_progress: float | None=None) -> None:
        if not hasattr(self, 'p6_goal_visual'):
            return
        goal = self._p6_normalize_goal_data(self.networth_data.get('goal', getattr(self, '_p6_goal_data', {})))
        self._p6_goal_data = dict(goal)
        currency = self._p6_normalize_totals_currency(goal.get('currency', self._p6_selected_totals_currency()))
        current_value, available = self._p6_goal_net_worth(currency)
        target_value = float(goal.get('target_amount', 0.0) or 0.0)
        progress_value = self._p6_goal_anim_progress if animation_progress is None else animation_progress
        self.p6_goal_visual.set_state(
            current_value=current_value,
            target_value=target_value,
            currency=currency,
            prefix=self._p6_goal_prefix(currency),
            status_text=self._p6_goal_status_text(current_value, target_value, currency, available),
            available=available,
            animation_progress=progress_value,
        )

    def _p6_replay_progress_animation(self) -> None:
        """Replay the current-totals pie animation when page 6 becomes visible."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        if hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.stop()
        self._p6_progress_anim_progress = 0.0
        self._p6_update_progress_chart(self._p6_progress_series, progress=0.0)
        if self._p6_progress_series and hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.start()

    def _p6_step_progress_animation(self) -> None:
        """Advance the current-totals pie animation."""
        step = self._P6_PROGRESS_ANIMATION_INTERVAL_MS / max(float(self._P6_PROGRESS_ANIMATION_DURATION_MS), 1.0)
        self._p6_progress_anim_progress = min(1.0, float(self._p6_progress_anim_progress) + step)
        self._p6_update_progress_chart(self._p6_progress_series, progress=self._p6_progress_anim_progress)
        if self._p6_progress_anim_progress >= 1.0 and hasattr(self, '_p6_progress_anim_timer'):
            self._p6_progress_anim_timer.stop()

    def _p6_replay_goal_animation(self) -> None:
        if not hasattr(self, 'p6_goal_visual'):
            return
        if hasattr(self, '_p6_goal_anim_timer'):
            self._p6_goal_anim_timer.stop()
        self._p6_goal_anim_progress = 0.0
        self._p6_update_goal_panel(animation_progress=0.0)
        if hasattr(self, '_p6_goal_anim_timer'):
            self._p6_goal_anim_timer.start()

    def _p6_step_goal_animation(self) -> None:
        step = self._P6_GOAL_ANIMATION_INTERVAL_MS / max(float(self._P6_GOAL_ANIMATION_DURATION_MS), 1.0)
        self._p6_goal_anim_progress = min(1.0, float(self._p6_goal_anim_progress) + step)
        eased = 1.0 - pow(1.0 - self._p6_goal_anim_progress, 3)
        self._p6_update_goal_panel(animation_progress=eased)
        if self._p6_goal_anim_progress >= 1.0 and hasattr(self, '_p6_goal_anim_timer'):
            self._p6_goal_anim_timer.stop()

    def _p6_progress_counter_text(self, value: float) -> str:
        """Format the animated total label."""
        return f'{self._p6_currency_prefix()}{value:,.0f}'

    def _p6_progress_counter_positions(self, labels: list[dict[str, Any]], y_min: float, y_max: float) -> dict[int, float]:
        """Nudge right-side counter labels apart when values are close together."""
        if not labels:
            return {}
        span = max(float(y_max) - float(y_min), 1.0)
        gap = max(span * 0.08, 1.0)
        margin = gap * 0.6
        ordered = sorted(labels, key=lambda item: float(item.get('desired_y', 0.0)))
        placed = []
        next_floor = float(y_min) + margin
        for item in ordered:
            value = max(float(item.get('desired_y', 0.0)), next_floor)
            placed.append({'index': int(item.get('index', 0)), 'y': value})
            next_floor = value + gap
        upper_limit = float(y_max) - margin
        if placed and placed[-1]['y'] > upper_limit:
            shift = placed[-1]['y'] - upper_limit
            for item in placed:
                item['y'] -= shift
        lower_limit = float(y_min) + margin
        if placed and placed[0]['y'] < lower_limit:
            shift = lower_limit - placed[0]['y']
            for item in placed:
                item['y'] += shift
        return {int(item['index']): float(item['y']) for item in placed}

    def _p6_update_progress_chart(self, series: list[dict[str, Any]], *, progress: float=1.0) -> None:
        """Render the current-totals pie chart."""
        if not hasattr(self, 'p6_progress_plot'):
            return
        current_progress = min(max(float(progress), 0.0), 1.0)
        weights = {}
        slice_colors = []
        full_total = 0.0
        label_counts = {}
        for index, entry in enumerate(series):
            value = max(float(entry.get('value', 0.0) or 0.0), 0.0)
            if value <= 0:
                continue
            base_label = str(entry.get('label', f'Total {index + 1}') or f'Total {index + 1}')
            label_counts[base_label] = label_counts.get(base_label, 0) + 1
            label = base_label if label_counts[base_label] == 1 else f'{base_label} {label_counts[base_label]}'
            weights[label] = value
            slice_colors.append(str(entry.get('color', self.theme_color('accent')) or self.theme_color('accent')))
            full_total += value
        self.p6_progress_plot.set_theme(slice_colors or PieChartWidget.COLORS, self.theme_color('text_primary'))
        self.p6_progress_plot.set_data(weights)
        self.p6_progress_plot.set_animation_progress(current_progress if weights else 1.0)
        self.p6_progress_plot.set_center_text(self._p6_progress_counter_text(full_total * current_progress), f'Total {self._p6_selected_totals_currency()}')
        self.p6_progress_plot.update()

    def _p6_on_show(self) -> None:
        """Autoplay the current-totals animation only once per app session."""
        if not getattr(self, '_p6_progress_autoplay_done', False):
            self._p6_progress_autoplay_done = True
            self._p6_replay_progress_animation()
            self._p6_replay_goal_animation()

    def _p6_populate_tables(self, *, force_progress_rebuild: bool=False) -> None:
        """Handle p6 populate tables."""
        for category in ['cash', 'debt']:
            table = self._p6_table_for(category)
            data_list = sorted(self.networth_data.get(category, []), key=lambda x: x.get('amount', 0.0), reverse=True)
            table.blockSignals(True)
            table.setRowCount(0)
            for item in data_list:
                self._p6_insert_row_ui(table, category, item.get('desc', ''), item.get('amount', 0.0))
            table.blockSignals(False)
        bills_table = getattr(self, 'p6_bills_table', None)
        if bills_table is not None:
            bills_table.blockSignals(True)
            bills_table.setRowCount(0)
            bills = list(self.networth_data.get('recurring_bills', []))
            for item in bills:
                bill = item if isinstance(item, dict) else {}
                self._p6_insert_row_ui(
                    bills_table,
                    'recurring_bills',
                    bill.get('desc', ''),
                    bill.get('amount', 0.0),
                    bill.get('frequency', 'monthly'),
                    bill.get('currency', 'SGD'),
                )
            bills_table.blockSignals(False)
        self._p6_sync_goal_controls()
        self._p6_update_total(force_progress_rebuild=force_progress_rebuild)

    def _p6_insert_row_ui(self, table: Any, category: Any, desc: Any, amount: Any, frequency: Any='monthly', currency: Any='SGD') -> None:
        """Handle p6 insert row ui."""
        row = table.rowCount()
        table.insertRow(row)
        try:
            amount_value = float(amount or 0.0)
        except (TypeError, ValueError):
            amount_value = 0.0
        desc_item = QTableWidgetItem(str(desc or ''))
        amt_item = QTableWidgetItem(f'{amount_value:.2f}')
        amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, 0, desc_item)
        table.setItem(row, 1, amt_item)
        if category == 'recurring_bills':
            frequency_combo = QComboBox()
            frequency_combo.addItem('Monthly', 'monthly')
            frequency_combo.addItem('Yearly', 'yearly')
            frequency_combo.setMinimumWidth(88)
            frequency_index = frequency_combo.findData(self._p6_bill_frequency(frequency))
            frequency_combo.setCurrentIndex(frequency_index if frequency_index >= 0 else 0)
            frequency_combo.currentIndexChanged.connect(lambda *_: self._p6_on_data_changed('recurring_bills'))
            table.setCellWidget(row, 2, frequency_combo)
            currency_combo = QComboBox()
            currency_combo.addItem('SGD', 'SGD')
            currency_combo.addItem('USD', 'USD')
            currency_index = currency_combo.findData(self._p6_normalize_totals_currency(currency))
            currency_combo.setCurrentIndex(currency_index if currency_index >= 0 else 0)
            currency_combo.currentIndexChanged.connect(lambda *_: self._p6_on_data_changed('recurring_bills'))
            table.setCellWidget(row, 3, currency_combo)

    def _p6_add_row(self, category: Any) -> None:
        """Handle p6 add row."""
        table = self._p6_table_for(category)
        table.blockSignals(True)
        if category == 'recurring_bills':
            self._p6_insert_row_ui(table, category, 'New Bill', 0.0, 'monthly', self._p6_selected_totals_currency())
        else:
            self._p6_insert_row_ui(table, category, 'New Item', 0.0)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_remove_selected_row(self, category: Any) -> None:
        """Remove only the currently selected row from the chosen finance table."""
        table = self._p6_table_for(category)
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row < 0 or row >= table.rowCount():
            return
        table.blockSignals(True)
        table.removeRow(row)
        table.blockSignals(False)
        self._p6_on_data_changed(category)

    def _p6_on_data_changed(self, category: Any) -> None:
        """Handle p6 on data changed."""
        table = self._p6_table_for(category)
        new_data = []
        for r in range(table.rowCount()):
            d_item = table.item(r, 0)
            a_item = table.item(r, 1)
            if d_item and a_item:
                try:
                    amt = float(a_item.text().replace('$', '').replace(',', ''))
                except:
                    amt = 0.0
                if category == 'recurring_bills':
                    frequency_combo = table.cellWidget(r, 2)
                    currency_combo = table.cellWidget(r, 3)
                    frequency = self._p6_bill_frequency(
                        frequency_combo.currentData() if isinstance(frequency_combo, QComboBox) else 'monthly'
                    )
                    currency = self._p6_normalize_totals_currency(
                        currency_combo.currentData() if isinstance(currency_combo, QComboBox) else self._p6_selected_totals_currency()
                    )
                    new_data.append({
                        'desc': d_item.text(),
                        'amount': max(amt, 0.0),
                        'frequency': frequency,
                        'currency': currency,
                    })
                else:
                    new_data.append({'desc': d_item.text(), 'amount': amt})
        if category != 'recurring_bills':
            new_data.sort(key=lambda x: x.get('amount', 0.0), reverse=True)
        self.networth_data[category] = new_data
        save_networth_data(self.networth_data)
        if category == 'recurring_bills' and self._p6_valid_usd_sgd_rate() is None:
            self._p6_refresh_fx_rate()
        if category == 'recurring_bills':
            self._p6_update_recurring_bills_total()
            return
        self._p6_populate_tables(force_progress_rebuild=True)

    def _p6_update_total(self, *, force_progress_rebuild: bool=False) -> None:
        """Handle p6 update total."""
        portfolio_breakdown = self._p6_portfolio_breakdown()
        progress_series = self._p6_current_total_series()
        self._p6_progress_series = progress_series
        display_currency = self._p6_selected_totals_currency()
        if force_progress_rebuild:
            self._p6_progress_legend_signature = []
            self._p6_progress_plot_signature = []
        if hasattr(self, 'p6_silo_box'):
            self.p6_silo_box.setTitle(f'Personal Finance Silos ({display_currency})')
        if hasattr(self, 'p6_silo_bar'):
            self.p6_silo_bar.set_value_prefix(self._p6_currency_prefix())
        bar_data = []
        asset_idx = 0
        for ci in self.networth_data.get('cash', []):
            amt = ci.get('amount', 0.0)
            if amt > 0:
                bar_data.append((ci.get('desc', 'Cash'), self._p6_convert_amount(amt, 'SGD', display_currency), self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]))
                asset_idx += 1
        for item in portfolio_breakdown:
            stock_value = float(item.get('stocks', 0.0) or 0.0)
            brokerage_cash = float(item.get('cash', 0.0) or 0.0)
            options_value = float(item.get('options', 0.0) or 0.0)
            if stock_value > 0 or brokerage_cash > 0 or options_value > 0:
                stock_color = self.ASSET_COLORS[asset_idx % len(self.ASSET_COLORS)]
                segments = []
                if stock_value > 0:
                    segments.append({'value': self._p6_convert_amount(stock_value, 'USD', display_currency), 'color': stock_color})
                if brokerage_cash > 0:
                    segments.append({'value': self._p6_convert_amount(brokerage_cash, 'USD', display_currency), 'color': self.BROKERAGE_CASH_BAR_COLOR})
                if options_value > 0:
                    segments.append({'value': self._p6_convert_amount(options_value, 'USD', display_currency), 'color': self.BROKERAGE_OPTIONS_BAR_COLOR})
                bar_data.append({'label': str(item.get('name', 'Portfolio') or 'Portfolio'), 'segments': segments})
                asset_idx += 1
            if options_value < 0:
                bar_data.append((f"{item['name']} Options", self._p6_convert_amount(abs(options_value), 'USD', display_currency), self.DEBT_COLORS[0]))
                asset_idx += 1
        debt_idx = 0
        for di in self.networth_data.get('debt', []):
            amt = di.get('amount', 0.0)
            if amt > 0:
                bar_data.append((di.get('desc', 'Debt'), self._p6_convert_amount(amt, 'SGD', display_currency), self.DEBT_COLORS[debt_idx % len(self.DEBT_COLORS)]))
                debt_idx += 1
        self.p6_silo_bar.set_data(bar_data)
        current_progress = self._p6_progress_anim_progress if hasattr(self, '_p6_progress_anim_timer') and self._p6_progress_anim_timer.isActive() else 1.0
        self._p6_update_progress_chart(progress_series, progress=current_progress)
        goal_progress = self._p6_goal_anim_progress if hasattr(self, '_p6_goal_anim_timer') and self._p6_goal_anim_timer.isActive() else 1.0
        self._p6_update_goal_panel(animation_progress=goal_progress)
        self._p6_update_recurring_bills_total()

    def _p6_toggle_scale(self) -> None:
        """Toggle between log and linear scale for the silo bar chart."""
        use_log = self.p6_scale_btn.isChecked()
        self.p6_scale_btn.setText('Log' if use_log else 'Linear')
        self.set_theme_variant(self.p6_scale_btn, 'accent' if use_log else None)
        self.p6_scale_btn.setProperty('bt_checked', 'true' if use_log else 'false')
        self._repolish_widget(self.p6_scale_btn)
        self.p6_silo_bar.use_log = use_log
        self.p6_silo_bar.update()

    def _apply_networth_theme(self) -> None:
        """Refresh Personal Finance theme surfaces."""
        if hasattr(self, 'p6_silo_bar'):
            for label_name in ('p6_fx_label', 'p6_currency_note', 'p6_goal_target_label', 'p6_goal_currency_label'):
                label = getattr(self, label_name, None)
                if label is not None:
                    label.setStyleSheet(f'color: {self.theme_color("text_secondary")}; font-size: 11px; background: transparent;')
            bills_total_label = getattr(self, 'p6_bills_total_label', None)
            if bills_total_label is not None:
                bills_total_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px; font-weight: 600; background: transparent;')
            if hasattr(self, 'p6_goal_visual'):
                self.p6_goal_visual.set_theme(self.theme_color('accent'), self.theme_color('text_primary'), self.theme_color('text_secondary'), self.theme_color('panel_border'))
            self.p6_silo_bar.set_theme(self.theme_color('text_primary'))
            self._p6_progress_legend_signature = []
            self._p6_progress_plot_signature = []
            self._p6_style_progress_plot()
            self._p6_update_total()
            self._p6_refresh_fx_label()
