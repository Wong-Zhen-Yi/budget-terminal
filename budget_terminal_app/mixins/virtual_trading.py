from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from budget_terminal_app.compat import *
from budget_terminal_app.data_service.results import market_data_meta
from budget_terminal_app.paper_trading import (
    PaperOrderRequest,
    PaperTradingEngine,
    PaperTradingStore,
    RecurringScheduleSpec,
    RecurringStatus,
    YahooPaperQuoteService,
    format_share_quantity,
    next_recurring_run,
    recurring_timezone,
)
from budget_terminal_app.paper_trading.models import iso_utc
from budget_terminal_app.services.chart_data import ChartDataService
from budget_terminal_app.widgets.batched_render import run_batched


P32_SYMBOL_CHART_RANGES = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "30m"),
    "1M": ("1mo", "1h"),
    "3M": ("3mo", "1d"),
    "1Y": ("1y", "1wk"),
    "ALL": ("max", "1mo"),
}


class VirtualTradingMixin:
    """Robinhood-inspired presentation for the shared paper-trading ledger."""

    _P32_ENGINE_INTERVAL_MS = 30_000
    _P32_MARK_INTERVAL_MS = 60_000
    _P32_ACCENT = "#00c805"

    def init_page32(self) -> None:
        self.page32.setObjectName("virtualTradingPage")
        page_layout = QVBoxLayout(self.page32)
        page_layout.setContentsMargins(18, 14, 18, 12)
        page_layout.setSpacing(10)
        self._p32_store = PaperTradingStore()
        self._p32_quote_service = YahooPaperQuoteService()
        self._p32_engine = PaperTradingEngine(
            self._p32_store,
            self._p32_quote_service,
            allow_premarket_marks=True,
            instant_fill=True,
        )
        self._p32_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="BudgetTerminalVirtual")
        self._p32_task_inflight = False
        self._p32_engine_started = False
        self._p32_active_account_id = ""
        self._p32_chart_request_id = 0
        self._p32_chart_inflight = False
        self._p32_chart_loaded_symbol = ""
        self._p32_chart_loaded_range = ""
        self._p32_chart_range_key = "1M"
        self._p32_chart_frame = None
        self._p32_chart_includes_extended_hours = False
        self._p32_market_phase = ""
        self._p32_chart_data_service = None
        self._p32_owns_chart_data_service = False
        self._p32_view_request_seq = 0
        self._p32_view_refresh_running = False
        self._p32_view_refresh_context = None
        self._p32_view_refresh_pending = None
        self._p32_view_cache = {}
        self._p32_pending_recurring_selection = None
        self._p32_active_account_snapshot = None
        self._p32_table_render_generations: dict[int, int] = {}
        self._p32_accounts_request_seq = 0
        self._p32_accounts_refresh_running = False
        self._p32_accounts_refresh_context = ""
        self._p32_accounts_refresh_pending: str | None = None
        self._p32_accounts: list[dict[str, Any]] = []

        page_layout.addWidget(self._p32_build_header())
        page_layout.addWidget(self._p32_build_empty_state(), 1)
        self.p32_workspace = self._p32_build_workspace()
        page_layout.addWidget(self.p32_workspace, 1)
        self.p32_status_label = QLabel("Simulation only · Virtual orders fill immediately without using bid/ask spreads.")
        self.set_theme_role(self.p32_status_label, "status_muted")
        page_layout.addWidget(self.p32_status_label)

        self._p32_engine_timer = QTimer(self)
        self._p32_engine_timer.setInterval(self._P32_ENGINE_INTERVAL_MS)
        self._p32_engine_timer.timeout.connect(lambda: self._p32_run_engine_cycle(mark=False))
        self._p32_mark_timer = QTimer(self)
        self._p32_mark_timer.setInterval(self._P32_MARK_INTERVAL_MS)
        self._p32_mark_timer.timeout.connect(lambda: self._p32_run_engine_cycle(mark=True))
        self._p32_refresh_accounts()
        self._apply_virtual_trading_theme()

    def _p32_build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("virtualHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        title_row = QHBoxLayout()
        title = QLabel("Virtual")
        title.setObjectName("virtualPageTitle")
        badge = QLabel("SIMULATION")
        badge.setObjectName("virtualBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(title)
        title_row.addWidget(badge)
        title_row.addStretch(1)
        subtitle = QLabel("A focused stock and ETF brokerage view powered by the Paper ledger")
        self.set_theme_role(subtitle, "muted")
        self.p32_inspiration_note = QLabel(
            "Interface inspired by Robinhood, adapted freely for Budget Terminal rather than treated as a strict replica."
        )
        self.p32_inspiration_note.setWordWrap(True)
        self.set_theme_role(self.p32_inspiration_note, "muted")
        text.addLayout(title_row)
        text.addWidget(subtitle)
        text.addWidget(self.p32_inspiration_note)
        layout.addLayout(text, 1)

        self.p32_account_combo = QComboBox()
        self.p32_account_combo.setMinimumWidth(190)
        self.p32_account_combo.currentIndexChanged.connect(self._p32_on_account_changed)
        self.p32_new_account_btn = QPushButton("New")
        self.p32_new_account_btn.setProperty("virtualRole", "secondary")
        self.p32_new_account_btn.clicked.connect(self._p32_create_account_dialog)
        self.p32_edit_account_btn = QPushButton("Edit account")
        self.p32_edit_account_btn.setProperty("virtualRole", "secondary")
        self.p32_edit_account_btn.clicked.connect(self._p32_edit_account_dialog)
        self.p32_archive_account_btn = QPushButton("Archive")
        self.p32_archive_account_btn.setProperty("virtualRole", "secondary")
        self.p32_archive_account_btn.clicked.connect(self._p32_toggle_archive_account)
        self.p32_refresh_btn = QPushButton("Refresh")
        self.p32_refresh_btn.setProperty("virtualRole", "secondary")
        self.p32_refresh_btn.clicked.connect(lambda: self._p32_run_engine_cycle(mark=True, force=True))
        layout.addWidget(self.p32_account_combo)
        layout.addWidget(self.p32_new_account_btn)
        layout.addWidget(self.p32_edit_account_btn)
        layout.addWidget(self.p32_archive_account_btn)
        layout.addWidget(self.p32_refresh_btn)
        return frame

    def _p32_build_empty_state(self) -> QFrame:
        self.p32_empty_state = QFrame()
        self.p32_empty_state.setObjectName("virtualEmptyState")
        self.set_theme_role(self.p32_empty_state, "panel")
        layout = QVBoxLayout(self.p32_empty_state)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)
        icon = QLabel("V")
        icon.setObjectName("virtualEmptyIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Start investing virtually")
        title.setObjectName("virtualEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel(
            "Create a paper account with simulated cash. Virtual and Paper share the same accounts, "
            "positions, orders, fills, and backup controls."
        )
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        self.set_theme_role(detail, "muted")
        button = QPushButton("Create virtual account")
        button.setObjectName("virtualPrimaryButton")
        button.setMinimumWidth(220)
        button.clicked.connect(self._p32_create_account_dialog)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        layout.addStretch(1)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addLayout(row)
        layout.addStretch(1)
        return self.p32_empty_state

    def _p32_build_workspace(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._p32_build_investing_panel())
        splitter.addWidget(self._p32_build_order_card())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([920, 360])
        self.p32_main_splitter = splitter
        return splitter

    def _p32_build_investing_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("virtualHero")
        self.set_theme_role(hero, "panel")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 12)
        hero_layout.setSpacing(4)
        top = QHBoxLayout()
        heading = QLabel("Investing")
        heading.setObjectName("virtualSectionHeading")
        self.p32_market_state_label = QLabel("Paper market")
        self.p32_market_state_label.setObjectName("virtualMarketBadge")
        top.addWidget(heading)
        top.addStretch(1)
        top.addWidget(self.p32_market_state_label)
        self.p32_equity_label = QLabel("$0.00")
        self.p32_equity_label.setObjectName("virtualEquity")
        self.p32_return_label = QLabel("$0.00 (0.00%) all time")
        self.p32_return_label.setObjectName("virtualReturn")
        hero_layout.addLayout(top)
        hero_layout.addWidget(self.p32_equity_label)
        hero_layout.addWidget(self.p32_return_label)

        self.p32_performance_plot = pg.PlotWidget()
        self.p32_performance_plot.setMinimumHeight(220)
        self.p32_performance_plot.setMouseEnabled(x=False, y=False)
        self.p32_performance_plot.hideAxis("left")
        self.p32_performance_plot.hideAxis("bottom")
        self.p32_performance_plot.setMenuEnabled(False)
        hero_layout.addWidget(self.p32_performance_plot, 1)

        range_row = QHBoxLayout()
        range_row.setSpacing(4)
        self.p32_range_buttons: dict[str, QPushButton] = {}
        self.p32_range_group = QButtonGroup(self)
        self.p32_range_group.setExclusive(True)
        for label, key in (("1D", "1d"), ("1W", "1w"), ("1M", "1m"), ("3M", "3m"), ("1Y", "1y"), ("ALL", "all")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("virtualRole", "range")
            button.setProperty("rangeKey", key)
            button.setMaximumWidth(54)
            button.clicked.connect(self._p32_refresh_performance)
            self.p32_range_group.addButton(button)
            self.p32_range_buttons[key] = button
            range_row.addWidget(button)
        self.p32_range_buttons["all"].setChecked(True)
        range_row.addStretch(1)
        hero_layout.addLayout(range_row)
        layout.addWidget(hero, 3)

        buying_power = QFrame()
        buying_power.setObjectName("virtualBuyingPower")
        self.set_theme_role(buying_power, "panel")
        power_layout = QHBoxLayout(buying_power)
        power_layout.setContentsMargins(16, 12, 16, 12)
        power_layout.setSpacing(22)
        self.p32_summary_labels: dict[str, QLabel] = {}
        for key, title in (("buying_power", "Buying power"), ("cash", "Cash"), ("reserved_cash", "Reserved")):
            block = QVBoxLayout()
            name = QLabel(title)
            self.set_theme_role(name, "muted")
            value = QLabel("$0.00")
            value.setObjectName("virtualMetricValue")
            block.addWidget(name)
            block.addWidget(value)
            power_layout.addLayout(block, 1)
            self.p32_summary_labels[key] = value
        layout.addWidget(buying_power)

        self.p32_tabs = QTabWidget()
        self.p32_tabs.setObjectName("virtualTabs")
        self.p32_positions_table = self._p32_table(["Symbol", "Shares", "Price", "Equity", "Total return", "Average cost"])
        self.p32_positions_table.itemDoubleClicked.connect(self._p32_trade_selected_position)
        self.p32_tabs.addTab(self.p32_positions_table, "Holdings")
        self.p32_tabs.addTab(self._p32_build_orders_tab(), "Orders")
        self.p32_fills_table = self._p32_table(["Symbol", "Side", "Shares", "Price", "Realized P&L", "Filled"])
        self.p32_tabs.addTab(self.p32_fills_table, "Activity")
        self.p32_tabs.addTab(self._p32_build_recurring_tab(), "Recurring")
        self.p32_tabs.currentChanged.connect(lambda _index: self._p32_refresh_all())
        layout.addWidget(self.p32_tabs, 3)
        return panel

    def _p32_build_orders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.p32_order_filter = QComboBox()
        for label, value in (("All", "all"), ("Pending", "pending"), ("Filled", "filled"), ("Cancelled", "cancelled"), ("Rejected", "rejected"), ("Expired", "expired")):
            self.p32_order_filter.addItem(label, value)
        self.p32_order_filter.currentIndexChanged.connect(self._p32_refresh_orders)
        self.p32_cancel_order_btn = QPushButton("Cancel order")
        self.p32_cancel_order_btn.setProperty("virtualRole", "secondary")
        self.p32_cancel_order_btn.clicked.connect(self._p32_cancel_selected_order)
        toolbar.addWidget(QLabel("Status"))
        toolbar.addWidget(self.p32_order_filter)
        toolbar.addStretch(1)
        toolbar.addWidget(self.p32_cancel_order_btn)
        self.p32_orders_table = self._p32_table(
            ["Symbol", "Side", "Order", "Hours / TIF", "Shares", "Status", "Last evaluation", "Submitted", "ID"]
        )
        self.p32_orders_table.setColumnHidden(8, True)
        self.p32_orders_table.itemSelectionChanged.connect(self._p32_update_cancel_button)
        self.p32_orders_table.itemSelectionChanged.connect(self._p32_update_order_detail)
        self.p32_order_detail_label = QLabel("Select an order to inspect its price, expiry, and latest engine decision.")
        self.p32_order_detail_label.setWordWrap(True)
        self.set_theme_role(self.p32_order_detail_label, "muted")
        layout.addLayout(toolbar)
        layout.addWidget(self.p32_orders_table, 1)
        layout.addWidget(self.p32_order_detail_label)
        return page

    def _p32_build_recurring_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.p32_add_funding_btn = QPushButton("Add funding")
        self.p32_add_buy_btn = QPushButton("Add recurring buy")
        self.p32_edit_schedule_btn = QPushButton("Edit")
        self.p32_toggle_schedule_btn = QPushButton("Pause")
        self.p32_cancel_schedule_btn = QPushButton("Cancel")
        for button in (
            self.p32_add_funding_btn,
            self.p32_add_buy_btn,
            self.p32_edit_schedule_btn,
            self.p32_toggle_schedule_btn,
            self.p32_cancel_schedule_btn,
        ):
            button.setProperty("virtualRole", "secondary")
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.p32_add_funding_btn.clicked.connect(self._p32_add_funding_schedule)
        self.p32_add_buy_btn.clicked.connect(self._p32_add_buy_schedule)
        self.p32_edit_schedule_btn.clicked.connect(self._p32_edit_selected_schedule)
        self.p32_toggle_schedule_btn.clicked.connect(self._p32_toggle_selected_schedule)
        self.p32_cancel_schedule_btn.clicked.connect(self._p32_cancel_selected_schedule)
        self.p32_recurring_table = self._p32_table(
            ["Type", "Details", "Schedule", "Next run", "Last result", "Status", "ID"]
        )
        self.p32_recurring_table.setColumnHidden(6, True)
        self.p32_recurring_table.itemSelectionChanged.connect(self._p32_update_recurring_controls)
        self.p32_recurring_detail = QLabel(
            "Funding uses calendar cadence. Recurring buys skip weekends and US market holidays."
        )
        self.p32_recurring_detail.setWordWrap(True)
        self.set_theme_role(self.p32_recurring_detail, "muted")
        layout.addLayout(toolbar)
        layout.addWidget(self.p32_recurring_table, 1)
        layout.addWidget(self.p32_recurring_detail)
        self._p32_update_recurring_controls()
        return page

    def _p32_schedule_timezone_name(self) -> str:
        getter = getattr(self, "_clock_country_by_code", None)
        code_getter = getattr(self, "_current_clock_country_code", None)
        if callable(getter) and callable(code_getter):
            choice = getter(code_getter())
            return str(choice.get("zone") or "LOCAL")
        return "LOCAL"

    def _p32_schedule_dialog(
        self,
        kind: str,
        schedule: dict[str, Any] | None = None,
    ) -> tuple[RecurringScheduleSpec, str] | None:
        editing = schedule is not None
        dialog = QDialog(self)
        if editing:
            dialog.setWindowTitle("Edit recurring schedule")
        else:
            dialog.setWindowTitle("Add recurring funding" if kind == "funding" else "Add recurring buy")
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        heading = QLabel("Recurring funding" if kind == "funding" else "Recurring buy")
        heading.setObjectName("virtualSectionHeading")
        layout.addWidget(heading)
        form = QFormLayout()
        symbol = QLineEdit(str((schedule or {}).get("symbol") or ""))
        symbol.setMaxLength(12)
        symbol.setPlaceholderText("e.g. AAPL")
        amount = QDoubleSpinBox()
        amount.setRange(0.01, 1_000_000_000.0)
        amount.setDecimals(2)
        amount.setPrefix("$")
        amount.setValue(float((schedule or {}).get("amount") or 100.0))
        cadence = QComboBox()
        cadence.addItem("Every day", "daily")
        cadence.addItem("Every week", "weekly")
        cadence.addItem("Every month", "monthly")
        cadence.setCurrentIndex(max(0, cadence.findData(str((schedule or {}).get("cadence") or "monthly"))))
        run_time = QTimeEdit()
        run_time.setDisplayFormat("HH:mm")
        parsed_time = QTime.fromString(str((schedule or {}).get("local_time") or "09:00"), "HH:mm")
        run_time.setTime(parsed_time if parsed_time.isValid() else QTime(9, 0))
        weekday = QComboBox()
        for index, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")):
            weekday.addItem(name, index)
        weekday.setCurrentIndex(int((schedule or {}).get("weekday") if (schedule or {}).get("weekday") is not None else 0))
        month_day = QSpinBox()
        month_day.setRange(1, 31)
        month_day.setValue(int((schedule or {}).get("month_day") or 1))
        timezone_name = str((schedule or {}).get("timezone") or self._p32_schedule_timezone_name())
        timezone_label = QLabel(timezone_name)
        form.addRow("Symbol", symbol)
        form.addRow("Total USD budget" if kind == "buy" else "USD amount", amount)
        form.addRow("Frequency", cadence)
        form.addRow("Local time", run_time)
        form.addRow("Weekday", weekday)
        form.addRow("Day of month", month_day)
        form.addRow("Timezone", timezone_label)
        symbol.setVisible(kind == "buy")
        symbol_label = form.labelForField(symbol)
        if symbol_label is not None:
            symbol_label.setVisible(kind == "buy")
        weekday_label = form.labelForField(weekday)
        month_day_label = form.labelForField(month_day)
        layout.addLayout(form)
        preview = QLabel()
        preview.setWordWrap(True)
        self.set_theme_role(preview, "muted")
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save changes" if editing else "Create schedule")
        save.setObjectName("virtualPrimaryButton")

        def current_spec() -> RecurringScheduleSpec:
            return RecurringScheduleSpec(
                account_id=self._p32_active_account_id,
                kind=kind,
                cadence=str(cadence.currentData()),
                amount=amount.value(),
                symbol=symbol.text(),
                timezone=timezone_name,
                local_time=run_time.time().toString("HH:mm"),
                weekday=int(weekday.currentData()),
                month_day=month_day.value(),
            ).normalized()

        def refresh_fields() -> None:
            cadence_value = str(cadence.currentData())
            weekly = cadence_value == "weekly"
            monthly = cadence_value == "monthly"
            weekday.setVisible(weekly)
            month_day.setVisible(monthly)
            if weekday_label is not None:
                weekday_label.setVisible(weekly)
            if month_day_label is not None:
                month_day_label.setVisible(monthly)
            try:
                next_run = next_recurring_run(current_spec(), dt.datetime.now(dt.timezone.utc))
                timezone = recurring_timezone(timezone_name)
                local_next = next_run.astimezone(timezone)
                preview.setText(f"Next run: {local_next.strftime('%b %d, %Y %H:%M %Z')}")
                save.setEnabled(True)
            except Exception as exc:
                preview.setText(str(exc))
                save.setEnabled(False)

        cadence.currentIndexChanged.connect(refresh_fields)
        symbol.textChanged.connect(refresh_fields)
        amount.valueChanged.connect(refresh_fields)
        run_time.timeChanged.connect(refresh_fields)
        weekday.currentIndexChanged.connect(refresh_fields)
        month_day.valueChanged.connect(refresh_fields)
        refresh_fields()
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        spec = current_spec()
        return spec, iso_utc(next_recurring_run(spec, dt.datetime.now(dt.timezone.utc)))

    def _p32_add_funding_schedule(self) -> None:
        payload = self._p32_schedule_dialog("funding")
        if payload is None:
            return
        spec, next_run = payload
        try:
            self._p32_store.create_recurring_schedule(spec, next_run_at=next_run)
        except Exception as exc:
            QMessageBox.warning(self, "Schedule Not Created", str(exc))
            return
        self._p32_set_status("Recurring funding schedule created.", "positive")
        self._p32_refresh_recurring()

    def _p32_add_buy_schedule(self) -> None:
        payload = self._p32_schedule_dialog("buy")
        if payload is None:
            return
        spec, next_run = payload
        try:
            self._p32_store.create_recurring_schedule(spec, next_run_at=next_run)
        except Exception as exc:
            QMessageBox.warning(self, "Schedule Not Created", str(exc))
            return
        self._p32_set_status(f"Recurring buy for {spec.symbol} created.", "positive")
        self._p32_refresh_recurring()

    def _p32_selected_schedule(self) -> dict[str, Any] | None:
        row = self.p32_recurring_table.currentRow()
        item = self.p32_recurring_table.item(row, 6) if row >= 0 else None
        if item is None:
            return None
        try:
            return self._p32_store.get_recurring_schedule(item.text())
        except ValueError:
            return None

    def _p32_edit_selected_schedule(self) -> None:
        schedule = self._p32_selected_schedule()
        if schedule is None:
            return
        payload = self._p32_schedule_dialog(str(schedule["kind"]), schedule)
        if payload is None:
            return
        spec, next_run = payload
        try:
            self._p32_store.update_recurring_schedule(schedule["id"], spec, next_run_at=next_run)
        except Exception as exc:
            QMessageBox.warning(self, "Schedule Not Updated", str(exc))
            return
        self._p32_set_status("Recurring schedule updated.", "positive")
        self._p32_refresh_recurring(schedule["id"])

    def _p32_toggle_selected_schedule(self) -> None:
        schedule = self._p32_selected_schedule()
        if schedule is None:
            return
        try:
            if schedule["status"] == "active":
                self._p32_store.set_recurring_schedule_status(
                    schedule["id"], RecurringStatus.PAUSED, reason="Paused by user"
                )
                message = "Recurring schedule paused."
            else:
                next_run = iso_utc(next_recurring_run(schedule, dt.datetime.now(dt.timezone.utc)))
                self._p32_store.set_recurring_schedule_status(
                    schedule["id"], RecurringStatus.ACTIVE, next_run_at=next_run
                )
                message = "Recurring schedule resumed."
        except Exception as exc:
            QMessageBox.warning(self, "Schedule Not Updated", str(exc))
            return
        self._p32_set_status(message, "positive")
        self._p32_refresh_recurring(schedule["id"])

    def _p32_cancel_selected_schedule(self) -> None:
        schedule = self._p32_selected_schedule()
        if schedule is None:
            return
        reply = QMessageBox.question(
            self,
            "Cancel Recurring Schedule",
            "Cancel this schedule? Its run history will be retained.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._p32_store.set_recurring_schedule_status(schedule["id"], RecurringStatus.CANCELLED)
        self._p32_set_status("Recurring schedule cancelled.", "positive")
        self._p32_refresh_recurring(schedule["id"])

    def _p32_refresh_recurring(
        self,
        select_schedule_id: str | None = None,
        *,
        schedules: Any = None,
        account: Any = None,
    ) -> None:
        if not getattr(self, "_p32_active_account_id", ""):
            self.p32_recurring_table.setRowCount(0)
            self._p32_update_recurring_controls()
            return
        if schedules is None:
            if select_schedule_id is not None:
                self._p32_pending_recurring_selection = str(select_schedule_id)
            if self._p32_has_window_refresh_runtime():
                self._p32_refresh_all()
                return
            schedules = [
                dict(row)
                for row in self._p32_store.list_recurring_schedules(self._p32_active_account_id)
            ]
            account = dict(self._p32_store.get_account(self._p32_active_account_id))
        selected_id = select_schedule_id
        if selected_id is None:
            selected_id = getattr(self, "_p32_pending_recurring_selection", None)
        if selected_id is None:
            current = self._p32_selected_schedule()
            selected_id = str(current["id"]) if current else None
        self._p32_pending_recurring_selection = None
        values: list[list[str]] = []
        selected_row = -1
        for row_index, schedule in enumerate(schedules):
            kind = str(schedule["kind"])
            if kind == "funding":
                kind_label = "Funding"
                details = f"${float(schedule['amount']):,.2f} deposit"
            else:
                kind_label = "Buy"
                details = f"${float(schedule['amount']):,.2f} · {schedule['symbol']}"
            cadence = str(schedule["cadence"])
            if cadence == "weekly":
                weekday = (
                    "Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday",
                )[int(schedule["weekday"])]
                schedule_text = f"Weekly · {weekday} {schedule['local_time']}"
            elif cadence == "monthly":
                schedule_text = f"Monthly · day {int(schedule['month_day'])} {schedule['local_time']}"
            else:
                schedule_text = f"Daily · {schedule['local_time']}"
            schedule_text += f" · {schedule['timezone']}"
            last_status = str(schedule.get("last_run_status") or "")
            last_result = str(schedule.get("last_run_message") or "Never run")
            if last_status:
                last_result = f"{last_status.title()} · {last_result}"
            next_run = self._p32_parse_utc_time(schedule.get("next_run_at"))
            if next_run is not None:
                next_run_text = next_run.astimezone(
                    recurring_timezone(str(schedule.get("timezone") or "LOCAL"))
                ).strftime("%b %d, %H:%M %Z")
            else:
                next_run_text = str(schedule.get("next_run_at") or "")
            values.append([
                kind_label,
                details,
                schedule_text,
                next_run_text,
                last_result,
                str(schedule["status"]).title(),
                str(schedule["id"]),
            ])
            if str(schedule["id"]) == str(selected_id or ""):
                selected_row = row_index
        def _after_render() -> None:
            if selected_row >= 0:
                self.p32_recurring_table.selectRow(selected_row)
            if isinstance(account, dict):
                self._p32_active_account_snapshot = dict(account)
            self._p32_update_recurring_controls()

        self._p32_fill_table(self.p32_recurring_table, values, on_complete=_after_render)

    def _p32_update_recurring_controls(self) -> None:
        table = getattr(self, "p32_recurring_table", None)
        selected = self._p32_selected_schedule() if table is not None else None
        status = str((selected or {}).get("status") or "")
        editable = bool(selected and status != "cancelled")
        archived = False
        if getattr(self, "_p32_active_account_id", ""):
            account = getattr(self, "_p32_active_account_snapshot", None)
            archived = not isinstance(account, dict) or account.get("status") == "archived"
        self.p32_edit_schedule_btn.setEnabled(editable and not archived)
        self.p32_toggle_schedule_btn.setEnabled(editable and not archived)
        self.p32_toggle_schedule_btn.setText("Resume" if status == "paused" else "Pause")
        self.p32_cancel_schedule_btn.setEnabled(editable)
        if selected is None:
            self.p32_recurring_detail.setText(
                "Funding uses calendar cadence. Recurring buys skip weekends and US market holidays."
            )
            return
        reason = str(selected.get("pause_reason") or "").strip()
        detail = str(selected.get("last_run_message") or "No runs recorded yet.")
        if reason:
            detail = f"{reason} · {detail}"
        self.p32_recurring_detail.setText(detail)

    def _p32_build_order_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("virtualOrderCard")
        card.setMinimumWidth(315)
        self.set_theme_role(card, "panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        title = QLabel("Trade")
        title.setObjectName("virtualSectionHeading")
        layout.addWidget(title)

        self.p32_symbol_input = QLineEdit()
        self.p32_symbol_input.setPlaceholderText("Search symbol, e.g. AAPL")
        self.p32_symbol_input.setMaxLength(12)
        self.p32_symbol_input.textChanged.connect(self._p32_normalize_symbol)
        self.p32_symbol_input.returnPressed.connect(self._p32_request_symbol_chart)
        self.p32_chart_load_btn = QPushButton("Load")
        self.p32_chart_load_btn.setProperty("virtualRole", "secondary")
        self.p32_chart_load_btn.clicked.connect(self._p32_request_symbol_chart)
        symbol_row = QHBoxLayout()
        symbol_row.setSpacing(6)
        symbol_row.addWidget(self.p32_symbol_input, 1)
        symbol_row.addWidget(self.p32_chart_load_btn)
        layout.addLayout(symbol_row)

        side_row = QHBoxLayout()
        side_row.setSpacing(0)
        self.p32_side_group = QButtonGroup(self)
        self.p32_side_group.setExclusive(True)
        self.p32_buy_btn = QPushButton("Buy")
        self.p32_sell_btn = QPushButton("Sell")
        for button, side in ((self.p32_buy_btn, "buy"), (self.p32_sell_btn, "sell")):
            button.setCheckable(True)
            button.setProperty("virtualRole", "side")
            button.setProperty("orderSide", side)
            button.clicked.connect(self._p32_update_order_estimate)
            self.p32_side_group.addButton(button)
            side_row.addWidget(button, 1)
        self.p32_buy_btn.setChecked(True)
        layout.addLayout(side_row)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        self.p32_order_type_combo = QComboBox()
        for label, value in (("Market order", "market"), ("Limit order", "limit"), ("Stop order", "stop")):
            self.p32_order_type_combo.addItem(label, value)
        self.p32_order_type_combo.currentIndexChanged.connect(self._p32_update_ticket_fields)
        self.p32_quantity_spin = QDoubleSpinBox()
        self.p32_quantity_spin.setRange(0.000001, 10_000_000.0)
        self.p32_quantity_spin.setDecimals(6)
        self.p32_quantity_spin.setSingleStep(0.1)
        self.p32_quantity_spin.setValue(1)
        self.p32_quantity_spin.valueChanged.connect(self._p32_update_order_estimate)
        self.p32_tif_combo = QComboBox()
        self.p32_tif_combo.addItem("Good for day", "day")
        self.p32_tif_combo.addItem("Good 'til canceled", "gtc")
        self.p32_tif_combo.currentIndexChanged.connect(self._p32_update_session_hint)
        self.p32_trading_hours_combo = QComboBox()
        self.p32_trading_hours_combo.addItem("Regular market only", "regular")
        self.p32_trading_hours_combo.addItem("Pre-market + regular", "extended")
        self.p32_trading_hours_combo.currentIndexChanged.connect(self._p32_update_trading_hours)
        self.p32_limit_spin = self._p32_price_spin()
        self.p32_stop_spin = self._p32_price_spin()
        self.p32_limit_spin.valueChanged.connect(self._p32_update_order_estimate)
        self.p32_stop_spin.valueChanged.connect(self._p32_update_order_estimate)
        form.addRow("Order type", self.p32_order_type_combo)
        form.addRow("Shares", self.p32_quantity_spin)
        form.addRow("Trading hours", self.p32_trading_hours_combo)
        form.addRow("Time in force", self.p32_tif_combo)
        form.addRow("Limit price", self.p32_limit_spin)
        form.addRow("Stop price", self.p32_stop_spin)
        self.p32_limit_label = form.labelForField(self.p32_limit_spin)
        self.p32_stop_label = form.labelForField(self.p32_stop_spin)
        layout.addLayout(form)
        self.p32_session_hint = QLabel("")
        self.p32_session_hint.setWordWrap(True)
        self.set_theme_role(self.p32_session_hint, "muted")
        layout.addWidget(self.p32_session_hint)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("virtualDivider")
        layout.addWidget(divider)
        estimate_row = QHBoxLayout()
        estimate_title = QLabel("Estimated amount")
        self.p32_estimate_label = QLabel("After quote")
        self.p32_estimate_label.setObjectName("virtualEstimate")
        estimate_row.addWidget(estimate_title)
        estimate_row.addStretch(1)
        estimate_row.addWidget(self.p32_estimate_label)
        layout.addLayout(estimate_row)
        self.p32_quote_label = QLabel("Yahoo price data loads before review; bid/ask spread is ignored.")
        self.p32_quote_label.setWordWrap(True)
        self.set_theme_role(self.p32_quote_label, "muted")
        layout.addWidget(self.p32_quote_label)
        layout.addWidget(self._p32_build_symbol_chart(), 1)
        self.p32_review_btn = QPushButton("Review Order")
        self.p32_review_btn.setObjectName("virtualPrimaryButton")
        self.p32_review_btn.setMinimumHeight(40)
        self.p32_review_btn.clicked.connect(self._p32_review_order)
        layout.addWidget(self.p32_review_btn)
        warning = QLabel("Virtual orders are simulations and fill immediately without using bid/ask spreads.")
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(warning, "muted")
        layout.addWidget(warning)
        self._p32_update_ticket_fields()
        return card

    def _p32_build_symbol_chart(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("virtualSymbolChart")
        frame.setMinimumHeight(145)
        chart_layout = QVBoxLayout(frame)
        chart_layout.setContentsMargins(7, 6, 7, 5)
        chart_layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(5)
        self.p32_chart_symbol_label = QLabel("Symbol chart")
        self.p32_chart_symbol_label.setObjectName("virtualChartSymbol")
        self.p32_chart_price_label = QLabel("—")
        self.p32_chart_price_label.setObjectName("virtualChartPrice")
        self.p32_chart_change_label = QLabel("")
        self.p32_chart_change_label.setObjectName("virtualChartChange")
        header.addWidget(self.p32_chart_symbol_label)
        header.addStretch(1)
        header.addWidget(self.p32_chart_price_label)
        header.addWidget(self.p32_chart_change_label)
        chart_layout.addLayout(header)

        self.p32_chart_axis = DateAxisItem(orientation="bottom")
        self.p32_symbol_chart_plot = pg.PlotWidget(axisItems={"bottom": self.p32_chart_axis})
        self.p32_symbol_chart_plot.setMinimumHeight(78)
        self.p32_symbol_chart_plot.setMaximumHeight(180)
        self.p32_symbol_chart_plot.showGrid(x=True, y=True, alpha=0.12)
        self.p32_symbol_chart_plot.setMouseEnabled(x=False, y=False)
        plot_item = self.p32_symbol_chart_plot.getPlotItem()
        plot_item.setMenuEnabled(False)
        plot_item.hideAxis("left")
        plot_item.showAxis("right")
        plot_item.hideButtons()
        chart_layout.addWidget(self.p32_symbol_chart_plot, 1)

        range_row = QHBoxLayout()
        range_row.setSpacing(2)
        self.p32_chart_range_group = QButtonGroup(self)
        self.p32_chart_range_group.setExclusive(True)
        self.p32_chart_range_buttons: dict[str, QPushButton] = {}
        for key in P32_SYMBOL_CHART_RANGES:
            button = QPushButton(key)
            button.setCheckable(True)
            button.setProperty("virtualRole", "chartRange")
            button.clicked.connect(lambda checked=False, selected=key: self._p32_select_chart_range(selected))
            self.p32_chart_range_group.addButton(button)
            self.p32_chart_range_buttons[key] = button
            range_row.addWidget(button, 1)
        self.p32_chart_range_buttons[self._p32_chart_range_key].setChecked(True)
        chart_layout.addLayout(range_row)

        self.p32_chart_status_label = QLabel("Enter a symbol, then press Enter or Load.")
        self.p32_chart_status_label.setWordWrap(False)
        self.set_theme_role(self.p32_chart_status_label, "muted")
        chart_layout.addWidget(self.p32_chart_status_label)
        return frame

    @staticmethod
    def _p32_price_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.01, 10_000_000.0)
        spin.setDecimals(4)
        spin.setPrefix("$")
        spin.setValue(100.0)
        return spin

    @staticmethod
    def _p32_table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setMinimumHeight(34)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setShowGrid(False)
        return table

    def _p32_on_show(self) -> None:
        for timer_name in ("_p31_engine_timer", "_p31_mark_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self._p32_refresh_accounts(self._p32_shared_account_id())
        if not self._p32_engine_started:
            self._p32_engine_started = True
            self._p32_engine_timer.start()
            self._p32_mark_timer.start()
        self._p32_run_engine_cycle(mark=True, force=True)

    def _p32_on_hide(self) -> None:
        return

    def _p32_stop(self) -> None:
        self._p32_chart_request_id = int(getattr(self, "_p32_chart_request_id", 0)) + 1
        self._p32_chart_inflight = False
        self._p32_accounts_request_seq = int(getattr(self, "_p32_accounts_request_seq", 0)) + 1
        self._p32_accounts_refresh_running = False
        self._p32_accounts_refresh_pending = None
        for timer_name in ("_p32_engine_timer", "_p32_mark_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        executor = getattr(self, "_p32_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
            self._p32_executor = None
        chart_service = getattr(self, "_p32_chart_data_service", None)
        if chart_service is not None and getattr(self, "_p32_owns_chart_data_service", False):
            chart_service.close()
        self._p32_chart_data_service = None
        self._p32_owns_chart_data_service = False

    def _p32_shared_account_id(self) -> str:
        if getattr(self, "_p32_active_account_id", ""):
            return str(self._p32_active_account_id)
        return str(getattr(self, "_p31_active_account_id", "") or "")

    def _p32_refresh_accounts(self, select_account_id: str | None = None) -> None:
        desired = str(select_account_id or self._p32_active_account_id or "")
        if getattr(self, "_p32_accounts_refresh_running", False):
            active_desired = str(getattr(self, "_p32_accounts_refresh_context", "") or "")
            if desired == active_desired:
                self._p32_accounts_refresh_pending = None
            elif desired != getattr(self, "_p32_accounts_refresh_pending", None):
                self._p32_accounts_refresh_pending = desired
            return
        self._p32_start_accounts_refresh(desired)

    def _p32_start_accounts_refresh(self, desired: str) -> None:
        """Load the Virtual account selector without blocking Qt's event loop."""
        executor = getattr(self, "_p32_executor", None)
        dispatcher = getattr(self, "_invoke_main", None)
        has_window_runtime = executor is not None and callable(getattr(dispatcher, "emit", None))
        self._p32_accounts_request_seq = int(getattr(self, "_p32_accounts_request_seq", 0)) + 1
        request_id = self._p32_accounts_request_seq
        self._p32_accounts_refresh_running = True
        self._p32_accounts_refresh_context = str(desired or "")

        def _work() -> list[dict[str, Any]]:
            return [dict(account) for account in self._p32_store.list_accounts(include_archived=True)]

        if not has_window_runtime:
            try:
                accounts = _work()
                error = ""
            except Exception as exc:
                accounts = []
                error = str(exc)
            self._p32_complete_accounts_refresh(request_id, desired, accounts, error)
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
                    lambda rid=request_id, selected=desired, rows=accounts, message=error: self._p32_complete_accounts_refresh(
                        rid, selected, rows, message
                    )
                )
            except RuntimeError:
                return

        future.add_done_callback(_complete)

    def _p32_complete_accounts_refresh(
        self,
        request_id: int,
        desired: str,
        accounts: Any,
        error: str,
    ) -> None:
        if request_id != int(getattr(self, "_p32_accounts_request_seq", 0)):
            return
        self._p32_accounts_refresh_running = False
        self._p32_accounts_refresh_context = ""
        pending = getattr(self, "_p32_accounts_refresh_pending", None)
        self._p32_accounts_refresh_pending = None
        if pending is not None and pending != desired:
            self._p32_start_accounts_refresh(pending)
            return
        if error:
            self._p32_set_status(f"Virtual accounts could not be refreshed: {error}", "negative")
            return
        self._p32_apply_accounts(accounts, desired)

    def _p32_apply_accounts(self, accounts: Any, desired: str) -> None:
        accounts = [dict(account) for account in list(accounts or []) if isinstance(account, dict)]
        self._p32_accounts = accounts
        self.p32_account_combo.blockSignals(True)
        self.p32_account_combo.clear()
        selected_index = -1
        for account in accounts:
            archived = account["status"] == "archived"
            label = f"{account['name']} (Archived)" if archived else str(account["name"])
            self.p32_account_combo.addItem(label, account["id"])
            if account["id"] == desired:
                selected_index = self.p32_account_combo.count() - 1
        if selected_index < 0 and accounts:
            selected_index = next((index for index, account in enumerate(accounts) if account["status"] == "active"), 0)
        self.p32_account_combo.setCurrentIndex(selected_index)
        self.p32_account_combo.blockSignals(False)
        self._p32_active_account_id = str(self.p32_account_combo.currentData() or "")
        self._p32_active_account_snapshot = next(
            (dict(account) for account in accounts if str(account["id"] or "") == self._p32_active_account_id),
            None,
        )
        has_accounts = bool(accounts)
        self.p32_empty_state.setVisible(not has_accounts)
        self.p32_workspace.setVisible(has_accounts)
        self._p32_update_account_controls()
        if has_accounts:
            self._p32_refresh_all()

    def _p32_on_account_changed(self, _index: int) -> None:
        self._p32_active_account_id = str(self.p32_account_combo.currentData() or "")
        self._p32_active_account_snapshot = next(
            (
                dict(account)
                for account in getattr(self, "_p32_accounts", [])
                if str(account.get("id") or "") == self._p32_active_account_id
            ),
            None,
        )
        self._p32_update_account_controls()
        self._p32_refresh_all()

    def _p32_update_account_controls(self) -> None:
        account = getattr(self, "_p32_active_account_snapshot", None)
        archived = bool(account and account["status"] == "archived")
        self.p32_edit_account_btn.setEnabled(account is not None)
        self.p32_archive_account_btn.setEnabled(account is not None)
        self.p32_archive_account_btn.setText("Restore" if archived else "Archive")
        self.p32_review_btn.setEnabled(bool(account and not archived and not self._p32_task_inflight))
        if hasattr(self, "p32_add_funding_btn"):
            self.p32_add_funding_btn.setEnabled(bool(account and not archived))
            self.p32_add_buy_btn.setEnabled(bool(account and not archived))
            self._p32_update_recurring_controls()

    def _p32_account_dialog(self, title: str, account: dict[str, Any] | None = None) -> dict[str, Any] | None:
        editing = account is not None
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        details_heading = QLabel("Account details")
        details_heading.setObjectName("virtualSectionHeading")
        layout.addWidget(details_heading)
        form = QFormLayout()
        name = QLineEdit(str((account or {}).get("name", "")))
        name.setMaxLength(80)
        name.setPlaceholderText("e.g. Growth account")
        cash = QDoubleSpinBox()
        cash.setRange(0.0 if editing else 1.0, 1_000_000_000.0)
        cash.setDecimals(2)
        cash.setPrefix("$")
        current_cash = (
            self._p32_store.cash_balance(str(account.get("id") or ""))
            if editing
            else 100_000.0
        )
        reserved_cash = (
            self._p32_store.reserved_cash(str(account.get("id") or ""))
            if editing
            else 0.0
        )
        archived = bool(editing and account.get("status") == "archived")
        cash.setValue(current_cash)
        cash.setEnabled(not archived)
        form.addRow("Account name", name)
        form.addRow("Cash balance" if editing else "Starting cash", cash)
        layout.addLayout(form)

        change_label = QLabel()
        change_label.setWordWrap(True)
        self.set_theme_role(change_label, "muted")
        layout.addWidget(change_label)

        settings_group = QGroupBox("Future order settings")
        settings_group.setObjectName("virtualAccountSettings")
        settings_form = QFormLayout(settings_group)
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
        settings_form.addRow("Slippage", slippage)
        settings_form.addRow("Commission / fill", commission)
        layout.addWidget(settings_group)

        hint_text = (
            "Cash changes are recorded as deposits or withdrawals. Positions stay unchanged, and external cash flows "
            "do not count as investment returns. These account settings are shared with the Paper page."
            if editing
            else "The account and its future-order settings are shared with the Paper page."
        )
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        self.set_theme_role(hint, "muted")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save changes" if editing else "Create account")
        save_button.setObjectName("virtualPrimaryButton")

        def update_change_summary() -> None:
            clean_name = name.text().strip()
            desired_cash = cash.value()
            valid_amount = desired_cash + 1e-7 >= reserved_cash
            delta = desired_cash - current_cash
            if not editing:
                change_label.setText(f"Start with ${desired_cash:,.2f} in virtual cash.")
            elif archived:
                change_label.setText("Restore this account before changing its cash balance.")
            elif not valid_amount:
                change_label.setText(f"Keep at least ${reserved_cash:,.2f} for pending Paper buy orders.")
            elif delta > 0.005:
                change_label.setText(f"Deposit ${delta:,.2f} · New cash balance ${desired_cash:,.2f}")
            elif delta < -0.005:
                change_label.setText(f"Withdraw ${abs(delta):,.2f} · New cash balance ${desired_cash:,.2f}")
            else:
                change_label.setText(f"No cash change · Current balance ${current_cash:,.2f}")
            save_button.setEnabled(bool(clean_name) and valid_amount)

        name.textChanged.connect(update_change_summary)
        cash.valueChanged.connect(update_change_summary)
        update_change_summary()
        cancel_button.clicked.connect(dialog.reject)
        save_button.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        payload = {
            "name": name.text().strip(),
            "slippage_bps": slippage.value(),
            "commission_per_fill": commission.value(),
        }
        payload["target_cash" if editing else "initial_cash"] = cash.value()
        return payload

    def _p32_create_account_dialog(self) -> None:
        payload = self._p32_account_dialog("Create Virtual Account")
        if payload is None:
            return
        try:
            account = self._p32_store.create_account(**payload)
        except Exception as exc:
            QMessageBox.warning(self, "Account Not Created", str(exc))
            return
        self._p32_set_status(f"Created virtual account {account['name']}.", "positive")
        self._p32_refresh_accounts(account["id"])

    def _p32_edit_account_dialog(self) -> None:
        if not self._p32_active_account_id:
            return
        account = self._p32_store.get_account(self._p32_active_account_id)
        prior_cash = self._p32_store.cash_balance(account["id"])
        payload = self._p32_account_dialog("Edit Virtual Account", account)
        if payload is None:
            return
        target_cash = float(payload.get("target_cash", prior_cash) or 0.0)
        cash_delta = target_cash - prior_cash
        try:
            updated = self._p32_store.update_account(account["id"], **payload)
        except Exception as exc:
            QMessageBox.warning(self, "Account Not Updated", str(exc))
            return
        if abs(cash_delta) > 0.005:
            try:
                self._p32_store.record_equity_snapshot(account["id"], force=True)
            except Exception:
                logger.exception("Unable to record the equity snapshot after a Virtual cash adjustment.")
        if cash_delta > 0.005:
            message = f"Updated {updated['name']} · Deposited ${cash_delta:,.2f}."
        elif cash_delta < -0.005:
            message = f"Updated {updated['name']} · Withdrew ${abs(cash_delta):,.2f}."
        else:
            message = f"Updated {updated['name']} · Cash balance unchanged."
        self._p32_set_status(message, "positive")
        self._p32_refresh_accounts(updated["id"])

    def _p32_toggle_archive_account(self) -> None:
        if not self._p32_active_account_id:
            return
        account = self._p32_store.get_account(self._p32_active_account_id)
        try:
            if account["status"] == "archived":
                self._p32_store.restore_account(account["id"])
                message = f"Restored {account['name']}."
            else:
                reply = QMessageBox.question(
                    self,
                    "Archive Virtual Account",
                    "Archiving preserves history and cancels every pending order. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                self._p32_store.archive_account(account["id"])
                message = f"Archived {account['name']}."
        except Exception as exc:
            QMessageBox.warning(self, "Account Update Failed", str(exc))
            return
        self._p32_set_status(message, "positive")
        self._p32_refresh_accounts(account["id"])

    def _p32_normalize_symbol(self, text: str) -> None:
        upper = text.upper()
        if upper != text:
            cursor = self.p32_symbol_input.cursorPosition()
            self.p32_symbol_input.blockSignals(True)
            self.p32_symbol_input.setText(upper)
            self.p32_symbol_input.setCursorPosition(cursor)
            self.p32_symbol_input.blockSignals(False)
        self._p32_on_chart_symbol_edited(upper)

    def _p32_on_chart_symbol_edited(self, symbol: str) -> None:
        clean_symbol = str(symbol or "").upper().strip()
        loaded_symbol = str(getattr(self, "_p32_chart_loaded_symbol", "") or "")
        if clean_symbol == loaded_symbol:
            return
        self._p32_chart_request_id += 1
        self._p32_chart_inflight = False
        self.p32_chart_load_btn.setEnabled(True)
        self._p32_clear_symbol_chart("Enter a symbol, then press Enter or Load.")

    def _p32_get_chart_data_service(self) -> ChartDataService:
        shared_getter = getattr(self, "_get_chart_data_service", None)
        if callable(shared_getter):
            return shared_getter()
        service = getattr(self, "_p32_chart_data_service", None)
        if service is None:
            service = ChartDataService()
            self._p32_chart_data_service = service
            self._p32_owns_chart_data_service = True
        return service

    def _p32_select_chart_range(self, range_key: str) -> None:
        selected = str(range_key or "").upper()
        if selected not in P32_SYMBOL_CHART_RANGES:
            return
        self._p32_chart_range_key = selected
        button = self.p32_chart_range_buttons.get(selected)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        symbol = self.p32_symbol_input.text().upper().strip()
        if not symbol or symbol != self._p32_chart_loaded_symbol:
            return
        if selected == self._p32_chart_loaded_range and not self._p32_chart_inflight:
            return
        self._p32_request_symbol_chart()

    def _p32_request_symbol_chart(self, *_: Any, force_refresh: bool = False) -> None:
        symbol = self.p32_symbol_input.text().upper().strip()
        if not symbol:
            self._p32_clear_symbol_chart("Enter a symbol before loading its chart.", "negative")
            return
        range_key = self._p32_chart_range_key
        period, interval = P32_SYMBOL_CHART_RANGES[range_key]
        self._p32_chart_request_id += 1
        request_id = self._p32_chart_request_id
        prior_symbol = self._p32_chart_loaded_symbol
        self._p32_chart_inflight = True
        self.p32_chart_load_btn.setEnabled(False)
        if prior_symbol and prior_symbol != symbol:
            self._p32_clear_symbol_chart(f"Loading {symbol} {range_key} candles...")
        else:
            self._p32_set_chart_status(f"Loading {symbol} {range_key} candles...", "info")

        def _work() -> dict[str, Any]:
            return self._p32_get_chart_data_service().fetch_base_frame_payload(
                symbol,
                period=period,
                interval=interval,
                force_refresh=force_refresh,
                include_extended_hours=range_key == "1D",
            )

        self._p32_submit_chart_background(
            request_id=request_id,
            symbol=symbol,
            range_key=range_key,
            work=_work,
        )

    def _p32_submit_chart_background(
        self,
        *,
        request_id: int,
        symbol: str,
        range_key: str,
        work: Callable[[], dict[str, Any]],
    ) -> None:
        executor = getattr(self, "_p32_executor", None)
        if executor is None:
            self._p32_on_chart_error(request_id, "Chart loader is unavailable.")
            return

        def _run() -> None:
            try:
                payload = work()
            except Exception as exc:
                self._invoke_main.emit(
                    lambda rid=request_id, message=str(exc): self._p32_on_chart_error(rid, message)
                )
                return
            self._invoke_main.emit(
                lambda rid=request_id, ticker=symbol, key=range_key, value=payload: self._p32_on_chart_complete(
                    rid,
                    ticker,
                    key,
                    value,
                )
            )

        executor.submit(_run)

    def _p32_on_chart_complete(
        self,
        request_id: int,
        symbol: str,
        range_key: str,
        payload: dict[str, Any],
    ) -> None:
        if int(request_id) != int(self._p32_chart_request_id):
            return
        self._p32_chart_inflight = False
        self.p32_chart_load_btn.setEnabled(True)
        frame = payload.get("df") if isinstance(payload, dict) else None
        metadata = market_data_meta(payload)
        if frame is None or getattr(frame, "empty", True):
            reason = str(metadata.get("failure_reason") or f"No chart data returned for {symbol}.")
            self._p32_clear_symbol_chart(reason, "negative")
            return
        required_columns = {"Open", "High", "Low", "Close"}
        if not required_columns.issubset(set(frame.columns)):
            self._p32_clear_symbol_chart(f"Chart data for {symbol} is missing OHLC prices.", "negative")
            return
        self._p32_chart_loaded_symbol = str(symbol)
        self._p32_chart_loaded_range = str(range_key)
        self._p32_chart_includes_extended_hours = range_key == "1D"
        self._p32_chart_frame = frame.copy()
        self._p32_render_symbol_chart()
        source = str(metadata.get("source") or "Yahoo")
        if bool(metadata.get("is_stale")):
            age = metadata.get("cache_age_seconds")
            age_text = f" · cache age {float(age) / 60.0:.0f} min" if age not in (None, "") else ""
            self._p32_set_chart_status(f"Showing stale {source} data{age_text}.", "warning")
        elif self._p32_chart_includes_extended_hours:
            self._p32_set_chart_status(f"Loaded delayed pre-market candles from {source}.", "muted")
        elif source == "cache":
            self._p32_set_chart_status("Loaded from the local chart cache.", "muted")
        else:
            self._p32_set_chart_status(f"Loaded from {source}.", "muted")

    def _p32_on_chart_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self._p32_chart_request_id):
            return
        self._p32_chart_inflight = False
        self.p32_chart_load_btn.setEnabled(True)
        self._p32_clear_symbol_chart(f"Chart load failed: {message}", "negative")

    def _p32_clear_symbol_chart(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p32_symbol_chart_plot"):
            self.p32_symbol_chart_plot.clear()
            self.p32_chart_axis.set_dates([], "1d")
        self._p32_chart_loaded_symbol = ""
        self._p32_chart_loaded_range = ""
        self._p32_chart_includes_extended_hours = False
        self._p32_chart_frame = None
        if hasattr(self, "p32_chart_symbol_label"):
            self.p32_chart_symbol_label.setText("Symbol chart")
            self.p32_chart_price_label.setText("—")
            self.p32_chart_change_label.clear()
            self.p32_chart_change_label.setProperty("chartState", "flat")
            self._p32_repolish(self.p32_chart_change_label)
            self._p32_set_chart_status(message, status)

    def _p32_set_chart_status(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p32_chart_status_label"):
            self.set_status_text(self.p32_chart_status_label, str(message), status=status)

    def _p32_render_symbol_chart(self) -> None:
        frame = getattr(self, "_p32_chart_frame", None)
        if frame is None or getattr(frame, "empty", True):
            return
        clean_frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
        if clean_frame.empty:
            return
        candles = []
        for index, row in enumerate(clean_frame.itertuples()):
            candles.append((index, float(row.Open), float(row.Close), float(row.Low), float(row.High)))
        closes = [float(value) for value in clean_frame["Close"]]
        lows = [float(value) for value in clean_frame["Low"]]
        highs = [float(value) for value in clean_frame["High"]]
        first_close = closes[0]
        latest_close = closes[-1]
        change = latest_close - first_close
        change_pct = (change / first_close * 100.0) if first_close else 0.0
        state = "positive" if change > 0 else "negative" if change < 0 else "flat"

        plot = self.p32_symbol_chart_plot
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
        self.p32_chart_candle_item = candle_item
        self.p32_chart_last_price_line = latest_line
        _period, interval = P32_SYMBOL_CHART_RANGES.get(self._p32_chart_loaded_range, ("1mo", "1h"))
        self.p32_chart_axis.set_dates(clean_frame.index.to_list(), interval)
        plot.setXRange(-1.0, max(float(len(candles)), 1.0), padding=0.01)
        low = min(lows)
        high = max(highs)
        padding = max((high - low) * 0.07, abs(latest_close) * 0.002, 0.01)
        plot.setYRange(low - padding, high + padding, padding=0.0)

        session_suffix = " · PRE included" if self._p32_chart_includes_extended_hours else ""
        self.p32_chart_symbol_label.setText(
            f"{self._p32_chart_loaded_symbol} · {self._p32_chart_loaded_range}{session_suffix}"
        )
        self.p32_chart_price_label.setText(f"${latest_close:,.2f}")
        sign = "+" if change > 0 else ""
        self.p32_chart_change_label.setText(f"{sign}{change_pct:.2f}%")
        self.p32_chart_change_label.setProperty("chartState", state)
        self._p32_repolish(self.p32_chart_change_label)

    def _p32_selected_side(self) -> str:
        return "sell" if self.p32_sell_btn.isChecked() else "buy"

    def _p32_update_ticket_fields(self) -> None:
        order_type = str(self.p32_order_type_combo.currentData() or "market")
        if order_type != "limit" and str(self.p32_trading_hours_combo.currentData() or "regular") == "extended":
            self.p32_trading_hours_combo.setCurrentIndex(0)
        self.p32_limit_spin.setVisible(order_type == "limit")
        self.p32_stop_spin.setVisible(order_type == "stop")
        self.p32_limit_label.setVisible(order_type == "limit")
        self.p32_stop_label.setVisible(order_type == "stop")
        if order_type == "market":
            self.p32_tif_combo.setCurrentIndex(0)
            self.p32_tif_combo.setEnabled(False)
        else:
            self.p32_tif_combo.setEnabled(True)
        self._p32_update_session_hint()
        self._p32_update_order_estimate()

    def _p32_update_trading_hours(self, *_: Any) -> None:
        extended = str(self.p32_trading_hours_combo.currentData() or "regular") == "extended"
        if extended and str(self.p32_order_type_combo.currentData() or "market") != "limit":
            limit_index = self.p32_order_type_combo.findData("limit")
            self.p32_order_type_combo.setCurrentIndex(limit_index)
        if extended:
            self.p32_tif_combo.setCurrentIndex(self.p32_tif_combo.findData("day"))
            self.p32_tif_combo.setEnabled(False)
        else:
            self._p32_update_ticket_fields()
        self._p32_update_session_hint()

    def _p32_update_session_hint(self, *_: Any) -> None:
        if not hasattr(self, "p32_session_hint"):
            return
        extended = str(self.p32_trading_hours_combo.currentData() or "regular") == "extended"
        if extended:
            text = (
                "PRE eligible · DAY limit only · fills immediately at the entered limit price. "
                "Trading hours and time in force are retained in the order record."
            )
        elif str(self.p32_tif_combo.currentData() or "day") == "gtc":
            text = "Regular-hours GTC metadata · Virtual still fills immediately at its simulated price."
        else:
            text = "Regular-hours DAY metadata · Virtual fills immediately without waiting for the session."
        self.p32_session_hint.setText(text)

    def _p32_update_order_estimate(self, *_: Any) -> None:
        order_type = str(self.p32_order_type_combo.currentData() or "market")
        if order_type == "limit":
            amount = self.p32_quantity_spin.value() * self.p32_limit_spin.value()
            self.p32_estimate_label.setText(f"${amount:,.2f}")
        elif order_type == "stop":
            amount = self.p32_quantity_spin.value() * self.p32_stop_spin.value()
            self.p32_estimate_label.setText(f"~${amount:,.2f}")
        else:
            self.p32_estimate_label.setText("After quote")

    def _p32_build_request(self) -> PaperOrderRequest:
        order_type = str(self.p32_order_type_combo.currentData() or "market")
        return PaperOrderRequest(
            account_id=self._p32_active_account_id,
            symbol=self.p32_symbol_input.text(),
            side=self._p32_selected_side(),
            quantity=self.p32_quantity_spin.value(),
            order_type=order_type,
            tif=str(self.p32_tif_combo.currentData() or "day"),
            limit_price=self.p32_limit_spin.value() if order_type == "limit" else None,
            stop_price=self.p32_stop_spin.value() if order_type == "stop" else None,
            execution_session=str(self.p32_trading_hours_combo.currentData() or "regular"),
        ).normalized()

    def _p32_review_order(self) -> None:
        if self._p32_task_inflight:
            return
        try:
            request = self._p32_build_request()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Virtual Order", str(exc))
            return
        self._p32_set_busy(True, f"Loading Yahoo price data for {request.symbol}...")
        self._p32_submit_background(
            lambda: (request, self._p32_quote_service.fetch(request.symbol)),
            self._p32_show_order_review,
            "Quote load failed",
        )

    def _p32_show_order_review(self, payload: tuple[PaperOrderRequest, Any]) -> None:
        request, quote = payload
        self._p32_set_busy(False)
        extended = str(request.execution_session) == "extended"
        if request.order_type == "limit":
            reference = float(request.limit_price or 0.0)
            reference_source = "entered limit price"
        elif request.order_type == "stop":
            reference = float(request.stop_price or 0.0)
            reference_source = "entered stop price"
        elif quote.market_state == "PRE" and quote.mark_price:
            reference = float(quote.mark_price)
            reference_source = "Yahoo PRE mark"
        else:
            reference = float(quote.last_price or 0.0)
            reference_source = "Yahoo regular last price"
        if quote.market_state == "PRE" and quote.mark_timestamp is not None:
            quote_age = quote.mark_age_seconds()
        else:
            quote_age = quote.age_seconds()
        age_text = "timestamp unavailable" if quote_age is None else f"{quote_age / 60.0:.1f} min old"
        self.p32_quote_label.setText(
            f"Virtual price ${reference:,.4f} · {reference_source} · "
            f"{quote.market_state or 'state unavailable'} · {age_text} · bid/ask ignored"
        )
        if reference <= 0:
            QMessageBox.warning(
                self,
                "Price Unavailable",
                "A usable Yahoo pre-market mark, regular last price, or entered order price was not available.",
            )
            return
        estimate_price = (
            float(request.limit_price or 0.0)
            if request.order_type == "limit"
            else float(request.stop_price or reference)
            if request.order_type == "stop"
            else reference
        )
        estimated = request.quantity * estimate_price
        summary = self._p32_store.account_summary(request.account_id)
        account = self._p32_store.get_account(request.account_id)
        reservation = self._p32_engine.reservation_required(request, account, quote)
        price_detail = ""
        if request.order_type == "limit":
            price_detail = f"Limit price: ${float(request.limit_price or 0.0):,.4f}\n"
        elif request.order_type == "stop":
            price_detail = f"Stop trigger: ${float(request.stop_price or 0.0):,.4f}\n"
        hours_text = "Pre-market + regular (4:00 a.m.–4:00 p.m. ET)" if extended else "Regular market (9:30 a.m.–4:00 p.m. ET)"
        if request.side == "buy":
            if reservation > float(summary["buying_power"]) + 1e-7:
                QMessageBox.warning(
                    self,
                    "Insufficient Buying Power",
                    f"This order needs ${reservation:,.2f} of reserved cash, but only "
                    f"${float(summary['buying_power']):,.2f} is available.",
                )
                return
            impact = (
                f"Buying power: ${float(summary['buying_power']):,.2f}\n"
                f"Cash reserved: ${reservation:,.2f}\n"
                f"Remaining after reservation: ${float(summary['buying_power']) - reservation:,.2f}\n"
            )
        else:
            available = self._p32_store.available_shares(request.account_id, request.symbol)
            if request.quantity > available:
                QMessageBox.warning(
                    self,
                    "Insufficient Shares",
                    f"Only {format_share_quantity(available)} unreserved {request.symbol} share(s) are available to sell.",
                )
                return
            impact = (
                f"Available shares: {format_share_quantity(available)}\n"
                f"Remaining after fill: {format_share_quantity(max(available - request.quantity, 0))}\n"
            )
        execution_note = "Virtual execution is immediate and does not use the bid/ask spread.\n"
        detail = (
            f"{request.side.title()} {format_share_quantity(request.quantity)} share(s) of {request.symbol}\n"
            f"{request.order_type.title()} order\n"
            f"{price_detail}Trading hours: {hours_text}\n"
            f"Time in force: {request.tif.upper()}\n"
            "Execution timing: Immediate simulated fill\n"
            f"Fill reference: ${reference:,.4f} ({reference_source})\n"
            f"Source age: {age_text} · Bid/ask spread ignored\n"
            f"Estimated amount: ${estimated:,.2f}\n"
            f"{impact}{execution_note}\n"
            "Submit this virtual order?"
        )
        reply = QMessageBox.question(
            self,
            "Review Virtual Order",
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._p32_set_status("Virtual order review cancelled.")
            return
        self._p32_set_busy(True, f"Submitting virtual {request.side} order...")

        def _work() -> tuple[dict[str, Any], dict[str, Any]]:
            order = self._p32_engine.submit_order(request, quote=quote)
            result = self._p32_engine.process_pending_orders(quotes={request.symbol: quote})
            return order, result

        self._p32_submit_background(_work, self._p32_on_submit_complete, "Order submission failed")

    def _p32_on_submit_complete(self, payload: tuple[dict[str, Any], dict[str, Any]]) -> None:
        order, result = payload
        self._p32_set_busy(False)
        filled = int(result.get("filled", 0) or 0)
        status = "filled" if filled else str(self._p32_store.get_order(order["id"])["status"])
        self._p32_set_status(f"Virtual order {order['id'][:8]} is {status}.", "positive" if filled else "info")
        self._p32_refresh_all()

    def _p32_submit_background(self, work: Callable[[], Any], complete: Callable[[Any], None], error_prefix: str) -> None:
        executor = getattr(self, "_p32_executor", None)
        if executor is None:
            self._p32_set_busy(False)
            return

        def _run() -> None:
            try:
                payload = work()
            except Exception as exc:
                self._invoke_main.emit(lambda message=f"{error_prefix}: {exc}": self._p32_on_task_error(message))
                return
            self._invoke_main.emit(lambda value=payload: complete(value))

        executor.submit(_run)

    def _p32_run_engine_cycle(self, *, mark: bool, force: bool = False) -> None:
        if self._p32_task_inflight or getattr(self, "_p32_executor", None) is None:
            return
        self._p32_set_busy(True, "Refreshing virtual orders and account marks...")
        self._p32_submit_background(lambda: self._p32_engine.run_cycle(mark=mark), self._p32_on_cycle_complete, "Virtual refresh failed")

    def _p32_on_cycle_complete(self, result: dict[str, Any]) -> None:
        self._p32_set_busy(False)
        self._p32_market_phase = str(result.get("market_phase") or "")
        filled = int(result.get("filled", 0) or 0)
        expired = int(result.get("expired", 0) or 0)
        cycle_errors = list(result.get("errors", []) or [])
        mark_errors = list((result.get("marks") or {}).get("errors", []) or [])
        errors = mark_errors if self._p32_market_phase == "premarket" and mark_errors else cycle_errors + mark_errors
        if filled or expired:
            self._p32_set_status(f"Virtual engine: {filled} filled, {expired} expired.", "positive")
        elif self._p32_market_phase == "premarket" and errors:
            self._p32_set_status(
                f"Pre-market refresh retained {len(errors)} stale or unavailable Yahoo mark(s).",
                "warning",
            )
        elif self._p32_market_phase == "premarket":
            self._p32_set_status("Virtual account refreshed with delayed Yahoo pre-market marks.", "info")
        elif errors:
            self._p32_set_status(f"Virtual refresh completed with {len(errors)} Yahoo quote issue(s).", "warning")
        else:
            self._p32_set_status("Virtual account refreshed. Yahoo quotes may be delayed.", "info")
        self._p32_refresh_all()

    def _p32_on_task_error(self, message: str) -> None:
        self._p32_set_busy(False)
        self._p32_set_status(message, "negative")

    def _p32_set_busy(self, busy: bool, message: str = "") -> None:
        self._p32_task_inflight = bool(busy)
        self.p32_refresh_btn.setEnabled(not busy)
        self._p32_update_account_controls()
        if message:
            self._p32_set_status(message, "info")

    def _p32_set_status(self, message: str, status: str = "muted") -> None:
        if hasattr(self, "p32_status_label"):
            self.set_status_text(self.p32_status_label, str(message), status=status)

    def _p32_cancel_selected_order(self) -> None:
        row = self.p32_orders_table.currentRow()
        if row < 0:
            return
        order_id = self.p32_orders_table.item(row, 8)
        if order_id is None:
            return
        try:
            order = self._p32_store.cancel_order(order_id.text())
        except Exception as exc:
            QMessageBox.warning(self, "Order Not Cancelled", str(exc))
            return
        self._p32_set_status(f"Cancelled {order['symbol']} order {order['id'][:8]}.", "positive")
        self._p32_refresh_all()

    def _p32_trade_selected_position(self, item: QTableWidgetItem) -> None:
        symbol_item = self.p32_positions_table.item(item.row(), 0)
        quantity_item = self.p32_positions_table.item(item.row(), 1)
        if symbol_item is None or quantity_item is None:
            return
        self.p32_symbol_input.setText(symbol_item.text())
        try:
            self.p32_quantity_spin.setValue(max(0.000001, float(quantity_item.text().replace(",", ""))))
        except ValueError:
            self.p32_quantity_spin.setValue(1)
        self.p32_sell_btn.setChecked(True)
        self.p32_symbol_input.setFocus()

    def _p32_refresh_all(self) -> None:
        """Refresh common account data and only the visible Virtual tab off the UI thread."""
        if not self._p32_active_account_id:
            return
        account_id = str(self._p32_active_account_id)
        tab_index = int(self.p32_tabs.currentIndex()) if hasattr(self, "p32_tabs") else 0
        order_filter = str(self.p32_order_filter.currentData() or "all") if hasattr(self, "p32_order_filter") else "all"
        context = (account_id, tab_index, order_filter)
        cached = getattr(self, "_p32_view_cache", {}).get(context)
        if isinstance(cached, dict):
            self._p32_apply_view_snapshot(context, cached)
        if getattr(self, "_p32_view_refresh_running", False):
            if context != getattr(self, "_p32_view_refresh_context", None):
                self._p32_view_refresh_pending = context
            return
        self._p32_start_view_refresh(context)

    def _p32_has_window_refresh_runtime(self) -> bool:
        """Return whether the full window can marshal refresh results to Qt's UI thread."""
        dispatcher = getattr(self, "_invoke_main", None)
        return callable(getattr(dispatcher, "emit", None)) and callable(
            getattr(self, "_is_current_page", None)
        )

    def _p32_page_is_visible(self) -> bool:
        """Treat isolated widget probes as visible while preserving real-window guards."""
        is_current_page = getattr(self, "_is_current_page", None)
        if not callable(is_current_page):
            return True
        return bool(is_current_page(getattr(self, "page32", None)))

    def _p32_start_view_refresh(self, context: tuple[str, int, str]) -> None:
        executor = getattr(self, "_p32_executor", None)
        has_window_runtime = self._p32_has_window_refresh_runtime()
        if executor is None and has_window_runtime:
            return
        self._p32_view_request_seq += 1
        request_id = self._p32_view_request_seq
        self._p32_view_refresh_running = True
        self._p32_view_refresh_context = context

        def _work() -> dict[str, Any]:
            account_id, tab_index, order_filter = context
            account = dict(self._p32_store.get_account(account_id))
            summary = dict(self._p32_store.account_summary(account_id))
            positions = [dict(row) for row in self._p32_store.list_positions(account_id)]
            snapshot: dict[str, Any] = {
                "account": account,
                "summary": summary,
                "net_contributions": float(self._p32_store.net_contributions(account_id)),
                "positions": positions,
                "performance": [dict(row) for row in self._p32_store.list_equity_snapshots(account_id)],
                "cash_events": [dict(row) for row in self._p32_store.list_cash_events(account_id, external_only=True)],
                "tab_index": tab_index,
            }
            if tab_index == 1:
                snapshot["orders"] = [dict(row) for row in self._p32_store.list_orders(account_id, status=order_filter)]
            elif tab_index == 2:
                snapshot["fills"] = [dict(row) for row in self._p32_store.list_fills(account_id)]
            elif tab_index == 3:
                snapshot["recurring"] = [dict(row) for row in self._p32_store.list_recurring_schedules(account_id)]
            return snapshot

        if not has_window_runtime:
            try:
                payload = _work()
                error = ""
            except Exception as exc:
                payload = None
                error = str(exc)
            self._p32_complete_view_refresh(request_id, context, payload, error)
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
                    lambda rid=request_id, ctx=context, data=payload, message=error: self._p32_complete_view_refresh(
                        rid, ctx, data, message
                    )
                )
            except RuntimeError:
                return

        future.add_done_callback(_complete)

    def _p32_complete_view_refresh(
        self,
        request_id: int,
        context: tuple[str, int, str],
        payload: Any,
        error: str,
    ) -> None:
        if request_id != getattr(self, "_p32_view_request_seq", 0):
            return
        self._p32_view_refresh_running = False
        self._p32_view_refresh_context = None
        if isinstance(payload, dict):
            self._p32_view_cache[context] = payload
            self._p32_apply_view_snapshot(context, payload)
        elif error and self._p32_page_is_visible():
            self._p32_set_status(f"Virtual view refresh failed: {error}", "negative")
        pending = self._p32_view_refresh_pending
        self._p32_view_refresh_pending = None
        if pending is not None and pending != context:
            self._p32_start_view_refresh(pending)

    def _p32_current_view_context(self) -> tuple[str, int, str]:
        return (
            str(getattr(self, "_p32_active_account_id", "") or ""),
            int(self.p32_tabs.currentIndex()) if hasattr(self, "p32_tabs") else 0,
            str(self.p32_order_filter.currentData() or "all") if hasattr(self, "p32_order_filter") else "all",
        )

    def _p32_apply_view_snapshot(self, context: tuple[str, int, str], payload: dict[str, Any]) -> None:
        if context != self._p32_current_view_context():
            return
        if not self._p32_page_is_visible():
            return
        try:
            account = payload.get("account", {})
            if isinstance(account, dict):
                self._p32_active_account_snapshot = dict(account)
            self._p32_refresh_summary(payload)
            self._p32_refresh_performance(snapshot=payload)
            tab_index = int(payload.get("tab_index", context[1]))
            if tab_index == 0:
                self._p32_refresh_positions(payload.get("positions", []))
            elif tab_index == 1:
                self._p32_refresh_orders(rows=payload.get("orders", []))
            elif tab_index == 2:
                self._p32_refresh_fills(payload.get("fills", []))
            elif tab_index == 3:
                self._p32_refresh_recurring(
                    getattr(self, "_p32_pending_recurring_selection", None),
                    schedules=payload.get("recurring", []),
                    account=account,
                )
        except Exception as exc:
            logger.exception("Virtual page refresh failed.")
            self._p32_set_status(f"Virtual view refresh failed: {exc}", "negative")

    def _p32_refresh_summary(self, snapshot: Any = None) -> None:
        if not isinstance(snapshot, dict):
            self._p32_refresh_all()
            return
        summary = snapshot.get("summary", {})
        equity = float(summary.get("equity", 0.0) or 0.0)
        net_contributions = float(snapshot.get("net_contributions", 0.0) or 0.0)
        total_return = equity - net_contributions
        self.p32_equity_label.setText(f"${equity:,.2f}")
        sign = "+" if total_return > 0 else ""
        if net_contributions > 1e-7:
            total_return_pct = total_return / net_contributions * 100.0
            percent_sign = "+" if total_return_pct > 0 else ""
            percent_text = f"{percent_sign}{total_return_pct:.2f}%"
        else:
            percent_text = "—"
        self.p32_return_label.setText(f"{sign}${total_return:,.2f} ({percent_text}) all time")
        self.p32_return_label.setProperty("returnState", "positive" if total_return > 0 else "negative" if total_return < 0 else "flat")
        self._p32_repolish(self.p32_return_label)
        for key, label in self.p32_summary_labels.items():
            label.setText(f"${float(summary.get(key, 0.0) or 0.0):,.2f}")
        stale = int(summary.get("stale_mark_count", 0) or 0)
        positions = list(snapshot.get("positions", []) or [])
        has_premarket_marks = any("pre-market" in str(row.get("mark_source") or "").lower() for row in positions)
        if self._p32_market_phase == "premarket" or has_premarket_marks:
            badge = "PRE · delayed Yahoo marks"
            if stale:
                badge += f" · {stale} stale"
            self.p32_market_state_label.setText(badge)
        else:
            self.p32_market_state_label.setText("Live paper marks" if not stale else f"{stale} stale mark(s)")

    def _p32_refresh_performance(self, *_: Any, snapshot: Any = None) -> None:
        if not getattr(self, "_p32_active_account_id", ""):
            return
        if not isinstance(snapshot, dict):
            self._p32_refresh_all()
            return
        rows = list(snapshot.get("performance", []) or [])
        account = dict(snapshot.get("account", {}) or {})
        summary = dict(snapshot.get("summary", {}) or {})
        external_events = list(snapshot.get("cash_events", []) or [])
        adjustment_events = []
        for event in external_events:
            if event.get("event_type") not in {"deposit", "withdrawal"}:
                continue
            event_time = self._p32_parse_utc_time(event.get("created_at"))
            if event_time is not None:
                adjustment_events.append((event_time, event))
        adjustment_events.sort(key=lambda item: item[0])
        event_index = 0
        cumulative_adjustment = 0.0
        adjusted_rows = []
        for row in rows:
            row_time = self._p32_parse_utc_time(row.get("created_at"))
            while event_index < len(adjustment_events):
                event_time, event = adjustment_events[event_index]
                if row_time is None or event_time > row_time:
                    break
                cumulative_adjustment += float(event.get("amount") or 0.0)
                event_index += 1
            adjusted_rows.append((row_time, float(row.get("equity") or 0.0) - cumulative_adjustment))
        selected_key = next((key for key, button in self.p32_range_buttons.items() if button.isChecked()), "all")
        days = {"1d": 1, "1w": 7, "1m": 31, "3m": 93, "1y": 366}.get(selected_key)
        if days is not None:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
            filtered = []
            for timestamp, adjusted_equity in adjusted_rows:
                if timestamp is not None and timestamp >= cutoff:
                    filtered.append((timestamp, adjusted_equity))
            adjusted_rows = filtered
        values = [adjusted_equity for _timestamp, adjusted_equity in adjusted_rows]
        initial_cash = float(account.get("initial_cash", 0.0) or 0.0)
        net_contributions = float(snapshot.get("net_contributions", 0.0) or 0.0)
        adjusted_current_equity = float(summary.get("equity", 0.0) or 0.0) - (net_contributions - initial_cash)
        if not values:
            values = (
                [initial_cash, adjusted_current_equity]
                if days is None
                else [adjusted_current_equity, adjusted_current_equity]
            )
        elif len(values) == 1:
            values.insert(0, initial_cash if days is None else values[0])
        self.p32_performance_plot.clear()
        positive = values[-1] >= values[0]
        color = self._P32_ACCENT if positive else self.theme_color("accent_negative")
        baseline = values[0]
        self.p32_performance_plot.addLine(y=baseline, pen=pg.mkPen(self.theme_color("panel_border"), width=1, style=Qt.PenStyle.DashLine))
        self.p32_performance_plot.plot(
            list(range(len(values))),
            values,
            pen=pg.mkPen(color, width=2.4),
            fillLevel=baseline,
            brush=pg.mkBrush(QColor(color).red(), QColor(color).green(), QColor(color).blue(), 24),
        )
        self.p32_performance_plot.enableAutoRange()

    def _p32_refresh_positions(self, rows: Any = None) -> None:
        if rows is None:
            self._p32_refresh_all()
            return
        has_premarket_marks = any("pre-market" in str(row.get("mark_source") or "").lower() for row in rows)
        price_header = self.p32_positions_table.horizontalHeaderItem(2)
        if price_header is not None:
            price_header.setText(
                "Price (PRE)" if self._p32_market_phase == "premarket" or has_premarket_marks else "Price"
            )
        values = []
        returns = []
        for position in rows:
            quantity = float(position["quantity"])
            average = float(position["average_cost"] or 0.0)
            mark = float(position["mark_price"] or average)
            total_return = quantity * (mark - average)
            values.append([
                position["symbol"],
                format_share_quantity(quantity),
                f"${mark:,.4f}",
                f"${quantity * mark:,.2f}",
                f"{'+' if total_return > 0 else ''}${total_return:,.2f}",
                f"${average:,.4f}",
            ])
            returns.append(total_return)
        def _after_render() -> None:
            for row_index, value in enumerate(returns):
                item = self.p32_positions_table.item(row_index, 4)
                if item is not None:
                    item.setForeground(QColor(self._P32_ACCENT if value > 0 else self.theme_color("accent_negative") if value < 0 else self.theme_color("text_secondary")))

        self._p32_fill_table(self.p32_positions_table, values, on_complete=_after_render)

    def _p32_refresh_orders(self, *_: Any, rows: Any = None) -> None:
        if not self._p32_active_account_id:
            return
        if rows is None:
            self._p32_refresh_all()
            return
        values = []
        for order in rows:
            order_type = str(order["order_type"])
            if order_type == "limit":
                order_text = f"Limit @ ${float(order['limit_price']):,.4f}"
            elif order_type == "stop":
                order_text = f"Stop @ ${float(order['stop_price']):,.4f}"
            else:
                order_text = "Market"
            hours = "PRE + regular" if str(order.get("execution_session") or "regular") == "extended" else "Regular"
            evaluation = str(order.get("rejection_reason") or order.get("last_evaluation") or "Awaiting evaluation")
            values.append([
                order["symbol"],
                str(order["side"]).title(),
                order_text,
                f"{hours} · {str(order['tif']).upper()}",
                format_share_quantity(order["quantity"]),
                str(order["status"]).title(),
                evaluation,
                self._p32_format_time(order["submitted_at"]),
                order["id"],
            ])
        self._p32_fill_table(
            self.p32_orders_table,
            values,
            on_complete=lambda: (self._p32_update_cancel_button(), self._p32_update_order_detail()),
        )

    def _p32_update_cancel_button(self) -> None:
        selected = self.p32_orders_table.currentRow()
        status_item = self.p32_orders_table.item(selected, 5) if selected >= 0 else None
        self.p32_cancel_order_btn.setEnabled(bool(status_item and status_item.text() == "Pending"))

    def _p32_update_order_detail(self) -> None:
        row = self.p32_orders_table.currentRow()
        order_id_item = self.p32_orders_table.item(row, 8) if row >= 0 else None
        if order_id_item is None:
            self.p32_order_detail_label.setText(
                "Select an order to inspect its price, expiry, and latest engine decision."
            )
            return
        try:
            order = self._p32_store.get_order(order_id_item.text())
        except Exception:
            self.p32_order_detail_label.setText("Order details are no longer available.")
            return
        expires = self._p32_format_time(order.get("expires_at")) if order.get("expires_at") else "Until canceled"
        session = "Pre-market + regular" if str(order.get("execution_session") or "regular") == "extended" else "Regular market"
        price = "Market"
        if order.get("limit_price"):
            price = f"Limit ${float(order['limit_price']):,.4f}"
        elif order.get("stop_price"):
            price = f"Stop ${float(order['stop_price']):,.4f}"
        decision = str(order.get("rejection_reason") or order.get("last_evaluation") or "Awaiting evaluation")
        self.p32_order_detail_label.setText(
            f"{order['id'][:8]} · {price} · {session} · {str(order['tif']).upper()} · "
            f"Expires: {expires} · {decision}"
        )

    def _p32_refresh_fills(self, rows: Any = None) -> None:
        if rows is None:
            self._p32_refresh_all()
            return
        values = [[
            fill["symbol"],
            str(fill["side"]).title(),
            format_share_quantity(fill["quantity"]),
            f"${float(fill['fill_price']):,.4f}",
            f"${float(fill['realized_pnl_delta']):,.2f}",
            self._p32_format_time(fill["filled_at"]),
        ] for fill in rows]
        self._p32_fill_table(self.p32_fills_table, values)

    def _p32_fill_table(
        self,
        table: QTableWidget,
        rows: list[list[str]],
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        table_key = id(table)
        generation = self._p32_table_render_generations.get(table_key, 0) + 1
        self._p32_table_render_generations[table_key] = generation
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
            current = generation == self._p32_table_render_generations.get(table_key)
            visible = self._p32_page_is_visible()
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

        if not self._p32_has_window_refresh_runtime():
            _prepare()
            try:
                for row_index, values in enumerate(rows):
                    _apply(row_index, values)
            finally:
                _finish()
            return

        run_batched(
            self,
            ('virtual-table', table_key),
            list(rows),
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            is_current=lambda value: value == self._p32_table_render_generations.get(table_key),
            is_visible=self._p32_page_is_visible,
        )

    @staticmethod
    def _p32_parse_utc_time(value: Any) -> dt.datetime | None:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)

    @staticmethod
    def _p32_format_time(value: Any) -> str:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
            return parsed.strftime("%b %d, %H:%M")
        except (TypeError, ValueError):
            return str(value or "")

    def _p32_repolish(self, widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _apply_virtual_trading_theme(self) -> None:
        if not hasattr(self, "page32"):
            return
        text = self.theme_color("text_primary")
        secondary = self.theme_color("text_secondary")
        muted = self.theme_color("text_muted")
        panel = self.theme_color("panel_background")
        chart = self.theme_color("chart_bg")
        border = self.theme_color("panel_border")
        negative = self.theme_color("accent_negative")
        self.page32.setStyleSheet(f"""
            QWidget#virtualTradingPage {{ color: {text}; }}
            QLabel#virtualPageTitle {{ font-size: 27px; font-weight: 700; color: {text}; }}
            QLabel#virtualBadge {{ background: {self._P32_ACCENT}; color: #061b0b; border-radius: 8px;
                font-size: 9px; font-weight: 800; padding: 3px 8px; }}
            QFrame#virtualHero, QFrame#virtualBuyingPower, QFrame#virtualOrderCard, QFrame#virtualEmptyState {{
                background: {panel}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#virtualSymbolChart {{ background: {chart}; border: 1px solid {border}; border-radius: 8px; }}
            QGroupBox#virtualAccountSettings {{ border: 1px solid {border}; border-radius: 8px;
                margin-top: 8px; padding: 9px; font-weight: 650; color: {text}; }}
            QGroupBox#virtualAccountSettings::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QLabel#virtualSectionHeading, QLabel#virtualEmptyTitle {{ font-size: 17px; font-weight: 700; color: {text}; }}
            QLabel#virtualEquity {{ font-size: 31px; font-weight: 650; color: {text}; }}
            QLabel#virtualMetricValue, QLabel#virtualEstimate {{ font-size: 15px; font-weight: 650; color: {text}; }}
            QLabel#virtualChartSymbol, QLabel#virtualChartPrice {{ color: {text}; font-weight: 700; }}
            QLabel#virtualChartChange[chartState="positive"] {{ color: {self._P32_ACCENT}; font-weight: 700; }}
            QLabel#virtualChartChange[chartState="negative"] {{ color: {negative}; font-weight: 700; }}
            QLabel#virtualChartChange[chartState="flat"] {{ color: {secondary}; font-weight: 700; }}
            QLabel#virtualReturn[returnState="positive"] {{ color: {self._P32_ACCENT}; font-weight: 600; }}
            QLabel#virtualReturn[returnState="negative"] {{ color: {negative}; font-weight: 600; }}
            QLabel#virtualReturn[returnState="flat"] {{ color: {secondary}; font-weight: 600; }}
            QLabel#virtualMarketBadge {{ color: {muted}; border: 1px solid {border}; border-radius: 9px; padding: 3px 8px; }}
            QLabel#virtualEmptyIcon {{ background: {self._P32_ACCENT}; color: #061b0b; border-radius: 26px;
                font-size: 24px; font-weight: 800; min-width: 52px; max-width: 52px; min-height: 52px; max-height: 52px; }}
            QPushButton#virtualPrimaryButton {{ background: {self._P32_ACCENT}; color: #061b0b; border: none;
                border-radius: 8px; padding: 9px 14px; font-weight: 750; }}
            QPushButton#virtualPrimaryButton:hover {{ background: #00e20b; }}
            QPushButton#virtualPrimaryButton:disabled {{ background: {border}; color: {muted}; }}
            QPushButton[virtualRole="secondary"] {{ background: transparent; border: 1px solid {border};
                border-radius: 7px; padding: 6px 10px; color: {text}; }}
            QPushButton[virtualRole="side"] {{ background: transparent; border: 1px solid {border};
                padding: 8px; font-weight: 650; }}
            QPushButton[virtualRole="side"]:checked {{ background: {self._P32_ACCENT}; color: #061b0b; border-color: {self._P32_ACCENT}; }}
            QPushButton[virtualRole="range"] {{ background: transparent; border: none; color: {muted};
                padding: 4px 6px; font-weight: 650; }}
            QPushButton[virtualRole="range"]:checked {{ color: {self._P32_ACCENT}; border-bottom: 2px solid {self._P32_ACCENT}; }}
            QPushButton[virtualRole="chartRange"] {{ background: transparent; border: none; color: {muted};
                padding: 2px 1px; font-size: 10px; font-weight: 650; }}
            QPushButton[virtualRole="chartRange"]:checked {{ color: {self._P32_ACCENT}; border-bottom: 2px solid {self._P32_ACCENT}; }}
            QFrame#virtualDivider {{ color: {border}; }}
            QTabWidget#virtualTabs::pane {{ border: 1px solid {border}; border-radius: 9px; top: -1px; }}
            QTabWidget#virtualTabs QTabBar::tab:selected {{ color: {self._P32_ACCENT}; }}
        """)
        if hasattr(self, "p32_performance_plot"):
            self.p32_performance_plot.setBackground(chart)
            self._p32_refresh_performance()
        if hasattr(self, "p32_symbol_chart_plot"):
            self.p32_symbol_chart_plot.setBackground(chart)
            right_axis = self.p32_symbol_chart_plot.getPlotItem().getAxis("right")
            bottom_axis = self.p32_symbol_chart_plot.getPlotItem().getAxis("bottom")
            right_axis.setTextPen(self.theme_color("chart_axis"))
            bottom_axis.setTextPen(self.theme_color("chart_axis"))
            right_axis.setWidth(52)
            if self._p32_chart_frame is not None:
                self._p32_render_symbol_chart()
