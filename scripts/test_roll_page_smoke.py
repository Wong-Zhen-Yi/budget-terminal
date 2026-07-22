from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.compat import *
from budget_terminal_app.mixins.random_recommender import (
    P18_FULL_PAYLOAD_LIMIT,
    RandomRecommenderMixin,
)
from budget_terminal_app.workers.random_recommender import RandomStockWorker


class _RollHarness(RandomRecommenderMixin, QWidget):
    """Build only the Roll page, without the terminal startup or live warmups."""

    def __init__(self) -> None:
        super().__init__()
        self.saved_snapshots: list[dict[str, Any] | None] = []
        self.page18 = QWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page18)
        self.init_page18()

    def set_theme_role(self, widget: Any, role: str | None) -> Any:
        widget.setProperty("bt_role", role)
        return widget

    def set_theme_variant(self, widget: Any, variant: str | None) -> Any:
        widget.setProperty("bt_variant", variant)
        return widget

    def set_status_text(self, widget: Any, text: Any, *, status: str = "muted") -> None:
        widget.setText(str(text))
        widget.setProperty("bt_status", status)

    def theme_color(self, _token: str) -> str:
        return "#8aa4ff"

    def theme_qcolor(self, _token: str) -> QColor:
        return QColor("#8aa4ff")

    def style_plot_widget(self, _plot: Any, *, show_y_grid: bool = True) -> None:
        del show_y_grid

    def _make_news_table(self, on_click: Any, *_args: Any, **_kwargs: Any) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Headline", "Ticker", "Source", "Time"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.itemClicked.connect(lambda item, tbl=table: on_click(item, tbl))
        return table

    def _open_news_link_table(self, *_args: Any) -> None:
        return None

    def _populate_news_table(self, table: QTableWidget, articles: Any) -> None:
        rows = [dict(article) for article in list(articles or []) if isinstance(article, dict)]
        table.setRowCount(len(rows))
        for row, article in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(str(article.get("title") or "")))

    def _set_tab_session_snapshot(self, _key: str, snapshot: Any, *, immediate: bool = False) -> None:
        del immediate
        self.saved_snapshots.append(snapshot if isinstance(snapshot, dict) else None)


def _candidate(symbol: str, rank: int, *, tier: str = "strict") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "rank": rank,
        "score": 80.0 - rank,
        "pattern_type": "Breakout Setup" if tier == "strict" else "Near Breakout Setup",
        "pattern_score": 72.0 - rank,
        "pattern_match": tier == "strict",
        "match_tier": tier,
        "matched_modes": ["breakout"] if tier == "strict" else [],
        "primary_pattern_mode": "breakout",
        "sector": "Technology",
        "day_change_pct": 1.25,
        "fifty_two_week_change_pct": 0.18,
        "average_volume": 2_500_000,
        "reasons": ["liquid", "large cap"],
        "pattern_reasons": ["near resistance"],
        "quote": {"intentionally": "not persisted"},
    }


def _payload(symbol: str = "AAA", *, candidate_count: int = 2) -> dict[str, Any]:
    candidates = [
        _candidate(symbol if index == 0 else f"T{index:03d}", index + 1, tier="strict" if index == 0 else "near")
        for index in range(candidate_count)
    ]
    return {
        "symbol": symbol,
        "quote": {
            "longName": f"{symbol} Corporation",
            "regularMarketPrice": 101.0,
            "regularMarketPreviousClose": 100.0,
            "regularMarketChange": 1.0,
            "regularMarketChangePercent": 1.0,
            "marketCap": 20_000_000_000,
            "averageDailyVolume3Month": 2_500_000,
            "private_blob": "excluded from snapshot",
        },
        "info": {
            "longName": f"{symbol} Corporation",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Software",
            "currency": "USD",
            "currentPrice": 101.0,
            "previousClose": 100.0,
            "marketCap": 20_000_000_000,
            "private_blob": "excluded from snapshot",
        },
        "candidate_pool": candidates,
        "candidate_rank": 1,
        "candidate_score": 79.0,
        "candidate_reasons": ["liquid", "large cap"],
        "pattern_modes": ["breakout"],
        "pattern_match": True,
        "pattern_type": "Breakout Setup",
        "pattern_score": 71.0,
        "pattern_reasons": ["near resistance"],
        "match_tier": "strict",
        "matched_modes": ["breakout"],
        "primary_pattern_mode": "breakout",
        "screening_summary": "One-year daily history matched the selected pattern.",
        "chart_history": {},
        "top_options": [],
        "news": [],
        "news_status": "",
        "warnings": {},
        "fetch_meta": {"screen_cache_hit": False},
    }


