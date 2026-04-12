from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import math
from typing import Any
from ..compat import *


MC_TIMEFRAME_OPTIONS = [
    ('1D', '1y', '1d'),
    ('1W', '5y', '1wk'),
    ('1M', '5y', '1mo'),
]
MC_DEFAULT_TIMEFRAME = '1D'
MC_CHART_MIN_W = 380
MC_CHART_MIN_H = 280
MC_AUTO_ANCHOR = 0.85
MC_DEFAULT_SPAN = 80.0
MC_MIN_SPAN = 10.0


class _MCViewBox(pg.ViewBox):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a ViewBox that ignores the wheel until armed by a click."""
        super().__init__(*args, **kwargs)
        self._wheel_enabled = False

    def set_wheel_enabled(self, enabled: Any) -> None:
        """Toggle whether wheel events are allowed to change the view."""
        self._wheel_enabled = bool(enabled)

    def wheelEvent(self, event: Any, axis: Any = None) -> None:
        """Ignore wheel zoom until the chart is explicitly activated."""
        if not self._wheel_enabled:
            event.ignore()
            return
        super().wheelEvent(event, axis=axis)


class _MCPlotWidget(pg.PlotWidget):

    def __init__(self, *args: Any, activate_callback: Any = None, **kwargs: Any) -> None:
        """Create a plot widget that activates wheel interaction on click."""
        self._activate_callback = activate_callback
        super().__init__(*args, **kwargs)

    def mousePressEvent(self, event: Any) -> None:
        """Arm wheel interaction when the user explicitly clicks the chart."""
        if callable(self._activate_callback):
            self._activate_callback()
        super().mousePressEvent(event)

    def wheelEvent(self, event: Any) -> None:
        """Forward wheel events to the parent scroll area until activated."""
        view_box = self.getPlotItem().vb
        if getattr(view_box, '_wheel_enabled', False):
            super().wheelEvent(event)
            return
        event.ignore()
        parent = self.parent()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parent()
        if parent is not None:
            QApplication.sendEvent(parent.viewport(), event)


class MultiChartsMixin:

    def init_page11(self, container: Any = None, *, show_title: bool = True) -> None:
        """Build the Multi Charts view into the provided container once."""
        if getattr(self, '_mc_initialized', False):
            return
        self._mc_initialized = True
        self._mc_charts: dict[str, dict] = {}
        self._mc_timeframe_label = MC_DEFAULT_TIMEFRAME
        self._mc_timeframe_map = {label: (period, interval) for label, period, interval in MC_TIMEFRAME_OPTIONS}
        self._mc_fetching: set[str] = set()
        mc_state = load_multi_charts_settings()
        self._mc_custom_symbols: list[str] = list(mc_state.get('custom_symbols', []))
        self._mc_saved_order: list[str] = list(mc_state.get('order', []))
        self._mc_cols = 3
        self._mc_chart_style = 'Candlestick'
        self._mc_active_interaction_symbol = None
        self._mc_executor = ThreadPoolExecutor(max_workers=4)
        self._mc_resize_timer = QTimer(self)
        self._mc_resize_timer.setSingleShot(True)
        self._mc_resize_timer.timeout.connect(self._mc_handle_resize)
        self._mc_active_tab = 'portfolio'
        self._mc_container = container if container is not None else self.page11

        layout = QVBoxLayout(self._mc_container)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        if show_title:
            title = QLabel('<b>Multi Charts</b>')
            self.set_theme_role(title, 'page_title')
            toolbar.addWidget(title)
            toolbar.addSpacing(16)

        self._mc_tab_group = QButtonGroup(self)
        self._mc_tab_group.setExclusive(True)
        self._mc_tab_buttons: dict[str, QPushButton] = {}
        for tab_label, tab_key in (('Portfolio', 'portfolio'), ('Watchlist', 'watchlist')):
            btn = QPushButton(tab_label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(lambda checked, k=tab_key: self._mc_switch_tab(k))
            self._mc_tab_group.addButton(btn)
            self._mc_tab_buttons[tab_key] = btn
            toolbar.addWidget(btn)
        self._mc_tab_buttons['portfolio'].setChecked(True)
        toolbar.addSpacing(16)

        self._mc_timeframe_group = QButtonGroup(self)
        self._mc_timeframe_group.setExclusive(True)
        self._mc_timeframe_buttons: dict[str, QPushButton] = {}
        for label, _, _ in MC_TIMEFRAME_OPTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(lambda checked, lbl=label: self._mc_set_timeframe(lbl))
            self._mc_timeframe_group.addButton(btn)
            self._mc_timeframe_buttons[label] = btn
            toolbar.addWidget(btn)
        self._mc_timeframe_buttons[MC_DEFAULT_TIMEFRAME].setChecked(True)

        toolbar.addSpacing(12)
        self._mc_style_group = QButtonGroup(self)
        self._mc_style_group.setExclusive(True)
        self._mc_style_buttons: dict[str, QPushButton] = {}
        for style_name in ('Candlestick', 'Line'):
            btn = QPushButton(style_name)
            btn.setCheckable(True)
            btn.setMinimumHeight(26)
            btn.clicked.connect(lambda checked, s=style_name: self._mc_set_chart_style(s))
            self._mc_style_group.addButton(btn)
            self._mc_style_buttons[style_name] = btn
            toolbar.addWidget(btn)
        self._mc_style_buttons['Candlestick'].setChecked(True)

        toolbar.addSpacing(20)
        self._mc_add_input = QLineEdit()
        self._mc_add_input.setPlaceholderText('Add ticker (e.g. AAPL)')
        self._mc_add_input.setFixedWidth(160)
        self._mc_add_input.returnPressed.connect(self._mc_add_symbol)
        self._mc_add_btn = QPushButton('Add')
        self.set_theme_variant(self._mc_add_btn, 'accent')
        self._mc_add_btn.setFixedHeight(28)
        self._mc_add_btn.clicked.connect(self._mc_add_symbol)
        toolbar.addWidget(self._mc_add_input)
        toolbar.addWidget(self._mc_add_btn)

        toolbar.addSpacing(12)
        self._mc_reorder_btn = QPushButton('Reorder')
        self._mc_reorder_btn.setFixedHeight(28)
        self._mc_reorder_btn.clicked.connect(self._mc_open_reorder_dialog)
        toolbar.addWidget(self._mc_reorder_btn)

        refresh_btn = QPushButton('Refresh All')
        self.set_theme_variant(refresh_btn, 'accent')
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(self._mc_refresh_all)
        self._mc_refresh_btn = refresh_btn
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch()
        self._mc_status = QLabel('')
        self.set_theme_role(self._mc_status, 'status_muted')
        toolbar.addWidget(self._mc_status)
        layout.addLayout(toolbar)

        self._mc_scroll = QScrollArea()
        self._mc_scroll.setWidgetResizable(True)
        self._mc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._mc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._mc_grid_widget = QWidget()
        self._mc_grid_layout = QGridLayout(self._mc_grid_widget)
        self._mc_grid_layout.setContentsMargins(0, 0, 0, 0)
        self._mc_grid_layout.setSpacing(8)
        self._mc_scroll.setWidget(self._mc_grid_widget)
        self._mc_scroll.viewport().installEventFilter(self)
        layout.addWidget(self._mc_scroll, 1)

    def _mc_on_show(self) -> None:
        """Refresh the Multi Charts symbol grid when its view becomes visible."""
        symbols = self._mc_get_active_symbols()
        self._mc_sync_grid(symbols)
        if not self._mc_charts:
            self._mc_set_status('', 'muted')
            self._mc_sync_status_to_status_bar()
            return
        for sym in symbols:
            entry = self._mc_charts.get(sym)
            if entry and entry.get('df') is None:
                self._mc_fetch_single(sym)
        self._mc_sync_status_to_status_bar()

    def _mc_set_status(self, text: Any, status: Any = 'muted') -> None:
        """Set the Multi Charts status label and mirror it when visible."""
        if not hasattr(self, '_mc_status'):
            return
        self.set_status_text(self._mc_status, text, status=str(status))
        self._mc_sync_status_to_status_bar()

    def _mc_sync_status_to_status_bar(self) -> None:
        """Mirror the Multi Charts status into the shared footer when active."""
        if not hasattr(self, 'status_bar') or not hasattr(self, '_mc_status'):
            return
        is_active = (
            hasattr(self, '_p10_active_subtab_key')
            and callable(getattr(self, '_p10_active_subtab_key'))
            and self._p10_active_subtab_key() == 'multicharts'
        )
        if not is_active:
            return
        self.set_status_text(
            self.status_bar,
            self._mc_status.text(),
            status=str(self._mc_status.property('bt_status') or 'muted'),
        )

    def _mc_switch_tab(self, tab_key: str) -> None:
        """Switch between Portfolio and Watchlist tabs."""
        if tab_key == self._mc_active_tab:
            return
        self._mc_active_tab = tab_key
        for key, btn in self._mc_tab_buttons.items():
            btn.setChecked(key == tab_key)
        show_add = tab_key == 'portfolio'
        self._mc_add_input.setVisible(show_add)
        self._mc_add_btn.setVisible(show_add)
        self._mc_reorder_btn.setVisible(show_add)
        symbols = self._mc_get_active_symbols()
        self._mc_rebuild_grid(symbols)

    def _mc_get_active_symbols(self) -> list[str]:
        """Return symbols for the active tab."""
        if self._mc_active_tab == 'watchlist':
            return self._mc_get_watchlist_symbols()
        return self._mc_get_all_symbols()

    def _mc_get_watchlist_symbols(self) -> list[str]:
        """Return watchlist symbols from the Charts page."""
        watchlist = getattr(self, 'p10_custom_watchlist', [])
        seen = set()
        result = []
        for sym in watchlist:
            s = sym.upper().strip()
            if s and s not in seen:
                seen.add(s)
                result.append(s)
        return result

    def _mc_get_all_symbols(self) -> list[str]:
        """Return portfolio tickers + custom symbols, deduplicated, respecting saved order."""
        portfolio = list(getattr(self, 'tickers', []))
        seen = set()
        unordered = []
        for sym in portfolio + self._mc_custom_symbols:
            s = sym.upper().strip()
            if s and s not in seen:
                seen.add(s)
                unordered.append(s)
        if not self._mc_saved_order:
            return unordered
        result = []
        for s in self._mc_saved_order:
            if s in seen:
                result.append(s)
                seen.discard(s)
        for s in unordered:
            if s in seen:
                result.append(s)
        return result

    def _mc_save_state(self) -> None:
        """Persist custom symbols and chart order."""
        save_multi_charts_settings({
            'custom_symbols': list(self._mc_custom_symbols),
            'order': list(self._mc_charts.keys()),
        })

    def _mc_add_symbol(self) -> None:
        """Add a custom symbol from the input field."""
        text = self._mc_add_input.text().strip().upper()
        if not text:
            return
        self._mc_add_input.clear()
        existing = self._mc_get_all_symbols()
        if text in existing:
            self._mc_set_status(f'{text} already shown.', 'warning')
            return
        self._mc_custom_symbols.append(text)
        self._mc_sync_grid(self._mc_get_all_symbols())
        self._mc_fetch_single(text)
        self._mc_save_state()

    def _mc_remove_symbol(self, symbol: str) -> None:
        """Remove a custom symbol (portfolio/watchlist symbols can't be removed here)."""
        if self._mc_active_tab == 'watchlist':
            self._mc_set_status(f'{symbol} is in your watchlist \u2014 remove it in Charts.', 'warning')
            return
        portfolio = set(s.upper() for s in getattr(self, 'tickers', []))
        if symbol.upper() in portfolio:
            self._mc_set_status(f'{symbol} is in your portfolio \u2014 remove it there.', 'warning')
            return
        self._mc_custom_symbols = [s for s in self._mc_custom_symbols if s.upper() != symbol.upper()]
        if symbol in self._mc_charts:
            entry = self._mc_charts.pop(symbol)
            entry['frame'].setParent(None)
            entry['frame'].deleteLater()
        self._mc_relayout()
        self._mc_save_state()
        self._mc_set_status(f'Removed {symbol}.', 'muted')

    def _mc_open_reorder_dialog(self) -> None:
        """Open a drag-and-drop dialog to reorder charts."""
        symbols = list(self._mc_charts.keys())
        if len(symbols) < 2:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle('Reorder Charts')
        dialog.setMinimumWidth(320)
        dialog.setMinimumHeight(400)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(12, 12, 12, 12)
        dlg_layout.setSpacing(10)

        hint = QLabel('Drag items to reorder your charts.')
        hint.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px;')
        dlg_layout.addWidget(hint)

        list_widget = QListWidget()
        list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        list_widget.setStyleSheet(
            f'QListWidget {{ background-color: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 4px; '
            f'font-size: 13px; color: {self.theme_color("text_primary")}; }} '
            f'QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {self.theme_color("gridline")}; }} '
            f'QListWidget::item:selected {{ background-color: {self.theme_color("selected_bg")}; }} '
            f'QListWidget::item:hover {{ background-color: {self.theme_color("hover_bg")}; }}'
        )
        for sym in symbols:
            entry = self._mc_charts.get(sym)
            change_text = entry['change_label'].text() if entry else ''
            price_text = entry['price_label'].text() if entry else ''
            label = f'{sym}    {price_text}  {change_text}' if price_text and price_text != '--' else sym
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sym)
            list_widget.addItem(item)
        dlg_layout.addWidget(list_widget, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(dialog.reject)
        apply_btn = QPushButton('Apply')
        self.set_theme_variant(apply_btn, 'accent')
        apply_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        dlg_layout.addLayout(btn_row)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_order = []
            for i in range(list_widget.count()):
                sym = list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                new_order.append(sym)
            self._mc_apply_new_order(new_order)

    def _mc_apply_new_order(self, new_order: list[str]) -> None:
        """Reorder chart cards to match a new symbol order."""
        old_keys = list(self._mc_charts.keys())
        if new_order == old_keys:
            return
        reordered = {}
        for sym in new_order:
            if sym in self._mc_charts:
                reordered[sym] = self._mc_charts[sym]
        for sym in old_keys:
            if sym not in reordered:
                reordered[sym] = self._mc_charts[sym]
        self._mc_charts = reordered
        portfolio_set = set(t.upper() for t in getattr(self, 'tickers', []))
        self._mc_custom_symbols = [s for s in reordered if s not in portfolio_set]
        self._mc_relayout()
        self._mc_save_state()

    def _mc_set_chart_style(self, style: str) -> None:
        """Switch between Candlestick and Line chart styles."""
        if style == self._mc_chart_style:
            return
        self._mc_chart_style = style
        for name, btn in self._mc_style_buttons.items():
            btn.setChecked(name == style)
        for sym, entry in self._mc_charts.items():
            if entry.get('df') is not None and not entry['df'].empty:
                self._mc_render_chart(sym, entry, entry['df'])

    def _mc_set_timeframe(self, label: str) -> None:
        """Switch timeframe for all charts."""
        if label == self._mc_timeframe_label:
            return
        self._mc_timeframe_label = label
        for lbl, btn in self._mc_timeframe_buttons.items():
            btn.setChecked(lbl == label)
        self._mc_refresh_all()

    def _mc_refresh_all(self) -> None:
        """Fetch fresh data for all visible charts."""
        symbols = list(self._mc_charts.keys())
        if not symbols:
            symbols = self._mc_get_active_symbols()
            if symbols:
                self._mc_sync_grid(symbols)
        if symbols:
            self._mc_set_status(f'Loading {len(symbols)} chart{"s" if len(symbols) != 1 else ""}...', 'info')
        for sym in symbols:
            self._mc_fetch_single(sym)

    def _mc_rebuild_grid(self, symbols: list[str]) -> None:
        """Tear down and rebuild all chart cards."""
        for entry in self._mc_charts.values():
            entry['frame'].setParent(None)
            entry['frame'].deleteLater()
        self._mc_charts.clear()

        for sym in symbols:
            self._mc_charts[sym] = self._mc_create_chart_card(sym)

        self._mc_relayout()
        if not symbols:
            self._mc_set_status('', 'muted')
            return

        for sym in symbols:
            self._mc_fetch_single(sym)

    def _mc_sync_grid(self, symbols: list[str]) -> None:
        """Apply symbol set changes without rebuilding every chart card."""
        desired = [str(sym or '').upper().strip() for sym in symbols if str(sym or '').upper().strip()]
        desired_set = set(desired)
        current_symbols = list(self._mc_charts.keys())
        changed = False

        for sym in current_symbols:
            if sym in desired_set:
                continue
            entry = self._mc_charts.pop(sym, None)
            if entry:
                entry['frame'].setParent(None)
                entry['frame'].deleteLater()
                changed = True
            if self._mc_active_interaction_symbol == sym:
                self._mc_active_interaction_symbol = None

        for sym in desired:
            if sym in self._mc_charts:
                continue
            self._mc_charts[sym] = self._mc_create_chart_card(sym)
            changed = True

        reordered = {}
        for sym in desired:
            entry = self._mc_charts.get(sym)
            if entry:
                reordered[sym] = entry
        if list(reordered.keys()) != list(self._mc_charts.keys()):
            self._mc_charts = reordered
            changed = True

        if changed or self._mc_cols != self._mc_compute_cols():
            self._mc_relayout()
        self._mc_save_state()

    def _mc_compute_cols(self) -> int:
        """Compute grid column count based on viewport width."""
        vw = self._mc_scroll.viewport().width()
        if vw <= 0:
            return 3
        cols = max(1, vw // MC_CHART_MIN_W)
        return cols

    def _mc_relayout(self) -> None:
        """Re-arrange chart cards in the grid."""
        while self._mc_grid_layout.count():
            item = self._mc_grid_layout.takeAt(0)
            if item.widget():
                item.widget().hide()

        symbols = list(self._mc_charts.keys())
        cols = self._mc_compute_cols()
        self._mc_cols = cols
        for idx, sym in enumerate(symbols):
            entry = self._mc_charts.get(sym)
            if entry:
                row, col = divmod(idx, cols)
                self._mc_grid_layout.addWidget(entry['frame'], row, col)
                entry['frame'].show()

    def _mc_create_chart_card(self, symbol: str) -> dict:
        """Create a single chart card with header + plot widget."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setMinimumHeight(MC_CHART_MIN_H)
        frame.setStyleSheet(
            f'QFrame {{ background-color: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(4)

        header = QHBoxLayout()
        sym_label = QLabel(f'<b>{symbol}</b>')
        sym_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 14px; border: none;')
        price_label = QLabel('--')
        price_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
        change_label = QLabel('')
        change_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')

        remove_btn = QPushButton('\u00d7')
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet(
            f'QPushButton {{ color: {self.theme_color("text_muted")}; background: transparent; '
            f'border: none; font-size: 16px; font-weight: bold; }} '
            f'QPushButton:hover {{ color: {self.theme_color("accent_negative")}; }}'
        )
        remove_btn.setToolTip(f'Remove {symbol}')
        remove_btn.clicked.connect(lambda checked, s=symbol: self._mc_remove_symbol(s))

        header.addWidget(sym_label)
        header.addSpacing(8)
        header.addWidget(price_label)
        header.addWidget(change_label)
        header.addStretch()
        header.addWidget(remove_btn)
        card_layout.addLayout(header)

        date_axis = DateAxisItem(orientation='bottom')
        view_box = _MCViewBox()
        plot = _MCPlotWidget(
            viewBox=view_box,
            axisItems={'bottom': date_axis},
            activate_callback=lambda s=symbol: self._mc_activate_chart_interaction(s),
        )
        plot.showGrid(x=True, y=True, alpha=0.12)
        plot.getPlotItem().setMenuEnabled(False)
        plot.getPlotItem().hideAxis('left')
        plot.getPlotItem().showAxis('right')
        plot.setMinimumHeight(180)
        plot.setStyleSheet('border: none;')
        self.style_plot_widget(plot)

        view_guard = {'active': False}
        plot.getPlotItem().vb.sigXRangeChanged.connect(
            lambda *_, s=symbol, g=view_guard: self._mc_on_x_range_changed(s, g)
        )

        card_layout.addWidget(plot, 1)

        status_label = QLabel('Loading...')
        status_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 10px; border: none;')
        status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        card_layout.addWidget(status_label)

        return {
            'symbol': symbol,
            'frame': frame,
            'plot': plot,
            'view_box': view_box,
            'date_axis': date_axis,
            'sym_label': sym_label,
            'price_label': price_label,
            'change_label': change_label,
            'status_label': status_label,
            'remove_btn': remove_btn,
            'df': None,
            'rows': [],
            'view_guard': view_guard,
        }

    def _mc_activate_chart_interaction(self, symbol: str) -> None:
        """Allow wheel interaction only for the most recently clicked chart."""
        self._mc_active_interaction_symbol = symbol
        for chart_symbol, entry in self._mc_charts.items():
            entry.get('view_box').set_wheel_enabled(chart_symbol == symbol)

    # ------------------------------------------------------------------
    # Auto-follow viewport logic (always on)
    # ------------------------------------------------------------------

    def _mc_apply_auto_x_range(self, entry: dict, source_range: Any = None) -> None:
        """Anchor the latest bar near the right edge, preserving zoom span."""
        rows = entry.get('rows', [])
        if not rows:
            return
        latest_index = float(len(rows) - 1)
        if source_range and (float(source_range[1]) - float(source_range[0])) >= MC_MIN_SPAN:
            span = max(MC_MIN_SPAN, float(source_range[1]) - float(source_range[0]))
        else:
            span = max(20.0, min(MC_DEFAULT_SPAN, float(len(rows))))
        right_pad = span * (1.0 - MC_AUTO_ANCHOR)
        x_left = latest_index - span * MC_AUTO_ANCHOR
        x_right = latest_index + right_pad
        self._mc_set_x_range(entry, (x_left, x_right))
        self._mc_apply_auto_y_range(entry, (x_left, x_right))

    def _mc_set_x_range(self, entry: dict, x_range: Any) -> None:
        """Set x-range on a chart without re-triggering the range handler."""
        if not x_range:
            return
        left, right = float(x_range[0]), float(x_range[1])
        if right <= left:
            return
        entry['view_guard']['active'] = True
        try:
            entry['plot'].setXRange(left, right, padding=0)
        finally:
            entry['view_guard']['active'] = False

    def _mc_apply_auto_y_range(self, entry: dict, x_range: Any = None) -> None:
        """Fit y-axis to the visible bars."""
        rows = entry.get('rows', [])
        if not rows:
            return
        if x_range:
            left = max(0, int(math.floor(float(x_range[0]))))
            right = min(len(rows) - 1, int(math.ceil(float(x_range[1]))))
        else:
            left, right = 0, len(rows) - 1
        if right < left:
            return
        visible = rows[left:right + 1]
        if not visible:
            return
        if self._mc_chart_style == 'Line':
            values = [float(getattr(r, 'Close', 0)) for r in visible]
            low_val = min(values)
            high_val = max(values)
        else:
            low_val = min(float(getattr(r, 'Low', 0)) for r in visible)
            high_val = max(float(getattr(r, 'High', 0)) for r in visible)
        span = high_val - low_val
        pad = max(0.5, span * 0.08) if span > 0 else max(abs(high_val) * 0.03, 1.0)
        entry['plot'].setYRange(low_val - pad, high_val + pad, padding=0)

    def _mc_on_x_range_changed(self, symbol: str, guard: dict) -> None:
        """Re-anchor on zoom/scroll to keep current price in focus."""
        if guard.get('active'):
            return
        entry = self._mc_charts.get(symbol)
        if not entry or not entry.get('rows'):
            return
        try:
            current = tuple(entry['plot'].getPlotItem().vb.viewRange()[0])
        except Exception:
            return
        self._mc_apply_auto_x_range(entry, current)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _mc_fetch_single(self, symbol: str) -> None:
        """Fetch chart data for one symbol in a background thread."""
        if symbol in self._mc_fetching:
            return
        self._mc_fetching.add(symbol)
        self._mc_set_status(
            f'Loading {len(self._mc_fetching)} chart{"s" if len(self._mc_fetching) != 1 else ""}...',
            'info',
        )
        entry = self._mc_charts.get(symbol)
        if entry:
            entry['status_label'].setText('Loading...')

        def _run() -> None:
            try:
                period, interval = self._mc_timeframe_map.get(
                    self._mc_timeframe_label,
                    self._mc_timeframe_map[MC_DEFAULT_TIMEFRAME],
                )
                cache = self._get_cache_manager()
                df = cache.get_data(symbol, interval)
                if df is None or df.empty:
                    with YF_LOCK:
                        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
                    if df is not None and not df.empty and interval in ('1d', '1wk', '1mo'):
                        cache.save_data(symbol, interval, df)
                if df is None or df.empty:
                    self._invoke_main.emit(lambda s=symbol: self._mc_on_fetch_error(s, 'No data'))
                    return
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                rename_map = {}
                for col in list(df.columns):
                    text = str(col).strip().lower()
                    if text == 'open':
                        rename_map[col] = 'Open'
                    elif text == 'high':
                        rename_map[col] = 'High'
                    elif text == 'low':
                        rename_map[col] = 'Low'
                    elif text == 'close':
                        rename_map[col] = 'Close'
                    elif text == 'volume':
                        rename_map[col] = 'Volume'
                if rename_map:
                    df = df.rename(columns=rename_map)
                df = df.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
                self._invoke_main.emit(lambda s=symbol, d=df: self._mc_on_fetch_done(s, d))
            except Exception as exc:
                self._invoke_main.emit(lambda s=symbol, e=str(exc): self._mc_on_fetch_error(s, e))

        self._mc_executor.submit(_run)

    def _mc_on_fetch_done(self, symbol: str, df: Any) -> None:
        """Render chart data on the main thread."""
        self._mc_fetching.discard(symbol)
        entry = self._mc_charts.get(symbol)
        if not entry:
            return
        entry['df'] = df
        entry['rows'] = list(df.itertuples())
        self._mc_render_chart(symbol, entry, df)
        remaining = len(self._mc_fetching)
        if remaining > 0:
            self._mc_set_status(f'Loading {remaining} chart{"s" if remaining > 1 else ""}...', 'info')
        else:
            self._mc_set_status('', 'muted')

    def _mc_on_fetch_error(self, symbol: str, error: str) -> None:
        """Handle chart fetch error on the main thread."""
        self._mc_fetching.discard(symbol)
        entry = self._mc_charts.get(symbol)
        if entry:
            entry['status_label'].setText(f'Error: {error}')
            entry['status_label'].setStyleSheet(
                f'color: {self.theme_color("accent_negative")}; font-size: 10px; border: none;'
            )
        remaining = len(self._mc_fetching)
        if remaining == 0:
            self._mc_set_status('', 'muted')
        else:
            self._mc_set_status(f'Loading {remaining} chart{"s" if remaining != 1 else ""}...', 'info')

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _mc_render_chart(self, symbol: str, entry: dict, df: Any) -> None:
        """Render chart into a card's plot widget."""
        plot = entry['plot']
        plot.clear()

        rows = entry.get('rows') or list(df.itertuples())
        entry['rows'] = rows
        if not rows:
            entry['status_label'].setText('No data')
            return

        if self._mc_chart_style == 'Line':
            closes = [float(getattr(row, 'Close', 0)) for row in rows]
            x_vals = list(range(len(closes)))
            plot.plot(x_vals, closes, pen=pg.mkPen(color=self.theme_color('accent'), width=2), antialias=True)
        else:
            points = []
            for idx, row in enumerate(rows):
                o = float(getattr(row, 'Open', 0))
                c = float(getattr(row, 'Close', 0))
                l = float(getattr(row, 'Low', 0))
                h = float(getattr(row, 'High', 0))
                points.append((idx, o, c, l, h))
            candle_item = CandlestickItem(
                points,
                up_color=self.theme_color('chart_up_candle'),
                down_color=self.theme_color('chart_down_candle'),
            )
            plot.addItem(candle_item)

        dates = df.index.to_list()
        _, interval = self._mc_timeframe_map.get(
            self._mc_timeframe_label,
            self._mc_timeframe_map[MC_DEFAULT_TIMEFRAME],
        )
        entry['date_axis'].set_dates(dates, interval)

        latest = df.iloc[-1]
        last_close = float(latest['Close'])
        prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else last_close
        change_val = last_close - prev_close
        change_pct = (change_val / prev_close * 100) if prev_close else 0.0

        entry['price_label'].setText(f'${last_close:,.2f}')
        is_up = change_val >= 0
        color = self.theme_color('accent_positive' if is_up else 'accent_negative')
        sign = '+' if is_up else ''
        entry['change_label'].setText(f'{sign}{change_pct:.2f}%')
        entry['change_label'].setStyleSheet(f'color: {color}; font-size: 12px; font-weight: bold; border: none;')
        entry['price_label'].setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 12px; border: none;')

        last_line = pg.InfiniteLine(
            pos=last_close, angle=0,
            pen=pg.mkPen(color=self.theme_color('chart_reference'), width=1, style=Qt.PenStyle.DashLine),
        )
        plot.addItem(last_line)

        entry['status_label'].setText(f'{self._mc_timeframe_label} \u2022 {len(rows)} bars')
        entry['status_label'].setStyleSheet(
            f'color: {self.theme_color("text_muted")}; font-size: 10px; border: none;'
        )

        self._mc_apply_auto_x_range(entry)

    # ------------------------------------------------------------------
    # Responsive layout
    # ------------------------------------------------------------------

    def _mc_handle_resize(self) -> None:
        """Handle viewport resize to reflow the grid."""
        new_cols = self._mc_compute_cols()
        if new_cols != self._mc_cols:
            self._mc_relayout()

    def _mc_apply_theme(self) -> None:
        """Refresh Multi Charts widgets after a theme change."""
        for symbol, entry in getattr(self, '_mc_charts', {}).items():
            frame = entry.get('frame')
            if frame is not None:
                frame.setStyleSheet(
                    f'QFrame {{ background-color: {self.theme_color("panel_background")}; '
                    f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
                )
            sym_label = entry.get('sym_label')
            if sym_label is not None:
                sym_label.setStyleSheet(
                    f'color: {self.theme_color("text_primary")}; font-size: 14px; border: none;'
                )
            remove_btn = entry.get('remove_btn')
            if remove_btn is not None:
                remove_btn.setStyleSheet(
                    f'QPushButton {{ color: {self.theme_color("text_muted")}; background: transparent; '
                    f'border: none; font-size: 16px; font-weight: bold; }} '
                    f'QPushButton:hover {{ color: {self.theme_color("accent_negative")}; }}'
                )
            plot = entry.get('plot')
            if plot is not None:
                self.style_plot_widget(plot)
            df = entry.get('df')
            if df is not None and not df.empty:
                self._mc_render_chart(symbol, entry, df)
            else:
                price_label = entry.get('price_label')
                if price_label is not None:
                    price_label.setStyleSheet(
                        f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;'
                    )
                change_label = entry.get('change_label')
                if change_label is not None:
                    change_label.setStyleSheet(
                        f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;'
                    )
                status_label = entry.get('status_label')
                if status_label is not None:
                    status_color = 'accent_negative' if status_label.text().startswith('Error:') else 'text_muted'
                    status_label.setStyleSheet(
                        f'color: {self.theme_color(status_color)}; font-size: 10px; border: none;'
                    )
        if hasattr(self, '_mc_status'):
            self._mc_set_status(self._mc_status.text(), self._mc_status.property('bt_status') or 'muted')

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Intercept viewport resize for responsive relayout."""
        if hasattr(self, '_mc_scroll') and obj is self._mc_scroll.viewport():
            if event.type() == QEvent.Type.Resize:
                self._mc_resize_timer.start(75)
        return super().eventFilter(obj, event)
