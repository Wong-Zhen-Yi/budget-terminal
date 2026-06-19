from __future__ import annotations
from typing import Any
from ..compat import *

class WindowLifecycleMixin:
    _STARTUP_REFRESH_DELAY_MS = 2400
    _STARTUP_VISIBLE_REFRESH_DELAY_MS = 350
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

    def _clock_country_by_code(self, country_code: Any) -> dict[str, Any]:
        """Return the configured market-country entry for the clock."""
        code = normalize_clock_country_code(country_code)
        for choice in getattr(self, '_clock_country_choices', CLOCK_COUNTRY_CHOICES):
            if str(choice.get('code', '')).upper() == code:
                return dict(choice)
        return dict(CLOCK_COUNTRY_CHOICES[0])

    def _current_clock_country_code(self) -> str:
        """Return the active country code for the shared clock display."""
        return normalize_clock_country_code(getattr(self, '_clock_country_code', CLOCK_DEFAULT_COUNTRY_CODE))

    def _current_clock_country_index(self) -> int:
        """Return the active country index for the Settings clock selector."""
        code = self._current_clock_country_code()
        for index, choice in enumerate(getattr(self, '_clock_country_choices', CLOCK_COUNTRY_CHOICES)):
            if str(choice.get('code', '')).upper() == code:
                return index
        return 0

    def _get_clock_tzinfo(self) -> Any:
        """Resolve the selected market country into a tzinfo object."""
        choice = self._clock_country_by_code(self._current_clock_country_code())
        return ZoneInfo(str(choice.get('zone', 'America/New_York') or 'America/New_York'))

    def _now_for_clock_country(self) -> Any:
        """Return a timezone-aware current datetime for the selected clock country."""
        return datetime.datetime.now(self._get_clock_tzinfo())

    def _register_navigation_pages(self) -> None:
        """Handle register navigation pages."""
        self._startup_progress_begin('navigation', 'Navigation')
        self._pages.clear()
        self._register_page(0, self.btn_page1)
        self._register_page(25, self.btn_page26, on_show=self._p26_on_show if hasattr(self, '_p26_on_show') else None)
        self._register_page(1, self.btn_page4, on_show=self._p4_on_show if hasattr(self, '_p4_on_show') else None)
        self._register_page(2, self.btn_page6, on_show=self._p6_on_show if hasattr(self, '_p6_on_show') else None)
        self._register_page(3, self.btn_page7)
        self._register_page(19, self.btn_page20, on_show=self._p20_on_show)
        self._register_page(4, self.btn_page3, on_show=lambda: self.p3_crawler_timer.start(40) if hasattr(self, 'p3_crawler_timer') else None, on_hide=lambda: self.p3_crawler_timer.stop() if hasattr(self, 'p3_crawler_timer') else None)
        self._register_page(5, self.btn_page8, on_show=self._p8_on_show)
        self._register_page(6, self.btn_page17, on_show=self._p17_on_show)
        self._register_page(7, self.btn_page12, on_show=self._stocks_on_show)
        self._register_page(22, self.btn_page23, on_show=self._valuation_on_show if hasattr(self, '_valuation_on_show') else None)
        self._register_page(8, self.btn_page2, on_show=lambda: self._p2_relayout_charts() if hasattr(self, '_p2_relayout_charts') else None)
        self._register_page(9, self.btn_page10, on_show=self._p10_on_show)
        self._register_page(24, self.btn_page25, on_show=self._p25_on_show if hasattr(self, '_p25_on_show') else None)
        self._register_page(11, self.btn_page5)
        self._register_page(12, self.btn_page13)
        self._register_page(13, self.btn_page14, on_show=self._p14_on_show)
        self._register_page(14, self.btn_page19)
        self._register_page(15, self.btn_page15, on_show=self._p15_on_show)
        self._register_page(21, self.btn_page22, on_show=self._p22_on_show)
        self._register_page(23, self.btn_page24, on_show=self._p24_on_show)
        self._register_page(16, self.btn_page16, on_show=self._p16_on_show)
        self._register_page(18, self.btn_page18)
        self._register_page(20, self.btn_page21)
        self._register_page(17, self.btn_page9)
        self._apply_navigation_settings_to_shell()
        self._startup_progress_complete('navigation', 'Navigation')

    def _navigation_settings(self) -> dict[str, Any]:
        """Return normalized persisted navigation settings."""
        state = normalize_navigation_settings(getattr(self, 'navigation_state', DEFAULT_NAVIGATION_SETTINGS))
        self.navigation_state = state
        return state

    def _navigation_page_order(self) -> list[int]:
        """Return all registered pages in persisted display order."""
        state = self._navigation_settings()
        registered = set(getattr(self, '_pages', {}).keys())
        order = [page_index for page_index in state.get('page_order', []) if page_index in registered]
        for page_index in DEFAULT_NAVIGATION_PAGE_ORDER:
            if page_index in registered and page_index not in order:
                order.append(page_index)
        for page_index in registered:
            if page_index not in order:
                order.append(page_index)
        return order

    def _hidden_navigation_pages(self) -> set[int]:
        """Return the hidden page indexes, never including Settings."""
        state = self._navigation_settings()
        return {page_index for page_index in state.get('hidden_pages', []) if page_index != SETTINGS_PAGE_INDEX}

    def _ordered_nav_buttons(self, *, visible_only: bool) -> list[Any]:
        """Return navigation buttons in persisted order."""
        hidden = self._hidden_navigation_pages()
        buttons = []
        for page_index in self._navigation_page_order():
            if visible_only and page_index in hidden:
                continue
            page = getattr(self, '_pages', {}).get(page_index, {})
            button = page.get('btn') if isinstance(page, dict) else None
            if button is not None:
                buttons.append(button)
        return buttons

    def _first_visible_navigation_index(self) -> int:
        """Return the first visible page index, falling back to Settings."""
        hidden = self._hidden_navigation_pages()
        for page_index in self._navigation_page_order():
            if page_index not in hidden:
                return int(page_index)
        return SETTINGS_PAGE_INDEX

    def _apply_navigation_settings_to_shell(self, *, switch_hidden_current: bool=True) -> None:
        """Apply persisted navigation order and visibility to the top shell."""
        if not hasattr(self, '_nav_container_layout') or not getattr(self, '_pages', None):
            return
        layout = self._nav_container_layout
        while layout.count():
            layout.takeAt(0)
        hidden = self._hidden_navigation_pages()
        visible_buttons = set()
        for page_index in self._navigation_page_order():
            page = self._pages.get(page_index, {})
            button = page.get('btn') if isinstance(page, dict) else None
            if button is None:
                continue
            button.setVisible(page_index not in hidden)
            if page_index not in hidden:
                visible_buttons.add(button)
                layout.addWidget(button)
        for page in self._pages.values():
            button = page.get('btn') if isinstance(page, dict) else None
            if button is not None and button not in visible_buttons:
                button.setVisible(False)
        if hasattr(self, '_nav_container'):
            spacing = max(0, int(layout.spacing()))
            visible_count = len(visible_buttons)
            content_width = 0
            for button in visible_buttons:
                content_width += max(button.minimumWidth(), button.sizeHint().width())
            if visible_count > 1:
                content_width += spacing * (visible_count - 1)
            content_width = max(content_width, 1)
            self._nav_container.setMinimumWidth(content_width)
            self._nav_container.resize(content_width, self._nav_scroll_area.height())
            self._nav_container.updateGeometry()
            self._nav_scroll_area.widget().updateGeometry()
        self._refresh_main_tab_picker_items()
        if not switch_hidden_current or not hasattr(self, 'stacked_widget'):
            return
        current_index = int(self.stacked_widget.currentIndex())
        if current_index in hidden:
            self.switch_page(self._first_visible_navigation_index())

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
        """Build and refresh startup surfaces while the loading screen is visible."""
        if getattr(self, '_startup_hidden_preparation_started', False):
            return
        self._startup_hidden_preparation_started = True
        self._startup_profiler_stamp('hidden_startup_start')
        self._startup_warmup_mode = 'full_blocking_with_skip'
        logger.info('Startup loading all pages before first interaction.')
        self._startup_metrics_set_stage(
            'dashboard_data',
            status='running',
            detail='Dashboard data loading before first interaction.',
        )
        self.refresh_data(force=True, reason='startup_blocking')
        self._start_lazy_warmup()

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
        reason = str(getattr(self, '_startup_release_reason', '') or 'complete').strip().lower()
        if reason == 'skip':
            first_ui_detail = 'Released by skip; remaining startup work continued in the background.'
        elif reason == 'timeout':
            first_ui_detail = 'Released after 30s max wait; remaining startup work continued in the background.'
        elif reason == 'startup_error':
            first_ui_detail = 'Released after startup preparation error.'
        elif getattr(self, '_startup_dashboard_data_timed_out', False):
            first_ui_detail = 'Main window shown after dashboard startup timeout; data refresh still running.'
        else:
            first_ui_detail = 'Main window shown after full startup warmup.'
        self._startup_metrics_set_stage(
            'first_ui',
            status='complete',
            detail=first_ui_detail,
            completed_seconds=window_shown_seconds,
            duration_seconds=window_shown_seconds,
        )
        self._startup_progress_complete('first_show', 'First usable view')
        if profiler is not None:
            profiler.log_summary()
        if getattr(self, '_startup_dashboard_refresh_deferred', False):
            self._startup_dashboard_refresh_deferred = False
            self._schedule_startup_refresh(delay_ms=self._STARTUP_VISIBLE_REFRESH_DELAY_MS)
        elif not getattr(self, '_startup_ready_before_show', False):
            self._schedule_startup_refresh()
        self._start_lazy_warmup()
        self._schedule_startup_page_prefetches()
        full_blocking = str(getattr(self, '_startup_warmup_mode', '') or '').strip().lower() == 'full_blocking_with_skip'
        if not full_blocking or getattr(self, '_lazy_warmup_finished', False):
            self._schedule_startup_session_restores()

    def _schedule_startup_refresh(self, *, delay_ms: int | None = None) -> None:
        """Queue the first dashboard refresh after the first paint has settled."""
        if getattr(self, '_startup_refresh_pending', False):
            return
        self._startup_refresh_pending = True
        delay = self._STARTUP_REFRESH_DELAY_MS if delay_ms is None else max(int(delay_ms), 0)
        QTimer.singleShot(delay, self._run_startup_refresh)

    def _run_startup_refresh(self) -> None:
        """Run the deferred startup refresh once the window is visible."""
        self._startup_refresh_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        self._startup_profiler_stamp('startup_refresh_start')
        logger.info('Startup refresh started: %s page.', self._page_label(0))
        reason = 'startup_visible_refresh' if not getattr(self, '_startup_dashboard_data_actual_done', False) else 'startup_refresh'
        self.refresh_data(force=True, reason=reason)

    def _schedule_startup_page_prefetches(self) -> None:
        """Queue only essential post-show startup work."""
        if getattr(self, '_startup_page_prefetch_pending', False):
            return
        self._startup_page_prefetch_pending = True
        QTimer.singleShot(self._STARTUP_PRE_MARKET_TIMER_DELAY_MS, self._run_startup_pre_market_timer)

    def _startup_work_can_run(self) -> bool:
        """Return whether deferred startup work should still run."""
        if getattr(self, '_startup_show_completed', False) and self.isVisible():
            return True
        hidden_full_startup = (
            getattr(self, '_startup_hidden_preparation_started', False)
            and str(getattr(self, '_startup_warmup_mode', '') or '').strip().lower() == 'full_blocking_with_skip'
            and not getattr(self, '_startup_released_to_user', False)
        )
        return bool(hidden_full_startup)

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
        full_blocking = str(getattr(self, '_startup_warmup_mode', '') or '').strip().lower() == 'full_blocking_with_skip'
        if full_blocking and not getattr(self, '_startup_show_completed', False):
            self._startup_cache_warmup_pending = True
            QTimer.singleShot(1000, self._retry_startup_cache_warmup)
            return
        if not self._startup_work_can_run():
            return
        if (not getattr(self, '_startup_dashboard_data_actual_done', False)) or getattr(self, '_startup_page_prefetch_pending', False):
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
        mode = str(getattr(self, '_startup_warmup_mode', 'minimal') or 'minimal').strip().lower()
        minimal_specs = [
            {'label': 'chart cache', 'method': '_warm_startup_chart_cache'},
            {'label': 'portfolio metrics', 'method': '_warm_startup_portfolio_metrics'},
        ]
        if mode not in {'full', 'full_blocking_with_skip'}:
            return minimal_specs
        return [
            *minimal_specs,
            {'label': 'options expiries', 'method': '_warm_startup_options_expiries'},
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
                    request_key = ('chart', symbol, '1mo', '1d')
                    if request_key in getattr(self, '_startup_recent_data_request_keys', set()):
                        logger.info('Startup chart cache warmup skipped duplicate request for %s.', symbol)
                        continue
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
        restored_tabs = getattr(self, '_startup_session_restored_tabs', None)
        specs = [
            {'tab_key': 'stocks', 'page_index': 7, 'restore_method': '_stocks_restore_startup_session'},
            {'tab_key': 'valuation', 'page_index': 22, 'restore_method': '_valuation_restore_startup_session'},
            {'tab_key': 'roll', 'page_index': 18, 'restore_method': '_p18_restore_startup_session'},
            {'tab_key': 'fundamentals', 'page_index': 8, 'restore_method': '_p2_restore_startup_session'},
            {'tab_key': 'options', 'page_index': 11, 'restore_method': '_p5_restore_startup_session'},
            {'tab_key': 'etf', 'page_index': 12, 'restore_method': '_p13_restore_startup_session'},
            {'tab_key': 'politics', 'page_index': 15, 'restore_method': '_p15_restore_startup_session', 'allow_empty_snapshot': True},
            {'tab_key': 'youtube', 'page_index': 16, 'restore_method': '_p16_restore_startup_session'},
            {'tab_key': 'calendar', 'page_index': 3, 'restore_method': '_p7_restore_startup_session'},
        ]
        queue = []
        for spec in specs:
            tab_key = str(spec.get('tab_key') or '')
            if isinstance(restored_tabs, set) and tab_key in restored_tabs:
                continue
            snapshot = self._get_tab_session_snapshot(spec['tab_key']) if hasattr(self, '_get_tab_session_snapshot') else None
            if snapshot or spec.get('allow_empty_snapshot'):
                queue.append({**spec, 'snapshot': snapshot})
        return queue

    def _schedule_startup_session_restores(self) -> None:
        """Queue hidden last-session tab restores after early startup work has settled."""
        if getattr(self, '_startup_session_restore_pending', False):
            return
        full_blocking = str(getattr(self, '_startup_warmup_mode', 'minimal') or 'minimal').strip().lower() == 'full_blocking_with_skip'
        self._startup_progress_begin('session_restore', 'Session Restore')
        if not full_blocking:
            queue = self._startup_session_restore_specs()
            self._startup_session_restore_queue = []
            self._startup_metrics_set_stage(
                'session_restore',
                status='skipped',
                detail='Cached tab restore deferred until pages are opened.',
                count=len(queue),
                duration_seconds=0.0,
            )
            logger.info(
                'Startup session restore deferred for %s cached page(s): %s.',
                len(queue),
                ', '.join(self._page_label(item.get('page_index')) for item in queue) if queue else 'none',
            )
            self._startup_progress_complete('session_restore', 'Session Restore')
            return
        queue = self._startup_session_restore_specs()
        self._startup_session_restore_queue = list(queue)
        if not queue:
            self._startup_metrics_set_stage(
                'session_restore',
                status='complete',
                detail='No remaining cached tabs to restore.',
                count=0,
                duration_seconds=0.0,
            )
            self._startup_progress_complete('session_restore', 'Session Restore')
            self._schedule_startup_data_start()
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
        delay = 0 if full_blocking and not getattr(self, '_startup_show_completed', False) else self._STARTUP_SESSION_RESTORE_INITIAL_DELAY_MS
        QTimer.singleShot(delay, self._run_startup_session_restore_step)

    def _run_startup_session_restore_step(self) -> None:
        """Build, restore, and silently refresh one cached tab at a time."""
        self._startup_session_restore_pending = False
        if not self._startup_work_can_run():
            return
        queue = list(getattr(self, '_startup_session_restore_queue', []))
        if not queue:
            self._startup_metrics_set_stage(
                'session_restore',
                status='complete',
                detail='Startup session restore complete.',
                count=getattr(self, '_startup_session_restore_total', 0),
            )
            self._startup_progress_complete('session_restore', 'Session Restore')
            self._schedule_startup_data_start()
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
                restored_tabs = getattr(self, '_startup_session_restored_tabs', None)
                if isinstance(restored_tabs, set):
                    restored_tabs.add(str(current.get('tab_key') or ''))
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
            self._startup_progress_complete('session_restore', 'Session Restore')
            self._schedule_startup_data_start()

    def _schedule_startup_data_start(self) -> None:
        """Dispatch each page's normal startup data refresh path once pages are ready."""
        if getattr(self, '_startup_data_start_pending', False) or getattr(self, '_startup_data_start_done', False):
            return
        self._startup_data_start_pending = True
        self._startup_progress_begin('startup_data', 'Startup Data')
        self._startup_metrics_set_stage(
            'startup_data',
            status='running',
            detail='Dispatching page startup data refreshes.',
        )
        QTimer.singleShot(0, self._run_startup_data_start)

    def _run_startup_data_start(self) -> None:
        """Kick off page refreshes without waiting for every network call to finish."""
        self._startup_data_start_pending = False
        if not self._startup_work_can_run():
            self._startup_data_start_pending = True
            QTimer.singleShot(250, self._run_startup_data_start)
            return
        dispatched = 0
        failed = False

        def _dispatch(label: str, fn: Any, *args: Any, **kwargs: Any) -> None:
            nonlocal dispatched, failed
            if not callable(fn):
                return
            try:
                result = fn(*args, **kwargs)
                if result is not False:
                    dispatched += 1
            except Exception as exc:
                failed = True
                logger.exception('Startup data dispatch failed for %s.', label)
                if hasattr(self, '_record_data_health_exception'):
                    self._record_data_health_exception(f'Startup data: {label}', exc, severity='warning')

        if hasattr(self, '_fetch_portfolio_analytics'):
            _dispatch('Portfolio metrics', self._fetch_portfolio_analytics, force=False)
        if self._page_initialized(index=5):
            _dispatch('Sectors', getattr(self, '_p8_request_refresh', None), force=False, status_text='Loading sector data...')
        if self._page_initialized(index=6):
            _dispatch('Heatmap', getattr(self, '_p17_request_refresh', None), force=False)
        if self._page_initialized(index=7):
            _dispatch('Stocks', getattr(self, '_stocks_load_from_input', None), include_global_status=False, update_collection_info=True)
        if self._page_initialized(index=22):
            _dispatch('Valuation', getattr(self, 'load_valuation_data', None), update_collection_info=True)
        if self._page_initialized(index=8):
            _dispatch('Fundamentals', getattr(self, 'analyze_stock_p2', None), update_collection_info=True)
        if self._page_initialized(index=9):
            active_key = self._p10_active_subtab_key() if hasattr(self, '_p10_active_subtab_key') else 'chart'
            if active_key == 'compare':
                _dispatch('Charts compare', getattr(self, '_p10_refresh_compare_view', None), force=False)
            elif active_key == 'multiintervals':
                _dispatch('Charts intervals', getattr(self, '_p10_refresh_multi_interval_views', None), force=False)
            elif active_key == 'multicharts':
                _dispatch('Charts multi', getattr(self, '_mc_refresh_all', None))
            else:
                _dispatch('Charts', getattr(self, '_p10_refresh_chart', None), force_refresh=False)
        if self._page_initialized(index=11):
            _dispatch('Options', getattr(self, '_p5_load_active_subtab', None))
        if self._page_initialized(index=12):
            _dispatch('ETF', getattr(self, '_p13_load_etf', None), update_collection_info=True)
        if self._page_initialized(index=13):
            _dispatch('Pre-Market', getattr(self, '_p14_start_auto_refresh', None))
        if self._page_initialized(index=14):
            _dispatch('Crypto', getattr(self, '_p19_refresh_data', None))
        if self._page_initialized(index=15):
            _dispatch('Politics', getattr(self, '_p15_refresh', None), force=False)
        if self._page_initialized(index=16):
            _dispatch('YouTube', getattr(self, '_p16_refresh', None), force=False, auto_trigger=False)
        if self._page_initialized(index=17):
            _dispatch('Settings startup controls', getattr(self, '_refresh_startup_performance_views', None))
        if self._page_initialized(index=18):
            _dispatch('Roll', getattr(self, '_p18_roll_stock', None), include_global_status=False)

        self._startup_data_start_done = True
        self._startup_metrics_set_stage(
            'startup_data',
            status='failed' if failed else 'complete',
            detail='Startup data dispatch finished with errors.' if failed else 'Startup data refreshes dispatched.',
            count=dispatched,
        )
        self._startup_progress_complete('startup_data', 'Startup Data')
        self._startup_progress_finish_if_complete()

    def _start_lazy_warmup(self) -> None:
        """Warm secondary pages one at a time after the window becomes interactive."""
        if getattr(self, '_lazy_warmup_started', False) or getattr(self, '_lazy_warmup_finished', False):
            return
        if not getattr(self, '_startup_show_completed', False) and not self._startup_work_can_run():
            return
        self._startup_progress_begin('lazy_warmup', 'Page warmup')
        queue = []
        mode = str(getattr(self, '_startup_warmup_mode', 'minimal') or 'minimal').strip().lower()
        if mode == 'minimal':
            if not self._page_initialized(index=1):
                queue.append(1)
            self._lazy_warmup_queue = queue
            if not queue:
                self._lazy_warmup_finished = True
                self._startup_metrics_set_stage(
                    'page_warmup',
                    status='skipped',
                    detail='No priority pages needed warmup.',
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
                detail='Warming priority pages only.',
                count=self._lazy_warmup_total,
            )
            self._lazy_page_warmup_timer.start(getattr(self, '_LAZY_WARMUP_STEP_MS', 75))
            return
        excluded_pages = set() if mode == 'full_blocking_with_skip' else {3, 12}
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
            22: 58,
            8: 60,
            9: 65,
            24: 68,
            11: 70,
            12: 80,
            13: 90,
            14: 100,
            15: 110,
            21: 115,
            16: 120,
            17: 130,
            18: 140,
            3: 150,
            20: 999,
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
            if str(getattr(self, '_startup_warmup_mode', '') or '').strip().lower() == 'full_blocking_with_skip':
                self._schedule_startup_session_restores()
            else:
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
        initial_delay = 0 if mode == 'full_blocking_with_skip' and not getattr(self, '_startup_show_completed', False) else getattr(self, '_LAZY_WARMUP_INITIAL_DELAY_MS', 500)
        timer.start(initial_delay)

    def _warm_next_page(self) -> None:
        """Initialize one pending lazy page and reschedule the next warmup step."""
        while getattr(self, '_lazy_warmup_queue', []):
            page_index = self._lazy_warmup_queue.pop(0)
            if self._page_initialized(index=page_index):
                continue
            try:
                logger.info('Lazy page warmup loading %s page (index %s).', self._page_label(page_index), page_index)
                with self._startup_profiler_step(f'lazy_page_{int(page_index)}'):
                    priority_warmup = (
                        int(page_index) == 1
                        and str(getattr(self, '_startup_warmup_mode', 'minimal') or 'minimal').strip().lower() == 'minimal'
                    )
                    self._startup_priority_page_warmup = priority_warmup
                    try:
                        self._build_page_now(page_index, reason='lazy warmup')
                    finally:
                        self._startup_priority_page_warmup = False
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
            if str(getattr(self, '_startup_warmup_mode', '') or '').strip().lower() == 'full_blocking_with_skip':
                self._schedule_startup_session_restores()
            else:
                self._startup_progress_finish_if_complete()

    def _restore_lazy_session_for_page(self, page_index: Any) -> None:
        """Restore one cached tab snapshot when its page is opened or warmed."""
        try:
            numeric_index = int(page_index)
        except (TypeError, ValueError):
            return
        for spec in self._startup_session_restore_specs():
            if int(spec.get('page_index', -1)) != numeric_index:
                continue
            tab_key = str(spec.get('tab_key') or '')
            restored_tabs = getattr(self, '_startup_session_restored_tabs', None)
            if isinstance(restored_tabs, set) and tab_key in restored_tabs:
                return
            restore_fn = getattr(self, str(spec.get('restore_method', '') or ''), None)
            if not callable(restore_fn):
                return
            logger.info('Lazy session restore started: %s page (tab=%s).', self._page_label(numeric_index), tab_key)
            restore_fn(spec.get('snapshot'))
            if isinstance(restored_tabs, set):
                restored_tabs.add(tab_key)
            logger.info('Lazy session restore complete: %s page (tab=%s).', self._page_label(numeric_index), tab_key)
            return

    def _ensure_page_initialized(self, index: Any) -> None:
        """Synchronously build a lazy page before it becomes visible."""
        if self._page_initialized(index=index):
            return
        logger.info('Page initialization required before show: %s (index %s).', self._page_label(index), index)
        self._build_page_now(index, reason='before show')

    def _restore_window_height_after_page_switch(self, target_height: Any) -> None:
        """Undo page-switch height growth while leaving user-driven resizing intact."""
        try:
            height = int(target_height)
        except (TypeError, ValueError):
            return
        if height <= 0:
            return
        if self.isMaximized() or self.isFullScreen():
            return
        if self.height() > height:
            self.resize(self.width(), height)

    def _run_page_show_callback(self, index: int, sequence: int) -> None:
        """Run a deferred page-show callback only if the page is still current."""
        if not hasattr(self, 'stacked_widget'):
            return
        if int(self.stacked_widget.currentIndex()) != int(index):
            return
        if int(getattr(self, '_page_switch_sequence', 0) or 0) != int(sequence):
            return
        page = getattr(self, '_pages', {}).get(index, {})
        callback = page.get('on_show') if isinstance(page, dict) else None
        if callable(callback):
            callback()

    def switch_page(self, index: Any, *_: Any) -> None:
        """Switch page."""
        try:
            numeric_index = int(index)
        except (TypeError, ValueError):
            return
        preserve_height = 0
        if not (self.isMaximized() or self.isFullScreen()):
            preserve_height = int(self.height())
        previous_index = int(self.stacked_widget.currentIndex()) if hasattr(self, 'stacked_widget') else 0
        previous_label = self._page_label(previous_index)
        target_label = self._page_label(numeric_index)
        logger.info('Page navigation requested: %s (index %s) -> %s (index %s).', previous_label, previous_index, target_label, numeric_index)
        self._ensure_page_initialized(numeric_index)
        previous_page = self._pages.get(previous_index, {}) if hasattr(self, '_pages') else {}
        hide_callback = previous_page.get('on_hide') if isinstance(previous_page, dict) else None
        if previous_index != numeric_index and callable(hide_callback):
            hide_callback()
        self.stacked_widget.setCurrentIndex(numeric_index)
        self._restore_window_height_after_page_switch(preserve_height)
        for i, page in self._pages.items():
            page['btn'].setChecked(i == numeric_index)
        self._page_switch_sequence = int(getattr(self, '_page_switch_sequence', 0) or 0) + 1
        switch_sequence = int(self._page_switch_sequence)
        QTimer.singleShot(0, lambda idx=numeric_index, seq=switch_sequence: self._run_page_show_callback(idx, seq))
        if preserve_height:
            QTimer.singleShot(0, lambda height=preserve_height: self._restore_window_height_after_page_switch(height))
        logger.info('Page shown: %s (index %s).', target_label, numeric_index)

    def _refresh_main_tab_picker_items(self) -> None:
        """Sync the top-bar picker with visible pages and known first-level subtabs."""
        if not hasattr(self, '_tab_picker_list'):
            return
        items = []
        entries = []
        item_map = {}
        subpage_specs = self._tab_picker_subpage_specs()
        for button in self._ordered_nav_buttons(visible_only=True):
            page_index = self._page_index_for_button(button)
            if page_index is None:
                continue
            label = button.text().strip()
            if not label:
                continue
            main_entry = self._make_tab_picker_entry(label, page_index, aliases=(self._page_label(page_index),))
            entries.append(main_entry)
            items.append(main_entry['label'])
            for search_value in main_entry['search_values']:
                item_map.setdefault(search_value.casefold(), main_entry)
            for spec in subpage_specs.get(int(page_index), ()):
                tab_text = str(spec.get('tab_text', '') or '').strip()
                if not tab_text:
                    continue
                entry = self._make_tab_picker_entry(
                    f'{label} > {tab_text}',
                    page_index,
                    tab_widget_attr=spec.get('tab_widget_attr'),
                    tab_text=tab_text,
                    aliases=spec.get('aliases', ()),
                )
                entries.append(entry)
                items.append(entry['label'])
                for search_value in entry['search_values']:
                    item_map.setdefault(search_value.casefold(), entry)
        self._tab_picker_items = items
        self._tab_picker_entries = entries
        self._tab_picker_map = item_map
        self._filter_tab_picker_items(getattr(self, '_tab_picker_input', None).text() if hasattr(self, '_tab_picker_input') else '')

    def _tab_picker_subpage_specs(self) -> dict[int, tuple[dict[str, Any], ...]]:
        """Return static first-level subpages exposed through the page picker."""
        return {
            1: (
                {'tab_widget_attr': 'p4_content_tabs', 'tab_text': 'Positions'},
                {'tab_widget_attr': 'p4_content_tabs', 'tab_text': 'Portfolio Heatmap'},
                {'tab_widget_attr': 'p4_content_tabs', 'tab_text': 'Momentum Tracker', 'aliases': ('Momentum',)},
                {'tab_widget_attr': 'p4_content_tabs', 'tab_text': 'Portfolio Metrics', 'aliases': ('Metrics',)},
            ),
            3: (
                {'tab_widget_attr': 'p7_tabs', 'tab_text': 'Calendar'},
                {'tab_widget_attr': 'p7_tabs', 'tab_text': 'Earnings'},
            ),
            9: (
                {'tab_widget_attr': 'p10_tabs', 'tab_text': 'Main'},
                {'tab_widget_attr': 'p10_tabs', 'tab_text': 'Multi Charts', 'aliases': ('Multiple Charts',)},
                {'tab_widget_attr': 'p10_tabs', 'tab_text': 'Compare', 'aliases': ('Comparison',)},
            ),
            11: (
                {'tab_widget_attr': 'p5_tabs', 'tab_text': 'Chain', 'aliases': ('Options Chain',)},
                {
                    'tab_widget_attr': 'p5_tabs',
                    'tab_text': getattr(self, '_P5_TOP_VOLUME_TAB_LABEL', 'Options by Top Volume'),
                    'aliases': ('Top Volume',),
                },
                {
                    'tab_widget_attr': 'p5_tabs',
                    'tab_text': getattr(self, '_P5_STRIKE_TAB_LABEL', 'Options by Strike'),
                    'aliases': ('Strike',),
                },
            ),
            12: (
                {'tab_widget_attr': 'p13_tabs', 'tab_text': 'Holdings', 'aliases': ('ETF Holdings',)},
                {'tab_widget_attr': 'p13_tabs', 'tab_text': 'Arbitrage', 'aliases': ('ETF Arbitrage',)},
            ),
            21: (
                {'tab_widget_attr': 'p22_tabs', 'tab_text': 'Overview'},
                {'tab_widget_attr': 'p22_tabs', 'tab_text': 'Ticker Lookup', 'aliases': ('Ticker',)},
                {'tab_widget_attr': 'p22_tabs', 'tab_text': 'Manager Lookup', 'aliases': ('Manager',)},
                {'tab_widget_attr': 'p22_tabs', 'tab_text': 'Insider', 'aliases': ('Insiders',)},
            ),
            22: (
                {'tab_widget_attr': 'valuation_detail_tabs', 'tab_text': 'Main'},
                {'tab_widget_attr': 'valuation_detail_tabs', 'tab_text': 'Scenarios'},
                {'tab_widget_attr': 'valuation_detail_tabs', 'tab_text': 'Peers'},
                {'tab_widget_attr': 'valuation_detail_tabs', 'tab_text': 'Risk'},
                {'tab_widget_attr': 'valuation_detail_tabs', 'tab_text': 'Trends'},
            ),
        }

    def _make_tab_picker_entry(
        self,
        label: str,
        page_index: Any,
        *,
        tab_widget_attr: Any=None,
        tab_text: Any=None,
        aliases: Any=(),
    ) -> dict[str, Any]:
        """Build a searchable picker entry for one page or subpage target."""
        clean_label = str(label or '').strip()
        try:
            numeric_index = int(page_index)
        except (TypeError, ValueError):
            numeric_index = -1
        clean_tab_text = str(tab_text or '').strip()
        search_values = []
        for value in (clean_label, clean_label.replace('>', ' '), self._page_label(numeric_index), clean_tab_text, *tuple(aliases or ())):
            clean_value = str(value or '').strip()
            if clean_value and clean_value not in search_values:
                search_values.append(clean_value)
        return {
            'label': clean_label,
            'page_index': numeric_index,
            'tab_widget_attr': str(tab_widget_attr or '').strip(),
            'tab_text': clean_tab_text,
            'aliases': tuple(str(value).strip() for value in aliases or () if str(value).strip()),
            'search_values': tuple(search_values),
            'search_text': ' '.join(search_values).casefold(),
        }

    def _page_index_for_button(self, button: Any) -> Any:
        """Return the registered page index for a nav button."""
        for index, page in self._pages.items():
            if page.get('btn') is button:
                return index
        return None

    def _find_tab_picker_match(self, text: Any) -> Any:
        """Resolve user-entered picker text into a structured entry."""
        query = str(text or '').strip()
        if not query:
            return None
        lowered = query.casefold()
        exact = self._tab_picker_map.get(lowered)
        if exact is not None:
            return exact
        for entry in getattr(self, '_tab_picker_entries', []):
            if lowered in str(entry.get('search_text', '')):
                return entry
        return None

    def _find_main_tab_match(self, text: Any) -> Any:
        """Resolve user-entered picker text into a main page index."""
        entry = self._find_tab_picker_match(text)
        if not entry:
            return None
        return entry.get('page_index')

    def _filter_tab_picker_items(self, text: Any) -> None:
        """Filter popup picker rows from the current query text."""
        if not hasattr(self, '_tab_picker_list'):
            return
        query = str(text or '').strip().casefold()
        self._tab_picker_list.clear()
        matches = []
        for order, entry in enumerate(getattr(self, '_tab_picker_entries', [])):
            if not query:
                matches.append((order, order, entry))
                continue
            search_text = str(entry.get('search_text', ''))
            if query not in search_text:
                continue
            search_values = [str(value or '').casefold() for value in entry.get('search_values', ())]
            if query in search_values:
                rank = 0
            elif any(value.startswith(query) for value in search_values):
                rank = 1
            else:
                rank = 2
            matches.append((rank, order, entry))
        for _rank, _order, entry in sorted(matches, key=lambda item: (item[0], item[1])):
            item = QListWidgetItem(str(entry.get('label', '') or ''))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._tab_picker_list.addItem(item)
        if self._tab_picker_list.count() > 0:
            self._tab_picker_list.setCurrentRow(0)

    def _activate_tab_picker_item(self, item: Any) -> None:
        """Open a page or subpage from a popup list selection."""
        label = item.text() if hasattr(item, 'text') else str(item or '')
        entry = item.data(Qt.ItemDataRole.UserRole) if hasattr(item, 'data') else None
        if not isinstance(entry, dict):
            entry = self._find_tab_picker_match(label)
        if not isinstance(entry, dict):
            return
        page_index = entry.get('page_index')
        if page_index is None:
            return
        logger.info('Tab picker activated: %s -> %s page.', self._safe_log_text(label), self._page_label(page_index))
        self.switch_page(page_index)
        if entry.get('tab_widget_attr') and entry.get('tab_text'):
            self._select_tab_picker_subpage(entry)
        self._hide_tab_picker()

    def _select_tab_picker_subpage(self, entry: dict[str, Any]) -> bool:
        """Select the configured subtab for a structured picker entry."""
        tab_widget_attr = str(entry.get('tab_widget_attr', '') or '').strip()
        tab_text = str(entry.get('tab_text', '') or '').strip()
        tab_widget = getattr(self, tab_widget_attr, None)
        if not tab_widget_attr or not tab_text or tab_widget is None or not hasattr(tab_widget, 'count'):
            logger.warning(
                'Tab picker subpage target missing: %s (%s).',
                self._safe_log_text(entry.get('label')),
                self._safe_log_text(tab_widget_attr, fallback='unknown widget'),
            )
            return False
        target = tab_text.casefold()
        for index in range(int(tab_widget.count())):
            if str(tab_widget.tabText(index) or '').strip().casefold() == target:
                tab_widget.setCurrentIndex(index)
                return True
        logger.warning(
            'Tab picker subpage tab missing: %s (%s).',
            self._safe_log_text(entry.get('label')),
            self._safe_log_text(tab_text, fallback='unknown tab'),
        )
        return False

    def _show_tab_picker(self, *, preserve_query: bool=False) -> None:
        """Reveal the top-bar picker and focus it for typed navigation."""
        if not hasattr(self, '_tab_picker_popup'):
            return
        query = self._tab_picker_input.text() if preserve_query and hasattr(self, '_tab_picker_input') else ''
        self._refresh_main_tab_picker_items()
        popup_margin = 16
        popup_x = max(self.width() - self._tab_picker_popup.width() - popup_margin, popup_margin)
        popup_pos = self.mapToGlobal(QPoint(popup_x, 52))
        self._tab_picker_popup.move(popup_pos)
        if hasattr(self, '_tab_picker_input'):
            self._tab_picker_input.setText(query)
        self._filter_tab_picker_items(query)
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

    def _is_main_window_event_target(self, obj: Any) -> bool:
        """Return whether a global event target belongs to this main window."""
        target = obj if isinstance(obj, QWidget) else QApplication.focusWidget()
        if target is None:
            return False
        if target is self:
            return True
        if not isinstance(target, QWidget):
            return False
        return target.window() is self

    def _handle_global_input_exit_event(self, obj: Any, event: Any) -> bool:
        """Handle app-wide Escape/backtick behavior for text entry widgets."""
        if hasattr(self, '_tab_picker_popup') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            if self._is_plain_backtick_key(event):
                self._show_tab_picker(preserve_query=True)
                event.accept()
                return True
            return False
        if self._is_plain_escape_key(event) and self._dismiss_main_window_text_input(obj):
            event.accept()
            return True
        if self._is_plain_backtick_key(event) and self._is_main_window_event_target(obj):
            self._dismiss_main_window_text_input(obj, focus_current_button=False)
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
        buttons = self._ordered_nav_buttons(visible_only=True)
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
        if current_index == 0:
            if hasattr(self, 'refresh_data'):
                self.refresh_data(force=True, reason='manual_refresh')
            return
        if current_index == 4:
            if hasattr(self, '_p3_request_news_refresh'):
                self._p3_request_news_refresh()
            elif hasattr(self, 'refresh_data'):
                self.refresh_data(force=True, reason='manual_refresh')
            return
        if current_index == 25:
            if hasattr(self, '_p26_request_refresh'):
                self._p26_request_refresh(force=True)
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
            if hasattr(self, '_p7_earnings_tab_is_active') and self._p7_earnings_tab_is_active():
                if hasattr(self, '_p7_refresh_earnings'):
                    self._p7_refresh_earnings(force=True)
                return
            if hasattr(self, '_p7_fetch_events'):
                self._p7_fetch_events()
            return
        if current_index == 19:
            if hasattr(self, '_p20_refresh_trading_volume'):
                self._p20_refresh_trading_volume(force=True)
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
        if current_index == 22:
            if hasattr(self, 'load_valuation_data'):
                self.load_valuation_data(update_collection_info=True)
            return
        if current_index == 23:
            if hasattr(self, '_p24_refresh_current'):
                self._p24_refresh_current(force=True)
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
            if hasattr(self, '_p19_refresh_data'):
                self._p19_refresh_data()
            return
        if current_index == 15:
            if hasattr(self, '_p15_refresh'):
                self._p15_refresh(force=True)
            return
        if current_index == 16:
            if hasattr(self, '_p16_refresh'):
                self._p16_refresh(force=False, auto_trigger=False)
            return
        if current_index == 17:
            if hasattr(self, '_refresh_run_on_startup_controls'):
                self._refresh_run_on_startup_controls()
            if hasattr(self, '_refresh_settings_log_controls'):
                self._refresh_settings_log_controls()
            if hasattr(self, '_refresh_startup_performance_views'):
                self._refresh_startup_performance_views()
            if hasattr(self, '_set_settings_status'):
                self._set_settings_status('Settings panel refreshed.', 'positive')
            return
        if current_index == 18:
            if hasattr(self, '_p18_roll_stock'):
                self._p18_roll_stock(include_global_status=True)
            return
        if current_index == 20:
            if hasattr(self, '_p21_refresh_ipo_calendar'):
                self._p21_refresh_ipo_calendar(force=True)
            return

    def _handle_tab_picker_shortcut(self) -> None:
        """Open or refocus the popup tab picker from the global shortcut."""
        if hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible():
            self._show_tab_picker(preserve_query=True)
            return
        self._show_tab_picker()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Handle picker-specific keyboard and focus behavior before other filters."""
        if hasattr(self, '_tab_picker_popup') and hasattr(self, '_tab_picker_list') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            if self._is_plain_backtick_key(event):
                self._show_tab_picker(preserve_query=True)
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

    def _on_settings_clock_country_changed(self, index: int) -> None:
        """Handle market-country changes from the Settings page clock controls."""
        code = None
        if hasattr(self, 'settings_clock_country_combo') and index is not None and index >= 0:
            code = self.settings_clock_country_combo.itemData(int(index))
        self._clock_country_code = save_clock_country_code(code)
        self.update_time()

    def update_time(self, *_: Any) -> None:
        """Update time."""
        now = self._now_for_clock_country()
        if self._time_12h:
            self.time_label.setText(now.strftime('%I:%M:%S %p'))
        else:
            self.time_label.setText(now.strftime('%H:%M:%S'))
        self._refresh_data_collection_label()
        if hasattr(self, '_p26_maybe_refresh_market_status_display'):
            self._p26_maybe_refresh_market_status_display()

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
            now = self._now_for_clock_country()
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
            tzinfo = self._get_clock_tzinfo()
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
        if self._page_initialized(page_attr='page23'):
            if hasattr(self, '_valuation_persist_settings'):
                self._valuation_persist_settings()
            if hasattr(self, '_valuation_save_session_snapshot'):
                self._valuation_save_session_snapshot(immediate=True)
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
        if self._page_initialized(page_attr='page7') and hasattr(self, '_p7_save_session_snapshot'):
            self._p7_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page20') and hasattr(self, '_p20_save_session_snapshot'):
            self._p20_save_session_snapshot(immediate=True)
        if hasattr(self, '_persist_tab_session_cache'):
            self._persist_tab_session_cache(immediate=True)
        if self._page_initialized(page_attr='page6') and hasattr(self, '_p6_on_goal_controls_changed'):
            self._p6_on_goal_controls_changed()
        save_networth_data(self.networth_data)
        dashboard_executor = getattr(self, '_dashboard_fetch_executor', None)
        if dashboard_executor is not None:
            dashboard_executor.shutdown(wait=False, cancel_futures=True)
        executor = getattr(self, '_options_fetch_executor', None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        portfolio_executor = getattr(self, '_portfolio_task_executor', None)
        if portfolio_executor is not None:
            portfolio_executor.shutdown(wait=False, cancel_futures=True)
        heatmap_executor = getattr(self, '_p17_fetch_executor', None)
        if heatmap_executor is not None:
            heatmap_executor.shutdown(wait=False, cancel_futures=True)
        mc_executor = getattr(self, '_mc_executor', None)
        if mc_executor is not None:
            mc_executor.shutdown(wait=False, cancel_futures=True)
        compare_executor = getattr(self, '_p10_compare_executor', None)
        if compare_executor is not None:
            compare_executor.shutdown(wait=False, cancel_futures=True)
        multi_interval_executor = getattr(self, '_p10_multi_interval_executor', None)
        if multi_interval_executor is not None:
            multi_interval_executor.shutdown(wait=False, cancel_futures=True)
        backtest_executor = getattr(self, '_p25_executor', None)
        if backtest_executor is not None:
            backtest_executor.shutdown(wait=False, cancel_futures=True)
        global_executor = getattr(self, '_p26_executor', None)
        if global_executor is not None:
            global_executor.shutdown(wait=False, cancel_futures=True)
        handler = getattr(self, '_session_log_handler', None)
        if handler is not None:
            logger.removeHandler(handler)
            self._session_log_handler = None
        event.accept()
