from __future__ import annotations
import time
from typing import Any
from ..compat import *


class _GlobalInputExitFilter(QObject):

    def __init__(self, window: Any) -> None:
        """Forward global key events into the owning window without duplicating local filters."""
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Handle the dedicated app-wide text-input escape shortcuts."""
        return bool(getattr(self._window, '_handle_global_input_exit_event', lambda *_: False)(obj, event))


class _CurrentPageStackedWidget(QStackedWidget):
    """Stacked widget whose pages cannot force the main window taller."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)

    def _height_neutral_hint(self, hint: Any) -> Any:
        try:
            hint.setHeight(0)
        except AttributeError:
            pass
        return hint

    def sizeHint(self) -> Any:
        widget = self.currentWidget()
        hint = widget.sizeHint() if widget is not None else super().sizeHint()
        return self._height_neutral_hint(hint)

    def minimumSizeHint(self) -> Any:
        widget = self.currentWidget()
        hint = widget.minimumSizeHint() if widget is not None else super().minimumSizeHint()
        return self._height_neutral_hint(hint)


class _MainPageWidget(QWidget):
    """Top-level page widget that preserves width hints but not height pressure."""

    def sizeHint(self) -> Any:
        hint = super().sizeHint()
        try:
            hint.setHeight(0)
        except AttributeError:
            pass
        return hint

    def minimumSizeHint(self) -> Any:
        hint = super().minimumSizeHint()
        try:
            hint.setHeight(0)
        except AttributeError:
            pass
        return hint