def _build_harness() -> tuple[QApplication, _RollHarness]:
    app = QApplication.instance() or QApplication([])
    harness = _RollHarness()
    harness.resize(1500, 720)
    harness.show()
    app.processEvents()
    harness._p18_apply_responsive_layout(force=True)
    app.processEvents()
    return app, harness


def _grid_positions(harness: _RollHarness) -> list[tuple[int, int]]:
    positions = []
    for checkbox in harness._p18_pattern_checkboxes:
        index = harness.p18_pattern_grid.indexOf(checkbox)
        row, column, _row_span, _column_span = harness.p18_pattern_grid.getItemPosition(index)
        positions.append((row, column))
    return positions


def _resize_roll(app: QApplication, harness: _RollHarness, width: int) -> None:
    harness.resize(width, 720)
    app.processEvents()
    harness._p18_apply_responsive_layout(force=True)
    app.processEvents()


def test_responsive_breakpoints_scroll_and_resize_round_trip() -> None:
    app, harness = _build_harness()
    try:
        assert harness.p18_body_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert harness.p18_body_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

        assert harness._p18_responsive_mode == "wide"
        assert harness.p18_body_splitter.orientation() == Qt.Orientation.Horizontal
        assert harness.p18_research_splitter.orientation() == Qt.Orientation.Horizontal
        assert _grid_positions(harness) == [(0, index) for index in range(6)]
        assert all(not harness.p18_candidates_table.isColumnHidden(column) for column in (5, 7, 8))

        harness.p18_body_splitter.setSizes([320, 960])
        app.processEvents()
        wide_ratio = harness.p18_body_splitter.sizes()[0] / max(sum(harness.p18_body_splitter.sizes()), 1)

        _resize_roll(app, harness, 1024)
        assert harness._p18_responsive_mode == "medium"
        assert harness.p18_body_splitter.orientation() == Qt.Orientation.Vertical
        assert harness.p18_research_splitter.orientation() == Qt.Orientation.Horizontal
        assert _grid_positions(harness) == [(index // 3, index % 3) for index in range(6)]
        assert all(harness.p18_candidates_table.isColumnHidden(column) for column in (5, 7, 8))

        _resize_roll(app, harness, 820)
        assert harness._p18_responsive_mode == "compact"
        assert harness.p18_body_splitter.orientation() == Qt.Orientation.Vertical
        assert harness.p18_research_splitter.orientation() == Qt.Orientation.Vertical
        assert _grid_positions(harness) == [(index // 2, index % 2) for index in range(6)]
        assert harness.p18_body_host.minimumWidth() == 0

        _resize_roll(app, harness, 1500)
        assert harness._p18_responsive_mode == "wide"
        restored_sizes = harness.p18_body_splitter.sizes()
        restored_ratio = restored_sizes[0] / max(sum(restored_sizes), 1)
        assert abs(restored_ratio - wide_ratio) < 0.08
    finally:
        harness.close()
        app.processEvents()


def test_busy_progress_partial_and_stale_request_guards() -> None:
    app, harness = _build_harness()
    try:
        harness._p18_active_request = 42
        harness._p18_set_busy(True, status_text="Starting")
        assert not harness.p18_roll_btn.isEnabled()
        assert harness.p18_roll_btn.text() == "Rolling…"
        assert all(not checkbox.isEnabled() for checkbox in harness._p18_pattern_checkboxes)

        harness._p18_handle_progress(41, {"stage": "history", "message": "stale", "current": 5, "total": 5})
        assert harness.p18_status_label.text() == "Starting"
        harness._p18_handle_progress(42, {"request_id": 41, "stage": "history", "message": "embedded stale"})
        assert harness.p18_status_label.text() == "Starting"
        harness._p18_handle_progress(42, {"stage": "history", "current": 2, "total": 5})
        assert harness.p18_status_label.text() == "Fetching one-year daily history (2/5)"

        candidate_patch = {
            "section": "candidates",
            "stage": "candidates",
            "payload": {"candidate_pool": [_candidate("AAA", 1)], "pattern_modes": ["breakout"]},
        }
        harness._p18_handle_partial(41, candidate_patch)
        assert harness.p18_candidates_table.rowCount() == 0
        embedded_stale_patch = dict(candidate_patch, request_id=41)
        harness._p18_handle_partial(42, embedded_stale_patch)
        assert harness.p18_candidates_table.rowCount() == 0
        harness._p18_handle_partial(42, candidate_patch)
        assert harness.p18_candidates_table.rowCount() == 1
        assert harness.p18_candidates_table.item(0, 1).text() == "AAA"

        harness._p18_render_candidates([_candidate("NEAR", 1, tier="near")], pattern_modes=["breakout"])
        assert harness.p18_candidates_table.item(0, 3).text() == "Near Breakout Setup"
        assert harness.p18_candidates_table.item(0, 4).text() != "N/A"

        core_patch = {
            "section": "core",
            "stage": "core",
            "payload": _payload("AAA", candidate_count=1),
        }
        harness._p18_handle_partial(42, core_patch)
        assert harness.p18_symbol_label.text() == "AAA"
        assert not harness.p18_roll_btn.isEnabled()

        news_warning = "Recent headlines could not be loaded for AAA."
        harness._p18_handle_partial(42, {
            "section": "news",
            "stage": "enrichment",
            "payload": {"news": [], "news_status": news_warning},
        })
        assert harness.p18_news_empty.text() == news_warning

        harness._p18_handle_cancelled(41)
        assert not harness.p18_roll_btn.isEnabled()
        harness._p18_handle_cancelled(42)
        assert harness.p18_roll_btn.isEnabled()
        assert harness.p18_roll_btn.text() == "Roll"
        assert all(checkbox.isEnabled() for checkbox in harness._p18_pattern_checkboxes)
        assert harness.p18_status_label.text() == "Roll cancelled."

        class _FakeWorker:
            cancelled = False

            def cancel(self) -> None:
                self.cancelled = True

        class _FakeThread:
            interruption_requested = False
            quit_requested = False
            wait_timeout = None

            def requestInterruption(self) -> None:
                self.interruption_requested = True

            def quit(self) -> None:
                self.quit_requested = True

            @staticmethod
            def isRunning() -> bool:
                return True

            def wait(self, timeout: int) -> None:
                self.wait_timeout = timeout

        fake_worker = _FakeWorker()
        fake_thread = _FakeThread()
        harness._p18_inflight_workers = {99: (fake_worker, fake_thread)}
        harness._p18_shutdown_workers()
        assert fake_worker.cancelled
        assert fake_thread.interruption_requested
        assert fake_thread.quit_requested
        assert fake_thread.wait_timeout == 400
        harness._p18_inflight_workers.clear()

        provider_started = threading.Event()
        provider_gate = threading.Event()
        blocking_worker = RandomStockWorker()

        def block_provider() -> bool:
            provider_started.set()
            return provider_gate.wait(2.0)

        blocking_worker.fetch = lambda: blocking_worker._interruptible_call(
            block_provider,
            label="shutdown smoke",
        )
        blocking_thread = QThread()
        blocking_worker.moveToThread(blocking_thread)
        blocking_thread.started.connect(blocking_worker.run)
        blocking_thread.start()
        assert provider_started.wait(1.0)
        harness._p18_inflight_workers = {100: (blocking_worker, blocking_thread)}
        shutdown_started = time.monotonic()
        harness._p18_shutdown_workers()
        shutdown_elapsed = time.monotonic() - shutdown_started
        provider_gate.set()
        assert shutdown_elapsed < 0.5
        assert not blocking_thread.isRunning()
        harness._p18_inflight_workers.clear()
    finally:
        harness.close()
        app.processEvents()


def test_candidate_double_click_is_inert_and_history_refetches_exact_symbol() -> None:
    app, harness = _build_harness()
    try:
        harness._p18_apply_payload(_payload("AAA", candidate_count=2))
        app.processEvents()
        calls: list[dict[str, Any]] = []
        harness._p18_roll_stock = lambda *_args, **kwargs: calls.append(dict(kwargs))

        candidate_item = harness.p18_candidates_table.item(0, 1)
        harness.p18_candidates_table.itemDoubleClicked.emit(candidate_item)
        app.processEvents()
        assert calls == []

        assert harness.p18_history_table.rowCount() == 1
        harness._p18_full_payloads.clear()
        history_item = harness.p18_history_table.item(0, 0)
        harness.p18_history_table.itemDoubleClicked.emit(history_item)
        app.processEvents()
        assert calls == [{"target_symbol": "AAA"}]
    finally:
        harness.close()
        app.processEvents()


def test_compact_snapshot_is_bounded_round_trips_and_full_cache_is_lru() -> None:
    app, harness = _build_harness()
    try:
        payload = _payload("AAA", candidate_count=120)
        harness._p18_loaded_payload = payload
        harness._p18_set_pattern_modes(["breakout", "downtrend"])
        harness._p18_roll_history = [
            {
                "symbol": f"H{index:02d}",
                "company": f"History {index}",
                "sector": "Technology",
                "rolled_at": "10:00",
                "payload": {"large": "x" * 50_000},
            }
            for index in range(20)
        ]
        snapshot = harness._p18_session_snapshot()
        assert snapshot is not None
        serialized = json.dumps(snapshot, default=str)
        assert len(serialized) < 250_000
        assert len(snapshot["history"]) == 20
        assert all("payload" not in row for row in snapshot["history"])
        assert len(snapshot["payload"]["candidate_pool"]) == 120
        assert all("quote" not in candidate for candidate in snapshot["payload"]["candidate_pool"])
        assert "private_blob" not in snapshot["payload"]["info"]

        for index in range(P18_FULL_PAYLOAD_LIMIT + 2):
            harness._p18_remember_full_payload(_payload(f"C{index}", candidate_count=1))
        assert len(harness._p18_full_payloads) == P18_FULL_PAYLOAD_LIMIT
        assert list(harness._p18_full_payloads) == ["C2", "C3", "C4", "C5", "C6"]

        assert harness._p18_restore_session_snapshot(snapshot)
        assert harness._p18_current_symbol() == "AAA"
        assert set(harness._p18_selected_pattern_modes()) == {"breakout", "downtrend"}
        assert harness.p18_history_table.rowCount() == 20
    finally:
        harness.close()
        app.processEvents()


def main() -> None:
    test_responsive_breakpoints_scroll_and_resize_round_trip()
    test_busy_progress_partial_and_stale_request_guards()
    test_candidate_double_click_is_inert_and_history_refetches_exact_symbol()
    test_compact_snapshot_is_bounded_round_trips_and_full_cache_is_lru()
    print("Roll page smoke tests passed.")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
    os._exit(0)
