from __future__ import annotations

import datetime as dt
import math
from typing import Any

from PyQt6.QtWidgets import QProgressBar

from ..compat import *
from ..paper_trading.engine import PaperTradingEngine
from ..services.automatic_signal_scanner import (
    AutoTickerCandidate,
    AutomaticSignalScanPayload,
    AutomaticSignalScannerService,
)
from ..services.signal_models import SignalClass, SignalResult, TradeStatus
from ..table_cells import TableCell
from ..widgets.table_render import render_table_rows
from ..workers.automatic_signal_scanner import AutomaticSignalScannerWorker


_P40_HEADERS = (
    "Rank",
    "Ticker",
    "Price",
    "Market Cap",
    "20D $ Volume",
    "Score",
    "Signal",
    "Trade Status",
)
_P40_SIGNAL_RANK = {
    SignalClass.NONE: 0,
    SignalClass.WATCH: 1,
    SignalClass.LONG: 2,
    SignalClass.STRONG_LONG: 3,
}


class SignalScanner2PageMixin:
    """Manual liquid-leader scanner for the Signals page."""

    def _p40_initialize_controller(self) -> None:
        self._p40_service = AutomaticSignalScannerService(self._get_cache_manager())
        self._p40_payload = self._p40_service.load_latest_payload()
        self._p40_scanning = False
        self._p40_worker = None
        self._p40_thread = None
        self._p40_last_session = None
        self._p40_alert_states: dict[str, SignalClass] = {}

    def _p40_stop_controller(self) -> None:
        thread = getattr(self, "_p40_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)

    def _p40_market_session(self) -> Any:
        now = dt.datetime.now(dt.timezone.utc)
        return PaperTradingEngine._resolve_us_session(now)

    def _p40_launch_scan(self, *, force_market_refresh: bool = False) -> bool:
        if self._p40_scanning:
            self._p40_update_status("A scan is already running.", "warning")
            return False
        if getattr(self, "_refresh_shutdown", False):
            return False
        worker = AutomaticSignalScannerWorker(
            self._p40_service,
            force_market_refresh=force_market_refresh,
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._p40_on_scan_progress)
        worker.finished.connect(self._p40_on_scan_ready)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(self._p40_on_scan_error)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda w=worker, t=thread: self._p40_cleanup_worker(w, t))
        self._p40_worker = worker
        self._p40_thread = thread
        self._p40_scanning = True
        if hasattr(self, "p40_refresh_btn"):
            self.p40_refresh_btn.setEnabled(False)
            self.p40_progress.setRange(0, 0)
            self.p40_progress.setFormat("Sourcing liquid US equities…")
        self._p40_update_status("Sourcing and ranking liquid US equities…", "warning")
        thread.start()
        return True

    def _p40_cleanup_worker(self, worker: Any, thread: Any) -> None:
        if getattr(self, "_p40_worker", None) is worker:
            self._p40_worker = None
        if getattr(self, "_p40_thread", None) is thread:
            self._p40_thread = None

    def _p40_on_scan_progress(self, completed: int, total: int, ticker: str) -> None:
        if not hasattr(self, "p40_progress"):
            return
        self.p40_progress.setRange(0, max(int(total), 1))
        self.p40_progress.setValue(min(max(int(completed), 0), max(int(total), 1)))
        self.p40_progress.setFormat(f"{completed}/{total} — {ticker}")

    def _p40_on_scan_ready(self, payload: Any) -> None:
        self._p40_scanning = False
        if isinstance(payload, AutomaticSignalScanPayload):
            self._p40_payload = payload
            self._p40_process_signal_transitions(payload.results)
        if hasattr(self, "p40_refresh_btn"):
            self.p40_refresh_btn.setEnabled(True)
            self._p40_render_payload()
        status = self._p40_ready_status_text()
        status_kind = "warning" if self._p40_payload and self._p40_payload.errors else "positive"
        self._p40_update_status(status, status_kind)
        if hasattr(self, "status_bar"):
            self.set_status_text(self.status_bar, status, status=status_kind)

    def _p40_on_scan_error(self, message: Any) -> None:
        self._p40_scanning = False
        if hasattr(self, "p40_refresh_btn"):
            self.p40_refresh_btn.setEnabled(True)
            self.p40_progress.setRange(0, 1)
            self.p40_progress.setValue(0)
            self.p40_progress.setFormat("Scan failed")
        self._p40_update_status(f"Scan failed: {message}", "negative")

    def _p40_ready_status_text(self) -> str:
        payload = self._p40_payload
        if payload is None:
            return "Waiting for the next US market session."
        completed = payload.completed_at.strftime("%H:%M:%S")
        text = f"Last scan {completed} · {len(payload.results)} ticker(s) · {payload.source}"
        if payload.errors:
            text += f" · {len(payload.errors)} data error(s)"
        if not bool(getattr(self._p40_last_session, "is_open", False)):
            text += " · latest regular-session bars"
        return text

    def _p40_update_status(self, text: str, status: str) -> None:
        if hasattr(self, "p40_status_lbl"):
            self.set_status_text(self.p40_status_lbl, text, status=status)
        if hasattr(self, "p40_market_lbl"):
            session = getattr(self, "_p40_last_session", None)
            label = "US MARKET OPEN" if bool(getattr(session, "is_open", False)) else "US MARKET CLOSED"
            self.set_status_text(
                self.p40_market_lbl,
                label,
                status="positive" if bool(getattr(session, "is_open", False)) else "muted",
            )

    def _p40_process_signal_transitions(self, results: list[SignalResult]) -> None:
        for result in results:
            previous = self._p40_alert_states.get(result.ticker)
            self._p40_alert_states[result.ticker] = result.signal
            if previous is None:
                continue
            if (
                result.trade_status is TradeStatus.VALID_LONG
                and _P40_SIGNAL_RANK.get(result.signal, 0) > _P40_SIGNAL_RANK.get(previous, 0)
                and _P40_SIGNAL_RANK.get(result.signal, 0) >= _P40_SIGNAL_RANK[SignalClass.LONG]
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

    def init_page40(self) -> None:
        layout = QVBoxLayout(self.page40)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("<b>Signals</b>")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel(
            "Sources liquid US leaders on demand, then applies Daily → Hourly → 5-minute → 1-minute analysis. Decision support only."
        )
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_theme_role(subtitle, "status_muted")
        heading.addWidget(title)
        heading.addSpacing(10)
        heading.addWidget(subtitle, 1)
        layout.addLayout(heading)

        controls = QFrame()
        self.set_theme_role(controls, "panel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(8)
        self.p40_market_lbl = QLabel("US MARKET —")
        controls_layout.addWidget(self.p40_market_lbl)
        self.p40_refresh_btn = QPushButton("Refresh now")
        self.set_theme_variant(self.p40_refresh_btn, "accent")
        self.p40_refresh_btn.clicked.connect(self._p40_manual_refresh)
        controls_layout.addWidget(self.p40_refresh_btn)
        self.p40_filter_combo = QComboBox()
        for label, value in (
            ("All signals", "all"),
            ("Strong only", "strong"),
            ("Long setups", "long"),
            ("Watch", "watch"),
            ("Data errors", "error"),
        ):
            self.p40_filter_combo.addItem(label, value)
        self.p40_filter_combo.currentIndexChanged.connect(self._p40_render_payload)
        controls_layout.addWidget(self.p40_filter_combo)
        self.p40_search_input = QLineEdit()
        self.p40_search_input.setPlaceholderText("Search ticker")
        self.p40_search_input.setMaximumWidth(150)
        self.p40_search_input.textChanged.connect(self._p40_render_payload)
        controls_layout.addWidget(self.p40_search_input)
        self.p40_status_lbl = QLabel(self._p40_ready_status_text())
        self.p40_status_lbl.setMinimumWidth(0)
        self.p40_status_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.p40_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_layout.addWidget(self.p40_status_lbl, 1)
        layout.addWidget(controls)

        methodology = QLabel(
            "Universe: US common stocks · price ≥ $5 · market cap ≥ $2B · 20-session median dollar volume ≥ $20M · top 25 by liquidity · manual refresh only"
        )
        methodology.setWordWrap(True)
        self.set_theme_role(methodology, "status_muted")
        layout.addWidget(methodology)
        self.p40_universe_lbl = QLabel(self._p40_universe_status_text())
        self.p40_universe_lbl.setWordWrap(True)
        self.set_theme_role(self.p40_universe_lbl, "status_muted")
        layout.addWidget(self.p40_universe_lbl)

        self.p40_progress = QProgressBar()
        self.p40_progress.setRange(0, 1)
        self.p40_progress.setValue(0)
        self.p40_progress.setFormat("Click Refresh now to scan")
        self.p40_progress.setMaximumHeight(18)
        layout.addWidget(self.p40_progress)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.p40_table = self._p40_build_table()
        splitter.addWidget(self.p40_table)
        splitter.addWidget(self._p40_build_detail_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([820, 460])
        layout.addWidget(splitter, 1)
        self._p40_render_payload()
        self._p40_update_status(self._p40_ready_status_text(), "muted" if self._p40_payload is None else "positive")

    def _p40_build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_P40_HEADERS))
        table.setHorizontalHeaderLabels(list(_P40_HEADERS))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setMinimumHeight(28)
        for column in range(len(_P40_HEADERS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((52, 72, 82, 96, 112, 66, 112)):
            table.setColumnWidth(column, width)
        table.setSortingEnabled(True)
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

        self.p40_indicators_text = QPlainTextEdit()
        self.p40_indicators_text.setReadOnly(True)
        self.p40_indicators_text.setMinimumHeight(145)
        detail.addWidget(QLabel("Indicator values"))
        detail.addWidget(self.p40_indicators_text)
        self.p40_reasons_text = QPlainTextEdit()
        self.p40_reasons_text.setReadOnly(True)
        self.p40_reasons_text.setMinimumHeight(170)
        detail.addWidget(QLabel("Why this ticker was selected"))
        detail.addWidget(self.p40_reasons_text)
        self.p40_warnings_text = QPlainTextEdit()
        self.p40_warnings_text.setReadOnly(True)
        self.p40_warnings_text.setMinimumHeight(100)
        detail.addWidget(QLabel("Warnings and data health"))
        detail.addWidget(self.p40_warnings_text)
        detail.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _p40_manual_refresh(self) -> None:
        try:
            session = self._p40_market_session()
        except Exception as exc:
            self._p40_update_status(f"Market session unavailable: {exc}", "warning")
            return
        self._p40_last_session = session
        self._p40_launch_scan(force_market_refresh=True)

    def _p40_result_visible(self, result: SignalResult) -> bool:
        search = self.p40_search_input.text().upper().strip()
        if search and search not in result.ticker:
            return False
        selected = self.p40_filter_combo.currentData()
        if selected == "strong":
            return result.signal is SignalClass.STRONG_LONG
        if selected == "long":
            return result.signal in {SignalClass.LONG, SignalClass.STRONG_LONG}
        if selected == "watch":
            return result.signal is SignalClass.WATCH
        if selected == "error":
            return result.trade_status is TradeStatus.DATA_ERROR
        return True

    def _p40_render_payload(self, *_: Any) -> None:
        if not hasattr(self, "p40_table"):
            return
        payload = self._p40_payload
        self.p40_universe_lbl.setText(self._p40_universe_status_text())
        if payload is None:
            self.p40_table.setRowCount(0)
            self._p40_render_detail(None, None)
            return
        candidates = {candidate.ticker: candidate for candidate in payload.candidates}
        visible = [result for result in payload.results if self._p40_result_visible(result)]
        rows = [self._p40_table_row(candidates.get(result.ticker), result) for result in visible]
        render_table_rows(self.p40_table, rows)
        if self.p40_table.rowCount():
            self.p40_table.selectRow(0)
            self._p40_selection_changed()
        else:
            self._p40_render_detail(None, None)
        if payload.results:
            self.p40_progress.setRange(0, len(payload.results))
            self.p40_progress.setValue(len(payload.results))
            self.p40_progress.setFormat(self._p40_ready_status_text())

    def _p40_universe_status_text(self) -> str:
        payload = self._p40_payload
        if payload is None:
            return "Universe has not been sourced yet. Click Refresh now to run a scan."
        cache_label = "cached universe" if payload.universe_from_cache else "live universe refresh"
        return (
            f"Universe refreshed {payload.sourced_at.strftime('%Y-%m-%d %H:%M:%S')} · "
            f"{payload.source_candidate_count} sourced · {len(payload.candidates)} shortlisted · "
            f"{payload.rejected_candidate_count} rejected · {cache_label}"
        )

    def _p40_table_row(
        self,
        candidate: AutoTickerCandidate | None,
        result: SignalResult,
    ) -> tuple[TableCell, ...]:
        rank = candidate.quality_rank if candidate else 999
        market_cap = candidate.market_cap if candidate else None
        dollar_volume = candidate.median_dollar_volume if candidate else None
        price = result.price if result.price is not None and math.isfinite(result.price) else (candidate.price if candidate else None)
        color = self._p40_result_color(result)
        ticker_role = ((Qt.ItemDataRole.UserRole, result.ticker),)
        return (
            TableCell(str(rank) if candidate else "—", alignment="right", sort_value=float(rank)),
            TableCell(result.ticker, foreground=color, data_roles=ticker_role),
            TableCell(f"${price:,.2f}" if price is not None else "—", alignment="right", foreground=color, sort_value=price),
            TableCell(self._p40_compact_money(market_cap), alignment="right", sort_value=market_cap),
            TableCell(self._p40_compact_money(dollar_volume), alignment="right", sort_value=dollar_volume),
            TableCell(self._p40_score_text(result.raw_score, result.max_score), alignment="right", foreground=color, sort_value=result.raw_score),
            TableCell(result.signal_label, foreground=color, sort_value=float(_P40_SIGNAL_RANK.get(result.signal, 0))),
            TableCell(result.trade_status_label, foreground=color, tooltip=result.error or "\n".join(result.warnings)),
        )

    def _p40_selection_changed(self) -> None:
        row = self.p40_table.currentRow()
        if row < 0 or self._p40_payload is None:
            return
        ticker_item = self.p40_table.item(row, 1)
        if ticker_item is None:
            return
        ticker = ticker_item.data(Qt.ItemDataRole.UserRole)
        if not ticker:
            ticker = ticker_item.text()
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
            self.p40_detail_summary.setText("Click Refresh now to scan, then select a result.")
            self.p40_score_table.setRowCount(0)
            self.p40_indicators_text.clear()
            self.p40_reasons_text.clear()
            self.p40_warnings_text.clear()
            return
        price_text = f"${result.price:,.2f}" if result.price is not None else "Price unavailable"
        rank_text = f"Quality rank #{candidate.quality_rank}" if candidate else "Quality rank unavailable"
        self.p40_detail_ticker.setText(f"{result.ticker} · {price_text}")
        summary = (
            f"{rank_text} · Technical signal {result.signal_label} · "
            f"Score {self._p40_score_text(result.raw_score, result.max_score)}\n"
            f"Final trade status: {result.trade_status_label}"
        )
        self.set_status_text(
            self.p40_detail_summary,
            summary,
            status="negative" if result.trade_status is TradeStatus.DATA_ERROR else "warning" if result.trade_status is TradeStatus.TOO_EXTENDED else "positive" if result.trade_status is TradeStatus.VALID_LONG else "muted",
        )
        components = (
            ("Trend", result.trend_score, result.trend_max_score, "Daily direction"),
            ("Momentum", result.momentum_score, result.momentum_max_score, "Hourly structure"),
            ("Volume", result.volume_score, result.volume_max_score, "5-minute confirmation"),
            ("Entry", result.entry_score, result.entry_max_score, "5-minute breakout + 1-minute VWAP"),
        )
        self.p40_score_table.setRowCount(len(components))
        for row, (name, score, maximum, evidence) in enumerate(components):
            self.p40_score_table.setItem(row, 0, QTableWidgetItem(name))
            self.p40_score_table.setItem(row, 1, QTableWidgetItem(self._p40_score_text(score, maximum)))
            self.p40_score_table.setItem(row, 2, QTableWidgetItem(evidence))
        indicator_names = (
            ("EMA20", "ema20", "$"),
            ("EMA50", "ema50", "$"),
            ("EMA200", "ema200", "$"),
            ("RSI", "rsi", ""),
            ("MACD", "macd", ""),
            ("MACD signal", "macd_signal", ""),
            ("MACD histogram", "macd_histogram", ""),
            ("VWAP", "vwap", "$"),
            ("VWAP distance", "vwap_distance_pct", "%"),
            ("Relative volume", "relative_volume", "x"),
            ("Prior 20-bar high", "breakout_level", "$"),
        )
        indicator_lines = []
        for label, key, unit in indicator_names:
            value = result.indicators.get(key)
            try:
                numeric = float(value)
                text = f"${numeric:,.2f}" if unit == "$" else f"{numeric:,.2f}{unit}"
            except (TypeError, ValueError):
                text = "Unavailable"
            indicator_lines.append(f"{label}: {text}")
        self.p40_indicators_text.setPlainText("\n".join(indicator_lines))
        quality_lines = [f"✓ {reason}" for reason in (candidate.reasons if candidate else ())]
        signal_lines = [
            f"{'✓' if reason.passed else '○'} {reason.name} ({'+' + format(reason.points, 'g') if reason.passed else '+0'})\n   {reason.description}"
            for reason in result.reasons
        ]
        self.p40_reasons_text.setPlainText("\n".join(quality_lines + ([""] if quality_lines else []) + signal_lines))
        timeframe_lines = [f"{role.title()}: {status}" for role, status in result.timeframe_status.items()]
        warning_lines = [*(f"⚠ {item}" for item in result.warnings), "", *timeframe_lines]
        self.p40_warnings_text.setPlainText("\n".join(warning_lines).strip() or "No warnings.")

    def _p40_on_show(self) -> None:
        self._p40_render_payload()
        self._p40_update_status(self._p40_ready_status_text(), "muted" if self._p40_payload is None else "positive")

    def _apply_signal_scanner2_theme(self) -> None:
        if hasattr(self, "p40_detail_summary") and self._p40_payload is not None:
            self._p40_selection_changed()

    @staticmethod
    def _p40_score_text(score: float, maximum: float) -> str:
        def display(value: float) -> str:
            return str(int(value)) if float(value).is_integer() else f"{value:.1f}"

        return f"{display(score)}/{display(maximum)}"

    @staticmethod
    def _p40_compact_money(value: float | None) -> str:
        if value is None or not math.isfinite(float(value)):
            return "—"
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        return f"${value:,.0f}"

    def _p40_result_color(self, result: SignalResult) -> str:
        if result.trade_status is TradeStatus.DATA_ERROR:
            return self.theme_color("accent_negative")
        if result.trade_status is TradeStatus.TOO_EXTENDED:
            return self.theme_color("warning")
        if result.signal in {SignalClass.LONG, SignalClass.STRONG_LONG}:
            return self.theme_color("accent_positive")
        if result.signal is SignalClass.WATCH:
            return self.theme_color("warning")
        return self.theme_color("text_secondary")
