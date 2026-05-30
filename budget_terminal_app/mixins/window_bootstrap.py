from __future__ import annotations
from collections import deque
from copy import deepcopy
from contextlib import contextmanager, nullcontext
from typing import Any
from .. import __version__
from ..compat import *
from ..startup_metrics import make_launch_id, upsert_startup_launch, utc_now_iso


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
        'cash_balance': 0.0,
    }


def _window_bootstrap_normalize_cash_balance(value: Any) -> float:
    """Return a non-negative brokerage cash balance."""
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    return max(amount, 0.0)


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
    _SESSION_CACHE_PERSIST_DEBOUNCE_MS = 250
    _OPTIONS_FETCH_MAX_WORKERS = 4
    _PORTFOLIO_TASK_MAX_WORKERS = 4
    _DASHBOARD_FETCH_MAX_WORKERS = 2
    _P17_FETCH_MAX_WORKERS = 3
    _STARTUP_METRIC_STAGE_LABELS = {
        'first_ui': 'First UI',
        'dashboard_data': 'Dashboard Data',
        'session_restore': 'Session Restore',
        'startup_data': 'Startup Data',
        'page_warmup': 'Page Warmup',
        'cache_warmup': 'Cache Warmup',
    }

    def _startup_metrics_elapsed(self) -> float:
        """Return elapsed seconds from the startup profiler, when available."""
        profiler = getattr(self, '_startup_profiler', None)
        if profiler is None:
            return 0.0
        elapsed = getattr(profiler, 'elapsed', None)
        if callable(elapsed):
            return float(elapsed())
        return 0.0

    def _init_startup_metrics_state(self) -> None:
        """Create this process' startup metrics entry."""
        launch_id = make_launch_id()
        stages = {}
        for key, label in self._STARTUP_METRIC_STAGE_LABELS.items():
            stages[key] = {
                'label': label,
                'status': 'pending',
                'detail': '',
                'count': None,
                'started_seconds': None,
                'completed_seconds': None,
                'duration_seconds': None,
            }
        self._startup_metrics_current = {
            'launch_id': launch_id,
            'started_at': utc_now_iso(),
            'completed_at': '',
            'app_version': __version__,
            'status': 'running',
            'total_seconds': None,
            'stages': stages,
        }
        self._persist_startup_metrics_current()

    def _startup_metrics_terminal(self, status: Any) -> bool:
        """Return whether one stage status no longer represents active work."""
        return str(status or '') in {'complete', 'skipped', 'failed'}

    def _refresh_startup_metrics_launch_status(self) -> None:
        """Derive launch-level status from stage statuses."""
        launch = getattr(self, '_startup_metrics_current', None)
        if not isinstance(launch, dict):
            return
        stages = launch.get('stages', {})
        if not isinstance(stages, dict) or not stages:
            return
        stage_values = list(stages.values())
        if all(self._startup_metrics_terminal(stage.get('status')) for stage in stage_values if isinstance(stage, dict)):
            failed = any(str(stage.get('status', '') or '') == 'failed' for stage in stage_values if isinstance(stage, dict))
            launch['status'] = 'partial' if failed else 'complete'
            launch['completed_at'] = utc_now_iso()
            completed_values = [
                float(stage.get('completed_seconds') or 0.0)
                for stage in stage_values
                if isinstance(stage, dict) and stage.get('completed_seconds') is not None
            ]
            launch['total_seconds'] = max(completed_values) if completed_values else self._startup_metrics_elapsed()
        else:
            launch['status'] = 'running'
            launch['total_seconds'] = self._startup_metrics_elapsed()

    def _persist_startup_metrics_current(self) -> None:
        """Persist the current launch metrics without impacting startup flow."""
        launch = getattr(self, '_startup_metrics_current', None)
        if not isinstance(launch, dict):
            return
        try:
            upsert_startup_launch(launch)
        except Exception:
            logger.debug('Unable to persist startup metrics.', exc_info=True)

    def _startup_metrics_snapshot(self) -> dict[str, Any]:
        """Return a current-run startup metrics snapshot for Settings."""
        launch = deepcopy(getattr(self, '_startup_metrics_current', {}) or {})
        if not isinstance(launch, dict):
            return {}
        now_seconds = self._startup_metrics_elapsed()
        stages = launch.get('stages', {})
        if isinstance(stages, dict):
            for stage in stages.values():
                if not isinstance(stage, dict):
                    continue
                if str(stage.get('status', '') or '') == 'running':
                    started = stage.get('started_seconds')
                    try:
                        stage['duration_seconds'] = max(0.0, now_seconds - float(started))
                    except (TypeError, ValueError):
                        stage['duration_seconds'] = None
        if str(launch.get('status', '') or '') == 'running':
            launch['total_seconds'] = now_seconds
        return launch

    def _startup_metrics_set_stage(
        self,
        key: str,
        *,
        status: str,
        detail: Any = None,
        count: Any = None,
        completed_seconds: float | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """Update one startup metric stage and refresh Settings if visible."""
        launch = getattr(self, '_startup_metrics_current', None)
        if not isinstance(launch, dict):
            return
        stages = launch.setdefault('stages', {})
        stage = stages.setdefault(key, {
            'label': self._STARTUP_METRIC_STAGE_LABELS.get(key, key),
            'status': 'pending',
            'detail': '',
            'count': None,
            'started_seconds': None,
            'completed_seconds': None,
            'duration_seconds': None,
        })
        now_seconds = self._startup_metrics_elapsed()
        previous_started = stage.get('started_seconds')
        stage['label'] = self._STARTUP_METRIC_STAGE_LABELS.get(key, stage.get('label', key))
        stage['status'] = str(status or 'pending')
        if detail is not None:
            stage['detail'] = str(detail or '')
        if count is not None:
            stage['count'] = count
        if stage['status'] == 'running':
            stage['started_seconds'] = now_seconds
            stage['completed_seconds'] = None
            stage['duration_seconds'] = None
        elif self._startup_metrics_terminal(stage['status']):
            if completed_seconds is None:
                completed_seconds = now_seconds
            stage['completed_seconds'] = float(completed_seconds)
            if duration_seconds is None:
                try:
                    if previous_started is not None:
                        duration_seconds = max(0.0, float(completed_seconds) - float(previous_started))
                except (TypeError, ValueError):
                    duration_seconds = None
            if duration_seconds is None:
                duration_seconds = float(completed_seconds)
            stage['duration_seconds'] = float(duration_seconds)
        self._refresh_startup_metrics_launch_status()
        self._persist_startup_metrics_current()
        refresh = getattr(self, '_refresh_startup_performance_views', None)
        if callable(refresh):
            refresh()

    def _startup_profiler_stamp(self, name: str) -> None:
        """Record one startup milestone when profiling is enabled."""
        profiler = getattr(self, '_startup_profiler', None)
        if profiler is not None:
            profiler.stamp(name)

    def _startup_profiler_step(self, name: str) -> Any:
        """Return a no-op or active startup timing context manager."""
        profiler = getattr(self, '_startup_profiler', None)
        if profiler is None:
            return nullcontext()
        return profiler.step(name)

    @contextmanager
    def _startup_progress_step(self, key: str, label: str | None = None) -> Any:
        """Update the startup loading screen around one synchronous step."""
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.begin(key, label)
        try:
            yield
        finally:
            if progress is not None:
                progress.complete(key, label)

    def _startup_progress_begin(self, key: str, label: str | None = None) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.begin(key, label)

    def _startup_progress_complete(self, key: str, label: str | None = None) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.complete(key, label)

    def _startup_progress_begin_page(self, index: Any, label: str | None = None) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.begin_page(index, label)

    def _startup_progress_complete_page(self, index: Any, label: str | None = None) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.complete_page(index, label)

    def _startup_progress_register_pages(self, page_labels: Any) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.register_pages(page_labels)

    def _startup_progress_switch_to_compact(self) -> None:
        progress = getattr(self, '_startup_progress', None)
        if progress is not None:
            progress.switch_to_compact(self)

    def _startup_progress_finish_if_complete(self) -> bool:
        progress = getattr(self, '_startup_progress', None)
        return bool(progress is not None and progress.finish_if_complete())

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
            'cash_balance': 0.0,
        })
        entry.setdefault('portfolio', [])
        entry.setdefault('chart_slots', list(DEFAULT_CHART_SLOTS))
        entry.setdefault('portfolio_tracker', {})
        entry.setdefault('options_tracker', [])
        entry['cash_balance'] = _window_bootstrap_normalize_cash_balance(entry.get('cash_balance'))
        return entry

    def _apply_main_portfolio_runtime(self) -> None:
        """Sync app-wide runtime fields from the selected main portfolio."""
        entry = self._get_portfolio_entry(self.main_portfolio_id)
        self.tickers = entry['portfolio']
        self.chart_slots = entry['chart_slots']
        self.tracker_data = entry['portfolio_tracker']
        self.cash_balance = entry['cash_balance']
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
        self.active_cash_balance = entry['cash_balance']

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

    def _session_cache_tabs(self) -> dict[str, Any]:
        """Return the mutable tab-session cache payload map."""
        cache = getattr(self, '_tab_session_cache', None)
        if not isinstance(cache, dict):
            cache = load_tab_session_cache()
            self._tab_session_cache = cache
        tabs = cache.get('tabs')
        if not isinstance(tabs, dict):
            tabs = {}
            cache['tabs'] = tabs
        return tabs

    def _get_tab_session_snapshot(self, tab_key: str) -> dict[str, Any] | None:
        """Return one cached tab snapshot when available."""
        payload = self._session_cache_tabs().get(str(tab_key or '').strip())
        return deepcopy(payload) if isinstance(payload, dict) else None

    def _flush_tab_session_cache(self) -> None:
        """Write the current in-memory tab-session cache to disk immediately."""
        self._tab_session_cache = save_tab_session_cache(getattr(self, '_tab_session_cache', {}))

    def _persist_tab_session_cache(self, *, immediate: bool=False) -> None:
        """Persist cached tab snapshots, buffering bursty updates."""
        if immediate:
            if hasattr(self, '_session_cache_persist_timer'):
                self._session_cache_persist_timer.stop()
            self._flush_tab_session_cache()
            return
        if hasattr(self, '_session_cache_persist_timer'):
            self._session_cache_persist_timer.start(self._SESSION_CACHE_PERSIST_DEBOUNCE_MS)
        else:
            self._flush_tab_session_cache()

    def _set_tab_session_snapshot(self, tab_key: str, payload: Any, *, immediate: bool=False) -> None:
        """Replace one cached tab snapshot and schedule persistence."""
        key = str(tab_key or '').strip()
        if not key:
            return
        tabs = self._session_cache_tabs()
        snapshot = deepcopy(payload) if isinstance(payload, dict) else None
        if isinstance(snapshot, dict):
            snapshot['_session_saved_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tabs[key] = snapshot
        self._persist_tab_session_cache(immediate=immediate)

    def _clear_tab_session_cache(self, *, immediate: bool=False) -> None:
        """Clear all cached tab snapshots from memory and disk."""
        self._tab_session_cache = clear_tab_session_cache()
        if immediate:
            if hasattr(self, '_session_cache_persist_timer'):
                self._session_cache_persist_timer.stop()
            return
        self._persist_tab_session_cache()

    def _ensure_options_fetch_executor(self) -> Any:
        """Create the shared options executor only when the portfolio page needs it."""
        executor = getattr(self, '_options_fetch_executor', None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=self._OPTIONS_FETCH_MAX_WORKERS)
            self._options_fetch_executor = executor
        return executor

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
        self._call_if_page_initialized('_reload_options_table', page_attr='page4')
        self._call_if_page_initialized('_p4_refresh_portfolio_selector', page_attr='page4')
        if hasattr(self, '_dashboard_refresh_portfolio_selector'):
            self._dashboard_refresh_portfolio_selector()
        self._call_if_page_initialized('_p10_rebuild_watchlists', page_attr='page10')
        self._call_if_page_initialized('_p10_refresh_chart_presentation', page_attr='page10')
        self._call_if_page_initialized('_p6_update_total', page_attr='page6')
        self._call_if_page_initialized('_p7_refresh_options_expirations', page_attr='page7')
        if getattr(self, 'last_data', None):
            self._call_if_page_initialized('update_page4', self.last_data, page_attr='page4')
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
        self._momentum_metrics_cache = {
            key: value for key, value in getattr(self, '_momentum_metrics_cache', {}).items()
            if str(key[0]) != str(portfolio_id)
        }
        self._momentum_metrics_fetching = {
            key: value for key, value in getattr(self, '_momentum_metrics_fetching', {}).items()
            if str(key[0]) != str(portfolio_id)
        }
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=deleted_main)
        return True

    def __init__(self, startup_profiler: Any=None, data_service_client: Any=None, startup_progress: Any=None) -> None:
        """Initialize the object."""
        super().__init__()
        self._startup_profiler = startup_profiler
        self._startup_progress = startup_progress
        self._data_service_client = data_service_client
        self._invoke_main.connect(self._on_invoke_main)
        self._init_startup_metrics_state()
        with self._startup_profiler_step('window_init'), self._startup_progress_step('window_init', 'Main window'):
            self._init_session_log_capture()
            if hasattr(self, '_init_data_health_state'):
                self._init_data_health_state()
            self.setWindowTitle(f'Budget Terminal v{__version__}')
            with self._startup_profiler_step('state_load'), self._startup_progress_step('state_load', 'Saved state'):
                self.all_portfolios_state = load_all_portfolios_state()
                self.main_portfolio_id = self.all_portfolios_state.get('main_portfolio_id', DEFAULT_MAIN_PORTFOLIO_ID)
                self.active_portfolio_id = self.all_portfolios_state.get('active_portfolio_id', self.main_portfolio_id)
                self.fundamentals_page_state = load_fundamentals_page_settings()
                self.valuation_page_state = load_valuation_page_settings()
                self.dashboard_chart_state = load_dashboard_chart_settings()
                self.backtest_page_state = load_backtest_page_settings()
                self.portfolio_metrics_state = load_portfolio_metrics_settings()
                self.navigation_state = load_navigation_settings()
                self.networth_data = load_networth_data()
                self._tab_session_cache = load_tab_session_cache()
            self._rebuild_portfolio_slots()
            self.tickers = []
            self.chart_slots = []
            self._dashboard_chart_initialized = False
            self.dashboard_symbol = str(self.dashboard_chart_state.get('symbol', 'SPY') or 'SPY').upper()
            self.dashboard_timeframe_label = str(self.dashboard_chart_state.get('timeframe_label', '1 Day') or '1 Day')
            self.dashboard_active_indicators = list(self.dashboard_chart_state.get('indicators', ['Volume', '200 MA']))
            self.dashboard_auto_follow = bool(self.dashboard_chart_state.get('auto', True))
            self.p4_metrics_benchmark_symbol = str(
                self.portfolio_metrics_state.get('benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
                or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']
            ).upper().strip()
            self.p4_metrics_lookback_key = str(
                self.portfolio_metrics_state.get('lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
                or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
            ).strip().lower()
            self.dashboard_chart_df = None
            self.dashboard_chart_stats = {}
            self.dashboard_rsi_series = None
            self.dashboard_rsi_ma_series = None
            self.dashboard_chart_interval = '1d'
            self.dashboard_manual_x_range = None
            self.dashboard_pending_x_range = None
            self.dashboard_overlay_items = {}
            self.chart_configs = []
            self._dashboard_request_seq = 0
            self._dashboard_latest_request_id = 0
            self._dashboard_fetch_executor = None
            self._dashboard_latest_future = None
            self._p17_fetch_executor = None
            self._p17_fetch_futures = {}
            self._p25_executor = None
            self._cache_manager = CacheManager()
            self.last_data = None
            self.p2_current_data = None
            self.valuation_current_data = None
            self.p2_selected_configuration = str(
                self.fundamentals_page_state.get('selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
                or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
            ).strip().lower()
            self.p2_custom_selections_by_ticker = dict(
                self.fundamentals_page_state.get('custom_selections_by_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['custom_selections_by_ticker'])
            )
            self.tracker_data = {}
            self._mktcap_cache = {}
            self._mktcap_cache_ts = {}
            self._mktcap_inflight_tickers = set()
            self._mktcap_queued_tickers = set()
            self._return_metrics_cache = {}
            self._return_metrics_fetching = {}
            self._active_return_timeframe = 'dip_finder'
            self._momentum_metrics_cache = {}
            self._momentum_metrics_fetching = {}
            self._active_momentum_timeframe = '1mo'
            self._portfolio_analytics_cache = {}
            self._portfolio_analytics_fetching = {}
            self._data_collection_ts = None
            self._data_collection_sources = []
            self._portfolio_persist_timer = QTimer(self)
            self._portfolio_persist_timer.setSingleShot(True)
            self._portfolio_persist_timer.timeout.connect(self._flush_portfolio_persist)
            self._dashboard_state_persist_timer = QTimer(self)
            self._dashboard_state_persist_timer.setSingleShot(True)
            self._dashboard_state_persist_timer.timeout.connect(self._flush_dashboard_state_persist)
            self._session_cache_persist_timer = QTimer(self)
            self._session_cache_persist_timer.setSingleShot(True)
            self._session_cache_persist_timer.timeout.connect(self._flush_tab_session_cache)
            self._dashboard_refresh_timer = QTimer(self)
            self._dashboard_refresh_timer.setSingleShot(True)
            self._dashboard_refresh_timer.timeout.connect(self._execute_refresh_data)
            self._startup_show_completed = False
            self._startup_refresh_pending = False
            self._startup_dashboard_refresh_deferred = False
            self._startup_dashboard_timeout_pending = False
            self._startup_dashboard_data_actual_done = False
            self._startup_dashboard_data_timed_out = False
            self._startup_page_prefetch_pending = False
            self._startup_warmup_mode = 'full_blocking_with_skip'
            self._startup_released_to_user = False
            self._startup_release_reason = ''
            self._startup_data_start_pending = False
            self._startup_data_start_done = False
            self._startup_recent_data_request_keys = set()
            self._startup_cache_warmup_pending = False
            self._startup_cache_warmup_queue = []
            self._startup_session_restore_pending = False
            self._startup_session_restore_queue = []
            self._startup_session_restored_tabs = set()
            self._startup_dashboard_data_done = False
            self._lazy_warmup_started = False
            self._lazy_warmup_finished = False
            self._lazy_warmup_queue = []
            self._lazy_page_warmup_timer = QTimer(self)
            self._lazy_page_warmup_timer.setSingleShot(True)
            self._lazy_page_warmup_timer.timeout.connect(self._warm_next_page)
            self._p14_auto_refresh_timer = QTimer(self)
            self._p14_auto_refresh_timer.setInterval(int(getattr(self, '_P14_AUTO_REFRESH_INTERVAL_MS', 15 * 60 * 1000)))
            self._p14_auto_refresh_timer.timeout.connect(self._p14_auto_refresh_tick)
            self._options_fetch_executor = None
            self._portfolio_task_executor = None
            self._option_chain_memory_cache = {}
            self._option_chain_memory_cache_ttl = 60.0
            self._options_expiry_memory_cache = {}
            self._options_expiry_memory_cache_ttl = 900.0
            self.options_data = []
            self.active_tickers = []
            self.active_tracker_data = {}
            self.active_options_data = []
            with self._startup_profiler_step('theme_init'), self._startup_progress_step('theme_init', 'Theme system'):
                self.init_theme_system(apply=False)
            self.dashboard_chart_rows = []
            self.dashboard_chart_ma200 = None
            self.dashboard_chart_view_guard = False
            self._apply_main_portfolio_runtime()
            self._apply_active_portfolio_editor_state()
            with self._startup_profiler_step('ui_build'), self._startup_progress_step('ui_build', 'UI layout'):
                self.init_ui()
            with self._startup_profiler_step('theme_apply'), self._startup_progress_step('theme_apply', 'Theme styling'):
                self.theme_manager.apply_theme(self.current_theme_id, persist=False)
            self._sync_after_portfolio_change(refresh_main=False)
            self._apply_startup_window_size()

    def _on_invoke_main(self, fn: Any) -> None:
        """Handle invoke main."""
        fn()

    def _apply_startup_window_size(self) -> None:
        """Apply one stable startup size after the initial UI has its final size hints."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        available = screen.availableGeometry()
        width = min(1280, max(640, available.width() - 80))
        height = min(800, max(480, available.height() - 100))
        minimum_hint = self.minimumSizeHint()
        width = max(width, minimum_hint.width())
        height = min(height, max(360, available.height() - 40))
        self.resize(width, height)

    def _start_clock_timer(self) -> None:
        """Handle start clock timer."""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
