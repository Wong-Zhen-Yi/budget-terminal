from __future__ import annotations
from typing import Any
from ..compat import *

class OptionsFetchMixin:

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
        if data['delta'] is not None:
            self.options_data[row]['delta'] = data['delta']
        self._save_active_options_data()
        normal_color = self.theme_qcolor('text_primary')
        if t.item(row, 4):
            t.item(row, 4).setText(f"{data['strike']:.2f}")
            t.item(row, 4).setForeground(normal_color)
        if t.item(row, 7):
            t.item(row, 7).setText(f"{data['price']:.2f}")
            t.item(row, 7).setForeground(normal_color)
        if t.item(row, 8):
            t.item(row, 8).setText(f"{data['iv'] * 100:.1f}%")
            t.item(row, 8).setForeground(normal_color)
        if data['delta'] is not None and t.item(row, 9):
            t.item(row, 9).setText(f"{data['delta']:.3f}")
            t.item(row, 9).setForeground(normal_color)

    def _fetch_option_expiries_sync(self, row: Any, ticker: Any) -> None:
        """Synchronous version of expiry fetch for use within a worker thread."""
        try:
            portfolio_id = getattr(self, 'active_portfolio_id', '')
            row_id = ''
            if 0 <= row < len(self.options_data):
                row_id = str(self.options_data[row].get('row_id', '') or '').strip()
            cache = CacheManager()
            exps = cache.get_options_expiries(ticker)
            if exps is None:
                with YF_LOCK:
                    t_obj = yf.Ticker(ticker)
                    exps = t_obj.options
                if exps:
                    cache.save_options_expiries(ticker, exps)
            if exps:
                self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker, list(exps), portfolio_id))
        except Exception as e:
            logger.error(f'Sync expiry fetch failed for {ticker}: {e}')

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
        try:
            with YF_LOCK:
                t_obj = yf.Ticker(ticker)
                chain = t_obj.option_chain(expiry)
            is_call = 'Call' in strategy or 'Calls' == strategy
            df = chain.calls if is_call else chain.puts
            if df.empty:
                data_package = {'error': 'No Data'}
                self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))
                return
            if strike <= 0:
                underlying_price = 0.0
                if self.last_data and 'portfolio' in self.last_data:
                    underlying_price = float(self.last_data['portfolio'].get(ticker, {}).get('price', 0.0) or 0.0)
                if underlying_price > 0:
                    diffs = (df['strike'] - underlying_price).abs()
                else:
                    diffs = (df['strike']).abs()
            else:
                diffs = (df['strike'] - strike).abs()
            best_match_idx = diffs.argsort()[:1]
            match = df.iloc[best_match_idx]
            if not match.empty:
                m = match.iloc[0]
                actual_strike = float(m.get('strike', 0))
                if strike > 0 and abs(actual_strike - strike) > 0.01:
                    logger.debug(f'Closest strike for {ticker} {expiry} {strike} is {actual_strike}')
                bid = float(m.get('bid', 0))
                ask = float(m.get('ask', 0))
                last = float(m.get('lastPrice', 0))
                new_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                iv = float(m.get('impliedVolatility', 0))
                delta = float(m.get('delta', 0)) if 'delta' in m else None
                data_package = {'price': new_price, 'iv': iv, 'delta': delta, 'strike': actual_strike}
                self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))
            else:
                data_package = {'error': 'Strike Not Found'}
                self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))
        except Exception as e:
            logger.debug(f'Sync price fetch failed for {ticker}: {e}')
            err_msg = str(e)
            if 'expired' in err_msg.lower():
                err_msg = 'Expired'
            elif 'not found' in err_msg.lower():
                err_msg = 'Ticker Err'
            else:
                err_msg = 'Fetch Err'
            data_package = {'error': err_msg}
            self._invoke_main.emit(lambda: self._update_option_price_ui(row_id, ticker, data_package, portfolio_id))

    def _fetch_single_option_price(self, row: Any) -> None:
        """Background fetch of the current price for a single option row."""
        threading.Thread(target=lambda: self._fetch_single_option_price_sync(row), daemon=True).start()

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
            if t.item(row, 7):
                t.item(row, 7).setText(error)
                t.item(row, 7).setForeground(err_color)
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
                cache = CacheManager()
                exps = cache.get_options_expiries(ticker_clean)
                if exps:
                    logger.info(f'Loaded {len(exps)} expiries for {ticker_clean} from cache')
                    self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker_clean, list(exps), portfolio_id))
                    return
                logger.info(f'Fetching options expiries for {ticker_clean} from API')
                ticker_obj = yf.Ticker(ticker_clean)
                exps = ticker_obj.options
                if exps:
                    cache.save_options_expiries(ticker_clean, exps)
                    logger.info(f'Found {len(exps)} expiries for {ticker_clean}')
                    self._invoke_main.emit(lambda: self._set_expiry_combo(row_id, ticker_clean, list(exps), portfolio_id))
                else:
                    logger.warning(f'No expiries found for {ticker_clean}')
                    self._invoke_main.emit(lambda: self._reset_expiry_placeholder(row_id, ticker_clean, 'N/A', portfolio_id))
            except Exception as ex:
                logger.error(f'Options expiry fetch failed for {ticker}: {ex}', exc_info=True)
                self._invoke_main.emit(lambda: self._reset_expiry_placeholder(row_id, ticker, 'N/A', portfolio_id))
        threading.Thread(target=_run, daemon=True).start()

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

    def _set_expiry_combo(self, row_id: Any, ticker: Any, expiries: Any, portfolio_id: Any=None) -> None:
        """Replace the expiry cell with a QComboBox populated with fetched dates + DTE."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is None:
            return
        t = self.p4_opt_table
        expiries = [str(e) for e in expiries if e]
        if not expiries:
            self._reset_expiry_placeholder(row_id, ticker, 'N/A', portfolio_id)
            return
        saved = self.options_data[row].get('expiry', '') if row < len(self.options_data) else ''
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
        combo.setMinimumWidth(130)
        if saved in expiries:
            combo.setCurrentIndex(expiries.index(saved))
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
        self._fetch_single_option_price(row)
