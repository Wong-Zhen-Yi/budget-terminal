from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtWidgets import QProgressBar

from ..compat import *
from ..services.quant import QuantAnalyticsService, QuantScanPayload
from ..widgets.table_render import render_table_rows
from ..workers.quant import QuantScanWorker
from . import quant_presenters as presenters

#: The ticker payload must not live on ``Qt.ItemDataRole.UserRole``: that role is the sort payload
#: for ``widgets/table_render``, so a cell carrying both would have its ticker read back as a
#: sort value (or vice versa) the moment the column gained a sort key.
_P41_TICKER_ROLE = Qt.ItemDataRole.UserRole + 1
_P41_PAIR_ROLE = Qt.ItemDataRole.UserRole + 2

_P41_SCAN_KEY = ("quant", "scan")
_P41_PAIR_KEY = ("quant", "pair")

_P41_MAX_WORKERS = 2

_P41_METRICS = (
    ("ranked", "Ranked"),
    ("universe", "Universe"),
    ("pairs", "Pairs"),
    ("stationary", "Stationary"),
    ("leader", "Top composite"),
    ("errors", "Data errors"),
)

_P41_SCREEN_COLUMN_WIDTHS = (52, 74, 84, 70, 70, 70, 74, 68, 68, 82, 74, 60, 84)
_P41_PAIR_COLUMN_WIDTHS = (52, 70, 70, 62, 70, 76, 78, 62, 70, 86, 66)