class WindowSetupMixin:
    _LAZY_WARMUP_INITIAL_DELAY_MS = 350
    _LAZY_WARMUP_STEP_MS = 150
    _INTERACTION_LOG_BOUND_PROPERTY = 'bt_interaction_log_bound'
    _PAGE_LABELS = {
        0: 'Dashboard',
        1: 'Portfolio',
        2: 'Personal Finance',
        3: 'Calendar',
        4: 'News',
        5: 'Sectors',
        6: 'Heatmap',
        7: 'Stocks',
        8: 'Fundamentals',
        9: 'Charts',
        11: 'Options',
        12: 'ETF',
        13: 'Pre-Market',
        14: 'Crypto',
        15: 'Politics',
        16: 'YouTube',
        17: 'Settings',
        18: 'Roll',
        19: 'Trading Volumes',
        20: 'IPO',
        21: 'DATAROMA',
    }

    def init_ui(self) -> None:
        """Initialize ui."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        self._setup_window_shell(root_layout)
        self._init_dashboard_page()
        self._register_lazy_pages()
        self._initialize_startup_pages()
        self._register_navigation_pages()
        self._start_clock_timer()

    def _prepare_main_page_widget(self, page: Any) -> Any:
        """Keep a top-level page from contributing vertical minimum height."""
        if page is None:
            return page
        try:
            page.setMinimumHeight(0)
            page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        except AttributeError:
            pass
        return page

    def _new_main_page_widget(self) -> Any:
        """Create a main stack page with height-neutral sizing behavior."""
        return self._prepare_main_page_widget(_MainPageWidget())

    def _setup_window_shell(self, root_layout: Any) -> None:
        """Handle setup window shell."""
        self._startup_progress_begin('window_shell', 'Window shell')
        self.top_bar = QHBoxLayout()
        self.time_label = QLabel('--:--')
        self.set_theme_role(self.time_label, 'section_title')
        self._pages = {}
        self.btn_page1 = QPushButton('Dashboard')
        self.btn_page1.setCheckable(True)
        self.btn_page1.setChecked(True)
        self.btn_page2 = QPushButton('Fundamentals')
        self.btn_page2.setCheckable(True)
        self.btn_page3 = QPushButton('News')
        self.btn_page3.setCheckable(True)
        self.btn_page4 = QPushButton('Portfolio')
        self.btn_page4.setCheckable(True)
        self.btn_page5 = QPushButton('Options')
        self.btn_page5.setCheckable(True)
        self.btn_page13 = QPushButton('ETF')
        self.btn_page13.setCheckable(True)
        self.btn_page14 = QPushButton('Pre-Market')
        self.btn_page14.setCheckable(True)
        self.btn_page19 = QPushButton('Crypto')
        self.btn_page19.setCheckable(True)
        self.btn_page6 = QPushButton('Personal Finance')
        self.btn_page6.setCheckable(True)
        self.btn_page7 = QPushButton('Calendar')
        self.btn_page7.setCheckable(True)
        self.btn_page20 = QPushButton('Trading Volumes')
        self.btn_page20.setCheckable(True)
        self.btn_page8 = QPushButton('Sectors')
        self.btn_page8.setCheckable(True)
        self.btn_page17 = QPushButton('Heatmap')
        self.btn_page17.setCheckable(True)
        self.btn_page15 = QPushButton('Politics')
        self.btn_page15.setCheckable(True)
        self.btn_page22 = QPushButton('DATAROMA')
        self.btn_page22.setCheckable(True)
        self.btn_page16 = QPushButton('YouTube')
        self.btn_page16.setCheckable(True)
        self.btn_page9 = QPushButton('Settings')
        self.btn_page9.setCheckable(True)
        self.btn_page10 = QPushButton('Charts')
        self.btn_page10.setCheckable(True)
        self.btn_page11 = QPushButton('Multi Charts')
        self.btn_page11.setCheckable(True)
        self.btn_page12 = QPushButton('Stocks')
        self.btn_page12.setCheckable(True)
        self.btn_page18 = QPushButton('Roll')
        self.btn_page18.setCheckable(True)
        self.btn_page21 = QPushButton('IPO')
        self.btn_page21.setCheckable(True)
        self._nav_buttons = [
            self.btn_page1,
            self.btn_page4,
            self.btn_page6,
            self.btn_page7,
            self.btn_page20,
            self.btn_page3,
            self.btn_page8,
            self.btn_page17,
            self.btn_page12,
            self.btn_page2,
            self.btn_page10,
            self.btn_page5,
            self.btn_page13,
            self.btn_page14,
            self.btn_page19,
            self.btn_page15,
            self.btn_page22,
            self.btn_page16,
            self.btn_page18,
            self.btn_page21,
            self.btn_page9,
        ]
        self.top_refresh_btn = QPushButton('Reload (F5)')
        self.top_refresh_btn.setToolTip('Reload the current page (F5)')
        self.top_refresh_btn.clicked.connect(self._refresh_current_page)
        nav_scroll_left = QPushButton('<')
        nav_scroll_left.setFixedWidth(24)
        nav_scroll_left.setFixedHeight(38)
        nav_scroll_right = QPushButton('>')
        nav_scroll_right.setFixedWidth(24)
        nav_scroll_right.setFixedHeight(38)
        self._shell_log_buttons = [nav_scroll_left, nav_scroll_right]

        nav_container = QWidget()
        nav_container_layout = QHBoxLayout(nav_container)
        nav_container_layout.setContentsMargins(0, 0, 0, 0)
        nav_container_layout.setSpacing(4)
        for button in self._nav_buttons:
            button.setMinimumHeight(38)
            button.setMinimumWidth(110)
            nav_container_layout.addWidget(button)

        self._nav_scroll_area = QScrollArea()
        self._nav_scroll_area.setWidget(nav_container)
        self._nav_scroll_area.setWidgetResizable(False)
        self._nav_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._nav_scroll_area.setFixedHeight(42)

        nav_scroll_left.clicked.connect(lambda: self._nav_scroll_area.horizontalScrollBar().setValue(
            self._nav_scroll_area.horizontalScrollBar().value() - 200))
        nav_scroll_right.clicked.connect(lambda: self._nav_scroll_area.horizontalScrollBar().setValue(
            self._nav_scroll_area.horizontalScrollBar().value() + 200))

        self.top_bar.addWidget(nav_scroll_left)
        self.top_bar.addWidget(self._nav_scroll_area, 1)
        self.top_bar.addWidget(nav_scroll_right)
        self._tab_picker_items = []
        self._tab_picker_map = {}
        self._tab_picker_popup = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._tab_picker_popup.setModal(False)
        self._tab_picker_popup.setObjectName('tabPickerPopup')
        self._tab_picker_popup.setFixedWidth(300)
        popup_layout = QVBoxLayout(self._tab_picker_popup)
        popup_layout.setContentsMargins(10, 10, 10, 10)
        popup_layout.setSpacing(8)
        self._tab_picker_input = QLineEdit()
        self._tab_picker_input.setPlaceholderText('Type a tab name')
        self._tab_picker_input.textChanged.connect(self._filter_tab_picker_items)
        self._tab_picker_input.installEventFilter(self)
        popup_layout.addWidget(self._tab_picker_input)
        self._tab_picker_list = QListWidget()
        self._tab_picker_list.setMinimumHeight(220)
        self._tab_picker_list.setMaximumHeight(220)
        self._tab_picker_list.itemActivated.connect(self._activate_tab_picker_item)
        self._tab_picker_list.itemClicked.connect(self._activate_tab_picker_item)
        self._tab_picker_list.installEventFilter(self)
        popup_layout.addWidget(self._tab_picker_list)
        self._tab_picker_popup.installEventFilter(self)
        self._global_input_exit_filter = _GlobalInputExitFilter(self)
        self._app_keyboard_event_filter_installed = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._global_input_exit_filter)
            self._app_keyboard_event_filter_installed = True
        self._nav_prev_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._nav_prev_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._nav_prev_shortcut.activated.connect(lambda: self._handle_main_tab_arrow_shortcut(-1))
        self._nav_next_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._nav_next_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._nav_next_shortcut.activated.connect(lambda: self._handle_main_tab_arrow_shortcut(1))
        self._nav_cycle_shortcut = QShortcut(QKeySequence('Ctrl+Tab'), self)
        self._nav_cycle_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._nav_cycle_shortcut.activated.connect(self._handle_ctrl_tab_shortcut)
        self._page_refresh_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        self._page_refresh_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._page_refresh_shortcut.activated.connect(self._refresh_current_page)
        self._tab_picker_shortcut = QShortcut(QKeySequence('`'), self)
        self._tab_picker_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._tab_picker_shortcut.activated.connect(self._handle_tab_picker_shortcut)
        self._tz_choices = TIMEZONE_CHOICES
        self._clock_tz_index = 0
        self._time_12h = load_time_format()
        self.top_bar.addWidget(self.time_label)
        self.top_bar.addSpacing(8)
        self.top_bar.addWidget(self.top_refresh_btn)
        root_layout.addLayout(self.top_bar)
        self.stacked_widget = _CurrentPageStackedWidget()
        self.stacked_widget.setMinimumHeight(0)
        self.stacked_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        root_layout.addWidget(self.stacked_widget, 1)
        footer_row = QHBoxLayout()
        self.status_bar = QLabel('Ready')
        self.status_bar.setMinimumWidth(0)
        self.status_bar.setWordWrap(False)
        self.status_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_theme_role(self.status_bar, 'status_muted')
        self.data_collection_label = QLabel('Data collected: awaiting first refresh')
        self.set_theme_role(self.data_collection_label, 'status_muted')
        self.data_collection_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.data_health_label = QLabel('Data health: OK')
        self.set_theme_role(self.data_health_label, 'status_muted')
        self.data_health_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer_row.addWidget(self.status_bar, 1)
        footer_row.addWidget(self.data_health_label, 0)
        footer_row.addWidget(self.data_collection_label, 0)
        root_layout.addLayout(footer_row)
        self._bind_shell_interaction_logging()
        self._startup_progress_complete('window_shell', 'Window shell')

    def _safe_log_text(self, value: Any, *, max_length: int=80, fallback: str='unnamed') -> str:
        """Return a compact single-line label for session log messages."""
        text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
        while '  ' in text:
            text = text.replace('  ', ' ')
        if not text:
            text = fallback
        if len(text) > max_length:
            text = f'{text[:max_length - 3].rstrip()}...'
        return text

    def _page_label(self, index: Any=None) -> str:
        """Return a readable main-page label for log messages."""
        try:
            numeric_index = int(index if index is not None else self.stacked_widget.currentIndex())
        except (TypeError, ValueError, AttributeError):
            numeric_index = 0
        page = getattr(self, '_pages', {}).get(numeric_index, {})
        button = page.get('btn') if isinstance(page, dict) else None
        if button is not None and hasattr(button, 'text'):
            label = str(button.text() or '').strip()
            if label:
                return self._safe_log_text(label)
        return self._PAGE_LABELS.get(numeric_index, f'Page {numeric_index}')

    def _widget_log_label(self, widget: Any, *, fallback: str='control') -> str:
        """Return a non-sensitive label for a widget without reading user-entered values."""
        for attr_name in ('text', 'windowTitle', 'placeholderText', 'objectName'):
            attr = getattr(widget, attr_name, None)
            if not callable(attr):
                continue
            try:
                value = attr()
            except Exception:
                value = ''
            if value:
                return self._safe_log_text(value, fallback=fallback)
        return self._safe_log_text(widget.__class__.__name__, fallback=fallback)

    def _widget_log_page_label(self, widget: Any) -> str:
        """Resolve the owning visible page for an interaction log line."""
        current = widget
        while current is not None and isinstance(current, QWidget):
            try:
                page_index = self.stacked_widget.indexOf(current)
            except Exception:
                page_index = -1
            if page_index >= 0:
                return self._page_label(page_index)
            current = current.parentWidget()
        return self._page_label()

    def _mark_interaction_logger_bound(self, widget: Any, key: str) -> bool:
        """Return True once for each widget/signal pair that receives log wiring."""
        bound = widget.property(self._INTERACTION_LOG_BOUND_PROPERTY)
        if isinstance(bound, str):
            keys = {item for item in bound.split(',') if item}
        else:
            keys = set()
        if key in keys:
            return False
        keys.add(key)
        widget.setProperty(self._INTERACTION_LOG_BOUND_PROPERTY, ','.join(sorted(keys)))
        return True

    def _log_user_interaction(self, action: str, widget: Any, detail: Any='') -> None:
        """Emit one concise, privacy-aware user interaction log line."""
        label = self._widget_log_label(widget)
        page_label = self._widget_log_page_label(widget)
        clean_detail = self._safe_log_text(detail, max_length=120, fallback='') if detail else ''
        if clean_detail:
            logger.info('User action: %s "%s" on %s (%s).', action, label, page_label, clean_detail)
        else:
            logger.info('User action: %s "%s" on %s.', action, label, page_label)

    def _bind_button_interaction_logging(self, button: Any) -> None:
        if not self._mark_interaction_logger_bound(button, 'clicked'):
            return
        button.clicked.connect(lambda _checked=False, widget=button: self._log_user_interaction('clicked button', widget))

    def _bind_checkbox_interaction_logging(self, checkbox: Any) -> None:
        if not self._mark_interaction_logger_bound(checkbox, 'toggled'):
            return
        checkbox.toggled.connect(
            lambda checked=False, widget=checkbox: self._log_user_interaction(
                'toggled checkbox',
                widget,
                f'checked={bool(checked)}',
            )
        )

    def _bind_combo_interaction_logging(self, combo: Any) -> None:
        if not self._mark_interaction_logger_bound(combo, 'activated'):
            return
        combo.activated.connect(
            lambda index=0, widget=combo: self._log_user_interaction(
                'selected combo item',
                widget,
                f'index={int(index)}',
            )
        )

    def _bind_line_edit_interaction_logging(self, line_edit: Any) -> None:
        if not self._mark_interaction_logger_bound(line_edit, 'returnPressed'):
            return
        line_edit.returnPressed.connect(
            lambda widget=line_edit: self._log_user_interaction('submitted text field', widget)
        )

    def _bind_table_interaction_logging(self, table: Any) -> None:
        if not self._mark_interaction_logger_bound(table, 'cellClicked'):
            return
        table.cellClicked.connect(
            lambda row=0, column=0, widget=table: self._log_user_interaction(
                'clicked table cell',
                widget,
                f'row={int(row)} column={int(column)}',
            )
        )

    def _bind_list_interaction_logging(self, list_widget: Any) -> None:
        if not self._mark_interaction_logger_bound(list_widget, 'itemClicked'):
            return
        list_widget.itemClicked.connect(
            lambda _item=None, widget=list_widget: self._log_user_interaction(
                'clicked list item',
                widget,
                f'row={int(widget.currentRow())}',
            )
        )

    def _bind_tab_interaction_logging(self, tab_widget: Any) -> None:
        if not self._mark_interaction_logger_bound(tab_widget, 'tabBarClicked'):
            return
        tab_widget.tabBarClicked.connect(
            lambda index=0, widget=tab_widget: self._log_user_interaction(
                'clicked tab',
                widget,
                f'index={int(index)}',
            )
        )

    def _bind_shell_interaction_logging(self) -> None:
        """Wire meaningful top-shell controls that are not children of a page."""
        shell_buttons = list(getattr(self, '_shell_log_buttons', []))
        shell_buttons.extend(list(getattr(self, '_nav_buttons', [])))
        shell_buttons.append(getattr(self, 'top_refresh_btn', None))
        for button in shell_buttons:
            if button is not None:
                self._bind_button_interaction_logging(button)
        for widget in (getattr(self, '_tab_picker_input', None), getattr(self, '_tab_picker_list', None)):
            if isinstance(widget, QLineEdit):
                self._bind_line_edit_interaction_logging(widget)
            elif isinstance(widget, QListWidget):
                self._bind_list_interaction_logging(widget)

    def _bind_page_interaction_logging(self, page: Any, index: Any) -> None:
        """Wire concise interaction logs for meaningful controls on one built page."""
        if not isinstance(page, QWidget):
            return
        for button in page.findChildren(QPushButton):
            self._bind_button_interaction_logging(button)
        for checkbox in page.findChildren(QCheckBox):
            self._bind_checkbox_interaction_logging(checkbox)
        for combo in page.findChildren(QComboBox):
            self._bind_combo_interaction_logging(combo)
        for line_edit in page.findChildren(QLineEdit):
            self._bind_line_edit_interaction_logging(line_edit)
        for table in page.findChildren(QTableWidget):
            self._bind_table_interaction_logging(table)
        for list_widget in page.findChildren(QListWidget):
            self._bind_list_interaction_logging(list_widget)
        for tab_widget in page.findChildren(QTabWidget):
            self._bind_tab_interaction_logging(tab_widget)
        logger.info('Interaction logging wired for %s page.', self._page_label(index))

    def _init_dashboard_page(self) -> None:
        """Handle init dashboard page."""
        started_at = time.perf_counter()
        logger.info('Page load started: Dashboard (index 0, startup).')
        self._startup_progress_begin_page(0, 'Dashboard')
        self.page1 = self._new_main_page_widget()
        self.stacked_widget.addWidget(self.page1)
        main_layout = QHBoxLayout(self.page1)
        self.dashboard_main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_widget.setMinimumWidth(0)
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText('Enter Ticker (e.g. AAPL)')
        self.ticker_input.returnPressed.connect(self.add_ticker)
        add_btn = QPushButton('Add')
        self.set_theme_variant(add_btn, 'accent')
        add_btn.clicked.connect(self.add_ticker)
        add_btn.setFixedHeight(24)
        self._dashboard_add_btn_refs = [add_btn]
        self.port_table = QTableWidget(0, 6)
        self.port_table.setHorizontalHeaderLabels(['Ticker', 'Price', 'Chg %', 'Weight', 'Gain $', ''])
        port_header = self.port_table.horizontalHeader()
        port_header.setSectionsMovable(True)
        port_header.setMinimumHeight(28)
        port_header.setDefaultSectionSize(28)
        port_header.setStretchLastSection(False)
        for index in range(5):
            port_header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        port_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.port_table.setColumnWidth(5, 34)
        self.port_table.setMinimumWidth(0)
        self.port_table.verticalHeader().setVisible(False)
        self.port_table.verticalHeader().setDefaultSectionSize(24)
        self.port_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.port_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.port_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.port_table.cellClicked.connect(self._dashboard_on_portfolio_click)
        self.port_table.setAlternatingRowColors(True)
        if hasattr(self, '_dashboard_fit_portfolio_table_height'):
            self._dashboard_fit_portfolio_table_height()
        self.target_table = QTableWidget(0, 4)
        self.target_table.setHorizontalHeaderLabels(['Ticker', 'Current', 'Target', 'Upside (%)'])
        self.target_table.setMinimumWidth(0)
        self.target_table.horizontalHeader().setMinimumHeight(28)
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.target_table.verticalHeader().setDefaultSectionSize(24)
        self.target_table.setAlternatingRowColors(True)
        self.target_table.setMaximumHeight(150)
        self.news_table = QTableWidget(0, 4)
        self.news_table.setHorizontalHeaderLabels(['Headline', 'Ticker', 'Source', 'Time'])
        self.news_table.setMinimumWidth(0)
        self.news_table.horizontalHeader().setSectionsMovable(True)
        self.news_table.horizontalHeader().setMinimumHeight(28)
        self.news_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, 4):
            self.news_table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self.news_table.setColumnHidden(1, True)
        self.news_table.setColumnHidden(2, True)
        self.news_table.setColumnHidden(3, True)
        self.news_table.verticalHeader().setDefaultSectionSize(24)
        self.news_table.setMaximumHeight(150)
        self.news_table.itemClicked.connect(self.open_news_link)
        portfolio_box = QFrame()
        portfolio_box.setMinimumWidth(0)
        self.set_theme_role(portfolio_box, 'panel')
        portfolio_layout = QVBoxLayout(portfolio_box)
        portfolio_layout.setContentsMargins(6, 6, 6, 6)
        portfolio_layout.setSpacing(4)
        port_header = QHBoxLayout()
        port_header.setContentsMargins(0, 0, 0, 0)
        port_header.setSpacing(6)
        self.port_header_lbl = QLabel('<b>My Portfolio</b>')
        self.port_header_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.port_header_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.set_theme_role(self.port_header_lbl, 'card_title')
        self.dashboard_portfolio_combo = QComboBox()
        self.dashboard_portfolio_combo.setMinimumWidth(0)
        self.dashboard_portfolio_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.dashboard_portfolio_combo.currentIndexChanged.connect(self._dashboard_on_portfolio_changed)
        self.ticker_input.setMinimumWidth(0)
        self.ticker_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        port_header.addWidget(self.port_header_lbl)
        port_header.addWidget(self.dashboard_portfolio_combo, 1)
        port_header.addWidget(self.ticker_input, 1)
        port_header.addWidget(add_btn)
        portfolio_layout.addLayout(port_header)
        portfolio_layout.addWidget(self.port_table)
        portfolio_layout.addStretch(1)
        targets_label = QLabel('<b>Analyst Price Targets</b>')
        self.set_theme_role(targets_label, 'section_title')
        news_label = QLabel('<b>Live News Feed</b>')
        self.set_theme_role(news_label, 'section_title')
        self.target_table.setMaximumHeight(16777215)
        self.news_table.setMaximumHeight(16777215)
        port_section = QWidget()
        port_section.setMinimumWidth(0)
        port_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        port_section_layout = QVBoxLayout(port_section)
        port_section_layout.setContentsMargins(0, 0, 0, 0)
        port_section_layout.setSpacing(0)
        port_section_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        port_section_layout.addWidget(portfolio_box)
        targets_section = QWidget()
        targets_section.setMinimumWidth(0)
        targets_section_layout = QVBoxLayout(targets_section)
        targets_section_layout.setContentsMargins(0, 0, 0, 0)
        targets_section_layout.setSpacing(4)
        targets_section_layout.addWidget(targets_label)
        targets_section_layout.addWidget(self.target_table)
        news_section = QWidget()
        news_section.setMinimumWidth(0)
        news_section_layout = QVBoxLayout(news_section)
        news_section_layout.setContentsMargins(0, 0, 0, 0)
        news_section_layout.setSpacing(4)
        news_section_layout.addWidget(news_label)
        news_section_layout.addWidget(self.news_table)
        self.dashboard_left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.dashboard_left_splitter.setHandleWidth(6)
        self.dashboard_left_splitter.setStyleSheet(
            'QSplitter::handle { background: #2a2a4a; border-radius: 2px; }'
        )
        self.dashboard_left_splitter.addWidget(port_section)
        self.dashboard_left_splitter.addWidget(targets_section)
        self.dashboard_left_splitter.addWidget(news_section)
        self.dashboard_left_splitter.setStretchFactor(0, 3)
        self.dashboard_left_splitter.setStretchFactor(1, 2)
        self.dashboard_left_splitter.setStretchFactor(2, 2)
        self._p1_restore_left_splitter_sizes()
        self.dashboard_left_splitter.splitterMoved.connect(self._p1_on_left_splitter_moved)
        left_col.addWidget(self.dashboard_left_splitter)
        right_widget = QWidget()
        right_col = QVBoxLayout(right_widget)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(3)
        indices_bar = QHBoxLayout()
        self.index_labels = {}
        for index_name in ['SPY', 'DXY', 'VIX', 'GLD', 'WTI']:
            label = QLabel(f'{index_name}: --')
            label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
            label.setMinimumWidth(120)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.set_theme_role(label, 'index')
            indices_bar.addWidget(label)
            self.index_labels[index_name] = label
        right_col.addLayout(indices_bar)
        timeframe_options = [('1 Minute', '7d', '1m'), ('5 Minutes', '60d', '5m'), ('15 Minutes', '60d', '15m'), ('1 Hour', '730d', '1h'), ('1 Day', '5y', '1d'), ('1 Week', '5y', '1wk'), ('1 Month', '5y', '1mo')]
        self.dashboard_timeframe_map = {label: (period, interval) for label, period, interval in timeframe_options}
        self.dashboard_symbol_input = QLineEdit(self.dashboard_chart_state.get('symbol', 'SPY'))
        self.dashboard_symbol_input.setPlaceholderText('Ticker')
        self.dashboard_symbol_input.setFixedWidth(110)
        self.dashboard_symbol_input.returnPressed.connect(self._dashboard_load_from_input)
        self.dashboard_load_btn = QPushButton('Load')
        self.set_theme_variant(self.dashboard_load_btn, 'accent')
        self.dashboard_load_btn.clicked.connect(self._dashboard_load_from_input)
        self.dashboard_export_options_btn = QPushButton('Export Top Options')
        self.set_theme_variant(self.dashboard_export_options_btn, 'accent')
        self.dashboard_export_options_btn.clicked.connect(self._dashboard_export_top_options)
        self.dashboard_auto_btn = QPushButton('Auto')
        self.dashboard_auto_btn.setCheckable(True)
        self.dashboard_auto_btn.clicked.connect(self._dashboard_toggle_auto_follow)
        self.dashboard_timeframe_group = QButtonGroup(self)
        self.dashboard_timeframe_group.setExclusive(True)
        self.dashboard_timeframe_buttons = {}
        self.dashboard_indicator_buttons = {}
        self.dashboard_option_tables = {}

        header_widget = QWidget()
        header_widget.setMinimumWidth(0)
        header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        toolbar_title = QLabel('<b>Dashboard Chart</b>')
        self.set_theme_role(toolbar_title, 'page_title')
        toolbar.addWidget(toolbar_title)
        toolbar.addSpacing(6)
        toolbar.addWidget(self.dashboard_symbol_input)
        toolbar.addWidget(self.dashboard_load_btn)
        toolbar.addWidget(self.dashboard_export_options_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.dashboard_auto_btn)
        header_layout.addLayout(toolbar)

        timeframe_scroll = QScrollArea()
        timeframe_scroll.setWidgetResizable(False)
        timeframe_scroll.setFrameShape(QFrame.Shape.NoFrame)
        timeframe_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        timeframe_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        timeframe_scroll.setMinimumWidth(0)
        timeframe_scroll.setMinimumHeight(30)
        timeframe_scroll.setMaximumHeight(36)
        timeframe_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        timeframe_widget = QWidget()
        timeframe_widget.setMinimumWidth(0)
        timeframe_layout = QHBoxLayout(timeframe_widget)
        timeframe_layout.setContentsMargins(0, 0, 0, 0)
        timeframe_layout.setSpacing(4)
        for label, _, _ in timeframe_options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(24)
            btn.clicked.connect(partial(self._dashboard_set_timeframe, label))
            self.dashboard_timeframe_group.addButton(btn)
            self.dashboard_timeframe_buttons[label] = btn
            timeframe_layout.addWidget(btn)
        timeframe_layout.addStretch()
        timeframe_scroll.setWidget(timeframe_widget)

        indicator_row = QHBoxLayout()
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(4)
        indicator_label = QLabel('Indicators')
        self.set_theme_role(indicator_label, 'muted')
        indicator_row.addWidget(indicator_label)
        indicator_row.addSpacing(2)
        for name in ('Volume', 'RSI', '200 MA'):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setMinimumHeight(24)
            btn.clicked.connect(partial(self._dashboard_toggle_indicator, name))
            self.dashboard_indicator_buttons[name] = btn
            indicator_row.addWidget(btn)

        info_strip = QHBoxLayout()
        info_strip.setContentsMargins(0, 0, 0, 0)
        info_strip.setSpacing(6)
        self.dashboard_symbol_label = QLabel(self.dashboard_chart_state.get('symbol', 'SPY'))
        self.dashboard_price_label = QLabel('--')
        self.dashboard_price_label.setMinimumHeight(24)
        self.dashboard_price_label.setMinimumWidth(92)
        self.dashboard_change_label = QLabel('--')
        self.dashboard_ohlc_label = QLabel('O --  H --  L --  C --')
        self.dashboard_status_label = QLabel('Ready')
        self.set_theme_role(self.dashboard_status_label, 'status_muted')
        info_strip.addWidget(self.dashboard_symbol_label)
        info_strip.addSpacing(8)
        info_strip.addWidget(self.dashboard_price_label)
        info_strip.addWidget(self.dashboard_change_label)
        info_strip.addSpacing(8)
        info_strip.addWidget(self.dashboard_ohlc_label, 1)
        info_strip.addWidget(self.dashboard_status_label)

        compact_row = QHBoxLayout()
        compact_row.setContentsMargins(0, 0, 0, 0)
        compact_row.setSpacing(6)
        compact_row.addWidget(timeframe_scroll, 2)
        compact_row.addLayout(indicator_row)
        compact_row.addSpacing(4)
        compact_row.addLayout(info_strip, 3)
        header_layout.addLayout(compact_row)
        right_col.addWidget(header_widget)

        self.dashboard_body_splitter = QSplitter(Qt.Orientation.Horizontal)
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(6)
        self.dashboard_panels = QSplitter(Qt.Orientation.Vertical)
        self.dashboard_chart_axis = DateAxisItem(orientation='bottom')
        self.dashboard_main_plot = pg.PlotWidget(axisItems={'bottom': self.dashboard_chart_axis})
        self.dashboard_main_plot.showGrid(x=True, y=True, alpha=0.15)
        self.dashboard_main_plot.getPlotItem().setMenuEnabled(False)
        self.dashboard_main_plot.getPlotItem().hideAxis('left')
        self.dashboard_main_plot.getPlotItem().showAxis('right')
        self.dashboard_main_plot.getPlotItem().vb.sigXRangeChanged.connect(self._dashboard_on_x_range_changed)
        self.dashboard_main_plot.getPlotItem().vb.sigRangeChanged.connect(self._dashboard_refresh_overlay_positions)
        self.dashboard_volume_axis = DateAxisItem(orientation='bottom')
        self.dashboard_volume_plot = pg.PlotWidget(axisItems={'bottom': self.dashboard_volume_axis})
        self.dashboard_volume_plot.showGrid(x=True, y=False, alpha=0.1)
        self.dashboard_volume_plot.getPlotItem().setMenuEnabled(False)
        self.dashboard_volume_plot.getPlotItem().hideAxis('left')
        self.dashboard_volume_plot.getPlotItem().showAxis('right')
        self.dashboard_volume_plot.setMaximumHeight(160)
        self.dashboard_volume_plot.setXLink(self.dashboard_main_plot)
        self.dashboard_volume_plot.getPlotItem().vb.sigRangeChanged.connect(self._dashboard_refresh_overlay_positions)
        self.dashboard_rsi_axis = DateAxisItem(orientation='bottom')
        self.dashboard_rsi_plot = pg.PlotWidget(axisItems={'bottom': self.dashboard_rsi_axis})
        self.dashboard_rsi_plot.showGrid(x=True, y=True, alpha=0.1)
        self.dashboard_rsi_plot.getPlotItem().setMenuEnabled(False)
        self.dashboard_rsi_plot.getPlotItem().hideAxis('left')
        self.dashboard_rsi_plot.getPlotItem().showAxis('right')
        self.dashboard_rsi_plot.setMaximumHeight(160)
        self.dashboard_rsi_plot.setXLink(self.dashboard_main_plot)
        self.dashboard_rsi_plot.getPlotItem().vb.sigRangeChanged.connect(self._dashboard_refresh_overlay_positions)
        self.dashboard_panels.addWidget(self.dashboard_main_plot)
        self.dashboard_panels.addWidget(self.dashboard_volume_plot)
        self.dashboard_panels.addWidget(self.dashboard_rsi_plot)
        self.dashboard_panels.setStretchFactor(0, 6)
        self.dashboard_panels.setStretchFactor(1, 2)
        self.dashboard_panels.setStretchFactor(2, 2)
        chart_layout.addWidget(self.dashboard_panels, 1)
        self.dashboard_body_splitter.addWidget(chart_container)

        options_sidebar = QWidget()
        options_layout = QVBoxLayout(options_sidebar)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)
        for bucket_key, bucket_title in (
            ('0_week', 'Top Options by Volume - 0 Week'),
            ('2_weeks', 'Top Options by Volume - 2 Weeks'),
            ('4_weeks', 'Top Options by Volume - 4 Weeks'),
        ):
            bucket_label = QLabel(bucket_title)
            self.set_theme_role(bucket_label, 'section_title')
            table = QTableWidget(0, 6)
            table.setHorizontalHeaderLabels(['Ticker', 'Type', 'Strike', 'Exp', 'Price', 'Vol'])
            table.horizontalHeader().setMinimumHeight(28)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setDefaultSectionSize(24)
            table.setAlternatingRowColors(True)
            options_layout.addWidget(bucket_label)
            options_layout.addWidget(table, 1)
            self.dashboard_option_tables[bucket_key] = table
        self.dashboard_body_splitter.addWidget(options_sidebar)
        self.dashboard_body_splitter.setStretchFactor(0, 5)
        self.dashboard_body_splitter.setStretchFactor(1, 2)
        self.dashboard_body_splitter.splitterMoved.connect(self._dashboard_on_splitter_moved)
        right_col.addWidget(self.dashboard_body_splitter, 1)
        self._dashboard_apply_splitter_sizes()
        self.dashboard_crosshair_proxy = pg.SignalProxy(self.dashboard_main_plot.scene().sigMouseMoved, rateLimit=30, slot=self._dashboard_on_mouse_moved)
        self._dashboard_refresh_portfolio_selector()
        self.dashboard_main_splitter.addWidget(left_widget)
        self.dashboard_main_splitter.addWidget(right_widget)
        self.dashboard_main_splitter.setStretchFactor(0, 3)
        self.dashboard_main_splitter.setStretchFactor(1, 5)
        self.dashboard_main_splitter.splitterMoved.connect(self._dashboard_on_main_splitter_moved)
        main_layout.addWidget(self.dashboard_main_splitter)
        self._dashboard_apply_main_splitter_sizes()
        self._bind_page_interaction_logging(self.page1, 0)
        logger.info('Page load complete: Dashboard (index 0) in %.3fs.', time.perf_counter() - started_at)
        self._startup_progress_complete_page(0, 'Dashboard')

    def _lazy_page_specs(self) -> tuple[dict[str, Any], ...]:
        """Return metadata for pages that can be initialized after first paint."""
        return (
            {'index': 1, 'page_attr': 'page4', 'init_method': 'init_page4', 'theme_hook': '_apply_portfolio_theme', 'hydrate_hook': '_hydrate_lazy_page4'},
            {'index': 2, 'page_attr': 'page6', 'init_method': 'init_page6', 'theme_hook': '_apply_networth_theme'},
            {'index': 3, 'page_attr': 'page7', 'init_method': 'init_page7', 'theme_hook': '_apply_calendar_theme', 'hydrate_hook': '_hydrate_lazy_page7'},
            {'index': 4, 'page_attr': 'page3', 'init_method': 'init_page3', 'theme_hook': '_apply_news_theme', 'hydrate_hook': '_hydrate_lazy_page3'},
            {'index': 5, 'page_attr': 'page8', 'init_method': 'init_page8', 'theme_hook': '_apply_sectors_theme'},
            {'index': 6, 'page_attr': 'page17', 'init_method': 'init_page17', 'theme_hook': '_apply_spy_heatmap_theme'},
            {'index': 7, 'page_attr': 'page12', 'init_method': 'init_page12', 'theme_hook': '_apply_stocks_theme'},
            {'index': 8, 'page_attr': 'page2', 'init_method': 'init_page2', 'theme_hook': '_apply_fundamentals_theme', 'layout_margins': (10, 10, 10, 10)},
            {'index': 9, 'page_attr': 'page10', 'init_method': 'init_page10', 'theme_hook': '_apply_charts_page_theme'},
            {'index': 10, 'page_attr': 'page11', 'placeholder_only': True},
            {'index': 11, 'page_attr': 'page5', 'init_method': 'init_page5', 'theme_hook': '_apply_options_chain_theme'},
            {'index': 12, 'page_attr': 'page13', 'init_method': 'init_page13', 'theme_hook': '_apply_etf_theme'},
            {'index': 13, 'page_attr': 'page14', 'init_method': 'init_page14'},
            {'index': 14, 'page_attr': 'page19', 'init_method': 'init_page19', 'theme_hook': '_apply_crypto_theme'},
            {'index': 15, 'page_attr': 'page15', 'init_method': 'init_page15', 'theme_hook': '_apply_politics_theme'},
            {'index': 16, 'page_attr': 'page16', 'init_method': 'init_page16', 'theme_hook': '_apply_youtube_theme'},
            {'index': 17, 'page_attr': 'page9', 'init_method': 'init_page9', 'theme_hook': '_apply_settings_theme'},
            {'index': 18, 'page_attr': 'page18', 'init_method': 'init_page18', 'theme_hook': '_apply_random_recommender_theme'},
            {'index': 19, 'page_attr': 'page20', 'init_method': 'init_page20'},
            {'index': 20, 'page_attr': 'page21', 'init_method': 'init_page21', 'theme_hook': '_apply_ipo_theme'},
            {'index': 21, 'page_attr': 'page22', 'init_method': 'init_page22', 'theme_hook': '_apply_dataroma_theme'},
        )

    def _register_lazy_pages(self) -> None:
        """Insert placeholders for secondary pages so they can be built on demand."""
        self._startup_progress_begin('lazy_registry', 'Page registry')
        self._lazy_page_registry = {}
        for spec in self._lazy_page_specs():
            placeholder = self._new_main_page_widget()
            setattr(self, spec['page_attr'], placeholder)
            self.stacked_widget.addWidget(placeholder)
            if spec.get('placeholder_only'):
                continue
            self._lazy_page_registry[int(spec['index'])] = {
                **spec,
                'widget': placeholder,
                'initialized': False,
            }
        page_labels = [(0, self._PAGE_LABELS.get(0, 'Dashboard'))]
        page_labels.extend(
            (int(spec['index']), self._PAGE_LABELS.get(int(spec['index']), f"Page {spec['index']}"))
            for spec in self._lazy_page_specs()
            if not spec.get('placeholder_only')
        )
        self._startup_progress_register_pages(tuple(page_labels))
        self._startup_progress_complete('lazy_registry', 'Page registry')

    def _initialize_startup_pages(self) -> None:
        """Keep secondary pages lazy so first paint stays responsive."""
        return

    def _lazy_page_entry(self, *, index: Any = None, page_attr: str | None = None) -> Any:
        """Return one lazy-page registry entry by index or page attribute."""
        registry = getattr(self, '_lazy_page_registry', {})
        if page_attr:
            for entry in registry.values():
                if entry.get('page_attr') == page_attr:
                    return entry
            return None
        try:
            numeric = int(index)
        except (TypeError, ValueError):
            return None
        return registry.get(numeric)

    def _page_initialized(self, *, index: Any = None, page_attr: str | None = None) -> bool:
        """Return whether a page has been fully initialized rather than left as a placeholder."""
        if page_attr == 'page1':
            return True
        try:
            if int(index) == 0:
                return True
        except (TypeError, ValueError):
            pass
        entry = self._lazy_page_entry(index=index, page_attr=page_attr)
        return bool(entry and entry.get('initialized'))

    def _call_if_page_initialized(
        self,
        fn_name: str,
        *args: Any,
        index: Any = None,
        page_attr: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Call one helper only when its owning page has been initialized."""
        if not self._page_initialized(index=index, page_attr=page_attr):
            return False
        fn = getattr(self, fn_name, None)
        if not callable(fn):
            return False
        fn(*args, **kwargs)
        return True

    def _build_page_now(self, index: Any, *, reason: str='lazy') -> Any:
        """Replace a lazy placeholder with the real page widget and initialize it once."""
        entry = self._lazy_page_entry(index=index)
        if entry is None:
            return None
        if entry.get('initialized'):
            return entry.get('widget')
        started_at = time.perf_counter()
        placeholder = entry.get('widget')
        page_attr = str(entry.get('page_attr', '') or '')
        page_index = int(entry['index'])
        page_label = self._page_label(page_index)
        logger.info('Page load started: %s (index %s, reason=%s).', page_label, page_index, reason)
        self._startup_progress_begin_page(page_index, page_label)
        page = self._new_main_page_widget()
        setattr(self, page_attr, page)
        self.stacked_widget.insertWidget(page_index, page)
        init_method = getattr(self, str(entry.get('init_method', '') or ''), None)
        if not callable(init_method):
            raise AttributeError(f'Missing initializer for lazy page {page_attr}.')
        layout_margins = entry.get('layout_margins')
        if layout_margins is not None:
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(*tuple(layout_margins))
            init_method(page_layout)
        else:
            init_method()
        if placeholder is not None:
            self.stacked_widget.removeWidget(placeholder)
            placeholder.deleteLater()
        entry['widget'] = page
        entry['initialized'] = True
        theme_hook = getattr(self, str(entry.get('theme_hook', '') or ''), None)
        if callable(theme_hook):
            theme_hook()
        hydrate_hook = getattr(self, str(entry.get('hydrate_hook', '') or ''), None)
        if callable(hydrate_hook):
            hydrate_hook()
        session_restore_hook = getattr(self, '_restore_lazy_session_for_page', None)
        if callable(session_restore_hook):
            session_restore_hook(page_index)
        if hasattr(self, '_lazy_warmup_queue') and int(entry['index']) in getattr(self, '_lazy_warmup_queue', []):
            self._lazy_warmup_queue = [value for value in self._lazy_warmup_queue if int(value) != int(entry['index'])]
        self._bind_page_interaction_logging(page, page_index)
        logger.info('Page load complete: %s (index %s, reason=%s) in %.3fs.', page_label, page_index, reason, time.perf_counter() - started_at)
        self._startup_progress_complete_page(page_index, page_label)
        self._startup_progress_finish_if_complete()
        return page

    def _hydrate_lazy_page4(self) -> None:
        """Populate the Portfolio workspace with the current runtime state after lazy init."""
        if hasattr(self, '_sync_after_portfolio_change'):
            self._sync_after_portfolio_change(refresh_main=False)

    def _hydrate_lazy_page3(self) -> None:
        """Populate the News page from the most recent dashboard payload after lazy init."""
        if isinstance(getattr(self, 'last_data', None), dict):
            self.update_page3(self.last_data)

    def _hydrate_lazy_page7(self) -> None:
        """Refresh calendar-derived tables after lazy init."""
        if hasattr(self, '_p7_refresh_options_expirations'):
            self._p7_refresh_options_expirations()
        if hasattr(self, '_p7_render_month'):
            self._p7_render_month()
        if hasattr(self, '_p7_queue_market_holiday_year'):
            self._p7_queue_market_holiday_year(getattr(self, '_p7_year', None))
        if hasattr(self, '_p7_fetch_events'):
            self._p7_fetch_events()

    def _apply_window_theme(self) -> None:
        """Apply the active theme to shared shell widgets and dashboard plots."""
        self.set_status_text(self.status_bar, self.status_bar.text(), status=self.status_bar.property('bt_status') or 'muted')
        if hasattr(self, 'data_health_label'):
            self.set_status_text(self.data_health_label, self.data_health_label.text(), status=self.data_health_label.property('bt_status') or 'positive')
        self.set_status_text(self.data_collection_label, self.data_collection_label.text(), status=self.data_collection_label.property('bt_status') or 'muted')
        for plot in getattr(self, 'charts', []):
            self.style_plot_widget(plot)
