from __future__ import annotations
from typing import Any

from budget_terminal_app.compat import *
from budget_terminal_app.paths import user_data_dir
from budget_terminal_app.startup_integration import get_startup_registration_status, set_run_on_startup
from budget_terminal_app.startup_metrics import clear_startup_metrics_history, load_startup_metrics_history
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.settings_separator_lines = []

        header_frame = self._build_settings_header()
        theme_box = self._build_settings_preferences_box()
        actions_box = self._build_settings_user_data_box()
        data_health_box = self._build_settings_data_health_box()
        logs_box = self._build_settings_logs_box()
        shortcuts_box = self._build_settings_shortcuts_box()
        startup_box = self._build_settings_startup_performance_box()
        content_grid = self._build_settings_content_grid(
            theme_box,
            actions_box,
            shortcuts_box,
            data_health_box,
            logs_box,
            startup_box,
        )

        self.settings_status_label = QLabel('Ready')
        self.set_theme_role(self.settings_status_label, 'status_muted')
        self.settings_status_label.setMinimumHeight(18)
        layout.addWidget(header_frame)
        layout.addLayout(content_grid)
        layout.addWidget(self.settings_status_label)
        self._style_settings_log_output()
        self._style_settings_data_health_report()
        self._style_settings_startup_history_output()
        self._bind_settings_log_output(self.settings_log_output)
        self._refresh_data_health_views()
        self._refresh_settings_log_controls()
        self._refresh_run_on_startup_controls()
        self._refresh_startup_performance_views()
        logger.info('Settings page initialization complete.')

    def _build_settings_header(self) -> QFrame:
        """Build the Settings page header panel."""
        header_frame = QFrame()
        self.set_theme_role(header_frame, 'panel')
        header_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(6)
        title = QLabel('Settings')
        self.set_theme_role(title, 'page_title')
        description = QLabel('Tune the app workspace, manage saved data, and inspect the current session without leaving Budget Terminal.')
        description.setWordWrap(True)
        self.set_theme_role(description, 'muted')
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_row.addWidget(title, 1)
        self.settings_header_badge = QLabel('Live theme switching enabled')
        self.settings_header_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.settings_header_badge, 'accent')
        self.settings_header_badge.setMinimumHeight(24)
        self.settings_header_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        title_row.addWidget(self.settings_header_badge, 0, Qt.AlignmentFlag.AlignRight)
        header_layout.addLayout(title_row)
        header_layout.addWidget(description)
        return header_frame

    def _build_settings_preferences_box(self) -> QGroupBox:
        """Build Settings controls for theme, clock, and Windows startup preferences."""
        theme_box = QGroupBox('Preferences')
        self.set_theme_role(theme_box, 'panel')
        theme_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        theme_layout = QVBoxLayout(theme_box)
        theme_layout.setContentsMargins(12, 12, 12, 10)
        theme_layout.setSpacing(6)
        self.settings_theme_combo = QComboBox()
        self.settings_theme_combo.setObjectName('settingsThemeCombo')
        self.settings_theme_combo.setAccessibleName('Theme selector')
        self.settings_theme_combo.setToolTip('Theme selector')
        self.set_theme_role(self.settings_theme_combo, 'theme_selector')
        self.settings_theme_combo.setMinimumHeight(30)
        self.settings_theme_combo.setMinimumWidth(230)
        self.settings_theme_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        available_themes = self.theme_manager.available_themes()
        for theme_id, theme in available_themes.items():
            self.settings_theme_combo.addItem(theme.name, theme_id)
        longest_theme_name = max((len(theme.name) for theme in available_themes.values()), default=12)
        self.settings_theme_combo.setMinimumContentsLength(longest_theme_name + 2)
        self.settings_theme_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.settings_theme_combo.setMaxVisibleItems(max(4, len(available_themes)))
        theme_menu = self.settings_theme_combo.view()
        self.set_theme_role(theme_menu, 'theme_menu')
        theme_menu.setMinimumWidth(max(260, longest_theme_name * 10 + 88))
        theme_menu.setTextElideMode(Qt.TextElideMode.ElideNone)
        theme_menu.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if hasattr(theme_menu, 'setUniformItemSizes'):
            theme_menu.setUniformItemSizes(True)
        self.settings_theme_combo.setEnabled(len(available_themes) > 1)
        current_index = self.settings_theme_combo.findData(getattr(self, 'current_theme_id', self.theme_manager.current_theme_id))
        if current_index >= 0:
            self.settings_theme_combo.setCurrentIndex(current_index)
        self.settings_theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        self.settings_theme_preview = QLabel(self.theme_id_to_name(getattr(self, 'current_theme_id', self.theme_manager.current_theme_id)))
        self.set_theme_role(self.settings_theme_preview, 'theme_preview')
        self.settings_theme_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.settings_theme_preview.setMinimumHeight(28)
        self.settings_theme_preview.setMinimumWidth(150)
        self.settings_timezone_combo = QComboBox()
        self.settings_timezone_combo.setMinimumHeight(28)
        self.settings_timezone_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for name, _ in self._tz_choices:
            self.settings_timezone_combo.addItem(name)
        self.settings_timezone_combo.setCurrentIndex(self._current_clock_timezone_index())
        self.settings_timezone_combo.currentIndexChanged.connect(self._on_settings_timezone_changed)
        self.settings_time_format_checkbox = QCheckBox('Use 12-hour time in the top-bar clock')
        self.settings_time_format_checkbox.setChecked(bool(getattr(self, '_time_12h', True)))
        self.settings_time_format_checkbox.toggled.connect(lambda checked: self._toggle_time_format() if bool(checked) != bool(getattr(self, '_time_12h', False)) else None)
        self.settings_startup_checkbox = QCheckBox('Run Budget Terminal when I sign in to Windows')
        self.settings_startup_checkbox.toggled.connect(self._on_toggle_run_on_startup)
        self.settings_startup_hint = QLabel('Checking startup registration...')
        self.settings_startup_hint.setWordWrap(True)
        self.set_theme_role(self.settings_startup_hint, 'muted')
        theme_layout.addWidget(self._settings_section_header('Appearance', 'Choose the visual theme used across charts, tables, and controls.'))
        theme_row_controls = self._settings_transparent_widget()
        theme_row_layout = QHBoxLayout(theme_row_controls)
        theme_row_layout.setContentsMargins(0, 0, 0, 0)
        theme_row_layout.setSpacing(8)
        theme_row_layout.addWidget(self.settings_theme_combo, 1)
        theme_row_layout.addWidget(self.settings_theme_preview)
        theme_layout.addWidget(theme_row_controls)
        theme_layout.addWidget(self._settings_separator())
        theme_layout.addWidget(self._settings_section_header('Clock', 'Set the top-bar timezone and display format.'))
        theme_layout.addWidget(self.settings_timezone_combo)
        theme_layout.addWidget(self.settings_time_format_checkbox)
        theme_layout.addWidget(self._settings_separator())
        theme_layout.addWidget(self._settings_section_header('Windows Startup', 'Control whether the packaged app starts when you sign in.'))
        theme_layout.addWidget(self.settings_startup_checkbox)
        theme_layout.addWidget(self.settings_startup_hint)
        return theme_box

    def _settings_action_button(self, text: str, variant: str, slot: Any) -> QPushButton:
        """Create a Settings action button with the standard height and variant."""
        button = QPushButton(text)
        self.set_theme_variant(button, variant)
        button.setMinimumHeight(30)
        button.clicked.connect(slot)
        return button

    def _build_settings_user_data_box(self) -> QGroupBox:
        """Build Settings controls for user-data maintenance actions."""
        actions_box = QGroupBox('User Data')
        self.set_theme_role(actions_box, 'panel')
        actions_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(12, 12, 12, 10)
        actions_layout.setSpacing(6)
        actions_layout.addWidget(self._settings_section_header('Backups and Maintenance', 'Export or restore one JSON backup file, clear saved user data, or reset cached market data.'))
        export_btn = self._settings_action_button('Export User Data', 'accent', self._on_export_user_data)
        import_btn = self._settings_action_button('Import User Data', 'accent', self._on_import_user_data)
        clear_btn = self._settings_action_button('Clear All User Data', 'danger', self._on_clear_user_data)
        reset_cache_btn = self._settings_action_button('Reset Cache', 'danger', self._on_reset_cache)
        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        action_grid.addWidget(export_btn, 0, 0)
        action_grid.addWidget(import_btn, 0, 1)
        action_grid.addWidget(clear_btn, 1, 0)
        action_grid.addWidget(reset_cache_btn, 1, 1)
        actions_layout.addLayout(action_grid)
        return actions_box

    def _build_settings_data_health_box(self) -> QGroupBox:
        """Build Settings data-health status and report controls."""
        data_health_box = QGroupBox('Data Health')
        self.set_theme_role(data_health_box, 'panel')
        data_health_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        data_health_layout = QVBoxLayout(data_health_box)
        data_health_layout.setContentsMargins(12, 12, 12, 10)
        data_health_layout.setSpacing(6)
        data_health_layout.addWidget(self._settings_section_header('Market Data Status', 'Session-only view of stale data, cache fallback, missing prices, and API issues.'))
        data_health_toolbar = QHBoxLayout()
        data_health_toolbar.setContentsMargins(0, 0, 0, 0)
        data_health_toolbar.setSpacing(8)
        self.settings_data_health_summary_label = QLabel('Data health: OK')
        self.set_theme_role(self.settings_data_health_summary_label, 'status_muted')
        self.settings_data_health_refresh_btn = QPushButton('Refresh')
        self.settings_data_health_refresh_btn.setMinimumHeight(28)
        self.settings_data_health_refresh_btn.clicked.connect(self._on_refresh_data_health_report)
        self.settings_data_health_copy_btn = QPushButton('Copy Report')
        self.settings_data_health_copy_btn.setMinimumHeight(28)
        self.set_theme_variant(self.settings_data_health_copy_btn, 'accent')
        self.settings_data_health_copy_btn.clicked.connect(self._on_copy_data_health_report)
        data_health_toolbar.addWidget(self.settings_data_health_summary_label, 1)
        data_health_toolbar.addWidget(self.settings_data_health_refresh_btn)
        data_health_toolbar.addWidget(self.settings_data_health_copy_btn)
        self.settings_data_health_report = QPlainTextEdit()
        self.settings_data_health_report.setReadOnly(True)
        self.settings_data_health_report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.settings_data_health_report.setMinimumHeight(130)
        data_health_layout.addLayout(data_health_toolbar)
        data_health_layout.addWidget(self.settings_data_health_report, 1)
        return data_health_box

    def _build_settings_logs_box(self) -> QGroupBox:
        """Build Settings live application-log controls."""
        logs_box = QGroupBox('Application Logs')
        self.set_theme_role(logs_box, 'panel')
        logs_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.setContentsMargins(12, 12, 12, 10)
        logs_layout.setSpacing(6)
        logs_intro = self._settings_section_header('Session Output', 'Live Python logger output for this app session.')
        logs_toolbar = QHBoxLayout()
        logs_toolbar.setContentsMargins(0, 0, 0, 0)
        logs_toolbar.setSpacing(8)
        self.settings_log_meta_label = QLabel('Live session log | 0 entries')
        self.set_theme_role(self.settings_log_meta_label, 'muted')
        self.settings_log_pause_btn = QPushButton('Pause Auto-Scroll')
        self.settings_log_pause_btn.setCheckable(True)
        self.settings_log_pause_btn.setMinimumHeight(28)
        self.settings_log_pause_btn.clicked.connect(self._on_toggle_settings_logs_pause)
        self.settings_log_clear_btn = QPushButton('Clear')
        self.settings_log_clear_btn.setMinimumHeight(28)
        self.set_theme_variant(self.settings_log_clear_btn, 'danger')
        self.settings_log_clear_btn.clicked.connect(self._on_clear_settings_logs)
        logs_toolbar.addWidget(self.settings_log_meta_label, 1)
        logs_toolbar.addWidget(self.settings_log_pause_btn)
        logs_toolbar.addWidget(self.settings_log_clear_btn)
        self.settings_log_output = QPlainTextEdit()
        self.settings_log_output.setReadOnly(True)
        self.settings_log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.settings_log_output.setMinimumHeight(180)
        logs_layout.addWidget(logs_intro)
        logs_layout.addLayout(logs_toolbar)
        logs_layout.addWidget(self.settings_log_output, 1)
        return logs_box

    def _build_settings_startup_performance_box(self) -> QGroupBox:
        """Build Settings controls for startup timing metrics."""
        startup_box = QGroupBox('Startup Performance')
        self.set_theme_role(startup_box, 'panel')
        startup_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        startup_layout = QVBoxLayout(startup_box)
        startup_layout.setContentsMargins(12, 12, 12, 10)
        startup_layout.setSpacing(6)
        startup_layout.addWidget(self._settings_section_header('Launch Timing', 'Current launch milestones and recent startup history.'))

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.settings_startup_summary_label = QLabel('Current launch: collecting timings')
        self.set_theme_role(self.settings_startup_summary_label, 'muted')
        self.settings_startup_refresh_btn = QPushButton('Refresh')
        self.settings_startup_refresh_btn.setMinimumHeight(28)
        self.settings_startup_refresh_btn.clicked.connect(self._on_refresh_startup_performance)
        self.settings_startup_clear_btn = QPushButton('Clear History')
        self.settings_startup_clear_btn.setMinimumHeight(28)
        self.set_theme_variant(self.settings_startup_clear_btn, 'danger')
        self.settings_startup_clear_btn.clicked.connect(self._on_clear_startup_metrics_history)
        toolbar.addWidget(self.settings_startup_summary_label, 1)
        toolbar.addWidget(self.settings_startup_refresh_btn)
        toolbar.addWidget(self.settings_startup_clear_btn)
        startup_layout.addLayout(toolbar)

        stage_widget = self._settings_transparent_widget()
        stage_layout = QGridLayout(stage_widget)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setHorizontalSpacing(10)
        stage_layout.setVerticalSpacing(8)
        headers = ('Stage', 'Status', 'Time', 'Detail')
        for column, text in enumerate(headers):
            label = QLabel(text)
            self.set_theme_role(label, 'section_title')
            stage_layout.addWidget(label, 0, column)
        self.settings_startup_stage_rows = {}
        for row, (stage_key, stage_label) in enumerate((
            ('first_ui', 'First UI'),
            ('session_restore', 'Session Restore'),
            ('page_warmup', 'Page Warmup'),
            ('cache_warmup', 'Cache Warmup'),
        ), start=1):
            name_label = QLabel(stage_label)
            status_label = QLabel('Pending')
            time_label = QLabel('-')
            detail_label = QLabel('-')
            detail_label.setWordWrap(True)
            self.set_theme_role(name_label, 'muted')
            self.set_theme_role(status_label, 'status_muted')
            self.set_theme_role(time_label, 'accent')
            self.set_theme_role(detail_label, 'muted')
            stage_layout.addWidget(name_label, row, 0)
            stage_layout.addWidget(status_label, row, 1)
            stage_layout.addWidget(time_label, row, 2)
            stage_layout.addWidget(detail_label, row, 3)
            self.settings_startup_stage_rows[stage_key] = {
                'status': status_label,
                'time': time_label,
                'detail': detail_label,
            }
        stage_layout.setColumnStretch(0, 0)
        stage_layout.setColumnStretch(1, 0)
        stage_layout.setColumnStretch(2, 0)
        stage_layout.setColumnStretch(3, 1)
        startup_layout.addWidget(stage_widget)

        startup_layout.addWidget(self._settings_section_header('Recent Launches', 'Newest launch records saved on this device.'))
        self.settings_startup_history_output = QPlainTextEdit()
        self.settings_startup_history_output.setReadOnly(True)
        self.settings_startup_history_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.settings_startup_history_output.setMinimumHeight(90)
        startup_layout.addWidget(self.settings_startup_history_output)
        return startup_box

    def _build_settings_content_grid(
        self,
        theme_box: QGroupBox,
        actions_box: QGroupBox,
        shortcuts_box: QGroupBox,
        data_health_box: QGroupBox,
        logs_box: QGroupBox,
        startup_box: QGroupBox,
    ) -> QGridLayout:
        """Arrange the Settings page panels in the existing two-column grid."""
        content_grid = QGridLayout()
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.setHorizontalSpacing(4)
        content_grid.setVerticalSpacing(4)
        content_grid.addWidget(actions_box, 0, 0)
        content_grid.addWidget(data_health_box, 0, 1)
        content_grid.addWidget(shortcuts_box, 1, 0)
        content_grid.addWidget(theme_box, 2, 0)
        content_grid.addWidget(logs_box, 1, 1, 2, 1)
        content_grid.addWidget(startup_box, 3, 0, 1, 2)
        content_grid.setColumnStretch(0, 1)
        content_grid.setColumnStretch(1, 1)
        return content_grid

    def _settings_transparent_widget(self) -> QWidget:
        """Create a Settings helper widget that does not paint a panel background."""
        widget = QWidget()
        widget.setStyleSheet('background: transparent; border: 0;')
        return widget

    def _settings_section_header(self, title: str, description: str) -> QWidget:
        """Create a compact Settings section title and hint block."""
        section = self._settings_transparent_widget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(3)
        title_label = QLabel(title)
        self.set_theme_role(title_label, 'section_title')
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        self.set_theme_role(description_label, 'muted')
        section_layout.addWidget(title_label)
        section_layout.addWidget(description_label)
        return section

    def _settings_separator(self) -> QFrame:
        """Create a subtle divider for Settings panels."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet(f'background: {self.theme_color("panel_border")}; max-height: 1px; border: 0;')
        self.settings_separator_lines.append(line)
        return line

    def _style_settings_log_output(self) -> None:
        """Apply the active theme to the Settings log console."""
        if not hasattr(self, 'settings_log_output') or self.settings_log_output is None:
            return
        self.settings_log_output.setStyleSheet(
            f'QPlainTextEdit {{ background: {self.theme_color("input_bg")}; '
            f'color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("input_border")}; '
            f'border-radius: 5px; padding: 8px; '
            f'font-family: Consolas, "Cascadia Mono", monospace; font-size: 11px; }}'
        )

    def _style_settings_data_health_report(self) -> None:
        """Apply the active theme to the Settings data-health report."""
        if not hasattr(self, 'settings_data_health_report') or self.settings_data_health_report is None:
            return
        self.settings_data_health_report.setStyleSheet(
            f'QPlainTextEdit {{ background: {self.theme_color("input_bg")}; '
            f'color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("input_border")}; '
            f'border-radius: 5px; padding: 8px; '
            f'font-family: Consolas, "Cascadia Mono", monospace; font-size: 11px; }}'
        )

    def _style_settings_startup_history_output(self) -> None:
        """Apply the active theme to the Settings startup history output."""
        if not hasattr(self, 'settings_startup_history_output') or self.settings_startup_history_output is None:
            return
        self.settings_startup_history_output.setStyleSheet(
            f'QPlainTextEdit {{ background: {self.theme_color("input_bg")}; '
            f'color: {self.theme_color("text_secondary")}; '
            f'border: 1px solid {self.theme_color("input_border")}; '
            f'border-radius: 5px; padding: 8px; '
            f'font-family: Consolas, "Cascadia Mono", monospace; font-size: 11px; }}'
        )

    def _build_settings_shortcuts_box(self) -> Any:
        """Build a Settings panel that documents the current app-wide keyboard shortcuts."""
        shortcuts_box = QGroupBox('Keyboard Shortcuts')
        self.set_theme_role(shortcuts_box, 'panel')
        shortcuts_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        shortcuts_layout = QVBoxLayout(shortcuts_box)
        shortcuts_layout.setContentsMargins(12, 12, 12, 10)
        shortcuts_layout.setSpacing(6)
        shortcuts_layout.addWidget(self._settings_section_header('Navigation', 'Reference for app-wide shortcuts and the built-in tab picker.'))
        table_widget = self._settings_transparent_widget()
        table_layout = QGridLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setHorizontalSpacing(10)
        table_layout.setVerticalSpacing(10)
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
            shortcut_label.setMinimumHeight(24)
            self.set_theme_role(shortcut_label, 'accent')
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

    def _on_refresh_data_health_report(self) -> None:
        """Refresh the copyable data-health report."""
        if hasattr(self, '_refresh_data_health_views'):
            self._refresh_data_health_views()
        self._set_settings_status('Data health report refreshed.', 'positive')

    def _on_copy_data_health_report(self) -> None:
        """Copy the current data-health report to the clipboard."""
        report = self._build_data_health_report() if hasattr(self, '_build_data_health_report') else ''
        QApplication.clipboard().setText(report)
        if hasattr(self, 'settings_data_health_report'):
            self.settings_data_health_report.setPlainText(report)
        self._set_settings_status('Data health report copied to clipboard.', 'positive')

    def _settings_startup_format_seconds(self, value: Any) -> str:
        """Return a compact timing label for Settings startup metrics."""
        profiler = getattr(self, '_startup_profiler', None)
        formatter = getattr(profiler, 'format_seconds', None)
        if callable(formatter):
            return formatter(value)
        if value is None:
            return '-'
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return '-'
        if seconds < 0:
            return '-'
        if seconds < 1:
            return f'{seconds * 1000:.0f} ms'
        return f'{seconds:.2f} s'

    def _settings_startup_status_role(self, status: Any) -> str:
        """Return a status-text role for one startup metric state."""
        normalized = str(status or '').strip().lower()
        if normalized == 'complete':
            return 'positive'
        if normalized == 'running':
            return 'info'
        if normalized == 'failed':
            return 'negative'
        return 'muted'

    def _settings_startup_stage_seconds(self, stage_key: str, stage: Any) -> Any:
        """Return the display seconds for one current startup stage."""
        data = stage if isinstance(stage, dict) else {}
        if stage_key == 'first_ui':
            return data.get('completed_seconds') or data.get('duration_seconds')
        if str(data.get('status', '') or '') == 'pending':
            return None
        return data.get('duration_seconds')

    def _settings_startup_stage_detail(self, stage: Any) -> str:
        """Return a compact stage detail string."""
        data = stage if isinstance(stage, dict) else {}
        detail = str(data.get('detail', '') or '').strip()
        count = data.get('count')
        if count is not None:
            try:
                count_text = str(int(count))
            except (TypeError, ValueError):
                count_text = str(count)
            if count_text:
                detail = f'{detail} ({count_text})' if detail else count_text
        return detail or '-'

    def _settings_startup_format_timestamp(self, value: Any) -> str:
        """Return a local timestamp label for startup history rows."""
        text = str(value or '').strip()
        if not text:
            return '-'
        try:
            parsed = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
            parsed = parsed.astimezone()
            return parsed.strftime('%b %d %H:%M:%S')
        except Exception:
            return text

    def _settings_startup_history_line(self, launch: Any, current_launch_id: str) -> str:
        """Format one persisted launch for the Settings startup history view."""
        data = launch if isinstance(launch, dict) else {}
        stages = data.get('stages', {}) if isinstance(data.get('stages', {}), dict) else {}
        launch_id = str(data.get('launch_id', '') or '')
        current_text = ' current' if launch_id == current_launch_id else ''
        total = self._settings_startup_format_seconds(data.get('total_seconds'))
        first_ui = self._settings_startup_format_seconds((stages.get('first_ui') or {}).get('completed_seconds'))
        restore = self._settings_startup_format_seconds((stages.get('session_restore') or {}).get('duration_seconds'))
        page_warmup = self._settings_startup_format_seconds((stages.get('page_warmup') or {}).get('duration_seconds'))
        cache_warmup = self._settings_startup_format_seconds((stages.get('cache_warmup') or {}).get('duration_seconds'))
        status = str(data.get('status', 'running') or 'running')
        started = self._settings_startup_format_timestamp(data.get('started_at'))
        return (
            f'{started} | {status}{current_text} | total {total} | '
            f'UI {first_ui} | restore {restore} | page {page_warmup} | cache {cache_warmup}'
        )

    def _refresh_startup_performance_views(self) -> None:
        """Refresh Settings startup timing controls from current and persisted metrics."""
        if not hasattr(self, 'settings_startup_stage_rows'):
            return
        current = self._startup_metrics_snapshot() if hasattr(self, '_startup_metrics_snapshot') else {}
        stages = current.get('stages', {}) if isinstance(current.get('stages', {}), dict) else {}
        for stage_key, labels in self.settings_startup_stage_rows.items():
            stage = stages.get(stage_key, {})
            status = str(stage.get('status', 'pending') if isinstance(stage, dict) else 'pending').strip().lower() or 'pending'
            status_label = labels.get('status')
            if status_label is not None:
                self.set_status_text(status_label, status.replace('_', ' ').title(), status=self._settings_startup_status_role(status))
            time_label = labels.get('time')
            if time_label is not None:
                time_label.setText(self._settings_startup_format_seconds(self._settings_startup_stage_seconds(stage_key, stage)))
            detail_label = labels.get('detail')
            if detail_label is not None:
                detail_label.setText(self._settings_startup_stage_detail(stage))
        if hasattr(self, 'settings_startup_summary_label'):
            status = str(current.get('status', 'running') or 'running')
            total = self._settings_startup_format_seconds(current.get('total_seconds'))
            self.settings_startup_summary_label.setText(f'Current launch: {status} | total {total}')
        if hasattr(self, 'settings_startup_history_output'):
            try:
                history = load_startup_metrics_history()
            except Exception:
                history = {'launches': []}
            launches = list(history.get('launches', []) or [])
            current_id = str(current.get('launch_id', '') or '')
            for index, launch in enumerate(launches):
                if isinstance(launch, dict) and str(launch.get('launch_id', '') or '') == current_id:
                    launches[index] = current
                    break
            lines = [self._settings_startup_history_line(launch, current_id) for launch in launches[:10]]
            self.settings_startup_history_output.setPlainText('\n'.join(lines) if lines else 'No startup history recorded yet.')

    def _on_refresh_startup_performance(self) -> None:
        """Refresh startup timing controls on demand."""
        self._refresh_startup_performance_views()
        self._set_settings_status('Startup performance refreshed.', 'positive')

    def _on_clear_startup_metrics_history(self) -> None:
        """Clear persisted startup timing history while keeping current in-memory metrics."""
        try:
            clear_startup_metrics_history()
            if hasattr(self, '_persist_startup_metrics_current'):
                self._persist_startup_metrics_current()
        except Exception as exc:
            logger.exception('Unable to clear startup timing history.')
            self._set_settings_status(f'Startup history clear failed: {exc}', 'negative')
            return
        self._refresh_startup_performance_views()
        self._set_settings_status('Startup history cleared.', 'positive')

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
        if hasattr(self, 'settings_data_health_summary_label'):
            self.set_status_text(
                self.settings_data_health_summary_label,
                self.settings_data_health_summary_label.text(),
                status=self.settings_data_health_summary_label.property('bt_status') or 'muted',
            )
        for line in getattr(self, 'settings_separator_lines', []):
            line.setStyleSheet(f'background: {self.theme_color("panel_border")}; max-height: 1px; border: 0;')
        self._style_settings_log_output()
        self._style_settings_data_health_report()
        self._style_settings_startup_history_output()
        self._refresh_settings_log_controls()
        self._refresh_startup_performance_views()
        if hasattr(self, '_refresh_data_health_views'):
            self._refresh_data_health_views()

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
            'net_worth': normalize_networth_data(payload.get('net_worth')) if isinstance(payload, dict) else default_networth_data(),
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
            normalized['net_worth'] = default_networth_data()
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
        self.networth_data = normalize_networth_data(payload.get('net_worth')) if isinstance(payload, dict) else default_networth_data()
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
            DataWorker._other_news_cache = None
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