class QuantPageMixin:
    """Statistical screener and pairs (stat-arb) lab.

    The page sources its own liquid US-equity universe and never reads portfolio state, so both
    sub-tabs populate without any ticker input from the user.
    """

    # ------------------------------------------------------------------ controller

    def _p41_get_service(self) -> QuantAnalyticsService:
        service = getattr(self, "_p41_service", None)
        if service is None:
            service = QuantAnalyticsService(self._get_cache_manager())
            self._p41_service = service
        return service

    def _p41_get_executor(self) -> ThreadPoolExecutor:
        executor = getattr(self, "_p41_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=_P41_MAX_WORKERS)
            self._p41_executor = executor
        return executor

    def _p41_get_refresh_coordinator(self) -> Any:
        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is None:
            from budget_terminal_app.services.refresh_control import RefreshCoordinator

            coordinator = RefreshCoordinator()
            self._refresh_coordinator = coordinator
        return coordinator

    def _p41_page_is_visible(self) -> bool:
        page = getattr(self, "page41", None)
        if page is None or not hasattr(self, "_is_current_page"):
            return False
        try:
            return bool(self._is_current_page(page))
        except Exception:
            return False

    def _p41_stop_controller(self) -> None:
        """Release threads and the single-flight slot at shutdown."""

        self._p41_cancel_active_scan()
        thread = getattr(self, "_p41_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)
        executor = getattr(self, "_p41_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
            self._p41_executor = None
        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is not None:
            coordinator.cancel(_P41_SCAN_KEY)
            coordinator.cancel(_P41_PAIR_KEY)
        self._p41_scan_contexts = {}

    def _p41_cancel_active_scan(self) -> None:
        worker = getattr(self, "_p41_worker", None)
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()

    # ------------------------------------------------------------------ page construction

    def init_page41(self) -> None:
        settings = load_quant_page_settings()
        self._p41_settings = settings
        self._p41_service = None
        self._p41_worker = None
        self._p41_thread = None
        self._p41_scan_contexts: dict[int, dict[str, Any]] = {}
        self._p41_active_token: Any = None
        self._p41_render_pending = False
        self._p41_pending_error = ""
        self._p41_pair_detail: dict[str, Any] | None = None
        self._p41_pair_request = 0
        self._p41_payload = self._p41_get_service().load_latest_payload()

        layout = QVBoxLayout(self.page41)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("<b>Quant</b>")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel(
            "Sources its own liquid US universe, ranks it on cross-sectional factors, and hunts "
            "mean-reverting pairs. Decision support only."
        )
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_theme_role(subtitle, "status_muted")
        heading.addWidget(title)
        heading.addSpacing(10)
        heading.addWidget(subtitle, 1)
        layout.addLayout(heading)

        layout.addWidget(self._p41_build_controls())
        layout.addWidget(self._p41_build_metric_strip())

        self.p41_progress = QProgressBar()
        self.p41_progress.setRange(0, 1)
        self.p41_progress.setValue(0)
        self.p41_progress.setMaximumHeight(18)
        self.p41_progress.setVisible(False)
        layout.addWidget(self.p41_progress)

        self.p41_tabs = QTabWidget()
        self.p41_tabs.setDocumentMode(True)
        self.p41_screener_tab = self._p41_build_screener_tab(settings)
        self.p41_pairs_tab = self._p41_build_pairs_tab(settings)
        self.p41_tabs.addTab(self.p41_screener_tab, "Screener")
        self.p41_tabs.addTab(self.p41_pairs_tab, "Pairs")
        if str(settings.get("active_tab", "screener")) == "pairs":
            self.p41_tabs.setCurrentWidget(self.p41_pairs_tab)
        self.p41_tabs.currentChanged.connect(self._p41_on_subtab_changed)
        layout.addWidget(self.p41_tabs, 1)

        self._p41_render_payload()
        text, status = presenters.describe_scan_freshness(self._p41_payload)
        self._p41_update_status(text, status)

    def _p41_build_controls(self) -> Any:
        controls = QFrame()
        self.set_theme_role(controls, "panel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(8)

        self.p41_refresh_btn = QPushButton("Run scan")
        self.set_theme_variant(self.p41_refresh_btn, "accent")
        self.p41_refresh_btn.setToolTip(
            "Source the universe (cached for the session) and recompute every factor and pair."
        )
        self.p41_refresh_btn.clicked.connect(self._p41_manual_refresh)
        controls_layout.addWidget(self.p41_refresh_btn)

        self.p41_force_btn = QPushButton("Force universe refresh")
        self.p41_force_btn.setToolTip(
            "Re-screen the universe from scratch, ignoring the cached shortlist. Slower and more "
            "likely to be rate limited."
        )
        self.p41_force_btn.clicked.connect(self._p41_force_refresh)
        controls_layout.addWidget(self.p41_force_btn)

        self.p41_export_llm_btn = QPushButton("Export to LLM")
        self.set_theme_variant(self.p41_export_llm_btn, "positive")
        self.p41_export_llm_btn.setToolTip(
            "Copy the currently visible screener and pair rows to the clipboard as markdown."
        )
        self.p41_export_llm_btn.clicked.connect(self._p41_export_for_llm)
        controls_layout.addWidget(self.p41_export_llm_btn)

        controls_layout.addStretch(1)

        self.p41_status_lbl = QLabel("Ready")
        self.p41_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p41_status_lbl, "status_muted")
        controls_layout.addWidget(self.p41_status_lbl, 1)
        return controls

    def _p41_build_metric_strip(self) -> Any:
        strip = QFrame()
        self.set_theme_role(strip, "panel")
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(10, 6, 10, 6)
        strip_layout.setSpacing(18)
        self.p41_metric_labels: dict[str, Any] = {}
        for key, label_text in _P41_METRICS:
            cell = QVBoxLayout()
            cell.setSpacing(0)
            caption = QLabel(label_text)
            self.set_theme_role(caption, "muted")
            value = QLabel("—")
            self.set_theme_role(value, "metric")
            cell.addWidget(caption)
            cell.addWidget(value)
            strip_layout.addLayout(cell)
            self.p41_metric_labels[key] = value
        strip_layout.addStretch(1)
        return strip

    def _p41_build_screener_tab(self, settings: Any) -> Any:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 8, 0, 0)
        tab_layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel("Filter"))
        self.p41_screen_filter = QComboBox()
        for label, value in presenters.SCREEN_FILTERS:
            self.p41_screen_filter.addItem(label, value)
        saved = self.p41_screen_filter.findData(str(settings.get("screen_filter", "all")))
        if saved >= 0:
            self.p41_screen_filter.setCurrentIndex(saved)
        self.p41_screen_filter.currentIndexChanged.connect(self._p41_on_screen_filter_changed)
        filters.addWidget(self.p41_screen_filter)

        filters.addWidget(QLabel("Search"))
        self.p41_search_input = QLineEdit()
        self.p41_search_input.setPlaceholderText("Ticker")
        self.p41_search_input.setFixedWidth(110)
        self.p41_search_input.setText(str(settings.get("search", "")))
        self.p41_search_input.textChanged.connect(self._p41_on_search_changed)
        filters.addWidget(self.p41_search_input)
        filters.addStretch(1)

        methodology = QLabel(
            "Universe: US common stocks · price ≥ $5 · market cap ≥ $2B · 20-session median dollar "
            "volume ≥ $20M. Composite is a cross-sectional percentile: 50% momentum (3/6/12M), "
            "30% Sharpe, 20% low volatility."
        )
        methodology.setWordWrap(True)
        self.set_theme_role(methodology, "status_muted")

        self.p41_screen_table = self._p41_new_table(
            presenters.SCREEN_HEADERS,
            _P41_SCREEN_COLUMN_WIDTHS,
        )
        tab_layout.addLayout(filters)
        tab_layout.addWidget(methodology)
        tab_layout.addWidget(self.p41_screen_table, 1)
        return tab

    def _p41_build_pairs_tab(self, settings: Any) -> Any:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 8, 0, 0)
        tab_layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Filter"))
        self.p41_pair_filter = QComboBox()
        for label, value in presenters.PAIR_FILTERS:
            self.p41_pair_filter.addItem(label, value)
        saved = self.p41_pair_filter.findData(str(settings.get("pair_filter", "all")))
        if saved >= 0:
            self.p41_pair_filter.setCurrentIndex(saved)
        self.p41_pair_filter.currentIndexChanged.connect(self._p41_on_pair_filter_changed)
        controls.addWidget(self.p41_pair_filter)

        controls.addSpacing(12)
        controls.addWidget(QLabel("Inspect pair"))
        self.p41_pair_left_input = QLineEdit(str(settings.get("pair_left", "")))
        self.p41_pair_left_input.setPlaceholderText("Long")
        self.p41_pair_left_input.setFixedWidth(80)
        self.p41_pair_left_input.returnPressed.connect(self._p41_analyze_manual_pair)
        controls.addWidget(self.p41_pair_left_input)
        self.p41_pair_right_input = QLineEdit(str(settings.get("pair_right", "")))
        self.p41_pair_right_input.setPlaceholderText("Short")
        self.p41_pair_right_input.setFixedWidth(80)
        self.p41_pair_right_input.returnPressed.connect(self._p41_analyze_manual_pair)
        controls.addWidget(self.p41_pair_right_input)
        self.p41_pair_analyze_btn = QPushButton("Analyse")
        self.p41_pair_analyze_btn.setToolTip("Model any two tickers, independently of the discovered list.")
        self.p41_pair_analyze_btn.clicked.connect(self._p41_analyze_manual_pair)
        controls.addWidget(self.p41_pair_analyze_btn)
        controls.addStretch(1)
        tab_layout.addLayout(controls)

        methodology = QLabel(
            "Pairs are prescreened by return correlation, then the spread is fitted by OLS on price "
            "levels and tested for mean reversion. Because many pairs are tested at once, roughly "
            "1 in 20 will clear the 5% Dickey-Fuller threshold by chance — treat a stationary "
            "verdict as a shortlist, not a conclusion, and weigh it against correlation and "
            "half-life."
        )
        methodology.setWordWrap(True)
        self.set_theme_role(methodology, "status_muted")
        tab_layout.addWidget(methodology)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.p41_pair_table = self._p41_new_table(presenters.PAIR_HEADERS, _P41_PAIR_COLUMN_WIDTHS)
        self.p41_pair_table.itemSelectionChanged.connect(self._p41_on_pair_selected)
        splitter.addWidget(self.p41_pair_table)
        splitter.addWidget(self._p41_build_pair_detail_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([760, 520])
        tab_layout.addWidget(splitter, 1)
        return tab

    def _p41_build_pair_detail_panel(self) -> Any:
        panel = QFrame()
        self.set_theme_role(panel, "panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        self.p41_pair_title = QLabel("Select a pair")
        self.set_theme_role(self.p41_pair_title, "section_title")
        panel_layout.addWidget(self.p41_pair_title)

        self.p41_spread_axis = DateAxisItem(orientation="bottom")
        self.p41_spread_plot = pg.PlotWidget(axisItems={"bottom": self.p41_spread_axis})
        self.p41_spread_plot.getPlotItem().setMenuEnabled(False)
        self.p41_spread_plot.getPlotItem().hideAxis("left")
        self.p41_spread_plot.getPlotItem().showAxis("right")
        self.p41_spread_plot.setMinimumHeight(150)
        panel_layout.addWidget(self.p41_spread_plot, 3)

        self.p41_indexed_axis = DateAxisItem(orientation="bottom")
        self.p41_indexed_percent_axis = PercentAxisItem(orientation="right")
        self.p41_indexed_plot = pg.PlotWidget(
            axisItems={"bottom": self.p41_indexed_axis, "right": self.p41_indexed_percent_axis}
        )
        self.p41_indexed_plot.getPlotItem().setMenuEnabled(False)
        self.p41_indexed_plot.getPlotItem().hideAxis("left")
        self.p41_indexed_plot.getPlotItem().showAxis("right")
        self.p41_indexed_plot.setMinimumHeight(130)
        panel_layout.addWidget(self.p41_indexed_plot, 2)

        self.p41_pair_detail_text = QPlainTextEdit()
        self.p41_pair_detail_text.setReadOnly(True)
        self.p41_pair_detail_text.setMinimumHeight(120)
        panel_layout.addWidget(self.p41_pair_detail_text, 2)
        return panel

    def _p41_new_table(self, headers: Any, widths: Any) -> Any:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setMinimumHeight(28)
        for column in range(len(headers) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        table.setSortingEnabled(True)
        # Qt defaults the sort indicator to column 0 *descending*, which would open both tables
        # with the worst-ranked row on top. Rank ascending is the meaningful default here.
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        return table

    # ------------------------------------------------------------------ sub-tabs

    def _p41_active_subtab_key(self) -> str:
        if not hasattr(self, "p41_tabs"):
            return "screener"
        current = self.p41_tabs.currentWidget()
        if current is getattr(self, "p41_pairs_tab", None):
            return "pairs"
        return "screener"

    def _p41_on_subtab_changed(self, _index: Any = None) -> None:
        self._p41_persist_settings()
        self._p41_sync_status_bar()

    # ------------------------------------------------------------------ settings

    def _p41_persist_settings(self) -> None:
        if not hasattr(self, "p41_tabs"):
            return
        payload = {
            "active_tab": self._p41_active_subtab_key(),
            "screen_filter": str(self.p41_screen_filter.currentData() or "all"),
            "pair_filter": str(self.p41_pair_filter.currentData() or "all"),
            "search": self.p41_search_input.text(),
            "pair_left": self.p41_pair_left_input.text(),
            "pair_right": self.p41_pair_right_input.text(),
        }
        try:
            self._p41_settings = save_quant_page_settings(payload)
        except Exception:
            logger.debug("Quant page settings could not be persisted", exc_info=True)

    def _p41_on_screen_filter_changed(self, _index: Any = None) -> None:
        self._p41_persist_settings()
        self._p41_render_screen_table()

    def _p41_on_pair_filter_changed(self, _index: Any = None) -> None:
        self._p41_persist_settings()
        self._p41_render_pairs_table()

    def _p41_on_search_changed(self, _text: Any = None) -> None:
        self._p41_persist_settings()
        self._p41_render_screen_table()

    # ------------------------------------------------------------------ scanning

    def _p41_manual_refresh(self) -> None:
        self._p41_request_scan(force_universe_refresh=False)

    def _p41_force_refresh(self) -> None:
        self._p41_request_scan(force_universe_refresh=True)

    def _p41_refresh_screen(self, *, force: bool = False) -> None:
        """Refresh entry point for the Screener sub-tab."""

        self._p41_request_scan(force_universe_refresh=bool(force))

    def _p41_refresh_pairs(self, *, force: bool = False) -> None:
        """Refresh entry point for the Pairs sub-tab.

        A typed pair is a deliberate override, so re-resolve that rather than discarding it for a
        whole universe rescan.
        """

        left = str(self.p41_pair_left_input.text() or "").upper().strip() if hasattr(self, "p41_pair_left_input") else ""
        right = (
            str(self.p41_pair_right_input.text() or "").upper().strip()
            if hasattr(self, "p41_pair_right_input")
            else ""
        )
        if left and right:
            self._p41_analyze_manual_pair()
            return
        self._p41_request_scan(force_universe_refresh=bool(force))

    def _p41_request_scan(self, *, force_universe_refresh: bool = False) -> bool:
        if getattr(self, "_refresh_shutdown", False):
            return False
        coordinator = self._p41_get_refresh_coordinator()
        signature = (bool(force_universe_refresh),)
        token, should_start = coordinator.request(_P41_SCAN_KEY, signature)
        context = {"force_universe_refresh": bool(force_universe_refresh)}
        contexts = getattr(self, "_p41_scan_contexts", {})
        contexts[token.generation] = context
        retained = {
            item.generation
            for item in (coordinator.active_token(_P41_SCAN_KEY), coordinator.pending_token(_P41_SCAN_KEY))
            if item is not None
        }
        self._p41_scan_contexts = {key: value for key, value in contexts.items() if key in retained}
        if not should_start:
            # A newer request replaces any queued one, so the latest click always wins instead of
            # being refused outright.
            self._p41_update_status("Scan queued; it will start when the current one finishes.", "info")
            return False
        return self._p41_launch_scan(token, context)

    def _p41_launch_scan(self, token: Any, context: dict[str, Any]) -> bool:
        worker = QuantScanWorker(
            self._p41_get_service(),
            force_universe_refresh=bool(context.get("force_universe_refresh")),
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._p41_on_scan_progress)
        self._connect_worker_signal(worker.finished, self._p41_on_scan_ready, token)
        self._connect_worker_signal(worker.error, self._p41_on_scan_error, token)
        self._connect_worker_signal(worker.cancelled, self._p41_on_scan_cancelled, token)
        for signal in (worker.finished, worker.error, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._connect_worker_signal(thread.finished, self._p41_cleanup_worker, worker, thread)
        self._p41_worker = worker
        self._p41_thread = thread
        self._p41_active_token = token
        self._p41_set_busy(True)
        self._p41_update_status("Sourcing universe and computing factors…", "warning")
        thread.start()
        return True

    def _p41_cleanup_worker(self, worker: Any, thread: Any) -> None:
        if getattr(self, "_p41_worker", None) is worker:
            self._p41_worker = None
        if getattr(self, "_p41_thread", None) is thread:
            self._p41_thread = None

    def _p41_set_busy(self, busy: bool) -> None:
        if hasattr(self, "p41_refresh_btn"):
            self.p41_refresh_btn.setEnabled(not busy)
            self.p41_refresh_btn.setText("Scanning…" if busy else "Run scan")
        if hasattr(self, "p41_force_btn"):
            self.p41_force_btn.setEnabled(not busy)
        if hasattr(self, "p41_progress"):
            self.p41_progress.setVisible(busy)
            if busy:
                self.p41_progress.setRange(0, 0)
                self.p41_progress.setFormat("Sourcing universe…")

    def _p41_on_scan_progress(self, completed: int, total: int, ticker: str) -> None:
        if not hasattr(self, "p41_progress") or getattr(self, "_refresh_shutdown", False):
            return
        bound = max(int(total), 1)
        self.p41_progress.setRange(0, bound)
        self.p41_progress.setValue(min(max(int(completed), 0), bound))
        self.p41_progress.setFormat(f"{completed}/{total} — {ticker}")

    def _p41_finish_scan(self, token: Any) -> None:
        """Release the single-flight slot and start whatever was queued behind it."""

        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is None:
            return
        contexts = getattr(self, "_p41_scan_contexts", {})
        contexts.pop(getattr(token, "generation", None), None)
        next_token = coordinator.complete(token)
        if next_token is not None:
            next_context = contexts.get(next_token.generation)
            if isinstance(next_context, dict):
                self._p41_launch_scan(next_token, next_context)
                return
            coordinator.complete(next_token)
        self._p41_active_token = None
        self._p41_set_busy(False)

    def _p41_on_scan_ready(self, token: Any, payload: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        coordinator = getattr(self, "_refresh_coordinator", None)
        try:
            accepted = coordinator is None or coordinator.is_active(token)
            if accepted and isinstance(payload, QuantScanPayload):
                self._p41_payload = payload
                self._p41_record_health(payload)
            current = coordinator is None or coordinator.is_current(token)
            if accepted and current:
                self._p41_publish_results()
        except RuntimeError:
            return
        finally:
            self._p41_finish_scan(token)

    def _p41_publish_results(self) -> None:
        """Render and announce a completed scan, deferring both if the page is not on screen."""

        if not self._p41_page_is_visible():
            self._p41_render_pending = True
            return
        self._p41_render_payload()
        text, status = presenters.describe_scan_freshness(self._p41_payload)
        self._p41_update_status(text, status)

    def _p41_on_scan_error(self, token: Any, message: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        coordinator = getattr(self, "_refresh_coordinator", None)
        try:
            if coordinator is None or coordinator.is_current(token):
                text = f"Scan failed: {message}"
                if self._p41_page_is_visible():
                    self._p41_update_status(text, "negative")
                else:
                    self._p41_pending_error = str(message)
            if hasattr(self, "_record_data_health_exception"):
                self._record_data_health_exception("Quant", message)
        except RuntimeError:
            return
        finally:
            self._p41_finish_scan(token)

    def _p41_on_scan_cancelled(self, token: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        try:
            self._p41_update_status("Scan cancelled.", "muted")
        except RuntimeError:
            return
        finally:
            self._p41_finish_scan(token)

    def _p41_record_health(self, payload: QuantScanPayload) -> None:
        if not hasattr(self, "_record_data_health_event"):
            return
        errors = dict(payload.errors or {})
        if not errors:
            return
        try:
            self._record_data_health_event(
                "Quant",
                f"{len(errors)} ticker(s) returned incomplete daily history.",
                severity="issue",
                symbols=sorted(errors),
            )
        except Exception:
            logger.debug("Quant data-health reporting failed", exc_info=True)

    # ------------------------------------------------------------------ pair detail

    def _p41_analyze_manual_pair(self) -> None:
        left = str(self.p41_pair_left_input.text() or "").upper().strip()
        right = str(self.p41_pair_right_input.text() or "").upper().strip()
        self.p41_pair_left_input.setText(left)
        self.p41_pair_right_input.setText(right)
        self._p41_persist_settings()
        self._p41_load_pair(left, right)

    def _p41_load_pair(self, left: str, right: str) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        if not left or not right:
            self._p41_update_status("Enter two ticker symbols to inspect a pair.", "warning")
            return
        if left == right:
            self._p41_update_status("Choose two different ticker symbols.", "warning")
            return
        self._p41_pair_request = int(getattr(self, "_p41_pair_request", 0)) + 1
        request_id = self._p41_pair_request
        service = self._p41_get_service()
        self._p41_update_status(f"Modelling {left} / {right}…", "warning")

        def _run() -> None:
            try:
                detail = service.analyze_pair(left, right)
                message = ""
            except Exception as exc:
                detail = None
                message = str(exc)
            self._invoke_main.emit(
                lambda result=detail, error=message, rid=request_id: self._p41_on_pair_ready(rid, result, error)
            )

        self._p41_get_executor().submit(_run)

    def _p41_on_pair_ready(self, request_id: int, detail: Any, error: str) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        # A newer request supersedes this one; dropping it keeps the panel matching the inputs.
        if int(request_id) != int(getattr(self, "_p41_pair_request", 0)):
            return
        if error or not isinstance(detail, dict):
            if self._p41_page_is_visible():
                self._p41_update_status(f"Pair analysis failed: {error}", "negative")
            else:
                self._p41_pending_error = error
            return
        self._p41_pair_detail = detail
        if not self._p41_page_is_visible():
            self._p41_render_pending = True
            return
        self._p41_render_pair_detail()
        self._p41_update_status(
            f"{detail['left']} / {detail['right']} modelled over {detail['observations']} sessions.",
            "positive",
        )

    def _p41_on_pair_selected(self) -> None:
        table = getattr(self, "p41_pair_table", None)
        if table is None:
            return
        items = table.selectedItems()
        if not items:
            return
        payload = table.item(items[0].row(), 1)
        value = payload.data(_P41_PAIR_ROLE) if payload is not None else None
        if not value or "/" not in str(value):
            return
        left, right = str(value).split("/", 1)
        self.p41_pair_left_input.setText(left)
        self.p41_pair_right_input.setText(right)
        self._p41_load_pair(left, right)

    def _p41_render_pair_detail(self) -> None:
        detail = getattr(self, "_p41_pair_detail", None)
        if not isinstance(detail, dict) or not hasattr(self, "p41_spread_plot"):
            return
        self.p41_pair_title.setText(f"{detail['left']} / {detail['right']}")
        spread_z = detail.get("spread_z")
        self.p41_spread_plot.clear()
        if spread_z is not None:
            series = spread_z.dropna()
            if not series.empty:
                self.p41_spread_axis.set_dates(list(series.index), "1d")
                positions = list(range(len(series)))
                self.p41_spread_plot.plot(
                    positions,
                    [float(value) for value in series],
                    pen=self.theme_pen("accent", width=2),
                )
                for level, token in ((0.0, "chart_reference"), (2.0, "warning"), (-2.0, "warning")):
                    line = pg.InfiniteLine(
                        pos=level,
                        angle=0,
                        pen=self.theme_pen(token, width=1, style=Qt.PenStyle.DashLine),
                    )
                    self.p41_spread_plot.addItem(line)
        indexed = detail.get("indexed")
        self.p41_indexed_plot.clear()
        if indexed is not None and not indexed.empty:
            self.p41_indexed_axis.set_dates(list(indexed.index), "1d")
            positions = list(range(len(indexed)))
            for offset, column in enumerate(("left", "right")):
                if column not in indexed.columns:
                    continue
                self.p41_indexed_plot.plot(
                    positions,
                    [float(value) - 100.0 for value in indexed[column]],
                    pen=pg.mkPen(self.theme_series_color(offset), width=2),
                )
        self.p41_pair_detail_text.setPlainText("\n".join(presenters.build_pair_detail_lines(detail)))

    # ------------------------------------------------------------------ rendering

    def _p41_theme_colors(self) -> dict[str, str]:
        return {
            "positive": self.theme_color("accent_positive"),
            "negative": self.theme_color("accent_negative"),
            "warning": self.theme_color("warning"),
            "secondary": self.theme_color("text_secondary"),
            "accent": self.theme_color("accent"),
        }

    def _p41_visible_screen_rows(self) -> list[Any]:
        payload = getattr(self, "_p41_payload", None)
        rows = list(payload.rows) if payload is not None else []
        key = str(self.p41_screen_filter.currentData() or "all") if hasattr(self, "p41_screen_filter") else "all"
        rows = presenters.filter_screen_rows(rows, key)
        search = str(self.p41_search_input.text() or "").upper().strip() if hasattr(self, "p41_search_input") else ""
        if search:
            rows = [row for row in rows if search in row.ticker]
        return rows

    def _p41_visible_pair_rows(self) -> list[Any]:
        payload = getattr(self, "_p41_payload", None)
        rows = list(payload.pairs) if payload is not None else []
        key = str(self.p41_pair_filter.currentData() or "all") if hasattr(self, "p41_pair_filter") else "all"
        return presenters.filter_pair_rows(rows, key)

    def _p41_render_screen_table(self) -> None:
        if not hasattr(self, "p41_screen_table"):
            return
        rows = presenters.build_screen_rows(
            self._p41_visible_screen_rows(),
            colors=self._p41_theme_colors(),
            ticker_role=_P41_TICKER_ROLE,
        )
        render_table_rows(self.p41_screen_table, rows)

    def _p41_render_pairs_table(self) -> None:
        if not hasattr(self, "p41_pair_table"):
            return
        table = self.p41_pair_table
        blocked = table.blockSignals(True)
        try:
            rows = presenters.build_pair_rows(
                self._p41_visible_pair_rows(),
                colors=self._p41_theme_colors(),
                pair_role=_P41_PAIR_ROLE,
            )
            render_table_rows(table, rows)
        finally:
            table.blockSignals(blocked)

    def _p41_render_payload(self) -> None:
        if not hasattr(self, "p41_screen_table"):
            return
        self._p41_render_screen_table()
        self._p41_render_pairs_table()
        self._p41_render_pair_detail()
        metrics = presenters.summarize_metrics(getattr(self, "_p41_payload", None))
        for key, label in getattr(self, "p41_metric_labels", {}).items():
            label.setText(metrics.get(key, "—"))

    # ------------------------------------------------------------------ export

    def _p41_build_llm_export(self) -> str:
        screen_filter = getattr(self, "p41_screen_filter", None)
        pair_filter = getattr(self, "p41_pair_filter", None)
        search_input = getattr(self, "p41_search_input", None)
        return presenters.build_llm_export(
            getattr(self, "_p41_payload", None),
            screen_rows=self._p41_visible_screen_rows(),
            pair_rows=self._p41_visible_pair_rows(),
            screen_filter_label=screen_filter.currentText() if screen_filter is not None else "All ranked",
            pair_filter_label=pair_filter.currentText() if pair_filter is not None else "All pairs",
            search=str(search_input.text() or "").strip() if search_input is not None else "",
            pair_detail=getattr(self, "_p41_pair_detail", None),
        )

    def _p41_export_for_llm(self) -> None:
        payload = getattr(self, "_p41_payload", None)
        if payload is None or not payload.rows:
            self._p41_update_status("Run a scan before exporting.", "warning")
            return
        try:
            QApplication.clipboard().setText(self._p41_build_llm_export())
        except Exception as exc:
            self._p41_update_status(f"Export failed: {exc}", "negative")
            QMessageBox.critical(self, "Export Failed", f"Unable to copy the Quant scan to the clipboard.\n\n{exc}")
            return
        self._p41_update_status(
            f"Copied {len(self._p41_visible_screen_rows())} screener row(s) and "
            f"{len(self._p41_visible_pair_rows())} pair(s) to the clipboard.",
            "positive",
        )

    # ------------------------------------------------------------------ status

    def _p41_update_status(self, text: str, status: str) -> None:
        if hasattr(self, "p41_status_lbl"):
            self.set_status_text(self.p41_status_lbl, text, status=status)
        # Only the visible page owns the shared status bar.
        if hasattr(self, "status_bar") and self._p41_page_is_visible():
            self.set_status_text(self.status_bar, text, status=status)

    def _p41_sync_status_bar(self) -> None:
        if hasattr(self, "status_bar") and hasattr(self, "p41_status_lbl"):
            self.set_status_text(
                self.status_bar,
                self.p41_status_lbl.text(),
                status=str(self.p41_status_lbl.property("bt_status") or "muted"),
            )

    # ------------------------------------------------------------------ hooks

    def _p41_on_show(self) -> None:
        if getattr(self, "_p41_render_pending", False):
            self._p41_render_pending = False
            self._p41_render_payload()
            text, status = presenters.describe_scan_freshness(getattr(self, "_p41_payload", None))
            self._p41_update_status(text, status)
        else:
            self._p41_render_payload()
        pending_error = str(getattr(self, "_p41_pending_error", "") or "")
        if pending_error:
            self._p41_pending_error = ""
            self._p41_update_status(f"Scan failed: {pending_error}", "negative")
        self._p41_sync_status_bar()

    def _apply_quant_theme(self) -> None:
        if not hasattr(self, "p41_screen_table"):
            return
        for name in ("p41_spread_plot", "p41_indexed_plot"):
            plot = getattr(self, name, None)
            if plot is not None:
                self.style_plot_widget(plot)
        # Row colours are baked into the items, so a theme change has to rebuild them.
        self._p41_render_payload()
        if hasattr(self, "p41_status_lbl"):
            self.set_status_text(
                self.p41_status_lbl,
                self.p41_status_lbl.text(),
                status=str(self.p41_status_lbl.property("bt_status") or "muted"),
            )
