from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.data_service.results import strip_market_data_keys
from budget_terminal_app.workers.market_metrics import MonthReturnWorker
from budget_terminal_app.widgets.etf_heatmap import EtfHeatmapWidget

_P4_POSITIONS_SPLITTER_CONFIG = user_data_path('p4_splitter.json')
_P4_STOCK_TABLE_WIDTHS_CONFIG = user_data_path('p4_stock_table_widths.json')
_P4_OPTIONS_TABLE_WIDTHS_CONFIG = user_data_path('p4_options_table_widths.json')
_P4_DEFAULT_POSITIONS_SPLITTER_SIZES = [7, 4]
_P4_STOCK_SECTION_MIN_HEIGHT = 260
_P4_OPTIONS_SECTION_MIN_HEIGHT = 180
_P4_TABLE_FIXED_ACTION_WIDTH = 36
_P4_TABLE_RESIZE_DEBOUNCE_MS = 120
_P4_HIGHLIGHT_TIMEOUT_MS = 30_000
P4_OPTIONS_COLUMNS = (
    'Ticker',
    'Type',
    'Expiry',
    'Strike',
    'Qty',
    'Premium',
    'Market Price',
    'Vol',
    'OI',
    'IV',
    'P&L ($)',
    'Return %',
    'Annual %',
)
P4_OPTIONS_DEFAULT_WIDTHS = {
    0: 64,
    1: 48,
    2: 122,
    3: 60,
    4: 42,
    5: 66,
    6: 86,
    7: 54,
    8: 54,
    9: 52,
    10: 74,
    11: 70,
    12: 70,
}
_P4_HEATMAP_INTERVALS = (
    ('live', 'Live'),
    ('1d', '1D'),
    ('1w', '1W'),
    ('1m', '1M'),
    ('3m', '3M'),
    ('ytd', 'YTD'),
    ('1y', '1Y'),
)


class _PortfolioManagerList(QListWidget):
    """Drag-reorderable portfolio list that reports the resulting id order."""

    orderChanged = pyqtSignal(list)

    def dropEvent(self, event: Any) -> None:
        super().dropEvent(event)
        self.orderChanged.emit([
            str(self.item(index).data(Qt.ItemDataRole.UserRole) or '')
            for index in range(self.count())
        ])


