from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from ..compat import (
    DEFAULT_PORTFOLIO_METRICS_SETTINGS,
    P4_PORTFOLIO_COL_AVG_PRICE,
    P4_PORTFOLIO_COL_MARKET_CAP,
    P4_PORTFOLIO_COL_SHARES,
    P4_PORTFOLIO_COL_SYMBOL,
    P4_PORTFOLIO_COL_WEIGHT,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
    datetime,
    logger,
    math,
    pd,
    pg,
    save_portfolio_metrics_settings,
)
from budget_terminal_app.data_service.results import (
    describe_market_data_status,
    market_data_errors,
    market_data_meta,
    strip_market_data_keys,
)
from budget_terminal_app.mixins.portfolio_presenters import (
    build_portfolio_stock_row,
    format_market_cap,
    format_market_cap_value,
    margin_health_color_token,
    market_cap_color_token,
    market_cap_sort_value,
    market_cap_value,
)
from budget_terminal_app.services.portfolio_analysis import (
    filtered_summary,
    filtered_weights,
    margin_utilization,
    returns_cache_key,
    settle_trade,
)
from budget_terminal_app.table_cells import TableCell
from budget_terminal_app.widgets.batched_render import run_batched
from budget_terminal_app.widgets.table_render import render_table_cell, render_table_row, render_table_rows
from budget_terminal_app.workers.market_metrics import MarketCapWorker, MonthReturnWorker, PortfolioAnalyticsWorker, PortfolioMomentumWorker
from budget_terminal_app.workers.data import DataWorker

_P4_MKTCAP_CACHE_TTL_SECONDS = 6 * 60 * 60.0
_P4_MOMENTUM_REFRESH_DEBOUNCE_MS = 250
_P4_METRICS_REFRESH_DEBOUNCE_MS = 350
_P4_ENTRY_EDITABLE_COLUMNS = (P4_PORTFOLIO_COL_SHARES, P4_PORTFOLIO_COL_AVG_PRICE)
_P4_CONTENT_KEYS = ('positions', 'pie', 'heatmap', 'momentum', 'metrics')


