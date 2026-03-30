from __future__ import annotations
from collections import deque
from typing import Any
from .. import __version__
from ..compat import *


class _SessionLogHandler(logging.Handler):

    def __init__(self, window: Any) -> None:
        """Stream formatted log records into the running Qt window."""
        super().__init__(level=logging.INFO)
        self.window = window

    def emit(self, record: logging.LogRecord) -> None:
        """Format a log record and enqueue it onto the UI thread."""
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        try:
            self.window._invoke_main.emit(lambda msg=message: self.window._append_session_log_entry(msg))
        except RuntimeError:
            return


def _window_bootstrap_default_portfolio_entry(portfolio_id: Any) -> Any:
    """Build a local empty portfolio entry without importing private persistence helpers."""
    return {
        'id': portfolio_id,
        'name': DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, str(portfolio_id or DEFAULT_MAIN_PORTFOLIO_ID)),
        'portfolio': [],
        'chart_slots': list(DEFAULT_CHART_SLOTS),
        'portfolio_tracker': {},
        'options_tracker': [],
    }


def _window_bootstrap_normalize_portfolio_order(raw_order: Any, raw_portfolios: Any=None) -> list[str]:
    """Return a non-empty ordered list of supported portfolio ids."""
    order = []
    if isinstance(raw_order, list):
        for value in raw_order:
            portfolio_id = str(value or '').strip()
            if portfolio_id in PORTFOLIO_IDS and portfolio_id not in order:
                order.append(portfolio_id)
    portfolios = raw_portfolios if isinstance(raw_portfolios, dict) else {}
    for portfolio_id in portfolios.keys():
        clean_id = str(portfolio_id or '').strip()
        if clean_id in PORTFOLIO_IDS and clean_id not in order:
            order.append(clean_id)
    if not order:
        order = [DEFAULT_MAIN_PORTFOLIO_ID]
    return order[:MAX_PORTFOLIOS]


