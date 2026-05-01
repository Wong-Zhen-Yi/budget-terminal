from __future__ import annotations
from typing import Any

from budget_terminal_app.compat import *
from budget_terminal_app.paths import user_data_dir
from budget_terminal_app.startup_integration import get_startup_registration_status, set_run_on_startup
from budget_terminal_app.workers import calendar as calendar_worker
from budget_terminal_app.workers.data import DataWorker
from budget_terminal_app.workers.politics import CACHE_DIR as POLITICS_CACHE_DIR
from budget_terminal_app.workers.youtube import YOUTUBE_CACHE_DIR


class SettingsMixin:
    SETTINGS_CACHE_DIR_NAMES = (
        calendar_worker._ECONOMIC_EVENTS_CACHE_DIR,
        calendar_worker._MARKET_HOLIDAY_CACHE_DIR,
        POLITICS_CACHE_DIR,
        YOUTUBE_CACHE_DIR,
    )
    SETTINGS_SHORTCUT_ROWS = (
        ('Ctrl+Tab', 'Switch to the next main tab and wrap from Settings back to Dashboard.'),
        ('F5', 'Refresh the page that is currently open in the main workspace.'),
        ('`', 'Open or close the tab picker. If a main-window text input is focused, exit it first and then open the picker.'),
        ('Esc', 'Close the tab picker or exit the active main-window text input without changing pages.'),
    )

    def init_page9(self) -> None:
        """Build the Settings page UI."""
        logger.info('Settings page initialization started.')
        page_layout = QVBoxLayout(self.page9)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_layout.addWidget(scroll_area)
        content_widget = QWidget()
        scroll_area.setWidget(content_widget)
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel('Settings')
        self.set_theme_role(title, 'page_title')
        description = QLabel('Manage saved portfolio, tracker, personal finance, and chart data. Export User Data saves one JSON backup file, Import User Data restores from one JSON backup file, and Clear removes saved user data while keeping dashboard chart slots.')
        description.setWordWrap(True)
        self.set_theme_role(description, 'muted')
        header_layout.addWidget(title)
        header_layout.addWidget(description)
        self.settings_header_badge = QLabel('Live theme switching enabled')
        self.settings_header_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.settings_header_badge, 'badge')
        self.settings_header_badge.setMinimumHeight(34)
        self.settings_header_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(self.settings_header_badge, 0, Qt.AlignmentFlag.AlignLeft)

        theme_box = QGroupBox('Appearance')
        self.set_theme_role(theme_box, 'panel')
        theme_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        theme_layout = QVBoxLayout(theme_box)
        theme_layout.setContentsMargins(14, 16, 14, 14)
        theme_layout.setSpacing(12)
        theme_label = QLabel('Theme Selection')
        self.set_theme_role(theme_label, 'section_title')
        theme_hint = QLabel('Trading Dark is the current supported theme. The selector stays wired to the theme registry so additional themes can be restored cleanly later.')
        theme_hint.setWordWrap(True)
        self.set_theme_role(theme_hint, 'muted')
        self.settings_theme_combo = QComboBox()
        self.settings_theme_combo.setMinimumHeight(32)
        available_themes = self.theme_manager.available_themes()
        for theme_id, theme in available_themes.items():
            self.settings_theme_combo.addItem(theme.name, theme_id)
        self.settings_theme_combo.setEnabled(len(available_themes) > 1)
        current_index = self.settings_theme_combo.findData(getattr(self, 'current_theme_id', self.theme_manager.current_theme_id))
        if current_index >= 0:
            self.settings_theme_combo.setCurrentIndex(current_index)
        self.settings_theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        self.settings_theme_preview = QLabel(self.theme_id_to_name(getattr(self, 'current_theme_id', self.theme_manager.current_theme_id)))
        self.set_theme_role(self.settings_theme_preview, 'badge')
        self.settings_theme_preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.settings_theme_preview.setMinimumHeight(32)
        clock_label = QLabel('Clock')
        self.set_theme_role(clock_label, 'section_title')
        clock_hint = QLabel('Choose the timezone shown in the top-bar clock and whether it uses a 12-hour display.')
        clock_hint.setWordWrap(True)
        self.set_theme_role(clock_hint, 'muted')
        self.settings_timezone_combo = QComboBox()
        self.settings_timezone_combo.setMinimumHeight(32)
        self.settings_timezone_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for name, _ in self._tz_choices:
            self.settings_timezone_combo.addItem(name)
        self.settings_timezone_combo.setCurrentIndex(self._current_clock_timezone_index())
        self.settings_timezone_combo.currentIndexChanged.connect(self._on_settings_timezone_changed)
        self.settings_time_format_checkbox = QCheckBox('Use 12-hour time in the top-bar clock')
        self.settings_time_format_checkbox.setChecked(bool(getattr(self, '_time_12h', True)))
        self.settings_time_format_checkbox.toggled.connect(lambda checked: self._toggle_time_format() if bool(checked) != bool(getattr(self, '_time_12h', False)) else None)
        startup_label = QLabel('Windows Startup')
        self.set_theme_role(startup_label, 'section_title')
        self.settings_startup_checkbox = QCheckBox('Run Budget Terminal when I sign in to Windows')
        self.settings_startup_checkbox.toggled.connect(self._on_toggle_run_on_startup)
        self.settings_startup_hint = QLabel('Checking startup registration...')
        self.settings_startup_hint.setWordWrap(True)
        self.set_theme_role(self.settings_startup_hint, 'muted')
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(theme_hint)
        theme_layout.addWidget(self.settings_theme_combo)
        theme_layout.addWidget(self.settings_theme_preview)
        theme_layout.addSpacing(4)
        theme_layout.addWidget(clock_label)
        theme_layout.addWidget(clock_hint)
        theme_layout.addWidget(self.settings_timezone_combo)
        theme_layout.addWidget(self.settings_time_format_checkbox)
        theme_layout.addSpacing(4)
        theme_layout.addWidget(startup_label)
        theme_layout.addWidget(self.settings_startup_checkbox)
        theme_layout.addWidget(self.settings_startup_hint)

        actions_box = QGroupBox('User Data')
        self.set_theme_role(actions_box, 'panel')
        actions_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(14, 16, 14, 14)
        actions_layout.setSpacing(12)
        actions_intro = QLabel('Backup and restore your saved application state with a single JSON file. Export User Data writes one backup JSON, Import User Data restores from one backup JSON, and Clear removes saved user data while keeping dashboard chart slots intact.')
        actions_intro.setWordWrap(True)
        self.set_theme_role(actions_intro, 'muted')
        export_btn = QPushButton('Export User Data')
        self.set_theme_variant(export_btn, 'accent')
        export_btn.setMinimumHeight(32)
        export_btn.clicked.connect(self._on_export_user_data)
        import_btn = QPushButton('Import User Data')
        self.set_theme_variant(import_btn, 'accent')
        import_btn.setMinimumHeight(32)
        import_btn.clicked.connect(self._on_import_user_data)
        clear_btn = QPushButton('Clear All User Data')
        self.set_theme_variant(clear_btn, 'danger')
        clear_btn.setMinimumHeight(32)
        clear_btn.clicked.connect(self._on_clear_user_data)
        reset_cache_btn = QPushButton('Reset Cache')
        self.set_theme_variant(reset_cache_btn, 'danger')
        reset_cache_btn.setMinimumHeight(32)
        reset_cache_btn.clicked.connect(self._on_reset_cache)
        actions_layout.addWidget(actions_intro)
        actions_layout.addWidget(export_btn)
        actions_layout.addWidget(import_btn)
        actions_layout.addWidget(clear_btn)
        actions_layout.addWidget(reset_cache_btn)

        logs_box = QGroupBox('Application Logs')
        self.set_theme_role(logs_box, 'panel')
        logs_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.setContentsMargins(14, 16, 14, 14)
        logs_layout.setSpacing(10)
        logs_intro = QLabel('Live Python logger output for this app session. This mirrors the runtime messages you would normally watch in the IDE console.')
        logs_intro.setWordWrap(True)
        self.set_theme_role(logs_intro, 'muted')
        logs_toolbar = QHBoxLayout()
        logs_toolbar.setContentsMargins(0, 0, 0, 0)
        logs_toolbar.setSpacing(8)
        self.settings_log_meta_label = QLabel('Live session log | 0 entries')
        self.set_theme_role(self.settings_log_meta_label, 'muted')
        self.settings_log_pause_btn = QPushButton('Pause Auto-Scroll')
        self.settings_log_pause_btn.setCheckable(True)
        self.settings_log_pause_btn.clicked.connect(self._on_toggle_settings_logs_pause)
        self.settings_log_clear_btn = QPushButton('Clear')
        self.set_theme_variant(self.settings_log_clear_btn, 'danger')
        self.settings_log_clear_btn.clicked.connect(self._on_clear_settings_logs)
        logs_toolbar.addWidget(self.settings_log_meta_label, 1)
        logs_toolbar.addWidget(self.settings_log_pause_btn)
        logs_toolbar.addWidget(self.settings_log_clear_btn)
        self.settings_log_output = QPlainTextEdit()
        self.settings_log_output.setReadOnly(True)
        self.settings_log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.settings_log_output.setMinimumHeight(240)
        logs_layout.addWidget(logs_intro)
        logs_layout.addLayout(logs_toolbar)
        logs_layout.addWidget(self.settings_log_output, 1)
        shortcuts_box = self._build_settings_shortcuts_box()

        content_grid = QGridLayout()
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.setHorizontalSpacing(14)
        content_grid.setVerticalSpacing(14)
        content_grid.addWidget(theme_box, 0, 0)
        content_grid.addWidget(actions_box, 0, 1)
        content_grid.addWidget(shortcuts_box, 1, 0)
        content_grid.addWidget(logs_box, 1, 1)
        content_grid.setColumnStretch(0, 1)
        content_grid.setColumnStretch(1, 1)

        self.settings_status_label = QLabel('Ready')
        self.set_theme_role(self.settings_status_label, 'status_muted')
        layout.addLayout(header_layout)
        layout.addLayout(content_grid)
        layout.addWidget(self.settings_status_label)
        self._bind_settings_log_output(self.settings_log_output)
        self._refresh_settings_log_controls()
        self._refresh_run_on_startup_controls()
        logger.info('Settings page initialization complete.')

    def _build_settings_shortcuts_box(self) -> Any:
        """Build a Settings panel that documents the current app-wide keyboard shortcuts."""
        shortcuts_box = QGroupBox('Keyboard Shortcuts')
        self.set_theme_role(shortcuts_box, 'panel')
        shortcuts_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        shortcuts_layout = QVBoxLayout(shortcuts_box)
        shortcuts_layout.setContentsMargins(14, 16, 14, 14)
        shortcuts_layout.setSpacing(10)
        shortcuts_intro = QLabel('Reference for the app-wide keyboard shortcuts and the built-in tab picker opened with the backtick key.')
        shortcuts_intro.setWordWrap(True)
        self.set_theme_role(shortcuts_intro, 'muted')
        shortcuts_layout.addWidget(shortcuts_intro)
        table_widget = QWidget()
        table_layout = QGridLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setHorizontalSpacing(12)
        table_layout.setVerticalSpacing(8)
        shortcut_header = QLabel('Shortcut')
        behavior_header = QLabel('Behavior')
        self.set_theme_role(shortcut_header, 'section_title')
        self.set_theme_role(behavior_header, 'section_title')
        table_layout.addWidget(shortcut_header, 0, 0)
        table_layout.addWidget(behavior_header, 0, 1)
        for row_index, (shortcut, behavior) in enumerate(self.SETTINGS_SHORTCUT_ROWS, start=1):
            shortcut_label = QLabel(shortcut)
            shortcut_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shortcut_label.setMinimumWidth(110)
            self.set_theme_role(shortcut_label, 'badge')
            behavior_label = QLabel(behavior)
            behavior_label.setWordWrap(True)
            self.set_theme_role(behavior_label, 'muted')
            table_layout.addWidget(shortcut_label, row_index, 0, Qt.AlignmentFlag.AlignTop)
            table_layout.addWidget(behavior_label, row_index, 1)
        table_layout.setColumnStretch(0, 0)
        table_layout.setColumnStretch(1, 1)
        shortcuts_layout.addWidget(table_widget)
        return shortcuts_box

    def _set_settings_status(self, text: Any, status: Any='muted') -> None:
        """Update the settings page and window status messages together."""
        if hasattr(self, 'settings_status_label'):
            self.set_status_text(self.settings_status_label, text, status=str(status))
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=str(status))

    def _refresh_settings_log_controls(self) -> None:
        """Keep Settings log buttons aligned with the current capture state."""
        if hasattr(self, 'settings_log_pause_btn'):
            paused = bool(getattr(self, '_session_log_paused', False))
            self.settings_log_pause_btn.blockSignals(True)
            self.settings_log_pause_btn.setChecked(paused)
            self.settings_log_pause_btn.setText('Resume Auto-Scroll' if paused else 'Pause Auto-Scroll')
            self.settings_log_pause_btn.blockSignals(False)
            self.set_theme_variant(self.settings_log_pause_btn, 'accent' if paused else None)
        self._refresh_settings_log_status()

    def _on_toggle_settings_logs_pause(self, checked: Any=False) -> None:
        """Pause or resume live log updates in the Settings viewer."""
        self._set_session_log_paused(bool(checked))
        self._refresh_settings_log_controls()

    def _on_clear_settings_logs(self) -> None:
        """Clear the current session log buffer shown on the Settings page."""
        self._clear_session_logs()
        self._refresh_settings_log_controls()

    def _on_theme_selected(self, index: int) -> None:
        """Switch themes immediately from the Settings page."""
        if index < 0:
            return
        theme_id = self.settings_theme_combo.itemData(index)
        if not theme_id:
            return
        self.apply_theme_selection(str(theme_id))

    def _apply_settings_theme(self) -> None:
        """Refresh Settings-page theme-dependent widgets."""
        logger.info('Applying Settings page theme for %s.', self.theme().name)
        if hasattr(self, 'settings_theme_preview'):
            self.settings_theme_preview.setText(self.theme().name)
        if hasattr(self, 'settings_header_badge'):
            self.settings_header_badge.setText(f'Active Theme: {self.theme().name}')
        if hasattr(self, 'settings_theme_combo'):
            current_index = self.settings_theme_combo.findData(getattr(self, 'current_theme_id', self.theme_manager.current_theme_id))
            if current_index >= 0 and current_index != self.settings_theme_combo.currentIndex():
                self.settings_theme_combo.blockSignals(True)
                self.settings_theme_combo.setCurrentIndex(current_index)
                self.settings_theme_combo.blockSignals(False)
        if hasattr(self, 'settings_status_label'):
            self.set_status_text(self.settings_status_label, self.settings_status_label.text(), status=self.settings_status_label.property('bt_status') or 'muted')
        self._refresh_settings_log_controls()

    def _settings_cancel_pending_runtime_updates(self) -> None:
        """Stop delayed saves and invalidate in-flight refreshes before applying imported/reset state."""
        for timer_name in (
            '_portfolio_persist_timer',
            '_dashboard_state_persist_timer',
            '_session_cache_persist_timer',
            '_dashboard_refresh_timer',
            '_p14_auto_refresh_timer',
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    logger.exception('Unable to stop pending timer %s before settings state apply.', timer_name)
        if hasattr(self, '_dashboard_request_seq'):
            next_request_id = int(getattr(self, '_dashboard_request_seq', 0) or 0) + 1
            self._dashboard_request_seq = next_request_id
            self._dashboard_latest_request_id = next_request_id
        if hasattr(self, 'dashboard_load_btn'):
            self.dashboard_load_btn.setEnabled(True)

    def _refresh_run_on_startup_controls(self, status: Any=None) -> Any:
        """Refresh the Settings-page startup toggle from Windows registry state."""
        if not hasattr(self, 'settings_startup_checkbox'):
            return None
        if status is None:
            try:
                status = get_startup_registration_status()
            except Exception as exc:
                logger.exception('Unable to read run-on-startup state.')
                status = {
                    'supported': False,
                    'enabled': False,
                    'message': f'Run on startup status unavailable: {exc}',
                    'registered_command': '',
                    'registered_for_other_build': False,
                }
        self._settings_startup_status = status
        self.settings_startup_checkbox.blockSignals(True)
        self.settings_startup_checkbox.setChecked(bool(status.get('enabled', False)))
        self.settings_startup_checkbox.setEnabled(bool(status.get('supported', False)))
        self.settings_startup_checkbox.blockSignals(False)
        if hasattr(self, 'settings_startup_hint'):
            message = str(status.get('message', '') or '')
            registered_command = str(status.get('registered_command', '') or '').strip()
            if bool(status.get('registered_for_other_build', False)) and registered_command:
                message = f'{message}\nCurrent startup command: {registered_command}'
            self.settings_startup_hint.setText(message)
        return status

    def _on_toggle_run_on_startup(self, checked: bool) -> None:
        """Enable or disable packaged Windows startup registration."""
        action = 'enabled' if checked else 'disabled'
        try:
            status = set_run_on_startup(bool(checked))
        except Exception as exc:
            logger.exception('Run on startup update failed.')
            self._refresh_run_on_startup_controls()
            self._set_settings_status(f'Run on startup update failed: {exc}', 'negative')
            QMessageBox.critical(
                self,
                'Run on Startup Failed',
                f'Unable to update Windows startup registration.\n\n{exc}',
            )
            return
        self._refresh_run_on_startup_controls(status)
        self._set_settings_status(f'Run on startup {action}.', 'positive')

    def _sync_chart_slot_inputs(self) -> None:
        """Keep dashboard chart controls aligned with the saved workstation state."""
        if hasattr(self, 'dashboard_symbol_input'):
            symbol = str(getattr(self, 'dashboard_symbol', self.dashboard_chart_state.get('symbol', 'SPY')) or 'SPY').upper()
            self.dashboard_symbol_input.setText(symbol)

    def _reload_options_table(self) -> None:
        """Rebuild the options positions table from in-memory state."""
        if hasattr(self, '_page_initialized') and not self._page_initialized(page_attr='page4'):
            return
        table = getattr(self, 'p4_opt_table', None)
        if table is None:
            return
        table.blockSignals(True)
        table.setRowCount(0)
        table.blockSignals(False)
        if hasattr(self, '_p4_update_remove_options_button_state'):
            self._p4_update_remove_options_button_state()
        for pos in self.options_data:
            self._insert_options_row(pos)
        if hasattr(self, '_p4_apply_table_width_preferences'):
            self._p4_apply_table_width_preferences('options')
        self._update_total_pl_label()

    def _normalize_runtime_payload(self, payload: Any) -> Any:
        """Accept both legacy single-portfolio payloads and newer multi-portfolio payloads."""
        normalized = {
            'portfolio': payload.get('portfolio', {}) if isinstance(payload, dict) else {},
            'portfolio_tracker': payload.get('portfolio_tracker', {}) if isinstance(payload, dict) else {},
            'options_tracker': payload.get('options_tracker', []) if isinstance(payload, dict) else [],
            'net_worth': payload.get('net_worth', {'cash': [], 'debt': []}) if isinstance(payload, dict) else {'cash': [], 'debt': []},
            'portfolio_slots': [],
            'active_portfolio_index': 0,
            'main_portfolio_index': 0,
        }
        if not isinstance(normalized['portfolio'], dict):
            normalized['portfolio'] = {}
        if not isinstance(normalized['portfolio_tracker'], dict):
            normalized['portfolio_tracker'] = {}
        if not isinstance(normalized['options_tracker'], list):
            normalized['options_tracker'] = []
        if not isinstance(normalized['net_worth'], dict):
            normalized['net_worth'] = {'cash': [], 'debt': []}
        if not isinstance(payload, dict):
            return normalized
        raw_slots = payload.get('portfolio_slots', payload.get('portfolios', []))
        if isinstance(raw_slots, list):
            for index, slot in enumerate(raw_slots[:MAX_PORTFOLIOS]):
                if isinstance(slot, dict):
                    normalized['portfolio_slots'].append({
                        'id': int(slot.get('id', index)),
                        'name': str(slot.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                    })
        slot_count = max(len(normalized['portfolio_slots']), 1)
        for key in ('active_portfolio_index', 'main_portfolio_index'):
            try:
                normalized[key] = min(max(int(payload.get(key, normalized[key])), 0), slot_count - 1)
            except (TypeError, ValueError):
                normalized[key] = 0
        return normalized

    def _apply_runtime_user_data(self, payload: Any) -> None:
        """Apply imported or cleared data to the live UI state."""
        page2_initialized = self._page_initialized(page_attr='page2')
        page4_initialized = self._page_initialized(page_attr='page4')
        page6_initialized = self._page_initialized(page_attr='page6')
        page10_initialized = self._page_initialized(page_attr='page10')
        self._settings_cancel_pending_runtime_updates()
        if hasattr(self, '_clear_tab_session_cache'):
            self._clear_tab_session_cache(immediate=True)
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self._momentum_metrics_cache = {}
        self._momentum_metrics_fetching = {}
        self._portfolio_analytics_cache = {}
        self._portfolio_analytics_fetching = {}
        if isinstance(payload, dict) and isinstance(payload.get('portfolios'), dict):
            self.all_portfolios_state = save_all_portfolios_state(payload)
            self.main_portfolio_id = self.all_portfolios_state.get('main_portfolio_id', DEFAULT_MAIN_PORTFOLIO_ID)
            self.active_portfolio_id = self.all_portfolios_state.get('active_portfolio_id', self.main_portfolio_id)
        else:
            normalized = self._normalize_runtime_payload(payload)
            self.tickers = list(normalized.get('portfolio', {}).get('portfolio', []))
            self.chart_slots = list(normalized.get('portfolio', {}).get('chart_slots', self.chart_slots))
            self.tracker_data = dict(normalized.get('portfolio_tracker', {}))
            self.options_data = list(normalized.get('options_tracker', []))
            slot_specs = list(normalized.get('portfolio_slots', []))[:MAX_PORTFOLIOS]
            if not slot_specs:
                slot_specs = [{'id': 0, 'name': DEFAULT_PORTFOLIO_NAMES.get(DEFAULT_MAIN_PORTFOLIO_ID, DEFAULT_MAIN_PORTFOLIO_ID)}]
            portfolio_order = PORTFOLIO_IDS[:len(slot_specs)]
            main_index = min(max(int(normalized.get('main_portfolio_index', 0)), 0), len(portfolio_order) - 1)
            active_index = min(max(int(normalized.get('active_portfolio_index', main_index)), 0), len(portfolio_order) - 1)
            self.main_portfolio_id = portfolio_order[main_index]
            self.active_portfolio_id = portfolio_order[active_index]
            self.all_portfolios_state = {
                'main_portfolio_id': self.main_portfolio_id,
                'active_portfolio_id': self.active_portfolio_id,
                'portfolio_order': list(portfolio_order),
                'portfolios': {},
            }
            for index, portfolio_id in enumerate(portfolio_order):
                slot_name = str(slot_specs[index].get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id))
                self.all_portfolios_state['portfolios'][portfolio_id] = {
                    'name': slot_name,
                    'portfolio': list(self.tickers) if portfolio_id == self.main_portfolio_id else [],
                    'chart_slots': list(self.chart_slots) if portfolio_id == self.main_portfolio_id else list(DEFAULT_CHART_SLOTS),
                    'portfolio_tracker': dict(self.tracker_data) if portfolio_id == self.main_portfolio_id else {},
                    'options_tracker': list(self.options_data) if portfolio_id == self.main_portfolio_id else [],
                }
            self._persist_all_portfolios()
        self.fundamentals_page_state = save_fundamentals_page_settings(
            payload.get('fundamentals_page', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS)
        ) if isinstance(payload, dict) else save_fundamentals_page_settings(DEFAULT_FUNDAMENTALS_PAGE_SETTINGS)
        fundamentals_page_state = dict(self.fundamentals_page_state)
        self.p2_selected_configuration = str(
            fundamentals_page_state.get('selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
            or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
        ).strip().lower()
        self.p2_custom_selections_by_ticker = dict(
            fundamentals_page_state.get('custom_selections_by_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['custom_selections_by_ticker'])
        )
        self.chart_page_state = save_chart_page_settings(payload.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)) if isinstance(payload, dict) else save_chart_page_settings(DEFAULT_CHART_PAGE_SETTINGS)
        chart_page_state = dict(self.chart_page_state)
        self.multi_charts_state = save_multi_charts_settings(payload.get('multi_charts', DEFAULT_MULTI_CHARTS_SETTINGS)) if isinstance(payload, dict) else save_multi_charts_settings(DEFAULT_MULTI_CHARTS_SETTINGS)
        multi_charts_state = dict(self.multi_charts_state)
        self.p10_symbol = str(chart_page_state.get('symbol', 'SPY') or 'SPY').upper()
        self.p10_timeframe_label = str(chart_page_state.get('timeframe_label', '1 Day') or '1 Day')
        self.p10_compare_interval_label = str(chart_page_state.get('compare_interval_label', '1 Day') or '1 Day')
        self.p10_compare_range_label = str(chart_page_state.get('compare_range_label', '5Y') or '5Y')
        self.p10_custom_watchlist = list(chart_page_state.get('watchlist', []))
        self.p10_compare_symbols = list(chart_page_state.get('compare_symbols', []))
        self.p10_compare_presets = list(chart_page_state.get('compare_presets', []))
        if hasattr(self, '_p10_initial_multi_interval_labels'):
            self.p10_multi_interval_labels = self._p10_initial_multi_interval_labels(chart_page_state.get('multi_interval_labels', []))
        else:
            self.p10_multi_interval_labels = list(chart_page_state.get('multi_interval_labels', []))
        self.p10_active_indicators = list(chart_page_state.get('indicators', ['Volume', '200 MA']))
        self.p10_auto_follow = bool(chart_page_state.get('auto', True))
        self._mc_custom_symbols = list(multi_charts_state.get('custom_symbols', []))
        self._mc_saved_order = list(multi_charts_state.get('order', []))
        if hasattr(self, '_p10_clear_compare_plot_items'):
            try:
                self._p10_clear_compare_plot_items()
            except Exception:
                pass
        self._p10_compare_series_cache = {}
        self._p10_compare_plot_items = {}
        self._p10_compare_label_items = {}
        self._p10_compare_render_signature = None
        self._p10_multi_interval_cache = {}
        self.p10_compare_df = None
        self.p10_compare_errors = []
        self._p10_chart_dirty = True
        self._p10_compare_dirty = True
        if hasattr(self, '_p10_compare_target_preset_name'):
            self._p10_compare_target_preset_name = None
        self.dashboard_chart_state = save_dashboard_chart_settings(payload.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)) if isinstance(payload, dict) else save_dashboard_chart_settings(DEFAULT_DASHBOARD_CHART_SETTINGS)
        dashboard_chart_state = dict(self.dashboard_chart_state)
        self.dashboard_symbol = str(dashboard_chart_state.get('symbol', 'SPY') or 'SPY').upper()
        self.dashboard_timeframe_label = str(dashboard_chart_state.get('timeframe_label', '1 Day') or '1 Day')
        self.dashboard_active_indicators = list(dashboard_chart_state.get('indicators', ['Volume', '200 MA']))
        self.dashboard_auto_follow = bool(dashboard_chart_state.get('auto', True))
        self.portfolio_metrics_state = save_portfolio_metrics_settings(payload.get('portfolio_metrics', DEFAULT_PORTFOLIO_METRICS_SETTINGS)) if isinstance(payload, dict) else save_portfolio_metrics_settings(DEFAULT_PORTFOLIO_METRICS_SETTINGS)
        portfolio_metrics_state = dict(self.portfolio_metrics_state)
        self.p4_metrics_benchmark_symbol = str(
            portfolio_metrics_state.get('benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
            or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']
        ).upper().strip()
        self.p4_metrics_lookback_key = str(
            portfolio_metrics_state.get('lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
            or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
        ).strip().lower()
        self.networth_data = dict(payload.get('net_worth', {'cash': [], 'debt': []})) if isinstance(payload, dict) else {'cash': [], 'debt': []}
        self.last_data = None
        self._sync_after_portfolio_change(refresh_main=False)
        if page4_initialized and hasattr(self, 'p4_metrics_benchmark_input'):
            self.p4_metrics_benchmark_input.setText(self.p4_metrics_benchmark_symbol)
        if page4_initialized and hasattr(self, 'p4_metrics_lookback_combo'):
            index = self.p4_metrics_lookback_combo.findData(self.p4_metrics_lookback_key)
            if index >= 0:
                self.p4_metrics_lookback_combo.setCurrentIndex(index)
        if (
            page4_initialized
            and
            hasattr(self, 'p4_content_tabs')
            and self.p4_content_tabs.currentWidget() is getattr(self, 'p4_metrics_page', None)
            and hasattr(self, '_p4_refresh_portfolio_metrics_view')
        ):
            self._p4_refresh_portfolio_metrics_view(force=True)
        if page10_initialized and hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(self.p10_symbol)
        if page10_initialized and hasattr(self, 'p10_symbol_label'):
            self.p10_symbol_label.setText(self.p10_symbol)
        if page10_initialized and hasattr(self, 'p10_multi_interval_symbol_input'):
            self.p10_multi_interval_symbol_input.setText(self.p10_symbol)
        if page10_initialized and hasattr(self, 'p10_multi_interval_symbol_label'):
            self.p10_multi_interval_symbol_label.setText(self.p10_symbol)
        if page10_initialized and hasattr(self, '_p10_update_timeframe_button_styles'):
            self._p10_update_timeframe_button_styles()
        if page10_initialized and hasattr(self, '_p10_update_auto_button_style'):
            self._p10_update_auto_button_style()
        if page10_initialized and hasattr(self, '_p10_update_indicator_button_styles'):
            self._p10_update_indicator_button_styles()
        if page10_initialized and hasattr(self, '_p10_update_multi_interval_button_styles'):
            self._p10_update_multi_interval_button_styles()
        if page10_initialized and hasattr(self, '_p10_rebuild_watchlists'):
            self._p10_rebuild_watchlists()
        if page10_initialized and hasattr(self, '_p10_refresh_compare_symbol_list'):
            self._p10_refresh_compare_symbol_list()
        if page10_initialized and getattr(self, '_mc_initialized', False):
            self._mc_sync_grid(self._mc_get_active_symbols())
            if self._p10_active_subtab_key() == 'multicharts':
                self._mc_on_show()
        if page10_initialized and hasattr(self, '_p10_render_indicator_panels'):
            self._p10_render_indicator_panels()
        if page10_initialized and hasattr(self, '_p10_refresh_active_subtab'):
            self._p10_refresh_active_subtab(force=True)
        if hasattr(self, 'dashboard_symbol_input'):
            self.dashboard_symbol_input.setText(self.dashboard_symbol)
        if hasattr(self, 'dashboard_symbol_label'):
            self.dashboard_symbol_label.setText(self.dashboard_symbol)
        if hasattr(self, '_dashboard_update_timeframe_button_styles'):
            self._dashboard_update_timeframe_button_styles()
        if hasattr(self, '_dashboard_update_auto_button_style'):
            self._dashboard_update_auto_button_style()
        if hasattr(self, '_dashboard_update_indicator_button_styles'):
            self._dashboard_update_indicator_button_styles()
        if hasattr(self, '_dashboard_render_indicator_panels'):
            self._dashboard_render_indicator_panels()
        if hasattr(self, '_dashboard_apply_splitter_sizes'):
            self._dashboard_apply_splitter_sizes()
        self._sync_chart_slot_inputs()
        self.port_table.setRowCount(0)
        self.target_table.setRowCount(0)
        self.news_table.setRowCount(0)
        if page4_initialized and hasattr(self, 'p4_table'):
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)
            self._reload_options_table()
        if page6_initialized and hasattr(self, '_p6_populate_tables'):
            self._p6_populate_tables()
        if page2_initialized and hasattr(self, '_p2_apply_runtime_state'):
            self._p2_apply_runtime_state()
        if page4_initialized and hasattr(self, 'p4_total_label'):
            self.p4_total_label.setText('Total:  $0.00  USD')
        if page4_initialized and hasattr(self, '_p4_refresh_portfolio_selector'):
            self._p4_refresh_portfolio_selector()
        self.refresh_data()
        if getattr(self, '_startup_show_completed', False) and hasattr(self, '_p14_start_auto_refresh'):
            self._p14_start_auto_refresh()

    def _settings_default_user_data_path(self) -> str:
        """Return the default JSON path used by export and import dialogs."""
        return str(Path.home().joinpath('budget_terminal_user_data.json'))

    def _settings_choose_import_file(self) -> str | None:
        """Prompt for a single JSON backup file to restore from."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Select User Data Backup',
            self._settings_default_user_data_path(),
            'JSON files (*.json)',
        )
        return str(path or '').strip() or None

    def _settings_user_data_summary(self, path: Any, payload: Any) -> str:
        """Build the import preview text shown before overwrite."""
        data = payload if isinstance(payload, dict) else {}
        portfolio_order = data.get('portfolio_order', [])
        if isinstance(portfolio_order, list) and portfolio_order:
            portfolio_count = len(portfolio_order)
        else:
            portfolio_count = len(data.get('portfolios', {})) if isinstance(data.get('portfolios'), dict) else 0
        return '\n'.join([
            f'Source: {path}',
            f'Exported at: {str(data.get("exported_at", "") or "-")}',
            f'App version: {str(data.get("app_version", "") or "-")}',
            f'Portfolio count: {portfolio_count}',
        ])

    def _settings_confirm_import_user_data(self, path: Any, payload: Any) -> bool:
        """Confirm a JSON user-data import before overwriting saved state."""
        prompt = QMessageBox(self)
        prompt.setWindowTitle('Import User Data')
        prompt.setIcon(QMessageBox.Icon.Warning)
        prompt.setText('Importing will overwrite current saved user data.')
        prompt.setInformativeText(self._settings_user_data_summary(path, payload))
        import_btn = prompt.addButton('Import User Data', QMessageBox.ButtonRole.AcceptRole)
        prompt.addButton(QMessageBox.StandardButton.Cancel)
        prompt.exec()
        return prompt.clickedButton() is import_btn

    def _settings_flush_pending_user_data_saves(self) -> None:
        """Persist debounce-buffered user-data state before export, import, or clear."""
        if hasattr(self, '_persist_all_portfolios'):
            self._persist_all_portfolios(immediate=True)
        if hasattr(self, '_persist_dashboard_state'):
            self._persist_dashboard_state(immediate=True)

    def _on_export_user_data(self) -> None:
        """Export current user data into a single JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Export User Data',
            self._settings_default_user_data_path(),
            'JSON files (*.json)',
        )
        export_path = str(path or '').strip()
        if not export_path:
            self._set_settings_status('Export cancelled.')
            return
        if not export_path.lower().endswith('.json'):
            export_path = f'{export_path}.json'
        try:
            self._settings_flush_pending_user_data_saves()
            export_user_data_backup(export_path)
        except Exception as exc:
            self._set_settings_status(f'Export failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Export Failed', f'Unable to export user data.\n\n{exc}')
            return
        self._set_settings_status(f'User data exported to {export_path}', 'positive')
        QMessageBox.information(
            self,
            'Export Complete',
            f'User data exported successfully.\n\nFile: {export_path}'
        )

    def _on_import_user_data(self) -> None:
        """Import user data from a single JSON backup file."""
        path = self._settings_choose_import_file()
        if not path:
            self._set_settings_status('Import cancelled.')
            return
        try:
            payload = load_user_data_backup(path)
        except Exception as exc:
            self._set_settings_status(f'Import failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Import Failed', f'Unable to read the selected backup file.\n\n{exc}')
            return
        if not self._settings_confirm_import_user_data(path, payload):
            self._set_settings_status('Import cancelled.')
            return
        try:
            self._settings_flush_pending_user_data_saves()
            rollback_path = create_rollback_backup_file(reason='before_import')
            self._settings_cancel_pending_runtime_updates()
            normalized = apply_user_data_backup(payload)
            self._apply_runtime_user_data(normalized)
        except Exception as exc:
            self._set_settings_status(f'Import failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Import Failed', f'Unable to apply imported data.\n\n{exc}')
            return
        self._set_settings_status(f'User data imported from {path}', 'positive')
        QMessageBox.information(
            self,
            'Import Complete',
            f'User data imported successfully.\n\n'
            f'Source: {path}\n'
            f'Rollback backup: {rollback_path or "-"}'
        )

    def _on_clear_user_data(self) -> None:
        """Clear persisted user data after confirmation."""
        reply = QMessageBox.question(self, 'Clear All User Data', 'This will remove saved portfolio, tracker, personal finance, and options data. Dashboard chart slots will be kept. Continue?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            self._set_settings_status('Clear cancelled.')
            return
        try:
            self._settings_flush_pending_user_data_saves()
            self._settings_cancel_pending_runtime_updates()
            normalized = reset_user_data(self.chart_slots)
            self._apply_runtime_user_data(normalized)
        except Exception as exc:
            self._set_settings_status(f'Clear failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Clear Failed', f'Unable to clear user data.\n\n{exc}')
            return
        self._set_settings_status('All user data cleared.', 'positive')
        QMessageBox.information(self, 'Clear Complete', 'All saved user data has been cleared.')

    def _settings_clear_cache_directory(self, folder_name: str) -> bool:
        """Remove one known cache directory under the app data root."""
        folder = user_data_dir().joinpath(str(folder_name or '').strip())
        if not folder.exists():
            return False
        if folder.is_dir():
            shutil.rmtree(folder)
            return True
        folder.unlink()
        return True

    def _settings_clear_worker_memory_caches(self) -> None:
        """Flush shared worker-level memory caches that survive until app restart."""
        with DataWorker._details_cache_lock:
            DataWorker._stock_details_cache.clear()
            DataWorker._macro_news_cache.clear()
            DataWorker._non_chart_snapshot_cache.clear()
        with calendar_worker._ECONOMIC_EVENTS_CACHE_LOCK:
            calendar_worker._ECONOMIC_EVENTS_MEMORY_CACHE.clear()
        with calendar_worker._MARKET_HOLIDAY_CACHE_LOCK:
            calendar_worker._MARKET_HOLIDAY_MEMORY_CACHE.clear()

    def _settings_clear_runtime_cache_state(self) -> None:
        """Reset in-memory caches and loaded market payloads without touching saved user data."""
        self._settings_clear_worker_memory_caches()
        self._mktcap_cache = {}
        self._mktcap_cache_ts = {}
        self._mktcap_inflight_tickers = set()
        self._mktcap_queued_tickers = set()
        self._option_chain_memory_cache = {}
        self._options_expiry_memory_cache = {}
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self._momentum_metrics_cache = {}
        self._momentum_metrics_fetching = {}
        self._portfolio_analytics_cache = {}
        self._portfolio_analytics_fetching = {}
        self._p13_aum_cache = {}
        self.p10_chart_df = None
        self.p10_chart_stats = {}
        self._p10_chart_rows = []
        self.p10_rsi_series = None
        self.p10_rsi_ma_series = None
        self.p10_ma200_series = None
        self._p10_compare_series_cache = {}
        self._p10_multi_interval_cache = {}
        self.p10_compare_df = None
        self.p10_compare_errors = []
        self.p10_multi_interval_frames = {}
        self.last_data = None
        for plot_name in ('p10_main_plot', 'p10_volume_plot', 'p10_rsi_plot'):
            plot = getattr(self, plot_name, None)
            if plot is not None:
                try:
                    plot.clear()
                except Exception:
                    pass
        self.p10_candle_item = None
        self.p10_ma_line_item = None
        self.p10_avg_cost_line = None
        self.p10_last_price_line = None
        self.p10_volume_item = None
        self.p10_rsi_line_item = None
        self.p10_rsi_ma_line_item = None
        self.p10_rsi_upper_line = None
        self.p10_rsi_lower_line = None
        self._p10_overlay_items = {}
        if hasattr(self, '_p10_clear_compare_plot_items'):
            try:
                self._p10_clear_compare_plot_items()
            except Exception:
                pass
        if hasattr(self, '_p10_clear_multi_interval_plot'):
            try:
                self._p10_clear_multi_interval_plot()
            except Exception:
                pass
        if hasattr(self, '_dashboard_clear_chart'):
            self._dashboard_clear_chart(getattr(self, 'dashboard_symbol', 'Chart'))

    def _on_reset_cache(self) -> None:
        """Clear the persisted market-data cache after confirmation."""
        reply = QMessageBox.question(
            self,
            'Reset Cache',
            'This will remove cached stock, chart, and options market data only. Saved portfolio, tracker, and settings files will be kept. Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._set_settings_status('Cache reset cancelled.')
            return
        cache = self._get_cache_manager()
        cache_path = Path(cache.db_path)
        try:
            cleared_sqlite_cache = bool(cache.clear_all())
            cleared_dirs = []
            for folder_name in self.SETTINGS_CACHE_DIR_NAMES:
                if self._settings_clear_cache_directory(folder_name):
                    cleared_dirs.append(folder_name)
            self._settings_clear_runtime_cache_state()
            self._cache_manager = CacheManager()
        except Exception as exc:
            logger.error('Reset cache failed for %s: %s', cache_path, exc)
            self._set_settings_status(f'Cache reset failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Reset Cache Failed', f'Unable to reset cache.\n\n{exc}')
            return
        if cleared_sqlite_cache or cleared_dirs:
            logger.info('Market cache cleared at %s. Extra cache dirs removed: %s', cache_path, cleared_dirs)
            self._set_settings_status('All cached app data cleared.', 'positive')
            QMessageBox.information(
                self,
                'Reset Cache Complete',
                'All cached app data has been cleared. Saved user data was not changed.\n\nFresh market data will be fetched again on the next refresh.',
            )
            return
        logger.info('Reset cache requested, but no cache artifacts were present at %s.', cache_path)
        self._set_settings_status('Cache already clear.', 'positive')
        QMessageBox.information(
            self,
            'Reset Cache Complete',
            'No cache artifacts were present. Saved user data was not changed.',
        )
