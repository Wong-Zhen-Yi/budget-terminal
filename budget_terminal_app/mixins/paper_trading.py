from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable

from budget_terminal_app.compat import *
from budget_terminal_app.data_service.results import market_data_meta
from budget_terminal_app.paper_trading import (
    PaperOrderRequest,
    PaperTradingEngine,
    PaperTradingStore,
    YahooPaperQuoteService,
    format_share_quantity,
)
from budget_terminal_app.services.chart_data import ChartDataService
from budget_terminal_app.widgets.batched_render import run_batched


P31_SYMBOL_CHART_RANGES = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "30m"),
    "1M": ("1mo", "1h"),
    "3M": ("3mo", "1d"),
    "1Y": ("1y", "1wk"),
    "ALL": ("max", "1mo"),
}


class PaperTradingMixin:
    """First-class isolated paper-trading workspace."""

    _P31_ENGINE_INTERVAL_MS = 30_000
    _P31_MARK_INTERVAL_MS = 60_000

    def init_page31(self) -> None:
        page_layout = QVBoxLayout(self.page31)
        page_layout.setContentsMargins(12, 10, 12, 10)
        page_layout.setSpacing(8)
        self._p31_store = PaperTradingStore()
        self._p31_quote_service = YahooPaperQuoteService()
        self._p31_engine = PaperTradingEngine(self._p31_store, self._p31_quote_service)
        self._p31_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="BudgetTerminalPaper")
        self._p31_task_inflight = False
        self._p31_engine_started = False
        self._p31_active_account_id = ""
        self._p31_journal_entry_id = ""
        self._p31_chart_request_id = 0
        self._p31_chart_inflight = False
        self._p31_chart_loaded_symbol = ""
        self._p31_chart_loaded_range = ""
        self._p31_chart_range_key = "1M"
        self._p31_chart_frame = None
        self._p31_chart_data_service = None
        self._p31_owns_chart_data_service = False
        self._p31_view_request_seq = 0
        self._p31_view_refresh_running = False
        self._p31_view_refresh_context = None
        self._p31_view_refresh_pending = None
        self._p31_view_cache = {}
        self._p31_table_render_generations: dict[int, int] = {}
        self._p31_accounts_request_seq = 0
        self._p31_accounts_refresh_running = False
        self._p31_accounts_refresh_context = ""
        self._p31_accounts_refresh_pending: str | None = None
        self._p31_accounts: list[dict[str, Any]] = []
        self._p31_active_account_snapshot: dict[str, Any] | None = None

        page_layout.addWidget(self._p31_build_header())
        page_layout.addWidget(self._p31_build_empty_state())
        self.p31_workspace = QWidget()
        workspace_layout = QVBoxLayout(self.p31_workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(8)
        workspace_layout.addWidget(self._p31_build_summary())
        workspace_layout.addWidget(self._p31_build_body(), 1)
        page_layout.addWidget(self.p31_workspace, 1)
        self.p31_status_label = QLabel("Paper trading uses potentially delayed Yahoo bid/ask quotes.")
        self.set_theme_role(self.p31_status_label, "status_muted")
        page_layout.addWidget(self.p31_status_label)

        self._p31_engine_timer = QTimer(self)
        self._p31_engine_timer.setInterval(self._P31_ENGINE_INTERVAL_MS)
        self._p31_engine_timer.timeout.connect(lambda: self._p31_run_engine_cycle(mark=False))
        self._p31_mark_timer = QTimer(self)
        self._p31_mark_timer.setInterval(self._P31_MARK_INTERVAL_MS)
        self._p31_mark_timer.timeout.connect(lambda: self._p31_run_engine_cycle(mark=True))
        self._p31_refresh_accounts()

    def _p31_build_header(self) -> QFrame:
        frame = QFrame()
        self.set_theme_role(frame, "panel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        text = QVBoxLayout()
        title = QLabel("Paper Trading")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel("Long-only US stock and ETF simulation · Yahoo bid/ask · isolated from Portfolio and broker data")
        subtitle.setWordWrap(True)
        self.set_theme_role(subtitle, "muted")
        text.addWidget(title)
        text.addWidget(subtitle)
        layout.addLayout(text, 1)
        self.p31_account_combo = QComboBox()
        self.p31_account_combo.setMinimumWidth(190)
        self.p31_account_combo.currentIndexChanged.connect(self._p31_on_account_changed)
        self.p31_new_account_btn = QPushButton("New Account")
        self.set_theme_variant(self.p31_new_account_btn, "accent")
        self.p31_new_account_btn.clicked.connect(self._p31_create_account_dialog)
        self.p31_edit_account_btn = QPushButton("Edit")
        self.p31_edit_account_btn.clicked.connect(self._p31_edit_account_dialog)
        self.p31_archive_account_btn = QPushButton("Archive")
        self.set_theme_variant(self.p31_archive_account_btn, "danger")
        self.p31_archive_account_btn.clicked.connect(self._p31_toggle_archive_account)
        self.p31_refresh_btn = QPushButton("Refresh")
        self.p31_refresh_btn.clicked.connect(lambda: self._p31_run_engine_cycle(mark=True, force=True))
        layout.addWidget(self.p31_account_combo)
        layout.addWidget(self.p31_new_account_btn)
        layout.addWidget(self.p31_edit_account_btn)
        layout.addWidget(self.p31_archive_account_btn)
        layout.addWidget(self.p31_refresh_btn)
        return frame

    def _p31_build_empty_state(self) -> QFrame:
        self.p31_empty_state = QFrame()
        self.set_theme_role(self.p31_empty_state, "panel")
        layout = QVBoxLayout(self.p31_empty_state)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        title = QLabel("Create a paper account to begin")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(title, "section_title")
        detail = QLabel(
            "Choose a name and starting USD cash balance. Paper activity is stored in a separate SQLite ledger "
            "and never changes Portfolio or Combined holdings."
        )
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        self.set_theme_role(detail, "muted")
        button = QPushButton("Create Paper Account")
        button.setMinimumWidth(190)
        self.set_theme_variant(button, "accent")
        button.clicked.connect(self._p31_create_account_dialog)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addLayout(row)
        layout.addStretch(1)
        return self.p31_empty_state

    def _p31_build_summary(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.p31_summary_labels: dict[str, QLabel] = {}
        for key, title in (
            ("equity", "Equity"),
            ("cash", "Cash"),
            ("reserved_cash", "Reserved"),
            ("buying_power", "Buying Power"),
            ("realized_pnl", "Realized P&L"),
            ("unrealized_pnl", "Unrealized P&L"),
        ):
            frame = QFrame()
            self.set_theme_role(frame, "panel")
            card = QVBoxLayout(frame)
            card.setContentsMargins(10, 8, 10, 8)
            name = QLabel(title)
            self.set_theme_role(name, "muted")
            value = QLabel("$0.00")
            self.set_theme_role(value, "section_title")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            card.addWidget(name)
            card.addWidget(value)
            layout.addWidget(frame, 1)
            self.p31_summary_labels[key] = value
        return widget

    def _p31_build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._p31_build_order_ticket())
        splitter.addWidget(self._p31_build_tabs())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([330, 900])
        self.p31_main_splitter = splitter
        return splitter

    def _p31_build_order_ticket(self) -> QGroupBox:
        box = QGroupBox("Order Ticket")
        self.set_theme_role(box, "panel")
        box.setMinimumWidth(300)
        form = QFormLayout(box)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        self.p31_symbol_input = QLineEdit()
        self.p31_symbol_input.setPlaceholderText("AAPL")
        self.p31_symbol_input.setMaxLength(12)
        self.p31_symbol_input.textChanged.connect(self._p31_normalize_symbol)
        self.p31_symbol_input.returnPressed.connect(self._p31_request_symbol_chart)
        self.p31_chart_load_btn = QPushButton("Load")
        self.p31_chart_load_btn.clicked.connect(self._p31_request_symbol_chart)
        symbol_widget = QWidget()
        symbol_layout = QHBoxLayout(symbol_widget)
        symbol_layout.setContentsMargins(0, 0, 0, 0)
        symbol_layout.setSpacing(6)
        symbol_layout.addWidget(self.p31_symbol_input, 1)
        symbol_layout.addWidget(self.p31_chart_load_btn)
        self.p31_side_combo = QComboBox()
        self.p31_side_combo.addItem("Buy", "buy")
        self.p31_side_combo.addItem("Sell", "sell")
        self.p31_order_type_combo = QComboBox()
        for label, value in (("Market", "market"), ("Limit", "limit"), ("Stop", "stop")):
            self.p31_order_type_combo.addItem(label, value)
        self.p31_order_type_combo.currentIndexChanged.connect(self._p31_update_ticket_fields)
        self.p31_quantity_spin = QDoubleSpinBox()
        self.p31_quantity_spin.setRange(0.000001, 10_000_000.0)
        self.p31_quantity_spin.setDecimals(6)
        self.p31_quantity_spin.setSingleStep(0.1)
        self.p31_quantity_spin.setValue(1)
        self.p31_tif_combo = QComboBox()
        self.p31_tif_combo.addItem("DAY", "day")
        self.p31_tif_combo.addItem("GTC", "gtc")
        self.p31_limit_spin = self._p31_price_spin()
        self.p31_stop_spin = self._p31_price_spin()
        self.p31_reasoning_input = QPlainTextEdit()
        self.p31_reasoning_input.setPlaceholderText("Entry or exit reasoning (optional)")
        self.p31_reasoning_input.setMaximumHeight(90)
        self.p31_tags_input = QLineEdit()
        self.p31_tags_input.setPlaceholderText("swing, earnings, risk-off")
        self.p31_quote_label = QLabel("Quote loads when the order is submitted.")
        self.p31_quote_label.setWordWrap(True)
        self.set_theme_role(self.p31_quote_label, "muted")
        self.p31_submit_btn = QPushButton("Submit Paper Order")
        self.p31_submit_btn.setMinimumHeight(34)
        self.set_theme_variant(self.p31_submit_btn, "accent")
        self.p31_submit_btn.clicked.connect(self._p31_submit_order)
        form.addRow("Symbol", symbol_widget)
        form.addRow("Side", self.p31_side_combo)
        form.addRow("Order type", self.p31_order_type_combo)
        form.addRow("Quantity", self.p31_quantity_spin)
        form.addRow("Time in force", self.p31_tif_combo)
        form.addRow("Limit price", self.p31_limit_spin)
        form.addRow("Stop price", self.p31_stop_spin)
        form.addRow("Reasoning", self.p31_reasoning_input)
        form.addRow("Tags", self.p31_tags_input)
        form.addRow(self.p31_quote_label)
        form.addRow(self._p31_build_symbol_chart())
        form.addRow(self.p31_submit_btn)
        warning = QLabel("Simulation only. Yahoo quotes may be delayed. Last price is never used for fills.")
        warning.setWordWrap(True)
        self.set_theme_role(warning, "status_warning")
        form.addRow(warning)
        self._p31_update_ticket_fields()
        return box

    def _p31_build_symbol_chart(self) -> QFrame:
        frame = QFrame()
        self.set_theme_role(frame, "panel")
        frame.setMinimumHeight(185)
        chart_layout = QVBoxLayout(frame)
        chart_layout.setContentsMargins(8, 8, 8, 7)
        chart_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(5)
        self.p31_chart_symbol_label = QLabel("Symbol chart")
        self.set_theme_role(self.p31_chart_symbol_label, "card_title")
        self.p31_chart_price_label = QLabel("—")
        self.set_theme_role(self.p31_chart_price_label, "section_title")
        self.p31_chart_change_label = QLabel("")
        header.addWidget(self.p31_chart_symbol_label)
        header.addStretch(1)
        header.addWidget(self.p31_chart_price_label)
        header.addWidget(self.p31_chart_change_label)
        chart_layout.addLayout(header)

        self.p31_chart_axis = DateAxisItem(orientation="bottom")
        self.p31_symbol_chart_plot = pg.PlotWidget(axisItems={"bottom": self.p31_chart_axis})
        self.style_plot_widget(self.p31_symbol_chart_plot)
        self.p31_symbol_chart_plot.setMinimumHeight(112)
        self.p31_symbol_chart_plot.setMaximumHeight(220)
        self.p31_symbol_chart_plot.showGrid(x=True, y=True, alpha=0.12)
        self.p31_symbol_chart_plot.setMouseEnabled(x=False, y=False)
        plot_item = self.p31_symbol_chart_plot.getPlotItem()
        plot_item.setMenuEnabled(False)
        plot_item.hideAxis("left")
        plot_item.showAxis("right")
        plot_item.hideButtons()
        chart_layout.addWidget(self.p31_symbol_chart_plot, 1)

        range_row = QHBoxLayout()
        range_row.setSpacing(2)
        self.p31_chart_range_group = QButtonGroup(self)
        self.p31_chart_range_group.setExclusive(True)
        self.p31_chart_range_buttons: dict[str, QPushButton] = {}
        for key in P31_SYMBOL_CHART_RANGES:
            button = QPushButton(key)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, selected=key: self._p31_select_chart_range(selected))
            self.p31_chart_range_group.addButton(button)
            self.p31_chart_range_buttons[key] = button
            range_row.addWidget(button, 1)
        self.p31_chart_range_buttons[self._p31_chart_range_key].setChecked(True)
        chart_layout.addLayout(range_row)

        self.p31_chart_status_label = QLabel("Enter a symbol, then press Enter or Load. Historical Yahoo data only.")
        self.p31_chart_status_label.setWordWrap(True)
        self.set_theme_role(self.p31_chart_status_label, "muted")
        chart_layout.addWidget(self.p31_chart_status_label)
        return frame

    @staticmethod
    def _p31_price_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.01, 10_000_000.0)
        spin.setDecimals(4)
        spin.setPrefix("$")
        spin.setValue(100.0)
        return spin

    def _p31_normalize_symbol(self, text: str) -> None:
        upper = text.upper()
        if upper != text:
            cursor = self.p31_symbol_input.cursorPosition()
            self.p31_symbol_input.blockSignals(True)
            self.p31_symbol_input.setText(upper)
            self.p31_symbol_input.setCursorPosition(cursor)
            self.p31_symbol_input.blockSignals(False)
        self._p31_on_chart_symbol_edited(upper)

    def _p31_on_chart_symbol_edited(self, symbol: str) -> None:
        clean_symbol = str(symbol or "").upper().strip()
        loaded_symbol = str(getattr(self, "_p31_chart_loaded_symbol", "") or "")
        if clean_symbol == loaded_symbol:
            return
        self._p31_chart_request_id += 1
        self._p31_chart_inflight = False
        self.p31_chart_load_btn.setEnabled(True)
        self._p31_clear_symbol_chart("Enter a symbol, then press Enter or Load. Historical Yahoo data only.")

    def _p31_get_chart_data_service(self) -> ChartDataService:
        shared_getter = getattr(self, "_get_chart_data_service", None)
        if callable(shared_getter):
            return shared_getter()
        service = getattr(self, "_p31_chart_data_service", None)
        if service is None:
            service = ChartDataService()
            self._p31_chart_data_service = service
            self._p31_owns_chart_data_service = True
        return service

    def _p31_select_chart_range(self, range_key: str) -> None:
        selected = str(range_key or "").upper()
        if selected not in P31_SYMBOL_CHART_RANGES:
            return
        self._p31_chart_range_key = selected
        button = self.p31_chart_range_buttons.get(selected)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        symbol = self.p31_symbol_input.text().upper().strip()
        if not symbol or symbol != self._p31_chart_loaded_symbol:
            return
        if selected == self._p31_chart_loaded_range and not self._p31_chart_inflight:
            return
        self._p31_request_symbol_chart()

    def _p31_request_symbol_chart(self, *_: Any, force_refresh: bool = False) -> None:
        symbol = self.p31_symbol_input.text().upper().strip()
        if not symbol:
            self._p31_clear_symbol_chart("Enter a symbol before loading its chart.", "negative")
            return
        range_key = self._p31_chart_range_key
        period, interval = P31_SYMBOL_CHART_RANGES[range_key]
        self._p31_chart_request_id += 1
        request_id = self._p31_chart_request_id
        prior_symbol = self._p31_chart_loaded_symbol
        self._p31_chart_inflight = True
        self.p31_chart_load_btn.setEnabled(False)
        if prior_symbol and prior_symbol != symbol:
            self._p31_clear_symbol_chart(f"Loading {symbol} {range_key} historical candles...")
        else:
            self._p31_set_chart_status(f"Loading {symbol} {range_key} historical candles...", "info")

        def _work() -> dict[str, Any]:
            return self._p31_get_chart_data_service().fetch_base_frame_payload(
                symbol,
                period=period,
                interval=interval,
                force_refresh=force_refresh,
            )

        self._p31_submit_chart_background(
            request_id=request_id,
            symbol=symbol,
            range_key=range_key,
            work=_work,
        )

    def _p31_submit_chart_background(
        self,
        *,
        request_id: int,
        symbol: str,
        range_key: str,
        work: Callable[[], dict[str, Any]],
    ) -> None:
        executor = getattr(self, "_p31_executor", None)
        if executor is None:
            self._p31_on_chart_error(request_id, "Chart loader is unavailable.")
            return

        def _run() -> None:
            try:
                payload = work()
            except Exception as exc:
                self._invoke_main.emit(
                    lambda rid=request_id, message=str(exc): self._p31_on_chart_error(rid, message)
                )
                return
            self._invoke_main.emit(
                lambda rid=request_id, ticker=symbol, key=range_key, value=payload: self._p31_on_chart_complete(
                    rid,
                    ticker,
                    key,
                    value,
                )
            )

        executor.submit(_run)

    def _p31_on_chart_complete(
        self,
        request_id: int,
        symbol: str,
        range_key: str,
        payload: dict[str, Any],
    ) -> None:
        if int(request_id) != int(self._p31_chart_request_id):
            return
        self._p31_chart_inflight = False
        self.p31_chart_load_btn.setEnabled(True)
        frame = payload.get("df") if isinstance(payload, dict) else None
        metadata = market_data_meta(payload)
        if frame is None or getattr(frame, "empty", True):
            reason = str(metadata.get("failure_reason") or f"No chart data returned for {symbol}.")
            self._p31_clear_symbol_chart(reason, "negative")
            return
        required_columns = {"Open", "High", "Low", "Close"}
        if not required_columns.issubset(set(frame.columns)):
            self._p31_clear_symbol_chart(f"Chart data for {symbol} is missing OHLC prices.", "negative")
            return
        self._p31_chart_loaded_symbol = str(symbol)
        self._p31_chart_loaded_range = str(range_key)
        self._p31_chart_frame = frame.copy()
        self._p31_render_symbol_chart()
        source = str(metadata.get("source") or "Yahoo")
        if bool(metadata.get("is_stale")):
            age = metadata.get("cache_age_seconds")
            age_text = f" · cache age {float(age) / 60.0:.0f} min" if age not in (None, "") else ""
            self._p31_set_chart_status(f"Showing stale {source} historical data{age_text}.", "warning")
        elif source == "cache":
            self._p31_set_chart_status("Loaded historical prices from the local chart cache.", "muted")
        else:
            self._p31_set_chart_status(f"Loaded historical prices from {source}.", "muted")

    def _p31_on_chart_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._p31_chart_request_id):
            return
        self._p31_chart_inflight = False
        self.p31_chart_load_btn.setEnabled(True)
        self._p31_clear_symbol_chart(f"Chart load failed: {message}", "negative")

    def _p31_clear_symbol_chart(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p31_symbol_chart_plot"):
            self.p31_symbol_chart_plot.clear()
            self.p31_chart_axis.set_dates([], "1d")
        self._p31_chart_loaded_symbol = ""
        self._p31_chart_loaded_range = ""
        self._p31_chart_frame = None
        if hasattr(self, "p31_chart_symbol_label"):
            self.p31_chart_symbol_label.setText("Symbol chart")
            self.p31_chart_price_label.setText("—")
            self._p31_set_chart_change("", "muted")
            self._p31_set_chart_status(message, status)

    def _p31_set_chart_status(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p31_chart_status_label"):
            self.set_status_text(self.p31_chart_status_label, str(message), status=status)

    def _p31_set_chart_change(self, text: str, status: str) -> None:
        if hasattr(self, "p31_chart_change_label"):
            self.set_status_text(self.p31_chart_change_label, text, status=status)

    def _p31_render_symbol_chart(self) -> None:
        frame = getattr(self, "_p31_chart_frame", None)
        if frame is None or getattr(frame, "empty", True):
            return
        clean_frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
        if clean_frame.empty:
            return
        candles = [
            (index, float(row.Open), float(row.Close), float(row.Low), float(row.High))
            for index, row in enumerate(clean_frame.itertuples())
        ]
        closes = [float(value) for value in clean_frame["Close"]]
        lows = [float(value) for value in clean_frame["Low"]]
        highs = [float(value) for value in clean_frame["High"]]
        first_close = closes[0]
        latest_close = closes[-1]
        change = latest_close - first_close
        change_pct = (change / first_close * 100.0) if first_close else 0.0
        status = "positive" if change > 0 else "negative" if change < 0 else "muted"

        plot = self.p31_symbol_chart_plot
        plot.clear()
        candle_item = CandlestickItem(
            candles,
            up_color=self.theme_color("chart_up_candle"),
            down_color=self.theme_color("chart_down_candle"),
        )
        plot.addItem(candle_item)
        latest_line = pg.InfiniteLine(
            pos=latest_close,
            angle=0,
            pen=pg.mkPen(self.theme_color("chart_reference"), width=1, style=Qt.PenStyle.DashLine),
        )
        plot.addItem(latest_line)
        self.p31_chart_candle_item = candle_item
        self.p31_chart_last_price_line = latest_line
        _period, interval = P31_SYMBOL_CHART_RANGES.get(self._p31_chart_loaded_range, ("1mo", "1h"))
        self.p31_chart_axis.set_dates(clean_frame.index.to_list(), interval)
        plot.setXRange(-1.0, max(float(len(candles)), 1.0), padding=0.01)
        low = min(lows)
        high = max(highs)
        padding = max((high - low) * 0.07, abs(latest_close) * 0.002, 0.01)
        plot.setYRange(low - padding, high + padding, padding=0.0)

        self.p31_chart_symbol_label.setText(f"{self._p31_chart_loaded_symbol} · {self._p31_chart_loaded_range}")
        self.p31_chart_price_label.setText(f"${latest_close:,.2f}")
        sign = "+" if change > 0 else ""
        self._p31_set_chart_change(f"{sign}{change_pct:.2f}%", status)

    def _p31_build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self.p31_tabs = tabs
        self.p31_positions_table = self._p31_table(
            ["Symbol", "Qty", "Avg Cost", "Mark", "Market Value", "Unrealized", "Realized", "Mark Status"]
        )
        tabs.addTab(self.p31_positions_table, "Positions")

        orders_page = QWidget()
        orders_layout = QVBoxLayout(orders_page)
        orders_layout.setContentsMargins(0, 0, 0, 0)
        orders_toolbar = QHBoxLayout()
        self.p31_order_filter = QComboBox()
        for label, value in (
            ("All orders", "all"),
            ("Pending", "pending"),
            ("Filled", "filled"),
            ("Cancelled", "cancelled"),
            ("Rejected", "rejected"),
            ("Expired", "expired"),
        ):
            self.p31_order_filter.addItem(label, value)
        self.p31_order_filter.currentIndexChanged.connect(self._p31_refresh_orders)
        self.p31_cancel_order_btn = QPushButton("Cancel Selected")
        self.set_theme_variant(self.p31_cancel_order_btn, "danger")
        self.p31_cancel_order_btn.clicked.connect(self._p31_cancel_selected_order)
        orders_toolbar.addWidget(QLabel("Status"))
        orders_toolbar.addWidget(self.p31_order_filter)
        orders_toolbar.addStretch(1)
        orders_toolbar.addWidget(self.p31_cancel_order_btn)
        self.p31_orders_table = self._p31_table(
            ["Submitted", "Symbol", "Side", "Type", "Qty", "Limit", "Stop", "TIF", "Status", "Last Evaluation", "ID"]
        )
        self.p31_orders_table.setColumnHidden(10, True)
        self.p31_orders_table.itemSelectionChanged.connect(self._p31_update_cancel_button)
        orders_layout.addLayout(orders_toolbar)
        orders_layout.addWidget(self.p31_orders_table, 1)
        tabs.addTab(orders_page, "Orders")

        self.p31_fills_table = self._p31_table(
            ["Filled", "Symbol", "Side", "Qty", "Bid", "Ask", "Fill Price", "Commission", "Realized P&L", "Source"]
        )
        tabs.addTab(self.p31_fills_table, "Fills")
        tabs.addTab(self._p31_build_journal_tab(), "Journal")
        tabs.addTab(self._p31_build_performance_tab(), "Performance")
        tabs.currentChanged.connect(lambda _index: self._p31_refresh_all())
        return tabs

    def _p31_build_journal_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.p31_journal_table = self._p31_table(["Updated", "Tags", "Note", "Order", "ID"])
        self.p31_journal_table.setColumnHidden(4, True)
        self.p31_journal_table.itemSelectionChanged.connect(self._p31_load_selected_journal)
        editor_row = QHBoxLayout()
        self.p31_journal_note = QPlainTextEdit()
        self.p31_journal_note.setPlaceholderText("Add a review note...")
        self.p31_journal_note.setMaximumHeight(90)
        self.p31_journal_tags = QLineEdit()
        self.p31_journal_tags.setPlaceholderText("tags, comma-separated")
        save = QPushButton("Save Journal Entry")
        self.set_theme_variant(save, "accent")
        save.clicked.connect(self._p31_save_journal)
        fresh = QPushButton("New")
        fresh.clicked.connect(self._p31_clear_journal_editor)
        editor_row.addWidget(self.p31_journal_tags, 1)
        editor_row.addWidget(fresh)
        editor_row.addWidget(save)
        layout.addWidget(self.p31_journal_table, 1)
        layout.addWidget(self.p31_journal_note)
        layout.addLayout(editor_row)
        return page

    def _p31_build_performance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.p31_performance_hint = QLabel("Equity snapshots are recorded after fills and at most every five minutes while the app is open.")
        self.set_theme_role(self.p31_performance_hint, "muted")
        self.p31_performance_plot = pg.PlotWidget()
        self.p31_performance_plot.showGrid(x=True, y=True, alpha=0.2)
        self.p31_performance_plot.setLabel("left", "Equity", units="$ ")
        self.p31_performance_plot.setLabel("bottom", "Snapshot")
        layout.addWidget(self.p31_performance_hint)
        layout.addWidget(self.p31_performance_plot, 1)
        return page

    @staticmethod
    def _p31_table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(25)
        table.horizontalHeader().setMinimumHeight(28)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _p31_on_show(self) -> None:
        for timer_name in ("_p32_engine_timer", "_p32_mark_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        if not getattr(self, "_p31_engine_started", False):
            self._p31_engine_started = True
            self._p31_engine_timer.start()
            self._p31_mark_timer.start()
            self._p31_run_engine_cycle(mark=True, force=True)
        self._p31_refresh_accounts(self._p31_active_account_id)

    def _p31_stop(self) -> None:
        for timer_name in ("_p31_engine_timer", "_p31_mark_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self._p31_chart_request_id = int(getattr(self, "_p31_chart_request_id", 0)) + 1
        self._p31_accounts_request_seq = int(getattr(self, "_p31_accounts_request_seq", 0)) + 1
        self._p31_accounts_refresh_running = False
        self._p31_accounts_refresh_pending = None
        executor = getattr(self, "_p31_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
            self._p31_executor = None
        chart_service = getattr(self, "_p31_chart_data_service", None)
        if chart_service is not None and getattr(self, "_p31_owns_chart_data_service", False):
            chart_service.close()
            self._p31_chart_data_service = None
            self._p31_owns_chart_data_service = False

    def _p31_refresh_accounts(self, select_account_id: str | None = None) -> None:
        desired = str(select_account_id or self._p31_active_account_id or "")
        if getattr(self, "_p31_accounts_refresh_running", False):
            active_desired = str(getattr(self, "_p31_accounts_refresh_context", "") or "")
            if desired == active_desired:
                self._p31_accounts_refresh_pending = None
            elif desired != getattr(self, "_p31_accounts_refresh_pending", None):
                self._p31_accounts_refresh_pending = desired
            return
        self._p31_start_accounts_refresh(desired)

    def _p31_start_accounts_refresh(self, desired: str) -> None:
        """Load the Paper account selector without blocking Qt's event loop."""
        executor = getattr(self, "_p31_executor", None)
        dispatcher = getattr(self, "_invoke_main", None)
        has_window_runtime = executor is not None and callable(getattr(dispatcher, "emit", None))
        self._p31_accounts_request_seq = int(getattr(self, "_p31_accounts_request_seq", 0)) + 1
        request_id = self._p31_accounts_request_seq
        self._p31_accounts_refresh_running = True
        self._p31_accounts_refresh_context = str(desired or "")

        def _work() -> list[dict[str, Any]]:
            return [dict(account) for account in self._p31_store.list_accounts(include_archived=True)]

        if not has_window_runtime:
            try:
                accounts = _work()
                error = ""
            except Exception as exc:
                accounts = []
                error = str(exc)
            self._p31_complete_accounts_refresh(request_id, desired, accounts, error)
            return

        future = executor.submit(_work)

        def _complete(done: Any) -> None:
            try:
                accounts = done.result()
                error = ""
            except Exception as exc:
                accounts = []
                error = str(exc)
            try:
                self._invoke_main.emit(
                    lambda rid=request_id, selected=desired, rows=accounts, message=error: self._p31_complete_accounts_refresh(
                        rid, selected, rows, message
                    )
                )
            except RuntimeError:
                return

        future.add_done_callback(_complete)

    def _p31_complete_accounts_refresh(
        self,
        request_id: int,
        desired: str,
        accounts: Any,
        error: str,
    ) -> None:
        if request_id != int(getattr(self, "_p31_accounts_request_seq", 0)):
            return
        self._p31_accounts_refresh_running = False
        self._p31_accounts_refresh_context = ""
        pending = getattr(self, "_p31_accounts_refresh_pending", None)
        self._p31_accounts_refresh_pending = None
        if pending is not None and pending != desired:
            self._p31_start_accounts_refresh(pending)
            return
        if error:
            self._p31_set_status(f"Paper accounts could not be refreshed: {error}", "negative")
            return
        self._p31_apply_accounts(accounts, desired)

    def _p31_apply_accounts(self, accounts: Any, desired: str) -> None:
        accounts = [dict(account) for account in list(accounts or []) if isinstance(account, dict)]
        self._p31_accounts = accounts
        self.p31_account_combo.blockSignals(True)
        self.p31_account_combo.clear()
        selected_index = -1
        for account in accounts:
            archived = account["status"] == "archived"
            label = f"{account['name']} (Archived)" if archived else str(account["name"])
            self.p31_account_combo.addItem(label, account["id"])
            if account["id"] == desired:
                selected_index = self.p31_account_combo.count() - 1
        if selected_index < 0 and self.p31_account_combo.count():
            active_index = next((i for i, account in enumerate(accounts) if account["status"] == "active"), 0)
            selected_index = active_index
        self.p31_account_combo.setCurrentIndex(selected_index)
        self.p31_account_combo.blockSignals(False)
        self._p31_active_account_id = str(self.p31_account_combo.currentData() or "")
        self._p31_active_account_snapshot = next(
            (dict(account) for account in accounts if str(account.get("id") or "") == self._p31_active_account_id),
            None,
        )
        has_accounts = bool(accounts)
        self.p31_empty_state.setVisible(not has_accounts)
        self.p31_workspace.setVisible(has_accounts)
        self._p31_update_account_controls()
        if has_accounts:
            self._p31_refresh_all()

    def _p31_on_account_changed(self, _index: int) -> None:
        self._p31_active_account_id = str(self.p31_account_combo.currentData() or "")
        self._p31_active_account_snapshot = next(
            (
                dict(account)
                for account in getattr(self, "_p31_accounts", [])
                if str(account.get("id") or "") == self._p31_active_account_id
            ),
            None,
        )
        self._p31_clear_journal_editor()
        self._p31_update_account_controls()
        self._p31_refresh_all()

    def _p31_update_account_controls(self) -> None:
        account = getattr(self, "_p31_active_account_snapshot", None)
        archived = bool(account and account["status"] == "archived")
        self.p31_edit_account_btn.setEnabled(account is not None)
        self.p31_archive_account_btn.setEnabled(account is not None)
        self.p31_archive_account_btn.setText("Restore" if archived else "Archive")
        self.p31_submit_btn.setEnabled(bool(account and not archived and not self._p31_task_inflight))

    def _p31_account_dialog(self, title: str, account: dict[str, Any] | None = None) -> dict[str, Any] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(390)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name = QLineEdit(str((account or {}).get("name", "")))
        cash = QDoubleSpinBox()
        cash.setRange(1.0, 1_000_000_000.0)
        cash.setDecimals(2)
        cash.setPrefix("$")
        cash.setValue(float((account or {}).get("initial_cash", 100_000.0)))
        cash.setEnabled(account is None or self._p31_store.can_edit_initial_cash(str(account.get("id") or "")))
        slippage = QDoubleSpinBox()
        slippage.setRange(0.0, 1000.0)
        slippage.setDecimals(2)
        slippage.setSuffix(" bps")
        slippage.setValue(float((account or {}).get("slippage_bps", 5.0)))
        commission = QDoubleSpinBox()
        commission.setRange(0.0, 10_000.0)
        commission.setDecimals(2)
        commission.setPrefix("$")
        commission.setValue(float((account or {}).get("commission_per_fill", 0.0)))
        form.addRow("Account name", name)
        form.addRow("Starting cash", cash)
        form.addRow("Slippage", slippage)
        form.addRow("Commission / fill", commission)
        layout.addLayout(form)
        hint = QLabel("Settings apply to future orders; each order snapshots its fee model.")
        hint.setWordWrap(True)
        self.set_theme_role(hint, "muted")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        self.set_theme_variant(save, "accent")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "name": name.text().strip(),
            "initial_cash": cash.value(),
            "slippage_bps": slippage.value(),
            "commission_per_fill": commission.value(),
        }

    def _p31_create_account_dialog(self) -> None:
        payload = self._p31_account_dialog("Create Paper Account")
        if payload is None:
            return
        try:
            account = self._p31_store.create_account(**payload)
        except Exception as exc:
            QMessageBox.warning(self, "Account Not Created", str(exc))
            return
        self._p31_set_status(f"Created paper account {account['name']}.", "positive")
        self._p31_refresh_accounts(account["id"])

    def _p31_edit_account_dialog(self) -> None:
        if not self._p31_active_account_id:
            return
        account = self._p31_store.get_account(self._p31_active_account_id)
        payload = self._p31_account_dialog("Edit Paper Account", account)
        if payload is None:
            return
        try:
            updated = self._p31_store.update_account(
                account["id"],
                name=payload["name"],
                initial_cash=payload["initial_cash"],
                slippage_bps=payload["slippage_bps"],
                commission_per_fill=payload["commission_per_fill"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "Account Not Updated", str(exc))
            return
        self._p31_set_status(f"Updated {updated['name']}.", "positive")
        self._p31_refresh_accounts(updated["id"])

    def _p31_toggle_archive_account(self) -> None:
        if not self._p31_active_account_id:
            return
        account = self._p31_store.get_account(self._p31_active_account_id)
        try:
            if account["status"] == "archived":
                self._p31_store.restore_account(account["id"])
                message = f"Restored {account['name']}."
            else:
                reply = QMessageBox.question(
                    self,
                    "Archive Paper Account",
                    "Archiving preserves history and cancels every pending order. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                self._p31_store.archive_account(account["id"])
                message = f"Archived {account['name']}."
        except Exception as exc:
            QMessageBox.warning(self, "Account Update Failed", str(exc))
            return
        self._p31_set_status(message, "positive")
        self._p31_refresh_accounts(account["id"])

    def _p31_update_ticket_fields(self) -> None:
        order_type = str(self.p31_order_type_combo.currentData() or "market")
        self.p31_limit_spin.setEnabled(order_type == "limit")
        self.p31_stop_spin.setEnabled(order_type == "stop")
        if order_type == "market":
            self.p31_tif_combo.setCurrentIndex(0)
            self.p31_tif_combo.setEnabled(False)
        else:
            self.p31_tif_combo.setEnabled(True)

    def _p31_submit_order(self) -> None:
        if self._p31_task_inflight:
            return
        tags = tuple(tag.strip() for tag in self.p31_tags_input.text().split(",") if tag.strip())
        order_type = str(self.p31_order_type_combo.currentData() or "market")
        request = PaperOrderRequest(
            account_id=self._p31_active_account_id,
            symbol=self.p31_symbol_input.text(),
            side=str(self.p31_side_combo.currentData() or "buy"),
            quantity=self.p31_quantity_spin.value(),
            order_type=order_type,
            tif=str(self.p31_tif_combo.currentData() or "day"),
            limit_price=self.p31_limit_spin.value() if order_type == "limit" else None,
            stop_price=self.p31_stop_spin.value() if order_type == "stop" else None,
            reasoning=self.p31_reasoning_input.toPlainText(),
            tags=tags,
        )
        try:
            request = request.normalized()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Paper Order", str(exc))
            return
        self._p31_set_busy(True, f"Loading Yahoo bid/ask for {request.symbol}...")

        def _work() -> tuple[dict[str, Any], dict[str, Any], Any]:
            quote = self._p31_quote_service.fetch(request.symbol)
            order = self._p31_engine.submit_order(request, quote=quote)
            result = self._p31_engine.process_pending_orders(quotes={request.symbol: quote})
            return order, result, quote

        self._p31_submit_background(_work, self._p31_on_submit_complete, "Order submission failed")

    def _p31_on_submit_complete(self, payload: tuple[dict[str, Any], dict[str, Any], Any]) -> None:
        order, result, quote = payload
        self.p31_quote_label.setText(
            f"Yahoo {quote.symbol}: bid ${float(quote.bid or 0):,.4f} · ask ${float(quote.ask or 0):,.4f} · {quote.market_state or 'state unavailable'}"
        )
        self.p31_reasoning_input.clear()
        self.p31_tags_input.clear()
        self._p31_set_busy(False)
        filled = int(result.get("filled", 0) or 0)
        status = "filled" if filled else str(self._p31_store.get_order(order["id"])["status"])
        self._p31_set_status(f"Paper order {order['id'][:8]} is {status}.", "positive" if filled else "info")
        self._p31_refresh_all()

    def _p31_submit_background(
        self,
        work: Callable[[], Any],
        complete: Callable[[Any], None],
        error_prefix: str,
    ) -> None:
        executor = getattr(self, "_p31_executor", None)
        if executor is None:
            self._p31_set_busy(False)
            return

        def _run() -> None:
            try:
                payload = work()
            except Exception as exc:
                self._invoke_main.emit(lambda message=f"{error_prefix}: {exc}": self._p31_on_task_error(message))
                return
            self._invoke_main.emit(lambda value=payload: complete(value))

        executor.submit(_run)

    def _p31_run_engine_cycle(self, *, mark: bool, force: bool = False) -> None:
        if self._p31_task_inflight:
            return
        if getattr(self, "_p31_executor", None) is None:
            return
        self._p31_set_busy(True, "Refreshing paper orders and account marks...")

        def _work() -> dict[str, Any]:
            return self._p31_engine.run_cycle(mark=mark)

        self._p31_submit_background(_work, self._p31_on_cycle_complete, "Paper refresh failed")

    def _p31_on_cycle_complete(self, result: dict[str, Any]) -> None:
        self._p31_set_busy(False)
        filled = int(result.get("filled", 0) or 0)
        expired = int(result.get("expired", 0) or 0)
        errors = list(result.get("errors", []) or []) + list((result.get("marks") or {}).get("errors", []) or [])
        if filled or expired:
            self._p31_set_status(f"Paper engine: {filled} filled, {expired} expired.", "positive")
        elif errors:
            self._p31_set_status(f"Paper engine completed with {len(errors)} Yahoo quote issue(s).", "warning")
        else:
            self._p31_set_status("Paper engine refreshed. Yahoo quotes may be delayed.", "info")
        self._p31_refresh_all()

    def _p31_on_task_error(self, message: str) -> None:
        self._p31_set_busy(False)
        self._p31_set_status(message, "negative")

    def _p31_set_busy(self, busy: bool, message: str = "") -> None:
        self._p31_task_inflight = bool(busy)
        self.p31_refresh_btn.setEnabled(not busy)
        self._p31_update_account_controls()
        if message:
            self._p31_set_status(message, "info")

    def _p31_set_status(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p31_status_label"):
            self.set_status_text(self.p31_status_label, str(message), status=status)

    def _p31_cancel_selected_order(self) -> None:
        row = self.p31_orders_table.currentRow()
        if row < 0:
            return
        order_id_item = self.p31_orders_table.item(row, 10)
        if order_id_item is None:
            return
        try:
            order = self._p31_store.cancel_order(order_id_item.text())
        except Exception as exc:
            QMessageBox.warning(self, "Order Not Cancelled", str(exc))
            return
        self._p31_set_status(f"Cancelled {order['symbol']} order {order['id'][:8]}.", "positive")
        self._p31_refresh_all()

    def _p31_save_journal(self) -> None:
        if not self._p31_active_account_id:
            return
        note = self.p31_journal_note.toPlainText().strip()
        tags = [tag.strip() for tag in self.p31_journal_tags.text().split(",") if tag.strip()]
        if not note and not tags:
            QMessageBox.warning(self, "Empty Journal Entry", "Enter a note or at least one tag.")
            return
        entry = self._p31_store.save_journal_entry(
            self._p31_active_account_id,
            note,
            tags,
            entry_id=self._p31_journal_entry_id or None,
        )
        self._p31_journal_entry_id = entry["id"]
        self._p31_set_status("Journal entry saved.", "positive")
        if self._p31_has_window_refresh_runtime():
            self._p31_refresh_all()
        else:
            rows = [dict(row) for row in self._p31_store.list_journal(self._p31_active_account_id)]
            self._p31_refresh_journal(rows)

    def _p31_clear_journal_editor(self) -> None:
        self._p31_journal_entry_id = ""
        if hasattr(self, "p31_journal_note"):
            self.p31_journal_note.clear()
            self.p31_journal_tags.clear()

    def _p31_load_selected_journal(self) -> None:
        row = self.p31_journal_table.currentRow()
        if row < 0:
            return
        entry_id = self.p31_journal_table.item(row, 4)
        if entry_id is None:
            return
        entries = self._p31_store.list_journal(self._p31_active_account_id)
        entry = next((item for item in entries if item["id"] == entry_id.text()), None)
        if entry is None:
            return
        self._p31_journal_entry_id = entry["id"]
        self.p31_journal_note.setPlainText(str(entry["note"] or ""))
        try:
            tags = json.loads(entry["tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        self.p31_journal_tags.setText(", ".join(map(str, tags)))

    def _p31_refresh_all(self) -> None:
        """Refresh the summary and visible Paper tab without reading SQLite on the UI thread."""
        if not getattr(self, "_p31_active_account_id", ""):
            return
        account_id = str(self._p31_active_account_id)
        tab_index = int(self.p31_tabs.currentIndex()) if hasattr(self, "p31_tabs") else 0
        order_filter = str(self.p31_order_filter.currentData() or "all") if hasattr(self, "p31_order_filter") else "all"
        context = (account_id, tab_index, order_filter)
        cached = getattr(self, "_p31_view_cache", {}).get(context)
        if isinstance(cached, dict):
            self._p31_apply_view_snapshot(context, cached)
        if getattr(self, "_p31_view_refresh_running", False):
            if context != getattr(self, "_p31_view_refresh_context", None):
                self._p31_view_refresh_pending = context
            return
        self._p31_start_view_refresh(context)

    def _p31_has_window_refresh_runtime(self) -> bool:
        """Return whether the full window can marshal refresh results to Qt's UI thread."""
        dispatcher = getattr(self, "_invoke_main", None)
        return callable(getattr(dispatcher, "emit", None)) and callable(
            getattr(self, "_is_current_page", None)
        )

    def _p31_page_is_visible(self) -> bool:
        """Treat isolated widget probes as visible while preserving real-window guards."""
        is_current_page = getattr(self, "_is_current_page", None)
        if not callable(is_current_page):
            return True
        return bool(is_current_page(getattr(self, "page31", None)))

    def _p31_start_view_refresh(self, context: tuple[str, int, str]) -> None:
        executor = getattr(self, "_p31_executor", None)
        has_window_runtime = self._p31_has_window_refresh_runtime()
        if executor is None and has_window_runtime:
            return
        self._p31_view_request_seq += 1
        request_id = self._p31_view_request_seq
        self._p31_view_refresh_running = True
        self._p31_view_refresh_context = context

        def _work() -> dict[str, Any]:
            account_id, tab_index, order_filter = context
            snapshot: dict[str, Any] = {
                "summary": dict(self._p31_store.account_summary(account_id)),
                "tab_index": tab_index,
            }
            if tab_index == 0:
                snapshot["positions"] = [dict(row) for row in self._p31_store.list_positions(account_id)]
            elif tab_index == 1:
                snapshot["orders"] = [dict(row) for row in self._p31_store.list_orders(account_id, status=order_filter)]
            elif tab_index == 2:
                snapshot["fills"] = [dict(row) for row in self._p31_store.list_fills(account_id)]
            elif tab_index == 3:
                snapshot["journal"] = [dict(row) for row in self._p31_store.list_journal(account_id)]
            elif tab_index == 4:
                snapshot["performance"] = [dict(row) for row in self._p31_store.list_equity_snapshots(account_id)]
            return snapshot

        if not has_window_runtime:
            try:
                payload = _work()
                error = ""
            except Exception as exc:
                payload = None
                error = str(exc)
            self._p31_complete_view_refresh(request_id, context, payload, error)
            return

        future = executor.submit(_work)

        def _complete(done: Any) -> None:
            try:
                payload = done.result()
                error = ""
            except Exception as exc:
                payload = None
                error = str(exc)
            try:
                self._invoke_main.emit(
                    lambda rid=request_id, ctx=context, data=payload, message=error: self._p31_complete_view_refresh(
                        rid, ctx, data, message
                    )
                )
            except RuntimeError:
                return

        future.add_done_callback(_complete)

    def _p31_complete_view_refresh(
        self,
        request_id: int,
        context: tuple[str, int, str],
        payload: Any,
        error: str,
    ) -> None:
        if request_id != getattr(self, "_p31_view_request_seq", 0):
            return
        self._p31_view_refresh_running = False
        self._p31_view_refresh_context = None
        if isinstance(payload, dict):
            self._p31_view_cache[context] = payload
            self._p31_apply_view_snapshot(context, payload)
        elif error and self._p31_page_is_visible():
            self._p31_set_status(f"Paper view refresh failed: {error}", "negative")
        pending = self._p31_view_refresh_pending
        self._p31_view_refresh_pending = None
        if pending is not None and pending != context:
            self._p31_start_view_refresh(pending)

    def _p31_current_view_context(self) -> tuple[str, int, str]:
        return (
            str(getattr(self, "_p31_active_account_id", "") or ""),
            int(self.p31_tabs.currentIndex()) if hasattr(self, "p31_tabs") else 0,
            str(self.p31_order_filter.currentData() or "all") if hasattr(self, "p31_order_filter") else "all",
        )

    def _p31_apply_view_snapshot(self, context: tuple[str, int, str], payload: dict[str, Any]) -> None:
        if context != self._p31_current_view_context():
            return
        if not self._p31_page_is_visible():
            return
        try:
            self._p31_refresh_summary(payload.get("summary", {}))
            tab_index = int(payload.get("tab_index", context[1]))
            if tab_index == 0:
                self._p31_refresh_positions(payload.get("positions", []))
            elif tab_index == 1:
                self._p31_refresh_orders(rows=payload.get("orders", []))
            elif tab_index == 2:
                self._p31_refresh_fills(payload.get("fills", []))
            elif tab_index == 3:
                self._p31_refresh_journal(payload.get("journal", []))
            elif tab_index == 4:
                self._p31_refresh_performance(payload.get("performance", []))
        except Exception as exc:
            logger.exception("Paper page refresh failed.")
            self._p31_set_status(f"Paper view refresh failed: {exc}", "negative")

    def _p31_refresh_summary(self, summary: Any = None) -> None:
        if summary is None:
            self._p31_refresh_all()
            return
        for key, label in self.p31_summary_labels.items():
            value = float(summary.get(key, 0.0) or 0.0)
            label.setText(f"${value:,.2f}")
            if key.endswith("pnl"):
                self.set_theme_role(label, "positive" if value > 0 else "negative" if value < 0 else "section_title")

    def _p31_refresh_positions(self, rows: Any = None) -> None:
        if rows is None:
            self._p31_refresh_all()
            return
        values = []
        for item in rows:
            quantity = float(item["quantity"])
            average = float(item["average_cost"] or 0.0)
            mark = float(item["mark_price"] or average)
            values.append([
                item["symbol"],
                format_share_quantity(quantity),
                f"${average:,.4f}",
                f"${mark:,.4f}",
                f"${quantity * mark:,.2f}",
                f"${quantity * (mark - average):,.2f}",
                f"${float(item['realized_pnl'] or 0.0):,.2f}",
                "Stale / fallback" if item["mark_is_stale"] else "Yahoo bid",
            ])
        self._p31_fill_table(self.p31_positions_table, values)

    def _p31_refresh_orders(self, *_: Any, rows: Any = None) -> None:
        if not getattr(self, "_p31_active_account_id", ""):
            return
        if rows is None:
            self._p31_refresh_all()
            return
        values = [[
            self._p31_format_time(item["submitted_at"]),
            item["symbol"],
            str(item["side"]).title(),
            str(item["order_type"]).title(),
            format_share_quantity(item["quantity"]),
            self._p31_optional_price(item["limit_price"]),
            self._p31_optional_price(item["stop_price"]),
            str(item["tif"]).upper(),
            str(item["status"]).title(),
            item["rejection_reason"] or item["last_evaluation"] or "—",
            item["id"],
        ] for item in rows]
        self._p31_fill_table(self.p31_orders_table, values, on_complete=self._p31_update_cancel_button)

    def _p31_update_cancel_button(self) -> None:
        selected = self.p31_orders_table.currentRow()
        status_item = self.p31_orders_table.item(selected, 8) if selected >= 0 else None
        self.p31_cancel_order_btn.setEnabled(bool(status_item and status_item.text() == "Pending"))

    def _p31_refresh_fills(self, rows: Any = None) -> None:
        if rows is None:
            self._p31_refresh_all()
            return
        values = [[
            self._p31_format_time(item["filled_at"]),
            item["symbol"],
            str(item["side"]).title(),
            format_share_quantity(item["quantity"]),
            f"${float(item['quote_bid']):,.4f}",
            f"${float(item['quote_ask']):,.4f}",
            f"${float(item['fill_price']):,.4f}",
            f"${float(item['commission']):,.2f}",
            f"${float(item['realized_pnl_delta']):,.2f}",
            item["quote_source"],
        ] for item in rows]
        self._p31_fill_table(self.p31_fills_table, values)

    def _p31_refresh_journal(self, rows: Any = None) -> None:
        if rows is None:
            self._p31_refresh_all()
            return
        values = []
        for item in rows:
            try:
                tags = ", ".join(json.loads(item["tags_json"] or "[]"))
            except json.JSONDecodeError:
                tags = ""
            values.append([
                self._p31_format_time(item["updated_at"]),
                tags,
                str(item["note"] or "").replace("\n", " "),
                str(item["order_id"] or "")[:8],
                item["id"],
            ])
        self._p31_fill_table(self.p31_journal_table, values)

    def _p31_refresh_performance(self, rows: Any = None) -> None:
        if rows is None:
            self._p31_refresh_all()
            return
        self.p31_performance_plot.clear()
        if not rows:
            self.p31_performance_hint.setText("No equity snapshots yet. Submit an order or refresh account marks.")
            return
        values = [float(row["equity"] or 0.0) for row in rows]
        self.p31_performance_plot.plot(
            list(range(len(values))),
            values,
            pen=pg.mkPen(self.theme_color("accent"), width=2),
            symbol="o" if len(values) < 50 else None,
            symbolSize=5,
        )
        stale = int(rows[-1]["stale_mark_count"] or 0)
        self.p31_performance_hint.setText(
            f"{len(rows)} snapshot(s) · latest equity ${values[-1]:,.2f} · stale marks {stale}"
        )

    def _p31_fill_table(
        self,
        table: QTableWidget,
        rows: list[list[str]],
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        table_key = id(table)
        generation = self._p31_table_render_generations.get(table_key, 0) + 1
        self._p31_table_render_generations[table_key] = generation
        selected_signature = ()
        selected_row = table.currentRow()
        if selected_row >= 0:
            selected_signature = tuple(
                table.item(selected_row, column).text() if table.item(selected_row, column) is not None else ''
                for column in range(table.columnCount())
            )
        previous_updates = True
        previous_signals = False
        prepared = False

        def _prepare() -> None:
            nonlocal previous_updates, previous_signals, prepared
            previous_updates = table.updatesEnabled()
            previous_signals = table.blockSignals(True)
            prepared = True
            table.setUpdatesEnabled(False)
            table.setRowCount(len(rows))

        def _apply(row_index: int, values: list[str]) -> None:
            for column, value in enumerate(values):
                table.setItem(row_index, column, QTableWidgetItem(str(value)))

        def _finish() -> None:
            if not prepared:
                return
            table.setUpdatesEnabled(previous_updates)
            table.blockSignals(previous_signals)
            current = generation == self._p31_table_render_generations.get(table_key)
            visible = self._p31_page_is_visible()
            if current and selected_signature:
                for row_index in range(table.rowCount()):
                    signature = tuple(
                        table.item(row_index, column).text() if table.item(row_index, column) is not None else ''
                        for column in range(table.columnCount())
                    )
                    if signature == selected_signature:
                        table.selectRow(row_index)
                        break
            if previous_updates:
                table.viewport().update()
            if current and visible and callable(on_complete):
                on_complete()

        if not self._p31_has_window_refresh_runtime():
            _prepare()
            try:
                for row_index, values in enumerate(rows):
                    _apply(row_index, values)
            finally:
                _finish()
            return

        run_batched(
            self,
            ('paper-table', table_key),
            list(rows),
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            is_current=lambda value: value == self._p31_table_render_generations.get(table_key),
            is_visible=self._p31_page_is_visible,
        )

    @staticmethod
    def _p31_optional_price(value: Any) -> str:
        return f"${float(value):,.4f}" if value not in (None, "") else "—"

    @staticmethod
    def _p31_format_time(value: Any) -> str:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
            return parsed.strftime("%b %d %H:%M:%S")
        except (TypeError, ValueError):
            return str(value or "")

    def _apply_paper_trading_theme(self) -> None:
        if hasattr(self, "p31_performance_plot"):
            self.style_plot_widget(self.p31_performance_plot)
            self._p31_refresh_performance()
        if hasattr(self, "p31_symbol_chart_plot"):
            self.style_plot_widget(self.p31_symbol_chart_plot)
            self._p31_render_symbol_chart()
