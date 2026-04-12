from __future__ import annotations
from typing import Any
from ..compat import *

_P4_POSITIONS_SPLITTER_CONFIG = user_data_path('p4_splitter.json')
_P4_STOCK_TABLE_WIDTHS_CONFIG = user_data_path('p4_stock_table_widths.json')
_P4_OPTIONS_TABLE_WIDTHS_CONFIG = user_data_path('p4_options_table_widths.json')
_P4_DEFAULT_POSITIONS_SPLITTER_SIZES = [7, 4]
_P4_STOCK_SECTION_MIN_HEIGHT = 260
_P4_OPTIONS_SECTION_MIN_HEIGHT = 180
_P4_TABLE_FIXED_ACTION_WIDTH = 36
_P4_TABLE_RESIZE_DEBOUNCE_MS = 120

class PortfolioSetupMixin:

    def _p4_get_portfolio_slots(self) -> Any:
        """Return a normalized ordered list of existing portfolio slot dicts."""
        slots = []
        raw = getattr(self, 'portfolio_slots', None)
        if isinstance(raw, list):
            for index, entry in enumerate(raw[:MAX_PORTFOLIOS]):
                if isinstance(entry, dict):
                    slots.append({
                        'id': int(entry.get('id', index)),
                        'portfolio_id': str(entry.get('portfolio_id', entry.get('id', index)) or entry.get('id', index)),
                        'name': str(entry.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}'),
                    })
        if not slots:
            slots.append({'id': 0, 'portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID, 'name': 'Portfolio 1'})
        return slots

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
        """Refresh portfolio tab labels and action copy."""
        if not hasattr(self, 'p4_portfolio_tabs'):
            return
        slots = self._p4_get_portfolio_slots()
        active_index = self._p4_get_active_portfolio_index()
        main_index = self._p4_get_main_portfolio_index()
        self.p4_portfolio_tabs.blockSignals(True)
        while self.p4_portfolio_tabs.count() > len(slots):
            self.p4_portfolio_tabs.removeTab(self.p4_portfolio_tabs.count() - 1)
        while self.p4_portfolio_tabs.count() < len(slots):
            self.p4_portfolio_tabs.addTab(QWidget(), '')
        for index, slot in enumerate(slots):
            label = str(slot.get('name', f'Portfolio {index + 1}') or f'Portfolio {index + 1}')
            if index == main_index:
                label = f'{label} *'
            self.p4_portfolio_tabs.setTabText(index, label)
        self.p4_portfolio_tabs.setCurrentIndex(active_index)
        self.p4_portfolio_tabs.blockSignals(False)
        if hasattr(self, 'p4_main_portfolio_label'):
            self.p4_main_portfolio_label.setText(f'Main Portfolio: {self._p4_portfolio_name(main_index)}')
        if hasattr(self, 'p4_set_main_btn'):
            if active_index == main_index:
                self.p4_set_main_btn.setText('Main Portfolio')
                self.p4_set_main_btn.setEnabled(False)
            else:
                self.p4_set_main_btn.setText('Set as Main')
                self.p4_set_main_btn.setEnabled(True)
        if hasattr(self, 'p4_new_portfolio_btn'):
            self.p4_new_portfolio_btn.setEnabled(len(slots) < MAX_PORTFOLIOS)
        if hasattr(self, 'p4_delete_portfolio_btn'):
            self.p4_delete_portfolio_btn.setEnabled(len(slots) > 1)
        if hasattr(self, 'port_header_lbl'):
            self.port_header_lbl.setText(f'{self._p4_portfolio_name(main_index)} ({len(getattr(self, "tickers", []))})')

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
                'resizable_cols': tuple(range(P4_PORTFOLIO_COL_ACTION)),
                'fixed_cols': {P4_PORTFOLIO_COL_ACTION: _P4_TABLE_FIXED_ACTION_WIDTH},
            },
            'options': {
                'table_attr': 'p4_opt_table',
                'config_path': _P4_OPTIONS_TABLE_WIDTHS_CONFIG,
                'resizable_cols': tuple(range(15)),
                'fixed_cols': {15: _P4_TABLE_FIXED_ACTION_WIDTH},
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
            base_widths = {int(col): 1 for col in spec.get('resizable_cols', ())}
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
        self._p4_apply_portfolio_table_widths()

    def _p4_on_content_tab_changed(self, index: int) -> None:
        """Refresh the visible Portfolio sub-tab after a tab switch."""
        if not hasattr(self, 'p4_content_tabs'):
            return
        widget = self.p4_content_tabs.widget(index)
        if widget is getattr(self, 'p4_positions_page', None):
            QTimer.singleShot(0, self._p4_apply_portfolio_table_widths)
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
            if active_tickers - fetched and hasattr(self, 'refresh_data'):
                self.refresh_data()
        elif hasattr(self, 'p4_table'):
            self.p4_table.blockSignals(True)
            self.p4_table.setRowCount(0)
            self.p4_table.blockSignals(False)
            if hasattr(self, '_p4_update_stock_positions_label'):
                self._p4_update_stock_positions_label()
            self._p4_apply_table_width_preferences('stock')
            if hasattr(self, '_p4_refresh_active_momentum_view'):
                self._p4_refresh_active_momentum_view()
        if (
            hasattr(self, 'p4_content_tabs')
            and self.p4_content_tabs.currentWidget() is getattr(self, 'p4_metrics_page', None)
            and hasattr(self, '_p4_refresh_portfolio_metrics_view')
        ):
            self._p4_refresh_portfolio_metrics_view()

    def _p4_rename_active_portfolio(self) -> None:
        """Prompt the user to rename the selected portfolio slot."""
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
        slots = self._p4_get_portfolio_slots()
        if len(slots) >= MAX_PORTFOLIOS:
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
            next_index = len(fallback_slots)
            fallback_slots.append({'id': next_index, 'portfolio_id': f'portfolio_{next_index + 1}', 'name': f'Portfolio {next_index + 1}'})
            self.portfolio_slots = fallback_slots
            self.active_portfolio_index = next_index
            created = True
        if created:
            self._p4_refresh_portfolio_selector()

    def _p4_delete_active_portfolio(self) -> None:
        """Delete the currently selected portfolio after confirmation."""
        slots = self._p4_get_portfolio_slots()
        if len(slots) <= 1:
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
        title_lbl = QLabel('<b>Portfolio</b>')
        self.set_theme_role(title_lbl, 'page_title')
        self.p4_total_label = QLabel('Total:  $0.00  USD')
        self.set_theme_role(self.p4_total_label, 'metric')
        self.p4_stock_positions_label = QLabel('Stock Positions:  0')
        self.set_theme_role(self.p4_stock_positions_label, 'badge')
        self.p4_opt_pl_label = QLabel('Options P&L:  $0.00')
        self.set_theme_role(self.p4_opt_pl_label, 'badge')
        summary_bar.addWidget(title_lbl)
        summary_bar.addStretch()
        summary_bar.addWidget(self.p4_opt_pl_label)
        summary_bar.addWidget(self.p4_stock_positions_label)
        summary_bar.addWidget(self.p4_total_label)
        layout.addLayout(summary_bar)
        selector_bar = QHBoxLayout()
        selector_bar.setSpacing(8)
        selector_label = QLabel('Portfolios')
        self.set_theme_role(selector_label, 'card_title')
        self.p4_portfolio_tabs = QTabWidget()
        self.p4_portfolio_tabs.setDocumentMode(True)
        self.p4_portfolio_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.p4_portfolio_tabs.tabBar().setMinimumHeight(32)
        self.p4_portfolio_tabs.currentChanged.connect(self._p4_on_portfolio_changed)
        self.p4_new_portfolio_btn = QPushButton('New Portfolio')
        self.set_theme_variant(self.p4_new_portfolio_btn, 'positive')
        self.p4_new_portfolio_btn.setMinimumHeight(30)
        self.p4_new_portfolio_btn.clicked.connect(self._p4_create_portfolio)
        self.p4_delete_portfolio_btn = QPushButton('Delete Portfolio')
        self.set_theme_variant(self.p4_delete_portfolio_btn, 'danger')
        self.p4_delete_portfolio_btn.setMinimumHeight(30)
        self.p4_delete_portfolio_btn.clicked.connect(self._p4_delete_active_portfolio)
        self.p4_rename_btn = QPushButton('Rename')
        self.set_theme_variant(self.p4_rename_btn, 'accent')
        self.p4_rename_btn.setMinimumHeight(30)
        self.p4_rename_btn.clicked.connect(self._p4_rename_active_portfolio)
        self.p4_set_main_btn = QPushButton('Set as Main')
        self.p4_set_main_btn.setMinimumHeight(30)
        self.set_theme_variant(self.p4_set_main_btn, 'accent')
        self.p4_set_main_btn.clicked.connect(self._p4_set_active_as_main)
        self.p4_main_portfolio_label = QLabel('Main Portfolio: Portfolio 1')
        self.set_theme_role(self.p4_main_portfolio_label, 'muted')
        selector_bar.addWidget(selector_label)
        selector_bar.addWidget(self.p4_portfolio_tabs, 1)
        selector_bar.addWidget(self.p4_new_portfolio_btn)
        selector_bar.addWidget(self.p4_delete_portfolio_btn)
        selector_bar.addWidget(self.p4_rename_btn)
        selector_bar.addWidget(self.p4_set_main_btn)
        selector_bar.addWidget(self.p4_main_portfolio_label)
        layout.addLayout(selector_bar)
        self.p4_content_tabs = QTabWidget()
        self.p4_content_tabs.setDocumentMode(True)
        self.p4_content_tabs.currentChanged.connect(self._p4_on_content_tab_changed)
        self.p4_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p4_main_splitter.setHandleWidth(6)
        self.p4_main_splitter.setChildrenCollapsible(False)
        self.p4_main_splitter.setStyleSheet(
            'QSplitter::handle { background: #2a2a4a; border-radius: 2px; }'
        )
        self.p4_positions_splitter = QSplitter(Qt.Orientation.Vertical)
        self.p4_positions_splitter.setHandleWidth(6)
        self.p4_positions_splitter.setChildrenCollapsible(False)
        self.p4_positions_splitter.setStyleSheet(
            'QSplitter::handle { background: #2a2a4a; border-radius: 2px; }'
        )
        stock_widget = QWidget()
        stock_widget.setMinimumHeight(_P4_STOCK_SECTION_MIN_HEIGHT)
        stock_layout = QVBoxLayout(stock_widget)
        stock_layout.setContentsMargins(0, 4, 0, 0)
        stock_layout.setSpacing(4)
        stock_header_layout = QHBoxLayout()
        stock_header = QLabel('Stock Positions')
        self.set_theme_role(stock_header, 'section_title')
        add_stock_btn = QPushButton('+ Add Position')
        add_stock_btn.setMinimumHeight(24)
        self.set_theme_variant(add_stock_btn, 'positive')
        add_stock_btn.clicked.connect(self._on_add_stock_clicked)
        export_llm_btn = QPushButton('Export for LLM')
        export_llm_btn.setMinimumHeight(24)
        self.set_theme_variant(export_llm_btn, 'positive')
        export_llm_btn.clicked.connect(self._p4_export_for_llm)
        stock_header_layout.addWidget(stock_header)
        stock_header_layout.addSpacing(10)
        stock_header_layout.addWidget(add_stock_btn)
        stock_header_layout.addSpacing(6)
        stock_header_layout.addWidget(export_llm_btn)
        stock_header_layout.addStretch()
        stock_layout.addLayout(stock_header_layout)
        self.p4_table = QTableWidget(0, len(P4_PORTFOLIO_COLUMNS))
        self.p4_table.setHorizontalHeaderLabels(P4_PORTFOLIO_COLUMNS)
        hh = self.p4_table.horizontalHeader()
        hh.setSectionsMovable(True)
        self.p4_table.verticalHeader().setVisible(False)
        self.p4_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.p4_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p4_table.verticalHeader().setDefaultSectionSize(52)
        self.p4_table.itemChanged.connect(self._on_tracker_cell_changed)
        self._p4_apply_table_width_preferences('stock')
        hh.sectionResized.connect(lambda logical, old, new: self._p4_on_table_section_resized('stock', logical, old, new))
        stock_layout.addWidget(self.p4_table, 1)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)
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
        weight_container = QWidget()
        weight_container_layout = QVBoxLayout(weight_container)
        weight_container_layout.setContentsMargins(0, 0, 0, 0)
        weight_container_layout.setSpacing(2)
        weight_container_layout.addWidget(weight_label)
        weight_container_layout.addWidget(self.p4_weight_chart, 1)
        right_layout.addWidget(dip_finder_label)
        right_layout.addWidget(self.p4_returns_tabs, 1)
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
        self.p4_positions_splitter.splitterMoved.connect(self._p4_apply_portfolio_table_widths)
        self.p4_main_splitter.addWidget(self.p4_positions_splitter)
        self.p4_main_splitter.addWidget(right_widget)
        self.p4_main_splitter.setCollapsible(0, False)
        self.p4_main_splitter.setCollapsible(1, False)
        self.p4_main_splitter.setStretchFactor(0, 3)
        self.p4_main_splitter.setStretchFactor(1, 1)
        self.p4_main_splitter.splitterMoved.connect(self._p4_apply_portfolio_table_widths)
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
        self.p4_metrics_page = self._build_portfolio_metrics_page() if hasattr(self, '_build_portfolio_metrics_page') else QWidget()
        self.p4_content_tabs.addTab(self.p4_positions_page, 'Positions')
        self.p4_content_tabs.addTab(self.p4_momentum_page, 'Momentum Tracker')
        self.p4_content_tabs.addTab(self.p4_metrics_page, 'Portfolio Metrics')
        layout.addWidget(self.p4_content_tabs, 1)
        QTimer.singleShot(0, self._p4_apply_portfolio_table_widths)
        self._p4_refresh_portfolio_selector()

    def _on_add_stock_clicked(self) -> None:
        """Handle add stock clicked."""
        ticker, ok = QInputDialog.getText(self, 'Add Stock Position', 'Enter Ticker Symbol:')
        if ok and ticker:
            ticker = ticker.upper().strip()
            tickers = self._p4_active_tickers() if hasattr(self, '_p4_active_tickers') else self.active_tickers
            tracker_data = self._p4_active_tracker_data() if hasattr(self, '_p4_active_tracker_data') else self.active_tracker_data
            if ticker and ticker not in tickers:
                tickers.append(ticker)
                if ticker not in tracker_data:
                    tracker_data[ticker] = {'shares': 0, 'avg_price': 0}
                if hasattr(self, '_p4_invalidate_returns_cache'):
                    self._p4_invalidate_returns_cache(self.active_portfolio_id)
                if hasattr(self, '_p4_invalidate_momentum_cache'):
                    self._p4_invalidate_momentum_cache(self.active_portfolio_id)
                if hasattr(self, '_p4_invalidate_portfolio_analytics_cache'):
                    self._p4_invalidate_portfolio_analytics_cache(self.active_portfolio_id)
                self._persist_all_portfolios()
                self.update_page4(self.last_data or {'portfolio': {}})
                if (
                    self.active_portfolio_id == self.main_portfolio_id
                    or getattr(self, '_dashboard_showing_all', False)
                ) and hasattr(self, '_dashboard_apply_local_portfolio_membership'):
                    self._dashboard_apply_local_portfolio_membership(self.last_data)
                if self.last_data:
                    self.refresh_data(reason='portfolio_membership_change')
                else:
                    self.refresh_data()

    def _init_options_tab(self) -> Any:
        """Build the Options section widget and return it."""
        options_widget = QWidget()
        layout = QVBoxLayout(options_widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        title_lbl = QLabel('Options Positions')
        self.set_theme_role(title_lbl, 'section_title')
        header.addWidget(title_lbl)
        header.addSpacing(10)
        add_btn = QPushButton('+ Add Position')
        add_btn.setMinimumHeight(24)
        self.set_theme_variant(add_btn, 'positive')
        add_btn.clicked.connect(self._add_options_row)
        refresh_opt_btn = QPushButton('↻ Sync')
        refresh_opt_btn.setMinimumHeight(24)
        self.set_theme_variant(refresh_opt_btn, 'accent')
        refresh_opt_btn.clicked.connect(self._sync_all_options)
        header.addWidget(add_btn)
        header.addSpacing(6)
        header.addWidget(refresh_opt_btn)
        header.addStretch()
        layout.addLayout(header)
        self.p4_opt_table = QTableWidget(0, 16)
        self.p4_opt_table.setHorizontalHeaderLabels(['Ticker', 'Type', 'Expiry', 'DTE', 'Strike', 'Qty', 'Premium', 'Market Price', 'IV (%)', 'Delta', 'Theta', 'P&L ($)', 'Return %', 'Annual %', 'Status', ''])
        oh = self.p4_opt_table.horizontalHeader()
        for col in range(15):
            oh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        oh.setSectionResizeMode(15, QHeaderView.ResizeMode.Fixed)
        self.p4_opt_table.setColumnWidth(15, 36)
        self.p4_opt_table.verticalHeader().setVisible(False)
        self.p4_opt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.p4_opt_table.verticalHeader().setDefaultSectionSize(38)
        self.p4_opt_table.setAlternatingRowColors(True)
        self.p4_opt_table.itemChanged.connect(self._on_options_cell_changed)
        layout.addWidget(self.p4_opt_table, 1)
        for pos in self.options_data:
            self._insert_options_row(pos)
        self._p4_apply_table_width_preferences('options')
        oh.sectionResized.connect(lambda logical, old, new: self._p4_on_table_section_resized('options', logical, old, new))
        return options_widget

    def _sync_all_options(self) -> None:
        """Refresh expiries and current prices for all options in the table sequentially."""
        t = self.p4_opt_table
        if t.rowCount() == 0:
            return
        self.set_status_text(self.status_bar, 'Syncing all options...', status='accent')

        def _run_sync() -> None:
            """Handle run sync."""
            success_count = 0
            fail_count = 0
            total = t.rowCount()
            for row in range(total):
                ticker_item = t.item(row, 0)
                if not ticker_item:
                    continue
                ticker = ticker_item.text().strip().upper()
                if not ticker:
                    continue
                self._invoke_main.emit(lambda r=row, sym=ticker: self.status_bar.setText(f'Syncing {sym} ({r + 1}/{total})...'))
                self._invoke_main.emit(lambda r=row: self._set_row_fetching_status(r))
                self._fetch_option_expiries_sync(row, ticker)
                self._fetch_single_option_price_sync(row)
                price_item = t.item(row, 7)
                if price_item and 'Err' in price_item.text():
                    fail_count += 1
                else:
                    success_count += 1
            msg = f'Sync Complete: {success_count} succeeded, {fail_count} failed'
            status = 'positive' if fail_count == 0 else 'warning'
            self._invoke_main.emit(lambda: self.set_status_text(self.status_bar, msg, status=status))

        threading.Thread(target=_run_sync, daemon=True).start()

    def _apply_portfolio_theme(self) -> None:
        """Refresh portfolio-page plot colors after a theme change."""
        for chart in getattr(self, 'p4_returns_charts', {}).values():
            self.style_plot_widget(chart)
        for chart in getattr(self, 'p4_momentum_charts', {}).values():
            self.style_plot_widget(chart)
        if hasattr(self, 'p4_weight_chart'):
            self.style_plot_widget(self.p4_weight_chart)
