from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.widgets.table_render import render_table_rows
from budget_terminal_app.mixins.options_chain_presenters import (
    build_chain_rows,
    build_option_summary_rows,
    format_chain_value,
    format_top_volume_expiration,
    prepare_strike_records,
    prepare_top_volume_records,
)
from budget_terminal_app.services.options_data import OPTIONS_MARKET_TIMEZONE


class OptionsChainMixin:
    _P5_CHAIN_COLUMNS = [
        ('Strike', 'strike', '{:.1f}'),
        ('Last', 'lastPrice', '{:.2f}'),
        ('Bid', 'bid', '{:.2f}'),
        ('Ask', 'ask', '{:.2f}'),
        ('Chg', 'change', '{:+.2f}'),
        ('Vol', 'volume', '{:,.0f}'),
        ('OI', 'openInterest', '{:,.0f}'),
        ('IV', 'iv_percent', '{:.1f}%'),
        ('Delta', 'delta_calc', '{:.3f}'),
        ('Gamma', 'gamma_calc', '{:.3f}'),
        ('Theta', 'theta_calc', '{:.3f}'),
        ('Vega', 'vega_calc', '{:.3f}'),
        ('Rho', 'rho_calc', '{:.3f}'),
    ]
    _P5_STRATEGIES = ('None', 'Covered Call', 'Cash Secured Put')
    _P5_STRATEGY_MIN_OI = 25.0
    _P5_STRATEGY_MIN_VOLUME = 0.0
    _P5_STRATEGY_MAX_SPREAD_RATIO = 0.60
    _P5_CC_DELTA_TARGET = 0.275
    _P5_CSP_DELTA_TARGET = 0.225
    _P5_CC_DELTA_BAND = (0.15, 0.40)
    _P5_CSP_DELTA_BAND = (0.12, 0.35)
    _P5_TOP_VOLUME_COLUMNS = ('Ticker', 'Type', 'Strike', 'Exp', 'Price', 'Vol')
    _P5_TOP_VOLUME_VIEW_KEY = 'top_volume'
    _P5_TOP_VOLUME_TAB_LABEL = 'Options by Top Volume'
    _P5_TOP_VOLUME_TAB_CONFIGS = (
        (_P5_TOP_VOLUME_VIEW_KEY, _P5_TOP_VOLUME_TAB_LABEL, ()),
    )
    _P5_TOP_VOLUME_TYPE_FILTERS = (
        ('both', 'Both', None),
        ('calls', 'Calls', 'Call'),
        ('puts', 'Puts', 'Put'),
    )
    _P5_TOP_VOLUME_GRID_COLUMNS = 3
    _P5_STRIKE_TAB_LABEL = 'Options by Strike'
    _P5_STRIKE_MATCH_TOLERANCE = 0.0001

    def init_page5(self) -> None:
        """Build the Options page UI."""
        layout = QVBoxLayout(self.page5)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        self._p5_expiry_request_seq = 0
        self._p5_expiry_latest_request_id = 0
        self._p5_chain_request_seq = 0
        self._p5_chain_latest_request_id = 0
        self._p5_top_volume_request_seq = 0
        self._p5_top_volume_latest_request_ids = {}
        self._p5_top_volume_payloads = {}
        self._p5_top_volume_type_filter = 'both'
        self._p5_top_volume_type_buttons = {}
        self.p5_top_volume_views = {}
        self._p5_top_volume_tab_order = []
        self._p5_strike_values_request_seq = 0
        self._p5_strike_values_latest_request_id = 0
        self._p5_strike_request_seq = 0
        self._p5_strike_latest_request_id = 0
        self._p5_strike_payload = self._p5_empty_strike_payload()
        self._p5_strike_available_strikes = []
        shared_controls = QHBoxLayout()
        self.p5_shared_ticker_input = QLineEdit()
        self.p5_shared_ticker_input.setPlaceholderText('Enter Ticker (e.g. AAPL)')
        self.p5_shared_ticker_input.setMinimumWidth(140)
        self.p5_shared_ticker_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_shared_ticker_input.returnPressed.connect(self._p5_load_active_subtab)
        shared_load_btn = QPushButton('Load All')
        self.set_theme_variant(shared_load_btn, 'accent')
        shared_load_btn.clicked.connect(self._p5_load_active_subtab)
        self.p5_export_top_volume_btn = QPushButton('Export Options by Top Volume')
        self.set_theme_variant(self.p5_export_top_volume_btn, 'accent')
        self.p5_export_top_volume_btn.clicked.connect(self._p5_export_top_options_by_volume)
        shared_controls.addWidget(QLabel('<b>Ticker:</b>'))
        shared_controls.addWidget(self.p5_shared_ticker_input)
        shared_controls.addWidget(shared_load_btn)
        shared_controls.addWidget(self.p5_export_top_volume_btn)
        shared_controls.addStretch()
        layout.addLayout(shared_controls, 0)
        self.p5_tabs = QTabWidget()
        self.p5_tabs.setDocumentMode(True)
        self.p5_tabs.addTab(self._p5_build_chain_tab(), 'Chain')
        for view_key, tab_label, bucket_config in self._P5_TOP_VOLUME_TAB_CONFIGS:
            self._p5_top_volume_latest_request_ids[view_key] = 0
            self._p5_top_volume_payloads[view_key] = self._p5_empty_top_volume_payload(bucket_config)
            self.p5_tabs.addTab(self._p5_build_top_volume_tab(view_key, tab_label, bucket_config), tab_label)
            self._p5_top_volume_tab_order.append(view_key)
        self.p5_tabs.addTab(self._p5_build_strike_tab(), self._P5_STRIKE_TAB_LABEL)
        layout.addWidget(self.p5_tabs, 1)

    def _p5_build_chain_tab(self) -> Any:
        """Build the Chain subtab content."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        controls = QHBoxLayout()
        load_btn = QPushButton('Load Chain')
        self.set_theme_variant(load_btn, 'accent')
        load_btn.clicked.connect(self._p5_load_expiries)
        self.p5_export_chain_btn = QPushButton('Export Chain')
        self.set_theme_variant(self.p5_export_chain_btn, 'accent')
        self.p5_export_chain_btn.clicked.connect(self._p5_export_chain)
        self.p5_expiry_combo = QComboBox()
        self.p5_expiry_combo.setMinimumWidth(140)
        self.p5_expiry_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_expiry_combo.currentIndexChanged.connect(self._p5_load_chain)
        self.p5_strategy_combo = QComboBox()
        self.p5_strategy_combo.setMinimumWidth(120)
        self.p5_strategy_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.p5_strategy_combo.addItems(list(self._P5_STRATEGIES))
        self.p5_strategy_combo.currentIndexChanged.connect(self._p5_refresh_strategy_view)
        self.p5_status_lbl = QLabel('Enter a ticker above to view the full options chain.')
        self.p5_status_lbl.setWordWrap(True)
        self.p5_status_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_theme_role(self.p5_status_lbl, 'status_muted')
        self.p5_price_lbl = QLabel('')
        self.p5_price_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {self.theme_color('accent_positive')}; margin-left: 10px;")
        self._p5_chain_df = pd.DataFrame()
        self._p5_chain_ticker = ''
        self._p5_chain_spot_price = 0.0
        self._p5_chain_expiry = ''
        self._p5_chain_rate = 0.0
        self._p5_chain_dividend_yield = 0.0
        self._p5_chain_rate_source = 'default'
        self._p5_chain_dividend_source = 'default'
        controls.addWidget(load_btn)
        controls.addWidget(self.p5_export_chain_btn)
        controls.addSpacing(10)
        controls.addWidget(self.p5_price_lbl)
        controls.addSpacing(20)
        controls.addWidget(QLabel('<b>Expiry:</b>'))
        controls.addWidget(self.p5_expiry_combo)
        controls.addSpacing(14)
        controls.addWidget(QLabel('<b>Strategy:</b>'))
        controls.addWidget(self.p5_strategy_combo)
        controls.addStretch()
        layout.addLayout(controls, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        calls_widget = QWidget()
        calls_layout = QVBoxLayout(calls_widget)
        calls_layout.setContentsMargins(0, 0, 0, 0)
        calls_layout.addWidget(QLabel('<b>CALLS</b>'))
        self.p5_calls_table = self._make_chain_table()
        calls_layout.addWidget(self.p5_calls_table)
        puts_widget = QWidget()
        puts_layout = QVBoxLayout(puts_widget)
        puts_layout.setContentsMargins(0, 0, 0, 0)
        puts_layout.addWidget(QLabel('<b>PUTS</b>'))
        self.p5_puts_table = self._make_chain_table()
        puts_layout.addWidget(self.p5_puts_table)
        splitter.addWidget(calls_widget)
        splitter.addWidget(puts_widget)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.p5_status_lbl, 0)
        return tab

    def _p5_build_top_volume_tab(self, view_key: str, tab_label: str, bucket_config: tuple[tuple[str, str, int], ...]) -> Any:
        """Build the dynamic top-volume subtab that expands to all fetched expirations."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        controls = QHBoxLayout()
        load_btn = QPushButton('Load Options by Top Volume')
        self.set_theme_variant(load_btn, 'accent')
        load_btn.clicked.connect(partial(self._p5_load_top_volume, view_key))
        controls.addWidget(load_btn)
        controls.addSpacing(10)
        controls.addWidget(QLabel('<b>Type:</b>'))
        type_group = QButtonGroup(tab)
        type_group.setExclusive(True)
        for mode_key, mode_label, _option_type in self._P5_TOP_VOLUME_TYPE_FILTERS:
            mode_btn = QPushButton(mode_label)
            mode_btn.setCheckable(True)
            mode_btn.setMinimumHeight(26)
            mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            mode_btn.clicked.connect(partial(self._p5_set_top_volume_type_filter, mode_key))
            type_group.addButton(mode_btn)
            self._p5_top_volume_type_buttons[mode_key] = mode_btn
            controls.addWidget(mode_btn)
        controls.addStretch()
        layout.addLayout(controls, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_contents = QWidget()
        scroll_layout = QGridLayout(scroll_contents)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setHorizontalSpacing(10)
        scroll_layout.setVerticalSpacing(10)
        scroll.setWidget(scroll_contents)
        layout.addWidget(scroll, 1)
        status_lbl = QLabel(f'Enter a ticker above to view {tab_label.lower()} across all available expirations.')
        status_lbl.setWordWrap(True)
        status_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_theme_role(status_lbl, 'status_muted')
        layout.addWidget(status_lbl, 0)
        self.p5_top_volume_views[view_key] = {
            'tab': tab,
            'tab_label': tab_label,
            'bucket_config': tuple(bucket_config),
            'status_lbl': status_lbl,
            'sections': {},
            'grid_layout': scroll_layout,
            'type_group': type_group,
        }
        self._p5_apply_top_volume_type_button_state()
        self._p5_set_top_volume_bucket_config(view_key, tuple(bucket_config))
        return tab

    def _p5_build_strike_tab(self) -> Any:
        """Build the Options by Strike subtab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        controls = QHBoxLayout()
        load_strikes_btn = QPushButton('Load Strikes')
        self.set_theme_variant(load_strikes_btn, 'accent')
        load_strikes_btn.clicked.connect(self._p5_load_strike_values)
        self.p5_strike_combo = QComboBox()
        self.p5_strike_combo.setFixedWidth(90)
        self.p5_strike_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._p5_reset_strike_combo()
        self.p5_strike_combo.currentIndexChanged.connect(self._p5_on_strike_combo_changed)
        load_options_btn = QPushButton('Load Options by Strike')
        self.set_theme_variant(load_options_btn, 'accent')
        load_options_btn.clicked.connect(self._p5_load_options_by_strike)
        controls.addWidget(load_strikes_btn)
        controls.addSpacing(10)
        controls.addWidget(QLabel('<b>Strike:</b>'))
        controls.addWidget(self.p5_strike_combo)
        controls.addWidget(load_options_btn)
        controls.addStretch()
        layout.addLayout(controls, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_contents = QWidget()
        self.p5_strike_grid_layout = QGridLayout(scroll_contents)
        self.p5_strike_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.p5_strike_grid_layout.setHorizontalSpacing(10)
        self.p5_strike_grid_layout.setVerticalSpacing(10)
        scroll.setWidget(scroll_contents)
        layout.addWidget(scroll, 1)
        self.p5_strike_status_lbl = QLabel('Enter a ticker above, load strikes, then choose a strike to view matching options across all available expirations.')
        self.p5_strike_status_lbl.setWordWrap(True)
        self.p5_strike_status_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_theme_role(self.p5_strike_status_lbl, 'status_muted')
        layout.addWidget(self.p5_strike_status_lbl, 0)
        self.p5_strike_sections = {}
        self._p5_set_strike_bucket_config(())
        return tab

    def _p5_top_volume_grid_column_count(self, count: int) -> int:
        """Return a compact grid width that adapts to the fetched expiration count."""
        total = max(int(count or 0), 0)
        if total <= 1:
            return 1
        if total <= 4:
            return 2
        return self._P5_TOP_VOLUME_GRID_COLUMNS

    def _p5_build_dynamic_top_volume_bucket_config(self, expiries: Any) -> tuple[tuple[str, str, int], ...]:
        """Convert the fetched yfinance expiration list into ordered UI bucket metadata."""
        parsed = []
        seen = set()
        today = self._p5_current_options_market_date()
        for expiry in self._p5_filter_live_expiries(expiries):
            expiry_text = str(expiry or '').strip()
            if not expiry_text or expiry_text in seen:
                continue
            try:
                expiry_date = datetime.date.fromisoformat(expiry_text)
            except Exception:
                continue
            seen.add(expiry_text)
            parsed.append((expiry_text, expiry_date))
        parsed.sort(key=lambda item: item[1])
        return tuple(
            (expiry_text, expiry_text, max((expiry_date - today).days, 0))
            for expiry_text, expiry_date in parsed
        )

    def _p5_current_options_market_date(self) -> datetime.date:
        """Return today's date in the US options market timezone."""
        return datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()

    def _p5_is_past_expiry(self, expiry: Any) -> bool:
        """Return whether an expiry is before the current US options market date."""
        try:
            expiry_date = datetime.date.fromisoformat(str(expiry or '').strip())
        except ValueError:
            return False
        return expiry_date < self._p5_current_options_market_date()

    def _p5_filter_live_expiries(self, expiries: Any) -> list[str]:
        """Return unique non-expired expiry strings, preserving source order."""
        live_expiries = []
        seen = set()
        for expiry in list(expiries or []):
            expiry_text = str(expiry or '').strip()
            if not expiry_text or expiry_text in seen or self._p5_is_past_expiry(expiry_text):
                continue
            seen.add(expiry_text)
            live_expiries.append(expiry_text)
        return live_expiries

    def _p5_set_top_volume_bucket_config(self, view_key: str, bucket_config: tuple[tuple[str, str, int], ...]) -> None:
        """Rebuild one dynamic top-volume grid so it matches the fetched expirations."""
        view = self._p5_top_volume_view(view_key)
        layout = view.get('grid_layout')
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        normalized_config = tuple(bucket_config) if isinstance(bucket_config, (list, tuple)) else ()
        view['bucket_config'] = normalized_config
        sections = {}
        if not normalized_config:
            view['sections'] = sections
            return
        grid_columns = self._p5_top_volume_grid_column_count(len(normalized_config))
        for index, (bucket_key, _bucket_label, _days_out) in enumerate(normalized_config):
            panel = QFrame()
            self.set_theme_role(panel, 'panel')
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(6, 6, 6, 6)
            panel_layout.setSpacing(4)
            section_label = QLabel('')
            self.set_theme_role(section_label, 'section_title')
            table = self._make_top_volume_table()
            panel_layout.addWidget(section_label)
            panel_layout.addWidget(table, 1)
            sections[bucket_key] = {'label': section_label, 'table': table, 'panel': panel}
            row = index // grid_columns
            col = index % grid_columns
            layout.addWidget(panel, row, col)
        for col in range(grid_columns):
            layout.setColumnStretch(col, 1)
        total_rows = max(1, math.ceil(len(normalized_config) / grid_columns))
        for row in range(total_rows):
            layout.setRowStretch(row, 1)
        view['sections'] = sections
        for bucket_key, _bucket_label, _days_out in normalized_config:
            self._p5_set_top_volume_bucket_title(view_key, bucket_key, bucket_key)

    def _p5_reset_strike_combo(self, selected_strike: float | None = None) -> None:
        """Reset the strike dropdown to the placeholder plus any loaded strikes."""
        if not hasattr(self, 'p5_strike_combo'):
            return
        self.p5_strike_combo.blockSignals(True)
        self.p5_strike_combo.clear()
        self.p5_strike_combo.addItem('Select strike', None)
        selected_index = 0
        for strike in list(getattr(self, '_p5_strike_available_strikes', []) or []):
            try:
                strike_value = float(strike)
            except (TypeError, ValueError):
                continue
            label = f'{strike_value:.1f}' if strike_value == round(strike_value, 1) else f'{strike_value:g}'
            self.p5_strike_combo.addItem(label, strike_value)
            if selected_strike is not None and abs(strike_value - float(selected_strike)) <= self._P5_STRIKE_MATCH_TOLERANCE:
                selected_index = self.p5_strike_combo.count() - 1
        self.p5_strike_combo.setCurrentIndex(selected_index)
        self.p5_strike_combo.blockSignals(False)

    def _p5_selected_strike(self) -> float | None:
        """Return the selected strike dropdown value, if any."""
        if not hasattr(self, 'p5_strike_combo'):
            return None
        value = self.p5_strike_combo.currentData()
        try:
            strike = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(strike):
            return None
        return strike

    def _p5_on_strike_combo_changed(self, *_: Any) -> None:
        """Persist the current strike selection and load matching rows."""
        payload = getattr(self, '_p5_strike_payload', {})
        if not isinstance(payload, dict):
            payload = self._p5_empty_strike_payload()
        selected_strike = self._p5_selected_strike()
        updated = dict(payload)
        updated['selected_strike'] = selected_strike
        updated['available_strikes'] = list(getattr(self, '_p5_strike_available_strikes', []) or [])
        self._p5_strike_payload = updated
        self._p5_save_session_snapshot()
        if selected_strike is not None:
            self._p5_load_options_by_strike()

    def _p5_set_strike_bucket_config(self, bucket_config: tuple[tuple[str, str, int], ...]) -> None:
        """Rebuild the strike grid to match the fetched expiration list."""
        layout = getattr(self, 'p5_strike_grid_layout', None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        normalized_config = tuple(bucket_config) if isinstance(bucket_config, (list, tuple)) else ()
        self._p5_strike_bucket_config = normalized_config
        sections = {}
        if not normalized_config:
            self.p5_strike_sections = sections
            return
        grid_columns = self._p5_top_volume_grid_column_count(len(normalized_config))
        for index, (bucket_key, _bucket_label, _days_out) in enumerate(normalized_config):
            panel = QFrame()
            self.set_theme_role(panel, 'panel')
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(6, 6, 6, 6)
            panel_layout.setSpacing(4)
            section_label = QLabel('')
            self.set_theme_role(section_label, 'section_title')
            table = self._make_top_volume_table()
            panel_layout.addWidget(section_label)
            panel_layout.addWidget(table, 1)
            sections[bucket_key] = {'label': section_label, 'table': table, 'panel': panel}
            row = index // grid_columns
            col = index % grid_columns
            layout.addWidget(panel, row, col)
        for col in range(grid_columns):
            layout.setColumnStretch(col, 1)
        total_rows = max(1, math.ceil(len(normalized_config) / grid_columns))
        for row in range(total_rows):
            layout.setRowStretch(row, 1)
        self.p5_strike_sections = sections
        for bucket_key, _bucket_label, _days_out in normalized_config:
            self._p5_set_strike_bucket_title(bucket_key, bucket_key)

    def _p5_strike_buckets(self) -> tuple[tuple[str, str, int], ...]:
        """Return the configured expiration buckets for the strike tab."""
        raw = getattr(self, '_p5_strike_bucket_config', ())
        return tuple(raw) if isinstance(raw, (list, tuple)) else ()

    def _p5_set_strike_bucket_title(self, bucket_key: str, expiry: str = '') -> None:
        """Refresh one strike section label."""
        section = getattr(self, 'p5_strike_sections', {}).get(bucket_key, {}) if isinstance(getattr(self, 'p5_strike_sections', {}), dict) else {}
        label_widget = section.get('label')
        if label_widget is None:
            return
        expiry_display = self._p5_format_top_volume_expiration(expiry)
        display_text = expiry_display or self._p5_format_top_volume_expiration(bucket_key) or bucket_key or 'Unavailable'
        label_widget.setText(f'Options by Strike - {display_text}')

    def _p5_clear_strike_tables(self) -> None:
        """Reset all strike tables to an empty state."""
        sections = getattr(self, 'p5_strike_sections', {}) if isinstance(getattr(self, 'p5_strike_sections', {}), dict) else {}
        for bucket_key, _bucket_label, _days_out in self._p5_strike_buckets():
            section = sections.get(bucket_key, {})
            table = section.get('table')
            if table is not None:
                render_table_rows(table, ())
                table.setToolTip('')
            self._p5_set_strike_bucket_title(bucket_key, bucket_key)

    def _make_chain_table(self) -> Any:
        """Create a shared options chain table."""
        t = QTableWidget(0, len(self._P5_CHAIN_COLUMNS))
        t.setHorizontalHeaderLabels([label for label, _, _ in self._P5_CHAIN_COLUMNS])
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        return t

    def _make_top_volume_table(self) -> Any:
        """Create a Top Options by Volume table using the dashboard-style columns."""
        table = QTableWidget(0, len(self._P5_TOP_VOLUME_COLUMNS))
        table.setHorizontalHeaderLabels(list(self._P5_TOP_VOLUME_COLUMNS))
        table.horizontalHeader().setMinimumHeight(28)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(220)
        return table

    def _p5_format_top_volume_expiration(self, expiry: str) -> str:
        """Render one expiration in compact uppercase month format."""
        return format_top_volume_expiration(expiry)

    def _p5_normalize_top_volume_type_filter(self, value: Any) -> str:
        """Return a supported top-volume option-type filter key."""
        mode = str(value or '').strip().lower()
        aliases = {
            'call': 'calls',
            'calls': 'calls',
            'put': 'puts',
            'puts': 'puts',
            'both': 'both',
            'all': 'both',
        }
        normalized = aliases.get(mode, 'both')
        valid_modes = {key for key, _label, _option_type in self._P5_TOP_VOLUME_TYPE_FILTERS}
        return normalized if normalized in valid_modes else 'both'

    def _p5_top_volume_type_label(self, mode: Any = None) -> str:
        """Return the display label for the selected top-volume option-type filter."""
        selected = self._p5_normalize_top_volume_type_filter(mode or getattr(self, '_p5_top_volume_type_filter', 'both'))
        for mode_key, mode_label, _option_type in self._P5_TOP_VOLUME_TYPE_FILTERS:
            if mode_key == selected:
                return mode_label
        return 'Both'

    def _p5_top_volume_option_type(self) -> str | None:
        """Return the chain row type required by the selected top-volume filter."""
        selected = self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both'))
        for mode_key, _mode_label, option_type in self._P5_TOP_VOLUME_TYPE_FILTERS:
            if mode_key == selected:
                return option_type
        return None

    def _p5_apply_top_volume_type_button_state(self) -> None:
        """Sync the top-volume toggle buttons to the current filter state."""
        selected = self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both'))
        self._p5_top_volume_type_filter = selected
        for mode_key, button in getattr(self, '_p5_top_volume_type_buttons', {}).items():
            button.blockSignals(True)
            button.setChecked(mode_key == selected)
            button.blockSignals(False)

    def _p5_set_top_volume_type_filter(self, mode: Any, *_: Any, refresh: bool = True, save: bool = True) -> None:
        """Update the top-volume option-type filter and refresh loaded tables."""
        selected = self._p5_normalize_top_volume_type_filter(mode)
        previous = self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both'))
        self._p5_top_volume_type_filter = selected
        self._p5_apply_top_volume_type_button_state()
        if save:
            self._p5_save_session_snapshot()
        if not refresh or selected == previous or not self._p5_shared_ticker():
            return
        for view_key in list(getattr(self, '_p5_top_volume_tab_order', [])):
            self._p5_load_top_volume(view_key)

    def _p5_empty_top_volume_payload(self, bucket_config: tuple[tuple[str, str, int], ...], ticker: str = '') -> dict[str, Any]:
        """Build an empty payload for one dynamic top-volume view."""
        bucket_order = [bucket_key for bucket_key, _, _ in bucket_config]
        return {
            'ticker': str(ticker or ''),
            'type_filter': self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both')),
            'bucket_order': bucket_order,
            'records': {bucket_key: [] for bucket_key in bucket_order},
            'expirations': {bucket_key: bucket_key for bucket_key in bucket_order},
        }

    def _p5_empty_strike_payload(self, bucket_config: tuple[tuple[str, str, int], ...] = (), ticker: str = '', selected_strike: float | None = None) -> dict[str, Any]:
        """Build an empty payload for the Options by Strike view."""
        bucket_order = [bucket_key for bucket_key, _, _ in tuple(bucket_config or ())]
        return {
            'ticker': str(ticker or ''),
            'selected_strike': selected_strike,
            'available_strikes': list(getattr(self, '_p5_strike_available_strikes', []) or []),
            'bucket_order': bucket_order,
            'records': {bucket_key: [] for bucket_key in bucket_order},
            'expirations': {bucket_key: bucket_key for bucket_key in bucket_order},
        }

    def _p5_normalize_top_volume_payload(self, payload: Any, *, ticker: str = '') -> dict[str, Any]:
        """Normalize one cached/live top-volume payload into the dynamic all-expiry shape."""
        raw_payload = payload if isinstance(payload, dict) else {}
        raw_records = raw_payload.get('records', {}) if isinstance(raw_payload.get('records', {}), dict) else {}
        raw_expirations = raw_payload.get('expirations', {}) if isinstance(raw_payload.get('expirations', {}), dict) else {}
        raw_order = [str(value or '').strip() for value in list(raw_payload.get('bucket_order', [])) if str(value or '').strip()]
        if not raw_order:
            raw_order = [
                str(value or '').strip()
                for value in list(raw_expirations.keys()) + list(raw_records.keys())
                if str(value or '').strip()
            ]
        bucket_config = self._p5_build_dynamic_top_volume_bucket_config(raw_order)
        bucket_order = [bucket_key for bucket_key, _, _ in bucket_config]
        return {
            'ticker': str(raw_payload.get('ticker', ticker) or ticker).upper().strip(),
            'type_filter': self._p5_normalize_top_volume_type_filter(raw_payload.get('type_filter', getattr(self, '_p5_top_volume_type_filter', 'both'))),
            'bucket_order': bucket_order,
            'records': {
                bucket_key: list(raw_records.get(bucket_key, []))
                for bucket_key in bucket_order
            },
            'expirations': {
                bucket_key: str(raw_expirations.get(bucket_key, bucket_key) or bucket_key)
                for bucket_key in bucket_order
            },
        }

    def _p5_normalize_strike_payload(self, payload: Any, *, ticker: str = '') -> dict[str, Any]:
        """Normalize a cached/live strike payload into the all-expiry shape."""
        raw_payload = payload if isinstance(payload, dict) else {}
        raw_records = raw_payload.get('records', {}) if isinstance(raw_payload.get('records', {}), dict) else {}
        raw_expirations = raw_payload.get('expirations', {}) if isinstance(raw_payload.get('expirations', {}), dict) else {}
        raw_order = [str(value or '').strip() for value in list(raw_payload.get('bucket_order', [])) if str(value or '').strip()]
        if not raw_order:
            raw_order = [
                str(value or '').strip()
                for value in list(raw_expirations.keys()) + list(raw_records.keys())
                if str(value or '').strip()
            ]
        bucket_config = self._p5_build_dynamic_top_volume_bucket_config(raw_order)
        bucket_order = [bucket_key for bucket_key, _, _ in bucket_config]
        selected_strike = raw_payload.get('selected_strike')
        try:
            selected_strike = float(selected_strike) if selected_strike is not None else None
        except (TypeError, ValueError):
            selected_strike = None
        available_strikes = []
        for strike in list(raw_payload.get('available_strikes', []) or []):
            try:
                strike_value = float(strike)
            except (TypeError, ValueError):
                continue
            if not pd.isna(strike_value):
                available_strikes.append(strike_value)
        available_strikes = sorted(set(available_strikes))
        return {
            'ticker': str(raw_payload.get('ticker', ticker) or ticker).upper().strip(),
            'selected_strike': selected_strike,
            'available_strikes': available_strikes,
            'bucket_order': bucket_order,
            'records': {
                bucket_key: list(raw_records.get(bucket_key, []))
                for bucket_key in bucket_order
            },
            'expirations': {
                bucket_key: str(raw_expirations.get(bucket_key, bucket_key) or bucket_key)
                for bucket_key in bucket_order
            },
        }

    def _p5_shared_ticker(self) -> str:
        """Return the shared Options-page ticker symbol."""
        return str(getattr(self, 'p5_shared_ticker_input', None).text() if hasattr(self, 'p5_shared_ticker_input') else '').upper().strip()

    def _p5_session_snapshot(self) -> dict[str, Any] | None:
        """Return the current Options workspace snapshot when it has restorable state."""
        shared_ticker = self._p5_shared_ticker() or str(getattr(self, '_p5_chain_ticker', '') or '').upper().strip()
        has_chain_data = not getattr(self, '_p5_chain_df', pd.DataFrame()).empty
        has_top_volume_data = any(
            any(bool(records) for records in (payload.get('records', {}) if isinstance(payload, dict) else {}).values())
            for payload in getattr(self, '_p5_top_volume_payloads', {}).values()
        )
        top_volume_type_filter = self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both'))
        has_top_volume_filter = top_volume_type_filter != 'both'
        strike_payload = getattr(self, '_p5_strike_payload', {})
        has_strike_data = (
            bool(getattr(self, '_p5_strike_available_strikes', []) or [])
            or any(bool(records) for records in (strike_payload.get('records', {}) if isinstance(strike_payload, dict) else {}).values())
            or self._p5_selected_strike() is not None
        )
        if not shared_ticker and not has_chain_data and not has_top_volume_data and not has_top_volume_filter and not has_strike_data:
            return None
        return {
            'shared_ticker': shared_ticker,
            'active_tab_index': int(self.p5_tabs.currentIndex()) if hasattr(self, 'p5_tabs') else 0,
            'selected_expiry': str(self.p5_expiry_combo.currentData() if hasattr(self, 'p5_expiry_combo') else getattr(self, '_p5_chain_expiry', '') or ''),
            'strategy': str(self.p5_strategy_combo.currentText() if hasattr(self, 'p5_strategy_combo') else 'None' or 'None'),
            'chain_ticker': str(getattr(self, '_p5_chain_ticker', '') or '').upper().strip(),
            'chain_spot_price': float(getattr(self, '_p5_chain_spot_price', 0.0) or 0.0),
            'chain_expiry': str(getattr(self, '_p5_chain_expiry', '') or '').strip(),
            'chain_rate': float(getattr(self, '_p5_chain_rate', 0.0) or 0.0),
            'chain_dividend_yield': float(getattr(self, '_p5_chain_dividend_yield', 0.0) or 0.0),
            'chain_rate_source': str(getattr(self, '_p5_chain_rate_source', 'default') or 'default'),
            'chain_dividend_source': str(getattr(self, '_p5_chain_dividend_source', 'default') or 'default'),
            'chain_df': serialize_session_value(getattr(self, '_p5_chain_df', pd.DataFrame())),
            'top_volume_type_filter': top_volume_type_filter,
            'top_volume_payloads': serialize_session_value(getattr(self, '_p5_top_volume_payloads', {})),
            'strike_payload': serialize_session_value(getattr(self, '_p5_strike_payload', {})),
        }

    def _p5_save_session_snapshot(self, *, immediate: bool=False) -> None:
        """Persist the latest Options workspace snapshot."""
        if hasattr(self, '_set_tab_session_snapshot'):
            self._set_tab_session_snapshot('options', self._p5_session_snapshot(), immediate=immediate)

    def _p5_restore_expiry_selection(self, expiry: str) -> None:
        """Restore the shared expiry selector from cached state."""
        expiry_text = str(expiry or '').strip()
        if not hasattr(self, 'p5_expiry_combo') or not expiry_text or self._p5_is_past_expiry(expiry_text):
            return
        self.p5_expiry_combo.blockSignals(True)
        self.p5_expiry_combo.clear()
        try:
            expiry_date = datetime.datetime.strptime(expiry_text, '%Y-%m-%d').date()
            dte = (expiry_date - self._p5_current_options_market_date()).days
            label = f'{expiry_text} ({dte}d)'
        except Exception:
            label = expiry_text
        self.p5_expiry_combo.addItem(label, expiry_text)
        self.p5_expiry_combo.blockSignals(False)

    def _p5_restore_session_snapshot(self, snapshot: Any) -> bool:
        """Restore the Options workspace from cached session state."""
        payload = snapshot if isinstance(snapshot, dict) else {}
        shared_ticker = str(payload.get('shared_ticker', '') or '').upper().strip()
        if shared_ticker:
            self.p5_shared_ticker_input.setText(shared_ticker)
        selected_expiry = str(payload.get('selected_expiry', '') or payload.get('chain_expiry', '') or '').strip()
        if self._p5_is_past_expiry(selected_expiry):
            selected_expiry = ''
        if selected_expiry:
            self._p5_restore_expiry_selection(selected_expiry)
        strategy = str(payload.get('strategy', 'None') or 'None')
        if strategy in self._P5_STRATEGIES:
            self.p5_strategy_combo.setCurrentText(strategy)
        self._p5_set_top_volume_type_filter(payload.get('top_volume_type_filter', 'both'), refresh=False, save=False)
        active_tab_index = int(payload.get('active_tab_index', 0) or 0) if hasattr(self, 'p5_tabs') else 0
        if hasattr(self, 'p5_tabs') and 0 <= active_tab_index < self.p5_tabs.count():
            self.p5_tabs.setCurrentIndex(active_tab_index)
        self._p5_chain_ticker = str(payload.get('chain_ticker', shared_ticker) or shared_ticker).upper().strip()
        self._p5_chain_spot_price = float(payload.get('chain_spot_price', 0.0) or 0.0)
        self._p5_chain_rate = float(payload.get('chain_rate', 0.0) or 0.0)
        self._p5_chain_dividend_yield = float(payload.get('chain_dividend_yield', 0.0) or 0.0)
        self._p5_chain_rate_source = str(payload.get('chain_rate_source', 'default') or 'default')
        self._p5_chain_dividend_source = str(payload.get('chain_dividend_source', 'default') or 'default')
        if self._p5_chain_spot_price > 0:
            self.p5_price_lbl.setText(f'${self._p5_chain_spot_price:.2f}')
        else:
            self.p5_price_lbl.setText('')
        chain_df = deserialize_session_value(payload.get('chain_df'))
        if selected_expiry and isinstance(chain_df, pd.DataFrame) and not chain_df.empty:
            self._p5_populate_tables(chain_df, selected_expiry or str(payload.get('chain_expiry', '') or ''))
            self.set_status_text(self.p5_status_lbl, f'Restored last session for {self._p5_chain_ticker or shared_ticker}.', status='positive')
        top_volume_payloads = deserialize_session_value(payload.get('top_volume_payloads'))
        if isinstance(top_volume_payloads, dict):
            for view_key, _tab_label, _bucket_config in self._P5_TOP_VOLUME_TAB_CONFIGS:
                cached_payload = top_volume_payloads.get(view_key)
                if not isinstance(cached_payload, dict):
                    continue
                normalized_payload = self._p5_normalize_top_volume_payload(cached_payload, ticker=shared_ticker)
                bucket_config = self._p5_build_dynamic_top_volume_bucket_config(normalized_payload.get('bucket_order', []))
                self._p5_set_top_volume_bucket_config(view_key, bucket_config)
                self._p5_top_volume_payloads[view_key] = normalized_payload
                self._p5_render_top_volume_tables(
                    view_key,
                    normalized_payload['ticker'],
                    normalized_payload['records'],
                    normalized_payload['expirations'],
                )
                view = self._p5_top_volume_view(view_key)
                status_lbl = view.get('status_lbl')
                if status_lbl is not None:
                    self.set_status_text(status_lbl, f"Restored last session for {normalized_payload['ticker']}.", status='positive')
        strike_payload = deserialize_session_value(payload.get('strike_payload'))
        if isinstance(strike_payload, dict):
            normalized_strike = self._p5_normalize_strike_payload(strike_payload, ticker=shared_ticker)
            self._p5_strike_available_strikes = list(normalized_strike.get('available_strikes', []) or [])
            self._p5_reset_strike_combo(normalized_strike.get('selected_strike'))
            strike_bucket_config = self._p5_build_dynamic_top_volume_bucket_config(normalized_strike.get('bucket_order', []))
            self._p5_set_strike_bucket_config(strike_bucket_config)
            self._p5_strike_payload = normalized_strike
            self._p5_render_strike_tables(
                normalized_strike['ticker'],
                normalized_strike.get('selected_strike'),
                normalized_strike['records'],
                normalized_strike['expirations'],
            )
            if hasattr(self, 'p5_strike_status_lbl'):
                selected = normalized_strike.get('selected_strike')
                if any(bool(records) for records in normalized_strike.get('records', {}).values()):
                    self.set_status_text(self.p5_strike_status_lbl, f"Restored {self._P5_STRIKE_TAB_LABEL.lower()} for {normalized_strike['ticker']}.", status='positive')
                elif self._p5_strike_available_strikes:
                    strike_text = f'{selected:g}' if selected is not None else ''
                    message = f'Restored strikes for {normalized_strike["ticker"]}.'
                    if strike_text:
                        message += f' Select Load Options by Strike to refresh {strike_text}.'
                    self.set_status_text(self.p5_strike_status_lbl, message, status='muted')
        return bool(shared_ticker or (isinstance(chain_df, pd.DataFrame) and not chain_df.empty) or self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both')) != 'both')

    def _p5_restore_startup_session(self, snapshot: Any) -> None:
        """Hydrate Options from the last session, then refresh it in the background."""
        restored = self._p5_restore_session_snapshot(snapshot)
        if restored and self._p5_shared_ticker():
            self._p5_load_expiries()
            for view_key in list(getattr(self, '_p5_top_volume_tab_order', [])):
                self._p5_load_top_volume(view_key)
            if self._p5_selected_strike() is not None:
                self._p5_load_options_by_strike()
            else:
                self._p5_load_strike_values()

    def _p5_load_active_subtab(self) -> None:
        """Load all Options subtabs using the shared ticker."""
        self._p5_load_expiries()
        for view_key in list(getattr(self, '_p5_top_volume_tab_order', [])):
            self._p5_load_top_volume(view_key)
        self._p5_load_strike_values()

    def _p5_top_volume_view(self, view_key: str) -> dict[str, Any]:
        """Return the metadata for one top-volume timeframe tab."""
        return getattr(self, 'p5_top_volume_views', {}).get(view_key, {})

    def _p5_top_volume_buckets(self, view_key: str) -> tuple[tuple[str, str, int], ...]:
        """Return the configured bucket list for one top-volume timeframe tab."""
        view = self._p5_top_volume_view(view_key)
        raw = view.get('bucket_config', ())
        return tuple(raw) if isinstance(raw, (list, tuple)) else ()

    def _p5_top_volume_bucket_label(self, view_key: str, bucket_key: str) -> str:
        """Return the configured label for one top-volume bucket key."""
        for key, label, _days_out in self._p5_top_volume_buckets(view_key):
            if key == bucket_key:
                return label
        return bucket_key

    def _p5_set_top_volume_bucket_title(self, view_key: str, bucket_key: str, expiry: str = '') -> None:
        """Refresh the section label for one top-volume expiration panel."""
        view = self._p5_top_volume_view(view_key)
        section = view.get('sections', {}).get(bucket_key, {}) if isinstance(view.get('sections', {}), dict) else {}
        label_widget = section.get('label')
        if label_widget is None:
            return
        bucket_label = self._p5_top_volume_bucket_label(view_key, bucket_key)
        expiry_display = self._p5_format_top_volume_expiration(expiry)
        display_text = expiry_display or self._p5_format_top_volume_expiration(bucket_label) or bucket_label or 'Unavailable'
        label_widget.setText(f'Top Options by Volume - {display_text}')

    def _p5_clear_top_volume_tables(self, view_key: str) -> None:
        """Reset all top-volume bucket tables to an empty state."""
        view = self._p5_top_volume_view(view_key)
        sections = view.get('sections', {}) if isinstance(view.get('sections', {}), dict) else {}
        for bucket_key, _bucket_label, _days_out in self._p5_top_volume_buckets(view_key):
            section = sections.get(bucket_key, {})
            table = section.get('table')
            if table is not None:
                render_table_rows(table, ())
                table.setToolTip('')
            self._p5_set_top_volume_bucket_title(view_key, bucket_key)

    def _p5_load_top_volume(self, view_key: str, *_: Any) -> None:
        """Fetch and render top options by volume across every available expiration."""
        view = self._p5_top_volume_view(view_key)
        status_lbl = view.get('status_lbl')
        tab_label = str(view.get('tab_label', 'Top Options') or 'Top Options')
        ticker = self._p5_shared_ticker()
        type_label = self._p5_top_volume_type_label()
        if not ticker:
            self._p5_set_top_volume_bucket_config(view_key, ())
            self._p5_clear_top_volume_tables(view_key)
            self._p5_top_volume_payloads[view_key] = self._p5_empty_top_volume_payload(())
            if status_lbl is not None:
                self.set_status_text(status_lbl, f'Enter a ticker above to view {tab_label.lower()} across all available expirations.', status='muted')
            return
        self._p5_top_volume_request_seq += 1
        request_id = self._p5_top_volume_request_seq
        self._p5_top_volume_latest_request_ids[view_key] = request_id
        self._p5_set_top_volume_bucket_config(view_key, ())
        self._p5_top_volume_payloads[view_key] = self._p5_empty_top_volume_payload((), ticker=ticker)
        if status_lbl is not None:
            self.set_status_text(status_lbl, f'Loading {tab_label.lower()} ({type_label}) for {ticker} across all available expirations...', status='warning')

        def _run() -> None:
            """Load one top-volume table per yfinance expiration in the background."""
            try:
                expiries = self._get_cached_options_expiries(ticker)
                if expiries is None:
                    with YF_LOCK:
                        ticker_obj = yf.Ticker(ticker)
                        expiries = ticker_obj.options
                    if expiries:
                        self._save_cached_options_expiries(ticker, expiries)
                bucket_config = self._p5_build_dynamic_top_volume_bucket_config(expiries)
                chain_cache: dict[str, Any] = {}
                bucket_records = {bucket_key: [] for bucket_key, _, _ in bucket_config}
                bucket_expirations = {bucket_key: bucket_key for bucket_key, _, _ in bucket_config}
                for bucket_key, _bucket_label, _days_out in bucket_config:
                    expiry = bucket_key
                    try:
                        chain_df = chain_cache.get(expiry)
                        if chain_df is None:
                            chain_df = self._get_cached_option_chain(ticker, expiry)
                            chain_cache[expiry] = chain_df
                        bucket_records[bucket_key] = self._p5_prepare_top_volume_records(chain_df, ticker, expiry)
                    except Exception as exc:
                        logger.warning('%s load failed for %s %s: %s', tab_label, ticker, expiry, exc)
                if request_id != getattr(self, '_p5_top_volume_latest_request_ids', {}).get(view_key, 0):
                    return
                self._invoke_main.emit(
                    lambda key=view_key, rid=request_id, symbol=ticker, config=bucket_config, records=bucket_records, expirations=bucket_expirations: self._p5_update_top_volume_view(
                        key,
                        rid,
                        symbol,
                        config,
                        records,
                        expirations,
                    )
                )
            except Exception as exc:
                logger.error('P5 %s load failed for %s: %s', tab_label.lower(), ticker, exc)
                if request_id != getattr(self, '_p5_top_volume_latest_request_ids', {}).get(view_key, 0):
                    return
                self._invoke_main.emit(
                    lambda key=view_key, rid=request_id, symbol=ticker, message=str(exc): self._p5_handle_top_volume_error(
                        key,
                        rid,
                        symbol,
                        message,
                    )
                )
        self._submit_options_fetch(_run)

    def _p5_select_top_volume_buckets(self, expiries: Any, bucket_config: tuple[tuple[str, str, int], ...]) -> dict[str, str]:
        """Resolve the first available expiration at or after each configured week offset."""
        bucket_map = {bucket_key: '' for bucket_key, _, _ in bucket_config}
        if not expiries:
            return bucket_map
        parsed = []
        for expiry in expiries:
            try:
                expiry_text = str(expiry or '').strip()
                if not expiry_text:
                    continue
                parsed.append((expiry_text, datetime.date.fromisoformat(expiry_text)))
            except Exception:
                continue
        if not parsed:
            return bucket_map
        parsed.sort(key=lambda item: item[1])
        today = datetime.date.today()
        for bucket_key, _bucket_label, days_out in bucket_config:
            target_date = today + datetime.timedelta(days=int(days_out))
            selected = next((expiry_text for expiry_text, expiry_date in parsed if expiry_date >= target_date), None)
            bucket_map[bucket_key] = selected or parsed[-1][0]
        return bucket_map

    def _p5_select_top_volume_expiries_after_days(self, expiries: Any, min_days_out: int) -> list[str]:
        """Return all expirations strictly beyond the configured minimum days out."""
        if not expiries:
            return []
        parsed = []
        for expiry in expiries:
            try:
                expiry_text = str(expiry or '').strip()
                if not expiry_text:
                    continue
                parsed.append((expiry_text, datetime.date.fromisoformat(expiry_text)))
            except Exception:
                continue
        if not parsed:
            return []
        parsed.sort(key=lambda item: item[1])
        target_date = datetime.date.today() + datetime.timedelta(days=int(min_days_out))
        return [expiry_text for expiry_text, expiry_date in parsed if expiry_date >= target_date]

    def _p5_prepare_top_volume_records(self, chain_df: Any, ticker: str, expiry: str) -> list[dict[str, Any]]:
        """Normalize one chain and return the top-volume rows for display."""
        return prepare_top_volume_records(
            chain_df,
            ticker=ticker,
            expiry=expiry,
            option_type=self._p5_top_volume_option_type(),
            pd_module=pd,
        )

    def _p5_prepare_top_volume_records_for_expiries(self, ticker: str, expiries: list[str], chain_cache: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Merge multiple expirations and return the top-volume rows across the whole range."""
        if not expiries:
            return []
        cache = chain_cache if isinstance(chain_cache, dict) else {}
        frames = []
        for expiry in expiries:
            try:
                chain_df = cache.get(expiry)
                if chain_df is None:
                    chain_df = self._get_cached_option_chain(ticker, expiry)
                    cache[expiry] = chain_df
                if chain_df is None or chain_df.empty:
                    continue
                prepared = chain_df.copy()
                if 'expiration' not in prepared.columns:
                    prepared['expiration'] = expiry
                frames.append(prepared)
            except Exception as exc:
                logger.warning('Long-term top options load failed for %s %s: %s', ticker, expiry, exc)
        if not frames:
            return []
        merged = pd.concat(frames, ignore_index=True)
        return self._p5_prepare_top_volume_records(merged, ticker, '')

    def _p5_load_strike_values(self, *_: Any) -> None:
        """Fetch all available strike values for the shared ticker."""
        ticker = self._p5_shared_ticker()
        if not ticker:
            self._p5_strike_available_strikes = []
            self._p5_reset_strike_combo()
            self._p5_set_strike_bucket_config(())
            self._p5_clear_strike_tables()
            self._p5_strike_payload = self._p5_empty_strike_payload()
            if hasattr(self, 'p5_strike_status_lbl'):
                self.set_status_text(self.p5_strike_status_lbl, 'Enter a ticker above, load strikes, then choose a strike to view matching options across all available expirations.', status='muted')
            return
        current_payload = getattr(self, '_p5_strike_payload', {})
        previous_ticker = str(current_payload.get('ticker', '') or '').upper().strip() if isinstance(current_payload, dict) else ''
        previous_selected = self._p5_selected_strike() if previous_ticker == ticker else None
        self._p5_strike_values_request_seq += 1
        request_id = self._p5_strike_values_request_seq
        self._p5_strike_values_latest_request_id = request_id
        self._p5_strike_latest_request_id = 0
        self._p5_strike_available_strikes = []
        self._p5_reset_strike_combo()
        self._p5_set_strike_bucket_config(())
        self._p5_strike_payload = self._p5_empty_strike_payload((), ticker=ticker)
        if hasattr(self, 'p5_strike_status_lbl'):
            self.set_status_text(self.p5_strike_status_lbl, f'Loading strikes for {ticker} across all available expirations...', status='warning')

        def _run() -> None:
            """Load all chains needed to build the strike dropdown."""
            try:
                expiries = self._get_cached_options_expiries(ticker)
                if expiries is None:
                    with YF_LOCK:
                        ticker_obj = yf.Ticker(ticker)
                        expiries = ticker_obj.options
                    if expiries:
                        self._save_cached_options_expiries(ticker, expiries)
                bucket_config = self._p5_build_dynamic_top_volume_bucket_config(expiries)
                strike_values = []
                for bucket_key, _bucket_label, _days_out in bucket_config:
                    try:
                        chain_df = self._get_cached_option_chain(ticker, bucket_key)
                        if chain_df is None or chain_df.empty or 'strike' not in chain_df.columns:
                            continue
                        strikes = pd.to_numeric(chain_df['strike'], errors='coerce').dropna()
                        strike_values.extend(float(value) for value in strikes.tolist())
                    except Exception as exc:
                        logger.warning('Strike list load failed for %s %s: %s', ticker, bucket_key, exc)
                if request_id != getattr(self, '_p5_strike_values_latest_request_id', 0):
                    return
                self._invoke_main.emit(
                    lambda rid=request_id, symbol=ticker, config=bucket_config, strikes=sorted(set(strike_values)), selected=previous_selected: self._p5_update_strike_values(
                        rid,
                        symbol,
                        config,
                        strikes,
                        selected,
                    )
                )
            except Exception as exc:
                logger.error('P5 strike list load failed for %s: %s', ticker, exc)
                if request_id != getattr(self, '_p5_strike_values_latest_request_id', 0):
                    return
                self._invoke_main.emit(lambda rid=request_id, symbol=ticker, message=str(exc): self._p5_handle_strike_values_error(rid, symbol, message))
        self._submit_options_fetch(_run)

    def _p5_update_strike_values(self, request_id: int, ticker: str, bucket_config: tuple[tuple[str, str, int], ...], strikes: list[float], selected_strike: float | None) -> None:
        """Apply a loaded strike list if it still matches the active ticker."""
        if request_id != getattr(self, '_p5_strike_values_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_strike_available_strikes = list(strikes or [])
        selected = None
        if selected_strike is not None:
            for strike_value in self._p5_strike_available_strikes:
                if abs(float(strike_value) - float(selected_strike)) <= self._P5_STRIKE_MATCH_TOLERANCE:
                    selected = float(strike_value)
                    break
        self._p5_reset_strike_combo(selected)
        self._p5_set_strike_bucket_config(bucket_config)
        self._p5_clear_strike_tables()
        self._p5_strike_payload = self._p5_empty_strike_payload(bucket_config, ticker=ticker, selected_strike=selected)
        self._p5_save_session_snapshot()
        expiry_count = len(bucket_config)
        strike_count = len(self._p5_strike_available_strikes)
        if not hasattr(self, 'p5_strike_status_lbl'):
            return
        if expiry_count <= 0:
            self.set_status_text(self.p5_strike_status_lbl, f'No listed options expirations were available for {ticker}.', status='warning')
        elif strike_count <= 0:
            self.set_status_text(self.p5_strike_status_lbl, f'No strikes were available for {ticker} across {expiry_count} expirations.', status='warning')
        elif selected is None:
            self.set_status_text(self.p5_strike_status_lbl, f'Loaded {strike_count} strikes for {ticker}. Choose a strike, then load options by strike.', status='positive')
        else:
            self.set_status_text(self.p5_strike_status_lbl, f'Loaded {strike_count} strikes for {ticker}. Selected strike {selected:g}.', status='positive')

    def _p5_handle_strike_values_error(self, request_id: int, ticker: str, message: str) -> None:
        """Render a strike-list load failure if the request is still current."""
        if request_id != getattr(self, '_p5_strike_values_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_strike_available_strikes = []
        self._p5_reset_strike_combo()
        self._p5_set_strike_bucket_config(())
        self._p5_clear_strike_tables()
        self._p5_strike_payload = self._p5_empty_strike_payload((), ticker=ticker)
        if hasattr(self, 'p5_strike_status_lbl'):
            self.set_status_text(self.p5_strike_status_lbl, f'Error loading strikes for {ticker}: {message}', status='negative')

    def _p5_load_options_by_strike(self, *_: Any) -> None:
        """Fetch and render all contracts matching the selected strike across expirations."""
        ticker = self._p5_shared_ticker()
        selected_strike = self._p5_selected_strike()
        if not ticker:
            self._p5_set_strike_bucket_config(())
            self._p5_clear_strike_tables()
            self._p5_strike_payload = self._p5_empty_strike_payload()
            if hasattr(self, 'p5_strike_status_lbl'):
                self.set_status_text(self.p5_strike_status_lbl, 'Enter a ticker above, load strikes, then choose a strike to view matching options across all available expirations.', status='muted')
            return
        if selected_strike is None:
            if hasattr(self, 'p5_strike_status_lbl'):
                self.set_status_text(self.p5_strike_status_lbl, 'Choose a strike before loading options by strike.', status='warning')
            return
        self._p5_strike_request_seq += 1
        request_id = self._p5_strike_request_seq
        self._p5_strike_latest_request_id = request_id
        self._p5_set_strike_bucket_config(())
        self._p5_strike_payload = self._p5_empty_strike_payload((), ticker=ticker, selected_strike=selected_strike)
        if hasattr(self, 'p5_strike_status_lbl'):
            self.set_status_text(self.p5_strike_status_lbl, f'Loading options by strike {selected_strike:g} for {ticker}...', status='warning')

        def _run() -> None:
            """Load and filter all expiration chains for one strike."""
            try:
                expiries = self._get_cached_options_expiries(ticker)
                if expiries is None:
                    with YF_LOCK:
                        ticker_obj = yf.Ticker(ticker)
                        expiries = ticker_obj.options
                    if expiries:
                        self._save_cached_options_expiries(ticker, expiries)
                bucket_config = self._p5_build_dynamic_top_volume_bucket_config(expiries)
                bucket_records = {bucket_key: [] for bucket_key, _, _ in bucket_config}
                bucket_expirations = {bucket_key: bucket_key for bucket_key, _, _ in bucket_config}
                for bucket_key, _bucket_label, _days_out in bucket_config:
                    try:
                        chain_df = self._get_cached_option_chain(ticker, bucket_key)
                        bucket_records[bucket_key] = self._p5_prepare_strike_records(chain_df, ticker, bucket_key, selected_strike)
                    except Exception as exc:
                        logger.warning('Options by strike load failed for %s %s %.4f: %s', ticker, bucket_key, selected_strike, exc)
                if request_id != getattr(self, '_p5_strike_latest_request_id', 0):
                    return
                self._invoke_main.emit(
                    lambda rid=request_id, symbol=ticker, strike=selected_strike, config=bucket_config, records=bucket_records, expirations=bucket_expirations: self._p5_update_strike_view(
                        rid,
                        symbol,
                        strike,
                        config,
                        records,
                        expirations,
                    )
                )
            except Exception as exc:
                logger.error('P5 options by strike load failed for %s %.4f: %s', ticker, selected_strike, exc)
                if request_id != getattr(self, '_p5_strike_latest_request_id', 0):
                    return
                self._invoke_main.emit(lambda rid=request_id, symbol=ticker, strike=selected_strike, message=str(exc): self._p5_handle_strike_error(rid, symbol, strike, message))
        self._submit_options_fetch(_run)

    def _p5_prepare_strike_records(self, chain_df: Any, ticker: str, expiry: str, selected_strike: float) -> list[dict[str, Any]]:
        """Normalize one chain and return rows matching the selected strike."""
        return prepare_strike_records(
            chain_df,
            ticker=ticker,
            expiry=expiry,
            selected_strike=selected_strike,
            tolerance=self._P5_STRIKE_MATCH_TOLERANCE,
            pd_module=pd,
        )

    def _p5_update_strike_view(self, request_id: int, ticker: str, selected_strike: float, bucket_config: tuple[tuple[str, str, int], ...], bucket_records: dict[str, list[dict[str, Any]]], bucket_expirations: dict[str, str]) -> None:
        """Store and render the latest Options by Strike payload."""
        if request_id != getattr(self, '_p5_strike_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_set_strike_bucket_config(bucket_config)
        normalized_payload = self._p5_normalize_strike_payload(
            {
                'ticker': ticker,
                'selected_strike': selected_strike,
                'available_strikes': list(getattr(self, '_p5_strike_available_strikes', []) or []),
                'bucket_order': [bucket_key for bucket_key, _, _ in bucket_config],
                'records': bucket_records,
                'expirations': bucket_expirations,
            },
            ticker=ticker,
        )
        normalized_records = normalized_payload.get('records', {}) if isinstance(normalized_payload.get('records', {}), dict) else {}
        normalized_expirations = normalized_payload.get('expirations', {}) if isinstance(normalized_payload.get('expirations', {}), dict) else {}
        self._p5_strike_payload = normalized_payload
        self._p5_save_session_snapshot()
        self._p5_render_strike_tables(ticker, selected_strike, normalized_records, normalized_expirations)
        row_total = sum(len(records) for records in normalized_records.values())
        expiry_count = len(normalized_payload.get('bucket_order', []))
        populated_count = sum(1 for records in normalized_records.values() if records)
        if not hasattr(self, 'p5_strike_status_lbl'):
            return
        if expiry_count <= 0:
            self.set_status_text(self.p5_strike_status_lbl, f'No listed options expirations were available for {ticker}.', status='warning')
            return
        if row_total <= 0:
            self.set_status_text(self.p5_strike_status_lbl, f'No options by strike data was available for {ticker} at strike {selected_strike:g} across {expiry_count} expirations.', status='warning')
            return
        status_text = f"Options by Strike updated for {ticker} strike {selected_strike:g} at {datetime.datetime.now().strftime('%H:%M:%S')}"
        status_text += f' | {row_total} rows across {expiry_count} expirations'
        if populated_count < expiry_count:
            status_text += f' | {expiry_count - populated_count} expirations returned no matching rows'
        self.set_status_text(self.p5_strike_status_lbl, status_text, status='positive' if populated_count == expiry_count else 'warning')

    def _p5_handle_strike_error(self, request_id: int, ticker: str, selected_strike: float, message: str) -> None:
        """Render an Options by Strike load failure if the request is still current."""
        if request_id != getattr(self, '_p5_strike_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_set_strike_bucket_config(())
        self._p5_clear_strike_tables()
        self._p5_strike_payload = self._p5_empty_strike_payload((), ticker=ticker, selected_strike=selected_strike)
        if hasattr(self, 'p5_strike_status_lbl'):
            self.set_status_text(self.p5_strike_status_lbl, f'Error loading options by strike for {ticker}: {message}', status='negative')

    def _p5_render_strike_tables(self, ticker: str, selected_strike: float | None, bucket_records: dict[str, list[dict[str, Any]]], bucket_expirations: dict[str, str]) -> None:
        """Render strike-matched records into the UI tables."""
        sections = getattr(self, 'p5_strike_sections', {}) if isinstance(getattr(self, 'p5_strike_sections', {}), dict) else {}
        for bucket_key, _bucket_label, _days_out in self._p5_strike_buckets():
            section = sections.get(bucket_key, {})
            table = section.get('table')
            expiry = str(bucket_expirations.get(bucket_key, '') or '')
            expiry_display = self._p5_format_top_volume_expiration(expiry)
            self._p5_set_strike_bucket_title(bucket_key, expiry)
            if table is None:
                continue
            strike_text = f'{selected_strike:g}' if selected_strike is not None else 'unselected'
            table.setToolTip(f'Using expiration {expiry_display} and strike {strike_text}' if expiry_display else f'No expiration available for strike {strike_text}')
            render_table_rows(
                table,
                build_option_summary_rows(
                    bucket_records.get(bucket_key, []),
                    ticker=ticker,
                    expiry=expiry,
                    positive_color=self.theme_color('accent_positive'),
                    negative_color=self.theme_color('accent_negative'),
                    pd_module=pd,
                ),
            )

    def _p5_update_top_volume_view(self, view_key: str, request_id: int, ticker: str, bucket_config: tuple[tuple[str, str, int], ...], bucket_records: dict[str, list[dict[str, Any]]], bucket_expirations: dict[str, str]) -> None:
        """Store and render the latest all-expiry top-volume payload."""
        if request_id != getattr(self, '_p5_top_volume_latest_request_ids', {}).get(view_key, 0):
            return
        view = self._p5_top_volume_view(view_key)
        status_lbl = view.get('status_lbl')
        tab_label = str(view.get('tab_label', 'Top Options') or 'Top Options')
        self._p5_set_top_volume_bucket_config(view_key, bucket_config)
        normalized_payload = self._p5_normalize_top_volume_payload(
            {
                'ticker': ticker,
                'type_filter': self._p5_normalize_top_volume_type_filter(getattr(self, '_p5_top_volume_type_filter', 'both')),
                'bucket_order': [bucket_key for bucket_key, _, _ in bucket_config],
                'records': bucket_records,
                'expirations': bucket_expirations,
            },
            ticker=ticker,
        )
        normalized_records = normalized_payload.get('records', {}) if isinstance(normalized_payload.get('records', {}), dict) else {}
        normalized_expirations = normalized_payload.get('expirations', {}) if isinstance(normalized_payload.get('expirations', {}), dict) else {}
        self._p5_top_volume_payloads[view_key] = normalized_payload
        self._p5_save_session_snapshot()
        self._p5_render_top_volume_tables(view_key, ticker, normalized_records, normalized_expirations)
        row_total = sum(len(records) for records in normalized_records.values())
        expiry_count = len(normalized_payload.get('bucket_order', []))
        populated_count = sum(1 for records in normalized_records.values() if records)
        if expiry_count <= 0:
            if status_lbl is not None:
                self.set_status_text(status_lbl, f'No listed options expirations were available for {ticker}.', status='warning')
            return
        if row_total <= 0:
            status_text = f'No {tab_label.lower()} data was available for {ticker} across {expiry_count} expirations.'
            if status_lbl is not None:
                self.set_status_text(status_lbl, status_text, status='warning')
            return
        status_text = f"{tab_label} ({self._p5_top_volume_type_label()}) updated for {ticker} at {datetime.datetime.now().strftime('%H:%M:%S')}"
        status_text += f' | {row_total} rows across {expiry_count} expirations'
        if populated_count < expiry_count:
            status_text += f' | {expiry_count - populated_count} expirations returned no ranked rows'
        if status_lbl is not None:
            self.set_status_text(status_lbl, status_text, status='positive' if populated_count == expiry_count else 'warning')

    def _p5_handle_top_volume_error(self, view_key: str, request_id: int, ticker: str, message: str) -> None:
        """Render a top-volume load failure if the request is still current."""
        if request_id != getattr(self, '_p5_top_volume_latest_request_ids', {}).get(view_key, 0):
            return
        view = self._p5_top_volume_view(view_key)
        status_lbl = view.get('status_lbl')
        tab_label = str(view.get('tab_label', 'Top Options') or 'Top Options')
        self._p5_set_top_volume_bucket_config(view_key, ())
        self._p5_clear_top_volume_tables(view_key)
        self._p5_top_volume_payloads[view_key] = self._p5_empty_top_volume_payload((), ticker=ticker)
        if status_lbl is not None:
            self.set_status_text(status_lbl, f'Error loading {tab_label.lower()} for {ticker}: {message}', status='negative')

    def _p5_render_top_volume_tables(self, view_key: str, ticker: str, bucket_records: dict[str, list[dict[str, Any]]], bucket_expirations: dict[str, str]) -> None:
        """Render the cached top-volume bucket records into the UI tables."""
        view = self._p5_top_volume_view(view_key)
        sections = view.get('sections', {}) if isinstance(view.get('sections', {}), dict) else {}
        for bucket_key, _bucket_label, _days_out in self._p5_top_volume_buckets(view_key):
            section = sections.get(bucket_key, {})
            table = section.get('table')
            expiry = str(bucket_expirations.get(bucket_key, '') or '')
            expiry_display = self._p5_format_top_volume_expiration(expiry)
            self._p5_set_top_volume_bucket_title(view_key, bucket_key, expiry)
            if table is None:
                continue
            table.setToolTip(f'Using expiration {expiry_display}' if expiry_display else 'No expiration available')
            render_table_rows(
                table,
                build_option_summary_rows(
                    bucket_records.get(bucket_key, []),
                    ticker=ticker,
                    expiry=expiry,
                    positive_color=self.theme_color('accent_positive'),
                    negative_color=self.theme_color('accent_negative'),
                    pd_module=pd,
                ),
            )

    def _p5_load_expiries(self) -> None:
        """Fetch available expiry dates for the entered ticker."""
        ticker = self._p5_shared_ticker()
        if not ticker:
            self.set_status_text(self.p5_status_lbl, 'Enter a ticker above to view the full options chain.', status='muted')
            return
        preferred_expiry = str(self.p5_expiry_combo.currentData() or getattr(self, '_p5_chain_expiry', '') or '').strip()
        self._p5_expiry_request_seq += 1
        request_id = self._p5_expiry_request_seq
        self._p5_expiry_latest_request_id = request_id
        self.set_status_text(self.p5_status_lbl, f'Fetching expiries for {ticker}...', status='warning')
        self.p5_expiry_combo.blockSignals(True)
        self.p5_expiry_combo.clear()
        self.p5_expiry_combo.blockSignals(False)

        def _run() -> None:
            """Fetch expiries and current spot."""
            try:
                price = None
                try:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        price = float(t_obj.fast_info['lastPrice'])
                except Exception as pe:
                    logger.warning(f'Failed to fetch price for {ticker}: {pe}')
                exps = self._get_cached_options_expiries(ticker)

                self._invoke_main.emit(
                    lambda rid=request_id, symbol=ticker, expiries=exps, spot=price, selected=preferred_expiry: self._p5_handle_loaded_expiries(
                        rid,
                        symbol,
                        expiries,
                        spot,
                        preferred_expiry=selected,
                    )
                )
            except Exception as e:
                logger.error(f'P5 expiry fetch failed for {ticker}: {e}')
                self._invoke_main.emit(lambda rid=request_id, message=str(e): self._p5_handle_expiry_error(rid, message))
        self._submit_options_fetch(_run)

    def _p5_handle_loaded_expiries(
        self,
        request_id: int,
        ticker: str,
        exps: Any,
        price: float | None,
        *,
        preferred_expiry: str='',
    ) -> None:
        """Apply one expiry fetch only when it is still current."""
        if request_id != getattr(self, '_p5_expiry_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_chain_spot_price = float(price or 0.0)
        self._p5_populate_expiries(exps, preferred_expiry=preferred_expiry)
        if price:
            self.p5_price_lbl.setText(f'${float(price):.2f}')
        else:
            self.p5_price_lbl.setText('')

    def _p5_handle_expiry_error(self, request_id: int, message: str) -> None:
        """Show an expiry-fetch failure only when it is still current."""
        if request_id != getattr(self, '_p5_expiry_latest_request_id', 0):
            return
        self.set_status_text(self.p5_status_lbl, f'Error: {message}', status='negative')

    def _p5_populate_expiries(self, exps: Any, *, preferred_expiry: str='') -> None:
        """Populate the expiry selector."""
        live_exps = self._p5_filter_live_expiries(exps)
        if not live_exps:
            self.p5_expiry_combo.blockSignals(True)
            self.p5_expiry_combo.clear()
            self.p5_expiry_combo.blockSignals(False)
            self._p5_populate_tables(pd.DataFrame(), '')
            self.set_status_text(self.p5_status_lbl, f'No current listed options expirations were available for {self._p5_shared_ticker() or "ticker"}.', status='warning')
            return
        self.p5_expiry_combo.blockSignals(True)
        self.p5_expiry_combo.clear()
        today = self._p5_current_options_market_date()
        preferred = str(preferred_expiry or '').strip()
        if self._p5_is_past_expiry(preferred):
            preferred = ''
        for exp in live_exps:
            try:
                ed = datetime.datetime.strptime(exp, '%Y-%m-%d').date()
                dte = (ed - today).days
                self.p5_expiry_combo.addItem(f'{exp} ({dte}d)', exp)
            except Exception:
                self.p5_expiry_combo.addItem(exp, exp)
        preferred_index = self.p5_expiry_combo.findData(preferred) if preferred else -1
        self.p5_expiry_combo.setCurrentIndex(preferred_index if preferred_index >= 0 else 0)
        self.p5_expiry_combo.blockSignals(False)
        self.set_status_text(self.p5_status_lbl, 'Expiries loaded.', status='positive')
        self._p5_load_chain()

    def _p5_load_chain(self) -> None:
        """Load and render the selected options chain."""
        ticker = self._p5_shared_ticker()
        expiry = self.p5_expiry_combo.currentData()
        if not ticker or not expiry:
            return
        if self._p5_is_past_expiry(expiry):
            self._p5_populate_tables(pd.DataFrame(), '')
            self.set_status_text(self.p5_status_lbl, f'Option expiry {expiry} has passed. Choose a current expiration.', status='warning')
            return
        self._p5_chain_request_seq += 1
        request_id = self._p5_chain_request_seq
        self._p5_chain_latest_request_id = request_id
        self.set_status_text(self.p5_status_lbl, f'Loading {ticker} {expiry} chain...', status='warning')
        spot_price = float(getattr(self, '_p5_chain_spot_price', 0.0) or 0.0)

        def _run() -> None:
            """Load raw chain, enrich it, and update the UI."""
            try:
                current_spot = spot_price
                if current_spot <= 0:
                    try:
                        with YF_LOCK:
                            current_spot = float(yf.Ticker(ticker).fast_info['lastPrice'])
                    except Exception as pe:
                        logger.warning(f'Failed to refresh spot price for {ticker}: {pe}')
                df = self._get_cached_option_chain(ticker, expiry)
                if df is None or df.empty:
                    raise ValueError(f'No option chain returned for {ticker} {expiry}.')
                greek_inputs = self._p5_resolve_greek_inputs(ticker, current_spot)
                current_spot = float(greek_inputs.get('spot_price', current_spot) or current_spot or 0.0)
                enriched = self._p5_enrich_chain(
                    df,
                    expiry,
                    current_spot,
                    float(greek_inputs.get('risk_free_rate', 0.0) or 0.0),
                    float(greek_inputs.get('dividend_yield', 0.0) or 0.0),
                )
                self._invoke_main.emit(
                    lambda rid=request_id, symbol=ticker, frame=enriched, exp=expiry, spot=current_spot, inputs=greek_inputs: self._p5_handle_loaded_chain(
                        rid,
                        symbol,
                        frame,
                        exp,
                        spot,
                        inputs,
                    )
                )
            except Exception as e:
                logger.error(f'P5 chain load failed for {ticker} {expiry}: {e}')
                self._invoke_main.emit(lambda rid=request_id, message=str(e): self._p5_handle_chain_error(rid, message))
        self._submit_options_fetch(_run)

    def _p5_handle_loaded_chain(
        self,
        request_id: int,
        ticker: str,
        df: Any,
        expiry: str,
        spot_price: float,
        greek_inputs: dict[str, Any],
    ) -> None:
        """Apply one chain response only when it is still current."""
        if request_id != getattr(self, '_p5_chain_latest_request_id', 0):
            return
        if ticker != self._p5_shared_ticker():
            return
        self._p5_update_chain_view(ticker, df, expiry, spot_price, greek_inputs)

    def _p5_handle_chain_error(self, request_id: int, message: str) -> None:
        """Show a chain-load failure only when it is still current."""
        if request_id != getattr(self, '_p5_chain_latest_request_id', 0):
            return
        self.set_status_text(self.p5_status_lbl, f'Error: {message}', status='negative')

    def _p5_enrich_chain(self, df: Any, expiry: str, spot_price: float, risk_free_rate: float, dividend_yield: float) -> Any:
        """Add UI-ready market and Greek columns to the raw chain data."""
        if df is None:
            return pd.DataFrame()
        enriched = df.copy()
        if 'type' not in enriched.columns:
            enriched['type'] = ''
        enriched['type'] = enriched['type'].fillna('')
        enriched['iv_percent'] = pd.to_numeric(enriched.get('impliedVolatility', 0), errors='coerce').fillna(0.0) * 100.0
        market_cols = ['strike', 'lastPrice', 'bid', 'ask', 'change', 'volume', 'openInterest', 'impliedVolatility']
        for col in market_cols:
            if col not in enriched.columns:
                enriched[col] = 0.0
            enriched[col] = pd.to_numeric(enriched[col], errors='coerce')
        # Fill missing IVs from option prices (e.g. when market is closed and yfinance returns 0)
        iv_col = enriched['impliedVolatility']
        needs_iv = iv_col.isna() | (iv_col <= 0)
        if needs_iv.any() and spot_price > 0:
            for idx in enriched.index[needs_iv]:
                row = enriched.loc[idx]
                bid = float(row.get('bid', 0) or 0)
                ask = float(row.get('ask', 0) or 0)
                last = float(row.get('lastPrice', 0) or 0)
                price = ((bid + ask) / 2) if (bid > 0 and ask > 0) else last
                computed_iv = self._p5_implied_vol(
                    spot_price,
                    float(row.get('strike', 0) or 0),
                    expiry,
                    risk_free_rate,
                    dividend_yield,
                    price,
                    str(row.get('type', '')).strip().lower(),
                )
                if computed_iv > 0:
                    enriched.at[idx, 'impliedVolatility'] = computed_iv
            enriched['iv_percent'] = pd.to_numeric(enriched['impliedVolatility'], errors='coerce').fillna(0.0) * 100.0
        greeks = enriched.apply(
            lambda row: pd.Series(
                self._p5_calc_greeks(
                    spot_price,
                    float(row.get('strike', 0.0) or 0.0),
                    expiry,
                    float(row.get('impliedVolatility', 0.0) or 0.0),
                    str(row.get('type', '')).strip().lower(),
                    risk_free_rate,
                    dividend_yield,
                )
            ),
            axis=1,
        )
        for col in ('delta_calc', 'gamma_calc', 'theta_calc', 'vega_calc', 'rho_calc', 'greeks_valid'):
            enriched[col] = greeks[col] if col in greeks else None
        return enriched

    def _p5_update_chain_view(self, ticker: str, df: Any, expiry: str, spot_price: float, greek_inputs: dict[str, Any]) -> None:
        """Store the latest spot value and redraw the chain tables."""
        self._p5_chain_ticker = str(ticker or '').upper().strip()
        self._p5_chain_spot_price = spot_price or 0.0
        self._p5_chain_rate = float(greek_inputs.get('risk_free_rate', 0.0) or 0.0)
        self._p5_chain_dividend_yield = float(greek_inputs.get('dividend_yield', 0.0) or 0.0)
        self._p5_chain_rate_source = str(greek_inputs.get('rate_source', 'default') or 'default')
        self._p5_chain_dividend_source = str(greek_inputs.get('dividend_source', 'default') or 'default')
        if spot_price:
            self.p5_price_lbl.setText(f'${spot_price:.2f}')
        self._p5_populate_tables(df, expiry)
        self._p5_save_session_snapshot()

    def _p5_escape_markdown_cell(self, value: Any) -> str:
        """Sanitize plain values for Markdown table cells."""
        if value is None:
            return ''
        try:
            if pd.isna(value):
                return ''
        except Exception:
            pass
        return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').strip()

    def _p5_format_option_export_value(self, value: Any, *, decimals: int=2, integer: bool=False) -> str:
        """Render one top-options export cell."""
        if value is None:
            return ''
        try:
            if pd.isna(value):
                return ''
        except Exception:
            pass
        try:
            if integer:
                return f'{int(float(value)):,}'
            return f'{float(value):,.{decimals}f}'
        except (TypeError, ValueError, OverflowError):
            return self._p5_escape_markdown_cell(value)

    def _p5_copy_export_to_clipboard(self, text: str, success_message: str, *, target_status_label: Any=None) -> bool:
        """Copy export text to the clipboard and update status labels."""
        try:
            QApplication.clipboard().setText(text)
        except Exception as exc:
            if target_status_label is not None:
                self.set_status_text(target_status_label, f'Export failed: {exc}', status='negative')
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, f'Export failed: {exc}', status='negative')
            QMessageBox.critical(self, 'Export Failed', f'Unable to copy export to the clipboard.\n\n{exc}')
            return False
        if target_status_label is not None:
            self.set_status_text(target_status_label, success_message, status='positive')
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, success_message, status='positive')
        return True

    def _p5_build_chain_export_table(self, df: Any) -> list[str]:
        """Convert one side of the chain into a Markdown table."""
        if df is None or df.empty:
            return ['No rows available.', '']
        lines = [
            '| ' + ' | '.join(label for label, _, _ in self._P5_CHAIN_COLUMNS) + ' |',
            '| ' + ' | '.join('---:' if label not in ('IV',) else '---' for label, _, _ in self._P5_CHAIN_COLUMNS) + ' |',
        ]
        for _idx, row in df.iterrows():
            cells = []
            for _label, key, fmt in self._P5_CHAIN_COLUMNS:
                value = row.get(key)
                cells.append(self._p5_escape_markdown_cell(self._p5_format_chain_value(value, fmt)))
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines.append('')
        return lines

    def _p5_build_chain_export(self) -> str:
        """Build a Markdown export for the currently loaded chain view."""
        ticker = str(getattr(self, '_p5_chain_ticker', '') or '').upper().strip()
        expiry = str(getattr(self, '_p5_chain_expiry', '') or '').strip()
        strategy = str(self.p5_strategy_combo.currentText() if hasattr(self, 'p5_strategy_combo') else 'None' or 'None')
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        calls = self._p5_chain_df[self._p5_chain_df['type'] == 'Call'].sort_values('strike').reset_index(drop=True)
        puts = self._p5_chain_df[self._p5_chain_df['type'] == 'Put'].sort_values('strike').reset_index(drop=True)
        lines = [
            f'# Options Chain Export - {ticker}',
            '',
            f'- Symbol: {ticker}',
            f'- Expiration: {expiry or "Unavailable"}',
            f'- Spot Price: {self._p5_format_option_export_value(getattr(self, "_p5_chain_spot_price", 0.0))}',
            f'- Risk-Free Rate: {self._p5_chain_rate * 100:.2f}% ({self._p5_chain_rate_source})',
            f'- Dividend Yield: {self._p5_chain_dividend_yield * 100:.2f}% ({self._p5_chain_dividend_source})',
            f'- Strategy View: {strategy}',
            f'- Exported At: {exported_at}',
            '',
            '## Context',
            '',
            'This is the currently loaded options chain for one expiry. Analyze liquidity, strike positioning, implied volatility, and call-versus-put structure from the quoted market data and calculated Greeks.',
            '',
            '## Calls',
            '',
        ]
        lines.extend(self._p5_build_chain_export_table(calls))
        lines.extend([
            '## Puts',
            '',
        ])
        lines.extend(self._p5_build_chain_export_table(puts))
        return '\n'.join(lines).rstrip() + '\n'

    def _p5_export_chain(self) -> None:
        """Copy the current chain snapshot to the clipboard for external analysis."""
        ticker = str(getattr(self, '_p5_chain_ticker', '') or '').upper().strip()
        if not ticker or getattr(self, '_p5_chain_df', pd.DataFrame()).empty or not str(getattr(self, '_p5_chain_expiry', '') or '').strip():
            self.set_status_text(self.p5_status_lbl, 'No chain data is currently loaded to export.', status='warning')
            QMessageBox.warning(self, 'No Chain Data', 'No options chain is currently loaded. Load a chain first, then export it.')
            return
        self._p5_copy_export_to_clipboard(
            self._p5_build_chain_export(),
            f'Chain export copied to clipboard for {ticker} {self._p5_chain_expiry}',
            target_status_label=self.p5_status_lbl,
        )

    def _p5_build_top_options_timeframe_export(self, view_key: str, tab_label: str, payload: dict[str, Any], bucket_config: tuple[tuple[str, str, int], ...]) -> list[str]:
        """Build one all-expiry section for the top-options export."""
        ticker = str(payload.get('ticker', '') or '').upper().strip()
        type_label = self._p5_top_volume_type_label(payload.get('type_filter', getattr(self, '_p5_top_volume_type_filter', 'both')))
        records_by_bucket = payload.get('records', {}) if isinstance(payload.get('records', {}), dict) else {}
        expirations = payload.get('expirations', {}) if isinstance(payload.get('expirations', {}), dict) else {}
        lines = [
            f'## {tab_label}',
            '',
            f'- Symbol: {ticker or "Unavailable"}',
            f'- Option Type Filter: {type_label}',
            f'- Expirations captured: {len(bucket_config)}',
            '',
            'This section lists the highest-volume contracts for every expiration returned by yfinance for the loaded ticker.',
            '',
        ]
        for bucket_key, bucket_label, _days_out in bucket_config:
            bucket_records = list(records_by_bucket.get(bucket_key, []))
            selected_expiration = str(expirations.get(bucket_key, '') or bucket_key or '')
            expiration_heading = self._p5_format_top_volume_expiration(selected_expiration) or self._p5_format_top_volume_expiration(bucket_label) or bucket_label
            lines.extend([
                f'### {expiration_heading}',
                '',
                f'- Selected expiration: {selected_expiration or "Unavailable"}',
                f'- Rows exported: {len(bucket_records)}',
                '',
            ])
            if not bucket_records:
                lines.extend([
                    'No top options volume records were available for this expiration.',
                    '',
                ])
                continue
            lines.extend([
                '| Ticker | Type | Strike | Expiration | Last Price | Volume |',
                '| --- | --- | ---: | --- | ---: | ---: |',
            ])
            for opt in bucket_records:
                lines.append(
                    '| {ticker} | {type_} | {strike} | {expiration} | {last_price} | {volume} |'.format(
                        ticker=self._p5_escape_markdown_cell(str(opt.get('ticker', ticker) or ticker)),
                        type_=self._p5_escape_markdown_cell(str(opt.get('type', '') or '')),
                        strike=self._p5_format_option_export_value(opt.get('strike'), decimals=1),
                        expiration=self._p5_escape_markdown_cell(str(opt.get('expiration', '') or selected_expiration)),
                        last_price=self._p5_format_option_export_value(opt.get('lastPrice')),
                        volume=self._p5_format_option_export_value(opt.get('volume', 0), integer=True),
                    )
                )
            lines.append('')
        return lines

    def _p5_build_top_options_export(self) -> str:
        """Build a combined Markdown export for the dynamic all-expiry top-options view."""
        exported_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        shared_ticker = self._p5_shared_ticker()
        loaded_symbols = sorted(
            {
                str(payload.get('ticker', '') or '').upper().strip()
                for payload in getattr(self, '_p5_top_volume_payloads', {}).values()
                if isinstance(payload, dict) and str(payload.get('ticker', '') or '').strip()
            }
        )
        symbol_summary = ', '.join(loaded_symbols) if loaded_symbols else 'Unavailable'
        type_label = self._p5_top_volume_type_label()
        lines = [
            '# Top Options by Volume Export',
            '',
            f'- Current Input Symbol: {shared_ticker or "Unavailable"}',
            f'- Loaded Symbols: {symbol_summary}',
            f'- Option Type Filter: {type_label}',
            f'- Exported At: {exported_at}',
            '',
            '## Context',
            '',
            'This export captures one ranked top-volume options table for every expiration currently returned by yfinance for the loaded ticker. Analyze call-versus-put skew, strike clustering, and volume concentration by expiration while noting that the data is still a ranked snapshot rather than full order-flow context.',
            '',
        ]
        for view_key, tab_label, _bucket_config in self._P5_TOP_VOLUME_TAB_CONFIGS:
            payload = getattr(self, '_p5_top_volume_payloads', {}).get(view_key, {})
            if not isinstance(payload, dict):
                payload = self._p5_empty_top_volume_payload(())
            normalized_payload = self._p5_normalize_top_volume_payload(payload)
            bucket_config = self._p5_build_dynamic_top_volume_bucket_config(normalized_payload.get('bucket_order', []))
            lines.extend(self._p5_build_top_options_timeframe_export(view_key, tab_label, normalized_payload, bucket_config))
        return '\n'.join(lines).rstrip() + '\n'

    def _p5_export_top_options_by_volume(self) -> None:
        """Copy the dynamic all-expiry top-options payload to the clipboard for external analysis."""
        payloads = getattr(self, '_p5_top_volume_payloads', {})
        total_rows = 0
        for view_key, _tab_label, _bucket_config in self._P5_TOP_VOLUME_TAB_CONFIGS:
            payload = payloads.get(view_key, {})
            normalized_payload = self._p5_normalize_top_volume_payload(payload) if isinstance(payload, dict) else self._p5_empty_top_volume_payload(())
            records = normalized_payload.get('records', {}) if isinstance(normalized_payload.get('records', {}), dict) else {}
            total_rows += sum(len(list(rows)) for rows in records.values())
        if total_rows <= 0:
            if hasattr(self, 'status_bar'):
                self.set_status_text(self.status_bar, 'No options by top volume data is currently loaded to export.', status='warning')
            QMessageBox.warning(
                self,
                'No Top Options Data',
                'No options by top volume data is currently loaded. Load the Options page data first, then export it.',
            )
            return
        self._p5_copy_export_to_clipboard(
            self._p5_build_top_options_export(),
            'Options by top volume export copied to clipboard',
        )

    def _p5_implied_vol(self, spot: float, strike: float, expiry: str, risk_free_rate: float, dividend_yield: float, market_price: float, option_type: str) -> float:
        """Newton-Raphson solver to back out implied volatility from an option price."""
        if market_price <= 0 or spot <= 0 or strike <= 0 or option_type not in ('call', 'put'):
            return 0.0
        try:
            exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        except ValueError:
            return 0.0
        dte_days = max((exp_date - datetime.date.today()).days, 0)
        t = max(dte_days / 365.0, 1.0 / 365.0)
        rate = min(max(float(risk_free_rate), 0.0), 1.0)
        dividend = min(max(float(dividend_yield), 0.0), 1.0)
        normal = NormalDist()
        exp_neg_qt = math.exp(-dividend * t)
        exp_neg_rt = math.exp(-rate * t)
        sqrt_t = math.sqrt(t)
        sigma = 0.3
        for _ in range(30):
            denom = sigma * sqrt_t
            if denom <= 0:
                return 0.0
            d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * t) / denom
            d2 = d1 - denom
            pdf_d1 = normal.pdf(d1)
            if option_type == 'call':
                bs_price = spot * exp_neg_qt * normal.cdf(d1) - strike * exp_neg_rt * normal.cdf(d2)
            else:
                bs_price = strike * exp_neg_rt * normal.cdf(-d2) - spot * exp_neg_qt * normal.cdf(-d1)
            vega = spot * exp_neg_qt * pdf_d1 * sqrt_t
            if vega < 1e-12:
                break
            sigma -= (bs_price - market_price) / vega
            sigma = max(0.001, min(sigma, 10.0))
            if abs(bs_price - market_price) < 0.001:
                return sigma
        return 0.0

    def _p5_calc_greeks(self, spot: float, strike: float, expiry: str, iv: float, option_type: str, risk_free_rate: float, dividend_yield: float) -> dict[str, Any]:
        """Compute Black-Scholes Greeks for one option row."""
        if spot <= 0 or strike <= 0 or iv <= 0 or option_type not in ('call', 'put'):
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        try:
            exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        except ValueError:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        dte_days = max((exp_date - datetime.date.today()).days, 0)
        t = max(dte_days / 365.0, 1.0 / 365.0)
        sigma = float(iv)
        if sigma <= 0:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        sqrt_t = math.sqrt(t)
        denom = sigma * sqrt_t
        if denom <= 0:
            return {
                'delta_calc': None,
                'gamma_calc': None,
                'theta_calc': None,
                'vega_calc': None,
                'rho_calc': None,
                'greeks_valid': False,
            }
        normal = NormalDist()
        rate = min(max(float(risk_free_rate), 0.0), 1.0)
        dividend = min(max(float(dividend_yield), 0.0), 1.0)
        exp_neg_qt = math.exp(-dividend * t)
        exp_neg_rt = math.exp(-rate * t)
        d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * t) / denom
        d2 = d1 - denom
        pdf_d1 = normal.pdf(d1)
        if option_type == 'call':
            delta = exp_neg_qt * normal.cdf(d1)
            theta_year = (-(spot * exp_neg_qt * pdf_d1 * sigma) / (2 * sqrt_t)) - (rate * strike * exp_neg_rt * normal.cdf(d2)) + (dividend * spot * exp_neg_qt * normal.cdf(d1))
            rho = (strike * t * exp_neg_rt * normal.cdf(d2)) / 100.0
        else:
            delta = exp_neg_qt * (normal.cdf(d1) - 1.0)
            theta_year = (-(spot * exp_neg_qt * pdf_d1 * sigma) / (2 * sqrt_t)) + (rate * strike * exp_neg_rt * normal.cdf(-d2)) - (dividend * spot * exp_neg_qt * normal.cdf(-d1))
            rho = (-strike * t * exp_neg_rt * normal.cdf(-d2)) / 100.0
        gamma = (exp_neg_qt * pdf_d1) / (spot * denom)
        vega = (spot * exp_neg_qt * pdf_d1 * sqrt_t) / 100.0
        theta = theta_year / 365.0
        return {
            'delta_calc': delta,
            'gamma_calc': gamma,
            'theta_calc': theta,
            'vega_calc': vega,
            'rho_calc': rho,
            'greeks_valid': True,
        }

    def _p5_resolve_greek_inputs(self, ticker: str, spot_price: float) -> dict[str, Any]:
        """Resolve market inputs used by the options-chain Greek calculations."""
        settings = load_options_chain_settings()
        fallback_rate = float(settings.get('default_risk_free_rate', 0.04) or 0.04)
        resolved_spot = float(spot_price or 0.0)
        rate = fallback_rate
        rate_source = 'config'
        dividend_yield = 0.0
        dividend_source = 'default'
        info: dict[str, Any] = {}
        try:
            with YF_LOCK:
                ticker_obj = yf.Ticker(ticker)
                if resolved_spot <= 0:
                    try:
                        resolved_spot = float(ticker_obj.fast_info['lastPrice'])
                    except Exception:
                        resolved_spot = float(resolved_spot or 0.0)
                try:
                    info = ticker_obj.info or {}
                except Exception:
                    info = {}
            market_rate = self._p5_fetch_market_rate()
            if market_rate is not None:
                rate = market_rate
                rate_source = 'market'
                save_options_chain_settings({'default_risk_free_rate': market_rate})
        except Exception as exc:
            logger.warning(f'Failed to resolve market inputs for {ticker}: {exc}')
        extracted_dividend = self._p5_extract_dividend_yield(info)
        if extracted_dividend is not None:
            dividend_yield = extracted_dividend
            dividend_source = 'ticker'
        return {
            'spot_price': resolved_spot,
            'risk_free_rate': rate,
            'rate_source': rate_source,
            'dividend_yield': dividend_yield,
            'dividend_source': dividend_source,
        }

    def _p5_fetch_market_rate(self) -> float | None:
        """Use the 13-week Treasury yield index as a simple risk-free proxy."""
        try:
            with YF_LOCK:
                rate_ticker = yf.Ticker('^IRX')
                fast_info = getattr(rate_ticker, 'fast_info', {}) or {}
                raw_value = fast_info.get('lastPrice')
                if raw_value in (None, 0):
                    info = rate_ticker.info or {}
                    raw_value = info.get('regularMarketPrice') or info.get('previousClose') or info.get('currentPrice')
        except Exception as exc:
            logger.warning(f'Failed to fetch ^IRX risk-free proxy: {exc}')
            return None
        try:
            rate_value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if rate_value <= 0:
            return None
        if rate_value > 1.0:
            rate_value /= 100.0
        return min(max(rate_value, 0.0), 1.0)

    def _p5_extract_dividend_yield(self, info: Any) -> float | None:
        """Extract dividend yield from the ticker quote payload when present."""
        if not isinstance(info, dict):
            return None
        for key in ('dividendYield', 'trailingAnnualDividendYield'):
            raw_value = info.get(key)
            try:
                yield_value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if yield_value < 0:
                continue
            if yield_value > 1.0:
                yield_value /= 100.0
            return min(max(yield_value, 0.0), 1.0)
        return None

    def _p5_refresh_strategy_view(self) -> None:
        """Reapply recommendation styling for the current strategy."""
        if not getattr(self, '_p5_chain_df', pd.DataFrame()).empty:
            self._p5_populate_tables(self._p5_chain_df, self._p5_chain_expiry)

    def _p5_populate_tables(self, df: Any, expiry: str) -> Any:
        """Render calls and puts tables, including strategy highlights."""
        self._p5_chain_df = df.copy() if df is not None else pd.DataFrame()
        self._p5_chain_expiry = expiry
        render_table_rows(self.p5_calls_table, ())
        render_table_rows(self.p5_puts_table, ())
        if df is None or df.empty:
            self.set_status_text(self.p5_status_lbl, 'No chain data available.', status='muted')
            return
        calls = df[df['type'] == 'Call'].sort_values('strike').reset_index(drop=True)
        puts = df[df['type'] == 'Put'].sort_values('strike').reset_index(drop=True)
        strategy = self.p5_strategy_combo.currentText()
        call_ranks, call_details = self._p5_rank_strategy_rows(calls, strategy)
        put_ranks, put_details = self._p5_rank_strategy_rows(puts, strategy)
        self._p5_fill_chain_table(self.p5_calls_table, calls, call_ranks, call_details)
        self._p5_fill_chain_table(self.p5_puts_table, puts, put_ranks, put_details)
        status_text = f"Chain updated at {datetime.datetime.now().strftime('%H:%M:%S')}"
        status_text += f" | r {self._p5_chain_rate * 100:.2f}% ({self._p5_chain_rate_source}) | q {self._p5_chain_dividend_yield * 100:.2f}% ({self._p5_chain_dividend_source})"
        strategy_count = len(call_ranks if strategy == 'Covered Call' else put_ranks if strategy == 'Cash Secured Put' else {})
        if strategy != 'None' and strategy_count:
            side = 'call' if strategy == 'Covered Call' else 'put'
            status_text += f' | {strategy}: highlighted top {strategy_count} {side} candidates'
            top_details = self._p5_best_strategy_details(strategy, call_details, put_details)
            if top_details:
                status_text += f" | #1: {top_details}"
        self.set_status_text(self.p5_status_lbl, status_text, status='positive')

    def _p5_fill_chain_table(self, table: Any, data: Any, ranks: dict[int, int], details: dict[int, dict[str, Any]]) -> None:
        """Populate a single chain table with optional recommendation styling."""
        render_table_rows(
            table,
            build_chain_rows(
                data,
                self._P5_CHAIN_COLUMNS,
                ranks,
                details,
                strategy_tooltip=self._p5_strategy_tooltip,
                strategy_bg=self._p5_strategy_bg,
                positive_color=self.theme_color('accent_positive'),
                negative_color=self.theme_color('accent_negative'),
                muted_color=self.theme_color('text_muted'),
                pd_module=pd,
            ),
        )

    def _p5_strategy_bg(self, rank: int | None) -> str | None:
        """Resolve recommendation highlight backgrounds from theme tokens."""
        if not rank:
            return None
        return {
            1: self.theme_color('accent_positive_bg'),
            2: self.theme_color('info_bg'),
            3: self.theme_color('accent_soft'),
        }.get(rank, self.theme_color('background_secondary'))

    def _apply_options_chain_theme(self) -> None:
        """Refresh options-chain page styling after a theme change."""
        if hasattr(self, 'p5_price_lbl'):
            self.p5_price_lbl.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {self.theme_color('accent_positive')}; margin-left: 10px;"
            )
        if hasattr(self, 'p5_status_lbl'):
            self.set_status_text(self.p5_status_lbl, self.p5_status_lbl.text(), status=self.p5_status_lbl.property('bt_status') or 'muted')
        if not getattr(self, '_p5_chain_df', pd.DataFrame()).empty:
            self._p5_populate_tables(self._p5_chain_df, self._p5_chain_expiry)
        for view_key, view in getattr(self, 'p5_top_volume_views', {}).items():
            status_lbl = view.get('status_lbl')
            if status_lbl is not None:
                self.set_status_text(status_lbl, status_lbl.text(), status=status_lbl.property('bt_status') or 'muted')
            top_volume_payload = getattr(self, '_p5_top_volume_payloads', {}).get(view_key, {})
            if isinstance(top_volume_payload, dict):
                normalized_payload = self._p5_normalize_top_volume_payload(top_volume_payload)
                bucket_config = self._p5_build_dynamic_top_volume_bucket_config(normalized_payload.get('bucket_order', []))
                self._p5_set_top_volume_bucket_config(view_key, bucket_config)
                self._p5_render_top_volume_tables(
                    view_key,
                    str(normalized_payload.get('ticker', '') or ''),
                    normalized_payload.get('records', {}) if isinstance(normalized_payload.get('records', {}), dict) else {},
                    normalized_payload.get('expirations', {}) if isinstance(normalized_payload.get('expirations', {}), dict) else {},
                )
        if hasattr(self, 'p5_strike_status_lbl'):
            self.set_status_text(
                self.p5_strike_status_lbl,
                self.p5_strike_status_lbl.text(),
                status=self.p5_strike_status_lbl.property('bt_status') or 'muted',
            )
        strike_payload = getattr(self, '_p5_strike_payload', {})
        if isinstance(strike_payload, dict) and hasattr(self, 'p5_strike_grid_layout'):
            normalized_strike = self._p5_normalize_strike_payload(strike_payload)
            self._p5_strike_available_strikes = list(normalized_strike.get('available_strikes', []) or [])
            self._p5_reset_strike_combo(normalized_strike.get('selected_strike'))
            bucket_config = self._p5_build_dynamic_top_volume_bucket_config(normalized_strike.get('bucket_order', []))
            self._p5_set_strike_bucket_config(bucket_config)
            self._p5_render_strike_tables(
                str(normalized_strike.get('ticker', '') or ''),
                normalized_strike.get('selected_strike'),
                normalized_strike.get('records', {}) if isinstance(normalized_strike.get('records', {}), dict) else {},
                normalized_strike.get('expirations', {}) if isinstance(normalized_strike.get('expirations', {}), dict) else {},
            )

    def _p5_format_chain_value(self, value: Any, fmt: str) -> str:
        """Format a chain cell value for display."""
        return format_chain_value(value, fmt, pd_module=pd)

    def _p5_rank_strategy_rows(self, data: Any, strategy: str) -> tuple[dict[int, int], dict[int, dict[str, Any]]]:
        """Score and rank the top strategy candidates for one table."""
        if data is None or data.empty or strategy == 'None':
            return ({}, {})
        if strategy == 'Covered Call' and str(data.iloc[0].get('type', '')).strip() != 'Call':
            return ({}, {})
        if strategy == 'Cash Secured Put' and str(data.iloc[0].get('type', '')).strip() != 'Put':
            return ({}, {})
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        spot = float(getattr(self, '_p5_chain_spot_price', 0.0) or 0.0)
        for idx, row in data.iterrows():
            score_data = self._p5_strategy_score(row, strategy, spot)
            score = score_data.get('score') if isinstance(score_data, dict) else None
            if score is not None:
                candidates.append((float(score), idx, score_data))
        candidates.sort(key=lambda item: item[0], reverse=True)
        ranks: dict[int, int] = {}
        details: dict[int, dict[str, Any]] = {}
        for rank, (_, idx, score_data) in enumerate(candidates[:3], start=1):
            ranks[int(idx)] = rank
            detail = dict(score_data or {})
            detail['rank'] = rank
            details[int(idx)] = detail
        return (ranks, details)

    def _p5_strategy_score(self, row: Any, strategy: str, spot: float) -> dict[str, Any] | None:
        """Return a recommendation score breakdown for one row or None if it is ineligible."""
        strike = float(row.get('strike', 0.0) or 0.0)
        bid = float(row.get('bid', 0.0) or 0.0)
        ask = float(row.get('ask', 0.0) or 0.0)
        last = float(row.get('lastPrice', 0.0) or 0.0)
        oi = float(row.get('openInterest', 0.0) or 0.0)
        vol = float(row.get('volume', 0.0) or 0.0)
        iv = float(row.get('impliedVolatility', 0.0) or 0.0)
        delta = row.get('delta_calc')
        gamma = row.get('gamma_calc')
        vega = row.get('vega_calc')
        if not row.get('greeks_valid') or strike <= 0 or spot <= 0:
            return None
        if any(v is None or pd.isna(v) for v in (delta, gamma, vega)):
            return None
        if bid <= 0 and ask <= 0 and last <= 0:
            return None
        premium = (bid + ask) / 2.0 if bid > 0 and ask > 0 else last
        if premium <= 0 or iv <= 0:
            return None
        delta_abs = abs(float(delta))
        gamma_abs = abs(float(gamma))
        vega_abs = abs(float(vega))
        has_live_spread = bid > 0 and ask > 0 and premium > 0
        spread_ratio = ((ask - bid) / premium) if has_live_spread else None
        if spread_ratio is not None and spread_ratio < 0:
            return None
        if oi < self._P5_STRATEGY_MIN_OI:
            return None
        if vol < self._P5_STRATEGY_MIN_VOLUME:
            return None
        if spread_ratio is not None and spread_ratio > self._P5_STRATEGY_MAX_SPREAD_RATIO:
            return None
        expiry = str(getattr(self, '_p5_chain_expiry', '') or '').strip()
        dte = self._p5_strategy_dte(expiry)
        if dte <= 0:
            return None
        spread_score = self._p5_strategy_linear_score(spread_ratio, 0.02, self._P5_STRATEGY_MAX_SPREAD_RATIO, inverse=True) if spread_ratio is not None else 35.0
        liquidity_score = (
            self._p5_strategy_linear_score(math.log1p(max(oi, 0.0)), math.log1p(self._P5_STRATEGY_MIN_OI), math.log1p(5000.0))
            + self._p5_strategy_linear_score(math.log1p(max(vol, 0.0)), math.log1p(self._P5_STRATEGY_MIN_VOLUME), math.log1p(1000.0))
        ) / 2.0
        if vol <= 0:
            liquidity_score = liquidity_score * 0.85
        greek_stability_score = (
            self._p5_strategy_linear_score(gamma_abs, 0.0, 0.05, inverse=True) * 0.55
            + self._p5_strategy_linear_score(vega_abs, 0.0, 0.35, inverse=True) * 0.45
        )
        base_details = {
            'strategy': strategy,
            'strike': strike,
            'premium': premium,
            'delta_abs': delta_abs,
            'dte': dte,
            'annualized_yield': 0.0,
            'spread_ratio': spread_ratio,
            'oi': oi,
            'volume': vol,
            'liquidity_score': liquidity_score,
            'spread_score': spread_score,
            'greek_stability_score': greek_stability_score,
            'score': 0.0,
            'rationale': '',
        }
        if strategy == 'Covered Call':
            if strike < spot:
                return None
            delta_score = self._p5_strategy_band_score(delta_abs, self._P5_CC_DELTA_TARGET, *self._P5_CC_DELTA_BAND)
            annualized_yield = (premium / spot) * (365.0 / dte)
            yield_score = self._p5_strategy_linear_score(annualized_yield, 0.04, 0.30)
            upside_room = max(0.0, (strike / spot) - 1.0)
            upside_score = self._p5_strategy_linear_score(upside_room, 0.01, 0.12)
            strategy_score = (
                delta_score * 0.30
                + yield_score * 0.25
                + liquidity_score * 0.15
                + spread_score * 0.15
                + upside_score * 0.15
                + greek_stability_score * 0.10
            )
            if strike <= spot:
                strategy_score *= 0.90
            details = dict(base_details)
            details.update({
                'annualized_yield': annualized_yield,
                'delta_score': delta_score,
                'yield_score': yield_score,
                'upside_room': upside_room,
                'upside_score': upside_score,
                'has_live_spread': has_live_spread,
                'score': strategy_score,
                'rationale': self._p5_describe_covered_call(delta_abs, annualized_yield, upside_room, spread_ratio, oi, vol, has_live_spread),
            })
            return details
        if strategy == 'Cash Secured Put':
            if strike > spot:
                return None
            delta_score = self._p5_strategy_band_score(delta_abs, self._P5_CSP_DELTA_TARGET, *self._P5_CSP_DELTA_BAND)
            annualized_yield = (premium / strike) * (365.0 / dte)
            yield_score = self._p5_strategy_linear_score(annualized_yield, 0.05, 0.35)
            breakeven = strike - premium
            breakeven_discount = max(0.0, (spot - breakeven) / spot)
            breakeven_score = self._p5_strategy_linear_score(breakeven_discount, 0.01, 0.12)
            strategy_score = (
                delta_score * 0.30
                + yield_score * 0.25
                + breakeven_score * 0.20
                + liquidity_score * 0.15
                + spread_score * 0.10
                + greek_stability_score * 0.10
            )
            if strike >= spot:
                strategy_score *= 0.88
            details = dict(base_details)
            details.update({
                'annualized_yield': annualized_yield,
                'delta_score': delta_score,
                'yield_score': yield_score,
                'breakeven': breakeven,
                'breakeven_discount': breakeven_discount,
                'breakeven_score': breakeven_score,
                'has_live_spread': has_live_spread,
                'score': strategy_score,
                'rationale': self._p5_describe_cash_secured_put(delta_abs, annualized_yield, breakeven_discount, spread_ratio, oi, vol, has_live_spread),
            })
            return details
        return None

    def _p5_strategy_dte(self, expiry: str) -> int:
        """Return days to expiry for strategy ranking."""
        if not expiry:
            return 0
        try:
            exp_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        except Exception:
            return 0
        return max(0, (exp_date - datetime.date.today()).days)

    def _p5_strategy_linear_score(self, value: float, low: float, high: float, inverse: bool=False) -> float:
        """Map a value into a capped 0-100 score."""
        try:
            value_f = float(value)
            low_f = float(low)
            high_f = float(high)
        except (TypeError, ValueError):
            return 0.0
        if high_f <= low_f:
            return 0.0
        normalized = (value_f - low_f) / (high_f - low_f)
        normalized = max(0.0, min(1.0, normalized))
        if inverse:
            normalized = 1.0 - normalized
        return normalized * 100.0

    def _p5_strategy_band_score(self, value: float, target: float, lower: float, upper: float) -> float:
        """Return a 0-100 score for proximity to a target within a preferred band."""
        try:
            value_f = float(value)
            target_f = float(target)
            lower_f = float(lower)
            upper_f = float(upper)
        except (TypeError, ValueError):
            return 0.0
        if upper_f <= lower_f or value_f < lower_f or value_f > upper_f:
            return 0.0
        band_radius = max(target_f - lower_f, upper_f - target_f, 1e-09)
        distance = abs(value_f - target_f)
        return max(0.0, (1.0 - (distance / band_radius)) * 100.0)

    def _p5_strategy_tooltip(self, rank: int | None, details: dict[str, Any]) -> str:
        """Return a tooltip explaining a ranked strategy row."""
        if not rank or not details:
            return ''
        lines = [
            f"Rank #{rank} | Score {float(details.get('score', 0.0)):.1f}",
            str(details.get('rationale', '') or '').strip(),
            f"Delta {float(details.get('delta_abs', 0.0)):.3f} | DTE {int(details.get('dte', 0) or 0)} | Ann. yield {float(details.get('annualized_yield', 0.0)) * 100:.1f}%",
            f"{self._p5_format_spread_summary(details)} | OI {float(details.get('oi', 0.0)):.0f} | Vol {float(details.get('volume', 0.0)):.0f}",
        ]
        if details.get('strategy') == 'Covered Call':
            lines.append(f"Upside room {(float(details.get('upside_room', 0.0)) * 100):.1f}%")
        elif details.get('strategy') == 'Cash Secured Put':
            lines.append(f"Break-even discount {(float(details.get('breakeven_discount', 0.0)) * 100):.1f}%")
        return '\n'.join([line for line in lines if line])

    def _p5_best_strategy_details(self, strategy: str, call_details: dict[int, dict[str, Any]], put_details: dict[int, dict[str, Any]]) -> str:
        """Return a short summary for the top-ranked row."""
        detail_map = call_details if strategy == 'Covered Call' else put_details if strategy == 'Cash Secured Put' else {}
        top_detail = next((detail for detail in detail_map.values() if int(detail.get('rank', 0) or 0) == 1), None)
        if not top_detail:
            return ''
        strike = float(top_detail.get('strike', 0.0) or 0.0)
        summary = f"strike {strike:.1f}, score {float(top_detail.get('score', 0.0)):.1f}"
        rationale = str(top_detail.get('rationale', '') or '').strip()
        if rationale:
            summary += f", {rationale}"
        return summary


    def _p5_describe_covered_call(self, delta_abs: float, annualized_yield: float, upside_room: float, spread_ratio: float | None, oi: float, vol: float, has_live_spread: bool) -> str:
        """Return a plain-English explanation for a covered-call rank."""
        spread_text = f"{(spread_ratio * 100):.1f}% spread" if has_live_spread and spread_ratio is not None else 'no live bid/ask spread'
        return (
            f"Close to the {self._P5_CC_DELTA_TARGET:.3f} delta target, "
            f"offers {annualized_yield * 100:.1f}% annualized yield, "
            f"keeps {upside_room * 100:.1f}% upside room, "
            f"with {spread_text} and usable liquidity (OI {oi:.0f}, Vol {vol:.0f})."
        )

    def _p5_describe_cash_secured_put(self, delta_abs: float, annualized_yield: float, breakeven_discount: float, spread_ratio: float | None, oi: float, vol: float, has_live_spread: bool) -> str:
        """Return a plain-English explanation for a cash-secured-put rank."""
        spread_text = f"{(spread_ratio * 100):.1f}% spread" if has_live_spread and spread_ratio is not None else 'no live bid/ask spread'
        return (
            f"Close to the {self._P5_CSP_DELTA_TARGET:.3f} delta target, "
            f"offers {annualized_yield * 100:.1f}% annualized yield, "
            f"improves entry by {breakeven_discount * 100:.1f}% to break-even, "
            f"with {spread_text} and usable liquidity (OI {oi:.0f}, Vol {vol:.0f})."
        )

    def _p5_format_spread_summary(self, details: dict[str, Any]) -> str:
        """Format spread text for live and after-hours ranked rows."""
        if bool(details.get('has_live_spread')):
            return f"Spread {(float(details.get('spread_ratio', 0.0)) * 100):.1f}%"
        return 'Spread unavailable after hours'
