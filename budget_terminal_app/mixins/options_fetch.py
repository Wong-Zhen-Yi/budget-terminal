from __future__ import annotations
import time
from typing import Any
from ..compat import *
from budget_terminal_app.services.options_data import OptionsMarketDataService

class OptionsFetchMixin:
    def _get_options_data_service(self) -> OptionsMarketDataService:
        """Return the shared options market-data service for this window session."""
        service = getattr(self, '_options_data_service', None)
        cache_manager = self._get_cache_manager()
        if service is None or getattr(service, 'cache_manager', None) is not cache_manager:
            service = OptionsMarketDataService(
                cache_manager,
                expiry_memory_cache=getattr(self, '_options_expiry_memory_cache', {}),
                chain_memory_cache=getattr(self, '_option_chain_memory_cache', {}),
                expiry_memory_ttl_seconds=getattr(self, '_options_expiry_memory_cache_ttl', 900.0),
                chain_memory_ttl_seconds=getattr(self, '_option_chain_memory_cache_ttl', 60.0),
            )
            self._options_data_service = service
        return service

    def _get_cached_options_expiries(self, ticker: Any) -> Any:
        """Return cached expiry dates from memory or SQLite before hitting the network."""
        ticker_key = str(ticker or '').strip().upper()
        if not ticker_key:
            return None
        payload = self._get_options_data_service().fetch_expiries_payload(ticker_key)
        self._last_options_expiry_payload = payload
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Options expiries', payload, symbols=[ticker_key])
        expiries = payload.get('expiries') if isinstance(payload, dict) else None
        return list(expiries) if expiries else None

    def _save_cached_options_expiries(self, ticker: Any, expiries: Any) -> None:
        """Persist expiry dates into the short-lived memory cache and SQLite."""
        ticker_key = str(ticker or '').strip().upper()
        expiry_list = [str(expiry) for expiry in list(expiries or []) if expiry]
        if not ticker_key or not expiry_list:
            return
        self._options_expiry_memory_cache[ticker_key] = (time.time(), expiry_list)
        self._get_cache_manager().save_options_expiries(ticker_key, expiry_list)

    def _get_cached_option_chain(self, ticker: Any, expiry: Any) -> Any:
        """Return one option chain for a ticker/expiry, reusing memory and SQLite caches."""
        ticker_key = str(ticker or '').strip().upper()
        expiry_key = str(expiry or '').strip()
        if not ticker_key or not expiry_key:
            return None
        payload = self._get_options_data_service().fetch_chain_payload(ticker_key, expiry_key)
        self._last_option_chain_payload = payload
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Options chain', payload, symbols=[ticker_key])
        chain_df = payload.get('chain') if isinstance(payload, dict) else None
        if chain_df is None or chain_df.empty:
            return None
        return chain_df.copy()

    def _submit_options_fetch(self, fn: Any) -> None:
        """Run bounded background work for options fetches."""
        executor = getattr(self, '_options_fetch_executor', None)
        if executor is None and hasattr(self, '_ensure_options_fetch_executor'):
            executor = self._ensure_options_fetch_executor()
        if executor is None:
            threading.Thread(target=fn, daemon=True).start()
            return
        executor.submit(fn)

    def _resolve_active_option_row(self, row: Any, ticker: Any, portfolio_id: Any=None) -> Any:
        """Return a still-valid row index for an async options callback."""
        expected_portfolio_id = str(portfolio_id or getattr(self, 'active_portfolio_id', '')).strip()
        current_portfolio_id = str(getattr(self, 'active_portfolio_id', '')).strip()
        if expected_portfolio_id and current_portfolio_id and expected_portfolio_id != current_portfolio_id:
            return None
        try:
            row_index = int(row)
        except (TypeError, ValueError):
            return None
        t = self.p4_opt_table
        if row_index < 0 or row_index >= t.rowCount() or row_index >= len(self.options_data):
            return None
        ticker_item = t.item(row_index, 0)
        current_ticker = ticker_item.text().strip().upper() if ticker_item else ''
        if current_ticker != str(ticker or '').strip().upper():
            return None
        return row_index

    def _resolve_active_option_row_by_id(self, row_id: Any, ticker: Any=None, portfolio_id: Any=None) -> Any:
        """Resolve a live options-table row from a stable position id."""
        expected_portfolio_id = str(portfolio_id or getattr(self, 'active_portfolio_id', '')).strip()
        current_portfolio_id = str(getattr(self, 'active_portfolio_id', '')).strip()
        if expected_portfolio_id and current_portfolio_id and expected_portfolio_id != current_portfolio_id:
            return None
        row_id_text = str(row_id or '').strip()
        if not row_id_text:
            return None
        expected_ticker = str(ticker or '').strip().upper()
        for row_index, pos in enumerate(self.options_data):
            if str(pos.get('row_id', '') or '').strip() != row_id_text:
                continue
            if expected_ticker:
                current_ticker = str(pos.get('ticker', '') or '').strip().upper()
                if current_ticker != expected_ticker:
                    return None
            if row_index >= self.p4_opt_table.rowCount():
                return None
            ticker_item = self.p4_opt_table.item(row_index, 0)
            if expected_ticker and ticker_item and ticker_item.text().strip().upper() != expected_ticker:
                return None
            return row_index
        return None

    def _apply_option_market_data(self, row: Any, data: Any) -> None:
        """Persist fetched option data into the row and table."""
        if row >= len(self.options_data):
            return
        t = self.p4_opt_table
        self.options_data[row]['current_price'] = data['price']
        self.options_data[row]['iv'] = data['iv']
        self.options_data[row]['strike'] = data['strike']
        self.options_data[row]['volume'] = data.get('volume', 0.0)
        self.options_data[row]['open_interest'] = data.get('open_interest', 0.0)
        if data['delta'] is not None:
            self.options_data[row]['delta'] = data['delta']
        self._save_active_options_data()
        normal_color = self.theme_qcolor('text_primary')
        if t.item(row, 3):
            t.item(row, 3).setText(f"{data['strike']:.2f}")
            t.item(row, 3).setForeground(normal_color)
        if t.item(row, 6):
            t.item(row, 6).setText(f"{data['price']:.2f}")
            t.item(row, 6).setForeground(normal_color)
        if t.item(row, 7):
            t.item(row, 7).setText(self._format_option_count(data.get('volume', 0.0)))
            t.item(row, 7).setForeground(normal_color)
        if t.item(row, 8):
            t.item(row, 8).setText(self._format_option_count(data.get('open_interest', 0.0)))
            t.item(row, 8).setForeground(normal_color)
        if t.item(row, 9):
            t.item(row, 9).setText(f"{data['iv'] * 100:.1f}%")
            t.item(row, 9).setForeground(normal_color)

    def _clean_option_number(self, value: Any, default: float=0.0) -> float:
        """Return a finite float from Yahoo option-chain values."""
        if value is None:
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(number) or math.isinf(number):
            return default
        return number

    def _fetch_option_expiries_sync(self, row: Any, ticker: Any) -> None:
        """Synchronous version of expiry fetch for use within a worker thread."""
        try:
            portfolio_id = getattr(self, 'active_portfolio_id', '')
            row_id = ''
            if 0 <= row < len(self.options_data):
                row_id = str(self.options_data[row].get('row_id', '') or '').strip()
            exps = self._fetch_option_expiries_list_sync(ticker)
            if exps:
                self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker, list(exps), portfolio_id))
        except Exception as e:
            logger.error(f'Sync expiry fetch failed for {ticker}: {e}')
            if hasattr(self, '_record_data_health_exception'):
                self._record_data_health_exception('Options expiries', e, symbols=[ticker])

    def _fetch_option_expiries_list_sync(self, ticker: Any) -> list[str]:
        """Fetch option expiries from explicit input without touching Qt widgets."""
        ticker_key = str(ticker or '').strip().upper()
        if not ticker_key:
            return []
        payload = self._get_options_data_service().fetch_expiries_payload(ticker_key)
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('Options expiries', payload, symbols=[ticker_key])
        expiries = payload.get('expiries') if isinstance(payload, dict) else None
        return [str(expiry) for expiry in list(expiries or []) if expiry]

    def _fetch_option_quote_for_values_sync(
        self,
        ticker: Any,
        expiry: Any,
        strike: Any,
        strategy: Any,
        *,
        underlying_price: Any=0.0,
    ) -> dict[str, Any]:
        """Fetch one option quote from explicit values without reading UI state."""
        ticker_key = str(ticker or '').strip().upper()
        expiry_key = str(expiry or '').strip()
        if not ticker_key:
            return {'error': 'Ticker Err'}
        if not expiry_key:
            return {'error': 'Incomplete Data'}
        try:
            data_package = self._get_options_data_service().fetch_option_quote_payload(
                ticker_key,
                expiry_key,
                strike,
                strategy,
                underlying_price=underlying_price,
            )
            if hasattr(self, '_record_data_health_payload'):
                self._record_data_health_payload('Option quote', data_package, symbols=[ticker_key])
            return data_package
        except Exception as e:
            logger.debug(f'Sync price fetch failed for {ticker_key}: {e}')
            if hasattr(self, '_record_data_health_exception'):
                self._record_data_health_exception('Option quote', e, symbols=[ticker_key])
            err_msg = str(e)
            if 'expired' in err_msg.lower():
                err_msg = 'Expired'
            elif 'not found' in err_msg.lower():
                err_msg = 'Ticker Err'
            else:
                err_msg = 'Fetch Err'
            return {'error': err_msg}

    def _fetch_single_option_price_sync(self, row: Any) -> None:
        """Synchronous version of price fetch for use within a worker thread."""
        if row >= len(self.options_data):
            return
        pos = self.options_data[row]
        row_id = str(pos.get('row_id', '') or '').strip()
        portfolio_id = getattr(self, 'active_portfolio_id', '')
        ticker = pos.get('ticker', '').strip().upper()
        expiry = pos.get('expiry', '').strip()
        strike = float(pos.get('strike', 0.0) or 0.0)
        strategy = pos.get('strategy', 'Calls')
        if not ticker:
            return
        if not expiry:
            data_package = {'error': 'Incomplete Data'}
            self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))
            return
        underlying_price = 0.0
        if self.last_data and 'portfolio' in self.last_data:
            underlying_price = float(self.last_data['portfolio'].get(ticker, {}).get('price', 0.0) or 0.0)
        data_package = self._fetch_option_quote_for_values_sync(
            ticker,
            expiry,
            strike,
            strategy,
            underlying_price=underlying_price,
        )
        self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))

    def _fetch_single_option_price(self, row: Any) -> None:
        """Background fetch of the current price for a single option row."""
        self._submit_options_fetch(lambda: self._fetch_single_option_price_sync(row))

    def _update_option_price_ui(self, row_id: Any, ticker: Any, data: Any, portfolio_id: Any=None) -> None:
        """Handle update option price ui."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is None:
            return
        t = self.p4_opt_table
        t.blockSignals(True)
        error = data.get('error')
        if error:
            err_color = self.theme_qcolor('accent_negative')
            if t.item(row, 6):
                t.item(row, 6).setText(error)
                t.item(row, 6).setForeground(err_color)
            if t.item(row, 7):
                t.item(row, 7).setText('N/A')
                t.item(row, 7).setForeground(self.theme_qcolor('text_muted'))
            if t.item(row, 8):
                t.item(row, 8).setText('N/A')
                t.item(row, 8).setForeground(self.theme_qcolor('text_muted'))
            if t.item(row, 9):
                t.item(row, 9).setText('N/A')
                t.item(row, 9).setForeground(self.theme_qcolor('text_muted'))
        else:
            self._apply_option_market_data(row, data)
        t.blockSignals(False)
        self._recalc_options_row(row)

    def _fetch_option_expiries(self, row_id: Any, ticker: Any) -> None:
        """Background fetch of available expiry dates for ticker; populates col 2 combo."""

        def _run() -> None:
            """Handle run."""
            try:
                portfolio_id = getattr(self, 'active_portfolio_id', '')
                ticker_clean = ticker.strip().upper()
                exps = self._get_cached_options_expiries(ticker_clean)
                if exps:
                    logger.info(f'Loaded {len(exps)} expiries for {ticker_clean} from cache')
                    self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker_clean, list(exps), portfolio_id))
                    return
                logger.info(f'Fetching options expiries for {ticker_clean} from API')
                ticker_obj = yf.Ticker(ticker_clean)
                exps = ticker_obj.options
                if exps:
                    self._save_cached_options_expiries(ticker_clean, exps)
                    logger.info(f'Found {len(exps)} expiries for {ticker_clean}')
                    self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker_clean, list(exps), portfolio_id))
                else:
                    logger.warning(f'No expiries found for {ticker_clean}')
                    self._invoke_main.emit(lambda: self._reset_expiry_placeholder(row_id, ticker_clean, 'N/A', portfolio_id))
            except Exception as ex:
                logger.error(f'Options expiry fetch failed for {ticker}: {ex}', exc_info=True)
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception('Options expiries', ex, symbols=[ticker])
                self._invoke_main.emit(lambda: self._reset_expiry_placeholder(row_id, ticker, 'N/A', portfolio_id))
        self._submit_options_fetch(_run)

    def _reset_expiry_placeholder(self, row_id: Any, ticker: Any, text: Any, portfolio_id: Any=None) -> None:
        """Reset the expiry cell to a plain text item when no options are available."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is None:
            return
        t = self.p4_opt_table
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        item = QTableWidgetItem(text)
        item.setFlags(ro_flags)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(self.theme_qcolor('text_muted'))
        t.blockSignals(True)
        t.setItem(row, 2, item)
        t.blockSignals(False)

    def _set_expiry_combo(
        self,
        row_id: Any,
        ticker: Any,
        expiries: Any,
        portfolio_id: Any=None,
        *,
        selected_expiry: Any=None,
        fetch_price: bool=True,
    ) -> None:
        """Replace the expiry cell with a QComboBox populated with fetched dates + DTE."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is None:
            return
        t = self.p4_opt_table
        expiries = [str(e) for e in expiries if e]
        if not expiries:
            self._reset_expiry_placeholder(row_id, ticker, 'N/A', portfolio_id)
            return
        saved = str(selected_expiry or '').strip() or (self.options_data[row].get('expiry', '') if row < len(self.options_data) else '')
        today = datetime.date.today()
        combo = QComboBox()
        combo.setMaxVisibleItems(12)
        for exp in expiries:
            try:
                ed = datetime.datetime.strptime(exp, '%Y-%m-%d').date()
                dte = (ed - today).days
                combo.addItem(f'{exp}  ({dte}d)', exp)
            except ValueError:
                combo.addItem(exp, exp)
        combo.setMinimumHeight(22)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        try:
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        except AttributeError:
            pass
        if hasattr(self, '_p4_center_option_combo'):
            self._p4_center_option_combo(combo)
        if saved in expiries:
            combo.setCurrentIndex(expiries.index(saved))
            if row < len(self.options_data) and self.options_data[row].get('expiry') != saved:
                self.options_data[row]['expiry'] = saved
                self._save_active_options_data()
        elif row < len(self.options_data):
            self.options_data[row]['expiry'] = expiries[0]
            if not self.options_data[row].get('open_date'):
                self.options_data[row]['open_date'] = today.isoformat()
            self._save_active_options_data()
        combo.currentIndexChanged.connect(lambda idx, row_index=row, expected_ticker=ticker: self._on_expiry_combo_changed_by_row(row_index, expected_ticker, combo))
        t.blockSignals(True)
        t.setItem(row, 2, QTableWidgetItem(''))
        t.setCellWidget(row, 2, combo)
        t.blockSignals(False)
        self._recalc_options_row(row)
        if fetch_price:
            self._fetch_single_option_price(row)