@dataclass(frozen=True, slots=True)
class _PortfolioRefreshContext:
    portfolio_id: str
    tickers: tuple[str, ...]
    included_tickers: tuple[str, ...]
    heatmap_tickers: tuple[str, ...]
    tracker_signature: tuple[tuple[str, float, float, bool], ...]
    shares_map: tuple[tuple[str, float], ...]
    cash_amount: float
    subtab: str
    return_timeframe: str
    return_config: tuple[tuple[str, Any], ...]
    heatmap_interval: str
    heatmap_config: tuple[tuple[str, Any], ...]
    momentum_timeframe: str
    momentum_config: tuple[tuple[str, Any], ...]
    metrics_benchmark: str
    metrics_lookback: str

    @property
    def signature(self) -> tuple[Any, ...]:
        return (
            self.portfolio_id,
            self.tickers,
            self.included_tickers,
            self.tracker_signature,
            round(self.cash_amount, 2),
            self.subtab,
            self.return_timeframe,
            self.return_config,
            self.heatmap_interval,
            self.heatmap_config,
            self.momentum_timeframe,
            self.momentum_config,
            self.metrics_benchmark,
            self.metrics_lookback,
        )

    @property
    def holdings_signature(self) -> tuple[Any, ...]:
        """Return the inputs that determine whether quote results are still safe."""
        return (
            self.portfolio_id,
            self.tickers,
            self.included_tickers,
            self.tracker_signature,
            round(self.cash_amount, 2),
        )


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
            self._p4_end_position_entry()
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

    def _p4_end_position_entry(self) -> None:
        """Release the active position-entry guard without starting data work."""
        self._p4_active_position_entry_guard = None
        table = getattr(self, 'p4_table', None)
        if table is not None and bool(getattr(self, '_p4_stock_table_sorting_was_enabled', False)):
            table.setSortingEnabled(True)
        self._p4_stock_table_sorting_was_enabled = False

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
        """Focus one stock row's editable cell and open its editor."""
        self._p4_begin_position_entry(ticker, column)
        self._p4_restore_position_entry_cell()
        table = getattr(self, 'p4_table', None)
        active = self._p4_active_position_entry()
        if table is None or not active:
            return
        row = self._p4_find_stock_row(active.get('ticker'))
        if row < 0:
            return
        item = table.item(row, int(active.get('column', column)))
        if item is not None:
            table.editItem(item)

    def _p4_stock_editor_open(self) -> bool:
        """Return whether a positions cell editor is currently open."""
        return bool(getattr(getattr(self, 'p4_table', None), 'editor_open', False))

    def _p4_defer_positions_render(self) -> None:
        """Mark the positions table for a render once the open editor closes."""
        self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
        self._p4_dirty_subtabs.add('positions')

    def _p4_on_stock_editor_finished(self) -> None:
        """Re-render the positions table once editing has really finished."""
        QTimer.singleShot(0, self._p4_flush_deferred_positions_render)

    def _p4_flush_deferred_positions_render(self) -> None:
        """Apply a positions render that was skipped because a cell editor was open."""
        if self._p4_stock_editor_open():
            return
        if 'positions' not in getattr(self, '_p4_dirty_subtabs', set()):
            return
        data = getattr(self, 'last_data', None)
        if not data:
            return
        self.update_page4(data, render_scope='positions', mark_hidden_dirty=False)

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
        self._p4_end_position_entry()

    def _p4_refresh_holdings(self) -> None:
        """Refresh active holdings through one visible-subtab-first pipeline."""
        if getattr(self, '_refresh_shutdown', False):
            return
        self._p4_end_position_entry()
        context = self._p4_capture_refresh_context()
        coordinator = self._p4_get_refresh_coordinator()
        token, should_start = coordinator.request('portfolio.holdings', context.signature)
        contexts = getattr(self, '_p4_holdings_refresh_contexts', {})
        contexts[token.generation] = context
        self._p4_holdings_refresh_contexts = contexts
        if not should_start:
            if coordinator.is_active(token):
                self._p4_set_holdings_refresh_status('Holdings refresh already running.', status='info')
            else:
                self._p4_set_holdings_refresh_status('Updated holdings queued.', status='info')
            return
        self._p4_set_holdings_refresh_busy(True)
        self._p4_start_holdings_refresh(token, context)

    def _p4_get_refresh_coordinator(self) -> Any:
        """Return the shared refresh coordinator, creating it for small harnesses."""
        coordinator = getattr(self, '_refresh_coordinator', None)
        if coordinator is None:
            from budget_terminal_app.services.refresh_control import RefreshCoordinator

            coordinator = RefreshCoordinator()
            self._refresh_coordinator = coordinator
        return coordinator

    def _p4_set_holdings_refresh_busy(self, busy: bool) -> None:
        """Apply busy state only to the Portfolio holdings refresh action."""
        button = getattr(self, 'p4_refresh_holdings_btn', None)
        if button is None:
            return
        button.setEnabled(not busy)
        button.setText('Refreshing…' if busy else 'Refresh Holdings')

    def _p4_set_holdings_refresh_status(self, text: Any, *, status: str='muted') -> None:
        """Show page-local holdings refresh progress without changing navigation."""
        label = getattr(self, 'p4_refresh_holdings_status_lbl', None)
        if label is not None:
            self.set_status_text(label, str(text or ''), status=status)

    def _p4_holdings_refresh_running(self) -> bool:
        """Return whether the shared coordinator has an active holdings request."""
        coordinator = getattr(self, '_refresh_coordinator', None)
        return bool(
            coordinator is not None
            and coordinator.active_token('portfolio.holdings') is not None
        )

    def _p4_active_content_key(self) -> str:
        """Return the stable key for the selected Portfolio sub-tab."""
        tabs = getattr(self, 'p4_content_tabs', None)
        if tabs is None:
            return 'positions'
        widget = tabs.currentWidget()
        for attr_name, key in (
            ('p4_positions_page', 'positions'),
            ('p4_pie_page', 'pie'),
            ('p4_heatmap_page', 'heatmap'),
            ('p4_momentum_page', 'momentum'),
            ('p4_metrics_page', 'metrics'),
        ):
            candidate = getattr(self, attr_name, None)
            if candidate is not None and widget is candidate:
                return key
        return 'positions'

    def _p4_page_visible(self) -> bool:
        """Return whether Portfolio is the current top-level page."""
        page = getattr(self, 'page4', None)
        if page is None:
            return True
        is_current = getattr(self, '_is_current_page', None)
        if callable(is_current):
            try:
                return bool(is_current(page))
            except Exception:
                return False
        stack = getattr(self, 'stack', None) or getattr(self, 'stacked_widget', None)
        return stack is None or stack.currentWidget() is page

    def _p4_tracker_refresh_signature(self) -> tuple[tuple[str, float, float, bool], ...]:
        """Capture the current editable holdings inputs as an immutable signature."""
        tracker_data = self._p4_active_tracker_data()
        signature = []
        for ticker in self._p4_active_tickers():
            symbol = self._p4_normalize_stock_symbol(ticker)
            entry = tracker_data.get(ticker, {}) if isinstance(tracker_data, dict) else {}
            if not isinstance(entry, dict) and isinstance(tracker_data, dict):
                entry = tracker_data.get(symbol, {})
            try:
                shares = round(float((entry or {}).get('shares', 0) or 0), 8)
            except (AttributeError, TypeError, ValueError):
                shares = 0.0
            try:
                avg_price = round(float((entry or {}).get('avg_price', 0) or 0), 8)
            except (AttributeError, TypeError, ValueError):
                avg_price = 0.0
            signature.append((symbol, shares, avg_price, (entry or {}).get('include_in_weight') is not False))
        return tuple(sorted(item for item in signature if item[0]))

    @staticmethod
    def _p4_frozen_config(config: Any) -> tuple[tuple[str, Any], ...]:
        """Freeze a small timeframe configuration for a background request."""
        allowed = {'period', 'interval', 'start'}
        return tuple(
            sorted((str(key), value) for key, value in dict(config or {}).items() if str(key) in allowed)
        )

    @staticmethod
    def _p4_thawed_config(config: Any) -> dict[str, Any]:
        return dict(config or ())

    def _p4_capture_refresh_context(self) -> _PortfolioRefreshContext:
        """Capture all Portfolio inputs before handing work to a background thread."""
        portfolio_id = str(self.active_portfolio_id)
        tickers = tuple(sorted({
            self._p4_normalize_stock_symbol(ticker)
            for ticker in self._p4_active_tickers()
            if self._p4_normalize_stock_symbol(ticker)
        }))
        tracker_signature = self._p4_tracker_refresh_signature()
        shares_map = tuple((symbol, shares) for symbol, shares, _avg, _included in tracker_signature)
        included_tickers = tuple(sorted({
            self._p4_normalize_stock_symbol(ticker)
            for ticker in self._p4_weight_included_tickers()
            if self._p4_normalize_stock_symbol(ticker)
        }))
        positive_shares = {symbol for symbol, shares in shares_map if shares > 0.0}
        heatmap_tickers = tuple(symbol for symbol in included_tickers if symbol in positive_shares)
        return_timeframe = str(getattr(self, '_active_return_timeframe', 'dip_finder') or 'dip_finder')
        heatmap_interval = str(getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').lower()
        momentum_timeframe = str(getattr(self, '_active_momentum_timeframe', '1mo') or '1mo')
        return _PortfolioRefreshContext(
            portfolio_id=portfolio_id,
            tickers=tickers,
            included_tickers=included_tickers,
            heatmap_tickers=heatmap_tickers,
            tracker_signature=tracker_signature,
            shares_map=shares_map,
            cash_amount=round(float(self._p4_active_cash_balance(portfolio_id) or 0.0), 2),
            subtab=self._p4_active_content_key(),
            return_timeframe=return_timeframe,
            return_config=self._p4_frozen_config(self._get_return_timeframe_config(return_timeframe)),
            heatmap_interval=heatmap_interval,
            heatmap_config=self._p4_frozen_config(
                self._p4_heatmap_interval_config(heatmap_interval)
                if hasattr(self, '_p4_heatmap_interval_config') else {}
            ),
            momentum_timeframe=momentum_timeframe,
            momentum_config=self._p4_frozen_config(self._get_return_timeframe_config(momentum_timeframe)),
            metrics_benchmark=self._p4_normalize_metrics_benchmark_symbol(
                getattr(self, 'p4_metrics_benchmark_symbol', 'SPY')
            ),
            metrics_lookback=str(getattr(self, 'p4_metrics_lookback_key', '1y') or '1y').lower(),
        )

    def _p4_fetch_quotes_stage(self, tickers: Any) -> dict[str, Any]:
        client = getattr(self, '_data_service_client', None)
        if client is not None:
            return client.fetch_portfolio_quotes(tickers)
        return DataWorker(tickers, [], refresh_reason='portfolio_quotes').fetch_portfolio_quotes()

    def _p4_fetch_market_caps_stage(self, tickers: Any) -> dict[str, Any]:
        client = getattr(self, '_data_service_client', None)
        return client.fetch_market_caps(tickers) if client is not None else MarketCapWorker(tickers).fetch()

    def _p4_fetch_visible_dependency(self, context: _PortfolioRefreshContext, quotes: Any) -> tuple[str, Any]:
        """Fetch only the expensive dependency needed by the captured visible tab."""
        client = getattr(self, '_data_service_client', None)
        if context.subtab == 'positions':
            config = self._p4_thawed_config(context.return_config)
            if not context.included_tickers:
                return 'returns', {}
            payload = (
                client.fetch_month_returns(context.included_tickers, **config)
                if client is not None else MonthReturnWorker(context.included_tickers, **config).fetch()
            )
            return 'returns', payload
        if context.subtab == 'heatmap' and context.heatmap_interval not in {'live', '1d'}:
            config = self._p4_thawed_config(context.heatmap_config)
            if not context.heatmap_tickers:
                return 'heatmap', {}
            payload = (
                client.fetch_month_returns(context.heatmap_tickers, **config)
                if client is not None else MonthReturnWorker(context.heatmap_tickers, **config).fetch()
            )
            return 'heatmap', payload
        if context.subtab == 'momentum':
            config = self._p4_thawed_config(context.momentum_config)
            shares_map = dict(context.shares_map)
            payload = (
                client.fetch_portfolio_momentum(
                    context.tickers,
                    shares_map,
                    cash_amount=context.cash_amount,
                    **config,
                )
                if client is not None else PortfolioMomentumWorker(
                    context.tickers,
                    shares_map,
                    cash_amount=context.cash_amount,
                    **config,
                ).fetch()
            )
            return 'momentum', payload
        if context.subtab == 'metrics':
            prices_map = self._p4_quote_prices(quotes)
            if context.tickers and not prices_map:
                return 'metrics', None
            shares_map = dict(context.shares_map)
            payload = (
                client.fetch_portfolio_analytics(
                    context.tickers,
                    shares_map,
                    prices_map=prices_map,
                    benchmark_symbol=context.metrics_benchmark,
                    lookback_key=context.metrics_lookback,
                    cash_amount=context.cash_amount,
                )
                if client is not None else PortfolioAnalyticsWorker(
                    context.tickers,
                    shares_map,
                    prices_map=prices_map,
                    benchmark_symbol=context.metrics_benchmark,
                    lookback_key=context.metrics_lookback,
                    cash_amount=context.cash_amount,
                ).fetch()
            )
            return 'metrics', payload
        return '', None

    @staticmethod
    def _p4_quote_prices(payload: Any) -> dict[str, float]:
        prices = {}
        portfolio = payload.get('portfolio', {}) if isinstance(payload, dict) else {}
        for ticker, quote in portfolio.items() if isinstance(portfolio, dict) else ():
            try:
                prices[str(ticker).upper()] = float((quote or {}).get('price'))
            except (AttributeError, TypeError, ValueError):
                continue
        return prices

    def _p4_start_holdings_refresh(self, token: Any, context: _PortfolioRefreshContext) -> None:
        """Run one ordered Portfolio refresh pipeline on the single outer worker."""
        def _run() -> None:
            result = {'quotes': None, 'market_caps': None, 'dependency': ('', None), 'exceptions': []}
            try:
                result['quotes'] = self._p4_fetch_quotes_stage(context.tickers)
            except Exception as exc:
                logger.warning('Portfolio quote refresh failed: %s', exc)
                result['exceptions'].append(('quotes', str(exc)))
            try:
                result['market_caps'] = self._p4_fetch_market_caps_stage(context.tickers)
            except Exception as exc:
                logger.warning('Portfolio market-cap refresh failed: %s', exc)
                result['exceptions'].append(('market caps', str(exc)))
            try:
                result['dependency'] = self._p4_fetch_visible_dependency(context, result['quotes'])
            except Exception as exc:
                logger.warning('Portfolio %s refresh failed: %s', context.subtab, exc)
                result['exceptions'].append((context.subtab, str(exc)))
            if getattr(self, '_refresh_shutdown', False):
                return
            try:
                self._invoke_main.emit(
                    lambda payload=result, requested_token=token, captured=context: self._p4_on_holdings_refresh_ready(
                        requested_token,
                        captured,
                        payload,
                    )
                )
            except RuntimeError:
                return

        try:
            self._p4_submit_background_task(_run)
        except Exception as exc:
            logger.exception('Portfolio holdings worker could not start: %s', exc)
            contexts = getattr(self, '_p4_holdings_refresh_contexts', {})
            contexts.pop(token.generation, None)
            next_token = self._p4_get_refresh_coordinator().complete(token)
            if next_token is not None:
                next_context = contexts.get(next_token.generation)
                if next_context is not None:
                    self._p4_start_holdings_refresh(next_token, next_context)
                    return
                self._p4_get_refresh_coordinator().complete(next_token)
            self._p4_set_holdings_refresh_busy(False)
            self._p4_set_holdings_refresh_status(
                'Holdings refresh could not start; showing previous prices.',
                status='negative',
            )

    def _p4_context_is_current(self, context: _PortfolioRefreshContext) -> bool:
        """Reject late results when the active portfolio or editable inputs changed."""
        if str(getattr(self, 'active_portfolio_id', '')) != context.portfolio_id:
            return False
        try:
            return self._p4_capture_refresh_context().holdings_signature == context.holdings_signature
        except Exception:
            return False

    def _p4_cache_market_caps(self, payload: Any) -> None:
        results = strip_market_data_keys(payload) if isinstance(payload, dict) else {}
        if not isinstance(results, dict):
            return
        fetched_at = self._p4_mktcap_cache_now()
        for ticker, value in results.items():
            symbol = self._p4_normalize_stock_symbol(ticker)
            if symbol:
                self._mktcap_cache[symbol] = value
                self._mktcap_cache_ts[symbol] = fetched_at

    def _p4_cache_visible_dependency(self, context: _PortfolioRefreshContext, dependency: Any) -> None:
        kind, payload = dependency if isinstance(dependency, tuple) and len(dependency) == 2 else ('', None)
        if not kind or payload is None:
            return
        if isinstance(payload, dict) and market_data_meta(payload).get('freshness') == 'failed':
            return
        if kind == 'returns':
            cache_key = (context.portfolio_id, context.return_timeframe, context.included_tickers)
            normalized = strip_market_data_keys(payload) if isinstance(payload, dict) else {}
            if context.included_tickers and not normalized:
                return
            previous = self._return_metrics_cache.get(cache_key, {})
            merged = dict(previous) if isinstance(previous, dict) else {}
            merged.update(normalized)
            self._return_metrics_cache[cache_key] = merged
            self._return_metrics_fetching[cache_key] = False
        elif kind == 'heatmap':
            cache_key = (context.portfolio_id, context.heatmap_interval, context.heatmap_tickers)
            normalized = strip_market_data_keys(payload) if isinstance(payload, dict) else {}
            if context.heatmap_tickers and not normalized:
                return
            self._p4_heatmap_return_cache[cache_key] = normalized if isinstance(normalized, dict) else {}
            self._p4_heatmap_return_fetching[cache_key] = False
        elif kind == 'momentum':
            cache_key = self._p4_momentum_cache_key(
                context.momentum_timeframe,
                context.portfolio_id,
                shares_signature=context.shares_map,
                cash_amount=context.cash_amount,
            )
            self._momentum_metrics_cache[cache_key] = payload if isinstance(payload, dict) else {}
            self._momentum_metrics_fetching[cache_key] = False
        elif kind == 'metrics':
            shares_signature = tuple((symbol, shares) for symbol, shares in context.shares_map if shares > 0.0)
            if context.cash_amount > 0.0:
                shares_signature = tuple(sorted((*shares_signature, ('CASH', round(context.cash_amount, 2)))))
            cache_key = self._p4_portfolio_analytics_cache_key(
                portfolio_id=context.portfolio_id,
                benchmark_symbol=context.metrics_benchmark,
                lookback_key=context.metrics_lookback,
                shares_signature=shares_signature,
            )
            self._portfolio_analytics_cache[cache_key] = payload if isinstance(payload, dict) else {}
            self._portfolio_analytics_fetching[cache_key] = False

    def _p4_merge_quote_payload(self, payload: Any) -> int:
        """Merge quote-only data without dropping Dashboard charts, news, or targets."""
        quotes = payload.get('portfolio', {}) if isinstance(payload, dict) else {}
        if not isinstance(quotes, dict) or not quotes:
            return 0
        self._p4_latest_quote_overlay = {
            'completed_monotonic': monotonic(),
            'quotes': {
                str(ticker).upper(): dict(quote) if isinstance(quote, dict) else quote
                for ticker, quote in quotes.items()
            },
        }
        data = dict(getattr(self, 'last_data', None) or {})
        portfolio = dict(data.get('portfolio', {}) or {})
        portfolio.update(quotes)
        data['portfolio'] = portfolio
        self.last_data = data
        return len(quotes)

    def _p4_on_holdings_refresh_ready(self, token: Any, context: _PortfolioRefreshContext, result: Any) -> None:
        """Cache a pipeline result, render only the current visible tab, then promote pending work."""
        coordinator = self._p4_get_refresh_coordinator()
        contexts = getattr(self, '_p4_holdings_refresh_contexts', {})
        try:
            self._p4_apply_holdings_refresh_result(
                context,
                result,
                current_request=coordinator.is_current(token),
            )
        except Exception as exc:
            logger.exception('Portfolio holdings completion failed: %s', exc)
            self._p4_set_holdings_refresh_status(
                'Holdings refresh failed; showing previous prices.',
                status='negative',
            )
        finally:
            contexts.pop(token.generation, None)
            next_token = coordinator.complete(token)
            if next_token is not None:
                next_context = contexts.get(next_token.generation)
                if next_context is not None:
                    self._p4_start_holdings_refresh(next_token, next_context)
                    return
                coordinator.complete(next_token)
            self._p4_set_holdings_refresh_busy(False)
            if self._p4_page_visible():
                self._p4_render_deferred_subtab()

    def _p4_apply_holdings_refresh_result(
        self,
        context: _PortfolioRefreshContext,
        result: Any,
        *,
        current_request: bool,
    ) -> None:
        """Cache and conditionally render one completed holdings payload."""
        result = result if isinstance(result, dict) else {}
        quote_payload = result.get('quotes')
        self._p4_holdings_refresh_cache = getattr(self, '_p4_holdings_refresh_cache', {})
        self._p4_holdings_refresh_cache[context.signature] = result
        self._p4_cache_market_caps(result.get('market_caps'))
        self._p4_cache_visible_dependency(context, result.get('dependency'))

        quote_meta = market_data_meta(quote_payload)
        quote_errors = market_data_errors(quote_payload)
        usable_quotes = self._p4_quote_prices(quote_payload)
        inputs_current = self._p4_context_is_current(context)
        if current_request and inputs_current and usable_quotes:
            self._p4_merge_quote_payload(quote_payload)
            self._p4_dirty_subtabs = set(_P4_CONTENT_KEYS)
            if self._p4_page_visible():
                self._p4_render_deferred_subtab()

        freshness = str(quote_meta.get('freshness') or 'failed').lower()
        exceptions = list(result.get('exceptions') or [])
        component_issues = []
        for component_name, component_payload in (
            ('market caps', result.get('market_caps')),
            (str((result.get('dependency') or ('', None))[0] or ''), (result.get('dependency') or ('', None))[1]),
        ):
            if not component_name or not isinstance(component_payload, dict):
                continue
            component_meta = market_data_meta(component_payload)
            component_errors = market_data_errors(component_payload)
            if str(component_meta.get('freshness') or 'fresh').lower() in {'failed', 'partial', 'stale'}:
                component_issues.append(component_name)
            component_issues.extend(component_name for _error in component_errors)
        if current_request and inputs_current:
            if not context.tickers:
                self._p4_dirty_subtabs = set(_P4_CONTENT_KEYS)
                if self._p4_page_visible():
                    self._p4_render_deferred_subtab()
                self._p4_set_holdings_refresh_status('No stock holdings to refresh.', status='muted')
            elif not usable_quotes or freshness == 'failed':
                self._p4_set_holdings_refresh_status(
                    'Holdings refresh failed; showing previous prices.',
                    status='negative',
                )
            elif exceptions or quote_errors or component_issues or freshness in {'partial', 'stale'}:
                unavailable = len(exceptions) + len(quote_errors) + len(component_issues)
                suffix = f' ({unavailable} component issue(s))' if unavailable else ''
                self._p4_set_holdings_refresh_status(f'Holdings refreshed with partial data{suffix}.', status='warning')
            else:
                self._p4_set_holdings_refresh_status('Holdings refreshed.', status='positive')
        elif current_request:
            self._p4_set_holdings_refresh_status(
                'Holdings changed while refreshing; run Refresh Holdings again.',
                status='warning',
            )

    def _p4_mark_all_subtabs_dirty(self) -> None:
        self._p4_dirty_subtabs = set(_P4_CONTENT_KEYS)

    def _p4_render_deferred_subtab(self) -> None:
        """Render or fetch only the Portfolio sub-tab that is currently visible."""
        if not self._p4_page_visible():
            return
        scope = self._p4_active_content_key()
        dirty = getattr(self, '_p4_dirty_subtabs', None)
        if isinstance(dirty, set) and scope not in dirty:
            return
        data = getattr(self, 'last_data', None) or {'portfolio': {}}
        self.update_page4(
            data,
            render_scope=scope,
            mark_hidden_dirty=False,
        )

    def _p4_returns_cache_key(self, timeframe_key: Any, portfolio_id: Any = None) -> Any:
        """Build the cache key for one portfolio/timeframe/inclusion selection."""
        return returns_cache_key(
            portfolio_id or self.active_portfolio_id,
            timeframe_key,
            (self._p4_normalize_stock_symbol(ticker) for ticker in self._p4_weight_included_tickers()),
        )

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

    def _p4_momentum_cache_key(
        self,
        timeframe_key: Any,
        portfolio_id: Any = None,
        *,
        shares_signature: Any = None,
        cash_amount: Any = None,
    ) -> Any:
        """Build a momentum key that changes with tickers, shares, and cash."""
        pid = str(portfolio_id or self.active_portfolio_id)
        if shares_signature is None:
            shares_signature = tuple(sorted(self._p4_active_momentum_shares_map().items()))
        else:
            shares_signature = tuple(sorted(
                (self._p4_normalize_stock_symbol(symbol), round(float(shares or 0.0), 8))
                for symbol, shares in shares_signature
                if self._p4_normalize_stock_symbol(symbol)
            ))
        ticker_signature = tuple(sorted(symbol for symbol, _shares in shares_signature))
        cash = self._p4_active_cash_balance(pid) if cash_amount is None else cash_amount
        return (pid, str(timeframe_key), ticker_signature, shares_signature, round(float(cash or 0.0), 2))

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

    def _p4_cash_included_in_weight(self, portfolio_id: Any = None) -> bool:
        """Return whether brokerage cash participates in filtered allocation views."""
        entry = self._get_portfolio_entry(portfolio_id or getattr(self, 'active_portfolio_id', None))
        return entry.get('include_cash_in_weight') is not False

    def _p4_weight_included_cash_balance(self, portfolio_id: Any = None) -> float:
        """Return cash for filtered views, or zero when the cash position is unchecked."""
        if not self._p4_cash_included_in_weight(portfolio_id):
            return 0.0
        return self._p4_active_cash_balance(portfolio_id)

    def _p4_filtered_weight_map(self, metrics_map: Any) -> tuple[dict[Any, float], float]:
        """Return weights rebased across enabled stock and cash positions."""
        return filtered_weights(metrics_map, self._p4_weight_included_tickers(), self._p4_weight_included_cash_balance())

    def _p4_filtered_summary_values(self, metrics_map: Any) -> dict[str, float]:
        """Return net top-summary values for checked assets after margin debt."""
        return filtered_summary(
            metrics_map,
            self._p4_weight_included_tickers(),
            self._p4_weight_included_cash_balance(),
            self._p4_active_margin_debt(),
        )

    def _p4_signed_currency_text(self, value: Any) -> str:
        """Format a signed currency value with the sign before the dollar symbol."""
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        sign = '+' if amount >= 0.0 else '-'
        return f'{sign}${abs(amount):,.2f}'

    def _p4_update_filtered_summary_labels(self, metrics_map: Any) -> None:
        """Update Portfolio summary labels from checked stocks plus cash."""
        summary = self._p4_filtered_summary_values(metrics_map)
        if hasattr(self, 'p4_total_label'):
            self.p4_total_label.setText(f'Total:  ${summary["filtered_total"]:,.2f}  USD')
        self._p4_update_margin_utilization_label(metrics_map)
        stock_pl_label = getattr(self, 'p4_stock_pl_label', None)
        if stock_pl_label is None:
            return
        stock_pnl = summary['checked_stock_pnl']
        color = self.theme_color('accent_positive' if stock_pnl >= 0.0 else 'accent_negative')
        stock_pl_label.setText(f'Stock P&L:  {self._p4_signed_currency_text(stock_pnl)}')
        stock_pl_label.setStyleSheet(
            f'background: {self.theme_color("background_secondary")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 6px; padding: 6px 12px; '
            f'font-size: 13px; font-weight: bold; color: {color};'
        )

    def _p4_pie_chart_data(self, metrics_map: Any) -> tuple[dict[str, float], float]:
        """Return descending positive slices and total for the Pie Chart sub-tab."""
        weights, _gross_filtered_total = self._p4_filtered_weight_map(metrics_map)
        slices = {
            str(ticker): float(weight)
            for ticker, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True)
            if float(weight or 0.0) > 0.0
        }
        return slices, self._p4_filtered_summary_values(metrics_map)['filtered_total']

    def _p4_refresh_pie_chart(self, metrics_map: Any = None) -> None:
        """Refresh the checked-position pie chart and its filtered total."""
        if hasattr(self, 'p4_content_tabs') and (
            not self._p4_page_visible() or self._p4_active_content_key() != 'pie'
        ):
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('pie')
            return
        if metrics_map is None:
            data = getattr(self, 'last_data', None)
            portfolio = data.get('portfolio', {}) if isinstance(data, dict) else {}
            metrics_map, _total_value = self._p4_build_tracker_metrics_map(portfolio)
        slices, filtered_total = self._p4_pie_chart_data(metrics_map)
        chart = getattr(self, 'p4_pie_chart', None)
        if chart is not None:
            chart.set_data(slices)
            chart.setVisible(bool(slices))
        scroll_area = getattr(self, 'p4_pie_scroll_area', None)
        if scroll_area is not None:
            scroll_area.setVisible(bool(slices))
        empty_label = getattr(self, 'p4_pie_empty_label', None)
        if empty_label is not None:
            empty_label.setVisible(not slices)
        total_label = getattr(self, 'p4_pie_total_label', None)
        if total_label is not None:
            total_label.setText(f'Filtered Total:  ${filtered_total:,.2f}  USD')

    def _p4_apply_symbol_checkbox(self, row: int, ticker: Any) -> None:
        """Apply the persisted inclusion state to one visible Symbol item."""
        table = getattr(self, 'p4_table', None)
        item = table.item(int(row), P4_PORTFOLIO_COL_SYMBOL) if table is not None else None
        if item is None:
            return
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked
            if self._p4_position_included_in_weight(ticker)
            else Qt.CheckState.Unchecked
        )
        item.setToolTip('Include this position in Portfolio Weight, Pie Chart, Dip Finder, and Portfolio Heatmap')

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
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
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
            self.update_page4(last_data, defer_expensive_refresh=True)
        else:
            self._p4_update_cash_dependent_views()
        self._p4_refresh_personal_finance_tables()

    def _p4_active_margin_debt(self, portfolio_id: Any = None) -> float:
        """Return the selected portfolio's margin debt."""
        if portfolio_id is None or str(portfolio_id) == str(getattr(self, 'active_portfolio_id', '')):
            value = getattr(self, 'active_margin_debt', None)
            if value is None:
                getter = getattr(self, '_get_portfolio_entry', None)
                entry = getter(getattr(self, 'active_portfolio_id', None)) if callable(getter) else {}
                value = entry.get('margin_debt', 0.0) if isinstance(entry, dict) else 0.0
        else:
            getter = getattr(self, '_get_portfolio_entry', None)
            entry = getter(portfolio_id) if callable(getter) else {}
            value = entry.get('margin_debt', 0.0) if isinstance(entry, dict) else 0.0
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if not math.isfinite(amount):
            amount = 0.0
        return max(amount, 0.0)

    def _p4_set_active_margin_debt(self, value: Any) -> None:
        """Persist margin debt and refresh net totals and Personal Finance."""
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if not math.isfinite(amount):
            amount = 0.0
        amount = max(amount, 0.0)
        self.active_margin_debt = amount
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        entry['margin_debt'] = amount
        self._persist_all_portfolios()
        self._p4_update_margin_dependent_views()

    def _p4_sync_cash_input(self) -> None:
        """Reflect active cash and margin values into the summary editors."""
        control = getattr(self, 'p4_cash_input', None)
        if control is not None:
            control.blockSignals(True)
            control.setValue(self._p4_active_cash_balance())
            control.blockSignals(False)
        checkbox = getattr(self, 'p4_cash_include_checkbox', None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(self._p4_cash_included_in_weight())
            checkbox.blockSignals(False)
        margin_control = getattr(self, 'p4_margin_input', None)
        if margin_control is not None:
            margin_control.blockSignals(True)
            margin_control.setValue(self._p4_active_margin_debt())
            margin_control.blockSignals(False)

    def _p4_on_cash_balance_changed(self, value: float) -> None:
        """Handle user edits to brokerage cash."""
        self._p4_set_active_cash_balance(value)

    def _p4_on_margin_debt_changed(self, value: float) -> None:
        """Handle user edits to margin debt."""
        self._p4_set_active_margin_debt(value)

    def _p4_refresh_personal_finance_tables(self) -> None:
        """Rebuild Personal Finance totals, but only once page 6 has been built.

        Page 6 is lazily initialized, so calling ``_p6_populate_tables`` before its widgets
        exist raises. ``_call_if_page_initialized`` is missing on lightweight test probes that
        compose only the portfolio mixins, hence the defensive lookup.
        """
        call_if_initialized = getattr(self, '_call_if_page_initialized', None)
        if callable(call_if_initialized):
            call_if_initialized('_p6_populate_tables', force_progress_rebuild=True, page_attr='page6')
        elif hasattr(self, '_p6_populate_tables'):
            self._p6_populate_tables(force_progress_rebuild=True)

    def _p4_tracker_entry_cost(self, tracker_entry: Any) -> float:
        """Return one tracker entry's cost basis (shares times average price)."""
        entry = tracker_entry if isinstance(tracker_entry, dict) else {}
        try:
            cost = float(entry.get('shares', 0) or 0) * float(entry.get('avg_price', 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return cost if math.isfinite(cost) else 0.0

    def _p4_margin_utilization_percent(self, metrics_map: Any) -> float | None:
        """Return margin debt as a percent of gross assets for the active portfolio."""
        metrics = metrics_map if isinstance(metrics_map, dict) else {}
        stock_market_value = 0.0
        for row in metrics.values():
            try:
                stock_market_value += float((row or {}).get('market_value', 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        return margin_utilization(stock_market_value, self._p4_active_cash_balance(), self._p4_active_margin_debt())

    def _p4_update_margin_utilization_label(self, metrics_map: Any) -> None:
        """Colour-code the margin chip by how much of the account is borrowed."""
        label = getattr(self, 'p4_margin_pct_label', None)
        margin_input = getattr(self, 'p4_margin_input', None)
        if label is None and margin_input is None:
            return
        percent = self._p4_margin_utilization_percent(metrics_map)
        color = self._p4_market_cap_color_from_token(margin_health_color_token(percent))
        if label is not None:
            if percent is None:
                label.setVisible(False)
            else:
                label.setText(f'{percent:.1f}% used')
                label.setStyleSheet(f'color: {color}; font-size: 11px; font-weight: 700;')
                label.setVisible(True)
        if margin_input is not None:
            margin_input.setStyleSheet(
                f'QDoubleSpinBox[bt_role="cash_input"] {{ color: {color}; }}'
                if percent is not None else ''
            )

    def _p4_apply_trade_cash_flow(self, cost_delta: Any, ticker: Any = '') -> None:
        """Settle a position's cost-basis change against brokerage cash, then margin."""
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
        try:
            delta = float(cost_delta or 0.0)
        except (TypeError, ValueError):
            return
        if not math.isfinite(delta) or delta == 0.0:
            return
        previous_cash = self._p4_active_cash_balance()
        previous_margin = self._p4_active_margin_debt()
        cash, margin = settle_trade(previous_cash, previous_margin, delta)
        if cash == previous_cash and margin == previous_margin:
            return
        self.active_cash_balance = cash
        self.active_margin_debt = margin
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        entry['cash_balance'] = cash
        entry['margin_debt'] = margin
        if self.active_portfolio_id == self.main_portfolio_id:
            self.cash_balance = cash
        self._persist_all_portfolios()
        self._p4_sync_cash_input()
        self._p4_invalidate_momentum_cache()
        self._p4_invalidate_portfolio_analytics_cache()
        self._p4_refresh_personal_finance_tables()
        self._p4_report_trade_cash_flow(ticker, previous_cash - cash, margin - previous_margin)

    def _p4_report_trade_cash_flow(self, ticker: Any, cash_used: float, margin_added: float) -> None:
        """Announce an automatic cash/margin settlement so an accidental edit stays visible."""
        status_bar = getattr(self, 'status_bar', None)
        if status_bar is None or not hasattr(self, 'set_status_text'):
            return
        symbol = str(ticker or '').strip().upper()
        parts = []
        if abs(cash_used) >= 0.005:
            parts.append(f'{self._p4_signed_currency_text(-cash_used)} cash')
        if abs(margin_added) >= 0.005:
            parts.append(f'{self._p4_signed_currency_text(margin_added)} margin')
        if not parts:
            return
        prefix = f'{symbol}: ' if symbol else ''
        self.set_status_text(
            status_bar,
            f'{prefix}{", ".join(parts)}',
            status='warning' if margin_added > 0.0 else 'info',
        )

    def _p4_update_margin_dependent_views(self) -> None:
        """Refresh displays whose net values include margin debt."""
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        metrics_map, _net_total = self._p4_build_tracker_metrics_map(portfolio)
        self._p4_update_filtered_summary_labels(metrics_map)
        self._p4_refresh_pie_chart(metrics_map)
        self._p4_refresh_personal_finance_tables()

    def _p4_on_cash_weight_inclusion_changed(self, included: bool) -> None:
        """Persist the Cash checkbox and refresh only its filtered views."""
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        entry['include_cash_in_weight'] = bool(included)
        self._persist_all_portfolios(immediate=True)
        self._p4_refresh_weight_filter_views()

    def _p4_update_cash_dependent_views(self) -> None:
        """Refresh total and allocation displays when only cash changed."""
        portfolio = self.last_data.get('portfolio', {}) if isinstance(getattr(self, 'last_data', None), dict) else {}
        metrics_map, _total_value = self._p4_build_tracker_metrics_map(portfolio)
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
        self._p4_update_filtered_summary_labels(metrics_map)
        if hasattr(self, 'p4_weight_chart'):
            self._update_weight_chart(weights)
        self._p4_refresh_pie_chart(metrics_map)
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
            self._p4_page_visible()
            and
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
        self.p4_stock_positions_label.setText(f'Positions:  {numeric_count}')

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
        portfolio_id = str(self.active_portfolio_id)
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
                lambda result=payload, key=cache_key, pid=portfolio_id: self._on_portfolio_analytics_ready(key, pid, result)
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
        margin_debt = self._p4_active_margin_debt()
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
        if margin_debt > 0.0:
            lines.append(f'Margin Debt: ${margin_debt:,.2f}')
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
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
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
        previous_cost = self._p4_tracker_entry_cost(tracker_entry)
        tracker_entry['shares' if col == P4_PORTFOLIO_COL_SHARES else 'avg_price'] = val
        self._p4_apply_trade_cash_flow(self._p4_tracker_entry_cost(tracker_entry) - previous_cost, ticker)
        self._persist_all_portfolios()
        if self.last_data:
            self._recalc_tracker_row(row, ticker, self.last_data.get('portfolio', {}))

    def _p4_on_weight_inclusion_changed(self, item: Any) -> None:
        """Persist one Symbol checkbox and refresh only its filtered views."""
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
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
        """Refresh allocation, Dip Finder, and Heatmap after an inclusion toggle."""
        data = getattr(self, 'last_data', None)
        portfolio = data.get('portfolio', {}) if isinstance(data, dict) else {}
        metrics_map, _total_value = self._p4_build_tracker_metrics_map(portfolio)
        weights, _filtered_total = self._p4_filtered_weight_map(metrics_map)
        self._p4_update_filtered_summary_labels(metrics_map)
        table = getattr(self, 'p4_table', None)
        if table is not None:
            previous = table.blockSignals(True)
            sorting_enabled = table.isSortingEnabled()
            keep_sorting_disabled = self._p4_position_entry_is_active()
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
                if sorting_enabled and not keep_sorting_disabled:
                    table.setSortingEnabled(True)
                table.blockSignals(previous)
            self._p4_restore_position_entry_cell()
        if hasattr(self, 'p4_weight_chart'):
            self._update_weight_chart(weights)
        self._p4_refresh_pie_chart(metrics_map)
        if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)
        # Historical returns stay cached until the explicit holdings refresh.

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
        gross_market_value = stock_market_value + cash_balance
        margin_debt = self._p4_active_margin_debt()
        for item in metrics_map.values():
            cost = item['cost']
            market_value = item['market_value']
            item['weight'] = market_value / gross_market_value * 100 if gross_market_value else 0
            item['growth'] = item['dollar_gain'] / cost * 100 if cost else 0
        return metrics_map, gross_market_value - margin_debt

    def _recalc_tracker_row(self, row: Any, ticker: Any, portfolio: Any) -> None:
        """Handle recalc tracker row."""
        if self._p4_stock_editor_open():
            # Qt commits data before closing the editor, so on Tab this would rewrite the row
            # while an editor is still live. The deferred render picks the values up instead.
            self._p4_defer_positions_render()
            metrics_map, _total_market_value = self._p4_build_tracker_metrics_map(portfolio)
            self._p4_update_filtered_summary_labels(metrics_map)
            return
        metrics_map, _total_market_value = self._p4_build_tracker_metrics_map(portfolio)
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
        self._p4_update_filtered_summary_labels(metrics_map)
        if self._p4_position_entry_is_active():
            return
        self._update_weight_chart(weights)
        self._p4_refresh_pie_chart(metrics_map)
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
        """Return typed analyst target payloads keyed by normalized ticker."""
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
                targets[symbol] = dict(item)
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
        if getattr(self, '_p4_active_portfolio_is_combined', lambda: False)():
            return
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
        removed_cost = self._p4_tracker_entry_cost(
            tracker_data.get(matched_ticker) or tracker_data.get(clean_ticker)
        )
        tracker_data.pop(matched_ticker, None)
        tracker_data.pop(clean_ticker, None)
        self._p4_apply_trade_cash_flow(-removed_cost, clean_ticker)
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

        def _apply(xi: int, item: Any) -> None:
            value, color = item
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=pg.mkBrush(color), pen=pg.mkPen(color)))
            sign = '+' if value >= 0 else ''
            label = pg.TextItem(text=f'{sign}{value:.1f}%', color=color, anchor=(0.5, 1.0 if value >= 0 else 0.0))
            label.setPos(xi, value)
            pw.addItem(label)

        def _finish_chart() -> None:
            pw.addItem(pg.InfiniteLine(pos=0, angle=0, pen=self.theme_pen('chart_reference', width=1)))
            ax = pw.getAxis('bottom')
            ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
            ax.setStyle(tickFont=self.font())
            pw.showAxis('bottom')
            pw.showAxis('left')
            max_v = max((abs(value) for value in values)) if values else 1
            pw.setYRange(-max_v * 1.6, max_v * 1.6)
            pw.setXRange(-0.6, len(tickers) - 0.4)

        if len(tickers) <= 25:
            for xi, item in enumerate(zip(values, colors)):
                _apply(xi, item)
            _finish_chart()
            return

        generations = getattr(self, '_p4_returns_render_generations', {})
        generation = int(generations.get(timeframe_key, 0) or 0) + 1
        generations[timeframe_key] = generation
        self._p4_returns_render_generations = generations
        previous_updates = True
        prepared = False
        failed = False

        def _prepare() -> None:
            nonlocal previous_updates, prepared
            previous_updates = pw.updatesEnabled()
            prepared = True
            pw.setUpdatesEnabled(False)

        def _on_error(_exc: Exception) -> None:
            nonlocal failed
            failed = True
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('positions')

        def _finish() -> None:
            if prepared:
                pw.setUpdatesEnabled(previous_updates)
            if not failed and (
                generation == self._p4_returns_render_generations.get(timeframe_key)
                and self._p4_page_visible()
                and self._p4_active_content_key() == 'positions'
            ):
                _finish_chart()
                if previous_updates:
                    pw.update()
            else:
                self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
                self._p4_dirty_subtabs.add('positions')

        run_batched(
            self,
            ('portfolio.positions.returns', timeframe_key),
            zip(values, colors),
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            on_error=_on_error,
            is_current=lambda value: value == self._p4_returns_render_generations.get(timeframe_key),
            is_visible=lambda: self._p4_page_visible() and self._p4_active_content_key() == 'positions',
            max_items=25,
        )

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

        def _apply(xi: int, item: Any) -> None:
            _ticker, value, brush, pen = item
            pw.addItem(pg.BarGraphItem(x=[xi], height=[value], width=0.6, brush=brush, pen=pen))
            label = pg.TextItem(text=f'{value:.1f}%', color=self.theme_color('text_primary'), anchor=(0.5, 1.0))
            label.setPos(xi, value + label_offset)
            pw.addItem(label)

        def _finish_chart() -> None:
            ax = pw.getAxis('bottom')
            ax.setTicks([[(i, ticker) for i, ticker in enumerate(tickers)]])
            ax.setStyle(tickFont=self.font())
            pw.showAxis('bottom')
            pw.showAxis('left')
            pw.setYRange(0, max_value + label_offset + max(max_value * 0.15, 0.5))
            pw.setXRange(-0.6, len(tickers) - 0.4)

        if len(tickers) <= 25:
            for xi, item in enumerate(zip(tickers, values, brushes, pens)):
                _apply(xi, item)
            _finish_chart()
            return

        generation = int(getattr(self, '_p4_weight_render_generation', 0) or 0) + 1
        self._p4_weight_render_generation = generation
        previous_updates = True
        prepared = False
        failed = False

        def _prepare() -> None:
            nonlocal previous_updates, prepared
            previous_updates = pw.updatesEnabled()
            prepared = True
            pw.setUpdatesEnabled(False)

        def _on_error(_exc: Exception) -> None:
            nonlocal failed
            failed = True
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('positions')

        def _finish() -> None:
            if prepared:
                pw.setUpdatesEnabled(previous_updates)
            if not failed and (
                generation == getattr(self, '_p4_weight_render_generation', 0)
                and self._p4_page_visible()
                and self._p4_active_content_key() == 'positions'
            ):
                _finish_chart()
                if previous_updates:
                    pw.update()
            else:
                self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
                self._p4_dirty_subtabs.add('positions')

        run_batched(
            self,
            'portfolio.positions.weights',
            zip(tickers, values, brushes, pens),
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            on_error=_on_error,
            is_current=lambda value: value == getattr(self, '_p4_weight_render_generation', 0),
            is_visible=lambda: self._p4_page_visible() and self._p4_active_content_key() == 'positions',
            max_items=25,
        )

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
        tickers = list(self._p4_active_tickers())
        shares_map = self._p4_active_momentum_shares_map()
        cash_amount = self._p4_active_cash_balance()
        cache_key = self._p4_momentum_cache_key(
            timeframe_key,
            portfolio_id,
            shares_signature=tuple(shares_map.items()),
            cash_amount=cash_amount,
        )
        if self._momentum_metrics_fetching.get(cache_key, False):
            return
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
                lambda result=payload, key=timeframe_key, pid=portfolio_id, requested_cache_key=cache_key: self._on_momentum_ready(
                    key,
                    pid,
                    result,
                    requested_cache_key,
                )
            )

        self._p4_submit_background_task(_run)

    def _on_momentum_ready(
        self,
        timeframe_key: Any,
        portfolio_id: Any,
        payload: Any,
        cache_key: Any = None,
    ) -> None:
        """Handle portfolio momentum data becoming ready."""
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Portfolio momentum', payload, symbols=self._p4_active_tickers())
        cache_key = cache_key or self._p4_momentum_cache_key(timeframe_key, portfolio_id)
        self._momentum_metrics_fetching[cache_key] = False
        self._momentum_metrics_cache[cache_key] = payload
        current_key = self._p4_momentum_cache_key(timeframe_key, self.active_portfolio_id)
        if (
            cache_key == current_key
            and str(portfolio_id) == str(self.active_portfolio_id)
            and timeframe_key == self._active_momentum_timeframe
            and self._p4_active_content_key() == 'momentum'
            and self._p4_page_visible()
        ):
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
        if self._p4_active_content_key() != 'momentum' or not self._p4_page_visible():
            return
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
        results = strip_market_data_keys(results) if isinstance(results, dict) else {}
        cache_key = cache_key or self._p4_returns_cache_key(timeframe_key, portfolio_id)
        self._return_metrics_fetching[cache_key] = False
        previous = self._return_metrics_cache.get(cache_key, {})
        merged_results = dict(previous) if isinstance(previous, dict) else {}
        if isinstance(results, dict):
            merged_results.update(results)
        self._return_metrics_cache[cache_key] = merged_results
        current_cache_key = self._p4_returns_cache_key(timeframe_key, portfolio_id)
        if (
            cache_key == current_cache_key
            and str(portfolio_id) == str(self.active_portfolio_id)
            and timeframe_key == self._active_return_timeframe
            and self._p4_active_content_key() == 'positions'
            and self._p4_page_visible()
        ):
            self._update_returns_chart(timeframe_key, merged_results)

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
        if self._p4_page_visible() and self._p4_active_content_key() == 'positions':
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
        else:
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('positions')
        queued = list(getattr(self, '_mktcap_queued_tickers', set()))
        self._mktcap_queued_tickers = set()
        if queued:
            remaining = [ticker for ticker in queued if str(ticker or '').strip().upper() not in request_tickers]
            self._fetch_market_caps(remaining)

    def _p4_finalize_positions_table_render(self, selected_symbol: str='') -> None:
        """Restore Portfolio table affordances after a complete row render."""
        self._p4_apply_visible_symbol_checkboxes()
        if self._p4_position_entry_is_active():
            self._p4_restore_position_entry_cell()
        elif selected_symbol:
            selected_row = self._p4_find_stock_row(selected_symbol)
            if selected_row >= 0:
                self.p4_table.selectRow(selected_row)
        if hasattr(self, '_p4_update_remove_stock_button_state'):
            self._p4_update_remove_stock_button_state()
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('stock')

    def _p4_render_positions_rows(self, rows: Any) -> bool:
        """Render large holdings tables in short, navigation-safe GUI slices."""
        if self._p4_stock_editor_open():
            # Replacing items would close the open editor and discard uncommitted text.
            self._p4_defer_positions_render()
            return False
        normalized_rows = list(rows or [])
        selected_symbol = ''
        selection_model = self.p4_table.selectionModel()
        if (
            selection_model is not None
            and selection_model.hasSelection()
            and hasattr(self, '_p4_selected_stock_ticker')
        ):
            selected_symbol = self._p4_selected_stock_ticker()
        if len(normalized_rows) <= 50:
            render_table_rows(self.p4_table, normalized_rows)
            self._p4_finalize_positions_table_render(selected_symbol)
            return False

        generation = int(getattr(self, '_p4_positions_render_generation', 0) or 0) + 1
        self._p4_positions_render_generation = generation
        previous_updates = True
        previous_signals = False
        sorting_enabled = False
        prepared = False

        def _prepare() -> None:
            nonlocal previous_updates, previous_signals, sorting_enabled, prepared
            previous_updates = self.p4_table.updatesEnabled()
            previous_signals = self.p4_table.blockSignals(True)
            sorting_enabled = bool(self.p4_table.isSortingEnabled())
            prepared = True
            self.p4_table.setSortingEnabled(False)
            self.p4_table.setUpdatesEnabled(False)
            self.p4_table.setRowCount(len(normalized_rows))

        def _apply(row_index: int, row: Any) -> None:
            render_table_row(self.p4_table, row_index, row)

        def _finish() -> None:
            if not prepared:
                return
            self.p4_table.setUpdatesEnabled(previous_updates)
            if sorting_enabled and not self._p4_position_entry_is_active():
                self.p4_table.setSortingEnabled(True)
            self.p4_table.blockSignals(previous_signals)
            if previous_updates:
                self.p4_table.viewport().update()
            render_current = (
                generation == getattr(self, '_p4_positions_render_generation', 0)
                and self._p4_page_visible()
                and self._p4_active_content_key() == 'positions'
            )
            if render_current:
                self._p4_finalize_positions_table_render(selected_symbol)
            else:
                self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
                self._p4_dirty_subtabs.add('positions')

        def _on_error(_exc: Exception) -> None:
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('positions')

        run_batched(
            self,
            'portfolio.positions.rows',
            normalized_rows,
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            on_error=_on_error,
            is_current=lambda value: value == getattr(self, '_p4_positions_render_generation', 0),
            is_visible=lambda: self._p4_page_visible() and self._p4_active_content_key() == 'positions',
        )
        return True

    def update_page4(
        self,
        data: Any,
        *,
        preserve_visible_order: bool | None = None,
        defer_expensive_refresh: bool=False,
        render_scope: str | None = None,
        mark_hidden_dirty: bool=True,
    ) -> None:
        """Update the visible Portfolio sub-tab and defer every hidden sub-tab."""
        dirty = set(getattr(self, '_p4_dirty_subtabs', set()))
        if mark_hidden_dirty:
            dirty.update(_P4_CONTENT_KEYS)
        self._p4_dirty_subtabs = dirty
        if not self._p4_page_visible():
            return
        scope = str(render_scope or self._p4_active_content_key()).strip().lower()
        if scope not in _P4_CONTENT_KEYS:
            scope = 'positions'
        portfolio = data.get('portfolio', {})
        tickers = self._p4_active_tickers()
        metrics_map, _total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        self._p4_update_stock_positions_label(len(tickers))
        self._p4_update_filtered_summary_labels(metrics_map)

        if scope == 'pie':
            self._p4_refresh_pie_chart(metrics_map)
            self._p4_dirty_subtabs.discard(scope)
            return
        if scope == 'heatmap':
            if defer_expensive_refresh:
                return
            interval_key = str(getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').lower()
            cache_key = self._p4_heatmap_returns_cache_key(interval_key)
            if (
                self._p4_holdings_refresh_running()
                and not self._p4_heatmap_uses_snapshot_returns(interval_key)
                and cache_key not in getattr(self, '_p4_heatmap_return_cache', {})
            ):
                return
            if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
                self._p4_refresh_portfolio_heatmap_view(reset_view=False)
            self._p4_dirty_subtabs.discard(scope)
            return
        if scope == 'momentum':
            active_cache_key = self._p4_momentum_cache_key(self._active_momentum_timeframe)
            cash_balance = self._p4_active_cash_balance()
            if not tickers and cash_balance <= 0.0:
                payload = self._p4_empty_momentum_payload('No portfolio holdings available')
                self._momentum_metrics_cache[active_cache_key] = payload
                self._momentum_metrics_fetching[active_cache_key] = False
                self._update_momentum_chart(self._active_momentum_timeframe, payload)
            elif active_cache_key in self._momentum_metrics_cache:
                self._update_momentum_chart(
                    self._active_momentum_timeframe,
                    self._momentum_metrics_cache.get(active_cache_key, {}),
                )
            elif not defer_expensive_refresh:
                if self._p4_holdings_refresh_running():
                    return
                self._fetch_momentum_for_timeframe(self._active_momentum_timeframe)
            self._p4_dirty_subtabs.discard(scope)
            return
        if scope == 'metrics':
            cache_key = self._p4_portfolio_analytics_cache_key()
            if defer_expensive_refresh:
                return
            if (
                cache_key not in getattr(self, '_portfolio_analytics_cache', {})
                and self._p4_holdings_refresh_running()
            ):
                return
            if not defer_expensive_refresh:
                self._p4_refresh_portfolio_metrics_view()
            self._p4_dirty_subtabs.discard(scope)
            return

        if self._p4_stock_editor_open():
            # Rendering now would replace the item under the open editor, closing it and
            # discarding uncommitted text. Summary labels above stay live; the table waits.
            self._p4_defer_positions_render()
            return
        active_entry = self._p4_position_entry_is_active()
        preserve_order = active_entry if preserve_visible_order is None else bool(preserve_visible_order)
        defer_refresh = bool(defer_expensive_refresh or active_entry)
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
        self._p4_render_positions_rows(rows)

        if defer_refresh:
            self._p4_dirty_subtabs.discard(scope)
            return
        self._update_weight_chart(weights)

        active_cache_key = self._p4_returns_cache_key(self._active_return_timeframe)
        included_tickers = self._p4_weight_included_tickers()
        returns_deferred = False
        if not included_tickers:
            self._return_metrics_cache[active_cache_key] = {}
            self._return_metrics_fetching[active_cache_key] = False
            self._update_returns_chart(self._active_return_timeframe, {})
        elif active_cache_key in self._return_metrics_cache:
            self._update_returns_chart(
                self._active_return_timeframe,
                self._return_metrics_cache.get(active_cache_key, {}),
            )
        elif self._p4_holdings_refresh_running():
            returns_deferred = True
        else:
            self._fetch_returns_for_timeframe(self._active_return_timeframe)
        if not self._p4_holdings_refresh_running():
            self._fetch_market_caps(sorted_tickers)
        if not returns_deferred:
            self._p4_dirty_subtabs.discard(scope)
