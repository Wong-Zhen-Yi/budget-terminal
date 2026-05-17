from __future__ import annotations
from typing import Any
from ..compat import *

class WindowLifecycleMixin:
    _STARTUP_REFRESH_DELAY_MS = 2400
    _STARTUP_DASHBOARD_DATA_TIMEOUT_MS = 15000
    _STARTUP_SECTORS_PREFETCH_DELAY_MS = 4500
    _STARTUP_HEATMAP_PREFETCH_DELAY_MS = 5500
    _STARTUP_PRE_MARKET_TIMER_DELAY_MS = 6500
    _STARTUP_SESSION_RESTORE_INITIAL_DELAY_MS = 7000
    _STARTUP_SESSION_RESTORE_STEP_MS = 250
    _STARTUP_CACHE_WARMUP_INITIAL_DELAY_MS = 1200
    _STARTUP_CACHE_WARMUP_STEP_MS = 1400

    def _get_tzinfo(self, idx: Any) -> Any:
        """Resolve a UI timezone selection into a tzinfo object."""
        if idx is None or idx < 0 or idx >= len(self._tz_choices):
            idx = 0
        _, zone_name = self._tz_choices[idx]
        if zone_name is None:
            return datetime.datetime.now().astimezone().tzinfo
        return ZoneInfo(zone_name)

    def _now_for_timezone_index(self, idx: Any) -> Any:
        """Return a timezone-aware current datetime for the selected zone."""
        tzinfo = self._get_tzinfo(idx)
        return datetime.datetime.now(tzinfo) if tzinfo else datetime.datetime.now().astimezone()

    def _register_navigation_pages(self) -> None:
        """Handle register navigation pages."""
        self._startup_progress_begin('navigation', 'Navigation')
        self._pages.clear()
        self._register_page(0, self.btn_page1)
        self._register_page(1, self.btn_page4, on_show=self._p4_on_show if hasattr(self, '_p4_on_show') else None)
        self._register_page(2, self.btn_page6, on_show=self._p6_on_show if hasattr(self, '_p6_on_show') else None)
        self._register_page(3, self.btn_page7)
        self._register_page(4, self.btn_page3, on_show=lambda: self.p3_crawler_timer.start(40) if hasattr(self, 'p3_crawler_timer') else None, on_hide=lambda: self.p3_crawler_timer.stop() if hasattr(self, 'p3_crawler_timer') else None)
        self._register_page(5, self.btn_page8, on_show=self._p8_on_show)
        self._register_page(6, self.btn_page17, on_show=self._p17_on_show)
        self._register_page(7, self.btn_page12, on_show=self._stocks_on_show)
        self._register_page(8, self.btn_page2, on_show=lambda: self._p2_relayout_charts() if hasattr(self, '_p2_relayout_charts') else None)
        self._register_page(9, self.btn_page10, on_show=self._p10_on_show)
        self._register_page(11, self.btn_page5)
        self._register_page(12, self.btn_page13)
        self._register_page(13, self.btn_page14, on_show=self._p14_on_show)
        self._register_page(14, self.btn_page15, on_show=self._p15_on_show)
        self._register_page(15, self.btn_page16, on_show=self._p16_on_show)
        self._register_page(17, self.btn_page18)
        self._register_page(16, self.btn_page9)
        self._refresh_main_tab_picker_items()
        self._startup_progress_complete('navigation', 'Navigation')

    def _is_current_page(self, page: Any) -> bool:
        """Return whether the provided stacked page is currently visible."""
        return hasattr(self, 'stacked_widget') and page is not None and self.stacked_widget.currentWidget() is page

    def resizeEvent(self, event: Any) -> None:
        """Handle resizeEvent."""
        super().resizeEvent(event)
        if hasattr(self, '_dashboard_fit_portfolio_table_height'):
            if not hasattr(self, 'stacked_widget') or self._is_current_page(getattr(self, 'page1', None)):
                self._dashboard_fit_portfolio_table_height()
        if hasattr(self, '_p4_apply_portfolio_table_widths') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page4', None)):
                self._p4_apply_portfolio_table_widths()
        if hasattr(self, '_p2_relayout_charts') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page2', None)):
                self._p2_relayout_charts()
        if hasattr(self, '_p8_relayout_cards') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page8', None)):
                self._p8_relayout_cards()
        if hasattr(self, '_p7_apply_detail_table_widths') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page7', None)):
                self._p7_apply_detail_table_widths()
    def _register_page(self, index: Any, btn: Any, on_show: Any=None, on_hide: Any=None) -> None:
        """Register a page in the nav system. Wires the button and stores lifecycle callbacks."""
        self._pages[index] = {'btn': btn, 'on_show': on_show, 'on_hide': on_hide}
        btn.clicked.connect(partial(self.switch_page, index))

    def _prepare_startup_before_show(self) -> None:
        """Run startup-blocking work while the main window remains hidden."""
        if getattr(self, '_startup_hidden_preparation_started', False):
            return
        self._startup_hidden_preparation_started = True
        self._startup_profiler_stamp('hidden_startup_start')
        self._startup_profiler_stamp('startup_refresh_start')
        logger.info('Startup refresh started before first show: %s page.', self._page_label(0))
        self._startup_metrics_set_stage(
            'dashboard_data',
            status='running',
            detail='Loading first dashboard data before showing the main window.',
        )
        self.refresh_data(force=True)
        self._startup_dashboard_timeout_pending = True
        QTimer.singleShot(self._STARTUP_DASHBOARD_DATA_TIMEOUT_MS, self._on_startup_dashboard_timeout)
        self._startup_progress_finish_if_complete()

    def _on_startup_dashboard_timeout(self) -> None:
        """Release first UI if startup dashboard data is still loading."""
        self._startup_dashboard_timeout_pending = False
        if getattr(self, '_startup_dashboard_data_actual_done', False):
            return
        if getattr(self, '_startup_show_completed', False):
            return
        self._startup_dashboard_data_timed_out = True
        self._startup_metrics_set_stage(
            'dashboard_data',
            status='running',
            detail='Dashboard data is still loading; first UI released after startup timeout.',
        )
        logger.warning(
            'Startup dashboard data still loading after %.1fs; showing main window while refresh continues.',
            self._STARTUP_DASHBOARD_DATA_TIMEOUT_MS / 1000.0,
        )
        if hasattr(self, 'dashboard_status_label'):
            self._dashboard_set_status('Dashboard data is still loading; window opened after startup timeout.', 'warning')
        self._complete_startup_dashboard_data('Dashboard Data delayed', actual=False)

    def showEvent(self, event: Any) -> None:
        """Start deferred startup work only after the window has been shown once."""
        super().showEvent(event)
        if getattr(self, '_startup_show_completed', False):
            return
        self._startup_show_completed = True
        self._startup_profiler_stamp('window_shown')
        profiler = getattr(self, '_startup_profiler', None)
        window_shown_seconds = profiler.latest('window_shown') if profiler is not None and hasattr(profiler, 'latest') else None
        self._startup_metrics_set_stage(
            'first_ui',
            status='complete',
            detail=(
                'Main window shown after dashboard startup timeout; data refresh still running.'
                if getattr(self, '_startup_dashboard_data_timed_out', False)
                else 'Main window shown.'
            ),
            completed_seconds=window_shown_seconds,
            duration_seconds=window_shown_seconds,
        )
        self._startup_progress_complete('first_show', 'First usable view')
        if profiler is not None:
            profiler.log_summary()
        if not getattr(self, '_startup_ready_before_show', False):
            self._schedule_startup_refresh()
        self._start_lazy_warmup()
        self._schedule_startup_page_prefetches()
        self._schedule_startup_session_restores()

    def _schedule_startup_refresh(self) -> None:
        """Queue the first dashboard refresh after the first paint has settled."""
        if getattr(self, '_startup_refresh_pending', False):
            return
        self._startup_refresh_pending = True
        QTimer.singleShot(self._STARTUP_REFRESH_DELAY_MS, self._run_startup_refresh)

    def _run_startup_refresh(self) -> None:
        """Run the deferred startup refresh once the window is visible."""
        self._startup_refresh_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        self._startup_profiler_stamp('startup_refresh_start')
        logger.info('Startup refresh started: %s page.', self._page_label(0))
        self.refresh_data(force=True)

    def _schedule_startup_page_prefetches(self) -> None:
        """Queue post-show page data work in separate waves."""
        if getattr(self, '_startup_page_prefetch_pending', False):
            return
        self._startup_page_prefetch_pending = True
        QTimer.singleShot(self._STARTUP_SECTORS_PREFETCH_DELAY_MS, self._run_startup_sectors_prefetch)
        QTimer.singleShot(self._STARTUP_HEATMAP_PREFETCH_DELAY_MS, self._run_startup_heatmap_prefetch)
        QTimer.singleShot(self._STARTUP_PRE_MARKET_TIMER_DELAY_MS, self._run_startup_pre_market_timer)

    def _startup_work_can_run(self) -> bool:
        """Return whether deferred startup work should still run."""
        return bool(getattr(self, '_startup_show_completed', False) and self.isVisible())

    def _run_startup_sectors_prefetch(self) -> None:
        """Build and refresh the Sectors page after the first startup wave."""
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        logger.info('Startup prefetch loading %s page.', self._page_label(5))
        self._ensure_page_initialized(5)
        logger.info('Startup prefetch requesting data for %s page.', self._page_label(5))
        self._call_if_page_initialized(
            '_p8_request_refresh',
            page_attr='page8',
            status_text='Loading sector data...',
        )

    def _run_startup_heatmap_prefetch(self) -> None:
        """Build and refresh the Heatmap page after Sectors has started."""
        if not self._startup_work_can_run():
            return
        logger.info('Startup prefetch loading %s page.', self._page_label(6))
        self._ensure_page_initialized(6)
        logger.info('Startup prefetch requesting data for %s page.', self._page_label(6))
        self._call_if_page_initialized(
            '_p17_request_refresh',
            page_attr='page17',
        )

    def _run_startup_pre_market_timer(self) -> None:
        """Start the Pre-Market auto refresh timer after early startup has settled."""
        self._startup_page_prefetch_pending = False
        if not self._startup_work_can_run():
            return
        if hasattr(self, '_p14_start_auto_refresh'):
            logger.info('Startup prefetch starting Pre-Market auto refresh timer.')
            self._p14_start_auto_refresh()
        logger.info('Startup page prefetch waves complete.')
        self._schedule_startup_cache_warmup()

    def _schedule_startup_cache_warmup(self) -> None:
        """Queue balanced cache warmup after the dashboard has loaded."""
        if getattr(self, '_startup_cache_warmup_pending', False) or getattr(self, '_startup_cache_warmup_started', False):
            return
        if not self._startup_work_can_run():
            return
        if (not getattr(self, '_startup_dashboard_data_done', False)) or getattr(self, '_startup_page_prefetch_pending', False):
            self._startup_cache_warmup_pending = True
            QTimer.singleShot(1000, self._retry_startup_cache_warmup)
            return
        self._startup_cache_warmup_queue = self._startup_cache_warmup_specs()
        if not self._startup_cache_warmup_queue:
            self._startup_metrics_set_stage(
                'cache_warmup',
                status='skipped',
                detail='No cache warmup tasks were available.',
                count=0,
                duration_seconds=0.0,
            )
            return
        self._startup_cache_warmup_total = len(self._startup_cache_warmup_queue)
        self._startup_cache_warmup_failed = False
        self._startup_cache_warmup_started = True
        self._startup_cache_warmup_pending = True
        self._startup_metrics_set_stage(
            'cache_warmup',
            status='running',
            detail='Startup cache warmup queued.',
            count=self._startup_cache_warmup_total,
        )
        logger.info(
            'Startup cache warmup queued for %s task(s): %s.',
            len(self._startup_cache_warmup_queue),
            ', '.join(item.get('label', 'warmup') for item in self._startup_cache_warmup_queue),
        )
        QTimer.singleShot(self._STARTUP_CACHE_WARMUP_INITIAL_DELAY_MS, self._run_startup_cache_warmup_step)

    def _retry_startup_cache_warmup(self) -> None:
        """Retry cache warmup scheduling after the dashboard finishes."""
        self._startup_cache_warmup_pending = False
        self._schedule_startup_cache_warmup()

    def _startup_cache_warmup_specs(self) -> list[dict[str, Any]]:
        """Return balanced staged cache warmup work."""
        return [
            {'label': 'chart cache', 'method': '_warm_startup_chart_cache'},
            {'label': 'options expiries', 'method': '_warm_startup_options_expiries'},
            {'label': 'portfolio metrics', 'method': '_warm_startup_portfolio_metrics'},
            {'label': 'sector data', 'method': '_warm_startup_sector_data'},
            {'label': 'ETF heatmap', 'method': '_warm_startup_etf_heatmap'},
            {'label': 'ETF holdings', 'method': '_warm_startup_etf_holdings'},
        ]

    def _run_startup_cache_warmup_step(self) -> None:
        """Run one background warmup task and schedule the next wave."""
        self._startup_cache_warmup_pending = False
        if not self._startup_work_can_run():
            return
        queue = list(getattr(self, '_startup_cache_warmup_queue', []) or [])
        if not queue:
            logger.info('Startup cache warmup complete.')
            self._startup_metrics_set_stage(
                'cache_warmup',
                status='complete',
                detail='Startup cache warmup complete.',
                count=getattr(self, '_startup_cache_warmup_total', 0),
            )
            return
        current = queue.pop(0)
        self._startup_cache_warmup_queue = queue
        label = str(current.get('label') or 'warmup')
        method = getattr(self, str(current.get('method') or ''), None)
        if callable(method):
            try:
                logger.info('Startup cache warmup running: %s.', label)
                method()
            except Exception as exc:
                logger.exception('Startup cache warmup failed for %s.', label)
                self._startup_cache_warmup_failed = True
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception(f'Warmup: {label}', exc, severity='warning')
        if self._startup_cache_warmup_queue:
            self._startup_cache_warmup_pending = True
            QTimer.singleShot(self._STARTUP_CACHE_WARMUP_STEP_MS, self._run_startup_cache_warmup_step)
        else:
            logger.info('Startup cache warmup complete.')
            failed = bool(getattr(self, '_startup_cache_warmup_failed', False))
            self._startup_metrics_set_stage(
                'cache_warmup',
                status='failed' if failed else 'complete',
                detail='Startup cache warmup finished with errors.' if failed else 'Startup cache warmup complete.',
                count=getattr(self, '_startup_cache_warmup_total', 0),
            )

    def _startup_warmup_symbols(self, *, limit: int = 12) -> list[str]:
        """Return a bounded ticker universe for background warmup."""
        symbols = []
        candidates = [
            getattr(self, 'dashboard_symbol', ''),
            getattr(self, 'p10_symbol', ''),
        ]
        candidates.extend(list(getattr(self, 'chart_slots', []) or []))
        if hasattr(self, '_get_fetch_tickers'):
            candidates.extend(list(self._get_fetch_tickers() or []))
        for value in candidates:
            symbol = str(value or '').upper().strip()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= int(limit):
                break
        return symbols

    def _warm_startup_chart_cache(self) -> None:
        """Warm common chart frames without changing visible chart state."""
        symbols = self._startup_warmup_symbols(limit=8)
        if not symbols:
            return

        def _run() -> None:
            try:
                from budget_terminal_app.services.chart_data import ChartDataService

                service = ChartDataService(self._get_cache_manager())
                for symbol in symbols:
                    payload = service.fetch_base_frame_payload(symbol, period='1mo', interval='1d')
                    if hasattr(self, '_record_data_health_payload'):
                        self._record_data_health_payload('Warmup chart cache', payload, symbols=[symbol])
                logger.info('Startup chart cache warmup finished for %s symbol(s).', len(symbols))
            except Exception as exc:
                logger.warning('Startup chart cache warmup failed: %s', exc)
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception('Warmup chart cache', exc, symbols=symbols, severity='warning')

        threading.Thread(target=_run, daemon=True).start()

    def _warm_startup_options_expiries(self) -> None:
        """Warm option expiry caches for saved portfolio/options symbols."""
        symbols = []
        symbols.extend(self._startup_warmup_symbols(limit=12))
        for pos in list(getattr(self, 'options_data', []) or []):
            ticker = str((pos or {}).get('ticker', '') if isinstance(pos, dict) else '').upper().strip()
            if ticker and ticker not in symbols:
                symbols.append(ticker)
        symbols = symbols[:16]
        if not symbols:
            return

        def _run() -> None:
            try:
                service = self._get_options_data_service()
                for symbol in symbols:
                    payload = service.fetch_expiries_payload(symbol)
                    if hasattr(self, '_record_data_health_payload'):
                        self._record_data_health_payload('Warmup options expiries', payload, symbols=[symbol])
                logger.info('Startup options expiry warmup finished for %s symbol(s).', len(symbols))
            except Exception as exc:
                logger.warning('Startup options expiry warmup failed: %s', exc)
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception('Warmup options expiries', exc, symbols=symbols, severity='warning')

        threading.Thread(target=_run, daemon=True).start()

    def _warm_startup_portfolio_metrics(self) -> None:
        """Warm active portfolio analytics cache."""
        if not self._startup_work_can_run():
            return
        self._ensure_page_initialized(1)
        if hasattr(self, '_fetch_portfolio_analytics'):
            self._fetch_portfolio_analytics(force=False)

    def _warm_startup_sector_data(self) -> None:
        """Warm sector page data using existing throttles."""
        if not self._startup_work_can_run():
            return
        self._ensure_page_initialized(5)
        self._call_if_page_initialized(
            '_p8_request_refresh',
            page_attr='page8',
            status_text='Warming sector data...',
        )

    def _warm_startup_etf_heatmap(self) -> None:
        """Warm ETF heatmap data using existing throttles."""
        if not self._startup_work_can_run():
            return
        self._ensure_page_initialized(6)
        self._call_if_page_initialized('_p17_request_refresh', page_attr='page17')

    def _warm_startup_etf_holdings(self) -> None:
        """Warm last-session ETF holdings without changing visible inputs."""
        snapshot = self._get_tab_session_snapshot('etf') if hasattr(self, '_get_tab_session_snapshot') else None
        ticker = ''
        if isinstance(snapshot, dict):
            ticker = str(snapshot.get('input_ticker') or snapshot.get('ticker') or '').upper().strip()
        if not ticker:
            return

        def _run() -> None:
            try:
                from budget_terminal_app.etf_holdings import EtfHoldingsService

                result = EtfHoldingsService().load(ticker)
                logger.info('Startup ETF holdings warmup finished for %s.', ticker)
            except Exception as exc:
                logger.warning('Startup ETF holdings warmup failed for %s: %s', ticker, exc)
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception('Warmup ETF holdings', exc, symbols=[ticker], severity='warning')

        threading.Thread(target=_run, daemon=True).start()

    def _startup_session_restore_specs(self) -> list[dict[str, Any]]:
        """Return the tab-session restore tasks that should run after first paint."""
        specs = [
            {'tab_key': 'stocks', 'page_index': 7, 'restore_method': '_stocks_restore_startup_session'},
            {'tab_key': 'roll', 'page_index': 17, 'restore_method': '_p18_restore_startup_session'},
            {'tab_key': 'fundamentals', 'page_index': 8, 'restore_method': '_p2_restore_startup_session'},
            {'tab_key': 'options', 'page_index': 11, 'restore_method': '_p5_restore_startup_session'},
            {'tab_key': 'etf', 'page_index': 12, 'restore_method': '_p13_restore_startup_session'},
            {'tab_key': 'politics', 'page_index': 14, 'restore_method': '_p15_restore_startup_session', 'allow_empty_snapshot': True},
            {'tab_key': 'youtube', 'page_index': 15, 'restore_method': '_p16_restore_startup_session'},
        ]
        queue = []
        for spec in specs:
            snapshot = self._get_tab_session_snapshot(spec['tab_key']) if hasattr(self, '_get_tab_session_snapshot') else None
            if snapshot or spec.get('allow_empty_snapshot'):
                queue.append({**spec, 'snapshot': snapshot})
        return queue

    def _schedule_startup_session_restores(self) -> None:
        """Queue hidden last-session tab restores after early startup work has settled."""
        if getattr(self, '_startup_session_restore_pending', False):
            return
        queue = self._startup_session_restore_specs()
        self._startup_session_restore_queue = list(queue)
        if not queue:
            self._startup_metrics_set_stage(
                'session_restore',
                status='skipped',
                detail='No cached tabs to restore.',
                count=0,
                duration_seconds=0.0,
            )
            return
        self._startup_session_restore_total = len(queue)
        self._startup_session_restore_failed = False
        self._startup_metrics_set_stage(
            'session_restore',
            status='running',
            detail='Restoring cached tabs.',
            count=self._startup_session_restore_total,
        )
        logger.info('Startup session restore queued for %s page(s): %s.', len(queue), ', '.join(self._page_label(item.get('page_index')) for item in queue))
        self._startup_session_restore_pending = True
        QTimer.singleShot(self._STARTUP_SESSION_RESTORE_INITIAL_DELAY_MS, self._run_startup_session_restore_step)

    def _run_startup_session_restore_step(self) -> None:
        """Build, restore, and silently refresh one cached tab at a time."""
        self._startup_session_restore_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        queue = list(getattr(self, '_startup_session_restore_queue', []))
        if not queue:
            self._startup_metrics_set_stage(
                'session_restore',
                status='complete',
                detail='Startup session restore complete.',
                count=getattr(self, '_startup_session_restore_total', 0),
            )
            return
        current = queue.pop(0)
        self._startup_session_restore_queue = queue
        page_index = current.get('page_index')
        page_label = self._page_label(page_index)
        logger.info('Startup session restore started: %s page (tab=%s).', page_label, current.get('tab_key'))
        try:
            self._ensure_page_initialized(page_index)
            restore_fn = getattr(self, str(current.get('restore_method', '') or ''), None)
            if callable(restore_fn):
                restore_fn(current.get('snapshot'))
            logger.info('Startup session restore complete: %s page (tab=%s).', page_label, current.get('tab_key'))
        except Exception:
            logger.exception('Startup session restore failed for %s.', current.get('tab_key'))
            self._startup_session_restore_failed = True
        if self._startup_session_restore_queue:
            self._startup_session_restore_pending = True
            QTimer.singleShot(self._STARTUP_SESSION_RESTORE_STEP_MS, self._run_startup_session_restore_step)
        else:
            failed = bool(getattr(self, '_startup_session_restore_failed', False))
            self._startup_metrics_set_stage(
                'session_restore',
                status='failed' if failed else 'complete',
                detail='Startup session restore finished with errors.' if failed else 'Startup session restore complete.',
                count=getattr(self, '_startup_session_restore_total', 0),
            )

    def _start_lazy_warmup(self) -> None:
        """Warm secondary pages one at a time after the window becomes interactive."""
        if getattr(self, '_lazy_warmup_started', False) or getattr(self, '_lazy_warmup_finished', False):
            return
        if not getattr(self, '_startup_show_completed', False):
            return
        self._startup_progress_begin('lazy_warmup', 'Page warmup')
        queue = []
        excluded_pages = {3, 12}
        for button in getattr(self, '_nav_buttons', []):
            page_index = self._page_index_for_button(button)
            if page_index in (None, 0) or self._page_initialized(index=page_index):
                continue
            if int(page_index) in excluded_pages:
                continue
            if page_index not in queue:
                queue.append(page_index)
        for page_index in getattr(self, '_lazy_page_registry', {}).keys():
            if page_index in (None, 0) or self._page_initialized(index=page_index):
                continue
            if int(page_index) in excluded_pages:
                continue
            if page_index not in queue:
                queue.append(page_index)
        priority = {
            1: 10,
            2: 20,
            4: 30,
            5: 40,
            6: 45,
            7: 50,
            8: 60,
            9: 65,
            11: 70,
            12: 80,
            13: 90,
            14: 100,
            15: 110,
            16: 120,
            17: 130,
            3: 150,
        }
        queue.sort(key=lambda value: priority.get(int(value), 999))
        self._lazy_warmup_queue = queue
        timer = getattr(self, '_lazy_page_warmup_timer', None)
        if timer is None or not queue:
            self._lazy_warmup_finished = True
            self._startup_metrics_set_stage(
                'page_warmup',
                status='skipped',
                detail='No lazy pages needed warmup.',
                count=0,
                duration_seconds=0.0,
            )
            self._startup_progress_finish_if_complete()
            return
        self._lazy_warmup_started = True
        self._lazy_warmup_total = len(queue)
        self._lazy_warmup_failed = False
        self._startup_metrics_set_stage(
            'page_warmup',
            status='running',
            detail='Lazy page warmup queued.',
            count=self._lazy_warmup_total,
        )
        logger.info('Lazy page warmup queued for %s page(s): %s.', len(queue), ', '.join(self._page_label(index) for index in queue))
        timer.start(getattr(self, '_LAZY_WARMUP_INITIAL_DELAY_MS', 500))

    def _warm_next_page(self) -> None:
        """Initialize one pending lazy page and reschedule the next warmup step."""
        while getattr(self, '_lazy_warmup_queue', []):
            page_index = self._lazy_warmup_queue.pop(0)
            if self._page_initialized(index=page_index):
                continue
            try:
                logger.info('Lazy page warmup loading %s page (index %s).', self._page_label(page_index), page_index)
                with self._startup_profiler_step(f'lazy_page_{int(page_index)}'):
                    self._build_page_now(page_index, reason='lazy warmup')
            except Exception:
                logger.exception('Lazy page warmup failed for page index %s.', page_index)
                self._lazy_warmup_failed = True
                self._startup_progress_complete_page(page_index, self._page_label(page_index))
            break
        timer = getattr(self, '_lazy_page_warmup_timer', None)
        if timer is not None and getattr(self, '_lazy_warmup_queue', []):
            timer.start(getattr(self, '_LAZY_WARMUP_STEP_MS', 75))
        else:
            self._lazy_warmup_finished = True
            failed = bool(getattr(self, '_lazy_warmup_failed', False))
            self._startup_metrics_set_stage(
                'page_warmup',
                status='failed' if failed else 'complete',
                detail='Lazy page warmup finished with errors.' if failed else 'Lazy page warmup complete.',
                count=getattr(self, '_lazy_warmup_total', 0),
            )
            self._startup_progress_finish_if_complete()

    def _ensure_page_initialized(self, index: Any) -> None:
        """Synchronously build a lazy page before it becomes visible."""
        if self._page_initialized(index=index):
            return
        logger.info('Page initialization required before show: %s (index %s).', self._page_label(index), index)
        self._build_page_now(index, reason='before show')

    def switch_page(self, index: Any, *_: Any) -> None:
        """Switch page."""
        try:
            numeric_index = int(index)
        except (TypeError, ValueError):
            return
        previous_index = int(self.stacked_widget.currentIndex()) if hasattr(self, 'stacked_widget') else 0
        previous_label = self._page_label(previous_index)
        target_label = self._page_label(numeric_index)
        logger.info('Page navigation requested: %s (index %s) -> %s (index %s).', previous_label, previous_index, target_label, numeric_index)
        self._ensure_page_initialized(numeric_index)
        self.stacked_widget.setCurrentIndex(numeric_index)
        for i, page in self._pages.items():
            page['btn'].setChecked(i == numeric_index)
            cb = page['on_show'] if i == numeric_index else page['on_hide']
            if cb:
                cb()
        logger.info('Page shown: %s (index %s).', target_label, numeric_index)

    def _refresh_main_tab_picker_items(self) -> None:
        """Sync the top-bar tab picker with the registered main navigation pages."""
        if not hasattr(self, '_tab_picker_list'):
            return
        items = []
        item_map = {}
        for button in getattr(self, '_nav_buttons', []):
            page_index = self._page_index_for_button(button)
            if page_index is None:
                continue
            label = button.text().strip()
            if not label:
                continue
            items.append(label)
            item_map[label.casefold()] = page_index
        self._tab_picker_items = items
        self._tab_picker_map = item_map
        self._filter_tab_picker_items(getattr(self, '_tab_picker_input', None).text() if hasattr(self, '_tab_picker_input') else '')

    def _page_index_for_button(self, button: Any) -> Any:
        """Return the registered page index for a nav button."""
        for index, page in self._pages.items():
            if page.get('btn') is button:
                return index
        return None

    def _find_main_tab_match(self, text: Any) -> Any:
        """Resolve user-entered tab text into a main page index."""
        query = str(text or '').strip()
        if not query:
            return None
        lowered = query.casefold()
        exact = self._tab_picker_map.get(lowered)
        if exact is not None:
            return exact
        for label in self._tab_picker_items:
            if lowered in label.casefold():
                return self._tab_picker_map.get(label.casefold())
        return None

    def _filter_tab_picker_items(self, text: Any) -> None:
        """Filter popup picker rows from the current query text."""
        if not hasattr(self, '_tab_picker_list'):
            return
        query = str(text or '').strip().casefold()
        self._tab_picker_list.clear()
        for label in self._tab_picker_items:
            if not query or query in label.casefold():
                self._tab_picker_list.addItem(label)
        if self._tab_picker_list.count() > 0:
            self._tab_picker_list.setCurrentRow(0)

    def _activate_tab_picker_item(self, item: Any) -> None:
        """Open a page from a popup list selection."""
        label = item.text() if hasattr(item, 'text') else str(item or '')
        page_index = self._find_main_tab_match(label)
        if page_index is None:
            return
        logger.info('Tab picker activated: %s -> %s page.', self._safe_log_text(label), self._page_label(page_index))
        self.switch_page(page_index)
        self._hide_tab_picker()

    def _show_tab_picker(self) -> None:
        """Reveal the top-bar picker and focus it for typed navigation."""
        if not hasattr(self, '_tab_picker_popup'):
            return
        self._refresh_main_tab_picker_items()
        popup_margin = 16
        popup_x = max(self.width() - self._tab_picker_popup.width() - popup_margin, popup_margin)
        popup_pos = self.mapToGlobal(QPoint(popup_x, 52))
        self._tab_picker_popup.move(popup_pos)
        self._tab_picker_input.clear()
        self._filter_tab_picker_items('')
        self._tab_picker_popup.show()
        self._tab_picker_popup.raise_()
        self._tab_picker_popup.activateWindow()
        self._tab_picker_input.setFocus()

    def _current_main_nav_button(self) -> Any:
        """Return the navigation button for the active main page."""
        if not hasattr(self, 'stacked_widget'):
            return None
        return self._pages.get(self.stacked_widget.currentIndex(), {}).get('btn')

    def _hide_tab_picker(self) -> None:
        """Collapse the top-bar picker after selection or cancellation."""
        if not hasattr(self, '_tab_picker_popup'):
            return
        self._tab_picker_popup.hide()
        self._tab_picker_input.clear()
        self._tab_picker_list.clearSelection()
        current_button = self._current_main_nav_button()
        if current_button is not None:
            current_button.setFocus()

    def _is_plain_escape_key(self, event: Any) -> bool:
        """Return whether the event is an unmodified Escape keypress."""
        return (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        )

    def _is_plain_backtick_key(self, event: Any) -> bool:
        """Return whether the event is an unmodified backtick keypress."""
        if event.type() != QEvent.Type.KeyPress or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if str(event.text() or '') == '`':
            return True
        quote_left = getattr(Qt.Key, 'Key_QuoteLeft', None)
        return quote_left is not None and event.key() == quote_left

    def _resolve_main_window_text_input(self, widget: Any) -> Any:
        """Resolve a focused child widget back to an editable main-window text input."""
        current = widget
        while current is not None:
            if not isinstance(current, QWidget):
                return None
            if isinstance(current, QAbstractSpinBox):
                if current.window() is not self:
                    return None
                if hasattr(current, 'isReadOnly') and current.isReadOnly():
                    return None
                return current
            if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit)):
                if isinstance(current, QLineEdit):
                    ancestor = current.parentWidget()
                    while ancestor is not None and ancestor is not self and ancestor is not getattr(self, '_tab_picker_popup', None):
                        if isinstance(ancestor, QAbstractSpinBox):
                            if ancestor.window() is not self:
                                return None
                            if hasattr(ancestor, 'isReadOnly') and ancestor.isReadOnly():
                                return None
                            return ancestor
                        ancestor = ancestor.parentWidget()
                if current.window() is not self:
                    return None
                if hasattr(current, 'isReadOnly') and current.isReadOnly():
                    return None
                return current
            if current is self or current is getattr(self, '_tab_picker_popup', None):
                return None
            current = current.parentWidget()
        return None

    def _dismiss_main_window_text_input(self, widget: Any=None, *, focus_current_button: bool=True) -> bool:
        """Exit the active main-window text input and restore non-editing focus."""
        target_widget = widget if isinstance(widget, QWidget) else QApplication.focusWidget()
        target = self._resolve_main_window_text_input(target_widget)
        if target is None:
            return False
        target.clearFocus()
        if focus_current_button:
            current_button = self._current_main_nav_button()
            if current_button is not None:
                current_button.setFocus()
        return True

    def _handle_global_input_exit_event(self, obj: Any, event: Any) -> bool:
        """Handle app-wide Escape/backtick behavior for text entry widgets."""
        if hasattr(self, '_tab_picker_popup') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event) or self._is_plain_backtick_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            return False
        if self._is_plain_escape_key(event) and self._dismiss_main_window_text_input(obj):
            event.accept()
            return True
        if self._is_plain_backtick_key(event) and self._dismiss_main_window_text_input(obj, focus_current_button=False):
            self._show_tab_picker()
            event.accept()
            return True
        return False

    def _should_handle_main_tab_navigation_keys(self) -> bool:
        """Limit global navigation shortcuts to non-editing contexts."""
        if hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible():
            return False
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return True
        blocked_types = (QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget, QTabWidget)
        widget = focus_widget
        while widget is not None:
            if isinstance(widget, blocked_types):
                return False
            widget = widget.parentWidget()
        return True

    def _step_main_tab(self, direction: int) -> bool:
        """Move between registered main tabs with wraparound."""
        buttons = list(getattr(self, '_nav_buttons', []))
        if not buttons:
            return False
        current_index = self.stacked_widget.currentIndex()
        current_pos = None
        for pos, button in enumerate(buttons):
            page_index = self._page_index_for_button(button)
            if page_index == current_index:
                current_pos = pos
                break
        if current_pos is None:
            fallback_index = self._page_index_for_button(buttons[0])
            if fallback_index is None:
                return False
            self.switch_page(fallback_index)
            return True
        next_pos = (current_pos + direction) % len(buttons)
        next_index = self._page_index_for_button(buttons[next_pos])
        if next_index is None:
            return False
        self.switch_page(next_index)
        return True

    def _handle_main_tab_arrow_shortcut(self, direction: int) -> None:
        """Move between main tabs from a global shortcut when safe to do so."""
        if self._should_handle_main_tab_navigation_keys():
            self._step_main_tab(direction)

    def _should_handle_ctrl_tab_navigation(self) -> bool:
        """Allow Ctrl+Tab unless the popup tab picker is currently active."""
        return not (hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible())

    def _handle_ctrl_tab_shortcut(self) -> None:
        """Cycle forward through main tabs from the global Ctrl+Tab shortcut."""
        if self._should_handle_ctrl_tab_navigation():
            self._step_main_tab(1)

    def _refresh_current_page(self) -> None:
        """Run the most appropriate refresh action for the currently visible page."""
        if not hasattr(self, 'stacked_widget'):
            return
        current_index = int(self.stacked_widget.currentIndex())
        logger.info('Manual refresh requested: %s page (index %s).', self._page_label(current_index), current_index)
        if current_index in (0, 4):
            if hasattr(self, 'refresh_data'):
                self.refresh_data(force=True, reason='manual_refresh')
            return
        if current_index == 1:
            current_widget = self.p4_content_tabs.currentWidget() if hasattr(self, 'p4_content_tabs') else None
            if current_widget is getattr(self, 'p4_metrics_page', None):
                if hasattr(self, '_p4_invalidate_portfolio_analytics_cache'):
                    self._p4_invalidate_portfolio_analytics_cache(self.active_portfolio_id)
                if hasattr(self, '_p4_refresh_portfolio_metrics_view'):
                    self._p4_refresh_portfolio_metrics_view(force=True)
                return
            if current_widget is getattr(self, 'p4_momentum_page', None):
                if hasattr(self, '_p4_invalidate_momentum_cache'):
                    self._p4_invalidate_momentum_cache(self.active_portfolio_id)
                if hasattr(self, '_p4_refresh_active_momentum_view'):
                    self._p4_refresh_active_momentum_view()
                return
            if hasattr(self, 'refresh_data'):
                self.refresh_data(force=True, reason='manual_refresh')
            return
        if current_index == 2:
            if hasattr(self, '_p6_populate_tables'):
                self._p6_populate_tables()
            if hasattr(self, '_p6_replay_progress_animation'):
                self._p6_replay_progress_animation()
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'Personal finance view refreshed.', status='positive')
            return
        if current_index == 3:
            if hasattr(self, '_p7_fetch_events'):
                self._p7_fetch_events()
            return
        if current_index == 5:
            if hasattr(self, '_p8_request_refresh'):
                self._p8_request_refresh(force=True, status_text='Refreshing sector data...')
            return
        if current_index == 6:
            if hasattr(self, '_p17_request_refresh'):
                self._p17_request_refresh(force=True)
            return
        if current_index == 7:
            if hasattr(self, '_stocks_load_from_input'):
                self._stocks_load_from_input(include_global_status=True, update_collection_info=True)
            return
        if current_index == 8:
            if hasattr(self, 'analyze_stock_p2'):
                self.analyze_stock_p2(update_collection_info=True)
            return
        if current_index == 9:
            active_key = self._p10_active_subtab_key() if hasattr(self, '_p10_active_subtab_key') else 'chart'
            if active_key == 'compare':
                if hasattr(self, '_p10_refresh_compare_view'):
                    self._p10_refresh_compare_view(force=True)
                return
            if active_key == 'multiintervals':
                if hasattr(self, '_p10_refresh_multi_interval_views'):
                    self._p10_refresh_multi_interval_views(force=True)
                return
            if active_key == 'multicharts':
                if hasattr(self, '_mc_refresh_all'):
                    self._mc_refresh_all()
                return
            if hasattr(self, '_p10_refresh_chart'):
                self._p10_refresh_chart(force_refresh=True)
            return
        if current_index == 11:
            if hasattr(self, '_p5_load_active_subtab'):
                self._p5_load_active_subtab()
            return
        if current_index == 12:
            if hasattr(self, '_p13_load_etf'):
                self._p13_load_etf(update_collection_info=True)
            return
        if current_index == 13:
            if hasattr(self, '_p14_refresh'):
                self._p14_refresh(force=True)
            return
        if current_index == 14:
            if hasattr(self, '_p15_refresh'):
                self._p15_refresh(force=True)
            return
        if current_index == 15:
            if hasattr(self, '_p16_refresh'):
                self._p16_refresh(force=False, auto_trigger=False)
            return
        if current_index == 16:
            if hasattr(self, '_refresh_run_on_startup_controls'):
                self._refresh_run_on_startup_controls()
            if hasattr(self, '_refresh_settings_log_controls'):
                self._refresh_settings_log_controls()
            if hasattr(self, '_refresh_startup_performance_views'):
                self._refresh_startup_performance_views()
            if hasattr(self, '_set_settings_status'):
                self._set_settings_status('Settings panel refreshed.', 'positive')
            return
        if current_index == 17:
            if hasattr(self, '_p18_roll_stock'):
                self._p18_roll_stock(include_global_status=True)

    def _handle_tab_picker_shortcut(self) -> None:
        """Open or close the popup tab picker from the global shortcut."""
        if hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible():
            self._hide_tab_picker()
            return
        if self._should_handle_main_tab_navigation_keys():
            self._show_tab_picker()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Handle picker-specific keyboard and focus behavior before other filters."""
        if hasattr(self, '_tab_picker_popup') and hasattr(self, '_tab_picker_list') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event) or self._is_plain_backtick_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            if obj is self._tab_picker_input and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Down and self._tab_picker_list.count() > 0:
                    self._tab_picker_list.setFocus()
                    self._tab_picker_list.setCurrentRow(max(self._tab_picker_list.currentRow(), 0))
                    event.accept()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._tab_picker_list.currentItem() is not None:
                    self._activate_tab_picker_item(self._tab_picker_list.currentItem())
                    event.accept()
                    return True
            if obj is self._tab_picker_list and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Up and self._tab_picker_list.currentRow() <= 0:
                    self._tab_picker_input.setFocus()
                    event.accept()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._tab_picker_list.currentItem() is not None:
                    self._activate_tab_picker_item(self._tab_picker_list.currentItem())
                    event.accept()
                    return True
            if obj is self._tab_picker_popup and event.type() == QEvent.Type.Hide:
                self._tab_picker_input.clear()
        return super().eventFilter(obj, event)

    def _toggle_time_format(self) -> None:
        """Handle toggle time format."""
        self._time_12h = not self._time_12h
        if hasattr(self, 'settings_time_format_checkbox'):
            self.settings_time_format_checkbox.blockSignals(True)
            self.settings_time_format_checkbox.setChecked(self._time_12h)
            self.settings_time_format_checkbox.blockSignals(False)
        save_time_format(self._time_12h)
        self.update_time()

    def _current_clock_timezone_index(self) -> int:
        """Return the active timezone index for the shared clock display."""
        try:
            idx = int(getattr(self, '_clock_tz_index', 0))
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(getattr(self, '_tz_choices', ())):
            return 0
        return idx

    def _on_settings_timezone_changed(self, index: int) -> None:
        """Handle timezone changes from the Settings page clock controls."""
        self._clock_tz_index = self._current_clock_timezone_index() if index is None else int(index)
        self.update_time()

    def update_time(self, *_: Any) -> None:
        """Update time."""
        now = self._now_for_timezone_index(self._current_clock_timezone_index())
        if self._time_12h:
            self.time_label.setText(now.strftime('%I:%M:%S %p'))
        else:
            self.time_label.setText(now.strftime('%H:%M:%S'))
        self._refresh_data_collection_label()

    def _set_data_collection_info(self, sources: Any, collected_at: Any=None) -> None:
        """Persist footer metadata about the latest completed data fetch."""
        source_list = []
        if isinstance(sources, str):
            source_list = [sources]
        else:
            try:
                source_list = list(sources or [])
            except Exception:
                source_list = []
        cleaned = []
        for source in source_list:
            text = str(source or '').strip()
            if text and text not in cleaned:
                cleaned.append(text)
        self._data_collection_sources = cleaned
        if collected_at is None:
            now = self._now_for_timezone_index(self._current_clock_timezone_index())
            self._data_collection_ts = now.timestamp()
        else:
            try:
                self._data_collection_ts = float(collected_at)
            except Exception:
                self._data_collection_ts = None
        self._refresh_data_collection_label()
        if hasattr(self, '_refresh_data_health_views'):
            self._refresh_data_health_views()

    def _refresh_data_collection_label(self) -> None:
        """Refresh the footer label that summarizes the latest collected data."""
        if not hasattr(self, 'data_collection_label'):
            return
        if not self._data_collection_ts:
            self.data_collection_label.setText('Data collected: awaiting first refresh')
            return
        try:
            tzinfo = self._get_tzinfo(self._current_clock_timezone_index())
            collected_dt = datetime.datetime.fromtimestamp(float(self._data_collection_ts), tz=tzinfo)
        except Exception:
            self.data_collection_label.setText('Data collected: unavailable')
            return
        sources = ', '.join(self._data_collection_sources) if self._data_collection_sources else 'Unknown source'
        time_fmt = '%b %d, %Y %I:%M:%S %p' if getattr(self, '_time_12h', False) else '%b %d, %Y %H:%M:%S'
        self.data_collection_label.setText(f'Data collected: {sources} | {collected_dt.strftime(time_fmt)}')

    def _on_close_hold_complete(self) -> None:
        """Handle close hold complete."""
        reply = QMessageBox.question(self, 'Close Application', 'Are you sure you want to close Budget Terminal?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.close()

    def closeEvent(self, event: Any) -> None:
        """Closeevent."""
        warmup_timer = getattr(self, '_lazy_page_warmup_timer', None)
        if warmup_timer is not None:
            warmup_timer.stop()
        session_timer = getattr(self, '_session_cache_persist_timer', None)
        if session_timer is not None:
            session_timer.stop()
        pre_market_timer = getattr(self, '_p14_auto_refresh_timer', None)
        if pre_market_timer is not None:
            pre_market_timer.stop()
        p6_fx_timer = getattr(self, '_p6_fx_refresh_timer', None)
        if p6_fx_timer is not None:
            p6_fx_timer.stop()
        p6_goal_timer = getattr(self, '_p6_goal_anim_timer', None)
        if p6_goal_timer is not None:
            p6_goal_timer.stop()
        p6_fx_thread = getattr(self, '_p6_fx_thread', None)
        if p6_fx_thread is not None and p6_fx_thread.isRunning():
            p6_fx_thread.quit()
            p6_fx_thread.wait(3000)
        app = QApplication.instance()
        global_filter = getattr(self, '_global_input_exit_filter', None)
        if app is not None and global_filter is not None and getattr(self, '_app_keyboard_event_filter_installed', False):
            app.removeEventFilter(global_filter)
            self._app_keyboard_event_filter_installed = False
        main_entry = self._get_portfolio_entry(self.main_portfolio_id)
        main_entry['portfolio'] = self.tickers
        main_entry['chart_slots'] = self.chart_slots
        main_entry['portfolio_tracker'] = self.tracker_data
        main_entry['cash_balance'] = getattr(self, 'cash_balance', main_entry.get('cash_balance', 0.0))
        active_entry = self._get_portfolio_entry(self.active_portfolio_id)
        active_entry['portfolio'] = getattr(self, 'active_tickers', active_entry.get('portfolio', []))
        active_entry['portfolio_tracker'] = getattr(self, 'active_tracker_data', active_entry.get('portfolio_tracker', {}))
        active_entry['options_tracker'] = self.options_data
        active_entry['cash_balance'] = getattr(self, 'active_cash_balance', active_entry.get('cash_balance', 0.0))
        self._persist_all_portfolios(immediate=True)
        if hasattr(self, '_dashboard_save_state'):
            self._dashboard_save_state()
        if hasattr(self, '_persist_dashboard_state'):
            self._persist_dashboard_state(immediate=True)
        if self._page_initialized(page_attr='page12') and hasattr(self, '_stocks_save_session_snapshot'):
            self._stocks_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page18') and hasattr(self, '_p18_save_session_snapshot'):
            self._p18_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page2') and hasattr(self, '_p2_save_session_snapshot'):
            self._p2_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page5') and hasattr(self, '_p5_save_session_snapshot'):
            self._p5_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page13') and hasattr(self, '_p13_save_session_snapshot'):
            self._p13_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page16') and hasattr(self, '_p16_save_session_snapshot'):
            self._p16_save_session_snapshot(immediate=True)
        if hasattr(self, '_persist_tab_session_cache'):
            self._persist_tab_session_cache(immediate=True)
        if self._page_initialized(page_attr='page6') and hasattr(self, '_p6_on_goal_controls_changed'):
            self._p6_on_goal_controls_changed()
        save_networth_data(self.networth_data)
        executor = getattr(self, '_options_fetch_executor', None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        mc_executor = getattr(self, '_mc_executor', None)
        if mc_executor is not None:
            mc_executor.shutdown(wait=False, cancel_futures=True)
        compare_executor = getattr(self, '_p10_compare_executor', None)
        if compare_executor is not None:
            compare_executor.shutdown(wait=False, cancel_futures=True)
        multi_interval_executor = getattr(self, '_p10_multi_interval_executor', None)
        if multi_interval_executor is not None:
            multi_interval_executor.shutdown(wait=False, cancel_futures=True)
        handler = getattr(self, '_session_log_handler', None)
        if handler is not None:
            logger.removeHandler(handler)
            self._session_log_handler = None
        event.accept()
