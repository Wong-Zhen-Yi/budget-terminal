from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtWidgets import QProgressBar

from ..compat import *
from ..paper_trading.engine import PaperTradingEngine
from ..services.automatic_signal_scanner import (
    AutoTickerCandidate,
    AutomaticSignalScanPayload,
    AutomaticSignalScannerService,
)
from ..services.signal_models import SignalClass, SignalResult, TradeStatus
from ..widgets.table_render import render_table_rows
from ..workers.automatic_signal_scanner import AutomaticSignalScannerWorker
from . import signals_presenters as presenters

#: The ticker payload must not live on ``Qt.ItemDataRole.UserRole``: that role is the sort payload
#: for ``widgets/table_render``, so a cell carrying both would have its ticker read back as a
#: sort value (or vice versa) the moment the column gained a sort key.
_P40_TICKER_ROLE = Qt.ItemDataRole.UserRole + 1

_P40_REFRESH_KEY = ("signals", "scan")

_P40_FILTERS = (
    ("All signals", "all"),
    ("Strong only", "strong"),
    ("Long setups", "long"),
    ("Watch", "watch"),
    ("Blocked (extended)", "blocked"),
    ("Too new to score", "too_new"),
    ("Data errors", "error"),
)

_P40_METRICS = (
    ("shortlisted", "Shortlisted"),
    ("valid_long", "Valid longs"),
    ("blocked", "Blocked"),
    ("watch", "Watch"),
    ("too_new", "Too new"),
    ("errors", "Data errors"),
    ("scan_age", "Last scan"),
)


