from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-bulk-render-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QEventLoop, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QStackedWidget, QTableWidget, QTableWidgetItem, QWidget

from budget_terminal_app.widgets.batched_render import run_batched


def _run_until(handle, app: QApplication, timeout_seconds: float = 2.0) -> None:
    deadline = time.perf_counter() + timeout_seconds
    while handle.running and time.perf_counter() < deadline:
        app.processEvents()
    assert not handle.running, "batched render did not finish before timeout"


def test_bulk_table_render_yields_to_navigation_and_finishes_with_parity() -> None:
    app = QApplication.instance() or QApplication([])
    owner = QObject()
    source_page = QWidget()
    destination_page = QWidget()
    stack = QStackedWidget()
    stack.addWidget(source_page)
    stack.addWidget(destination_page)
    stack.setCurrentWidget(source_page)
    table = QTableWidget(0, 8, source_page)
    rows = [(row, [f"{row}:{column}" for column in range(8)]) for row in range(2_000)]
    heartbeat_times: list[float] = []
    started_at = time.perf_counter()
    heartbeat = QTimer()
    heartbeat.setInterval(25)
    heartbeat.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))
    heartbeat.start()

    def prepare() -> None:
        table.setUpdatesEnabled(False)
        table.setRowCount(len(rows))

    def apply_slow(row_index: int, item) -> None:
        _source_index, values = item
        for column, value in enumerate(values):
            table.setItem(row_index, column, QTableWidgetItem(value))
        busy_until = time.perf_counter() + 0.00025
        while time.perf_counter() < busy_until:
            pass

    def finish() -> None:
        table.setUpdatesEnabled(True)

    handle = run_batched(
        owner,
        "bulk-table",
        rows,
        apply_slow,
        prepare=prepare,
        finish=finish,
        is_visible=lambda: stack.currentWidget() is source_page,
    )
    loop = QEventLoop()
    QTimer.singleShot(25, lambda: stack.setCurrentWidget(destination_page))
    QTimer.singleShot(350, loop.quit)
    loop.exec()
    heartbeat.stop()

    assert stack.currentWidget() is destination_page
    assert handle.cancelled and handle.processed_count < len(rows)
    assert len(heartbeat_times) >= 5
    samples = [started_at, *heartbeat_times]
    max_gap = max(right - left for left, right in zip(samples, samples[1:]))
    assert max_gap <= 0.20, f"bulk rendering stalled the UI for {max_gap:.3f}s"

    stack.setCurrentWidget(source_page)
    final_rows = rows[:500]

    def prepare_final() -> None:
        table.setUpdatesEnabled(False)
        table.clearContents()
        table.setRowCount(len(final_rows))

    def apply_final(row_index: int, item) -> None:
        _source_index, values = item
        for column, value in enumerate(values):
            table.setItem(row_index, column, QTableWidgetItem(value))

    final_handle = run_batched(
        owner,
        "bulk-table",
        final_rows,
        apply_final,
        prepare=prepare_final,
        finish=finish,
        is_visible=lambda: stack.currentWidget() is source_page,
    )
    _run_until(final_handle, app)
    assert final_handle.completed
    assert table.rowCount() == len(final_rows)
    assert table.item(0, 0).text() == "0:0"
    assert table.item(len(final_rows) - 1, 7).text() == "499:7"


if __name__ == "__main__":
    test_bulk_table_render_yields_to_navigation_and_finishes_with_parity()
    print("Bulk render responsiveness smoke tests passed.")
