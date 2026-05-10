from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.data_service.results import describe_market_data_status, strip_market_data_keys
from budget_terminal_app.workers.market_metrics import MarketCapWorker, MonthReturnWorker, PortfolioAnalyticsWorker, PortfolioMomentumWorker

_P4_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0
_P4_MOMENTUM_REFRESH_DEBOUNCE_MS = 250
_P4_METRICS_REFRESH_DEBOUNCE_MS = 350
_P4_NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole
_P4_MISSING_NUMERIC_SORT_VALUE = float('-inf')
_P4_TRACKER_NUMERIC_COLUMNS = {
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_COST,
    P4_PORTFOLIO_COL_PRICE,
    P4_PORTFOLIO_COL_DAY_CHANGE,
    P4_PORTFOLIO_COL_MARKET_VALUE,
    P4_PORTFOLIO_COL_WEIGHT,
    P4_PORTFOLIO_COL_DOLLAR_GAIN,
    P4_PORTFOLIO_COL_GROWTH,
    P4_PORTFOLIO_COL_MARKET_CAP,
}


class _P4NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a stored numeric value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(_P4_NUMERIC_SORT_ROLE))
            right = float(other.data(_P4_NUMERIC_SORT_ROLE))
            return left < right
        except Exception:
            return super().__lt__(other)


_P4_METRICS_CARD_SPECS = (
    ('beta', 'Portfolio Beta', 'Shows how strongly the portfolio tends to move relative to the benchmark.'),
    ('alpha', 'Alpha', 'Measures performance above or below what beta alone would imply.'),
    ('volatility', 'Volatility', 'Annualized day-to-day return variability. Higher values mean a bumpier ride.'),
    ('max_drawdown', 'Max Drawdown', 'Largest peak-to-trough loss seen during the selected lookback window.'),
    ('sharpe', 'Sharpe Ratio', 'Excess return earned for each unit of total portfolio volatility.'),
    ('sortino', 'Sortino Ratio', 'Excess return earned for each unit of downside volatility only.'),
    ('cagr', 'CAGR', 'Smoothed annual growth rate from the start to the end of the period.'),
    ('tail_risk', 'Tail Risk', 'Average return during the worst 5% of days, shown as CVaR.'),
    ('skewness', 'Skewness', 'Indicates whether returns tend to have larger upside or downside surprises.'),
)
_P4_METRICS_EXPOSURE_GROUPS = (
    (
        'Coverage',
        (
            ('holdings_count', 'Holdings', 'Count of positions with positive share balances.'),
            ('valued_holdings_count', 'Valued Holdings', 'Holdings with a usable current market value for exposure calculations.'),
            ('unvalued_holdings_count', 'Unpriced Holdings', 'Holdings excluded from exposure calculations because no current value was available.'),
            ('coverage_pct', 'Coverage', 'Share of positive-share holdings included in the exposure calculation.'),
            ('invested_value', 'Invested Value', 'Current market value allocated across the priced holdings included in exposure.'),
        ),
    ),
    (
        'Concentration',
        (
            ('largest_position_ticker', 'Largest Position', 'Ticker symbol of the largest holding by current market value.'),
            ('largest_position_value', 'Largest Value', 'Current market value of the largest holding.'),
            ('top_position_weight', 'Largest Weight', 'How much of the portfolio is concentrated in the single largest holding.'),
            ('top_3_weight', 'Top 3 Weight', 'Combined portfolio weight of the three largest positions.'),
            ('top_5_weight', 'Top 5 Weight', 'Combined portfolio weight of the five largest positions.'),
        ),
    ),
    (
        'Diversification',
        (
            ('effective_holdings', 'Effective Holdings', 'Diversification-adjusted holding count based on portfolio weights.'),
            ('concentration_score', 'HHI', 'Herfindahl-Hirschman score. Higher values mean less diversification.'),
        ),
    ),
)
_P4_METRICS_TOP_POSITIONS_ROWS = 5
_P4_METRICS_LOOKBACK_OPTIONS = (
    ('1y', '1Y'),
    ('3y', '3Y'),
    ('5y', '5Y'),
    ('max', 'Max'),
)


