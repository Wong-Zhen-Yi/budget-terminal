from __future__ import annotations
from importlib import resources
from typing import Any

from PyQt6.QtGui import QImage, QPixmap
from budget_terminal_app.compat import *


class SettingsMixin:
    SETTINGS_DONATION_URL = 'https://buymeacoffee.com/BudgetTerminal'
    SETTINGS_CREATOR_IMAGE_SIZE = 208

    def init_page9(self) -> None:
        """Build the Settings page UI."""
        logger.info('Settings page initialization started.')
        layout = QVBoxLayout(self.page9)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(6)
        title = QLabel('Settings')
        self.set_theme_role(title, 'page_title')
        description = QLabel('Manage saved portfolio, tracker, personal finance, and options data. Export creates one backup JSON file, import restores it, and clear removes saved user data while keeping dashboard chart slots.')
        description.setWordWrap(True)
        self.set_theme_role(description, 'muted')
        title_col.addWidget(title)
        title_col.addWidget(description)
        self.settings_header_badge = QLabel('Live theme switching enabled')
        self.settings_header_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.settings_header_badge, 'badge')
        self.settings_header_badge.setMinimumHeight(34)
        self.settings_header_badge.setMinimumWidth(220)
        header_row.addLayout(title_col, 1)
        header_row.addWidget(self.settings_header_badge, 0, Qt.AlignmentFlag.AlignTop)

        theme_box = QGroupBox('Appearance')
        self.set_theme_role(theme_box, 'panel')
        theme_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(theme_hint)
        theme_layout.addWidget(self.settings_theme_combo)
        theme_layout.addWidget(self.settings_theme_preview)

        actions_box = QGroupBox('User Data')
        self.set_theme_role(actions_box, 'panel')
        actions_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(14, 16, 14, 14)
        actions_layout.setSpacing(12)
        actions_intro = QLabel('Backup and restore your saved application state. Clear removes user data but keeps dashboard chart slots intact.')
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

        note_box = QGroupBox("Creator's Note")
        self.set_theme_role(note_box, 'panel')
        note_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        note_layout = QVBoxLayout(note_box)
        note_layout.setContentsMargins(14, 16, 14, 14)
        note_layout.setSpacing(10)
        note_title = QLabel('Built for retail investors')
        self.set_theme_role(note_title, 'section_title')
        note_body = QLabel("Wong here, I made this with Claude, Codex and Gemini CLI tools. Some of the data might not be accurate because of yfinance API limitations so always double check with the official sources.")
        note_body.setWordWrap(True)
        self.set_theme_role(note_body, 'muted')
        note_footer = QLabel(f'If you find this terminal useful donate here. Thanks! <a href="{self.SETTINGS_DONATION_URL}">buymeacoffee.com/BudgetTerminal</a>')
        note_footer.setOpenExternalLinks(True)
        self.set_theme_role(note_footer, 'accent')
        self.settings_creator_image_label = QLabel()
        self.settings_creator_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.settings_creator_image_label.setMinimumSize(self.SETTINGS_CREATOR_IMAGE_SIZE, self.SETTINGS_CREATOR_IMAGE_SIZE)
        self.settings_creator_image_label.setMaximumSize(self.SETTINGS_CREATOR_IMAGE_SIZE, self.SETTINGS_CREATOR_IMAGE_SIZE)
        self.settings_creator_image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.settings_creator_image_label.setScaledContents(False)
        self.settings_creator_image_pixmap = None
        self._refresh_settings_creator_image()
        note_layout.addWidget(note_title)
        note_layout.addWidget(note_body)
        note_layout.addWidget(note_footer)
        note_layout.addWidget(self.settings_creator_image_label, 0, Qt.AlignmentFlag.AlignCenter)
        note_layout.addStretch()

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
        logs_layout.addWidget(logs_intro)
        logs_layout.addLayout(logs_toolbar)
        logs_layout.addWidget(self.settings_log_output, 1)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(theme_box, 0, 0)
        grid.addWidget(actions_box, 0, 1)
        grid.addWidget(note_box, 1, 0)
        grid.addWidget(logs_box, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        self.settings_status_label = QLabel('Ready')
        self.set_theme_role(self.settings_status_label, 'status_muted')
        layout.addLayout(header_row)
        layout.addLayout(grid)
        layout.addWidget(self.settings_status_label)
        layout.addStretch()
        self._bind_settings_log_output(self.settings_log_output)
        self._refresh_settings_log_controls()
        logger.info('Settings page initialization complete.')

    def _settings_creator_image_path(self) -> Any:
        """Return the bundled Creator's Note image asset path."""
        return resources.files('budget_terminal_app').joinpath('assets').joinpath('qr-code.png')

    def _load_settings_image_pixmap_from_bytes(self, raw_bytes: bytes, source: str) -> Any:
        """Decode the Creator's Note image bytes with explicit format hints."""
        if not raw_bytes:
            logger.warning("Settings creator image decode skipped because %s returned no data.", source)
            return None
        pixmap = QPixmap()
        if pixmap.loadFromData(raw_bytes, 'PNG'):
            logger.info("Settings creator image decoded from %s via QPixmap.loadFromData.", source)
            return pixmap
        qt_image = QImage.fromData(raw_bytes, 'PNG')
        if not qt_image.isNull():
            logger.info("Settings creator image decoded from %s via QImage.fromData.", source)
            return QPixmap.fromImage(qt_image)
        logger.warning("Settings creator image decode failed for %s.", source)
        return None

    def _load_settings_creator_image_pixmap(self) -> Any:
        """Load the bundled Creator's Note image asset."""
        image_path = self._settings_creator_image_path()
        logger.info("Loading Settings creator image from %s.", image_path)
        try:
            raw_bytes = image_path.read_bytes()
        except OSError:
            logger.exception("Settings creator image could not be read from %s.", image_path)
            return None
        pixmap = self._load_settings_image_pixmap_from_bytes(raw_bytes, f'asset {image_path.name}')
        if pixmap is not None:
            logger.info("Settings creator image loaded successfully from %s.", image_path)
            return pixmap
        logger.warning("Settings creator image decode failed for %s after byte-based fallback.", image_path)
        return None

    def _build_settings_creator_image(self) -> Any:
        """Load and scale the Creator's Note image asset."""
        image_pixmap = self._load_settings_creator_image_pixmap()
        if image_pixmap is None or image_pixmap.isNull():
            raise RuntimeError(
                "Unable to render the Creator's Note image. Verify budget_terminal_app/assets/qr-code.png exists and is a readable PNG."
            )
        return image_pixmap.scaled(
            self.SETTINGS_CREATOR_IMAGE_SIZE,
            self.SETTINGS_CREATOR_IMAGE_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _refresh_settings_creator_image(self) -> None:
        """Show the Creator's Note image when available, otherwise a clear fallback message."""
        if not hasattr(self, 'settings_creator_image_label'):
            return
        try:
            creator_image = self._build_settings_creator_image()
        except Exception as exc:
            logger.exception("Settings creator image refresh failed.")
            creator_image = None
            error_message = str(exc)
        else:
            error_message = ''
        if creator_image is not None:
            self.set_theme_role(self.settings_creator_image_label, None)
            self.settings_creator_image_label.clear()
            self.settings_creator_image_label.setStyleSheet('')
            self.settings_creator_image_pixmap = creator_image
            self.settings_creator_image_label.setPixmap(creator_image)
            logger.info(
                "Settings creator image rendered at label size %sx%s with pixmap size %sx%s.",
                self.settings_creator_image_label.width(),
                self.settings_creator_image_label.height(),
                creator_image.width(),
                creator_image.height(),
            )
            return
        self.settings_creator_image_pixmap = None
        self.settings_creator_image_label.setPixmap(QPixmap())
        self.settings_creator_image_label.setText(error_message or "Creator image unavailable: asset load failed.")
        self.set_theme_role(self.settings_creator_image_label, 'badge')
        logger.warning("Settings creator image fallback text shown: %s", self.settings_creator_image_label.text())

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
        if hasattr(self, 'settings_creator_image_label'):
            self._refresh_settings_creator_image()
        if hasattr(self, 'settings_status_label'):
            self.set_status_text(self.settings_status_label, self.settings_status_label.text(), status=self.settings_status_label.property('bt_status') or 'muted')
        self._refresh_settings_log_controls()

    def _sync_chart_slot_inputs(self) -> None:
        """Keep dashboard chart controls aligned with the saved workstation state."""
        if hasattr(self, 'dashboard_symbol_input'):
            symbol = str(getattr(self, 'dashboard_symbol', self.dashboard_chart_state.get('symbol', 'SPY')) or 'SPY').upper()
            self.dashboard_symbol_input.setText(symbol)

    def _reload_options_table(self) -> None:
        """Rebuild the options positions table from in-memory state."""
        table = self.p4_opt_table
        table.blockSignals(True)
        table.setRowCount(0)
        table.blockSignals(False)
        for pos in self.options_data:
            self._insert_options_row(pos)
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
            for index, slot in enumerate(raw_slots[:3]):
                if isinstance(slot, dict):
                    normalized['portfolio_slots'].append({
                        'id': int(slot.get('id', index)),
                        'name': str(slot.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                    })
        for key in ('active_portfolio_index', 'main_portfolio_index'):
            try:
                normalized[key] = min(max(int(payload.get(key, normalized[key])), 0), 2)
            except (TypeError, ValueError):
                normalized[key] = 0
        return normalized

    def _apply_runtime_user_data(self, payload: Any) -> None:
        """Apply imported or cleared data to the live UI state."""
        if isinstance(payload, dict) and isinstance(payload.get('portfolios'), dict):
            self.all_portfolios_state = save_all_portfolios_state(payload)
            self.main_portfolio_id = self.all_portfolios_state.get('main_portfolio_id', PORTFOLIO_IDS[0])
            self.active_portfolio_id = self.all_portfolios_state.get('active_portfolio_id', self.main_portfolio_id)
        else:
            normalized = self._normalize_runtime_payload(payload)
            self.tickers = list(normalized.get('portfolio', {}).get('portfolio', []))
            self.chart_slots = list(normalized.get('portfolio', {}).get('chart_slots', self.chart_slots))
            self.tracker_data = dict(normalized.get('portfolio_tracker', {}))
            self.options_data = list(normalized.get('options_tracker', []))
            self.main_portfolio_id = self._portfolio_id_from_index(normalized.get('main_portfolio_index', 0))
            self.active_portfolio_id = self._portfolio_id_from_index(normalized.get('active_portfolio_index', normalized.get('main_portfolio_index', 0)))
            self.all_portfolios_state = {
                'main_portfolio_id': self.main_portfolio_id,
                'active_portfolio_id': self.active_portfolio_id,
                'portfolios': {},
            }
            for portfolio_id in PORTFOLIO_IDS:
                self.all_portfolios_state['portfolios'][portfolio_id] = {
                    'name': DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id),
                    'portfolio': list(self.tickers) if portfolio_id == self.main_portfolio_id else [],
                    'chart_slots': list(self.chart_slots) if portfolio_id == self.main_portfolio_id else list(DEFAULT_CHART_SLOTS),
                    'portfolio_tracker': dict(self.tracker_data) if portfolio_id == self.main_portfolio_id else {},
                    'options_tracker': list(self.options_data) if portfolio_id == self.main_portfolio_id else [],
                }
            self._persist_all_portfolios()
        self.chart_page_state = save_chart_page_settings(payload.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)) if isinstance(payload, dict) else save_chart_page_settings(DEFAULT_CHART_PAGE_SETTINGS)
        chart_page_state = dict(self.chart_page_state)
        self.p10_symbol = str(chart_page_state.get('symbol', 'SPY') or 'SPY').upper()
        self.p10_timeframe_label = str(chart_page_state.get('timeframe_label', '1 Day') or '1 Day')
        self.p10_custom_watchlist = list(chart_page_state.get('watchlist', []))
        self.p10_active_indicators = list(chart_page_state.get('indicators', ['Volume', '200 MA']))
        self.p10_auto_follow = bool(chart_page_state.get('auto', True))
        self.dashboard_chart_state = save_dashboard_chart_settings(payload.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)) if isinstance(payload, dict) else save_dashboard_chart_settings(DEFAULT_DASHBOARD_CHART_SETTINGS)
        dashboard_chart_state = dict(self.dashboard_chart_state)
        self.dashboard_symbol = str(dashboard_chart_state.get('symbol', 'SPY') or 'SPY').upper()
        self.dashboard_timeframe_label = str(dashboard_chart_state.get('timeframe_label', '1 Day') or '1 Day')
        self.dashboard_active_indicators = list(dashboard_chart_state.get('indicators', ['Volume', '200 MA']))
        self.dashboard_auto_follow = bool(dashboard_chart_state.get('auto', True))
        self.networth_data = dict(payload.get('net_worth', {'cash': [], 'debt': []})) if isinstance(payload, dict) else {'cash': [], 'debt': []}
        self.last_data = None
        self._sync_after_portfolio_change(refresh_main=False)
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(self.p10_symbol)
        if hasattr(self, 'p10_symbol_label'):
            self.p10_symbol_label.setText(self.p10_symbol)
        if hasattr(self, '_p10_update_timeframe_button_styles'):
            self._p10_update_timeframe_button_styles()
        if hasattr(self, '_p10_update_auto_button_style'):
            self._p10_update_auto_button_style()
        if hasattr(self, '_p10_update_indicator_button_styles'):
            self._p10_update_indicator_button_styles()
        if hasattr(self, '_p10_rebuild_watchlists'):
            self._p10_rebuild_watchlists()
        if hasattr(self, '_p10_render_indicator_panels'):
            self._p10_render_indicator_panels()
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
        self.p4_table.blockSignals(True)
        self.p4_table.setRowCount(0)
        self.p4_table.blockSignals(False)
        self._reload_options_table()
        self._p6_populate_tables()
        self.p4_total_label.setText('Total:  $0.00  USD')
        if hasattr(self, '_p4_refresh_portfolio_selector'):
            self._p4_refresh_portfolio_selector()
        self.refresh_data()

    def _on_export_user_data(self) -> None:
        """Export current user data to a single JSON file."""
        default_name = f"budget_terminal_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self, 'Export User Data', str(Path.home() / default_name), 'JSON Files (*.json)')
        if not path:
            self._set_settings_status('Export cancelled.')
            return
        try:
            export_user_data_backup(path)
        except Exception as exc:
            self._set_settings_status(f'Export failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Export Failed', f'Unable to export user data.\n\n{exc}')
            return
        self._set_settings_status(f'User data exported to {path}', 'positive')
        QMessageBox.information(self, 'Export Complete', f'User data exported successfully.\n\n{path}')

    def _on_import_user_data(self) -> None:
        """Import user data from a previously exported backup file."""
        path, _ = QFileDialog.getOpenFileName(self, 'Import User Data', str(Path.home()), 'JSON Files (*.json)')
        if not path:
            self._set_settings_status('Import cancelled.')
            return
        try:
            payload = load_user_data_backup(path)
        except Exception as exc:
            self._set_settings_status(f'Import failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Import Failed', f'Unable to import user data.\n\n{exc}')
            return
        reply = QMessageBox.question(self, 'Import User Data', 'Importing will overwrite current saved user data. Continue?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            self._set_settings_status('Import cancelled.')
            return
        try:
            normalized = apply_user_data_backup(payload)
            self._apply_runtime_user_data(normalized)
        except Exception as exc:
            self._set_settings_status(f'Import failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Import Failed', f'Unable to apply imported data.\n\n{exc}')
            return
        self._set_settings_status(f'Imported user data from {path}', 'positive')
        QMessageBox.information(self, 'Import Complete', 'User data imported successfully.')

    def _on_clear_user_data(self) -> None:
        """Clear persisted user data after confirmation."""
        reply = QMessageBox.question(self, 'Clear All User Data', 'This will remove saved portfolio, tracker, personal finance, and options data. Dashboard chart slots will be kept. Continue?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            self._set_settings_status('Clear cancelled.')
            return
        try:
            normalized = reset_user_data(self.chart_slots)
            self._apply_runtime_user_data(normalized)
        except Exception as exc:
            self._set_settings_status(f'Clear failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Clear Failed', f'Unable to clear user data.\n\n{exc}')
            return
        self._set_settings_status('All user data cleared.', 'positive')
        QMessageBox.information(self, 'Clear Complete', 'All saved user data has been cleared.')

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
        cache_path = user_data_path('budget_cache.db')
        try:
            existed = cache_path.exists()
            if existed:
                cache_path.unlink()
            self._mktcap_cache = {}
            self._return_metrics_cache = {}
            self._return_metrics_fetching = {}
        except Exception as exc:
            self._set_settings_status(f'Cache reset failed: {exc}', 'negative')
            QMessageBox.critical(self, 'Reset Cache Failed', f'Unable to reset cache.\n\n{exc}')
            return
        if existed:
            self._set_settings_status('Market cache cleared.', 'positive')
            QMessageBox.information(self, 'Reset Cache Complete', 'Cached market data has been cleared.')
            return
        self._set_settings_status('Cache already clear.', 'positive')
        QMessageBox.information(self, 'Reset Cache Complete', 'No cache file was present. Cached market data is already clear.')