class SignalScanner2PageMixin:
    """Manual liquid-leader scanner for the Signals page."""

    def _p40_initialize_controller(self) -> None:
        self._p40_service = AutomaticSignalScannerService(self._get_cache_manager())
        self._p40_payload = self._p40_service.load_latest_payload()
        self._p40_worker = None
        self._p40_thread = None
        self._p40_last_session = None
        self._p40_session_resolved = False
        self._p40_session_executor: Any = None
        self._p40_alert_states: dict[str, SignalClass] = {}
        self._p40_scan_contexts: dict[int, dict[str, Any]] = {}
        self._p40_active_token: Any = None
        self._p40_render_pending = False
        self._p40_pending_error = ""
        self._p40_settings = load_signals_page_settings()

    # ------------------------------------------------------------------ lifecycle

    def _p40_stop_controller(self) -> None:
        self._p40_cancel_active_scan()
        thread = getattr(self, "_p40_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)
        executor = getattr(self, "_p40_session_executor", None)
        if executor is not None:
            executor.shutdown(wait=False)
            self._p40_session_executor = None
        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is not None:
            coordinator.cancel(_P40_REFRESH_KEY)
        self._p40_scan_contexts = {}

    def _p40_cancel_active_scan(self) -> None:
        worker = getattr(self, "_p40_worker", None)
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()

    def _p40_get_refresh_coordinator(self) -> Any:
        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is None:
            from budget_terminal_app.services.refresh_control import RefreshCoordinator

            coordinator = RefreshCoordinator()
            self._refresh_coordinator = coordinator
        return coordinator

    def _p40_page_is_visible(self) -> bool:
        page = getattr(self, "page40", None)
        if page is None or not hasattr(self, "_is_current_page"):
            return False
        try:
            return bool(self._is_current_page(page))
        except Exception:
            return False

    # ------------------------------------------------------------------ market session

    def _p40_market_session(self) -> Any:
        now = dt.datetime.now(dt.timezone.utc)
        return PaperTradingEngine._resolve_us_session(now)

    def _p40_resolve_session_async(self) -> None:
        """Resolve the NYSE session off the UI thread.

        ``_resolve_us_session`` imports ``pandas_market_calendars`` and builds a multi-day schedule,
        which is far too slow to run while painting the page.
        """

        if getattr(self, "_p40_session_resolved", False):
            return
        if getattr(self, "_p40_session_executor", None) is None:
            self._p40_session_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="p40-session")

        def _resolve() -> None:
            try:
                session = self._p40_market_session()
            except Exception as exc:
                logger.info("Signals market session unavailable: %s", exc)
                session = None
            try:
                self._invoke_main.emit(lambda value=session: self._p40_apply_session(value))
            except RuntimeError:
                return

        try:
            self._p40_session_executor.submit(_resolve)
        except RuntimeError:
            return

    def _p40_apply_session(self, session: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        self._p40_last_session = session
        self._p40_session_resolved = session is not None
        self._p40_update_market_label()

    def _p40_update_market_label(self) -> None:
        if not hasattr(self, "p40_market_lbl"):
            return
        session = getattr(self, "_p40_last_session", None)
        if not getattr(self, "_p40_session_resolved", False) or session is None:
            # Never claim the market is closed just because the calendar has not answered yet.
            self.set_status_text(self.p40_market_lbl, "US MARKET —", status="muted")
            return
        is_open = bool(getattr(session, "is_open", False))
        self.set_status_text(
            self.p40_market_lbl,
            "US MARKET OPEN" if is_open else "US MARKET CLOSED",
            status="positive" if is_open else "muted",
        )

    # ------------------------------------------------------------------ scanning

    def _p40_request_scan(self, *, force_market_refresh: bool = False, force_universe_refresh: bool = False) -> bool:
        if getattr(self, "_refresh_shutdown", False):
            return False
        coordinator = self._p40_get_refresh_coordinator()
        signature = (bool(force_market_refresh), bool(force_universe_refresh))
        token, should_start = coordinator.request(_P40_REFRESH_KEY, signature)
        context = {
            "force_market_refresh": bool(force_market_refresh),
            "force_universe_refresh": bool(force_universe_refresh),
        }
        contexts = getattr(self, "_p40_scan_contexts", {})
        contexts[token.generation] = context
        retained = {
            item.generation
            for item in (coordinator.active_token(_P40_REFRESH_KEY), coordinator.pending_token(_P40_REFRESH_KEY))
            if item is not None
        }
        self._p40_scan_contexts = {key: value for key, value in contexts.items() if key in retained}
        if not should_start:
            # A newer request replaces any queued one, so the latest click always wins instead of
            # being refused outright.
            self._p40_update_status("Scan queued; it will start when the current one finishes.", "info")
            return False
        return self._p40_launch_scan(token, context)

    def _p40_launch_scan(self, token: Any, context: dict[str, Any]) -> bool:
        worker = AutomaticSignalScannerWorker(
            self._p40_service,
            force_market_refresh=bool(context.get("force_market_refresh")),
            force_universe_refresh=bool(context.get("force_universe_refresh")),
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._p40_on_scan_progress)
        worker.finished.connect(lambda payload, item=token: self._p40_on_scan_ready(item, payload))
        worker.error.connect(lambda message, item=token: self._p40_on_scan_error(item, message))
        worker.cancelled.connect(lambda item=token: self._p40_on_scan_cancelled(item))
        for signal in (worker.finished, worker.error, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda w=worker, t=thread: self._p40_cleanup_worker(w, t))
        self._p40_worker = worker
        self._p40_thread = thread
        self._p40_active_token = token
        self._p40_set_busy(True)
        self._p40_update_status("Sourcing and ranking liquid US equities…", "warning")
        thread.start()
        return True

    def _p40_cleanup_worker(self, worker: Any, thread: Any) -> None:
        if getattr(self, "_p40_worker", None) is worker:
            self._p40_worker = None
        if getattr(self, "_p40_thread", None) is thread:
            self._p40_thread = None

    def _p40_set_busy(self, busy: bool) -> None:
        if hasattr(self, "p40_refresh_btn"):
            self.p40_refresh_btn.setEnabled(not busy)
            self.p40_refresh_btn.setText("Refreshing…" if busy else "Refresh now")
        if hasattr(self, "p40_force_btn"):
            self.p40_force_btn.setEnabled(not busy)
        if hasattr(self, "p40_progress"):
            self.p40_progress.setVisible(busy)
            if busy:
                self.p40_progress.setRange(0, 0)
                self.p40_progress.setFormat("Sourcing liquid US equities…")

    def _p40_on_scan_progress(self, completed: int, total: int, ticker: str) -> None:
        if not hasattr(self, "p40_progress") or getattr(self, "_refresh_shutdown", False):
            return
        bound = max(int(total), 1)
        self.p40_progress.setRange(0, bound)
        self.p40_progress.setValue(min(max(int(completed), 0), bound))
        self.p40_progress.setFormat(f"{completed}/{total} — {ticker}")

    def _p40_finish_scan(self, token: Any) -> None:
        """Release the single-flight slot and start whatever was queued behind it."""

        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is None:
            return
        contexts = getattr(self, "_p40_scan_contexts", {})
        contexts.pop(getattr(token, "generation", None), None)
        next_token = coordinator.complete(token)
        if next_token is not None:
            next_context = contexts.get(next_token.generation)
            if isinstance(next_context, dict):
                self._p40_launch_scan(next_token, next_context)
                return
            coordinator.complete(next_token)
        self._p40_active_token = None
        self._p40_set_busy(False)

    def _p40_on_scan_ready(self, token: Any, payload: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        coordinator = getattr(self, "_refresh_coordinator", None)
        try:
            accepted = coordinator is None or coordinator.is_active(token)
            if accepted and isinstance(payload, AutomaticSignalScanPayload):
                self._p40_payload = payload
                self._p40_process_signal_transitions(payload.results)
                self._p40_record_health(payload)
            current = coordinator is None or coordinator.is_current(token)
            if accepted and current:
                self._p40_publish_results()
        except RuntimeError:
            return
        finally:
            self._p40_finish_scan(token)

    def _p40_publish_results(self) -> None:
        """Render and announce a completed scan, deferring both if the page is not on screen."""

        if not self._p40_page_is_visible():
            self._p40_render_pending = True
            return
        self._p40_render_payload()
        text, status = presenters.describe_scan_freshness(self._p40_payload)
        self._p40_update_status(text, status)

    def _p40_on_scan_error(self, token: Any, message: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        coordinator = getattr(self, "_refresh_coordinator", None)
        try:
            if coordinator is None or coordinator.is_current(token):
                text = f"Scan failed: {message}"
                if self._p40_page_is_visible():
                    self._p40_update_status(text, "negative")
                else:
                    self._p40_pending_error = str(message)
            if hasattr(self, "_record_data_health_exception"):
                self._record_data_health_exception("Signals", message)
        except RuntimeError:
            return
        finally:
            self._p40_finish_scan(token)

    def _p40_on_scan_cancelled(self, token: Any) -> None:
        if getattr(self, "_refresh_shutdown", False):
            return
        try:
            self._p40_update_status("Scan cancelled.", "muted")
        except RuntimeError:
            return
        finally:
            self._p40_finish_scan(token)

    def _p40_record_health(self, payload: AutomaticSignalScanPayload) -> None:
        if not hasattr(self, "_record_data_health_event"):
            return
        errors = dict(payload.errors or {})
        if not errors:
            return
        try:
            self._record_data_health_event(
                "Signals",
                f"{len(errors)} ticker(s) returned incomplete market data.",
                severity="issue",
                symbols=sorted(errors),
            )
        except Exception:
            logger.debug("Signals data-health reporting failed", exc_info=True)

    # ------------------------------------------------------------------ status

    def _p40_update_status(self, text: str, status: str) -> None:
        if hasattr(self, "p40_status_lbl"):
            self.set_status_text(self.p40_status_lbl, text, status=status)
        # Only the visible page owns the shared status bar.
        if hasattr(self, "status_bar") and self._p40_page_is_visible():
            self.set_status_text(self.status_bar, text, status=status)
        self._p40_update_market_label()

    def _p40_sync_status_bar(self) -> None:
        if hasattr(self, "status_bar") and hasattr(self, "p40_status_lbl"):
            self.set_status_text(
                self.status_bar,
                self.p40_status_lbl.text(),
                status=str(self.p40_status_lbl.property("bt_status") or "muted"),
            )

    def _p40_process_signal_transitions(self, results: list[SignalResult]) -> None:
        for result in results:
            previous = self._p40_alert_states.get(result.ticker)
            self._p40_alert_states[result.ticker] = result.signal
            if previous is None:
                continue
            if (
                result.trade_status is TradeStatus.VALID_LONG
                and presenters.SIGNAL_RANK.get(result.signal, 0) > presenters.SIGNAL_RANK.get(previous, 0)
                and presenters.SIGNAL_RANK.get(result.signal, 0) >= presenters.SIGNAL_RANK[SignalClass.LONG]
            ):
                self.on_signal2_generated(result)

    def on_signal2_generated(self, result: SignalResult) -> None:
        """Future alert-service seam; this page never submits orders."""

        logger.info(
            "Signals transition: %s %s %.1f/%.1f",
            result.ticker,
            result.signal.value,
            result.raw_score,
            result.max_score,
        )

    # ------------------------------------------------------------------ page construction

    def init_page40(self) -> None:
        settings = getattr(self, "_p40_settings", None) or load_signals_page_settings()
        self._p40_settings = settings
        layout = QVBoxLayout(self.page40)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("<b>Signals</b>")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel(
            "Sources liquid US leaders on demand, then applies Daily → Hourly → 5-minute → 1-minute analysis. "
            "Decision support only."
        )
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_theme_role(subtitle, "status_muted")
        heading.addWidget(title)
        heading.addSpacing(10)
        heading.addWidget(subtitle, 1)
        layout.addLayout(heading)

        layout.addWidget(self._p40_build_controls(settings))
        layout.addWidget(self._p40_build_metric_strip())

        methodology = QLabel(
            "Universe: US common stocks · price ≥ $5 · market cap ≥ $2B · 20-session median dollar volume ≥ $20M "
            "· top 25 by liquidity. Context timeframes score the last closed bar; entry uses the live bar."
        )
        methodology.setWordWrap(True)
        self.set_theme_role(methodology, "status_muted")
        layout.addWidget(methodology)
        self.p40_universe_lbl = QLabel(presenters.describe_universe(self._p40_payload))
        self.p40_universe_lbl.setWordWrap(True)
        self.set_theme_role(self.p40_universe_lbl, "status_muted")
        layout.addWidget(self.p40_universe_lbl)

        self.p40_progress = QProgressBar()
        self.p40_progress.setRange(0, 1)
        self.p40_progress.setValue(0)
        self.p40_progress.setMaximumHeight(18)
        self.p40_progress.setVisible(False)
        layout.addWidget(self.p40_progress)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._p40_build_table_panel())
        splitter.addWidget(self._p40_build_detail_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([820, 460])
        layout.addWidget(splitter, 1)

        self._p40_search_timer = QTimer(self.page40)
        self._p40_search_timer.setSingleShot(True)
        self._p40_search_timer.setInterval(200)
        self._p40_search_timer.timeout.connect(self._p40_apply_search)

        self._p40_render_payload()
        text, status = presenters.describe_scan_freshness(self._p40_payload)
        self._p40_update_status(text, status)
        self._p40_resolve_session_async()

    def _p40_build_controls(self, settings: Any) -> QFrame:
        controls = QFrame()
        self.set_theme_role(controls, "panel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(8)

        self.p40_market_lbl = QLabel("US MARKET —")
        controls_layout.addWidget(self.p40_market_lbl)

        self.p40_refresh_btn = QPushButton("Refresh now")
        self.set_theme_variant(self.p40_refresh_btn, "accent")
        self.p40_refresh_btn.setToolTip(
            "Rescan using cached bars where they are still within their timeframe's freshness window."
        )
        self.p40_refresh_btn.clicked.connect(self._p40_manual_refresh)
        controls_layout.addWidget(self.p40_refresh_btn)

        self.p40_force_btn = QPushButton("Force full re-download")
        self.p40_force_btn.setToolTip(
            "Re-source the universe and re-download every timeframe, ignoring caches. Slower and more "
            "likely to be rate limited."
        )
        self.p40_force_btn.clicked.connect(self._p40_force_refresh)
        controls_layout.addWidget(self.p40_force_btn)

        self.p40_filter_combo = QComboBox()
        for label, value in _P40_FILTERS:
            self.p40_filter_combo.addItem(label, value)
        saved_filter = self.p40_filter_combo.findData(str(settings.get("filter", "all")))
        if saved_filter >= 0:
            self.p40_filter_combo.setCurrentIndex(saved_filter)
        self.p40_filter_combo.currentIndexChanged.connect(self._p40_filter_changed)
        controls_layout.addWidget(self.p40_filter_combo)

        self.p40_search_input = QLineEdit()
        self.p40_search_input.setPlaceholderText("Search ticker")
        self.p40_search_input.setMaximumWidth(150)
        self.p40_search_input.setText(str(settings.get("search", "")))
        self.p40_search_input.textChanged.connect(self._p40_search_changed)
        controls_layout.addWidget(self.p40_search_input)

        self.p40_status_lbl = QLabel("")
        self.p40_status_lbl.setMinimumWidth(0)
        self.p40_status_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.p40_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_layout.addWidget(self.p40_status_lbl, 1)
        return controls

    def _p40_build_metric_strip(self) -> QFrame:
        panel = QFrame()
        self.set_theme_role(panel, "panel")
        strip = QHBoxLayout(panel)
        strip.setContentsMargins(10, 8, 10, 8)
        strip.setSpacing(16)
        self.p40_metric_labels: dict[str, Any] = {}
        for key, title in _P40_METRICS:
            column = QVBoxLayout()
            column.setSpacing(1)
            caption = QLabel(title)
            self.set_theme_role(caption, "muted")
            value = QLabel("—")
            self.set_theme_role(value, "metric")
            column.addWidget(caption)
            column.addWidget(value)
            strip.addLayout(column)
            self.p40_metric_labels[key] = value
        strip.addStretch(1)
        return panel

    def _p40_build_table_panel(self) -> QWidget:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.p40_table = self._p40_build_table()
        box.addWidget(self.p40_table, 1)
        self.p40_empty_lbl = QLabel("Click Refresh now to scan liquid US leaders.")
        self.p40_empty_lbl.setWordWrap(True)
        self.p40_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(self.p40_empty_lbl, "status_muted")
        box.addWidget(self.p40_empty_lbl)
        return container

    def _p40_build_table(self) -> QTableWidget:
        headers = presenters.SIGNAL_HEADERS
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
        for column, width in enumerate((52, 72, 82, 96, 112, 66, 112)):
            table.setColumnWidth(column, width)
        table.setSortingEnabled(True)
        # Qt defaults the sort indicator to column 0 *descending*, and render_table_rows re-enables
        # sorting after every repopulate, so without this the shortlist opens with the worst-ranked
        # candidate on top.
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        table.itemSelectionChanged.connect(self._p40_selection_changed)
        return table

    def _p40_build_detail_panel(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        detail = QVBoxLayout(content)
        detail.setContentsMargins(10, 4, 4, 4)
        detail.setSpacing(7)
        self.p40_detail_ticker = QLabel("Select a signal result")
        self.set_theme_role(self.p40_detail_ticker, "page_title")
        self.p40_detail_summary = QLabel("Click Refresh now to scan, then select a result.")
        self.p40_detail_summary.setWordWrap(True)
        detail.addWidget(self.p40_detail_ticker)
        detail.addWidget(self.p40_detail_summary)

        self.p40_score_table = QTableWidget(0, 3)
        self.p40_score_table.setHorizontalHeaderLabels(["Component", "Score", "Evidence"])
        self.p40_score_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p40_score_table.verticalHeader().setVisible(False)
        self.p40_score_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.p40_score_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.p40_score_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.p40_score_table.setMaximumHeight(150)
        detail.addWidget(self.p40_score_table)

        for attr, caption, height in (
            ("p40_indicators_text", "Indicator values", 145),
            ("p40_reasons_text", "Why this ticker was selected", 170),
            ("p40_warnings_text", "Bar freshness, warnings and data health", 120),
        ):
            label = QLabel(caption)
            self.set_theme_role(label, "section_title")
            detail.addWidget(label)
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setMinimumHeight(height)
            setattr(self, attr, editor)
            detail.addWidget(editor)
        detail.addStretch(1)
        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------ user actions

    def _p40_manual_refresh(self) -> None:
        self._p40_resolve_session_async()
        self._p40_request_scan(force_market_refresh=False, force_universe_refresh=False)

    def _p40_force_refresh(self) -> None:
        self._p40_resolve_session_async()
        self._p40_request_scan(force_market_refresh=True, force_universe_refresh=True)

    def _p40_filter_changed(self) -> None:
        self._p40_persist_settings()
        self._p40_render_payload()

    def _p40_search_changed(self) -> None:
        timer = getattr(self, "_p40_search_timer", None)
        if timer is None:
            self._p40_apply_search()
            return
        timer.start()

    def _p40_apply_search(self) -> None:
        self._p40_persist_settings()
        self._p40_render_payload()

    def _p40_persist_settings(self) -> None:
        if not hasattr(self, "p40_filter_combo") or not hasattr(self, "p40_search_input"):
            return
        state = {
            "filter": str(self.p40_filter_combo.currentData() or "all"),
            "search": self.p40_search_input.text(),
        }
        try:
            self._p40_settings = save_signals_page_settings(state)
        except Exception:
            logger.debug("Signals page settings could not be persisted", exc_info=True)

    # ------------------------------------------------------------------ rendering

    def _p40_result_visible(self, result: SignalResult) -> bool:
        search = self.p40_search_input.text().upper().strip()
        if search and search not in result.ticker:
            return False
        selected = self.p40_filter_combo.currentData()
        if selected == "strong":
            # Filter on trade status too: a blocked entry is not a tradable strong setup, and
            # listing it under one misrepresents it as actionable.
            return result.signal is SignalClass.STRONG_LONG and result.trade_status is TradeStatus.VALID_LONG
        if selected == "long":
            return result.trade_status is TradeStatus.VALID_LONG
        if selected == "watch":
            return result.trade_status is TradeStatus.WATCH
        if selected == "blocked":
            return result.trade_status is TradeStatus.TOO_EXTENDED
        if selected == "too_new":
            return result.trade_status is TradeStatus.INSUFFICIENT_HISTORY
        if selected == "error":
            return result.trade_status is TradeStatus.DATA_ERROR
        return True

    def _p40_theme_colors(self) -> dict[str, str]:
        return {
            "positive": self.theme_color("accent_positive"),
            "negative": self.theme_color("accent_negative"),
            "warning": self.theme_color("warning"),
            "secondary": self.theme_color("text_secondary"),
        }

    def _p40_selected_ticker(self) -> str:
        table = getattr(self, "p40_table", None)
        if table is None:
            return ""
        row = table.currentRow()
        if row < 0:
            return ""
        item = table.item(row, 1)
        if item is None:
            return ""
        return str(item.data(_P40_TICKER_ROLE) or item.text() or "")

    def _p40_render_payload(self, *_: Any) -> None:
        if not hasattr(self, "p40_table"):
            return
        payload = self._p40_payload
        self.p40_universe_lbl.setText(presenters.describe_universe(payload))
        self._p40_update_metrics()
        if payload is None:
            render_table_rows(self.p40_table, [])
            self._p40_show_empty("No scan yet. Click Refresh now to source and score liquid US leaders.")
            self._p40_render_detail(None, None)
            return

        previous_ticker = self._p40_selected_ticker()
        scrollbar = self.p40_table.verticalScrollBar()
        previous_scroll = scrollbar.value() if scrollbar is not None else 0
        candidates = {candidate.ticker: candidate for candidate in payload.candidates}
        visible = [result for result in payload.results if self._p40_result_visible(result)]
        rows = presenters.build_signal_rows(
            candidates,
            visible,
            colors=self._p40_theme_colors(),
            ticker_role=_P40_TICKER_ROLE,
        )
        render_table_rows(self.p40_table, rows)

        if not rows:
            self._p40_show_empty(
                "No results match this filter."
                if payload.results
                else "The last scan produced no results. Try Force full re-download."
            )
            self._p40_render_detail(None, None)
            return
        self._p40_show_empty("")
        self._p40_restore_selection(previous_ticker, previous_scroll)

    def _p40_restore_selection(self, ticker: str, scroll_value: int) -> None:
        """Keep the user's row (and scroll position) across filter and search re-renders."""

        table = self.p40_table
        target = 0
        if ticker:
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                if item is not None and str(item.data(_P40_TICKER_ROLE) or item.text()) == ticker:
                    target = row
                    break
        table.selectRow(target)
        scrollbar = table.verticalScrollBar()
        if scrollbar is not None and ticker:
            scrollbar.setValue(min(scroll_value, scrollbar.maximum()))
        self._p40_selection_changed()

    def _p40_show_empty(self, message: str) -> None:
        if not hasattr(self, "p40_empty_lbl"):
            return
        self.p40_empty_lbl.setText(message)
        self.p40_empty_lbl.setVisible(bool(message))

    def _p40_update_metrics(self) -> None:
        if not hasattr(self, "p40_metric_labels"):
            return
        payload = self._p40_payload
        if payload is None:
            for label in self.p40_metric_labels.values():
                label.setText("—")
            return
        counts = presenters.summarize_results(payload.results)
        completed = presenters.as_naive_local(getattr(payload, "completed_at", None))
        age = presenters.format_age(dt.datetime.now() - completed) if completed is not None else "—"
        values = {
            "shortlisted": str(len(payload.candidates)),
            "valid_long": str(counts["valid_long"]),
            "blocked": str(counts["blocked"]),
            "watch": str(counts["watch"]),
            "too_new": str(counts["too_new"]),
            "errors": str(counts["errors"]),
            "scan_age": age,
        }
        for key, label in self.p40_metric_labels.items():
            label.setText(values.get(key, "—"))

    def _p40_selection_changed(self) -> None:
        ticker = self._p40_selected_ticker()
        if not ticker or self._p40_payload is None:
            return
        result = next((item for item in self._p40_payload.results if item.ticker == ticker), None)
        candidate = next((item for item in self._p40_payload.candidates if item.ticker == ticker), None)
        self._p40_render_detail(candidate, result)

    def _p40_render_detail(
        self,
        candidate: AutoTickerCandidate | None,
        result: SignalResult | None,
    ) -> None:
        if result is None:
            self.p40_detail_ticker.setText("Select a signal result")
            self.set_status_text(
                self.p40_detail_summary,
                "Click Refresh now to scan, then select a result.",
                status="muted",
            )
            render_table_rows(self.p40_score_table, [])
            self.p40_indicators_text.clear()
            self.p40_reasons_text.clear()
            self.p40_warnings_text.clear()
            return
        price_text = presenters.format_price(result.price)
        rank_text = f"Quality rank #{candidate.quality_rank}" if candidate else "Quality rank unavailable"
        self.p40_detail_ticker.setText(f"{result.ticker} · {price_text}")
        summary = (
            f"{rank_text} · Technical signal {result.signal_label} · "
            f"Score {presenters.format_score(result.raw_score, result.max_score)}\n"
            f"Final trade status: {result.trade_status_label}"
        )
        self.set_status_text(self.p40_detail_summary, summary, status=self._p40_detail_status(result))
        render_table_rows(self.p40_score_table, presenters.build_score_component_rows(result))
        self.p40_indicators_text.setPlainText("\n".join(presenters.build_indicator_lines(result)))
        self.p40_reasons_text.setPlainText("\n".join(presenters.build_reason_lines(candidate, result)))
        self.p40_warnings_text.setPlainText("\n".join(presenters.build_warning_lines(result)).strip())

    @staticmethod
    def _p40_detail_status(result: SignalResult) -> str:
        if result.trade_status is TradeStatus.INSUFFICIENT_HISTORY:
            return "muted"
        if result.trade_status is TradeStatus.DATA_ERROR:
            return "negative"
        if result.trade_status is TradeStatus.TOO_EXTENDED:
            return "warning"
        if result.trade_status is TradeStatus.VALID_LONG:
            return "positive"
        return "muted"

    # ------------------------------------------------------------------ hooks

    def _p40_on_show(self) -> None:
        if getattr(self, "_p40_render_pending", False):
            self._p40_render_pending = False
            self._p40_render_payload()
            text, status = presenters.describe_scan_freshness(self._p40_payload)
            self._p40_update_status(text, status)
        else:
            self._p40_render_payload()
        pending_error = str(getattr(self, "_p40_pending_error", "") or "")
        if pending_error:
            self._p40_pending_error = ""
            self._p40_update_status(f"Scan failed: {pending_error}", "negative")
        elif not getattr(self, "_p40_render_pending", False):
            if not self.p40_status_lbl.text():
                text, status = presenters.describe_scan_freshness(self._p40_payload)
                self._p40_update_status(text, status)
        self._p40_sync_status_bar()
        self._p40_resolve_session_async()

    def _apply_signal_scanner2_theme(self) -> None:
        if not hasattr(self, "p40_table"):
            return
        # Row colours are baked into the items, so a theme change has to rebuild them.
        self._p40_render_payload()
        self._p40_update_market_label()
        if hasattr(self, "p40_status_lbl"):
            self.set_status_text(
                self.p40_status_lbl,
                self.p40_status_lbl.text(),
                status=str(self.p40_status_lbl.property("bt_status") or "muted"),
            )