class _PortfolioNameEdit(QLineEdit):
    """Inline name editor with Escape-to-cancel behavior."""

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.setText(str(self.property('committed_name') or ''))
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class _PortfolioHighlightMouseFilter(QObject):
    """Forward app-wide mouse presses to the Portfolio highlight controller."""

    def __init__(self, window: Any, app: QApplication) -> None:
        super().__init__(window)
        self._window = window
        self._app = app
        window.destroyed.connect(self.detach)

    def detach(self, *_: Any) -> None:
        """Remove this filter when its owning window is destroyed."""
        app = self._app
        self._app = None
        self._window = None
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Observe mouse presses without consuming or changing their normal behavior."""
        window = self._window
        if window is not None and event.type() == QEvent.Type.MouseButtonPress:
            window._p4_handle_highlight_mouse_press(obj, event)
        return False


class PortfolioSetupMixin:

    @staticmethod
    def _p4_table_has_visual_selection(table: Any) -> bool:
        """Return whether a table currently paints any selected cells."""
        if table is None:
            return False
        selection_model = table.selectionModel()
        return bool(selection_model is not None and selection_model.hasSelection())

    def _p4_arm_stock_highlight_timer(self, *, restart: bool=False) -> None:
        """Start the stock highlight deadline, optionally restarting it for a user click."""
        timer = getattr(self, '_p4_stock_highlight_timer', None)
        if timer is not None and (restart or not timer.isActive()):
            timer.start()

    def _p4_stop_stock_highlight_timer(self) -> None:
        """Stop the stock highlight deadline without changing table state."""
        timer = getattr(self, '_p4_stock_highlight_timer', None)
        if timer is not None:
            timer.stop()

    def _p4_clear_stock_highlight(self) -> None:
        """Clear only the stock table's visual selection."""
        self._p4_stop_stock_highlight_timer()
        table = getattr(self, 'p4_table', None)
        if table is not None:
            table.clearSelection()

    def _p4_arm_options_highlight_timer(self, *, restart: bool=False) -> None:
        """Start the options highlight deadline, optionally restarting it for a user click."""
        timer = getattr(self, '_p4_options_highlight_timer', None)
        if timer is not None and (restart or not timer.isActive()):
            timer.start()

    def _p4_stop_options_highlight_timer(self) -> None:
        """Stop the options highlight deadline without changing table state."""
        timer = getattr(self, '_p4_options_highlight_timer', None)
        if timer is not None:
            timer.stop()

    def _p4_clear_options_highlight(self) -> None:
        """Clear only the options table's visual selection."""
        self._p4_stop_options_highlight_timer()
        table = getattr(self, 'p4_opt_table', None)
        if table is not None:
            table.clearSelection()

    def _p4_on_stock_highlight_selection_changed(self) -> None:
        """Give a programmatic stock selection one deadline without extending an active one."""
        if self._p4_table_has_visual_selection(getattr(self, 'p4_table', None)):
            self._p4_arm_stock_highlight_timer()
        else:
            self._p4_stop_stock_highlight_timer()

    def _p4_on_options_highlight_selection_changed(self) -> None:
        """Give a programmatic options selection one deadline without extending an active one."""
        if self._p4_table_has_visual_selection(getattr(self, 'p4_opt_table', None)):
            self._p4_arm_options_highlight_timer()
        else:
            self._p4_stop_options_highlight_timer()

    @staticmethod
    def _p4_event_global_position(event: Any) -> QPoint | None:
        """Return a mouse event's integer global position across supported Qt APIs."""
        try:
            return event.globalPosition().toPoint()
        except AttributeError:
            try:
                return event.globalPos()
            except AttributeError:
                return None

    @staticmethod
    def _p4_widget_is_within(widget: Any, parent: Any) -> bool:
        """Return whether a mouse receiver is a widget or one of its descendants."""
        return bool(
            isinstance(widget, QWidget)
            and isinstance(parent, QWidget)
            and (widget is parent or parent.isAncestorOf(widget))
        )

    def _p4_table_row_at_mouse_press(self, table: Any, widget: Any, global_position: QPoint | None) -> int:
        """Resolve a press inside a table viewport to a valid model row."""
        if table is None or global_position is None or not self._p4_widget_is_within(widget, table):
            return -1
        viewport = table.viewport()
        viewport_position = viewport.mapFromGlobal(global_position)
        if not viewport.rect().contains(viewport_position):
            return -1
        index = table.indexAt(viewport_position)
        return int(index.row()) if index.isValid() and 0 <= index.row() < table.rowCount() else -1

    def _p4_option_control_row_at_mouse_press(self, widget: Any, global_position: QPoint | None) -> int:
        """Resolve embedded option combos and their visible popup entries to an owning row."""
        table = getattr(self, 'p4_opt_table', None)
        if table is None:
            return -1
        for row in range(table.rowCount()):
            for column in (1, 2):
                combo = table.cellWidget(row, column)
                if not isinstance(combo, QComboBox):
                    continue
                if self._p4_widget_is_within(widget, combo):
                    return row
                try:
                    view = combo.view()
                    if self._p4_widget_is_within(widget, view):
                        return row
                    if global_position is None or not view.isVisible():
                        continue
                    viewport = view.viewport()
                    popup_position = viewport.mapFromGlobal(global_position)
                    if viewport.rect().contains(popup_position) and view.indexAt(popup_position).isValid():
                        return row
                except RuntimeError:
                    continue
        return -1

    def _p4_handle_highlight_mouse_press(self, widget: Any, event: Any) -> None:
        """Apply Portfolio highlight lifetime rules for one app-wide mouse press."""
        global_position = self._p4_event_global_position(event)
        option_control_row = self._p4_option_control_row_at_mouse_press(widget, global_position)
        option_row = self._p4_table_row_at_mouse_press(
            getattr(self, 'p4_opt_table', None),
            widget,
            global_position,
        )
        if option_control_row >= 0 or option_row >= 0:
            self._p4_clear_stock_highlight()
            self._p4_arm_options_highlight_timer(restart=True)
            return
        stock_row = self._p4_table_row_at_mouse_press(
            getattr(self, 'p4_table', None),
            widget,
            global_position,
        )
        if stock_row >= 0:
            self._p4_clear_options_highlight()
            self._p4_arm_stock_highlight_timer(restart=True)
            return
        self._p4_clear_stock_highlight()
        self._p4_clear_options_highlight()

    def _p4_initialize_position_highlight_behavior(self) -> None:
        """Install independent highlight timers and the Portfolio mouse observer."""
        self._p4_stock_highlight_timer = QTimer(self)
        self._p4_stock_highlight_timer.setInterval(_P4_HIGHLIGHT_TIMEOUT_MS)
        self._p4_stock_highlight_timer.setSingleShot(True)
        self._p4_stock_highlight_timer.timeout.connect(self._p4_clear_stock_highlight)
        self._p4_options_highlight_timer = QTimer(self)
        self._p4_options_highlight_timer.setInterval(_P4_HIGHLIGHT_TIMEOUT_MS)
        self._p4_options_highlight_timer.setSingleShot(True)
        self._p4_options_highlight_timer.timeout.connect(self._p4_clear_options_highlight)
        self.p4_table.itemSelectionChanged.connect(self._p4_on_stock_highlight_selection_changed)
        self.p4_opt_table.itemSelectionChanged.connect(self._p4_on_options_highlight_selection_changed)
        app = QApplication.instance()
        if app is not None:
            self._p4_highlight_mouse_filter = _PortfolioHighlightMouseFilter(self, app)
            app.installEventFilter(self._p4_highlight_mouse_filter)

    def _p4_submit_background_task(self, fn: Any) -> None:
        """Run one Portfolio background task through the bounded page executor."""
        executor = getattr(self, '_portfolio_task_executor', None)
        if executor is None:
            # Portfolio workers can create their own bounded per-ticker pools. Keep
            # one outer task active so completions cannot pile up on the Qt thread.
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='PortfolioRefresh')
            self._portfolio_task_executor = executor
        executor.submit(fn)

    def _p4_get_portfolio_slots(self) -> Any:
        """Return a normalized ordered list of existing portfolio slot dicts."""
        slots = []
        raw = getattr(self, 'portfolio_slots', None)
        if isinstance(raw, list):
            for index, entry in enumerate(raw[:MAX_PORTFOLIOS + 1]):
                if isinstance(entry, dict):
                    slots.append({
                        'id': int(entry.get('id', index)),
                        'portfolio_id': str(entry.get('portfolio_id', entry.get('id', index)) or entry.get('id', index)),
                        'name': str(entry.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                    })
        if not slots:
            slots.append({'id': 0, 'portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID, 'name': 'Portfolio 1'})
        return slots

    def _p4_active_portfolio_is_combined(self) -> bool:
        """Return whether the visible Portfolio workspace is the virtual aggregate."""
        return str(getattr(self, 'active_portfolio_id', '') or '') == COMBINED_PORTFOLIO_ID

    def _p4_editable_portfolio_count(self) -> int:
        """Return the number of persisted, user-editable portfolios."""
        return sum(
            1 for slot in self._p4_get_portfolio_slots()
            if str(slot.get('portfolio_id', '') or '') != COMBINED_PORTFOLIO_ID
        )

    def _p4_apply_combined_read_only_state(self) -> None:
        """Apply the active portfolio's editing policy to all Portfolio controls."""
        read_only = self._p4_active_portfolio_is_combined()
        for name in ('p4_add_stock_btn', 'p4_add_options_btn'):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(not read_only)
        if read_only:
            for name in ('p4_remove_stock_btn', 'p4_remove_options_btn'):
                control = getattr(self, name, None)
                if control is not None:
                    control.setEnabled(False)
        else:
            if hasattr(self, '_p4_update_remove_stock_button_state'):
                self._p4_update_remove_stock_button_state()
            if hasattr(self, '_p4_update_remove_options_button_state'):
                self._p4_update_remove_options_button_state()
        cash_input = getattr(self, 'p4_cash_input', None)
        if cash_input is not None:
            cash_input.setEnabled(not read_only)
        margin_input = getattr(self, 'p4_margin_input', None)
        if margin_input is not None:
            margin_input.setEnabled(not read_only)
        cash_checkbox = getattr(self, 'p4_cash_include_checkbox', None)
        if cash_checkbox is not None:
            cash_checkbox.setEnabled(not read_only)
        stock_table = getattr(self, 'p4_table', None)
        if stock_table is not None:
            stock_table.setEditTriggers(
                QTableWidget.EditTrigger.NoEditTriggers
                if read_only else QTableWidget.EditTrigger.AllEditTriggers
            )
        options_table = getattr(self, 'p4_opt_table', None)
        if options_table is not None:
            options_table.setEditTriggers(
                QTableWidget.EditTrigger.NoEditTriggers
                if read_only else QTableWidget.EditTrigger.AllEditTriggers
            )
            for row in range(options_table.rowCount()):
                for column in (1, 2):
                    widget = options_table.cellWidget(row, column)
                    if widget is not None:
                        widget.setEnabled(not read_only)

    def _p4_get_active_portfolio_index(self) -> int:
        """Return the selected portfolio index for the page-4 workspace."""
        slots = self._p4_get_portfolio_slots()
        value = getattr(self, 'active_portfolio_index', 0)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return min(max(value, 0), max(len(slots) - 1, 0))

    def _p4_get_main_portfolio_index(self) -> int:
        """Return the app-wide main portfolio index."""
        slots = self._p4_get_portfolio_slots()
        for attr_name in ('main_portfolio_index', 'primary_portfolio_index'):
            value = getattr(self, attr_name, None)
            if value is None:
                continue
            try:
                return min(max(int(value), 0), max(len(slots) - 1, 0))
            except (TypeError, ValueError):
                return 0
        return self._p4_get_active_portfolio_index()

    def _p4_portfolio_name(self, index: int) -> str:
        """Resolve a portfolio display name."""
        slots = self._p4_get_portfolio_slots()
        if 0 <= index < len(slots):
            return str(slots[index].get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}')
        return f'Portfolio {index + 1}'

    def _p4_apply_fallback_portfolio_identity(self, index: int, *, make_main: bool=False) -> None:
        """Update local identity state when shared runtime helpers are unavailable."""
        slots = self._p4_get_portfolio_slots()
        index = min(max(int(index), 0), max(len(slots) - 1, 0))
        self.active_portfolio_index = index
        self.portfolio_slots = slots
        if make_main:
            self.main_portfolio_index = index

    def _p4_refresh_portfolio_selector(self) -> None:
        """Refresh the compact portfolio selector and its identity labels."""
        if not hasattr(self, 'p4_portfolio_combo'):
            return
        slots = self._p4_get_portfolio_slots()
        active_index = self._p4_get_active_portfolio_index()
        main_index = self._p4_get_main_portfolio_index()
        active_id = str(slots[active_index].get('portfolio_id', '') or '')
        main_id = str(slots[main_index].get('portfolio_id', '') or '')
        self.p4_portfolio_combo.blockSignals(True)
        self.p4_portfolio_combo.clear()
        for index, slot in enumerate(slots):
            portfolio_id = str(slot.get('portfolio_id', '') or '')
            label = str(slot.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}')
            badges = []
            if portfolio_id == main_id:
                badges.append('Main')
            if portfolio_id == COMBINED_PORTFOLIO_ID:
                badges.append('Read only')
            display = f'{label}  ·  {" · ".join(badges)}' if badges else label
            self.p4_portfolio_combo.addItem(display, portfolio_id)
        combo_index = self.p4_portfolio_combo.findData(active_id)
        self.p4_portfolio_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        self.p4_portfolio_combo.blockSignals(False)
        if hasattr(self, 'p4_main_portfolio_label'):
            self.p4_main_portfolio_label.setText(f'Main: {self._p4_portfolio_name(main_index)}')
        if hasattr(self, 'port_header_lbl'):
            self.port_header_lbl.setText(f'{self._p4_portfolio_name(main_index)} ({len(getattr(self, "tickers", []))})')
        if hasattr(self, '_p4_sync_cash_input'):
            self._p4_sync_cash_input()
        self._p4_apply_combined_read_only_state()
        dialog = getattr(self, '_p4_portfolio_manager_dialog', None)
        if dialog is not None and dialog.isVisible() and not getattr(self, '_p4_manager_refreshing', False):
            self._p4_refresh_portfolio_manager()

    @staticmethod
    def _p4_manager_number(value: Any, default: float=0.0) -> float:
        """Return a finite numeric value for manager summaries."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    def _p4_portfolio_manager_summary(self, portfolio_id: Any) -> dict[str, Any]:
        """Build one network-free account summary from saved state and loaded quotes."""
        portfolio_id = str(portfolio_id or '')
        if portfolio_id == COMBINED_PORTFOLIO_ID:
            source_ids = [
                str(slot.get('portfolio_id', '') or '')
                for slot in self._p4_get_portfolio_slots()
                if str(slot.get('portfolio_id', '') or '') != COMBINED_PORTFOLIO_ID
            ]
            summaries = [self._p4_portfolio_manager_summary(source_id) for source_id in source_ids]
            return {
                'stock_count': sum(int(summary['stock_count']) for summary in summaries),
                'option_count': sum(int(summary['option_count']) for summary in summaries),
                'cash': sum(float(summary['cash']) for summary in summaries),
                'stock_value': sum(float(summary['stock_value']) for summary in summaries),
                'options_value': sum(float(summary['options_value']) for summary in summaries),
                'margin_debt': sum(float(summary['margin_debt']) for summary in summaries),
                'held_count': sum(int(summary['held_count']) for summary in summaries),
                'priced_count': sum(int(summary['priced_count']) for summary in summaries),
            }

        entry = self._get_portfolio_entry(portfolio_id) if hasattr(self, '_get_portfolio_entry') else {}
        if not isinstance(entry, dict):
            entry = {}
        tickers = list(entry.get('portfolio', []))
        tracker = entry.get('portfolio_tracker', {})
        tracker = tracker if isinstance(tracker, dict) else {}
        options_data = entry.get('options_tracker', [])
        options_data = options_data if isinstance(options_data, list) else []
        data = getattr(self, 'last_data', None)
        quotes = data.get('portfolio', {}) if isinstance(data, dict) else {}
        quotes = quotes if isinstance(quotes, dict) else {}

        stock_value = 0.0
        held_count = 0
        priced_count = 0
        for raw_ticker in tickers:
            ticker = str(raw_ticker or '').upper().strip()
            position = tracker.get(raw_ticker, tracker.get(ticker, {}))
            position = position if isinstance(position, dict) else {}
            shares = self._p4_manager_number(position.get('shares'))
            if shares == 0.0:
                continue
            held_count += 1
            quote = quotes.get(ticker, {})
            quote = quote if isinstance(quote, dict) else {}
            price = self._p4_manager_number(quote.get('price'))
            if price <= 0.0:
                continue
            priced_count += 1
            stock_value += shares * price

        options_value = 0.0
        for position in options_data:
            if not isinstance(position, dict):
                continue
            strategy = str(position.get('strategy', 'Calls') or 'Calls')
            current = self._p4_manager_number(position.get('current_price'))
            premium = self._p4_manager_number(position.get('premium'))
            contracts = self._p4_manager_number(position.get('contracts'), 1.0)
            if strategy in ('Covered Call', 'Cash Secured Put'):
                options_value += (premium - current) * contracts * 100.0
            else:
                options_value += current * contracts * 100.0

        return {
            'stock_count': len(tickers),
            'option_count': len(options_data),
            'cash': max(self._p4_manager_number(entry.get('cash_balance')), 0.0),
            'stock_value': stock_value,
            'options_value': options_value,
            'margin_debt': max(self._p4_manager_number(entry.get('margin_debt')), 0.0),
            'held_count': held_count,
            'priced_count': priced_count,
        }

    def _p4_portfolio_manager_value_text(self, summary: Any) -> str:
        """Format a transparent full-account estimate and quote coverage."""
        summary = summary if isinstance(summary, dict) else {}
        held_count = int(summary.get('held_count', 0) or 0)
        priced_count = int(summary.get('priced_count', 0) or 0)
        total = sum(
            self._p4_manager_number(summary.get(key))
            for key in ('stock_value', 'cash', 'options_value')
        )
        total -= max(self._p4_manager_number(summary.get('margin_debt')), 0.0)
        if held_count > 0 and priced_count == 0:
            return f'Value unavailable  ·  0/{held_count} priced'
        if priced_count < held_count:
            return f'Partial est. ${total:,.2f}  ·  {priced_count}/{held_count} priced'
        return f'Est. ${total:,.2f}'

    def _p4_manager_index_for_id(self, portfolio_id: Any) -> int:
        """Resolve a portfolio id to its current selector index."""
        clean_id = str(portfolio_id or '')
        for index, slot in enumerate(self._p4_get_portfolio_slots()):
            if str(slot.get('portfolio_id', '') or '') == clean_id:
                return index
        return 0

    def _p4_manager_commit_name(self, portfolio_id: Any, editor: Any) -> None:
        """Commit an inline portfolio rename without changing the active account."""
        if getattr(self, '_p4_manager_refreshing', False):
            return
        portfolio_id = str(portfolio_id or '')
        if portfolio_id == COMBINED_PORTFOLIO_ID:
            return
        index = self._p4_manager_index_for_id(portfolio_id)
        current_name = self._p4_portfolio_name(index)
        clean_name = str(editor.text() or '').strip()
        if clean_name == current_name:
            editor.setProperty('committed_name', current_name)
            return
        self._p4_manager_refreshing = True
        try:
            if not self._p4_try_call_runtime(
                ('rename_portfolio', '_rename_portfolio', 'set_portfolio_name', '_set_portfolio_name'),
                index,
                clean_name,
            ):
                slots = self._p4_get_portfolio_slots()
                slots[index]['name'] = clean_name or f'Portfolio {index + 1}'
                self.portfolio_slots = slots
                self._p4_refresh_portfolio_selector()
        finally:
            self._p4_manager_refreshing = False
        QTimer.singleShot(0, self._p4_refresh_portfolio_manager)

    def _p4_manager_select(self, portfolio_id: Any) -> None:
        """Select one manager entry in the Portfolio workspace."""
        self._p4_on_portfolio_changed(self._p4_manager_index_for_id(portfolio_id))
        self._p4_refresh_portfolio_manager()

    def _p4_manager_set_main(self, portfolio_id: Any) -> None:
        """Promote one manager entry to the app-wide main portfolio."""
        index = self._p4_manager_index_for_id(portfolio_id)
        if not self._p4_try_call_runtime(
            ('set_main_portfolio_index', '_set_main_portfolio_index', '_select_main_portfolio', 'use_portfolio_as_main'),
            index,
        ):
            self._p4_apply_fallback_portfolio_identity(index, make_main=True)
            self._p4_refresh_portfolio_selector()
        self._p4_refresh_portfolio_manager()

    def _p4_manager_delete(self, portfolio_id: Any) -> None:
        """Delete any editable manager entry after confirmation."""
        portfolio_id = str(portfolio_id or '')
        if portfolio_id == COMBINED_PORTFOLIO_ID:
            return
        if self._p4_editable_portfolio_count() <= 1:
            QMessageBox.information(self, 'Delete Portfolio', 'At least one portfolio must remain.')
            return
        index = self._p4_manager_index_for_id(portfolio_id)
        portfolio_name = self._p4_portfolio_name(index)
        reply = QMessageBox.question(
            self,
            'Delete Portfolio',
            f'Delete "{portfolio_name}" and all of its stock, tracker, and options data?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = False
        for name in ('delete_portfolio', '_delete_portfolio', 'remove_portfolio', '_remove_portfolio'):
            fn = getattr(self, name, None)
            if callable(fn):
                deleted = bool(fn(index))
                break
        if deleted:
            self._p4_refresh_portfolio_selector()
            self._p4_refresh_portfolio_manager()

    def _p4_manager_create(self) -> None:
        """Create a portfolio and keep the manager dialog current."""
        self._p4_create_portfolio()
        self._p4_refresh_portfolio_manager()

    def _p4_manager_reorder(self, ordered_ids: Any) -> None:
        """Persist a manager drag result while keeping Combined fixed last."""
        editable_ids = [
            str(portfolio_id or '')
            for portfolio_id in list(ordered_ids or [])
            if str(portfolio_id or '') != COMBINED_PORTFOLIO_ID
        ]
        fn = getattr(self, 'reorder_portfolios', None)
        if callable(fn):
            fn(editable_ids)
        self._p4_refresh_portfolio_manager()

    def _p4_build_portfolio_manager_row(self, slot: Any) -> tuple[QListWidgetItem, QWidget]:
        """Build one rich portfolio row for the manager list."""
        portfolio_id = str(slot.get('portfolio_id', '') or '')
        is_combined = portfolio_id == COMBINED_PORTFOLIO_ID
        active_id = str(getattr(self, 'active_portfolio_id', '') or '')
        main_id = str(getattr(self, 'main_portfolio_id', '') or '')
        summary = self._p4_portfolio_manager_summary(portfolio_id)

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, portfolio_id)
        item.setSizeHint(QSize(680, 76))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not is_combined:
            flags |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)

        row = QFrame()
        self.set_theme_role(row, 'panel')
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 7, 8, 7)
        layout.setSpacing(10)
        drag_label = QLabel('☰' if not is_combined else '•')
        self.set_theme_role(drag_label, 'muted')
        drag_label.setFixedWidth(18)
        layout.addWidget(drag_label)

        identity = QWidget()
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(3)
        name = str(slot.get('name', '') or '')
        if is_combined:
            name_widget = QLabel(name)
            self.set_theme_role(name_widget, 'section_title')
        else:
            name_widget = _PortfolioNameEdit(name)
            name_widget.setProperty('committed_name', name)
            name_widget.setMinimumWidth(180)
            name_widget.editingFinished.connect(
                lambda pid=portfolio_id, editor=name_widget: self._p4_manager_commit_name(pid, editor)
            )
        identity_layout.addWidget(name_widget)
        badges = []
        if portfolio_id == active_id:
            badges.append('ACTIVE')
        if portfolio_id == main_id:
            badges.append('MAIN')
        if is_combined:
            badges.append('READ ONLY')
        status = QLabel('  ·  '.join(badges) if badges else 'Saved portfolio')
        self.set_theme_role(status, 'badge' if badges else 'muted')
        identity_layout.addWidget(status)
        layout.addWidget(identity, 2)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(3)
        counts = QLabel(
            f'{int(summary["stock_count"])} stocks  ·  {int(summary["option_count"])} options  ·  '
            f'Cash ${float(summary["cash"]):,.2f}'
        )
        self.set_theme_role(counts, 'muted')
        value = QLabel(self._p4_portfolio_manager_value_text(summary))
        self.set_theme_role(value, 'metric')
        details_layout.addWidget(counts)
        details_layout.addWidget(value)
        layout.addWidget(details, 3)

        select_btn = QPushButton('Selected' if portfolio_id == active_id else 'Select')
        select_btn.setEnabled(portfolio_id != active_id)
        select_btn.setMinimumWidth(72)
        select_btn.clicked.connect(lambda _checked=False, pid=portfolio_id: self._p4_manager_select(pid))
        layout.addWidget(select_btn)
        main_btn = QPushButton('Main' if portfolio_id == main_id else 'Set Main')
        main_btn.setEnabled(portfolio_id != main_id)
        main_btn.setMinimumWidth(78)
        self.set_theme_variant(main_btn, 'accent')
        main_btn.clicked.connect(lambda _checked=False, pid=portfolio_id: self._p4_manager_set_main(pid))
        layout.addWidget(main_btn)
        if not is_combined:
            delete_btn = QPushButton('Delete')
            delete_btn.setEnabled(self._p4_editable_portfolio_count() > 1)
            delete_btn.setMinimumWidth(66)
            self.set_theme_variant(delete_btn, 'danger')
            delete_btn.clicked.connect(lambda _checked=False, pid=portfolio_id: self._p4_manager_delete(pid))
            layout.addWidget(delete_btn)
        else:
            spacer = QWidget()
            spacer.setFixedWidth(66)
            layout.addWidget(spacer)
        return item, row

    def _p4_refresh_portfolio_manager(self) -> None:
        """Rebuild manager rows after an immediate catalog change."""
        list_widget = getattr(self, 'p4_portfolio_manager_list', None)
        if list_widget is None or getattr(self, '_p4_manager_refreshing', False):
            return
        self._p4_manager_refreshing = True
        try:
            list_widget.blockSignals(True)
            list_widget.clear()
            for slot in self._p4_get_portfolio_slots():
                item, row = self._p4_build_portfolio_manager_row(slot)
                list_widget.addItem(item)
                list_widget.setItemWidget(item, row)
            list_widget.blockSignals(False)
            add_btn = getattr(self, 'p4_manager_add_btn', None)
            if add_btn is not None:
                add_btn.setEnabled(self._p4_editable_portfolio_count() < MAX_PORTFOLIOS)
        finally:
            self._p4_manager_refreshing = False

    def _p4_build_portfolio_manager_dialog(self) -> QDialog:
        """Create the reusable, network-free Portfolio manager dialog."""
        existing = getattr(self, '_p4_portfolio_manager_dialog', None)
        if existing is not None:
            self._p4_refresh_portfolio_manager()
            return existing
        dialog = QDialog(self)
        dialog.setWindowTitle('Manage Portfolios')
        dialog.setMinimumSize(860, 480)
        dialog.resize(980, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel('Manage Portfolios')
        self.set_theme_role(title, 'page_title')
        hint = QLabel('Rename inline, drag editable portfolios to reorder, or change the active and main portfolios. Values use the latest loaded quotes.')
        hint.setWordWrap(True)
        self.set_theme_role(hint, 'muted')
        layout.addWidget(title)
        layout.addWidget(hint)
        self.p4_portfolio_manager_list = _PortfolioManagerList()
        self.p4_portfolio_manager_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.p4_portfolio_manager_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.p4_portfolio_manager_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.p4_portfolio_manager_list.setSpacing(4)
        self.p4_portfolio_manager_list.orderChanged.connect(self._p4_manager_reorder)
        layout.addWidget(self.p4_portfolio_manager_list, 1)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.p4_manager_add_btn = QPushButton('+ New Portfolio')
        self.set_theme_variant(self.p4_manager_add_btn, 'positive')
        self.p4_manager_add_btn.clicked.connect(self._p4_manager_create)
        footer.addWidget(self.p4_manager_add_btn)
        footer.addStretch(1)
        done_btn = QPushButton('Done')
        self.set_theme_variant(done_btn, 'accent')
        done_btn.clicked.connect(dialog.accept)
        footer.addWidget(done_btn)
        layout.addLayout(footer)
        self._p4_portfolio_manager_dialog = dialog
        self._p4_refresh_portfolio_manager()
        return dialog

    def _p4_open_portfolio_manager(self) -> None:
        """Open the Portfolio manager without triggering market-data work."""
        dialog = self._p4_build_portfolio_manager_dialog()
        self._p4_refresh_portfolio_manager()
        dialog.exec()

    def _p4_save_positions_splitter_sizes(self, *_: Any) -> None:
        """Persist the page-4 stock/options splitter sizes to disk."""
        if not hasattr(self, 'p4_positions_splitter'):
            return
        sizes = [int(size) for size in self.p4_positions_splitter.sizes() if int(size) > 0]
        if len(sizes) != 2:
            return
        try:
            _P4_POSITIONS_SPLITTER_CONFIG.write_text(json.dumps(sizes))
        except Exception:
            pass

    def _p4_restore_positions_splitter_sizes(self) -> None:
        """Restore saved page-4 splitter sizes or apply the default layout."""
        if not hasattr(self, 'p4_positions_splitter'):
            return
        try:
            sizes = json.loads(_P4_POSITIONS_SPLITTER_CONFIG.read_text())
            if isinstance(sizes, list) and len(sizes) == 2:
                clean_sizes = [max(int(size), 1) for size in sizes]
                self.p4_positions_splitter.setSizes(clean_sizes)
                return
        except Exception:
            pass
        self.p4_positions_splitter.setSizes(list(_P4_DEFAULT_POSITIONS_SPLITTER_SIZES))

    def _p4_table_width_specs(self) -> dict[str, dict[str, Any]]:
        """Return width-persistence metadata for the page-4 tables."""
        return {
            'stock': {
                'table_attr': 'p4_table',
                'config_path': _P4_STOCK_TABLE_WIDTHS_CONFIG,
                'resizable_cols': tuple(range(len(P4_PORTFOLIO_COLUMNS))),
                'fixed_cols': {},
            },
            'options': {
                'table_attr': 'p4_opt_table',
                'config_path': _P4_OPTIONS_TABLE_WIDTHS_CONFIG,
                'resizable_cols': tuple(range(len(P4_OPTIONS_COLUMNS))),
                'default_widths': P4_OPTIONS_DEFAULT_WIDTHS,
                'fixed_cols': {},
            },
        }

    def _p4_table_width_spec(self, table_key: str) -> dict[str, Any]:
        """Return one page-4 table width spec."""
        return self._p4_table_width_specs().get(table_key, {})

    def _p4_table_widget(self, table_key: str) -> Any:
        """Resolve one page-4 table widget from its key."""
        spec = self._p4_table_width_spec(table_key)
        return getattr(self, spec.get('table_attr', ''), None)

    def _p4_table_width_guard_attr(self, table_key: str) -> str:
        """Return the guard attribute for programmatic width updates."""
        return f'_p4_{table_key}_table_width_guard'

    def _p4_table_width_timer_attr(self, table_key: str) -> str:
        """Return the debounce timer attribute for one page-4 table."""
        return f'_p4_{table_key}_table_width_timer'

    def _p4_configure_table_widths(self, table_key: str) -> None:
        """Make one page-4 table user-resizable while keeping action columns fixed."""
        table = self._p4_table_widget(table_key)
        if table is None:
            return
        spec = self._p4_table_width_spec(table_key)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(18)
        for col in spec.get('resizable_cols', ()):
            header.setSectionResizeMode(int(col), QHeaderView.ResizeMode.Interactive)
        for col, width in spec.get('fixed_cols', {}).items():
            header.setSectionResizeMode(int(col), QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(int(col), int(width))

    def _p4_table_visible_width(self, table_key: str) -> int:
        """Return the visible width available to one table's columns."""
        table = self._p4_table_widget(table_key)
        if table is None:
            return 0
        viewport_width = int(table.viewport().width())
        if viewport_width > 0:
            return viewport_width
        fallback = int(table.width()) - (table.frameWidth() * 2)
        if table.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            fallback -= int(table.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
        return max(fallback, 0)

    def _p4_capture_table_width_preferences(self, table_key: str) -> dict[int, int]:
        """Capture the current resizable-column widths for one table."""
        table = self._p4_table_widget(table_key)
        spec = self._p4_table_width_spec(table_key)
        if table is None:
            return {}
        widths = {}
        for col in spec.get('resizable_cols', ()):
            width = int(table.columnWidth(int(col)))
            if width <= 0:
                return {}
            widths[int(col)] = width
        return widths

    def _p4_load_table_width_preferences(self, table_key: str) -> dict[int, int]:
        """Load saved manual widths for one page-4 table."""
        spec = self._p4_table_width_spec(table_key)
        expected_columns = {int(col) for col in spec.get('resizable_cols', ())}
        try:
            raw = json.loads(spec.get('config_path').read_text())
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        parsed = {}
        for key, value in raw.items():
            try:
                col = int(key)
                width = int(value)
            except (TypeError, ValueError):
                return {}
            if width <= 0:
                return {}
            parsed[col] = width
        return parsed if set(parsed.keys()) == expected_columns else {}

    def _p4_save_table_width_preferences(self, table_key: str, widths: Any = None) -> None:
        """Persist manual widths for one page-4 table."""
        if getattr(self, self._p4_table_width_guard_attr(table_key), False):
            return
        spec = self._p4_table_width_spec(table_key)
        widths = widths or self._p4_capture_table_width_preferences(table_key)
        if not widths:
            return
        payload = {str(int(col)): int(width) for col, width in widths.items() if int(width) > 0}
        if len(payload) != len(spec.get('resizable_cols', ())):
            return
        try:
            spec.get('config_path').write_text(json.dumps(payload))
        except Exception:
            pass

    def _p4_scale_table_widths(self, widths: dict[int, int], target_total: int) -> dict[int, int]:
        """Scale one table's saved widths to fit a new total width."""
        if not widths:
            return {}
        columns = [int(col) for col in widths.keys()]
        target_total = max(int(target_total), len(columns))
        weights = {col: max(int(widths[col]), 1) for col in columns}
        total_weight = max(sum(weights.values()), 1)
        scaled = {col: int((target_total * weights[col]) // total_weight) for col in columns}
        used = sum(scaled.values())
        remainder = max(target_total - used, 0)
        fractions = sorted(
            columns,
            key=lambda col: ((target_total * weights[col]) / total_weight) - scaled[col],
            reverse=True,
        )
        for index in range(remainder):
            scaled[fractions[index % len(fractions)]] += 1
        return scaled

    def _p4_apply_table_width_preferences(self, table_key: str, preferred_widths: Any = None) -> None:
        """Fit one page-4 table's columns to its visible panel width."""
        table = self._p4_table_widget(table_key)
        if table is None:
            return
        spec = self._p4_table_width_spec(table_key)
        self._p4_configure_table_widths(table_key)
        fixed_total = sum(int(width) for width in spec.get('fixed_cols', {}).values())
        available_width = self._p4_table_visible_width(table_key)
        if available_width <= fixed_total:
            return
        base_widths = preferred_widths or self._p4_load_table_width_preferences(table_key)
        if not base_widths:
            default_widths = spec.get('default_widths', {})
            base_widths = {
                int(col): int(default_widths.get(int(col), 1))
                for col in spec.get('resizable_cols', ())
            }
        scaled = self._p4_scale_table_widths(base_widths, available_width - fixed_total)
        guard_attr = self._p4_table_width_guard_attr(table_key)
        setattr(self, guard_attr, True)
        table.setUpdatesEnabled(False)
        try:
            for col in spec.get('resizable_cols', ()):
                width = int(scaled.get(int(col), 1))
                table.setColumnWidth(int(col), width)
            for col, width in spec.get('fixed_cols', {}).items():
                table.setColumnWidth(int(col), int(width))
        finally:
            table.setUpdatesEnabled(True)
            setattr(self, guard_attr, False)

    def _p4_apply_portfolio_table_widths(self, *_: Any) -> None:
        """Fit both page-4 tables to their current visible panel widths."""
        self._p4_apply_table_width_preferences('stock')
        self._p4_apply_table_width_preferences('options')

    def _p4_refit_tables_after_splitter_move(self, *_: Any) -> None:
        """Fit tables now and once more after Qt settles splitter geometry."""
        self._p4_apply_portfolio_table_widths()
        timer = getattr(self, '_p4_splitter_refit_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._p4_apply_portfolio_table_widths)
            self._p4_splitter_refit_timer = timer
        timer.start(0)

    def _p4_apply_positions_splitter_theme(self) -> None:
        """Apply theme-aware handles to the splitters on the Positions tab."""
        stylesheet = (
            f'QSplitter::handle {{ background: {self.theme_color("panel_border")}; '
            'border-radius: 2px; }} '
            f'QSplitter::handle:hover {{ background: {self.theme_color("accent")}; }}'
        )
        for splitter_name in ('p4_main_splitter', 'p4_positions_splitter'):
            splitter = getattr(self, splitter_name, None)
            if splitter is not None:
                splitter.setStyleSheet(stylesheet)

    def _p4_schedule_table_width_fit(self, table_key: str) -> None:
        """Debounce one table's width normalization after a user resize."""
        timer = getattr(self, self._p4_table_width_timer_attr(table_key), None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda key=table_key: self._p4_apply_table_width_preferences(key))
            setattr(self, self._p4_table_width_timer_attr(table_key), timer)
        timer.start(_P4_TABLE_RESIZE_DEBOUNCE_MS)

    def _p4_on_table_section_resized(self, table_key: str, logical_index: int, _old_size: int, _new_size: int) -> None:
        """Persist one table's manual widths and re-fit them to the visible panel."""
        spec = self._p4_table_width_spec(table_key)
        if int(logical_index) not in {int(col) for col in spec.get('resizable_cols', ())}:
            return
        if getattr(self, self._p4_table_width_guard_attr(table_key), False):
            return
        self._p4_save_table_width_preferences(table_key)
        self._p4_schedule_table_width_fit(table_key)

    def _p4_on_show(self) -> None:
        """Refresh page-4 table widths when the Portfolio tab becomes visible."""
        # Lazy-page rollback/re-entrancy can briefly expose the provisional
        # page widget before Portfolio controls exist.  Treat that as not yet
        # renderable instead of scheduling work against missing tables.
        if not hasattr(self, 'p4_table'):
            return
        if hasattr(self, '_dashboard_apply_pending_page_data'):
            self._dashboard_apply_pending_page_data('portfolio')
        if getattr(self, '_p4_options_fetch_deferred', False) and hasattr(self, '_reload_options_table'):
            self._p4_options_fetch_deferred = False
            self._reload_options_table()
        self._p4_apply_portfolio_table_widths()
        if hasattr(self, '_p4_render_deferred_subtab'):
            self._p4_render_deferred_subtab()

    def _p4_on_content_tab_changed(self, index: int) -> None:
        """Refresh the visible Portfolio sub-tab after a tab switch."""
        if not hasattr(self, 'p4_content_tabs'):
            return
        if hasattr(self, '_p4_render_deferred_subtab'):
            QTimer.singleShot(0, self._p4_render_deferred_subtab)
            return
        widget = self.p4_content_tabs.widget(index)
        if widget is getattr(self, 'p4_positions_page', None):
            QTimer.singleShot(0, self._p4_apply_portfolio_table_widths)
            return
        if widget is getattr(self, 'p4_pie_page', None) and hasattr(self, '_p4_refresh_pie_chart'):
            QTimer.singleShot(0, self._p4_refresh_pie_chart)
            return
        if widget is getattr(self, 'p4_heatmap_page', None) and hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
            QTimer.singleShot(0, lambda: self._p4_refresh_portfolio_heatmap_view(reset_view=False))
            return
        if widget is getattr(self, 'p4_momentum_page', None) and hasattr(self, '_p4_refresh_active_momentum_view'):
            QTimer.singleShot(0, self._p4_refresh_active_momentum_view)
            return
        if widget is getattr(self, 'p4_metrics_page', None) and hasattr(self, '_p4_refresh_portfolio_metrics_view'):
            QTimer.singleShot(0, self._p4_refresh_portfolio_metrics_view)

    def _p4_try_call_runtime(self, names: Any, *args: Any) -> bool:
        """Call the first runtime helper that exists."""
        for name in names:
            fn = getattr(self, name, None)
            if callable(fn):
                fn(*args)
                return True
        return False

    def _p4_on_portfolio_changed(self, index: int) -> None:
        """Switch the shared page-4 workspace to a different portfolio."""
        slots = self._p4_get_portfolio_slots()
        if not slots:
            return
        combo = getattr(self, 'p4_portfolio_combo', None)
        portfolio_id = combo.itemData(index) if combo is not None and index >= 0 else None
        if portfolio_id is not None:
            index = self._p4_manager_index_for_id(portfolio_id)
        else:
            index = min(max(int(index), 0), len(slots) - 1)
        if not self._p4_try_call_runtime(
            ('set_active_portfolio_index', '_set_active_portfolio_index', '_activate_portfolio_index', '_switch_active_portfolio'),
            index,
        ):
            self._p4_apply_fallback_portfolio_identity(index)
        self._p4_refresh_portfolio_selector()
        if hasattr(self, '_reload_options_table'):
            self._reload_options_table()
        if getattr(self, 'last_data', None):
            self.update_page4(self.last_data)
            fetched = set(self.last_data.get('portfolio', {}).keys())
            active_tickers = set(self._p4_active_tickers()) if hasattr(self, '_p4_active_tickers') else set()
            if active_tickers - fetched and hasattr(self, '_p4_refresh_holdings'):
                self._p4_refresh_holdings()
        elif hasattr(self, 'p4_table'):
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)
            if hasattr(self, '_p4_update_stock_positions_label'):
                self._p4_update_stock_positions_label()
            self._p4_update_remove_stock_button_state()
            self._p4_apply_table_width_preferences('stock')
            if hasattr(self, '_p4_refresh_active_momentum_view'):
                self._p4_refresh_active_momentum_view()
            if hasattr(self, '_p4_refresh_portfolio_heatmap_view'):
                self._p4_refresh_portfolio_heatmap_view(reset_view=True)
            if hasattr(self, '_p4_refresh_pie_chart'):
                self._p4_refresh_pie_chart()
        self._p4_apply_combined_read_only_state()
        if (
            hasattr(self, 'p4_content_tabs')
            and self.p4_content_tabs.currentWidget() is getattr(self, 'p4_metrics_page', None)
            and hasattr(self, '_p4_refresh_portfolio_metrics_view')
        ):
            self._p4_refresh_portfolio_metrics_view()

    def _p4_build_pie_chart_page(self) -> Any:
        """Build the checked-position portfolio allocation sub-tab."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        summary_frame = QFrame()
        self.set_theme_role(summary_frame, 'panel')
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(10)

        heading_layout = QVBoxLayout()
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(2)
        title_label = QLabel('Included Portfolio Allocation')
        self.set_theme_role(title_label, 'section_title')
        subtitle_label = QLabel('Checked positions')
        self.set_theme_role(subtitle_label, 'muted')
        heading_layout.addWidget(title_label)
        heading_layout.addWidget(subtitle_label)
        summary_layout.addLayout(heading_layout)
        summary_layout.addStretch()

        self.p4_pie_total_label = QLabel('Filtered Total:  $0.00  USD')
        self.p4_pie_total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p4_pie_total_label, 'metric')
        summary_layout.addWidget(self.p4_pie_total_label)
        layout.addWidget(summary_frame)

        chart_frame = QFrame()
        self.set_theme_role(chart_frame, 'panel')
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(12, 12, 12, 12)
        chart_layout.setSpacing(0)

        self.p4_pie_chart = PieChartWidget()
        self.p4_pie_chart.setMinimumHeight(320)
        self.p4_pie_chart.set_donut(True, hole_ratio=0.50)
        self.p4_pie_chart.set_callout_labels(True)
        self.p4_pie_chart.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        self.p4_pie_chart.setVisible(False)
        self.p4_pie_scroll_area = QScrollArea()
        self.p4_pie_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.p4_pie_scroll_area.setWidgetResizable(True)
        self.p4_pie_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p4_pie_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p4_pie_scroll_area.viewport().setAutoFillBackground(False)
        self.p4_pie_scroll_area.setWidget(self.p4_pie_chart)
        self.p4_pie_scroll_area.setVisible(False)
        chart_layout.addWidget(self.p4_pie_scroll_area, 1)

        self.p4_pie_empty_label = QLabel('No included portfolio value.')
        self.p4_pie_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.p4_pie_empty_label, 'muted')
        self.p4_pie_empty_label.setVisible(True)
        chart_layout.addWidget(self.p4_pie_empty_label, 1)
        layout.addWidget(chart_frame, 1)
        return page

    def _p4_build_portfolio_heatmap_page(self) -> Any:
        """Build the active portfolio heatmap sub-tab."""
        self._p4_heatmap_rows = []
        self._p4_heatmap_selected_row = None
        self._p4_heatmap_interval_key = 'live'
        self._p4_heatmap_return_cache = {}
        self._p4_heatmap_return_fetching = {}
        self._p4_heatmap_interval_buttons = {}

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        summary_frame = QFrame()
        self.set_theme_role(summary_frame, 'panel')
        self.p4_heatmap_summary_frame = summary_frame
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 6, 12, 6)
        summary_layout.setSpacing(0)
        self.p4_heatmap_summary_labels = {}
        for index, (key, label, default) in enumerate((
            ('holdings', 'Holdings', '--'),
            ('cash', 'Cash', '--'),
            ('coverage', 'Coverage', '--'),
            ('weighted', 'Weighted Move', '--'),
            ('largest', 'Largest', '--'),
            ('strongest', 'Strongest', '--'),
            ('weakest', 'Weakest', '--'),
        )):
            sep = None
            if index:
                sep = QFrame()
                sep.setFixedWidth(1)
                summary_layout.addWidget(sep)
            cell = QVBoxLayout()
            cell.setContentsMargins(10, 2, 10, 2)
            cell.setSpacing(1)
            header = QLabel(label)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel(default)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(header)
            cell.addWidget(value)
            summary_layout.addLayout(cell, 1)
            self.p4_heatmap_summary_labels[key] = value
            self.p4_heatmap_summary_labels[f'{key}_header'] = header
            self.p4_heatmap_summary_labels[f'{key}_sep'] = sep
        layout.addWidget(summary_frame)

        interval_row = QHBoxLayout()
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.setSpacing(6)
        interval_label = QLabel('Interval')
        self.set_theme_role(interval_label, 'muted')
        interval_row.addWidget(interval_label)
        self.p4_heatmap_interval_group = QButtonGroup(page)
        self.p4_heatmap_interval_group.setExclusive(True)
        for key, label in _P4_HEATMAP_INTERVALS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, interval_key=key: self._p4_select_heatmap_interval(interval_key))
            interval_row.addWidget(button)
            self.p4_heatmap_interval_group.addButton(button)
            self._p4_heatmap_interval_buttons[key] = button
        self._p4_heatmap_interval_buttons[self._p4_heatmap_interval_key].setChecked(True)
        interval_row.addStretch()
        layout.addLayout(interval_row)

        self.p4_heatmap_status_lbl = QLabel('Ready')
        self.p4_heatmap_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.set_theme_role(self.p4_heatmap_status_lbl, 'status_muted')
        layout.addWidget(self.p4_heatmap_status_lbl)

        self.p4_heatmap = EtfHeatmapWidget()
        self.p4_heatmap.set_empty_message('Add positive-share holdings and refresh market data to render the portfolio heatmap')
        self.p4_heatmap.holdingSelected.connect(self._p4_on_heatmap_holding_selected)
        self.p4_heatmap.holdingActivated.connect(self._p4_open_heatmap_symbol_in_charts)
        layout.addWidget(self.p4_heatmap, 1)

        detail_frame = QFrame()
        self.set_theme_role(detail_frame, 'panel')
        self.p4_heatmap_detail_frame = detail_frame
        detail_layout = QHBoxLayout(detail_frame)
        detail_layout.setContentsMargins(12, 8, 12, 8)
        detail_layout.setSpacing(18)
        self.p4_heatmap_detail_symbol_lbl = QLabel('Select a holding')
        self.p4_heatmap_detail_sector_lbl = QLabel('Sector: --')
        self.p4_heatmap_detail_weight_lbl = QLabel('Weight: --')
        self.p4_heatmap_detail_price_lbl = QLabel('Price: --')
        self.p4_heatmap_detail_value_lbl = QLabel('Market Value: --')
        self.p4_heatmap_detail_change_lbl = QLabel('Day Change: --')
        for label in (
            self.p4_heatmap_detail_symbol_lbl,
            self.p4_heatmap_detail_sector_lbl,
            self.p4_heatmap_detail_weight_lbl,
            self.p4_heatmap_detail_price_lbl,
            self.p4_heatmap_detail_value_lbl,
            self.p4_heatmap_detail_change_lbl,
        ):
            label.setMinimumHeight(22)
            detail_layout.addWidget(label)
        detail_layout.addStretch()
        layout.addWidget(detail_frame)

        self._apply_portfolio_heatmap_theme()
        self._p4_refresh_portfolio_heatmap_view(reset_view=True)
        return page

    def _p4_heatmap_tab_visible(self) -> bool:
        """Return whether the Portfolio Heatmap sub-tab is currently visible."""
        return (
            hasattr(self, 'p4_content_tabs')
            and self.p4_content_tabs.currentWidget() is getattr(self, 'p4_heatmap_page', None)
        )

    def _p4_select_heatmap_interval(self, interval_key: Any) -> None:
        """Switch the Portfolio Heatmap interval."""
        key = str(interval_key or 'live').strip().lower()
        if key not in dict(_P4_HEATMAP_INTERVALS):
            key = 'live'
        self._p4_heatmap_interval_key = key
        for button_key, button in getattr(self, '_p4_heatmap_interval_buttons', {}).items():
            button.blockSignals(True)
            button.setChecked(button_key == key)
            button.blockSignals(False)
        self._p4_style_heatmap_interval_buttons()
        self._p4_refresh_portfolio_heatmap_view(reset_view=False)

    def _p4_heatmap_interval_label(self, interval_key: Any = None) -> str:
        """Return the user-facing label for one Portfolio Heatmap interval."""
        key = str(interval_key or getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        return dict(_P4_HEATMAP_INTERVALS).get(key, 'Live')

    def _p4_heatmap_uses_snapshot_returns(self, interval_key: Any = None) -> bool:
        """Return whether an interval can use the latest quote snapshot."""
        key = str(interval_key or getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        return key in {'live', '1d'}

    def _p4_heatmap_interval_config(self, interval_key: Any) -> dict[str, Any]:
        """Return fetch config for one Portfolio Heatmap interval."""
        key = str(interval_key or 'live').strip().lower()
        today = datetime.date.today()
        return {
            '1w': {'start': (today - datetime.timedelta(days=7)).isoformat(), 'interval': '1d'},
            '1m': {'period': '1mo', 'interval': '1d'},
            '3m': {'period': '3mo', 'interval': '1d'},
            'ytd': {'start': f'{today.year}-01-01', 'interval': '1d'},
            '1y': {'period': '1y', 'interval': '1d'},
        }.get(key, {'period': '1mo', 'interval': '1d'})

    def _p4_heatmap_stock_symbols(self) -> list[str]:
        """Return positive-share stock symbols for interval-return fetches."""
        tracker_data = self._p4_active_tracker_data() if hasattr(self, '_p4_active_tracker_data') else {}
        symbols = []
        seen = set()
        for ticker in self._p4_active_tickers() if hasattr(self, '_p4_active_tickers') else []:
            symbol = str(ticker or '').strip().upper()
            if not symbol or symbol == 'CASH' or symbol in seen:
                continue
            if hasattr(self, '_p4_position_included_in_weight') and not self._p4_position_included_in_weight(ticker):
                continue
            try:
                shares = float((tracker_data.get(ticker, {}) or tracker_data.get(symbol, {}) or {}).get('shares', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                shares = 0.0
            if shares > 0.0:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def _p4_heatmap_returns_cache_key(self, interval_key: Any = None, portfolio_id: Any = None) -> tuple[Any, ...]:
        """Build a cache key for Portfolio Heatmap interval returns."""
        key = str(interval_key or getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        pid = str(portfolio_id or getattr(self, 'active_portfolio_id', ''))
        return (pid, key, tuple(sorted(self._p4_heatmap_stock_symbols())))

    def _p4_fetch_heatmap_returns_for_interval(self, interval_key: Any) -> bool:
        """Fetch longer-interval stock returns for the Portfolio Heatmap."""
        key = str(interval_key or 'live').strip().lower()
        if self._p4_heatmap_uses_snapshot_returns(key):
            return False
        cache_key = self._p4_heatmap_returns_cache_key(key)
        cache = getattr(self, '_p4_heatmap_return_cache', {})
        fetching = getattr(self, '_p4_heatmap_return_fetching', {})
        if cache_key in cache or fetching.get(cache_key):
            return False
        symbols = list(cache_key[2])
        if not symbols:
            cache[cache_key] = {}
            self._p4_heatmap_return_cache = cache
            return False
        fetching[cache_key] = True
        self._p4_heatmap_return_fetching = fetching
        config = self._p4_heatmap_interval_config(key)
        if hasattr(self, 'p4_heatmap_status_lbl'):
            self.set_status_text(self.p4_heatmap_status_lbl, f'Loading {self._p4_heatmap_interval_label(key)} heatmap returns...', status='warning')

        def _run() -> None:
            try:
                client = getattr(self, '_data_service_client', None)
                if client is not None:
                    results = client.fetch_month_returns(
                        symbols,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                    )
                else:
                    results = MonthReturnWorker(
                        symbols,
                        period=config.get('period', '1mo'),
                        interval=config.get('interval', '1d'),
                        start=config.get('start'),
                    ).fetch()
            except Exception as exc:
                logger.warning('Portfolio heatmap interval return request failed; falling back to direct worker: %s', exc)
                results = MonthReturnWorker(
                    symbols,
                    period=config.get('period', '1mo'),
                    interval=config.get('interval', '1d'),
                    start=config.get('start'),
                ).fetch()
            self._invoke_main.emit(lambda payload=results, requested_key=key, requested_cache_key=cache_key: self._p4_on_heatmap_returns_ready(requested_key, requested_cache_key, payload))

        self._p4_submit_background_task(_run)
        return True

    def _p4_on_heatmap_returns_ready(self, interval_key: Any, cache_key: Any, results: Any) -> None:
        """Cache fetched heatmap interval returns and refresh if still active."""
        fetching = getattr(self, '_p4_heatmap_return_fetching', {})
        fetching[cache_key] = False
        self._p4_heatmap_return_fetching = fetching
        cache = getattr(self, '_p4_heatmap_return_cache', {})
        normalized = {}
        results = strip_market_data_keys(results) if isinstance(results, dict) else results
        if isinstance(results, dict):
            for ticker, value in results.items():
                symbol = str(ticker or '').strip().upper()
                if isinstance(value, (int, float)):
                    normalized[symbol] = float(value)
        cache[cache_key] = normalized
        self._p4_heatmap_return_cache = cache
        if (
            str(interval_key or '').strip().lower() == str(getattr(self, '_p4_heatmap_interval_key', 'live')).strip().lower()
            and getattr(self, '_p4_page_visible', lambda: True)()
            and getattr(self, '_p4_active_content_key', lambda: 'heatmap')() == 'heatmap'
        ):
            self._p4_refresh_portfolio_heatmap_view(reset_view=False)
        else:
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('heatmap')

    def _p4_heatmap_sector_lookup(self) -> dict[str, str]:
        """Return a symbol-to-sector lookup based on the app's sector universe."""
        cached = getattr(self, '_p4_heatmap_sector_by_ticker', None)
        if isinstance(cached, dict):
            return cached
        lookup = {}
        for sector, tickers in SECTOR_DATA.items():
            for ticker in tickers:
                symbol = str(ticker or '').strip().upper()
                if symbol:
                    lookup.setdefault(symbol, sector)
        self._p4_heatmap_sector_by_ticker = lookup
        return lookup

    def _p4_heatmap_sector_for_symbol(self, symbol: Any) -> str:
        """Resolve one portfolio ticker into a heatmap sector bucket."""
        text = str(symbol or '').strip().upper()
        if not text:
            return 'Unclassified'
        lookup = self._p4_heatmap_sector_lookup()
        return lookup.get(text) or lookup.get(text.replace('.', '-')) or lookup.get(text.replace('-', '.')) or 'Unclassified'

    def _p4_portfolio_heatmap_rows(self, portfolio: Any, interval_key: Any = None, interval_returns: Any = None) -> list[dict[str, Any]]:
        """Build heatmap rows from active portfolio tracker metrics."""
        if not isinstance(portfolio, dict):
            portfolio = {}
        interval_key = str(interval_key or getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        interval_label = self._p4_heatmap_interval_label(interval_key)
        interval_returns = interval_returns if isinstance(interval_returns, dict) else {}
        metrics_map, _full_total_market_value = self._p4_build_tracker_metrics_map(portfolio)
        _weights, total_market_value = self._p4_filtered_weight_map(metrics_map)
        if total_market_value <= 0:
            return []
        rows = []
        for ticker in sorted(
            self._p4_active_tickers(),
            key=lambda symbol: metrics_map.get(symbol, {}).get('market_value', 0.0),
            reverse=True,
        ):
            symbol = str(ticker or '').strip().upper()
            if not self._p4_position_included_in_weight(ticker):
                continue
            metrics = metrics_map.get(ticker, {})
            try:
                shares = float(metrics.get('shares', 0.0) or 0.0)
                market_value = float(metrics.get('market_value', 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if shares <= 0.0 or market_value <= 0.0:
                continue
            price = metrics.get('price')
            if self._p4_heatmap_uses_snapshot_returns(interval_key):
                change = metrics.get('change')
            else:
                change = interval_returns.get(symbol)
            rows.append({
                'symbol': symbol,
                'name': '',
                'sector': self._p4_heatmap_sector_for_symbol(symbol),
                'weight': market_value / total_market_value,
                'price': price if isinstance(price, (int, float)) else None,
                'change_pct': change if isinstance(change, (int, float)) else None,
                'change_label': f'{interval_label} Change',
                'interval_label': interval_label,
                'market_value': market_value,
                'shares': shares,
                'is_cash': False,
                'neutral_heat': False,
            })
        return rows

    def _p4_refresh_portfolio_heatmap_view(self, *, reset_view: bool=False) -> None:
        """Render the active portfolio heatmap from the latest quote snapshot."""
        if not hasattr(self, 'p4_heatmap'):
            return
        if hasattr(self, 'p4_content_tabs') and (
            not getattr(self, '_p4_page_visible', lambda: True)()
            or getattr(self, '_p4_active_content_key', lambda: 'heatmap')() != 'heatmap'
        ):
            self._p4_dirty_subtabs = set(getattr(self, '_p4_dirty_subtabs', set()))
            self._p4_dirty_subtabs.add('heatmap')
            return
        data = getattr(self, 'last_data', None)
        portfolio = data.get('portfolio', {}) if isinstance(data, dict) else {}
        interval_key = str(getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        cache_key = self._p4_heatmap_returns_cache_key(interval_key)
        cache = getattr(self, '_p4_heatmap_return_cache', {})
        fetching = getattr(self, '_p4_heatmap_return_fetching', {})
        fetch_started = False
        if not self._p4_heatmap_uses_snapshot_returns(interval_key) and cache_key not in cache:
            fetch_started = self._p4_fetch_heatmap_returns_for_interval(interval_key)
        rows = self._p4_portfolio_heatmap_rows(portfolio, interval_key, cache.get(cache_key, {}))
        self._p4_heatmap_rows = rows
        self.p4_heatmap.set_data(rows, reset_view=reset_view)
        self._p4_update_heatmap_summary(rows)
        selected_symbol = str((getattr(self, '_p4_heatmap_selected_row', None) or {}).get('symbol') or '').upper().strip()
        selected = next((row for row in rows if row.get('symbol') == selected_symbol), None)
        self._p4_on_heatmap_holding_selected(selected or (rows[0] if rows else None))
        is_loading = fetch_started or bool(fetching.get(cache_key))
        status = 'warning' if is_loading else ('positive' if rows else 'warning')
        if is_loading:
            message = f'Loading {self._p4_heatmap_interval_label(interval_key)} heatmap returns...'
        elif rows:
            message = f'Loaded {len(rows)} stock holding{"s" if len(rows) != 1 else ""} for {self._p4_heatmap_interval_label(interval_key)}.'
        else:
            message = 'No positive-share stock holdings to display.'
        if hasattr(self, 'p4_heatmap_status_lbl'):
            self.set_status_text(self.p4_heatmap_status_lbl, message, status=status)

    def _p4_update_heatmap_summary(self, rows: Any) -> None:
        """Update Portfolio Heatmap summary values."""
        labels = getattr(self, 'p4_heatmap_summary_labels', {})
        if not labels:
            return
        rows = list(rows or [])
        quoted = [row for row in rows if isinstance(row.get('change_pct'), (int, float))]
        labels['holdings'].setText(str(len(rows)) if rows else '--')
        cash_label = labels.get('cash')
        if cash_label is not None:
            cash_label.setText(self._p4_heatmap_cash_metric_text(rows))
        labels['coverage'].setText(f'{len(quoted)}/{len(rows)}' if rows else '--')
        weighted = self._p4_heatmap_weighted_change(quoted)
        self._p4_set_heatmap_change_label(labels.get('weighted'), weighted)
        largest = max(rows, key=lambda row: float(row.get('weight', 0.0) or 0.0), default=None)
        self._p4_set_heatmap_symbol_weight_label(labels.get('largest'), largest)
        strongest = max(quoted, key=lambda row: float(row.get('change_pct', 0.0) or 0.0), default=None)
        weakest = min(quoted, key=lambda row: float(row.get('change_pct', 0.0) or 0.0), default=None)
        self._p4_set_heatmap_symbol_change_label(labels.get('strongest'), strongest)
        self._p4_set_heatmap_symbol_change_label(labels.get('weakest'), weakest)

    def _p4_heatmap_cash_metric_text(self, rows: Any) -> str:
        """Return the cash metric shown outside the heatmap."""
        if hasattr(self, '_p4_cash_included_in_weight') and not self._p4_cash_included_in_weight():
            return 'Excluded'
        cash_balance = self._p4_active_cash_balance() if hasattr(self, '_p4_active_cash_balance') else 0.0
        stock_value = 0.0
        for row in rows or []:
            value = row.get('market_value') if isinstance(row, dict) else None
            if isinstance(value, (int, float)):
                stock_value += float(value)
        total_value = stock_value + cash_balance
        if cash_balance <= 0.0:
            return '$0'
        cash_pct = cash_balance / total_value * 100.0 if total_value > 0.0 else 0.0
        return f'${cash_balance:,.0f} / {cash_pct:.1f}%'

    def _p4_heatmap_weighted_change(self, rows: Any) -> Any:
        """Return weighted day move across rows with usable quote changes."""
        numerator = 0.0
        denominator = 0.0
        for row in rows or []:
            weight = row.get('weight')
            change = row.get('change_pct')
            if isinstance(weight, (int, float)) and isinstance(change, (int, float)):
                numerator += float(weight) * float(change)
                denominator += float(weight)
        return numerator / denominator if denominator > 0 else None

    def _p4_set_heatmap_change_label(self, label: Any, value: Any, *, prefix: str='') -> None:
        """Style one heatmap change label."""
        if label is None:
            return
        if not isinstance(value, (int, float)):
            label.setText(f'{prefix}--')
            label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; font-weight: bold; border: none;')
            return
        sign = '+' if float(value) >= 0 else ''
        label.setText(f'{prefix}{sign}{float(value):.2f}%')
        color = self.theme_color('accent_positive' if float(value) >= 0 else 'accent_negative')
        label.setStyleSheet(f'color: {color}; font-size: 12px; font-weight: bold; border: none;')

    def _p4_set_heatmap_symbol_change_label(self, label: Any, row: Any) -> None:
        """Show one symbol/change compact summary."""
        if label is None:
            return
        if not isinstance(row, dict) or not isinstance(row.get('change_pct'), (int, float)):
            label.setText('--')
            label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; font-weight: bold; border: none;')
            return
        symbol = str(row.get('symbol') or '--')
        value = float(row.get('change_pct') or 0.0)
        sign = '+' if value >= 0 else ''
        label.setText(f'{symbol} {sign}{value:.2f}%')
        color = self.theme_color('accent_positive' if value >= 0 else 'accent_negative')
        label.setStyleSheet(f'color: {color}; font-size: 12px; font-weight: bold; border: none;')

    def _p4_set_heatmap_symbol_weight_label(self, label: Any, row: Any) -> None:
        """Show one symbol/weight compact summary."""
        if label is None:
            return
        if not isinstance(row, dict):
            label.setText('--')
            label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; font-weight: bold; border: none;')
            return
        label.setText(f'{row.get("symbol") or "--"} {float(row.get("weight", 0.0) or 0.0) * 100.0:.1f}%')
        label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px; font-weight: bold; border: none;')

    def _p4_on_heatmap_holding_selected(self, row: Any) -> None:
        """Render selected portfolio heatmap holding details."""
        payload = row if isinstance(row, dict) else {}
        if not hasattr(self, 'p4_heatmap_detail_symbol_lbl'):
            return
        if not payload:
            self._p4_heatmap_selected_row = None
            self.p4_heatmap_detail_symbol_lbl.setText('Select a holding')
            self.p4_heatmap_detail_sector_lbl.setText('Sector: --')
            self.p4_heatmap_detail_weight_lbl.setText('Weight: --')
            self.p4_heatmap_detail_price_lbl.setText('Price: --')
            self.p4_heatmap_detail_value_lbl.setText('Market Value: --')
            change_label = self._p4_heatmap_interval_label()
            self.p4_heatmap_detail_change_lbl.setText(f'{change_label} Change: --')
            self._p4_set_heatmap_change_label(self.p4_heatmap_detail_change_lbl, None, prefix=f'{change_label} Change: ')
            return
        self._p4_heatmap_selected_row = dict(payload)
        self.p4_heatmap_detail_symbol_lbl.setText(str(payload.get('symbol') or '--'))
        self.p4_heatmap_detail_sector_lbl.setText(f'Sector: {payload.get("sector") or "Unclassified"}')
        self.p4_heatmap_detail_weight_lbl.setText(f'Weight: {float(payload.get("weight", 0.0) or 0.0) * 100.0:.2f}%')
        price = payload.get('price')
        self.p4_heatmap_detail_price_lbl.setText(f'Price: ${float(price):,.2f}' if isinstance(price, (int, float)) else 'Price: --')
        market_value = payload.get('market_value')
        self.p4_heatmap_detail_value_lbl.setText(f'Market Value: ${float(market_value):,.2f}' if isinstance(market_value, (int, float)) else 'Market Value: --')
        change_label = str(payload.get('change_label') or f'{self._p4_heatmap_interval_label()} Change')
        self._p4_set_heatmap_change_label(self.p4_heatmap_detail_change_lbl, payload.get('change_pct'), prefix=f'{change_label}: ')

    def _p4_open_heatmap_symbol_in_charts(self, symbol: Any) -> None:
        """Open a portfolio heatmap symbol in the Charts page."""
        ticker = str(symbol or '').upper().strip()
        if not ticker or ticker == 'CASH':
            return
        self.p10_symbol = ticker
        if isinstance(getattr(self, 'chart_page_state', None), dict):
            self.chart_page_state = {**self.chart_page_state, 'symbol': ticker}
        page_index = self.stacked_widget.indexOf(self.page10) if hasattr(self, 'stacked_widget') and hasattr(self, 'page10') else 9
        self.switch_page(page_index if page_index >= 0 else 9)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(ticker)
        if hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()

    def _apply_portfolio_heatmap_theme(self) -> None:
        """Refresh Portfolio Heatmap colors after a theme change."""
        if not hasattr(self, 'p4_heatmap'):
            return
        panel_style = (
            f'background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px;'
        )
        for frame in (getattr(self, 'p4_heatmap_summary_frame', None), getattr(self, 'p4_heatmap_detail_frame', None)):
            if frame is not None:
                frame.setStyleSheet(panel_style)
        for key, label in getattr(self, 'p4_heatmap_summary_labels', {}).items():
            if label is None:
                continue
            if key.endswith('_header'):
                label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
            elif key.endswith('_sep'):
                label.setStyleSheet(f'background: {self.theme_color("panel_border")};')
            elif key not in ('weighted', 'strongest', 'weakest'):
                label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px; font-weight: bold; border: none;')
        for label in (
            getattr(self, 'p4_heatmap_detail_symbol_lbl', None),
            getattr(self, 'p4_heatmap_detail_sector_lbl', None),
            getattr(self, 'p4_heatmap_detail_weight_lbl', None),
            getattr(self, 'p4_heatmap_detail_price_lbl', None),
            getattr(self, 'p4_heatmap_detail_value_lbl', None),
        ):
            if label is not None:
                label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self._p4_style_heatmap_interval_buttons()
        self.p4_heatmap.set_theme(
            background=self.theme_color('background_primary'),
            panel=self.theme_color('panel_background'),
            border=self.theme_color('panel_border'),
            text=self.theme_color('text_primary'),
            muted=self.theme_color('text_muted'),
            up=self.theme_color('accent_positive'),
            down=self.theme_color('accent_negative'),
            accent=self.theme_color('accent'),
        )
        self._p4_update_heatmap_summary(getattr(self, '_p4_heatmap_rows', []))
        self._p4_on_heatmap_holding_selected(getattr(self, '_p4_heatmap_selected_row', None))
        if hasattr(self, 'p4_heatmap_status_lbl'):
            self.set_status_text(
                self.p4_heatmap_status_lbl,
                self.p4_heatmap_status_lbl.text(),
                status=self.p4_heatmap_status_lbl.property('bt_status') or 'muted',
            )

    def _p4_style_heatmap_interval_buttons(self) -> None:
        """Refresh checked-state styling for Portfolio Heatmap interval buttons."""
        active_key = str(getattr(self, '_p4_heatmap_interval_key', 'live') or 'live').strip().lower()
        for key, button in getattr(self, '_p4_heatmap_interval_buttons', {}).items():
            is_active = key == active_key
            background = self.theme_color('button_checked_bg' if is_active else 'panel_background')
            text = self.theme_color('text_primary')
            border = self.theme_color('button_checked_border' if is_active else 'panel_border')
            button.setStyleSheet(
                f'QPushButton {{ background: {background}; color: {text}; border: 1px solid {border}; '
                'border-radius: 4px; padding: 3px 8px; font-weight: bold; }}'
            )

    def _p4_rename_active_portfolio(self) -> None:
        """Prompt the user to rename the selected portfolio slot."""
        if self._p4_active_portfolio_is_combined():
            return
        active_index = self._p4_get_active_portfolio_index()
        current_name = self._p4_portfolio_name(active_index)
        name, ok = QInputDialog.getText(self, 'Rename Portfolio', 'Portfolio name:', text=current_name)
        if not ok:
            return
        clean_name = str(name or '').strip() or f'Portfolio {active_index + 1}'
        if not self._p4_try_call_runtime(
            ('rename_portfolio', '_rename_portfolio', 'set_portfolio_name', '_set_portfolio_name'),
            active_index,
            clean_name,
        ):
            slots = self._p4_get_portfolio_slots()
            slots[active_index]['name'] = clean_name
            self.portfolio_slots = slots
        self._p4_refresh_portfolio_selector()

    def _p4_create_portfolio(self) -> None:
        """Create a new empty portfolio up to the configured cap."""
        if self._p4_editable_portfolio_count() >= MAX_PORTFOLIOS:
            QMessageBox.information(self, 'Portfolio Limit Reached', f'You can create up to {MAX_PORTFOLIOS} portfolios.')
            return
        handled = False
        created = False
        for name in ('create_portfolio', '_create_portfolio', 'add_portfolio', '_add_portfolio'):
            fn = getattr(self, name, None)
            if callable(fn):
                handled = True
                created = bool(fn())
                break
        if not handled:
            fallback_slots = self._p4_get_portfolio_slots()
            editable_slots = [
                slot for slot in fallback_slots
                if str(slot.get('portfolio_id', '') or '') != COMBINED_PORTFOLIO_ID
            ]
            combined_slots = [
                slot for slot in fallback_slots
                if str(slot.get('portfolio_id', '') or '') == COMBINED_PORTFOLIO_ID
            ]
            used_ids = {str(slot.get('portfolio_id', '') or '') for slot in editable_slots}
            portfolio_id = next((pid for pid in PORTFOLIO_IDS if pid not in used_ids), '')
            next_index = len(editable_slots)
            editable_slots.append({'id': next_index, 'portfolio_id': portfolio_id, 'name': f'Portfolio {next_index + 1}'})
            self.portfolio_slots = [*editable_slots, *combined_slots]
            self.active_portfolio_index = next_index
            created = True
        if created:
            self._p4_refresh_portfolio_selector()

    def _p4_delete_active_portfolio(self) -> None:
        """Delete the currently selected portfolio after confirmation."""
        if self._p4_active_portfolio_is_combined():
            return
        if self._p4_editable_portfolio_count() <= 1:
            QMessageBox.information(self, 'Delete Portfolio', 'At least one portfolio must remain.')
            return
        active_index = self._p4_get_active_portfolio_index()
        portfolio_name = self._p4_portfolio_name(active_index)
        reply = QMessageBox.question(
            self,
            'Delete Portfolio',
            f'Delete "{portfolio_name}" and all of its stock, tracker, and options data?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        handled = False
        deleted = False
        for name in ('delete_portfolio', '_delete_portfolio', 'remove_portfolio', '_remove_portfolio'):
            fn = getattr(self, name, None)
            if callable(fn):
                handled = True
                deleted = bool(fn(active_index))
                break
        if not handled:
            fallback_slots = self._p4_get_portfolio_slots()
            if 0 <= active_index < len(fallback_slots):
                del fallback_slots[active_index]
                for index, slot in enumerate(fallback_slots):
                    slot['id'] = index
                self.portfolio_slots = fallback_slots
                self.active_portfolio_index = min(active_index, len(fallback_slots) - 1)
                self.main_portfolio_index = min(self._p4_get_main_portfolio_index(), len(fallback_slots) - 1)
                deleted = True
        if deleted:
            self._p4_refresh_portfolio_selector()

    def _p4_set_active_as_main(self) -> None:
        """Mark the selected portfolio as the app-wide main portfolio."""
        active_index = self._p4_get_active_portfolio_index()
        if not self._p4_try_call_runtime(
            ('set_main_portfolio_index', '_set_main_portfolio_index', '_select_main_portfolio', 'use_portfolio_as_main'),
            active_index,
        ):
            self._p4_apply_fallback_portfolio_identity(active_index, make_main=True)
        self._p4_refresh_portfolio_selector()
        if hasattr(self, 'refresh_data'):
            self.refresh_data()

    def init_page4(self) -> None:
        """Initialize page4."""
        layout = QVBoxLayout(self.page4)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        summary_bar = QHBoxLayout()
        summary_bar.setSpacing(8)
        title_lbl = QLabel('<b>Portfolio</b>')
        self.set_theme_role(title_lbl, 'page_title')
        self.p4_total_label = QLabel('Total:  $0.00  USD')
        self.set_theme_role(self.p4_total_label, 'metric')
        self.p4_stock_positions_label = QLabel('Positions:  0')
        self.set_theme_role(self.p4_stock_positions_label, 'badge')
        self.p4_stock_pl_label = QLabel('Stock P&L:  +$0.00')
        self.set_theme_role(self.p4_stock_pl_label, 'badge')
        self.p4_opt_pl_label = QLabel('Options P&L:  $0.00')
        self.set_theme_role(self.p4_opt_pl_label, 'badge')
        self.p4_cash_chip = QFrame()
        self.set_theme_role(self.p4_cash_chip, 'summary_chip')
        cash_chip_layout = QHBoxLayout(self.p4_cash_chip)
        cash_chip_layout.setContentsMargins(10, 4, 8, 4)
        cash_chip_layout.setSpacing(8)
        self.p4_cash_include_checkbox = QCheckBox('BROKERAGE CASH')
        self.p4_cash_include_checkbox.setChecked(True)
        self.p4_cash_include_checkbox.setToolTip(
            'Include Cash in Portfolio Weight, Pie Chart, Dip Finder, and Portfolio Heatmap'
        )
        self.set_theme_role(self.p4_cash_include_checkbox, 'summary_chip_label')
        self.p4_cash_include_checkbox.toggled.connect(self._p4_on_cash_weight_inclusion_changed)
        self.p4_cash_input = QDoubleSpinBox()
        self.p4_cash_input.setRange(0.0, 999999999999.99)
        self.p4_cash_input.setDecimals(2)
        self.p4_cash_input.setPrefix('$')
        self.p4_cash_input.setSingleStep(100.0)
        if hasattr(self.p4_cash_input, 'setGroupSeparatorShown'):
            self.p4_cash_input.setGroupSeparatorShown(True)
        self.p4_cash_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.p4_cash_input.setKeyboardTracking(False)
        self.p4_cash_input.setMinimumWidth(122)
        self.p4_cash_input.setMaximumWidth(150)
        self.p4_cash_input.setMinimumHeight(24)
        self.p4_cash_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.set_theme_role(self.p4_cash_input, 'cash_input')
        self.p4_cash_input.valueChanged.connect(self._p4_on_cash_balance_changed)
        cash_chip_layout.addWidget(self.p4_cash_include_checkbox)
        cash_chip_layout.addWidget(self.p4_cash_input)
        self.p4_margin_chip = QFrame()
        self.set_theme_role(self.p4_margin_chip, 'summary_chip')
        margin_chip_layout = QHBoxLayout(self.p4_margin_chip)
        margin_chip_layout.setContentsMargins(10, 4, 8, 4)
        margin_chip_layout.setSpacing(8)
        self.p4_margin_label = QLabel('MARGIN')
        self.p4_margin_label.setToolTip('Margin debt deducted from portfolio total and personal net worth')
        self.set_theme_role(self.p4_margin_label, 'summary_chip_label')
        self.p4_margin_input = QDoubleSpinBox()
        self.p4_margin_input.setRange(0.0, 999999999999.99)
        self.p4_margin_input.setDecimals(2)
        self.p4_margin_input.setPrefix('$')
        self.p4_margin_input.setSingleStep(100.0)
        if hasattr(self.p4_margin_input, 'setGroupSeparatorShown'):
            self.p4_margin_input.setGroupSeparatorShown(True)
        self.p4_margin_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.p4_margin_input.setKeyboardTracking(False)
        self.p4_margin_input.setMinimumWidth(122)
        self.p4_margin_input.setMaximumWidth(150)
        self.p4_margin_input.setMinimumHeight(24)
        self.p4_margin_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.p4_margin_input.setToolTip('Margin debt deducted from portfolio total and counted as debt in Personal Finance')
        self.set_theme_role(self.p4_margin_input, 'cash_input')
        self.p4_margin_input.valueChanged.connect(self._p4_on_margin_debt_changed)
        margin_chip_layout.addWidget(self.p4_margin_label)
        margin_chip_layout.addWidget(self.p4_margin_input)
        summary_bar.addWidget(title_lbl)
        summary_bar.addSpacing(8)
        summary_bar.addWidget(self.p4_cash_chip)
        summary_bar.addWidget(self.p4_margin_chip)
        summary_bar.addWidget(self.p4_stock_pl_label)
        summary_bar.addWidget(self.p4_opt_pl_label)
        summary_bar.addWidget(self.p4_stock_positions_label)
        summary_bar.addWidget(self.p4_total_label)
        summary_bar.addStretch()
        layout.addLayout(summary_bar)
        selector_bar = QHBoxLayout()
        selector_bar.setSpacing(8)
        selector_label = QLabel('Portfolios')
        self.set_theme_role(selector_label, 'card_title')
        self.p4_portfolio_combo = QComboBox()
        self.p4_portfolio_combo.setMinimumWidth(260)
        self.p4_portfolio_combo.setMaximumWidth(440)
        self.p4_portfolio_combo.setMinimumHeight(30)
        self.p4_portfolio_combo.currentIndexChanged.connect(self._p4_on_portfolio_changed)
        self.p4_manage_portfolios_btn = QPushButton('Manage Portfolios')
        self.p4_manage_portfolios_btn.setMinimumHeight(30)
        self.set_theme_variant(self.p4_manage_portfolios_btn, 'accent')
        self.p4_manage_portfolios_btn.clicked.connect(self._p4_open_portfolio_manager)
        self.p4_main_portfolio_label = QLabel('Main: Portfolio 1')
        self.set_theme_role(self.p4_main_portfolio_label, 'muted')
        selector_bar.addWidget(selector_label)
        selector_bar.addWidget(self.p4_portfolio_combo)
        selector_bar.addWidget(self.p4_manage_portfolios_btn)
        selector_bar.addWidget(self.p4_main_portfolio_label)
        selector_bar.addStretch(1)
        layout.addLayout(selector_bar)
        self.p4_content_tabs = QTabWidget()
        self.p4_content_tabs.setDocumentMode(True)
        self.p4_content_tabs.currentChanged.connect(self._p4_on_content_tab_changed)
        self.p4_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p4_main_splitter.setHandleWidth(6)
        self.p4_main_splitter.setChildrenCollapsible(False)
        self.p4_positions_splitter = QSplitter(Qt.Orientation.Vertical)
        self.p4_positions_splitter.setHandleWidth(6)
        self.p4_positions_splitter.setChildrenCollapsible(False)
        self._p4_apply_positions_splitter_theme()
        stock_widget = QFrame()
        self.set_theme_role(stock_widget, 'panel')
        stock_widget.setMinimumHeight(_P4_STOCK_SECTION_MIN_HEIGHT)
        stock_layout = QVBoxLayout(stock_widget)
        stock_layout.setContentsMargins(8, 8, 8, 8)
        stock_layout.setSpacing(6)
        stock_header_layout = QHBoxLayout()
        stock_header = QLabel('Positions')
        self.set_theme_role(stock_header, 'section_title')
        self.p4_add_stock_btn = QPushButton('+ Add Position')
        self.p4_add_stock_btn.setMinimumHeight(24)
        self.set_theme_variant(self.p4_add_stock_btn, 'positive')
        self.p4_add_stock_btn.clicked.connect(self._on_add_stock_clicked)
        self.p4_remove_stock_btn = QPushButton('Remove Position')
        self.p4_remove_stock_btn.setMinimumHeight(24)
        self.p4_remove_stock_btn.setEnabled(False)
        self.set_theme_variant(self.p4_remove_stock_btn, 'danger')
        self.p4_remove_stock_btn.clicked.connect(self._p4_remove_selected_stock_position)
        self.p4_refresh_holdings_btn = QPushButton('Refresh Holdings')
        self.p4_refresh_holdings_btn.setMinimumHeight(24)
        self.set_theme_variant(self.p4_refresh_holdings_btn, 'accent')
        self.p4_refresh_holdings_btn.clicked.connect(self._p4_refresh_holdings)
        self.p4_refresh_holdings_status_lbl = QLabel('')
        self.set_theme_role(self.p4_refresh_holdings_status_lbl, 'muted')
        export_llm_btn = QPushButton('Export for LLM')
        export_llm_btn.setMinimumHeight(24)
        export_llm_btn.clicked.connect(self._p4_export_for_llm)
        export_tickers_btn = QPushButton('Export Tickers')
        export_tickers_btn.setMinimumHeight(24)
        export_tickers_btn.clicked.connect(self._p4_export_tickers)
        stock_header_layout.addWidget(stock_header)
        stock_header_layout.addSpacing(10)
        stock_header_layout.addWidget(self.p4_add_stock_btn)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(self.p4_remove_stock_btn)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(self.p4_refresh_holdings_btn)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(self.p4_refresh_holdings_status_lbl)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(export_llm_btn)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(export_tickers_btn)
        stock_header_layout.addStretch()
        stock_layout.addLayout(stock_header_layout)
        self.p4_table = QTableWidget(0, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        hh = self.p4_table.horizontalHeader()
        hh.setSectionsMovable(True)
        self.p4_table.verticalHeader().setVisible(False)
        self.p4_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.p4_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p4_table.setAlternatingRowColors(True)
        self.p4_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p4_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p4_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.p4_table.verticalHeader().setDefaultSectionSize(52)
        self.p4_table.itemChanged.connect(self._on_tracker_cell_changed)
        self.p4_table.itemSelectionChanged.connect(self._p4_update_remove_stock_button_state)
        self.p4_table.currentCellChanged.connect(self._p4_on_stock_current_cell_changed)
        hh.setSortIndicator(P4_PORTFOLIO_COL_MARKET_VALUE, Qt.SortOrder.DescendingOrder)
        self.p4_table.setSortingEnabled(True)
        self._p4_apply_table_width_preferences('stock')
        hh.sectionResized.connect(lambda logical, old, new: self._p4_on_table_section_resized('stock', logical, old, new))
        stock_layout.addWidget(self.p4_table, 1)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)
        dip_finder_container = QFrame()
        self.set_theme_role(dip_finder_container, 'panel')
        dip_finder_layout = QVBoxLayout(dip_finder_container)
        dip_finder_layout.setContentsMargins(8, 8, 8, 8)
        dip_finder_layout.setSpacing(6)
        dip_finder_label = QLabel('Dip Finder')
        self.set_theme_role(dip_finder_label, 'card_title')
        dip_finder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p4_returns_tabs = QTabWidget()
        self.p4_returns_tabs.setDocumentMode(True)
        self.p4_return_timeframes = [('dip_finder', '1 Month'), ('ytd', 'YTD'), ('1y', '1Y')]
        self.p4_returns_charts = {}
        for timeframe_key, tab_label in self.p4_return_timeframes:
            chart = pg.PlotWidget()
            chart.getPlotItem().setMenuEnabled(False)
            chart.getPlotItem().hideButtons()
            chart.getPlotItem().hideAxis('bottom')
            chart.getPlotItem().hideAxis('left')
            chart.setMouseEnabled(x=False, y=False)
            self.p4_returns_charts[timeframe_key] = chart
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(0)
            tab_layout.addWidget(chart)
            self.p4_returns_tabs.addTab(tab, tab_label)
        self.p4_returns_tabs.currentChanged.connect(self._on_returns_timeframe_changed)
        self.p4_momentum_tabs = QTabWidget()
        self.p4_momentum_tabs.setDocumentMode(True)
        self.p4_momentum_timeframes = [('1mo', '1 Month'), ('ytd', 'YTD'), ('1y', '1Y')]
        self.p4_momentum_axes = {}
        self.p4_momentum_charts = {}
        for timeframe_key, tab_label in self.p4_momentum_timeframes:
            axis = DateAxisItem(orientation='bottom')
            chart = pg.PlotWidget(axisItems={'bottom': axis})
            chart.getPlotItem().setMenuEnabled(False)
            chart.getPlotItem().hideButtons()
            chart.getPlotItem().hideAxis('left')
            chart.getPlotItem().showAxis('right')
            chart.setMouseEnabled(x=False, y=False)
            self.p4_momentum_axes[timeframe_key] = axis
            self.p4_momentum_charts[timeframe_key] = chart
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(0)
            tab_layout.addWidget(chart)
            self.p4_momentum_tabs.addTab(tab, tab_label)
        self.p4_momentum_tabs.currentChanged.connect(self._on_momentum_timeframe_changed)
        self.p4_momentum_summary_label = QLabel('No positive-share positions to project.')
        self.set_theme_role(self.p4_momentum_summary_label, 'muted')
        self.p4_momentum_summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p4_momentum_summary_label.setWordWrap(True)
        momentum_container = QWidget()
        momentum_layout = QVBoxLayout(momentum_container)
        momentum_layout.setContentsMargins(8, 8, 8, 8)
        momentum_layout.setSpacing(6)
        momentum_layout.addWidget(self.p4_momentum_tabs, 1)
        momentum_layout.addWidget(self.p4_momentum_summary_label)
        weight_label = QLabel('Portfolio Weight')
        self.set_theme_role(weight_label, 'card_title')
        weight_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p4_weight_chart = pg.PlotWidget()
        self.p4_weight_chart.getPlotItem().setMenuEnabled(False)
        self.p4_weight_chart.getPlotItem().hideButtons()
        self.p4_weight_chart.setMouseEnabled(x=False, y=False)
        weight_container = QFrame()
        self.set_theme_role(weight_container, 'panel')
        weight_container_layout = QVBoxLayout(weight_container)
        weight_container_layout.setContentsMargins(8, 8, 8, 8)
        weight_container_layout.setSpacing(6)
        weight_container_layout.addWidget(weight_label)
        weight_container_layout.addWidget(self.p4_weight_chart, 1)
        dip_finder_layout.addWidget(dip_finder_label)
        dip_finder_layout.addWidget(self.p4_returns_tabs, 1)
        right_layout.addWidget(dip_finder_container, 1)
        right_layout.addWidget(weight_container, 1)
        options_widget = self._init_options_tab()
        options_widget.setMinimumHeight(_P4_OPTIONS_SECTION_MIN_HEIGHT)
        self.p4_positions_splitter.addWidget(stock_widget)
        self.p4_positions_splitter.addWidget(options_widget)
        self.p4_positions_splitter.setCollapsible(0, False)
        self.p4_positions_splitter.setCollapsible(1, False)
        self.p4_positions_splitter.setStretchFactor(0, 3)
        self.p4_positions_splitter.setStretchFactor(1, 2)
        self._p4_restore_positions_splitter_sizes()
        self.p4_positions_splitter.splitterMoved.connect(self._p4_save_positions_splitter_sizes)
        self.p4_positions_splitter.splitterMoved.connect(self._p4_refit_tables_after_splitter_move)
        self.p4_main_splitter.addWidget(self.p4_positions_splitter)
        self.p4_main_splitter.addWidget(right_widget)
        self.p4_main_splitter.setCollapsible(0, False)
        self.p4_main_splitter.setCollapsible(1, False)
        self.p4_main_splitter.setStretchFactor(0, 3)
        self.p4_main_splitter.setStretchFactor(1, 1)
        self.p4_main_splitter.splitterMoved.connect(self._p4_refit_tables_after_splitter_move)
        self.p4_positions_page = QWidget()
        positions_layout = QVBoxLayout(self.p4_positions_page)
        positions_layout.setContentsMargins(0, 0, 0, 0)
        positions_layout.setSpacing(0)
        positions_layout.addWidget(self.p4_main_splitter)
        self.p4_momentum_page = QWidget()
        momentum_page_layout = QVBoxLayout(self.p4_momentum_page)
        momentum_page_layout.setContentsMargins(0, 0, 0, 0)
        momentum_page_layout.setSpacing(0)
        momentum_page_layout.addWidget(momentum_container)
        self.p4_heatmap_page = self._p4_build_portfolio_heatmap_page()
        self.p4_pie_page = self._p4_build_pie_chart_page()
        self.p4_metrics_page = self._build_portfolio_metrics_page() if hasattr(self, '_build_portfolio_metrics_page') else QWidget()
        self.p4_content_tabs.addTab(self.p4_positions_page, 'Positions')
        self.p4_content_tabs.addTab(self.p4_pie_page, 'Pie Chart')
        self.p4_content_tabs.addTab(self.p4_heatmap_page, 'Portfolio Heatmap')
        self.p4_content_tabs.addTab(self.p4_momentum_page, 'Momentum Tracker')
        self.p4_content_tabs.addTab(self.p4_metrics_page, 'Portfolio Metrics')
        layout.addWidget(self.p4_content_tabs, 1)
        self._p4_initialize_position_highlight_behavior()
        QTimer.singleShot(0, self._p4_apply_portfolio_table_widths)
        self._p4_sync_cash_input()
        self._p4_refresh_portfolio_selector()

    def _on_add_stock_clicked(self) -> None:
        """Handle add stock clicked."""
        if self._p4_active_portfolio_is_combined():
            return
        ticker, ok = QInputDialog.getText(self, 'Add Stock Position', 'Enter Ticker Symbol:')
        if ok and ticker:
            ticker = ticker.upper().strip()
            tickers = self._p4_active_tickers() if hasattr(self, '_p4_active_tickers') else self.active_tickers
            tracker_data = self._p4_active_tracker_data() if hasattr(self, '_p4_active_tracker_data') else self.active_tracker_data
            if not ticker:
                return
            if ticker not in tickers:
                tickers.append(ticker)
            if ticker not in tracker_data:
                tracker_data[ticker] = {'shares': 0, 'avg_price': 0, 'include_in_weight': True}
            if hasattr(self, '_p4_begin_position_entry'):
                self._p4_begin_position_entry(ticker, P4_PORTFOLIO_COL_SHARES)
            self._persist_all_portfolios()
            self.update_page4(
                self.last_data or {'portfolio': {}},
                preserve_visible_order=True,
                defer_expensive_refresh=True,
            )
            if hasattr(self, '_p4_focus_stock_entry_cell'):
                self._p4_focus_stock_entry_cell(ticker, P4_PORTFOLIO_COL_SHARES)

    def _p4_selected_stock_ticker(self) -> str:
        """Return the ticker from the currently selected stock row."""
        table = getattr(self, 'p4_table', None)
        if table is None:
            return ''
        selection_model = table.selectionModel()
        if selection_model is not None:
            row_candidates = [index.row() for index in selection_model.selectedRows()]
            if not row_candidates:
                row_candidates = [index.row() for index in selection_model.selectedIndexes()]
        else:
            row_candidates = []
        row_candidates.extend([table.currentRow()])
        current_item = table.currentItem()
        if current_item is not None:
            row_candidates.append(current_item.row())
        for row in row_candidates:
            if row < 0 or row >= table.rowCount():
                continue
            item = table.item(row, P4_PORTFOLIO_COL_SYMBOL)
            ticker = str(item.text() if item is not None else '').strip().upper()
            if ticker:
                return ticker
        return ''

    def _p4_update_remove_stock_button_state(self) -> None:
        """Enable stock removal only when a stock row is selected."""
        button = getattr(self, 'p4_remove_stock_btn', None)
        if button is None:
            return
        table = getattr(self, 'p4_table', None)
        button.setEnabled(bool(
            not self._p4_active_portfolio_is_combined()
            and table is not None
            and table.rowCount() > 0
        ))

    def _p4_remove_selected_stock_position(self) -> None:
        """Remove the currently selected stock position from the active portfolio."""
        if self._p4_active_portfolio_is_combined():
            return
        ticker = self._p4_selected_stock_ticker()
        if not ticker:
            QMessageBox.information(self, 'Remove Position', 'Select a stock position to remove.')
            self._p4_update_remove_stock_button_state()
            return
        self._p4_remove_active_ticker(ticker)
        self._p4_update_remove_stock_button_state()

    def _init_options_tab(self) -> Any:
        """Build the Options section widget and return it."""
        options_widget = QFrame()
        self.set_theme_role(options_widget, 'panel')
        layout = QVBoxLayout(options_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        title_lbl = QLabel('Options Positions')
        self.set_theme_role(title_lbl, 'section_title')
        header.addWidget(title_lbl)
        header.addSpacing(10)
        self.p4_add_options_btn = QPushButton('+ Add Position')
        self.p4_add_options_btn.setMinimumHeight(24)
        self.set_theme_variant(self.p4_add_options_btn, 'positive')
        self.p4_add_options_btn.clicked.connect(self._add_options_row)
        self.p4_remove_options_btn = QPushButton('Remove Position')
        self.p4_remove_options_btn.setMinimumHeight(24)
        self.p4_remove_options_btn.setEnabled(False)
        self.set_theme_variant(self.p4_remove_options_btn, 'danger')
        self.p4_remove_options_btn.clicked.connect(self._p4_remove_selected_options_position)
        refresh_opt_btn = QPushButton('↻ Sync')
        refresh_opt_btn.setMinimumHeight(24)
        self.set_theme_variant(refresh_opt_btn, 'accent')
        refresh_opt_btn.clicked.connect(self._sync_all_options)
        header.addWidget(self.p4_add_options_btn)
        header.addSpacing(6)
        header.addWidget(self.p4_remove_options_btn)
        header.addSpacing(6)
        header.addWidget(refresh_opt_btn)
        header.addStretch()
        layout.addLayout(header)
        self.p4_opt_table = QTableWidget(0, len(P4_OPTIONS_COLUMNS))
        self.p4_opt_table.setHorizontalHeaderLabels(list(P4_OPTIONS_COLUMNS))
        oh = self.p4_opt_table.horizontalHeader()
        for col in range(len(P4_OPTIONS_COLUMNS)):
            oh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.p4_opt_table.verticalHeader().setVisible(False)
        self.p4_opt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p4_opt_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p4_opt_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p4_opt_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.p4_opt_table.verticalHeader().setDefaultSectionSize(38)
        self.p4_opt_table.setAlternatingRowColors(True)
        self.p4_opt_table.itemChanged.connect(self._on_options_cell_changed)
        self.p4_opt_table.itemSelectionChanged.connect(self._p4_update_remove_options_button_state)
        layout.addWidget(self.p4_opt_table, 1)
        for pos in self.options_data:
            self._insert_options_row(pos)
        self._p4_apply_table_width_preferences('options')
        oh.sectionResized.connect(lambda logical, old, new: self._p4_on_table_section_resized('options', logical, old, new))
        return options_widget

    def _p4_option_sync_snapshots(self) -> list[dict[str, Any]]:
        """Capture option-row state on the Qt thread before background syncing."""
        table = self.p4_opt_table
        portfolio_id = str(getattr(self, 'active_portfolio_id', '') or '').strip()
        portfolio_prices = {}
        if isinstance(getattr(self, 'last_data', None), dict):
            raw_portfolio = self.last_data.get('portfolio', {})
            portfolio_prices = dict(raw_portfolio) if isinstance(raw_portfolio, dict) else {}
        snapshots: list[dict[str, Any]] = []
        needs_save = False
        for row in range(table.rowCount()):
            if row >= len(self.options_data) or not isinstance(self.options_data[row], dict):
                continue
            pos = self.options_data[row]
            before_row_id = str(pos.get('row_id', '') or '').strip()
            row_id = self._ensure_option_row_id(pos)
            needs_save = needs_save or (bool(row_id) and row_id != before_row_id)
            ticker_item = table.item(row, 0)
            ticker = (ticker_item.text() if ticker_item is not None else pos.get('ticker', '')).strip().upper()
            if not ticker:
                continue
            strategy_widget = table.cellWidget(row, 1)
            if isinstance(strategy_widget, QComboBox):
                strategy = strategy_widget.currentData() or strategy_widget.currentText()
            else:
                strategy = pos.get('strategy', 'Calls')
            if hasattr(self, '_option_strategy_value'):
                strategy = self._option_strategy_value(strategy)
            expiry_widget = table.cellWidget(row, 2)
            expiry = ''
            if isinstance(expiry_widget, QComboBox):
                expiry = str(expiry_widget.currentData() or expiry_widget.currentText() or '').split()[0].strip()
            if not expiry:
                expiry = str(pos.get('expiry', '') or '').strip()
            strike_item = table.item(row, 3)
            strike_value = strike_item.text() if strike_item is not None else pos.get('strike', 0.0)
            strike = self._clean_option_number(str(strike_value).replace('$', '').replace(',', ''), self._clean_option_number(pos.get('strike', 0.0)))
            underlying_price = 0.0
            raw_underlying = portfolio_prices.get(ticker, {})
            if isinstance(raw_underlying, dict):
                underlying_price = self._clean_option_number(raw_underlying.get('price', 0.0))
            snapshots.append({
                'row_index': row,
                'row_id': row_id,
                'portfolio_id': portfolio_id,
                'ticker': ticker,
                'strategy': strategy,
                'expiry': expiry,
                'strike': strike,
                'underlying_price': underlying_price,
            })
        if needs_save:
            self._save_active_options_data()
        return snapshots

    def _p4_set_option_sync_fetching(self, row_id: Any, ticker: Any, portfolio_id: Any=None) -> None:
        """Mark a still-live option row as fetching from the Qt thread."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is not None:
            self._set_row_fetching_status(row)

    def _p4_apply_option_sync_result(
        self,
        row_id: Any,
        ticker: Any,
        expiries: Any,
        selected_expiry: Any,
        data_package: Any,
        portfolio_id: Any=None,
    ) -> None:
        """Apply a bulk-sync result without triggering a second quote fetch."""
        row = self._resolve_active_option_row_by_id(row_id, ticker, portfolio_id)
        if row is None:
            return
        expiry_list = [str(expiry) for expiry in list(expiries or []) if expiry]
        expiry = str(selected_expiry or '').strip()
        if expiry_list:
            self._set_expiry_combo(
                row_id,
                ticker,
                expiry_list,
                portfolio_id,
                selected_expiry=expiry if expiry in expiry_list else None,
                fetch_price=False,
            )
        elif not expiry:
            self._reset_expiry_placeholder(row_id, ticker, 'N/A', portfolio_id)
        self._update_option_price_ui(row_id, ticker, data_package, portfolio_id)

    def _sync_all_options(self) -> None:
        """Refresh expiries and current prices for all options in the table sequentially."""
        snapshots = self._p4_option_sync_snapshots()
        if not snapshots:
            return
        self.set_status_text(self.status_bar, 'Syncing all options...', status='accent')

        def _run_sync() -> None:
            """Handle run sync."""
            success_count = 0
            fail_count = 0
            total = len(snapshots)
            for index, snapshot in enumerate(snapshots):
                ticker = snapshot['ticker']
                row_id = snapshot['row_id']
                portfolio_id = snapshot['portfolio_id']
                self._invoke_main.emit(lambda r=index, sym=ticker: self.status_bar.setText(f'Syncing {sym} ({r + 1}/{total})...'))
                self._invoke_main.emit(lambda rid=row_id, sym=ticker, pid=portfolio_id: self._p4_set_option_sync_fetching(rid, sym, pid))
                expiries = self._fetch_option_expiries_list_sync(ticker)
                selected_expiry = snapshot.get('expiry', '')
                if expiries and selected_expiry not in expiries:
                    selected_expiry = expiries[0]
                data_package = self._fetch_option_quote_for_values_sync(
                    ticker,
                    selected_expiry,
                    snapshot.get('strike', 0.0),
                    snapshot.get('strategy', 'Calls'),
                    underlying_price=snapshot.get('underlying_price', 0.0),
                )
                if isinstance(data_package, dict) and data_package.get('error'):
                    fail_count += 1
                else:
                    success_count += 1
                self._invoke_main.emit(
                    lambda rid=row_id, sym=ticker, exp=list(expiries), selected=selected_expiry, data=data_package, pid=portfolio_id:
                    self._p4_apply_option_sync_result(rid, sym, exp, selected, data, pid)
                )
            msg = f'Sync Complete: {success_count} succeeded, {fail_count} failed'
            status = 'positive' if fail_count == 0 else 'warning'
            self._invoke_main.emit(lambda: self.set_status_text(self.status_bar, msg, status=status))

        self._p4_submit_background_task(_run_sync)

    def _apply_portfolio_theme(self) -> None:
        """Refresh portfolio-page plot colors after a theme change."""
        self._p4_apply_positions_splitter_theme()
        for chart in getattr(self, 'p4_returns_charts', {}).values():
            self.style_plot_widget(chart)
        for chart in getattr(self, 'p4_momentum_charts', {}).values():
            self.style_plot_widget(chart)
        if hasattr(self, 'p4_weight_chart'):
            self.style_plot_widget(self.p4_weight_chart)
        if hasattr(self, 'p4_pie_chart'):
            self.p4_pie_chart.set_theme(self.theme_pie_palette(), self.theme_color('text_primary'))
        if hasattr(self, '_apply_portfolio_heatmap_theme'):
            self._apply_portfolio_heatmap_theme()
