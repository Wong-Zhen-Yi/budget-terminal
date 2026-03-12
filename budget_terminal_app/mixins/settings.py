from __future__ import annotations
from typing import Any
from ..compat import *


class SettingsMixin:

    def init_page9(self) -> None:
        """Build the Settings page UI."""
        layout = QVBoxLayout(self.page9)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel('<b>Settings</b>')
        title.setStyleSheet('font-size: 20px; color: white;')
        description = QLabel('Manage saved portfolio, tracker, personal finance, and options data. Export creates one backup JSON file, import restores it, and clear removes saved user data while keeping dashboard chart slots.')
        description.setWordWrap(True)
        description.setStyleSheet('color: #bbbbbb; font-size: 12px;')
        actions_box = QGroupBox('User Data')
        actions_box.setStyleSheet('QGroupBox { font-weight: bold; color: #cccccc; border: 1px solid #333; border-radius: 6px; padding-top: 12px; }QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }')
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(12, 14, 12, 12)
        actions_layout.setSpacing(10)
        export_btn = QPushButton('Export User Data')
        export_btn.clicked.connect(self._on_export_user_data)
        import_btn = QPushButton('Import User Data')
        import_btn.clicked.connect(self._on_import_user_data)
        clear_btn = QPushButton('Clear All User Data')
        clear_btn.setStyleSheet('QPushButton { background: #3a1a1a; color: #f44336; border: 1px solid #6a2a2a; border-radius: 4px; padding: 6px 12px; font-weight: bold; }QPushButton:hover { background: #521818; }')
        clear_btn.clicked.connect(self._on_clear_user_data)
        actions_layout.addWidget(export_btn)
        actions_layout.addWidget(import_btn)
        actions_layout.addWidget(clear_btn)
        self.settings_status_label = QLabel('Ready')
        self.settings_status_label.setStyleSheet('color: #888888; font-size: 11px;')
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(actions_box)
        layout.addWidget(self.settings_status_label)
        layout.addStretch()

    def _set_settings_status(self, text: Any, color: Any='#888888') -> None:
        """Update the settings page and window status messages together."""
        if hasattr(self, 'settings_status_label'):
            self.settings_status_label.setText(str(text))
            self.settings_status_label.setStyleSheet(f'color: {color}; font-size: 11px;')
        if hasattr(self, 'status_bar'):
            self.status_bar.setText(str(text))
            self.status_bar.setStyleSheet(f'color: {color}; font-size: 11px; padding: 2px;')

    def _sync_chart_slot_inputs(self) -> None:
        """Keep chart input fields aligned with the current saved chart slots."""
        for i, slot in enumerate(self.chart_slots):
            if i < len(self.chart_inputs):
                self.chart_inputs[i].setText(slot)

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
        self.networth_data = dict(payload.get('net_worth', {'cash': [], 'debt': []})) if isinstance(payload, dict) else {'cash': [], 'debt': []}
        self.last_data = None
        self._sync_after_portfolio_change(refresh_main=False)
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
            self._set_settings_status(f'Export failed: {exc}', '#f44336')
            QMessageBox.critical(self, 'Export Failed', f'Unable to export user data.\n\n{exc}')
            return
        self._set_settings_status(f'User data exported to {path}', '#80ff80')
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
            self._set_settings_status(f'Import failed: {exc}', '#f44336')
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
            self._set_settings_status(f'Import failed: {exc}', '#f44336')
            QMessageBox.critical(self, 'Import Failed', f'Unable to apply imported data.\n\n{exc}')
            return
        self._set_settings_status(f'Imported user data from {path}', '#80ff80')
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
            self._set_settings_status(f'Clear failed: {exc}', '#f44336')
            QMessageBox.critical(self, 'Clear Failed', f'Unable to clear user data.\n\n{exc}')
            return
        self._set_settings_status('All user data cleared.', '#80ff80')
        QMessageBox.information(self, 'Clear Complete', 'All saved user data has been cleared.')