class WindowBootstrapMixin:
    _PORTFOLIO_PERSIST_DEBOUNCE_MS = 250
    _DASHBOARD_STATE_PERSIST_DEBOUNCE_MS = 250
    _OPTIONS_FETCH_MAX_WORKERS = 4

    def _get_cache_manager(self) -> Any:
        """Return the shared cache manager for the running app session."""
        cache = getattr(self, '_cache_manager', None)
        if cache is None:
            cache = CacheManager()
            self._cache_manager = cache
        return cache

    def _portfolio_order(self) -> list[str]:
        """Return the current ordered portfolio id list, keeping state non-empty."""
        portfolios = self.all_portfolios_state.setdefault('portfolios', {})
        raw_order = self.all_portfolios_state.get('portfolio_order', [])
        order = [pid for pid in _window_bootstrap_normalize_portfolio_order(raw_order, portfolios) if pid in portfolios]
        if not order:
            order = [DEFAULT_MAIN_PORTFOLIO_ID]
            portfolios[DEFAULT_MAIN_PORTFOLIO_ID] = _window_bootstrap_default_portfolio_entry(DEFAULT_MAIN_PORTFOLIO_ID)
        self.all_portfolios_state['portfolio_order'] = order
        return list(order)

    def _portfolio_index_from_id(self, portfolio_id: Any) -> int:
        """Return the current ordered tab index for a portfolio id."""
        portfolio_ids = self._portfolio_order()
        try:
            return portfolio_ids.index(str(portfolio_id or '').strip())
        except ValueError:
            return 0

    def _portfolio_id_from_index(self, index: Any) -> Any:
        """Return the current ordered portfolio id for a tab index."""
        portfolio_ids = self._portfolio_order()
        try:
            numeric = int(index)
        except (TypeError, ValueError):
            numeric = 0
        numeric = min(max(numeric, 0), len(portfolio_ids) - 1)
        return portfolio_ids[numeric]

    def _rebuild_portfolio_slots(self) -> None:
        """Mirror the persisted portfolio catalog into the UI-friendly ordered slot list."""
        slots = []
        portfolios = self.all_portfolios_state.get('portfolios', {})
        portfolio_order = self._portfolio_order()
        for index, portfolio_id in enumerate(portfolio_order):
            entry = portfolios.get(portfolio_id, {})
            slots.append({
                'id': index,
                'portfolio_id': portfolio_id,
                'name': str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)),
            })
        self.portfolio_slots = slots
        self.main_portfolio_index = self._portfolio_index_from_id(self.main_portfolio_id)
        self.active_portfolio_index = self._portfolio_index_from_id(self.active_portfolio_id)

    def _get_portfolio_entry(self, portfolio_id: Any=None) -> Any:
        """Return a mutable portfolio entry from the runtime state."""
        portfolio_order = self._portfolio_order()
        if portfolio_id is None:
            pid = self._portfolio_id_from_index(self.active_portfolio_index)
        else:
            clean_id = str(portfolio_id or '').strip()
            pid = clean_id if clean_id in portfolio_order else portfolio_order[0]
        entry = self.all_portfolios_state.setdefault('portfolios', {}).setdefault(pid, {
            'name': DEFAULT_PORTFOLIO_NAMES.get(pid, pid),
            'portfolio': [],
            'chart_slots': list(DEFAULT_CHART_SLOTS),
            'portfolio_tracker': {},
            'options_tracker': [],
        })
        entry.setdefault('portfolio', [])
        entry.setdefault('chart_slots', list(DEFAULT_CHART_SLOTS))
        entry.setdefault('portfolio_tracker', {})
        entry.setdefault('options_tracker', [])
        return entry

    def _apply_main_portfolio_runtime(self) -> None:
        """Sync app-wide runtime fields from the selected main portfolio."""
        entry = self._get_portfolio_entry(self.main_portfolio_id)
        self.tickers = entry['portfolio']
        self.chart_slots = entry['chart_slots']
        self.tracker_data = entry['portfolio_tracker']
        if not getattr(self, '_dashboard_chart_initialized', False):
            fallback_symbol = str((self.chart_slots[0] if self.chart_slots else '') or '').upper().strip()
            current_symbol = str(getattr(self, 'dashboard_chart_state', {}).get('symbol', '') or '').upper().strip()
            if fallback_symbol and (not current_symbol or current_symbol == DEFAULT_DASHBOARD_CHART_SETTINGS['symbol']):
                self.dashboard_chart_state = normalize_dashboard_chart_settings({
                    **getattr(self, 'dashboard_chart_state', {}),
                    'symbol': fallback_symbol,
                })
                self._dashboard_chart_initialized = True

    def _apply_active_portfolio_editor_state(self) -> None:
        """Sync page-4 editor fields from the selected active portfolio."""
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        self.active_tickers = entry['portfolio']
        self.active_tracker_data = entry['portfolio_tracker']
        self.options_data = entry['options_tracker']
        self.active_options_data = self.options_data

    def _save_active_options_data(self) -> None:
        """Persist page-4 options rows to the selected active portfolio."""
        self._get_portfolio_entry(self.active_portfolio_id)['options_tracker'] = list(self.options_data)
        self._persist_all_portfolios()

    def _active_portfolio_uses_main_runtime(self) -> bool:
        """Return whether the portfolio editor is currently showing the app-wide main portfolio."""
        return self.active_portfolio_id == self.main_portfolio_id

    def _get_fetch_tickers(self) -> Any:
        """Return the deduplicated ticker set needed across saved portfolios."""
        combined = []
        for portfolio_id in self._portfolio_order():
            entry = self._get_portfolio_entry(portfolio_id)
            for ticker in list(entry.get('portfolio', [])):
                text = str(ticker or '').upper().strip()
                if text and text not in combined:
                    combined.append(text)
        return combined

    def _flush_portfolio_persist(self) -> None:
        """Write the current in-memory portfolio state to disk immediately."""
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        self.all_portfolios_state['portfolio_order'] = self._portfolio_order()
        save_all_portfolios_state(self.all_portfolios_state)

    def _persist_all_portfolios(self, *, immediate: bool=False) -> None:
        """Persist the full runtime portfolio state, buffering bursty edits."""
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        self.all_portfolios_state['portfolio_order'] = self._portfolio_order()
        if immediate:
            if hasattr(self, '_portfolio_persist_timer'):
                self._portfolio_persist_timer.stop()
            self._flush_portfolio_persist()
            return
        if hasattr(self, '_portfolio_persist_timer'):
            self._portfolio_persist_timer.start(self._PORTFOLIO_PERSIST_DEBOUNCE_MS)
        else:
            self._flush_portfolio_persist()

    def _flush_dashboard_state_persist(self) -> None:
        """Write the current dashboard chart state to disk immediately."""
        self.dashboard_chart_state = save_dashboard_chart_settings(self.dashboard_chart_state)

    def _persist_dashboard_state(self, *, immediate: bool=False) -> None:
        """Persist dashboard chart settings, buffering repeated UI tweaks."""
        if immediate:
            if hasattr(self, '_dashboard_state_persist_timer'):
                self._dashboard_state_persist_timer.stop()
            self._flush_dashboard_state_persist()
            return
        if hasattr(self, '_dashboard_state_persist_timer'):
            self._dashboard_state_persist_timer.start(self._DASHBOARD_STATE_PERSIST_DEBOUNCE_MS)
        else:
            self._flush_dashboard_state_persist()

    def _init_session_log_capture(self) -> None:
        """Attach a single in-memory session log collector to the app logger."""
        self._session_log_max_entries = 1500
        self._session_log_buffer = deque(maxlen=self._session_log_max_entries)
        self._session_log_paused = False
        self._session_log_rendered_entries = 0
        self._session_log_needs_rebuild = False
        self.settings_log_output = None
        self._session_log_handler = _SessionLogHandler(self)
        self._session_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(self._session_log_handler)

    def _configure_settings_log_output(self, widget: Any) -> None:
        """Apply bounded live-log document settings to the Settings viewer."""
        if widget is None:
            return
        widget.document().setMaximumBlockCount(max(int(getattr(self, '_session_log_max_entries', 0) or 0), 1))

    def _rebuild_settings_log_output(self) -> None:
        """Replace the Settings log viewer text from the current bounded buffer."""
        if self.settings_log_output is None:
            return
        self._configure_settings_log_output(self.settings_log_output)
        self.settings_log_output.setPlainText('\n'.join(self._session_log_buffer))
        self._session_log_rendered_entries = len(self._session_log_buffer)
        self._session_log_needs_rebuild = False

    def _append_settings_log_lines(self, lines: Any) -> None:
        """Append one or more preformatted log lines to the live Settings viewer."""
        if self.settings_log_output is None:
            return
        text_lines = [str(line or '').rstrip() for line in list(lines)]
        text_lines = [line for line in text_lines if line]
        if not text_lines:
            return
        self._configure_settings_log_output(self.settings_log_output)
        self.settings_log_output.setUpdatesEnabled(False)
        try:
            for line in text_lines:
                self.settings_log_output.appendPlainText(line)
        finally:
            self.settings_log_output.setUpdatesEnabled(True)
            self.settings_log_output.viewport().update()
        self._session_log_rendered_entries = len(self._session_log_buffer)

    def _append_session_log_entry(self, message: Any) -> None:
        """Append a formatted log line to the session buffer and Settings panel."""
        text = str(message or '').rstrip()
        if not text:
            return
        overflow = len(self._session_log_buffer) >= self._session_log_max_entries
        self._session_log_buffer.append(text)
        self._refresh_settings_log_status()
        if self.settings_log_output is None:
            self._session_log_needs_rebuild = True
            return
        if self._session_log_paused:
            if overflow:
                self._session_log_needs_rebuild = True
            return
        if self._session_log_needs_rebuild:
            self._rebuild_settings_log_output()
        else:
            self._append_settings_log_lines((text,))
        if self.settings_log_output is not None:
            scrollbar = self.settings_log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _bind_settings_log_output(self, widget: Any) -> None:
        """Attach the live Settings log widget to the current session buffer."""
        self.settings_log_output = widget
        if self.settings_log_output is None:
            return
        self._rebuild_settings_log_output()
        self._refresh_settings_log_status()
        if not self._session_log_paused:
            scrollbar = self.settings_log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear_session_logs(self) -> None:
        """Clear the visible in-memory session log history."""
        self._session_log_buffer.clear()
        self._session_log_rendered_entries = 0
        self._session_log_needs_rebuild = False
        if self.settings_log_output is not None:
            self.settings_log_output.clear()
        self._refresh_settings_log_status()

    def _set_session_log_paused(self, paused: Any) -> None:
        """Pause or resume live app log appends in the Settings viewer."""
        self._session_log_paused = bool(paused)
        self._refresh_settings_log_status()
        if not self._session_log_paused and self.settings_log_output is not None:
            if self._session_log_needs_rebuild or self._session_log_rendered_entries > len(self._session_log_buffer):
                self._rebuild_settings_log_output()
            else:
                pending_lines = list(self._session_log_buffer)[self._session_log_rendered_entries:]
                if pending_lines:
                    self._append_settings_log_lines(pending_lines)
            scrollbar = self.settings_log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _refresh_settings_log_status(self) -> None:
        """Refresh the Settings-page log status label."""
        if not hasattr(self, 'settings_log_meta_label'):
            return
        count = len(getattr(self, '_session_log_buffer', []))
        state = 'Paused' if getattr(self, '_session_log_paused', False) else 'Live'
        self.settings_log_meta_label.setText(f'{state} session log | {count} entries')

    def _sync_after_portfolio_change(self, *, refresh_main: bool=False) -> None:
        """Refresh derived runtime fields and visible page-4 widgets."""
        self._rebuild_portfolio_slots()
        self._apply_main_portfolio_runtime()
        self._apply_active_portfolio_editor_state()
        if hasattr(self, '_sync_chart_slot_inputs'):
            self._sync_chart_slot_inputs()
        if hasattr(self, '_reload_options_table'):
            self._reload_options_table()
        if hasattr(self, '_p4_refresh_portfolio_selector'):
            self._p4_refresh_portfolio_selector()
        if hasattr(self, '_dashboard_refresh_portfolio_selector'):
            self._dashboard_refresh_portfolio_selector()
        if hasattr(self, '_p10_rebuild_watchlists'):
            self._p10_rebuild_watchlists()
        if hasattr(self, '_p6_update_total'):
            self._p6_update_total()
        if hasattr(self, '_p7_refresh_options_expirations'):
            self._p7_refresh_options_expirations()
        if getattr(self, 'last_data', None):
            self.update_page4(self.last_data)
            self.repopulate_portfolio()
        if refresh_main:
            self.last_data = None
            self.refresh_data(force=True)

    def set_active_portfolio_index(self, index: Any) -> None:
        """Switch the page-4 editor to a different portfolio slot."""
        self.active_portfolio_id = self._portfolio_id_from_index(index)
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=False)

    def rename_portfolio(self, index: Any, name: Any) -> None:
        """Rename an existing portfolio."""
        portfolio_id = self._portfolio_id_from_index(index)
        clean_name = str(name or '').strip() or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)
        self._get_portfolio_entry(portfolio_id)['name'] = clean_name
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=False)

    def set_main_portfolio_index(self, index: Any) -> None:
        """Promote the selected portfolio to the app-wide main portfolio."""
        self.main_portfolio_id = self._portfolio_id_from_index(index)
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=True)

    def create_portfolio(self) -> bool:
        """Create a new empty portfolio and switch the editor to it."""
        portfolio_order = self._portfolio_order()
        if len(portfolio_order) >= MAX_PORTFOLIOS:
            return False
        available_ids = [portfolio_id for portfolio_id in PORTFOLIO_IDS if portfolio_id not in portfolio_order]
        if not available_ids:
            return False
        portfolio_id = available_ids[0]
        portfolios = self.all_portfolios_state.setdefault('portfolios', {})
        portfolios[portfolio_id] = _window_bootstrap_default_portfolio_entry(portfolio_id)
        portfolio_order.append(portfolio_id)
        self.all_portfolios_state['portfolio_order'] = portfolio_order
        self.active_portfolio_id = portfolio_id
        self.all_portfolios_state['active_portfolio_id'] = portfolio_id
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=False)
        return True

    def delete_portfolio(self, index: Any) -> bool:
        """Delete one portfolio while preserving a valid active and main selection."""
        portfolio_order = self._portfolio_order()
        if len(portfolio_order) <= 1:
            return False
        try:
            delete_index = int(index)
        except (TypeError, ValueError):
            delete_index = self._portfolio_index_from_id(self.active_portfolio_id)
        delete_index = min(max(delete_index, 0), len(portfolio_order) - 1)
        portfolio_id = portfolio_order[delete_index]
        remaining_order = [pid for pid in portfolio_order if pid != portfolio_id]
        if not remaining_order:
            return False
        replacement_index = min(delete_index, len(remaining_order) - 1)
        replacement_id = remaining_order[replacement_index]
        deleted_main = portfolio_id == self.main_portfolio_id
        deleted_active = portfolio_id == self.active_portfolio_id
        self.all_portfolios_state.setdefault('portfolios', {}).pop(portfolio_id, None)
        self.all_portfolios_state['portfolio_order'] = remaining_order
        if deleted_main:
            self.main_portfolio_id = replacement_id
        if deleted_active or self.active_portfolio_id not in remaining_order:
            self.active_portfolio_id = replacement_id
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        self._return_metrics_cache = {
            key: value for key, value in getattr(self, '_return_metrics_cache', {}).items()
            if str(key[0]) != str(portfolio_id)
        }
        self._return_metrics_fetching = {
            key: value for key, value in getattr(self, '_return_metrics_fetching', {}).items()
            if str(key[0]) != str(portfolio_id)
        }
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=deleted_main)
        return True

    def __init__(self) -> None:
        """Initialize the object."""
        super().__init__()
        self._invoke_main.connect(self._on_invoke_main)
        self._init_session_log_capture()
        self.setWindowTitle(f'Budget Terminal v{__version__}')
        self.resize(1280, 600)
        self.all_portfolios_state = load_all_portfolios_state()
        self.main_portfolio_id = self.all_portfolios_state.get('main_portfolio_id', DEFAULT_MAIN_PORTFOLIO_ID)
        self.active_portfolio_id = self.all_portfolios_state.get('active_portfolio_id', self.main_portfolio_id)
        self._rebuild_portfolio_slots()
        self.tickers = []
        self.chart_slots = []
        self.dashboard_chart_state = load_dashboard_chart_settings()
        self._dashboard_chart_initialized = False
        self.dashboard_symbol = str(self.dashboard_chart_state.get('symbol', 'SPY') or 'SPY').upper()
        self.dashboard_timeframe_label = str(self.dashboard_chart_state.get('timeframe_label', '1 Day') or '1 Day')
        self.dashboard_active_indicators = list(self.dashboard_chart_state.get('indicators', ['Volume', '200 MA']))
        self.dashboard_auto_follow = bool(self.dashboard_chart_state.get('auto', True))
        self.dashboard_chart_df = None
        self.dashboard_chart_stats = {}
        self.dashboard_rsi_series = None
        self.dashboard_chart_interval = '1d'
        self.dashboard_manual_x_range = None
        self.dashboard_pending_x_range = None
        self.dashboard_overlay_items = {}
        self.chart_configs = []
        self._dashboard_request_seq = 0
        self._dashboard_latest_request_id = 0
        self._cache_manager = CacheManager()
        self.last_data = None
        self.p2_current_data = None
        self.tracker_data = {}
        self._mktcap_cache = {}
        self._mktcap_cache_ts = {}
        self._mktcap_inflight_tickers = set()
        self._mktcap_queued_tickers = set()
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self._active_return_timeframe = 'dip_finder'
        self._news_auto_summarized = False
        self._data_collection_ts = None
        self._data_collection_sources = []
        self._portfolio_persist_timer = QTimer(self)
        self._portfolio_persist_timer.setSingleShot(True)
        self._portfolio_persist_timer.timeout.connect(self._flush_portfolio_persist)
        self._dashboard_state_persist_timer = QTimer(self)
        self._dashboard_state_persist_timer.setSingleShot(True)
        self._dashboard_state_persist_timer.timeout.connect(self._flush_dashboard_state_persist)
        self._dashboard_refresh_timer = QTimer(self)
        self._dashboard_refresh_timer.setSingleShot(True)
        self._dashboard_refresh_timer.timeout.connect(self._execute_refresh_data)
        self._options_fetch_executor = ThreadPoolExecutor(max_workers=self._OPTIONS_FETCH_MAX_WORKERS)
        self._option_chain_memory_cache = {}
        self._option_chain_memory_cache_ttl = 60.0
        self._options_expiry_memory_cache = {}
        self._options_expiry_memory_cache_ttl = 900.0
        self.options_data = []
        self.active_tickers = []
        self.active_tracker_data = {}
        self.active_options_data = []
        self.networth_data = load_networth_data()
        self.theme_settings = load_theme_settings()
        self.chart_page_state = load_chart_page_settings()
        self.init_theme_system(apply=False)
        self.dashboard_chart_rows = []
        self.dashboard_chart_ma200 = None
        self.dashboard_chart_view_guard = False
        self._apply_main_portfolio_runtime()
        self._apply_active_portfolio_editor_state()
        self.init_ui()
        self.theme_manager.apply_theme(self.current_theme_id, persist=False)
        self._sync_after_portfolio_change(refresh_main=False)
        self.refresh_data(force=True)

    def _on_invoke_main(self, fn: Any) -> None:
        """Handle invoke main."""
        fn()

    def _start_clock_timer(self) -> None:
        """Handle start clock timer."""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
