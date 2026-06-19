from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.data_service.results import describe_market_data_status, strip_market_data_keys
from budget_terminal_app.mixins.portfolio_presenters import (
    build_portfolio_stock_row,
    format_market_cap,
    format_market_cap_value,
    market_cap_color_token,
    market_cap_sort_value,
    market_cap_value,
)
from budget_terminal_app.table_cells import TableCell
from budget_terminal_app.widgets.table_render import render_table_cell, render_table_row, render_table_rows
from budget_terminal_app.workers.market_metrics import MarketCapWorker, MonthReturnWorker, PortfolioAnalyticsWorker, PortfolioMomentumWorker

_P4_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0
_P4_MOMENTUM_REFRESH_DEBOUNCE_MS = 250
_P4_METRICS_REFRESH_DEBOUNCE_MS = 350
_P4_POSITION_ENTRY_REFRESH_DEBOUNCE_MS = 300
_P4_ENTRY_EDITABLE_COLUMNS = (P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_AVG_PRICE)


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
    def _p4_normalize_stock_symbol(self, ticker: Any) -> str:
        """Return a normalized stock ticker for page-4 table operations."""
        return str(ticker or '').strip().upper()

    def _p4_find_stock_row(self, ticker: Any) -> int:
        """Return the visible stock-table row for a ticker, or -1."""
        table = getattr(self, 'p4_table', None)
        symbol = self._p4_normalize_stock_symbol(ticker)
        if table is None or not symbol:
            return -1
        for row in range(table.rowCount()):
            item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
            if self._p4_normalize_stock_symbol(item.text() if item else '') == symbol:
                return row
        return -1

    def _p4_visible_stock_order(self) -> list[str]:
        """Return stock tickers in their current visible table order."""
        table = getattr(self, 'p4_table', None)
        if table is None:
            return []
        order = []
        for row in range(table.rowCount()):
            item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
            symbol = self._p4_normalize_stock_symbol(item.text() if item else '')
            if symbol and symbol not in order:
                order.append(symbol)
        return order

    def _p4_stock_order_for_render(self, tickers: Any, metrics_map: dict[str, Any], *, preserve_visible_order: bool=False) -> list[Any]:
        """Return stock tickers in either stable visible order or market-value order."""
        ticker_list = list(tickers or [])
        if not preserve_visible_order:
            return sorted(
                ticker_list,
                key=lambda ticker: metrics_map.get(ticker, {}).get('market_value', 0),
                reverse=True,
            )
        by_symbol = {self._p4_normalize_stock_symbol(ticker): ticker for ticker in ticker_list}
        ordered = []
        seen = set()
        for symbol in self._p4_visible_stock_order():
            ticker = by_symbol.get(symbol)
            if ticker is not None and symbol not in seen:
                ordered.append(ticker)
                seen.add(symbol)
        for ticker in ticker_list:
            symbol = self._p4_normalize_stock_symbol(ticker)
            if symbol and symbol not in seen:
                ordered.append(ticker)
                seen.add(symbol)
        return ordered

    def _p4_active_position_entry(self) -> dict[str, Any] | None:
        """Return the active position-entry guard payload, if any."""
        payload = getattr(self, '_p4_active_position_entry_guard', None)
        return payload if isinstance(payload, dict) and payload.get('ticker') else None

    def _p4_position_entry_is_active(self) -> bool:
        """Return whether a stock position row is currently protected from movement."""
        return self._p4_active_position_entry() is not None

    def _p4_begin_position_entry(self, ticker: Any, column: int=P4_PORTFOLIO_COL_SHARES) -> None:
        """Protect one stock row from sorting while the user enters the position."""
        symbol = self._p4_normalize_stock_symbol(ticker)
        if not symbol:
            return
        table = getattr(self, 'p4_table', None)
        active = self._p4_active_position_entry()
        if active and active.get('ticker') != symbol:
            self._p4_end_position_entry(schedule_refresh=False)
        if table is not None and not self._p4_position_entry_is_active():
            self._p4_stock_table_sorting_was_enabled = bool(table.isSortingEnabled())
        if table is not None and table.isSortingEnabled():
            table.setSortingEnabled(False)
        try:
            column_value = int(column)
        except (TypeError, ValueError):
            column_value = P4_PORTFOLIO_COL_SHARES
        self._p4_active_position_entry_guard = {
            'ticker': symbol,
            'column': column_value if column_value in _P4_ENTRY_EDITABLE_COLUMNS else P4_PORTFOLIO_COL_SHARES,
        }
        dirty = set(getattr(self, '_p4_position_entry_dirty_tickers', set()))
        dirty.add(symbol)
        self._p4_position_entry_dirty_tickers = dirty

    def _p4_end_position_entry(self, *, schedule_refresh: bool=True) -> None:
        """Release the active position-entry guard and optionally queue a full refresh."""
        active = self._p4_active_position_entry()
        symbol = self._p4_normalize_stock_symbol(active.get('ticker') if active else '')
        complete = self._p4_position_entry_is_complete(symbol)
        self._p4_active_position_entry_guard = None
        table = getattr(self, 'p4_table', None)
        if table is not None and bool(getattr(self, '_p4_stock_table_sorting_was_enabled', False)):
            table.setSortingEnabled(True)
        self._p4_stock_table_sorting_was_enabled = False
        if schedule_refresh and symbol and complete:
            self._p4_schedule_position_entry_refresh(symbol, allow_heavy=True)
        elif symbol and not complete:
            self._p4_cancel_position_entry_refresh(symbol)

    def _p4_is_currently_editing_position_entry(self) -> bool:
        """Return whether focus is still on the protected ticker's editable cells."""
        active = self._p4_active_position_entry()
        table = getattr(self, 'p4_table', None)
        if not active or table is None:
            return False
        row = table.currentRow()
        column = table.currentColumn()
        item = table.item(row, P4_PORTFOLIO_COL_SYMBOL) if row >= 0 else None
        return (
            self._p4_normalize_stock_symbol(item.text() if item else '') == active.get('ticker')
            and column in _P4_ENTRY_EDITABLE_COLUMNS
        )

    def _p4_position_entry_has_positive_shares(self, ticker: Any=None) -> bool:
        """Return whether the guarded ticker has a positive share quantity."""
        entry = self._p4_position_entry_tracker_entry(ticker)
        return self._p4_position_entry_positive_value((entry or {}).get('shares', 0))

    def _p4_position_entry_positive_value(self, value: Any) -> bool:
        """Return whether a position-entry numeric field is positive."""
        try:
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
            return float(value or 0) > 0
        except (TypeError, ValueError):
            return False

    def _p4_position_entry_tracker_entry(self, ticker: Any=None) -> dict[str, Any]:
        """Return the tracker entry for a normalized ticker, if present."""
        active = self._p4_active_position_entry()
        symbol = self._p4_normalize_stock_symbol(ticker or (active or {}).get('ticker'))
        if not symbol:
            return {}
        tracker_data = self._p4_active_tracker_data()
        if not isinstance(tracker_data, dict):
            return {}
        if symbol in tracker_data and isinstance(tracker_data.get(symbol), dict):
            return tracker_data.get(symbol) or {}
        for saved_ticker, entry in tracker_data.items():
            if self._p4_normalize_stock_symbol(saved_ticker) == symbol and isinstance(entry, dict):
                return entry or {}
        return {}

    def _p4_position_entry_is_complete(self, ticker: Any=None) -> bool:
        """Return whether a stock position has both shares and average price entered."""
        entry = self._p4_position_entry_tracker_entry(ticker)
        return (
            self._p4_position_entry_positive_value((entry or {}).get('shares', 0))
            and self._p4_position_entry_positive_value((entry or {}).get('avg_price', 0))
        )

    def _p4_cancel_position_entry_refresh(self, ticker: Any=None) -> None:
        """Drop pending position-entry refresh work for an incomplete row."""
        symbol = self._p4_normalize_stock_symbol(ticker)
        dirty = set(getattr(self, '_p4_position_entry_dirty_tickers', set()))
        if symbol:
            dirty = {item for item in dirty if self._p4_normalize_stock_symbol(item) != symbol}
        else:
            dirty.clear()
        self._p4_position_entry_dirty_tickers = dirty
        if not dirty:
            self._p4_position_entry_allow_heavy = False
            timer = getattr(self, '_p4_position_entry_refresh_timer', None)
            if timer is not None and timer.isActive():
                timer.stop()

    def _p4_position_entry_refresh_pending(self) -> bool:
        """Return whether the completed-entry refresh debounce is still waiting."""
        timer = getattr(self, '_p4_position_entry_refresh_timer', None)
        return bool(timer is not None and timer.isActive())

    def _p4_restore_position_entry_cell(self) -> None:
        """Restore focus to the guarded ticker's editable cell after a table rebuild."""
        active = self._p4_active_position_entry()
        table = getattr(self, 'p4_table', None)
        if not active or table is None:
            return
        row = self._p4_find_stock_row(active.get('ticker'))
        if row < 0:
            return
        column = int(active.get('column', P4_PORTFOLIO_COL_SHARES))
        if column not in _P4_ENTRY_EDITABLE_COLUMNS:
            column = P4_PORTFOLIO_COL_SHARES
        self._p4_restoring_position_entry_cell = True
        try:
            table.selectRow(row)
            table.setCurrentCell(row, column)
            item = table.item(row, column)
            if item is not None:
                table.scrollToItem(item)
        finally:
            self._p4_restoring_position_entry_cell = False

    def _p4_focus_stock_entry_cell(self, ticker: Any, column: int=P4_PORTFOLIO_COL_SHARES) -> None:
        """Focus one stock row's editable cell."""
        self._p4_begin_position_entry(ticker, column)
        self._p4_restore_position_entry_cell()

    def _p4_on_stock_current_cell_changed(self, current_row: int, current_column: int, previous_row: int, previous_column: int) -> None:
        """Release the entry guard once focus leaves the protected row."""
        if getattr(self, '_p4_restoring_position_entry_cell', False):
            return
        active = self._p4_active_position_entry()
        if not active:
            return
        table = getattr(self, 'p4_table', None)
        item = table.item(current_row, P4_PORTFOLIO_COL_SYMBOL) if table is not None and current_row >= 0 else None
        symbol = self._p4_normalize_stock_symbol(item.text() if item else '')
        if symbol == active.get('ticker') and current_column in _P4_ENTRY_EDITABLE_COLUMNS:
            active['column'] = current_column
            return
        self._p4_end_position_entry(schedule_refresh=True)

    def _p4_schedule_position_entry_refresh(self, ticker: Any=None, *, allow_heavy: bool=False) -> None:
        """Debounce refresh work triggered by stock-position entry."""
        symbol = self._p4_normalize_stock_symbol(ticker)
        if symbol and not self._p4_position_entry_is_complete(symbol):
            self._p4_cancel_position_entry_refresh(symbol)
            return
        dirty = set(getattr(self, '_p4_position_entry_dirty_tickers', set()))
        if symbol:
            dirty.add(symbol)
        self._p4_position_entry_dirty_tickers = dirty
        self._p4_position_entry_allow_heavy = bool(getattr(self, '_p4_position_entry_allow_heavy', False) or allow_heavy)
        timer = getattr(self, '_p4_position_entry_refresh_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._p4_flush_position_entry_refresh)
            self._p4_position_entry_refresh_timer = timer
        timer.start(_P4_POSITION_ENTRY_REFRESH_DEBOUNCE_MS)

    def _p4_flush_position_entry_refresh(self) -> None:
        """Run deferred quote and analytics refresh work after entry settles."""
        timer = getattr(self, '_p4_position_entry_refresh_timer', None)
        if timer is not None and timer.isActive():
            timer.stop()
        dirty = set(getattr(self, '_p4_position_entry_dirty_tickers', set()))
        active = self._p4_active_position_entry()
        if active:
            dirty.add(active.get('ticker'))
        dirty = {self._p4_normalize_stock_symbol(ticker) for ticker in dirty if self._p4_normalize_stock_symbol(ticker)}
        if active and not self._p4_position_entry_is_complete(active.get('ticker')):
            self._p4_cancel_position_entry_refresh(active.get('ticker'))
            return
        dirty = {ticker for ticker in dirty if self._p4_position_entry_is_complete(ticker)}
        if not dirty:
            self._p4_position_entry_dirty_tickers = set()
            self._p4_position_entry_allow_heavy = False
            return
        self._p4_position_entry_dirty_tickers = set()
        allow_heavy = bool(getattr(self, '_p4_position_entry_allow_heavy', False))
        self._p4_position_entry_allow_heavy = False
        if active and self._p4_position_entry_is_complete(active.get('ticker')):
            allow_heavy = True
        if active and not self._p4_is_currently_editing_position_entry():
            allow_heavy = True

        if (
            (getattr(self, '_dashboard_showing_all', False) or getattr(self, 'active_portfolio_id', None) == getattr(self, 'main_portfolio_id', None))
            and hasattr(self, '_dashboard_apply_local_portfolio_membership')
        ):
            self._dashboard_apply_local_portfolio_membership(getattr(self, 'last_data', None))
        if hasattr(self, 'refresh_data'):
            if getattr(self, 'last_data', None):
                self.refresh_data(reason='portfolio_membership_change')
            else:
                self.refresh_data()
        if dirty:
            self._fetch_market_caps(sorted(dirty))
        if not allow_heavy:
            return
        self._p4_invalidate_returns_cache()
        self._p4_invalidate_momentum_cache()
        self._p4_invalidate_portfolio_analytics_cache()
        self._fetch_returns_for_timeframe(self._active_return_timeframe)
        self._p4_refresh_active_momentum_view()
        self._p4_schedule_portfolio_metrics_refresh()

    def _p4_returns_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio/timeframe/inclusion selection."""
        symbols = tuple(sorted(self._p4_normalize_stock_symbol(ticker) for ticker in self._p4_weight_included_tickers()))
        return (str(portfolio_id or self.active_portfolio_id), str(timeframe_key), symbols)

    def _p4_invalidate_returns_cache(self, portfolio_id: Any = None) -> None:
        """Drop cached return metrics for one portfolio slot."""
        pid = str(portfolio_id or self.active_portfolio_id)
        self._return_metrics_cache = {
            key: value
            for key, value in self._return_metrics_cache.items()
            if not (isinstance(key, tuple) and len(key) >= 2 and key[0] == pid)
        }
        self._return_metrics_fetching = {
            key: value
            for key, value in self._return_metrics_fetching.items()
            if not (isinstance(key, tuple) and len(key) >= 2 and key[0] == pid)
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

    def _p4_position_included_in_weight(self, ticker: Any) -> bool:
        """Return whether one active stock position participates in filtered views."""
        symbol = self._p4_normalize_stock_symbol(ticker)
        tracker_data = self._p4_active_tracker_data()
        if not isinstance(tracker_data, dict):
            return True
        entry = tracker_data.get(ticker)
        if not isinstance(entry, dict):
            entry = next(
                (
                    saved_entry
                    for saved_ticker, saved_entry in tracker_data.items()
                    if self._p4_normalize_stock_symbol(saved_ticker) == symbol and isinstance(saved_entry, dict)
                ),
                {},
            )
        return entry.get('include_in_weight') is not False

    def _p4_weight_included_tickers(self) -> list[Any]:
        """Return active tickers enabled for Weight, Dip Finder, and Heatmap views."""
        return [ticker for ticker in self._p4_active_tickers() if self._p4_position_included_in_weight(ticker)]

    def _p4_filtered_weight_map(self, metrics_map: Any) -> tuple[dict[Any, float], float]:
        """Return weights rebased across enabled stocks plus brokerage cash."""
        metrics_map = metrics_map if isinstance(metrics_map, dict) else {}
        included = self._p4_weight_included_tickers()
        cash_balance = self._p4_active_cash_balance()
        included_stock_value = sum(
            max(float((metrics_map.get(ticker, {}) or {}).get('market_value', 0.0) or 0.0), 0.0)
            for ticker in included
        )
        denominator = included_stock_value + cash_balance
        weights = {
            ticker: (
                max(float((metrics_map.get(ticker, {}) or {}).get('market_value', 0.0) or 0.0), 0.0)
                / denominator * 100.0
                if denominator > 0.0
                else 0.0
            )
            for ticker in included
        }
        if cash_balance > 0.0 and denominator > 0.0:
            weights['CASH'] = cash_balance / denominator * 100.0
        return weights, denominator

    def _p4_apply_symbol_checkbox(self, row: int, ticker: Any) -> None:
        """Apply the persisted inclusion state to one visible Symbol item."""
        table = getattr(self, 'p4_table', None)
        item = table.item(int(row), P4_PORTFOLIO_COL_SYMBOL) if table is not None else None
        if item is None:
            return
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked
            if self._p4_position_included_in_weight(ticker)
            else Qt.CheckState.Unchecked
        )
        item.setToolTip('Include this position in Portfolio Weight, Dip Finder, and Portfolio Heatmap')

    def _p4_apply_visible_symbol_checkboxes(self) -> None:
        """Restore checkboxes after a full table render or sort."""
        table = getattr(self, 'p4_table', None)
        if table is None:
            return
        previous = table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
                if item is not None:
                    self._p4_apply_symbol_checkbox(row, item.text())
        finally:
            table.blockSignals(previous)

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
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
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

        self._p4_submit_background_task(_run)

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

    def _p4_export_tickers(self) -> None:
        """Copy the active portfolio's stock tickers to the clipboard."""
        ordered_tickers = self._p4_stock_order_for_render(
            self._p4_active_tickers(),
            {},
            preserve_visible_order=True,
        )
        symbols = []
        seen = set()
        for ticker in ordered_tickers:
            symbol = self._p4_normalize_stock_symbol(ticker)
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        if not symbols:
            self.set_status_text(self.status_bar, 'No stock tickers to export', status='warning')
            return
        QApplication.clipboard().setText('\n'.join(symbols))
        self.set_status_text(self.status_bar, f'Exported {len(symbols)} tickers to clipboard', status='positive')

    def _p4_export_for_llm(self) -> None:
        """Export the active portfolio's stock and options data to clipboard for LLM analysis."""
        def _number(value: Any) -> float:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 0.0
            if math.isnan(number) or math.isinf(number):
                return 0.0
            return number

        def _plain(value: Any) -> str:
            return str(value if value is not None else '').replace('|', '/').strip()

        def _currency(value: Any, *, signed: bool=False) -> str:
            number = _number(value)
            prefix = '+' if signed and number >= 0 else ''
            return f'{prefix}${number:,.2f}'

        def _percent(value: Any, *, signed: bool=False, decimals: int=1) -> str:
            number = _number(value)
            prefix = '+' if signed and number >= 0 else ''
            return f'{prefix}{number:.{decimals}f}%'

        def _count(value: Any) -> str:
            return f'{int(round(_number(value))):,}'

        def _shares(value: Any) -> str:
            return f'{_number(value):g}'

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
            lines.append('| Ticker | Sh | Avg | Price | Day% | MV | Wt% | PnL | Gain% | MCap |')
            lines.append('| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |')
            sorted_tickers = sorted(tickers, key=lambda t: metrics_map.get(t, {}).get('market_value', 0), reverse=True)
            for ticker in sorted_tickers:
                m = metrics_map.get(ticker, {})
                mc = self._mktcap_cache.get(str(ticker or '').strip().upper())
                mc_str = self._format_market_cap(mc)
                lines.append(
                    '| {ticker} | {shares} | {avg_price} | {price} | {change} | {mv} | {weight} | {gain} | {growth} | {mc} |'.format(
                        ticker=_plain(ticker),
                        shares=_shares(m.get('shares', 0)),
                        avg_price=_currency(m.get('avg_price', 0)),
                        price=_currency(m.get('price', 0)),
                        change=_percent(m.get('change', 0), signed=True, decimals=2),
                        mv=_currency(m.get('market_value', 0)),
                        weight=_percent(m.get('weight', 0)),
                        gain=_currency(m.get('dollar_gain', 0), signed=True),
                        growth=_percent(m.get('growth', 0), signed=True),
                        mc=_plain(mc_str),
                    )
                )
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
            lines.append('| Ticker | Strat | Exp | Strike | Ctr | Prem | Cur | Vol | OI | IV% | PnL |')
            lines.append('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |')
            for pos in options_data:
                ticker = _plain(pos.get('ticker', '?')) or '?'
                strategy = _plain(pos.get('strategy', 'Calls')) or 'Calls'
                expiry = _plain(pos.get('expiry', 'N/A')) or 'N/A'
                strike = _number(pos.get('strike', 0))
                contracts = _number(pos.get('contracts', 1))
                premium = _number(pos.get('premium', 0))
                current = _number(pos.get('current_price', 0))
                iv = _number(pos.get('iv', 0))
                volume = _number(pos.get('volume', pos.get('vol', 0)))
                open_interest = _number(pos.get('open_interest', pos.get('openInterest', 0)))
                is_seller = strategy in ('Covered Call', 'Cash Secured Put')
                if is_seller:
                    pl = (premium - current) * contracts * 100
                else:
                    pl = (current - premium) * contracts * 100
                lines.append(
                    '| {ticker} | {strategy} | {expiry} | {strike} | {contracts} | {premium} | {current} | {volume} | {open_interest} | {iv} | {pl} |'.format(
                        ticker=ticker,
                        strategy=strategy,
                        expiry=expiry,
                        strike=_currency(strike),
                        contracts=_shares(contracts),
                        premium=_currency(premium),
                        current=_currency(current),
                        volume=_count(volume),
                        open_interest=_count(open_interest),
                        iv=_percent(iv * 100),
                        pl=_currency(pl, signed=True),
                    )
                )
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
        if col == P4_PORTFOLIO_COL_SYMBOL:
            self._p4_on_weight_inclusion_changed(item)
            return
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
        if hasattr(self, '_p4_begin_position_entry'):
            self._p4_begin_position_entry(ticker, col)
        tracker_data = self._p4_active_tracker_data()
        tracker_entry = tracker_data.setdefault(ticker, {})
        tracker_entry['shares' if col == P4_PORTFOLIO_COL_SHARES else 'avg_price'] = val
        self._persist_all_portfolios()
        if self.last_data:
            self._recalc_tracker_row(row, ticker, self.last_data.get('portfolio', {}))
        if hasattr(self, '_p4_schedule_position_entry_refresh') and self._p4_position_entry_is_complete(ticker):
            self._p4_schedule_position_entry_refresh(ticker, allow_heavy=(col == P4_PORTFOLIO_COL_SHARES and val > 0))
        elif hasattr(self, '_p4_cancel_position_entry_refresh'):
            self._p4_cancel_position_entry_refresh(ticker)

    def _p4_on_weight_inclusion_changed(self, item: Any) -> None:
        """Persist one Symbol checkbox and refresh only its filtered views."""
        ticker = self._p4_normalize_stock_symbol(item.text() if item is not None else '')
        if not ticker:
            return
        included = item.checkState() == Qt.CheckState.Checked
        tracker_data = self._p4_active_tracker_data()
        saved_ticker = next(
            (key for key in tracker_data if self._p4_normalize_stock_symbol(key) == ticker),
            ticker,
        )
        tracker_data.setdefault(saved_ticker, {})['include_in_weight'] = included
        self._persist_all_portfolios(immediate=True)
        self._p4_invalidate_returns_cache()
        self._p4_refresh_weight_filter_views()

    def _p4_refresh_weight_filter_views(self) -> None:
        """Refresh Weight, Dip Finder, and Heatmap after an inclusion toggle."""
        data = getattr(self, 'last_data', None)
        portfolio = data.get('portfolio', {}) if isinstance(data, dict) else {}
        metrics_map, _total_value = self._p4_build_tracker_metrics_map(portfolio)
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
        table = getattr(self, 'p4_table', None)
        if table is not None:
            previous = table.blockSignals(True)
            sorting_enabled = table.isSortingEnabled()
            if sorting_enabled:
                table.setSortingEnabled(False)
            try:
                for row in range(table.rowCount()):
                    symbol_item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
                    ticker = symbol_item.text() if symbol_item is not None else ''
                    metrics = dict(metrics_map.get(ticker, {}))
                    included = self._p4_position_included_in_weight(ticker)
                    metrics['weight'] = weights.get(ticker, 0.0)
                    weight_cell = self._p4_build_stock_table_row(
                        ticker,
                        metrics,
                        weight_included=included,
                    )[P4_PORTFOLIO_COL_WEIGHT]
                    render_table_cell(table, row, P4_PORTFOLIO_COL_WEIGHT, weight_cell)
                    self._p4_apply_symbol_checkbox(row, ticker)
            finally:
                if sorting_enabled:
                    table.setSortingEnabled(True)
                table.blockSignals(previous)
        if hasattr(self, 'p4_weight_chart'):
            self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)
        timeframe = getattr(self, '_active_return_timeframe', 'dip_finder')
        included_tickers = self._p4_weight_included_tickers()
        if not included_tickers:
            self._update_returns_chart(timeframe, {})
        else:
            self._fetch_returns_for_timeframe(timeframe)

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
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
        keep_sorting_disabled = self._p4_position_entry_is_active()
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
                weights.get(ticker, 0.0),
                metrics['dollar_gain'],
                metrics['growth'],
            )
        finally:
            if sorting_enabled and not keep_sorting_disabled:
                self.p4_table.setSortingEnabled(True)
            self.p4_table.blockSignals(False)
        self._p4_restore_position_entry_cell()
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        if self._p4_position_entry_is_active():
            return
        self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)

    def _p4_market_cap_color_from_token(self, token: str) -> str:
        """Resolve the presenter market-cap color token to the active theme."""
        if token == 'series_0':
            return self.theme_series_color(0)
        if token == 'series_3':
            return self.theme_series_color(3)
        return self.theme_color(token)

    def _p4_market_cap_cell(self, market_cap: Any) -> TableCell:
        """Return the themed market-cap table cell."""
        color = self._p4_market_cap_color_from_token(market_cap_color_token(market_cap))
        return TableCell(
            format_market_cap(market_cap),
            foreground=color,
            sort_value=market_cap_sort_value(market_cap),
        )

    def _p4_analyst_target_map(self, data: Any = None) -> dict[str, Any]:
        """Return analyst target prices keyed by normalized ticker."""
        source = data if isinstance(data, dict) else getattr(self, 'last_data', {})
        raw_targets = source.get('targets', []) if isinstance(source, dict) else []
        targets: dict[str, Any] = {}
        if not isinstance(raw_targets, list):
            return targets
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get('ticker') or '').strip().upper()
            if symbol:
                targets[symbol] = item.get('target')
        return targets

    def _p4_build_stock_table_row(
        self,
        ticker: Any,
        metrics: dict[str, Any],
        *,
        market_cap: Any = None,
        analyst_target: Any = None,
        weight_included: bool = True,
    ) -> Any:
        """Return the presenter row for one Portfolio stock position."""
        return build_portfolio_stock_row(
            ticker,
            metrics,
            default_color=self.theme_color('text_primary'),
            gain_color=self.theme_color('accent_positive' if float(metrics.get('dollar_gain', 0) or 0) >= 0 else 'accent_negative'),
            change_color=self.theme_color('accent_positive' if float(metrics.get('change', 0) or 0) >= 0 else 'accent_negative'),
            market_cap=market_cap,
            market_cap_color=self._p4_market_cap_color_from_token(market_cap_color_token(market_cap)),
            analyst_target=analyst_target,
            analyst_positive_color=self.theme_color('accent_positive'),
            analyst_negative_color=self.theme_color('accent_negative'),
            weight_included=weight_included,
        )

    def _p4_clear_mktcap_item(self, row: Any) -> None:
        """Clear stale market-cap text when a reused row has no cached value yet."""
        render_table_cell(self.p4_table, int(row), P4_PORTFOLIO_COL_MARKET_CAP, self._p4_market_cap_cell(None))

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
        market_cap = None
        cache_symbol = str(ticker or '').strip().upper()
        if cache_symbol in getattr(self, '_mktcap_cache', {}):
            market_cap = self._mktcap_cache[cache_symbol]
        analyst_targets = self._p4_analyst_target_map()
        row_cells = self._p4_build_stock_table_row(
            ticker,
            {
                'shares': shares,
                'avg_price': avg_price,
                'price': price,
                'change': change,
                'cost': cost,
                'market_value': mkt_val,
                'weight': weight,
                'dollar_gain': dollar_gain,
                'growth': growth,
            },
            market_cap=market_cap,
            analyst_target=analyst_targets.get(cache_symbol),
            weight_included=self._p4_position_included_in_weight(ticker),
        )
        render_table_row(self.p4_table, int(row), row_cells)
        self._p4_apply_symbol_checkbox(int(row), ticker)

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
            [ticker for ticker in self._p4_weight_included_tickers() if ticker in results],
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

        self._p4_submit_background_task(_run)

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
        self._p4_submit_background_task(worker_obj.run)
        return True

    def _fetch_returns_for_timeframe(self, timeframe_key: Any) -> None:
        """Fetch returns for a specific timeframe."""
        portfolio_id = str(self.active_portfolio_id)
        cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        if self._return_metrics_fetching.get(cache_key, False):
            return
        tickers = list(self._p4_weight_included_tickers())
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
                lambda payload=results, key=timeframe_key, pid=portfolio_id, requested_cache_key=cache_key: self._on_returns_ready(
                    key,
                    pid,
                    payload,
                    requested_cache_key,
                )
            )

        self._p4_submit_background_task(_run)

    def _on_returns_ready(self, timeframe_key: Any, portfolio_id: Any, results: Any, cache_key: Any = None) -> None:
        """Handle return metrics ready."""
        if hasattr(self, '_record_data_health_payload'):
            requested_symbols = cache_key[2] if isinstance(cache_key, tuple) and len(cache_key) >= 3 else self._p4_weight_included_tickers()
            self._record_data_health_payload('Portfolio returns', results, symbols=requested_symbols)
        results = strip_market_data_keys(results) if isinstance(results, dict) else results
        cache_key = cache_key or self._p4_returns_cache_key(timeframe_key, portfolio_id)
        self._return_metrics_fetching[cache_key] = False
        self._return_metrics_cache[cache_key] = results
        current_cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        if (
            cache_key == current_cache_key
            and str(portfolio_id) == str(self.active_portfolio_id)
            and timeframe_key == self._active_return_timeframe
        ):
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
        return format_market_cap(mc)

    def _p4_market_cap_value(self, mc: Any) -> Any:
        """Return a positive finite market-cap number or None."""
        return market_cap_value(mc)

    def _p4_format_market_cap_value(self, value: float) -> str:
        """Format a market-cap value with a compact suffix."""
        return format_market_cap_value(value)

    def _mktcap_color(self, mc: Any) -> Any:
        """Handle mktcap color."""
        return self._p4_market_cap_color_from_token(market_cap_color_token(mc))

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

        self._p4_submit_background_task(_run)
        return True

    def _update_mktcap_item(self, row: Any, ticker: Any, mc: Any) -> None:
        """Handle update mktcap item."""
        self.p4_table.blockSignals(True)
        try:
            render_table_cell(self.p4_table, int(row), P4_PORTFOLIO_COL_MARKET_CAP, self._p4_market_cap_cell(mc))
        finally:
            self.p4_table.blockSignals(False)

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
        keep_sorting_disabled = self._p4_position_entry_is_active()
        sorting_enabled = self.p4_table.isSortingEnabled()
        self.p4_table.setSortingEnabled(False)
        try:
            for row in range(self.p4_table.rowCount()):
                item = self.p4_table.item(row, P4_PORTFOLIO_COL_SYMBOL)
                symbol = str(item.text() if item else '').strip().upper()
                if symbol and symbol in normalized_results:
                    self._update_mktcap_item(row, symbol, normalized_results[symbol])
        finally:
            if sorting_enabled and not keep_sorting_disabled:
                self.p4_table.setSortingEnabled(True)
        self._p4_restore_position_entry_cell()
        queued = list(getattr(self, '_mktcap_queued_tickers', set()))
        self._mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if str(ticker or '').strip().upper() not in request_tickers]
            self._fetch_market_caps(remaining)

    def update_page4(
        self,
        data: Any,
        *,
        preserve_visible_order: bool | None = None,
        defer_expensive_refresh: bool=False,
    ) -> None:
        """Update page4."""
        portfolio = data.get('portfolio', {})
        tickers = self._p4_active_tickers()
        metrics_map, total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        active_entry = self._p4_position_entry_is_active()
        active_payload = self._p4_active_position_entry()
        active_incomplete_entry = bool(
            active_payload and not self._p4_position_entry_is_complete(active_payload.get('ticker'))
        )
        entry_refresh_pending = self._p4_position_entry_refresh_pending()
        preserve_order = active_entry if preserve_visible_order is None else bool(preserve_visible_order)
        defer_refresh = bool(defer_expensive_refresh or active_incomplete_entry or entry_refresh_pending)
        sorted_tickers = self._p4_stock_order_for_render(
            tickers,
            metrics_map,
            preserve_visible_order=preserve_order,
        )
        analyst_targets = self._p4_analyst_target_map(data)
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
        rows = []
        for ticker in sorted_tickers:
            metrics = dict(metrics_map.get(ticker, {}))
            included = self._p4_position_included_in_weight(ticker)
            metrics['weight'] = weights.get(ticker, 0.0)
            cache_symbol = str(ticker or '').strip().upper()
            rows.append(
                self._p4_build_stock_table_row(
                    ticker,
                    metrics,
                    market_cap=self._mktcap_cache.get(cache_symbol) if cache_symbol in self._mktcap_cache else None,
                    analyst_target=analyst_targets.get(cache_symbol),
                    weight_included=included,
                )
            )
        if preserve_order and self.p4_table.isSortingEnabled():
            self.p4_table.setSortingEnabled(False)
        render_table_rows(self.p4_table, rows)
        self._p4_apply_visible_symbol_checkboxes()
        self._p4_restore_position_entry_cell()

        cash_balance = self._p4_active_cash_balance()
        if hasattr(self, '_p4_update_remove_stock_button_state'):
            self._p4_update_remove_stock_button_state()
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('stock')
        self._p4_update_stock_positions_label(len(tickers))
        self.p4_total_label.setText(f'Total:  ${total_market_value:,.2f}  USD')
        if defer_refresh:
            return
        self._update_weight_chart(weights)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)

        active_cache_key = self._p4_returns_cache_key(self._active_return_timeframe)
        included_tickers = self._p4_weight_included_tickers()
        if not included_tickers:
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