class PortfolioMetricsMixin:
    def _p4_returns_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio/timeframe pair."""
        return (str(portfolio_id or self.active_portfolio_id), str(timeframe_key))

    def _p4_invalidate_returns_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached return metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._return_metrics_cache = {
            key: value
            for key, value in self._return_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }
        self._return_metrics_fetching = {
            key: value
            for key, value in self._return_metrics_fetching.items()
            if not (isinstance(key, tuple) and len(key) == 2 and key[0] == pid)
        }

    def _p4_momentum_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio momentum timeframe pair."""
        pid = str(portfolio_id or self.active_portfolio_id)
        return (pid, str(timeframe_key), round(self._p4_active_cash_balance(pid), 2))

    def _p4_invalidate_momentum_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached momentum metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._momentum_metrics_cache = {
            key: value
            for key, value in self._momentum_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) >= 2 and key[0] == pid)
        }
        self._momentum_metrics_fetching = {
            key: value
            for key, value in self._momentum_metrics_fetching.items()
            if not (isinstance(key, tuple) and len(key) >= 2 and key[0] == pid)
        }

    def _p4_active_tickers(self) -> Any:
        """Return tickers for the currently selected portfolio tab."""
        return getattr(self, 'active_tickers', self._get_portfolio_entry(self.active_portfolio_id).get('portfolio', []))

    def _p4_active_tracker_data(self) -> Any:
        """Return tracker data for the currently selected portfolio tab."""
        return getattr(
            self,
            'active_tracker_data',
            self._get_portfolio_entry(self.active_portfolio_id).setdefault('portfolio_tracker', {}),
        )

    def _p4_active_cash_balance(self, portfolio_id: Any = None) -> float:
        """Return the active portfolio's brokerage cash balance."""
        if portfolio_id is None or str(portfolio_id) == str(getattr(self, 'active_portfolio_id', '')):
            value = getattr(self, 'active_cash_balance', None)
            if value is None:
                value = self._get_portfolio_entry(getattr(self, 'active_portfolio_id', None)).get('cash_balance', 0.0)
        else:
            value = self._get_portfolio_entry(portfolio_id).get('cash_balance', 0.0)
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if not math.isfinite(amount):
            amount = 0.0
        return max(amount, 0.0)

    def _p4_set_active_cash_balance(self, value: Any) -> None:
        """Persist the active portfolio's brokerage cash balance and refresh dependent views."""
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if not math.isfinite(amount):
            amount = 0.0
        amount = max(amount, 0.0)
        self.active_cash_balance = amount
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        entry['cash_balance'] = amount
        if self.active_portfolio_id == self.main_portfolio_id:
            self.cash_balance = amount
        self._persist_all_portfolios()
        self._p4_invalidate_momentum_cache()
        self._p4_invalidate_portfolio_analytics_cache()
        last_data = getattr(self, 'last_data', None)
        if last_data:
            self.update_page4(last_data)
        else:
            self._p4_update_cash_dependent_views()
        if hasattr(self, '_p6_populate_tables'):
            self._p6_populate_tables(force_progress_rebuild=True)
        self._p4_schedule_momentum_refresh()
        self._p4_schedule_portfolio_metrics_refresh()

    def _p4_sync_cash_input(self) -> None:
        """Reflect the active portfolio cash value into the summary editor."""
        control = getattr(self, 'p4_cash_input', None)
        if control is None:
            return
        control.blockSignals(True)
        control.setValue(self._p4_active_cash_balance())
        control.blockSignals(False)

    def _p4_on_cash_balance_changed(self, value: float) -> None:
        """Handle user edits to brokerage cash."""
        self._p4_set_active_cash_balance(value)

    def _p4_update_cash_dependent_views(self) -> None:
        """Refresh total and allocation displays when only cash changed."""
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        metrics_map, total_value = self._p4_build_tracker_metrics_map(portfolio)
        weights = {symbol: item.get('weight', 0.0) for symbol, item in metrics_map.items()}
        cash_balance = self._p4_active_cash_balance()
        if cash_balance > 0.0 and total_value > 0.0:
            weights['CASH'] = cash_balance / total_value * 100.0
        if hasattr(self, 'p4_total_label'):
            self.p4_total_label.setText(f'Total:  ${total_value:,.2f}  USD')
        if hasattr(self, 'p4_weight_chart'):
            self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)

    def _build_portfolio_metrics_page(self) -> Any:
        """Build the Portfolio Metrics sub-tab content."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(8)

        controls_frame = QFrame()
        self.set_theme_role(controls_frame, 'panel')
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(12, 12, 12, 12)
        controls_layout.setSpacing(8)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        controls_title = QLabel('Risk & Return Analytics')
        self.set_theme_role(controls_title, 'section_title')
        benchmark_label = QLabel('Benchmark')
        self.set_theme_role(benchmark_label, 'muted')
        self.p4_metrics_benchmark_input = QLineEdit()
        self.p4_metrics_benchmark_input.setPlaceholderText('SPY')
        self.p4_metrics_benchmark_input.setMinimumWidth(90)
        self.p4_metrics_benchmark_input.setMaximumWidth(140)
        self.p4_metrics_benchmark_input.editingFinished.connect(self._p4_on_metrics_benchmark_edited)
        lookback_label = QLabel('Lookback')
        self.set_theme_role(lookback_label, 'muted')
        self.p4_metrics_lookback_combo = QComboBox()
        self.p4_metrics_lookback_combo.setMinimumWidth(90)
        for key, label in _P4_METRICS_LOOKBACK_OPTIONS:
            self.p4_metrics_lookback_combo.addItem(label, key)
        self.p4_metrics_lookback_combo.currentIndexChanged.connect(self._p4_on_metrics_lookback_changed)
        controls_row.addWidget(controls_title)
        controls_row.addStretch()
        controls_row.addWidget(benchmark_label)
        controls_row.addWidget(self.p4_metrics_benchmark_input)
        controls_row.addWidget(lookback_label)
        controls_row.addWidget(self.p4_metrics_lookback_combo)
        controls_layout.addLayout(controls_row)

        self.p4_metrics_status_label = QLabel('')
        self.p4_metrics_status_label.setWordWrap(True)
        self.p4_metrics_window_label = QLabel('')
        self.p4_metrics_window_label.setWordWrap(True)
        self.set_theme_role(self.p4_metrics_window_label, 'muted')
        controls_layout.addWidget(self.p4_metrics_status_label)
        controls_layout.addWidget(self.p4_metrics_window_label)
        page_layout.addWidget(controls_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        metrics_content = QWidget()
        metrics_content_layout = QVBoxLayout(metrics_content)
        metrics_content_layout.setContentsMargins(0, 0, 0, 0)
        metrics_content_layout.setSpacing(8)

        metrics_grid = QGridLayout()
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(8)
        self.p4_metrics_value_labels = {}
        for index, (metric_key, title, subtitle) in enumerate(_P4_METRICS_CARD_SPECS):
            card = QFrame()
            self.set_theme_role(card, 'panel')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(6)
            title_label = QLabel(title)
            self.set_theme_role(title_label, 'card_title')
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            self.set_theme_role(subtitle_label, 'muted')
            value_label = QLabel('--')
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.set_theme_role(value_label, 'metric')
            title_label.setToolTip(subtitle)
            value_label.setToolTip(subtitle)
            subtitle_label.setToolTip(subtitle)
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            card_layout.addWidget(subtitle_label)
            card_layout.addStretch(1)
            self.p4_metrics_value_labels[metric_key] = value_label
            metrics_grid.addWidget(card, index // 3, index % 3)
        metrics_content_layout.addLayout(metrics_grid)

        exposure_frame = QFrame()
        self.set_theme_role(exposure_frame, 'panel')
        exposure_layout = QVBoxLayout(exposure_frame)
        exposure_layout.setContentsMargins(12, 12, 12, 12)
        exposure_layout.setSpacing(8)
        exposure_title = QLabel('Exposure Metrics')
        self.set_theme_role(exposure_title, 'section_title')
        exposure_layout.addWidget(exposure_title)
        exposure_grid = QGridLayout()
        exposure_grid.setContentsMargins(0, 0, 0, 0)
        exposure_grid.setHorizontalSpacing(8)
        exposure_grid.setVerticalSpacing(8)
        self.p4_metrics_exposure_labels = {}
        coverage_panel, coverage_labels = self._p4_build_exposure_summary_panel(_P4_METRICS_EXPOSURE_GROUPS[0][0], _P4_METRICS_EXPOSURE_GROUPS[0][1])
        concentration_panel, concentration_labels = self._p4_build_exposure_summary_panel(_P4_METRICS_EXPOSURE_GROUPS[1][0], _P4_METRICS_EXPOSURE_GROUPS[1][1])
        diversification_panel, diversification_labels = self._p4_build_exposure_summary_panel(_P4_METRICS_EXPOSURE_GROUPS[2][0], _P4_METRICS_EXPOSURE_GROUPS[2][1])
        self.p4_metrics_exposure_labels.update(coverage_labels)
        self.p4_metrics_exposure_labels.update(concentration_labels)
        self.p4_metrics_exposure_labels.update(diversification_labels)
        top_holdings_panel = self._p4_build_exposure_top_holdings_panel()
        exposure_grid.addWidget(coverage_panel, 0, 0)
        exposure_grid.addWidget(concentration_panel, 0, 1)
        exposure_grid.addWidget(diversification_panel, 1, 0)
        exposure_grid.addWidget(top_holdings_panel, 1, 1)
        exposure_grid.setColumnStretch(0, 1)
        exposure_grid.setColumnStretch(1, 1)
        exposure_layout.addLayout(exposure_grid)
        metrics_content_layout.addWidget(exposure_frame)
        metrics_content_layout.addStretch(1)
        scroll.setWidget(metrics_content)
        page_layout.addWidget(scroll, 1)

        self._p4_sync_portfolio_metrics_controls()
        self._p4_reset_portfolio_metrics_view()
        return page

    def _p4_build_exposure_summary_panel(self, title: str, row_specs: Any) -> tuple[Any, dict[str, Any]]:
        """Build one compact grouped exposure panel and return its value labels."""
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        title_label = QLabel(title)
        self.set_theme_role(title_label, 'card_title')
        layout.addWidget(title_label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        labels = {}
        for row_index, (field_key, label_text, tooltip_text) in enumerate(tuple(row_specs or ())):
            name_label = QLabel(label_text)
            self.set_theme_role(name_label, 'muted')
            value_label = QLabel('--')
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.set_theme_role(value_label, 'card_title')
            name_label.setToolTip(tooltip_text)
            value_label.setToolTip(tooltip_text)
            grid.addWidget(name_label, row_index, 0)
            grid.addWidget(value_label, row_index, 1)
            labels[field_key] = value_label
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        return panel, labels

    def _p4_build_exposure_top_holdings_panel(self) -> Any:
        """Build the ranked top-holdings panel for the exposure section."""
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        title_label = QLabel('Top Holdings')
        self.set_theme_role(title_label, 'card_title')
        layout.addWidget(title_label)
        hint_label = QLabel('Largest priced positions by current market value.')
        hint_label.setWordWrap(True)
        self.set_theme_role(hint_label, 'muted')
        layout.addWidget(hint_label)
        self.p4_metrics_top_position_rows = []
        for index in range(_P4_METRICS_TOP_POSITIONS_ROWS):
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            rank_label = QLabel(f'{index + 1}.')
            self.set_theme_role(rank_label, 'muted')
            rank_label.setMinimumWidth(18)
            ticker_label = QLabel('--')
            self.set_theme_role(ticker_label, 'card_title')
            weight_label = QLabel('--')
            weight_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.set_theme_role(weight_label, 'card_title')
            value_label = QLabel('')
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.set_theme_role(value_label, 'muted')
            row_layout.addWidget(rank_label)
            row_layout.addWidget(ticker_label, 1)
            row_layout.addWidget(weight_label)
            row_layout.addWidget(value_label)
            layout.addLayout(row_layout)
            self.p4_metrics_top_position_rows.append({
                'ticker': ticker_label,
                'weight': weight_label,
                'value': value_label,
            })
        layout.addStretch(1)
        return panel

    def _p4_sync_portfolio_metrics_controls(self) -> None:
        """Reflect the persisted Portfolio Metrics state into the widgets."""
        benchmark_symbol = str(
            getattr(self, 'p4_metrics_benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
            or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']
        ).upper().strip()
        lookback_key = str(
            getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
            or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
        ).strip().lower()
        if hasattr(self, 'p4_metrics_benchmark_input'):
            self.p4_metrics_benchmark_input.blockSignals(True)
            self.p4_metrics_benchmark_input.setText(benchmark_symbol)
            self.p4_metrics_benchmark_input.blockSignals(False)
        if hasattr(self, 'p4_metrics_lookback_combo'):
            self.p4_metrics_lookback_combo.blockSignals(True)
            index = self.p4_metrics_lookback_combo.findData(lookback_key)
            if index >= 0:
                self.p4_metrics_lookback_combo.setCurrentIndex(index)
            self.p4_metrics_lookback_combo.blockSignals(False)

    def _p4_normalize_metrics_benchmark_symbol(self, value: Any) -> str:
        """Normalize a benchmark symbol entered into the metrics tab."""
        return str(value or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']).upper().strip() or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']

    def _p4_metrics_tab_visible(self) -> bool:
        """Return whether the Portfolio Metrics sub-tab is currently selected."""
        return (
            hasattr(self, 'p4_content_tabs')
            and hasattr(self, 'p4_metrics_page')
            and self.p4_content_tabs.currentWidget() is self.p4_metrics_page
        )

    def _p4_portfolio_metrics_settings_payload(self) -> dict[str, Any]:
        """Return the normalized persisted settings payload for the metrics tab."""
        return {
            'benchmark_symbol': self._p4_normalize_metrics_benchmark_symbol(
                getattr(self, 'p4_metrics_benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
            ),
            'lookback_key': str(
                getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
                or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
            ).strip().lower(),
        }

    def _p4_persist_portfolio_metrics_settings(self) -> None:
        """Persist the benchmark and lookback controls for the metrics sub-tab."""
        self.portfolio_metrics_state = save_portfolio_metrics_settings(self._p4_portfolio_metrics_settings_payload())

    def _p4_portfolio_analytics_shares_signature(self, portfolio_id: Any=None) -> tuple[tuple[str, float], ...]:
        """Return a stable signature of positive share counts for cache invalidation."""
        portfolio_id = str(portfolio_id or self.active_portfolio_id)
        if portfolio_id == str(self.active_portfolio_id):
            tracker_data = self._p4_active_tracker_data()
        else:
            tracker_data = self._get_portfolio_entry(portfolio_id).setdefault('portfolio_tracker', {})
        signature = []
        for ticker, tracker_entry in (tracker_data or {}).items():
            symbol = str(ticker or '').upper().strip()
            if not symbol:
                continue
            try:
                shares = float((tracker_entry or {}).get('shares', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                shares = 0.0
            if shares > 0:
                signature.append((symbol, round(shares, 8)))
        cash_balance = self._p4_active_cash_balance(portfolio_id)
        if cash_balance > 0.0:
            signature.append(('CASH', round(cash_balance, 2)))
        return tuple(sorted(signature))

    def _p4_portfolio_analytics_cache_key(
        self,
        *,
        portfolio_id: Any=None,
        benchmark_symbol: Any=None,
        lookback_key: Any=None,
        shares_signature: Any=None,
    ) -> Any:
        """Build the cache key for one portfolio/benchmark/lookback combination."""
        pid = str(portfolio_id or self.active_portfolio_id)
        benchmark = self._p4_normalize_metrics_benchmark_symbol(
            benchmark_symbol if benchmark_symbol is not None else getattr(self, 'p4_metrics_benchmark_symbol', 'SPY')
        )
        lookback = str(
            lookback_key if lookback_key is not None else getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
        ).strip().lower()
        signature = shares_signature if shares_signature is not None else self._p4_portfolio_analytics_shares_signature(pid)
        return (pid, benchmark, lookback, signature)

    def _p4_invalidate_portfolio_analytics_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached portfolio analytics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._portfolio_analytics_cache = {
            key: value
            for key, value in getattr(self, '_portfolio_analytics_cache', {}).items()
            if not (isinstance(key, tuple) and len(key) == 4 and key[0] == pid)
        }
        self._portfolio_analytics_fetching = {
            key: value
            for key, value in getattr(self, '_portfolio_analytics_fetching', {}).items()
            if not (isinstance(key, tuple) and len(key) == 4 and key[0] == pid)
        }

    def _p4_metrics_price_map(self) -> dict[str, float]:
        """Return the latest known prices for the active portfolio tickers."""
        prices = {}
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        for ticker in self._p4_active_tickers():
            symbol = str(ticker or '').upper().strip()
            if not symbol:
                continue
            raw_price = (portfolio.get(symbol, {}) if isinstance(portfolio, dict) else {}).get('price', 0)
            try:
                prices[symbol] = float(raw_price)
            except (TypeError, ValueError):
                continue
        return prices

    def _p4_schedule_portfolio_metrics_refresh(self) -> None:
        """Debounce expensive portfolio-metrics refreshes while the tracker is being edited."""
        if not self._p4_metrics_tab_visible():
            return
        timer = getattr(self, '_p4_metrics_refresh_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._p4_flush_portfolio_metrics_refresh)
            self._p4_metrics_refresh_timer = timer
        timer.start(_P4_METRICS_REFRESH_DEBOUNCE_MS)

    def _p4_flush_portfolio_metrics_refresh(self) -> None:
        """Run the deferred portfolio-metrics refresh after tracker edits settle."""
        self._p4_refresh_portfolio_metrics_view()

    def _p4_set_portfolio_metrics_status(self, text: Any, *, status: str='muted') -> None:
        """Update the sub-tab status label if it exists."""
        if hasattr(self, 'p4_metrics_status_label'):
            self.set_status_text(self.p4_metrics_status_label, text, status=status)

    def _p4_update_stock_positions_label(self, count: Any = None) -> None:
        """Refresh the Positions sub-tab stock-position count badge."""
        if not hasattr(self, 'p4_stock_positions_label'):
            return
        if count is None:
            try:
                count = len(list(self._p4_active_tickers()))
            except Exception:
                count = 0
        try:
            numeric_count = max(int(count), 0)
        except (TypeError, ValueError):
            numeric_count = 0
        self.p4_stock_positions_label.setText(f'Stock Positions:  {numeric_count}')

    def _p4_metric_display_text(self, metric_key: str, value: Any) -> tuple[str, str]:
        """Format one analytics metric for display."""
        if value is None:
            return ('--', 'muted')
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ('--', 'muted')
        if not math.isfinite(numeric):
            return ('--', 'muted')
        if metric_key == 'beta':
            return (f'{numeric:.2f}x', 'accent')
        if metric_key == 'alpha':
            return (f'{numeric:+.1f}% / yr', 'positive' if numeric >= 0 else 'negative')
        if metric_key == 'volatility':
            return (f'{numeric:.1f}% / yr', 'accent')
        if metric_key == 'max_drawdown':
            return (f'{numeric:.1f}%', 'negative' if numeric < 0 else 'positive')
        if metric_key in ('sharpe', 'sortino'):
            return (f'{numeric:.2f}', 'positive' if numeric >= 0 else 'negative')
        if metric_key == 'cagr':
            return (f'{numeric:+.1f}% / yr', 'positive' if numeric >= 0 else 'negative')
        if metric_key == 'tail_risk':
            return (f'{numeric:.2f}% CVaR', 'negative' if numeric < 0 else 'positive')
        if metric_key == 'skewness':
            return (f'{numeric:.2f}', 'positive' if numeric >= 0 else 'negative')
        return (f'{numeric:.2f}', 'accent')

    def _p4_exposure_display_text(self, field_key: str, value: Any) -> str:
        """Format one exposure metric for display."""
        if field_key == 'largest_position_ticker':
            text = str(value or '').upper().strip()
            return text or '--'
        if value is None:
            return '--'
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return '--'
        if not math.isfinite(numeric):
            return '--'
        if field_key in ('holdings_count', 'valued_holdings_count', 'unvalued_holdings_count'):
            return f'{int(round(numeric))}'
        if field_key in ('invested_value', 'largest_position_value'):
            return f'${numeric:,.2f}'
        if field_key in ('top_position_weight', 'top_3_weight', 'top_5_weight', 'coverage_pct'):
            return f'{numeric:.1f}%'
        if field_key == 'concentration_score':
            return f'{numeric:.3f}'
        if field_key == 'effective_holdings':
            return f'{numeric:.1f}'
        return f'{numeric:.2f}'

    def _p4_apply_top_positions(self, positions: Any) -> None:
        """Render the ranked top-holdings rows inside the exposure panel."""
        rows = list(getattr(self, 'p4_metrics_top_position_rows', []))
        normalized_positions = []
        for raw_position in positions if isinstance(positions, list) else []:
            if not isinstance(raw_position, dict):
                continue
            ticker = str(raw_position.get('ticker', '') or '').upper().strip()
            if not ticker:
                continue
            normalized_positions.append({
                'ticker': ticker,
                'weight_text': self._p4_exposure_display_text('coverage_pct', raw_position.get('weight_pct')),
                'value_text': self._p4_exposure_display_text('invested_value', raw_position.get('value')),
            })
            if len(normalized_positions) >= _P4_METRICS_TOP_POSITIONS_ROWS:
                break
        for index, row in enumerate(rows):
            ticker_label = row.get('ticker')
            weight_label = row.get('weight')
            value_label = row.get('value')
            payload = normalized_positions[index] if index < len(normalized_positions) else None
            if payload is None:
                if ticker_label is not None:
                    ticker_label.setText('--')
                if weight_label is not None:
                    weight_label.setText('--')
                if value_label is not None:
                    value_label.setText('')
                continue
            if ticker_label is not None:
                ticker_label.setText(payload['ticker'])
            if weight_label is not None:
                weight_label.setText(payload['weight_text'])
            if value_label is not None:
                value_label.setText(payload['value_text'])

    def _p4_reset_portfolio_metrics_view(self) -> None:
        """Reset the metrics tab to its placeholder state."""
        for metric_key in getattr(self, 'p4_metrics_value_labels', {}):
            label = self.p4_metrics_value_labels[metric_key]
            label.setText('--')
            label.setStyleSheet('')
        for field_key in getattr(self, 'p4_metrics_exposure_labels', {}):
            self.p4_metrics_exposure_labels[field_key].setText('--')
        self._p4_apply_top_positions([])
        if hasattr(self, 'p4_metrics_window_label'):
            self.p4_metrics_window_label.setText('Current-share risk analytics load when this sub-tab is active.')
        self._p4_set_portfolio_metrics_status('Load this tab to inspect portfolio risk, drawdown, and benchmark-relative metrics.', status='muted')

    def _p4_apply_portfolio_analytics_payload(self, payload: Any) -> None:
        """Render one normalized analytics payload into the Portfolio Metrics sub-tab."""
        if not isinstance(payload, dict):
            payload = {}
        metadata_status_text, metadata_status = describe_market_data_status(payload, 'Portfolio metrics loaded.')
        metrics = payload.get('metrics', {}) if isinstance(payload.get('metrics'), dict) else {}
        exposure = payload.get('exposure', {}) if isinstance(payload.get('exposure'), dict) else {}
        for metric_key, label in getattr(self, 'p4_metrics_value_labels', {}).items():
            text, status = self._p4_metric_display_text(metric_key, metrics.get(metric_key))
            label.setText(text)
            if status == 'positive':
                color = self.theme_color('accent_positive')
            elif status == 'negative':
                color = self.theme_color('accent_negative')
            elif status == 'accent':
                color = self.theme_color('accent')
            else:
                color = self.theme_color('text_muted')
            label.setStyleSheet(f'color: {color};')
        for field_key, label in getattr(self, 'p4_metrics_exposure_labels', {}).items():
            label.setText(self._p4_exposure_display_text(field_key, exposure.get(field_key)))
        self._p4_apply_top_positions(exposure.get('top_positions'))
        start_date = str(payload.get('start_date') or '--')
        end_date = str(payload.get('end_date') or '--')
        history_points = int(payload.get('history_points', 0) or 0)
        included_count = len(list(payload.get('included_tickers', []) or []))
        benchmark_symbol = str(payload.get('benchmark_symbol') or getattr(self, 'p4_metrics_benchmark_symbol', 'SPY')).upper()
        lookback_key = str(payload.get('lookback_key') or getattr(self, 'p4_metrics_lookback_key', '1y')).lower()
        lookback_label = next((label for key, label in _P4_METRICS_LOOKBACK_OPTIONS if key == lookback_key), lookback_key.upper())
        if hasattr(self, 'p4_metrics_window_label'):
            self.p4_metrics_window_label.setText(
                f'{included_count} holding{"s" if included_count != 1 else ""} | {history_points} daily points | '
                f'{start_date} to {end_date} | Benchmark {benchmark_symbol} | {lookback_label}'
            )
        reason = str(payload.get('reason') or '').strip()
        note = str(payload.get('note') or '').strip()
        if reason:
            self._p4_set_portfolio_metrics_status(reason, status='warning')
        elif note:
            self._p4_set_portfolio_metrics_status(note, status='warning')
        elif metadata_status != 'positive':
            self._p4_set_portfolio_metrics_status(metadata_status_text, status=metadata_status)
        else:
            self._p4_set_portfolio_metrics_status(metadata_status_text, status='positive')

    def _fetch_portfolio_analytics(self, *, force: bool=False) -> None:
        """Fetch portfolio analytics for the active portfolio and selected benchmark."""
        if not hasattr(self, 'p4_metrics_page'):
            return
        benchmark_symbol = self._p4_normalize_metrics_benchmark_symbol(
            getattr(self, 'p4_metrics_benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
        )
        lookback_key = str(
            getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
            or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
        ).strip().lower()
        cache_key = self._p4_portfolio_analytics_cache_key(
            portfolio_id=self.active_portfolio_id,
            benchmark_symbol=benchmark_symbol,
            lookback_key=lookback_key,
        )
        if force:
            getattr(self, '_portfolio_analytics_cache', {}).pop(cache_key, None)
        elif cache_key in getattr(self, '_portfolio_analytics_cache', {}):
            self._p4_apply_portfolio_analytics_payload(self._portfolio_analytics_cache.get(cache_key, {}))
            return
        if self._portfolio_analytics_fetching.get(cache_key, False):
            self._p4_set_portfolio_metrics_status('Refreshing portfolio metrics...', status='info')
            return
        shares_map = self._p4_active_momentum_shares_map()
        tickers = list(self._p4_active_tickers())
        prices_map = self._p4_metrics_price_map()
        cash_amount = self._p4_active_cash_balance()
        self._portfolio_analytics_fetching[cache_key] = True
        self._p4_set_portfolio_metrics_status(
            f'Loading {lookback_key.upper()} metrics versus {benchmark_symbol}...',
            status='info',
        )

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                if client is not None:
                    payload = client.fetch_portfolio_analytics(
                        tickers,
                        shares_map,
                        prices_map=prices_map,
                        benchmark_symbol=benchmark_symbol,
                        lookback_key=lookback_key,
                        cash_amount=cash_amount,
                    )
                else:
                    payload = PortfolioAnalyticsWorker(
                        tickers,
                        shares_map,
                        prices_map=prices_map,
                        benchmark_symbol=benchmark_symbol,
                        lookback_key=lookback_key,
                        cash_amount=cash_amount,
                    ).fetch()
            except Exception as exc:
                logger.warning('Embedded data service analytics request failed; falling back to direct worker: %s', exc)
                if hasattr(self, '_record_data_health_fallback'):
                    self._record_data_health_fallback('Portfolio analytics', exc, symbols=tickers)
                payload = PortfolioAnalyticsWorker(
                    tickers,
                    shares_map,
                    prices_map=prices_map,
                    benchmark_symbol=benchmark_symbol,
                    lookback_key=lookback_key,
                    cash_amount=cash_amount,
                ).fetch()
            self._invoke_main.emit(
                lambda result=payload, key=cache_key, pid=str(self.active_portfolio_id): self._on_portfolio_analytics_ready(key, pid, result)
            )

        threading.Thread(target=_run, daemon=True).start()

    def _on_portfolio_analytics_ready(self, cache_key: Any, portfolio_id: Any, payload: Any) -> None:
        """Handle one portfolio-analytics worker result becoming ready."""
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Portfolio analytics', payload, symbols=self._p4_active_tickers())
        self._portfolio_analytics_fetching[cache_key] = False
        self._portfolio_analytics_cache[cache_key] = payload
        current_key = self._p4_portfolio_analytics_cache_key(
            portfolio_id=self.active_portfolio_id,
            benchmark_symbol=getattr(self, 'p4_metrics_benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']),
            lookback_key=getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']),
        )
        if (
            self._p4_metrics_tab_visible()
            and str(portfolio_id) == str(self.active_portfolio_id)
            and cache_key == current_key
        ):
            self._p4_apply_portfolio_analytics_payload(payload)

    def _p4_refresh_portfolio_metrics_view(self, *, force: bool=False) -> None:
        """Refresh the visible metrics tab from cache or by launching a worker."""
        if not self._p4_metrics_tab_visible():
            return
        self._fetch_portfolio_analytics(force=force)

    def _p4_on_metrics_benchmark_edited(self) -> None:
        """Persist a benchmark change and refresh the metrics tab."""
        if not hasattr(self, 'p4_metrics_benchmark_input'):
            return
        benchmark_symbol = self._p4_normalize_metrics_benchmark_symbol(self.p4_metrics_benchmark_input.text())
        changed = benchmark_symbol != getattr(self, 'p4_metrics_benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
        self.p4_metrics_benchmark_symbol = benchmark_symbol
        self.p4_metrics_benchmark_input.setText(benchmark_symbol)
        self._p4_persist_portfolio_metrics_settings()
        if changed:
            self._p4_invalidate_portfolio_analytics_cache(self.active_portfolio_id)
        self._p4_refresh_portfolio_metrics_view(force=changed)

    def _p4_on_metrics_lookback_changed(self, index: int) -> None:
        """Persist a lookback change and refresh the metrics tab."""
        if not hasattr(self, 'p4_metrics_lookback_combo') or index < 0:
            return
        lookback_key = str(self.p4_metrics_lookback_combo.currentData() or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']).strip().lower()
        changed = lookback_key != getattr(self, 'p4_metrics_lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
        self.p4_metrics_lookback_key = lookback_key
        self._p4_persist_portfolio_metrics_settings()
        if changed:
            self._p4_invalidate_portfolio_analytics_cache(self.active_portfolio_id)
        self._p4_refresh_portfolio_metrics_view(force=changed)

    def _p4_on_metrics_refresh_clicked(self) -> None:
        """Force a fresh fetch for the current benchmark and lookback window."""
        self._p4_invalidate_portfolio_analytics_cache(self.active_portfolio_id)
        self._p4_refresh_portfolio_metrics_view(force=True)

    def _p4_export_for_llm(self) -> None:
        """Export the active portfolio's stock and options data to clipboard for LLM analysis."""
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        tickers = self._p4_active_tickers()
        options_data = getattr(self, 'active_options_data', getattr(self, 'options_data', []))
        cash_balance = self._p4_active_cash_balance()
        metrics_map, total_mv = self._p4_build_tracker_metrics_map(portfolio)
        active_index = self._p4_get_active_portfolio_index()
        portfolio_name = self._p4_portfolio_name(active_index)
        lines = []
        lines.append(f'=== PORTFOLIO EXPORT: {portfolio_name} ===')
        lines.append('')
        lines.append('--- STOCK POSITIONS ---')
        lines.append('')
        if not tickers:
            lines.append('(no stock positions)')
            lines.append('')
        else:
            sorted_tickers = sorted(tickers, key=lambda t: metrics_map.get(t, {}).get('market_value', 0), reverse=True)
            for ticker in sorted_tickers:
                m = metrics_map.get(ticker, {})
                shares = m.get('shares', 0)
                avg_price = m.get('avg_price', 0)
                price = m.get('price', 0)
                change = m.get('change', 0)
                cost = m.get('cost', 0)
                mv = m.get('market_value', 0)
                weight = m.get('weight', 0)
                gain = m.get('dollar_gain', 0)
                growth = m.get('growth', 0)
                mc = self._mktcap_cache.get(str(ticker or '').strip().upper())
                mc_str = self._format_market_cap(mc)
                sign = '+' if change >= 0 else ''
                gain_sign = '+' if gain >= 0 else ''
                growth_sign = '+' if growth >= 0 else ''
                lines.append(f'{ticker}')
                lines.append(f'  Shares: {shares:g} | Avg Price: ${avg_price:.2f} | Cost Basis: ${cost:,.2f}')
                lines.append(f'  Current Price: ${price:.2f} | Day Change: {sign}{change:.2f}%')
                lines.append(f'  Market Value: ${mv:,.2f} | Weight: {weight:.1f}%')
                lines.append(f'  P&L: {gain_sign}${gain:,.2f} | Growth: {growth_sign}{growth:.1f}%')
                lines.append(f'  Market Cap: {mc_str}')
                lines.append('')
        lines.append('--- BROKERAGE CASH ---')
        lines.append('')
        lines.append(f'Cash Balance: ${cash_balance:,.2f}')
        lines.append(f'Total Portfolio Value: ${total_mv:,.2f}')
        lines.append('')
        lines.append('--- OPTIONS POSITIONS ---')
        lines.append('')
        if not options_data:
            lines.append('(no options positions)')
            lines.append('')
        else:
            for pos in options_data:
                ticker = pos.get('ticker', '?')
                strategy = pos.get('strategy', 'Calls')
                expiry = pos.get('expiry', 'N/A')
                strike = pos.get('strike', 0)
                contracts = pos.get('contracts', 1)
                premium = pos.get('premium', 0)
                current = pos.get('current_price', 0)
                iv = pos.get('iv', 0)
                volume = pos.get('volume', pos.get('vol', 0))
                open_interest = pos.get('open_interest', pos.get('openInterest', 0))
                try:
                    volume = float(volume)
                except (TypeError, ValueError):
                    volume = 0.0
                try:
                    open_interest = float(open_interest)
                except (TypeError, ValueError):
                    open_interest = 0.0
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                if is_seller:
                    pl = (premium - current) * contracts * 100
                else:
                    pl = (current - premium) * contracts * 100
                pl_sign = '+' if pl >= 0 else ''
                lines.append(f'{ticker} | {strategy} | Strike: ${strike:.2f} | Expiry: {expiry}')
                lines.append(f'  Contracts: {contracts} | Premium: ${premium:.2f} | Current: ${current:.2f}')
                lines.append(f'  Vol: {volume:,.0f} | OI: {open_interest:,.0f} | IV: {iv * 100:.1f}%')
                lines.append(f'  P&L: {pl_sign}${pl:,.2f}')
                lines.append('')
        text = '\n'.join(lines)
        total_items = len(tickers) + len(options_data) + (1 if cash_balance > 0 else 0)
        QApplication.clipboard().setText(text)
        self.set_status_text(self.status_bar, f'Exported {portfolio_name} ({total_items} positions) to clipboard', status='positive')

    def _get_return_timeframe_config(self, timeframe_key: Any) -> Any:
        """Return fetch/render config for the requested timeframe."""
        current_year = datetime.date.today().year
        configs = {
            'dip_finder': {'period': '1mo', 'interval': '1d', 'sort_reverse': True},
            '1mo': {'period': '1mo', 'interval': '1d', 'sort_reverse': True},
            'ytd': {'start': f'{current_year}-01-01', 'interval': '1d', 'sort_reverse': True},
            '1y': {'period': '1y', 'interval': '1d', 'sort_reverse': True},
        }
        return configs.get(timeframe_key, configs['dip_finder'])

    def _on_tracker_cell_changed(self, item: Any) -> None:
        """Handle tracker cell changed."""
        col = item.column()
        if col not in (P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_AVG_PRICE):
            return
        row = item.row()
        sym_item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
        if not sym_item:
            return
        ticker = sym_item.text()
        try:
            val = float(item.text().replace('$', '').replace(',', ''))
        except ValueError:
            return
        tracker_data = self._p4_active_tracker_data()
        tracker_entry = tracker_data.setdefault(ticker, {})
        tracker_entry['shares' if col == P4_PORTFOLIO_COL_SHARES else 'avg_price'] = val
        self._persist_all_portfolios()
        if self.last_data:
            self._recalc_tracker_row(row, ticker, self.last_data.get('portfolio', {}))
        if col == P4_PORTFOLIO_COL_SHARES:
            self._p4_invalidate_momentum_cache()
            self._p4_invalidate_portfolio_analytics_cache()
            self._p4_schedule_momentum_refresh()
            self._p4_schedule_portfolio_metrics_refresh()

    def _p4_schedule_momentum_refresh(self) -> None:
        """Debounce expensive momentum refreshes while tracker cells are being edited."""
        timer = getattr(self, '_p4_momentum_refresh_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._p4_flush_momentum_refresh)
            self._p4_momentum_refresh_timer = timer
        timer.start(_P4_MOMENTUM_REFRESH_DEBOUNCE_MS)

    def _p4_flush_momentum_refresh(self) -> None:
        """Run the deferred momentum refresh after tracker edits settle."""
        self._p4_refresh_active_momentum_view()

    def _p4_build_tracker_metrics_map(self, portfolio: Any) -> Any:
        """Precompute derived tracker metrics for the active portfolio."""
        tracker_data = self._p4_active_tracker_data()
        tickers = self._p4_active_tickers()
        metrics_map = {}
        stock_market_value = 0.0
        for ticker in tickers:
            tracker_entry = tracker_data.get(ticker, {})
            shares = tracker_entry.get('shares', 0)
            avg_price = tracker_entry.get('avg_price', 0)
            price = portfolio.get(ticker, {}).get('price', 0)
            change = portfolio.get(ticker, {}).get('change', 0)
            cost = shares * avg_price
            market_value = shares * price
            dollar_gain = market_value - cost
            metrics_map[ticker] = {
                'shares': shares,
                'avg_price': avg_price,
                'price': price,
                'change': change,
                'cost': cost,
                'market_value': market_value,
                'dollar_gain': dollar_gain,
            }
            stock_market_value += market_value
        cash_balance = self._p4_active_cash_balance()
        total_market_value = stock_market_value + cash_balance
        for item in metrics_map.values():
            cost = item['cost']
            market_value = item['market_value']
            item['weight'] = market_value / total_market_value * 100 if total_market_value else 0
            item['growth'] = item['dollar_gain'] / cost * 100 if cost else 0
        return metrics_map, total_market_value

    def _recalc_tracker_row(self, row: Any, ticker: Any, portfolio: Any) -> None:
        """Handle recalc tracker row."""
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        metrics = metrics_map.get(ticker)
        if metrics is None:
            return
        sorting_enabled = self.p4_table.isSortingEnabled()
        self.p4_table.blockSignals(True)
        self.p4_table.setSortingEnabled(False)
        try:
            self._set_tracker_row(
                row,
                ticker,
                metrics['shares'],
                metrics['avg_price'],
                metrics['price'],
                metrics['change'],
                metrics['cost'],
                metrics['market_value'],
                metrics['weight'],
                metrics['dollar_gain'],
                metrics['growth'],
            )
        finally:
            self.p4_table.setSortingEnabled(sorting_enabled)
            self.p4_table.blockSignals(False)
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        weights = {symbol: item['weight'] for symbol, item in metrics_map.items()}
        cash_balance = self._p4_active_cash_balance()
        if cash_balance > 0.0 and total_market_value > 0.0:
            weights['CASH'] = cash_balance / total_market_value * 100.0
        self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)

    def _p4_ensure_tracker_item(self, row: Any, col: Any, flags: Any) -> Any:
        """Return an existing tracker cell item or create it once."""
        item = self.p4_table.item(row, col)
        if item is None:
            item = _P4NumericTableWidgetItem('') if col in _P4_TRACKER_NUMERIC_COLUMNS else QTableWidgetItem('')
            self.p4_table.setItem(row, col, item)
        item.setFlags(flags)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _p4_clear_mktcap_item(self, row: Any) -> None:
        """Clear stale market-cap text when a reused row has no cached value yet."""
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        item = self._p4_ensure_tracker_item(row, P4_PORTFOLIO_COL_MARKET_CAP, ro_flags)
        item.setText('--')
        item.setData(_P4_NUMERIC_SORT_ROLE, _P4_MISSING_NUMERIC_SORT_VALUE)
        item.setForeground(self.theme_qcolor('text_muted'))

    def _set_tracker_row(
        self,
        row: Any,
        ticker: Any,
        shares: Any,
        avg_price: Any,
        price: Any,
        change: Any,
        cost: Any,
        mkt_val: Any,
        weight: Any,
        dollar_gain: Any,
        growth: Any,
    ) -> Any:
        """Handle set tracker row."""
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        ed_flags = ro_flags | Qt.ItemFlag.ItemIsEditable
        default_text_color = self.theme_qcolor('text_primary')
        gain_color = self.theme_qcolor('accent_positive' if dollar_gain >= 0 else 'accent_negative')
        change_color = self.theme_qcolor('accent_positive' if change >= 0 else 'accent_negative')

        def _update_item(col: Any, text: Any, flags: Any = ro_flags, color: Any = None, sort_value: Any = None) -> None:
            item = self._p4_ensure_tracker_item(row, col, flags)
            item.setText(text)
            if col in _P4_TRACKER_NUMERIC_COLUMNS:
                item.setData(_P4_NUMERIC_SORT_ROLE, sort_value if sort_value is not None else _P4_MISSING_NUMERIC_SORT_VALUE)
            item.setForeground(color if color is not None else default_text_color)

        _update_item(P4_PORTFOLIO_COL_SYMBOL, ticker)
        _update_item(P4_PORTFOLIO_COL_SHARES, f'{shares:g}', ed_flags, sort_value=shares)
        _update_item(P4_PORTFOLIO_COL_AVG_PRICE, f'{avg_price:.2f}', ed_flags, sort_value=avg_price)
        _update_item(P4_PORTFOLIO_COL_COST, f'${cost:,.2f}', sort_value=cost)
        _update_item(P4_PORTFOLIO_COL_PRICE, f'${price:.2f}', sort_value=price)
        sign = '+' if change >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_DAY_CHANGE, f'{sign}{change:.2f}%', color=change_color, sort_value=change)
        _update_item(P4_PORTFOLIO_COL_MARKET_VALUE, f'${mkt_val:,.2f}', sort_value=mkt_val)
        _update_item(P4_PORTFOLIO_COL_WEIGHT, f'{weight:.1f}%', sort_value=weight)
        gain_sign = '+' if dollar_gain >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_DOLLAR_GAIN, f'{gain_sign}${dollar_gain:,.2f}', color=gain_color, sort_value=dollar_gain)
        growth_sign = '+' if growth >= 0 else ''
        _update_item(P4_PORTFOLIO_COL_GROWTH, f'{growth_sign}{growth:.1f}%', color=gain_color, sort_value=growth)

    def _p4_remove_active_ticker(self, ticker: Any) -> None:
        """Remove a ticker from the currently selected page-4 portfolio."""
        clean_ticker = str(ticker or '').strip().upper()
        if not clean_ticker:
            return
        tickers = self._p4_active_tickers()
        matched_ticker = None
        for saved_ticker in list(tickers):
            if str(saved_ticker or '').strip().upper() == clean_ticker:
                matched_ticker = saved_ticker
                break
        if matched_ticker is None:
            return
        tickers.remove(matched_ticker)
        tracker_data = self._p4_active_tracker_data()
        tracker_data.pop(matched_ticker, None)
        tracker_data.pop(clean_ticker, None)
        self._p4_invalidate_returns_cache()
        self._p4_invalidate_momentum_cache()
        self._p4_invalidate_portfolio_analytics_cache()
        self._persist_all_portfolios()
        if (
            (getattr(self, '_dashboard_showing_all', False) or self.active_portfolio_id == self.main_portfolio_id)
            and hasattr(self, '_dashboard_apply_local_portfolio_membership')
        ):
            self._dashboard_apply_local_portfolio_membership(self.last_data)
        if self.last_data and self.active_portfolio_id == self.main_portfolio_id and 'portfolio' in self.last_data:
            self.last_data['portfolio'].pop(matched_ticker, None)
            self.last_data['portfolio'].pop(clean_ticker, None)
        if self.last_data:
            self.update_page4(self.last_data)
        else:
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)
            self._p4_update_stock_positions_label()
            if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
                self._p4_refresh_portfolio_heatmap_view(reset_view=True)
            self._p4_refresh_active_momentum_view()
            if self._p4_metrics_tab_visible():
                self._p4_refresh_portfolio_metrics_view(force=True)

    def _update_returns_chart(self, timeframe_key: Any, results: Any) -> None:
        """Handle update returns chart."""
        pw = self.p4_returns_charts.get(timeframe_key)
        if pw is None:
            return
        pw.clear()
        config = self._get_return_timeframe_config(timeframe_key)
        tickers = sorted(
            [ticker for ticker in self._p4_active_tickers() if ticker in results],
            key=lambda ticker: results[ticker],
            reverse=config.get('sort_reverse', True),
        )
        if not tickers:
            return
        values = [results[ticker] for ticker in tickers]
        colors = [self.theme_color('accent_positive' if value >= 0 else 'accent_negative') for value in values]
        for xi, (value, color) in enumerate(zip(values, colors)):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=pg.mkBrush(color), pen=pg.mkPen(color)))
            sign = '+' if value >= 0 else ''
            label = pg.TextItem(text=f'{sign}{value:.1f}%', color=color, anchor=(0.5, 1.0 if value >= 0 else 0.0))
            label.setPos(xi, value)
            pw.addItem(label)
        pw.addItem(pg.InfiniteLine(pos=0, angle=0, pen=self.theme_pen('chart_reference', width=1)))
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        max_v = max((abs(value) for value in values)) if values else 1
        pw.setYRange(-max_v * 1.6, max_v * 1.6)
        pw.setXRange(-0.6, len(tickers) - 0.4)

    def _update_weight_chart(self, weights: Any) -> None:
        """Render portfolio weights as a descending bar chart."""
        pw = self.p4_weight_chart
        pw.clear()
        tickers = [ticker for ticker, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True) if weight > 0]
        if not tickers:
            pw.getPlotItem().hideAxis('bottom')
            pw.getPlotItem().hideAxis('left')
            return
        values = [weights[ticker] for ticker in tickers]
        colors = list(self.theme_pie_palette())
        brushes = [pg.mkBrush(colors[i % len(colors)]) for i in range(len(tickers))]
        pens = [pg.mkPen(colors[i % len(colors)]) for i in range(len(tickers))]
        max_value = max(values) if values else 1
        label_offset = max(max_value * 0.04, 0.6)
        for xi, (ticker, value, brush, pen) in enumerate(zip(tickers, values, brushes, pens)):
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=brush, pen=pen))
            label = pg.TextItem(text=f'{value:.1f}%', color=self.theme_color('text_primary'), anchor=(0.5, 1.0))
            label.setPos(xi, value + label_offset)
            pw.addItem(label)
        ax = pw.getAxis('bottom')
        ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
        ax.setStyle(tickFont=self.font())
        pw.showAxis('bottom')
        pw.showAxis('left')
        pw.setYRange(0, max_value + label_offset + max(max_value * 0.15, 0.5))
        pw.setXRange(-0.6, len(tickers) - 0.4)

    def _p4_empty_momentum_payload(self, reason: str, *, included: Any=None, excluded: Any=None) -> dict[str, Any]:
        """Build a normalized empty momentum payload."""
        return {
            'dates': [],
            'returns': [],
            'start_value': None,
            'end_value': None,
            'included_tickers': list(included or []),
            'excluded_tickers': list(excluded or []),
            'start_date': None,
            'reason': str(reason or '').strip(),
        }

    def _p4_momentum_ema_period(self, timeframe_key: Any) -> int:
        """Return the EMA period used for one momentum timeframe."""
        return {
            '1mo': 10,
            'ytd': 20,
            '1y': 50,
        }.get(str(timeframe_key or '').strip().lower(), 20)

    def _p4_set_momentum_summary(self, timeframe_key: Any, payload: Any, *, ema_last: Any=None) -> None:
        """Update the momentum summary label for the active timeframe."""
        if not hasattr(self, 'p4_momentum_summary_label'):
            return
        if not isinstance(payload, dict):
            payload = self._p4_empty_momentum_payload('No momentum data available')
        reason = str(payload.get('reason', '') or '').strip()
        returns = payload.get('returns', [])
        included = list(payload.get('included_tickers', []) or [])
        excluded = list(payload.get('excluded_tickers', []) or [])
        if reason or not returns:
            if not reason:
                metadata_text, metadata_status = describe_market_data_status(payload, 'No momentum data available')
                reason = metadata_text if metadata_status != 'positive' else ''
            self.p4_momentum_summary_label.setText(reason or 'No momentum data available')
            return
        total_return = float(returns[-1]) if returns else 0.0
        sign = '+' if total_return >= 0 else ''
        start_date = str(payload.get('start_date') or '--')
        parts = [
            f'Since {start_date}',
            f'Portfolio {sign}{total_return:.1f}%',
            f'{len(included)} holding{"s" if len(included) != 1 else ""}',
        ]
        if ema_last is not None:
            relation = 'Above' if total_return >= float(ema_last) else 'Below'
            parts.append(f'{relation} {self._p4_momentum_ema_period(timeframe_key)}-day EMA')
        if excluded:
            parts.append(f'{len(excluded)} excluded')
        self.p4_momentum_summary_label.setText(' | '.join(parts))

    def _update_momentum_chart(self, timeframe_key: Any, payload: Any) -> None:
        """Render one timeframe of portfolio momentum."""
        pw = getattr(self, 'p4_momentum_charts', {}).get(timeframe_key)
        axis = getattr(self, 'p4_momentum_axes', {}).get(timeframe_key)
        if pw is None:
            return
        pw.clear()
        if axis is not None:
            axis.set_dates([], '1d')
        if not isinstance(payload, dict):
            payload = self._p4_empty_momentum_payload('No momentum data available')
        dates = list(payload.get('dates', []) or [])
        returns = [float(value) for value in list(payload.get('returns', []) or [])]
        if len(dates) != len(returns) or len(returns) < 2:
            self._p4_set_momentum_summary(timeframe_key, payload)
            return
        xs = list(range(len(dates)))
        if axis is not None:
            axis.set_dates(dates, '1d')
        returns_series = pd.Series(returns, dtype='float64')
        ema_period = self._p4_momentum_ema_period(timeframe_key)
        ema_values = returns_series.ewm(span=ema_period, adjust=False).mean().tolist()
        line_color = self.theme_color('accent')
        pw.plot(xs, returns, pen=pg.mkPen(line_color, width=2), antialias=True)
        pw.plot(
            xs,
            ema_values,
            pen=pg.mkPen(self.theme_color('warning'), width=2, style=Qt.PenStyle.DashLine),
            antialias=True,
        )
        pw.addItem(
            pg.InfiniteLine(
                pos=0,
                angle=0,
                pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine),
            )
        )
        last_value = float(returns[-1])
        last_color = self.theme_color('accent_positive' if last_value >= 0 else 'accent_negative')
        last_sign = '+' if last_value >= 0 else ''
        anchor = (1.0, 0.0 if last_value >= 0 else 1.0)
        last_label = pg.TextItem(text=f'{last_sign}{last_value:.1f}%', color=last_color, anchor=anchor)
        last_label.setPos(xs[-1], last_value)
        pw.addItem(last_label)
        plot_item = pw.getPlotItem()
        plot_item.hideAxis('left')
        plot_item.showAxis('right')
        plot_item.showAxis('bottom')
        try:
            plot_item.getAxis('right').setLabel('Return %')
        except Exception:
            pass
        min_value = min(min(returns), min(ema_values), 0.0)
        max_value = max(max(returns), max(ema_values), 0.0)
        y_pad = max((max_value - min_value) * 0.15, 1.0)
        pw.setYRange(min_value - y_pad, max_value + y_pad)
        pw.setXRange(-0.4, len(xs) - 0.6)
        self._p4_set_momentum_summary(timeframe_key, payload, ema_last=ema_values[-1] if ema_values else None)

    def _p4_active_momentum_shares_map(self) -> dict[str, float]:
        """Return normalized current-share counts for the active portfolio."""
        shares_map = {}
        for ticker, tracker_entry in (self._p4_active_tracker_data() or {}).items():
            symbol = str(ticker or '').strip().upper()
            if not symbol:
                continue
            try:
                shares_map[symbol] = float((tracker_entry or {}).get('shares', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                shares_map[symbol] = 0.0
        return shares_map

    def _fetch_momentum_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch portfolio momentum for a specific timeframe."""
        portfolio_id = str(self.active_portfolio_id)
        cache_key = self._p4_momentum_cache_key(timeframe_key, portfolio_id)
        if self._momentum_metrics_fetching.get(cache_key, False):
            return
        tickers = list(self._p4_active_tickers())
        shares_map = self._p4_active_momentum_shares_map()
        cash_amount = self._p4_active_cash_balance()
        if not tickers and cash_amount <= 0.0:
            payload = self._p4_empty_momentum_payload('No portfolio holdings available')
            self._momentum_metrics_cache[cache_key] = payload
            self._momentum_metrics_fetching[cache_key] = False
            if portfolio_id == str(self.active_portfolio_id) and timeframe_key == self._active_momentum_timeframe:
                self._update_momentum_chart(timeframe_key, payload)
            return
        config = self._get_return_timeframe_config(timeframe_key)
        self._momentum_metrics_fetching[cache_key] = True

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                if client is not None:
                    payload = client.fetch_portfolio_momentum(
                        tickers,
                        shares_map,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                        cash_amount=cash_amount,
                    )
                else:
                    payload = PortfolioMomentumWorker(
                        tickers,
                        shares_map,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                        cash_amount=cash_amount,
                    ).fetch()
            except Exception as exc:
                logger.warning('Embedded data service momentum request failed; falling back to direct worker: %s', exc)
                if hasattr(self, '_record_data_health_fallback'):
                    self._record_data_health_fallback('Portfolio momentum', exc, symbols=tickers)
                payload = PortfolioMomentumWorker(
                    tickers,
                    shares_map,
                    period=config.get('period', '1mo'),
                    interval=config.get('interval', '1d'),
                    start=config.get('start'),
                    cash_amount=cash_amount,
                ).fetch()
            self._invoke_main.emit(
                lambda result=payload, key=timeframe_key, pid=portfolio_id: self._on_momentum_ready(key, pid, result)
            )

        threading.Thread(target=_run, daemon=True).start()

    def _on_momentum_ready(self, timeframe_key: Any, portfolio_id: Any, payload: Any) -> None:
        """Handle portfolio momentum data becoming ready."""
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Portfolio momentum', payload, symbols=self._p4_active_tickers())
        cache_key = self._p4_momentum_cache_key(timeframe_key, portfolio_id)
        self._momentum_metrics_fetching[cache_key] = False
        self._momentum_metrics_cache[cache_key] = payload
        if str(portfolio_id) == str(self.active_portfolio_id) and timeframe_key == self._active_momentum_timeframe:
            self._update_momentum_chart(timeframe_key, payload)

    def _on_momentum_timeframe_changed(self, index: int) -> None:
        """Handle momentum timeframe tab changes."""
        if index < 0 or index >= len(getattr(self, 'p4_momentum_timeframes', ())):
            return
        timeframe_key = self.p4_momentum_timeframes[index][0]
        self._active_momentum_timeframe = timeframe_key
        cache_key = self._p4_momentum_cache_key(timeframe_key)
        if cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(timeframe_key, self._momentum_metrics_cache.get(cache_key, {}))
            return
        self._fetch_momentum_for_timeframe(timeframe_key)

    def _p4_refresh_active_momentum_view(self) -> None:
        """Refresh the visible momentum chart from cache or fetch it."""
        timeframe_key = str(getattr(self, '_active_momentum_timeframe', '1mo') or '1mo')
        cache_key = self._p4_momentum_cache_key(timeframe_key)
        if cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(timeframe_key, self._momentum_metrics_cache.get(cache_key, {}))
            return
        self._fetch_momentum_for_timeframe(timeframe_key)

    def _launch_worker(self, worker_obj: Any, finished_slot: Any, flag_attr: Any) -> Any:
        """Guard-and-launch helper for background workers."""
        if getattr(self, flag_attr, False):
            return False
        setattr(self, flag_attr, True)
        worker_obj.finished.connect(finished_slot)
        threading.Thread(target=worker_obj.run, daemon=True).start()
        return True

    def _fetch_returns_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch returns for a specific timeframe."""
        portfolio_id = str(self.active_portfolio_id)
        cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        if self._return_metrics_fetching.get(cache_key, False):
            return
        tickers = list(self._p4_active_tickers())
        if not tickers:
            self._return_metrics_cache[cache_key] = {}
            self._return_metrics_fetching[cache_key] = False
            if portfolio_id == str(self.active_portfolio_id) and timeframe_key == self._active_return_timeframe:
                self._update_returns_chart(timeframe_key, {})
            return
        config = self._get_return_timeframe_config(timeframe_key)
        self._return_metrics_fetching[cache_key] = True

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                if client is not None:
                    results = client.fetch_month_returns(
                        tickers,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                    )
                else:
                    results = MonthReturnWorker(
                        tickers,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                    ).fetch()
            except Exception as exc:
                logger.warning('Embedded data service returns request failed; falling back to direct worker: %s', exc)
                if hasattr(self, '_record_data_health_fallback'):
                    self._record_data_health_fallback('Portfolio returns', exc, symbols=tickers)
                results = MonthReturnWorker(
                    tickers,
                    period=config.get('period', '1mo'),
                    interval=config.get('interval', '1d'),
                    start=config.get('start'),
                ).fetch()
            self._invoke_main.emit(
                lambda payload=results, key=timeframe_key, pid=portfolio_id: self._on_returns_ready(key, pid, payload)
            )

        threading.Thread(target=_run, daemon=True).start()

    def _on_returns_ready(self, timeframe_key: Any, portfolio_id: Any, results: Any) -> None:
        """Handle return metrics ready."""
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Portfolio returns', results, symbols=self._p4_active_tickers())
        results = strip_market_data_keys(results) if isinstance(results, dict) else results
        cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        self._return_metrics_fetching[cache_key] = False
        self._return_metrics_cache[cache_key] = results
        if str(portfolio_id) == str(self.active_portfolio_id) and timeframe_key == self._active_return_timeframe:
            self._update_returns_chart(timeframe_key, results)

    def _on_returns_timeframe_changed(self, index: int) -> None:
        """Handle return timeframe tab changes."""
        if index < 0 or index >= len(self.p4_return_timeframes):
            return
        timeframe_key = self.p4_return_timeframes[index][0]
        self._active_return_timeframe = timeframe_key
        cache_key = self._p4_returns_cache_key(timeframe_key)
        if cache_key in self._return_metrics_cache:
            self._update_returns_chart(timeframe_key, self._return_metrics_cache.get(cache_key, {}))
            return
        self._fetch_returns_for_timeframe(timeframe_key)

    def _format_market_cap(self, mc: Any) -> Any:
        """Handle format market cap."""
        value = self._p4_market_cap_value(mc)
        if value is None:
            return '--'
        if value >= 200000000000:
            bucket = 'Mega'
        elif value >= 10000000000:
            bucket = 'Large'
        elif value >= 2000000000:
            bucket = 'Mid'
        elif value >= 300000000:
            bucket = 'Small'
        else:
            bucket = 'Micro'
        return f'{bucket} ${self._p4_format_market_cap_value(value)}'

    def _p4_market_cap_value(self, mc: Any) -> Any:
        """Return a positive finite market-cap number or None."""
        if mc is None:
            return None
        try:
            value = float(str(mc).replace(',', '').strip())
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return value

    def _p4_format_market_cap_value(self, value: float) -> str:
        """Format a market-cap value with a compact suffix."""
        if value >= 1000000000000.0:
            return f'{value / 1000000000000.0:.2f}T'
        if value >= 1000000000.0:
            return f'{value / 1000000000.0:.2f}B'
        if value >= 1000000.0:
            return f'{value / 1000000.0:.2f}M'
        if value >= 1000.0:
            return f'{value / 1000.0:.1f}K'
        return f'{value:.2f}'

    def _mktcap_color(self, mc: Any) -> Any:
        """Handle mktcap color."""
        value = self._p4_market_cap_value(mc)
        if value is None:
            return self.theme_color('text_muted')
        if value >= 200000000000:
            return self.theme_color('warning')
        if value >= 10000000000:
            return self.theme_series_color(0)
        if value >= 2000000000:
            return self.theme_color('accent_positive')
        if value >= 300000000:
            return self.theme_series_color(3)
        return self.theme_color('accent_negative')

    def _p4_mktcap_cache_ttl_seconds(self) -> float:
        """Return the reuse window for cached market-cap values."""
        return float(getattr(self, '_mktcap_cache_ttl_seconds', _P4_MKTCAP_CACHE_TTL_SECONDS))

    def _p4_mktcap_cache_now(self) -> float:
        """Return the current UTC timestamp for market-cap freshness checks."""
        return datetime.datetime.now(datetime.timezone.utc).timestamp()

    def _p4_has_fresh_mktcap(self, ticker: Any) -> bool:
        """Return whether one cached market-cap entry is still fresh."""
        symbol = str(ticker or '').strip().upper()
        if not symbol:
            return False
        cache_ts = getattr(self, '_mktcap_cache_ts', {})
        fetched_at = cache_ts.get(symbol)
        if fetched_at is None:
            return False
        return (self._p4_mktcap_cache_now() - float(fetched_at)) < self._p4_mktcap_cache_ttl_seconds()

    def _p4_get_mktcap_refresh_candidates(self, tickers: Any = None) -> list[str]:
        """Return missing or stale tickers that still need a market-cap refresh."""
        candidates = []
        inflight = set(getattr(self, '_mktcap_inflight_tickers', set()))
        queued = set(getattr(self, '_mktcap_queued_tickers', set()))
        for ticker in tickers if tickers is not None else self._p4_active_tickers():
            symbol = str(ticker or '').strip().upper()
            if not symbol or symbol in inflight or symbol in queued:
                continue
            if (symbol not in self._mktcap_cache) or (not self._p4_has_fresh_mktcap(symbol)):
                candidates.append(symbol)
        return candidates

    def _p4_start_market_cap_fetch(self, tickers: Any) -> bool:
        """Launch one page-4 market-cap worker for the provided tickers."""
        symbols = [str(ticker or '').strip().upper() for ticker in tickers]
        symbols = [symbol for symbol in symbols if symbol]
        if not symbols:
            return False
        self._mktcap_fetching = True
        self._mktcap_inflight_tickers = set(symbols)

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                results = client.fetch_market_caps(symbols) if client is not None else MarketCapWorker(symbols).fetch()
            except Exception as exc:
                logger.warning('Embedded data service market-cap request failed; falling back to direct worker: %s', exc)
                if hasattr(self, '_record_data_health_fallback'):
                    self._record_data_health_fallback('Market caps', exc, symbols=symbols)
                results = MarketCapWorker(symbols).fetch()
            self._invoke_main.emit(lambda payload=results: self._on_market_caps_ready(payload))

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _update_mktcap_item(self, row: Any, ticker: Any, mc: Any) -> None:
        """Handle update mktcap item."""
        text = self._format_market_cap(mc)
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self.p4_table.blockSignals(True)
        item = self._p4_ensure_tracker_item(row, P4_PORTFOLIO_COL_MARKET_CAP, ro_flags)
        item.setText(text)
        try:
            sort_value = float(mc)
        except (TypeError, ValueError):
            sort_value = _P4_MISSING_NUMERIC_SORT_VALUE
        item.setData(_P4_NUMERIC_SORT_ROLE, sort_value)
        self.p4_table.blockSignals(False)
        item.setForeground(QColor(self._mktcap_color(mc)))

    def _fetch_market_caps(self, tickers: Any = None) -> None:
        """Fetch market caps."""
        needed = self._p4_get_mktcap_refresh_candidates(tickers)
        if not needed:
            return
        if getattr(self, '_mktcap_fetching', False):
            queued = set(getattr(self, '_mktcap_queued_tickers', set()))
            queued.update(needed)
            self._mktcap_queued_tickers = queued
            return
        self._p4_start_market_cap_fetch(needed)

    def _on_market_caps_ready(self, results: Any) -> None:
        """Handle market caps ready."""
        self._mktcap_fetching = False
        request_tickers = set(getattr(self, '_mktcap_inflight_tickers', set()))
        self._mktcap_inflight_tickers = set()
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Market caps', results, symbols=request_tickers)
        results = strip_market_data_keys(results) if isinstance(results, dict) else results
        normalized_results = {}
        if isinstance(results, dict) and results:
            fetched_at = self._p4_mktcap_cache_now()
            for ticker, mc in results.items():
                symbol = str(ticker or '').strip().upper()
                if not symbol:
                    continue
                normalized_results[symbol] = mc
                self._mktcap_cache[symbol] = mc
                self._mktcap_cache_ts[symbol] = fetched_at
        sorting_enabled = self.p4_table.isSortingEnabled()
        self.p4_table.setSortingEnabled(False)
        try:
            for row in range(self.p4_table.rowCount()):
                item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
                symbol = str(item.text() if item else '').strip().upper()
                if symbol and symbol in normalized_results:
                    self._update_mktcap_item(row, symbol, normalized_results[symbol])
        finally:
            self.p4_table.setSortingEnabled(sorting_enabled)
        queued = list(getattr(self, '_mktcap_queued_tickers', set()))
        self._mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if str(ticker or '').strip().upper() not in request_tickers]
            self._fetch_market_caps(remaining)

    def update_page4(self, data: Any) -> None:
        """Update page4."""
        portfolio = data.get('portfolio', {})
        tickers = self._p4_active_tickers()
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        weights = {}
        sorting_enabled = self.p4_table.isSortingEnabled()
        self.p4_table.blockSignals(True)
        self.p4_table.setSortingEnabled(False)
        self.p4_table.setUpdatesEnabled(False)
        try:
            self.p4_table.setRowCount(len(tickers))
            sorted_tickers = sorted(
                tickers,
                key=lambda ticker: metrics_map.get(ticker, {}).get('market_value', 0),
                reverse=True,
            )
            for i, ticker in enumerate(sorted_tickers):
                metrics = metrics_map.get(ticker, {})
                weights[ticker] = metrics.get('weight', 0)
                self._set_tracker_row(
                    i,
                    ticker,
                    metrics.get('shares', 0),
                    metrics.get('avg_price', 0),
                    metrics.get('price', 0),
                    metrics.get('change', 0),
                    metrics.get('cost', 0),
                    metrics.get('market_value', 0),
                    metrics.get('weight', 0),
                    metrics.get('dollar_gain', 0),
                    metrics.get('growth', 0),
                )
                cache_symbol = str(ticker or '').strip().upper()
                if cache_symbol in self._mktcap_cache:
                    self._update_mktcap_item(i, ticker, self._mktcap_cache[cache_symbol])
                else:
                    self._p4_clear_mktcap_item(i)
        finally:
            self.p4_table.setUpdatesEnabled(True)
            self.p4_table.setSortingEnabled(sorting_enabled)
            self.p4_table.blockSignals(False)
        cash_balance = self._p4_active_cash_balance()
        if cash_balance > 0.0 and total_market_value > 0.0:
            weights['CASH'] = cash_balance / total_market_value * 100.0
        if hasattr(self, '_p4_update_remove_stock_button_state'):
            self._p4_update_remove_stock_button_state()
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('stock')
        self._p4_update_stock_positions_label(len(tickers))
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)
        active_cache_key = self._p4_returns_cache_key(self._active_return_timeframe)
        if not tickers:
            self._return_metrics_cache[active_cache_key] = {}
            self._return_metrics_fetching[active_cache_key] = False
            self._update_returns_chart(self._active_return_timeframe, {})
        elif active_cache_key in self._return_metrics_cache:
            self._update_returns_chart(
                self._active_return_timeframe,
                self._return_metrics_cache.get(active_cache_key, {}),
            )
        else:
            self._fetch_returns_for_timeframe(self._active_return_timeframe)
        active_momentum_cache_key = self._p4_momentum_cache_key(self._active_momentum_timeframe)
        if not tickers and cash_balance <= 0.0:
            payload = self._p4_empty_momentum_payload('No portfolio holdings available')
            self._momentum_metrics_cache[active_momentum_cache_key] = payload
            self._momentum_metrics_fetching[active_momentum_cache_key] = False
            self._update_momentum_chart(self._active_momentum_timeframe, payload)
        elif active_momentum_cache_key in self._momentum_metrics_cache:
            self._update_momentum_chart(
                self._active_momentum_timeframe,
                self._momentum_metrics_cache.get(active_momentum_cache_key, {}),
            )
        else:
            self._fetch_momentum_for_timeframe(self._active_momentum_timeframe)
        self._fetch_market_caps(sorted_tickers)
        if self._p4_metrics_tab_visible():
            self._p4_refresh_portfolio_metrics_view()
