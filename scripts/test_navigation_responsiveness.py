from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="budget-terminal-navigation-responsive-")
os.environ["LOCALAPPDATA"] = _TEST_PROFILE.name
os.environ["APPDATA"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QLabel, QPushButton

from test_tab_picker_search import _build_window


# Charts (stacked index 9) is the heaviest builder in the package: init_page10
# constructs the Multi Charts page too, so its first build costs hundreds of
# milliseconds. That is exactly the cost that must not block navigation.
CHARTS_INDEX = 9
# Economic (stacked index 41 / page42) is the page whose initializer actually crashed on a
# cached payload from an older schema, so it stands in for "any builder can raise".
ECONOMIC_INDEX = 41
SWITCH_BUDGET_SECONDS = 0.35 if os.environ.get("CI") else 0.15


def _drain(app, passes: int = 8) -> None:
    for _ in range(passes):
        app.processEvents()


def _placeholder_text(widget) -> str:
    return " ".join(child.text() for child in widget.findChildren(QLabel))


def _retry_button(widget):
    for button in widget.findChildren(QPushButton):
        if button.text() == "Retry":
            return button
    return None


def test_first_visit_to_heavy_page_paints_before_building() -> None:
    app, window = _build_window()
    try:
        assert not window._page_initialized(index=CHARTS_INDEX)

        started_at = time.perf_counter()
        window.switch_page(CHARTS_INDEX)
        blocked_seconds = time.perf_counter() - started_at

        # The visible half of the switch is done and the build has not run yet.
        assert window.stacked_widget.currentIndex() == CHARTS_INDEX
        assert not window._page_initialized(index=CHARTS_INDEX)
        assert blocked_seconds <= SWITCH_BUDGET_SECONDS, (
            f"switch_page blocked the GUI thread for {blocked_seconds:.3f}s"
        )

        # One event-loop pass must complete the deferred build and the switch,
        # which is what the existing page smokes rely on.
        app.processEvents()
        assert window._page_initialized(index=CHARTS_INDEX)
        assert window.stacked_widget.currentIndex() == CHARTS_INDEX
    finally:
        window.close()
        app.processEvents()


def test_rapid_switching_builds_only_the_final_page() -> None:
    app, window = _build_window()
    try:
        targets = [CHARTS_INDEX, 12, 22, 19, 33]
        for index in targets:
            assert not window._page_initialized(index=index)

        started_at = time.perf_counter()
        for index in targets:
            window.switch_page(index)
        blocked_seconds = time.perf_counter() - started_at

        assert blocked_seconds <= SWITCH_BUDGET_SECONDS, (
            f"a burst of {len(targets)} switches blocked for {blocked_seconds:.3f}s"
        )
        assert window.stacked_widget.currentIndex() == targets[-1]

        _drain(app)

        assert window._page_initialized(index=targets[-1])
        assert window.stacked_widget.currentIndex() == targets[-1]
        for index in targets[:-1]:
            assert not window._page_initialized(index=index), (
                f"page {index} was passed through but still got built"
            )
            # An abandoned target must not keep a deferred-show flag, or warmup
            # would later yank the user back to it once it finishes building.
            entry = window._lazy_page_entry(index=index)
            assert not entry.get("show_after_build")
        assert window._pending_page_switch_index is None
    finally:
        window.close()
        app.processEvents()


def test_warmup_stands_aside_while_navigating() -> None:
    app, window = _build_window()
    try:
        quiet_ms = int(window._LAZY_WARMUP_QUIET_MS)
        window._lazy_warmup_queue = [12, 22, 19]
        warmup_timer = window._lazy_page_warmup_timer
        warmup_timer.start(0)

        window.switch_page(CHARTS_INDEX)
        assert window._navigation_quiet_remaining_ms() > 0
        assert warmup_timer.remainingTime() > 0

        # Inside the quiet window the warmup step must reschedule, not build.
        window._warm_next_page()
        assert window._lazy_warmup_queue == [12, 22, 19], "warmup built a page during navigation"
        assert not window._page_initialized(index=12)

        # Once the quiet period lapses and no switch is pending, warmup resumes.
        window._pending_page_switch_index = None
        window._last_navigation_at = time.perf_counter() - (quiet_ms / 1000.0) - 0.05
        assert window._navigation_quiet_remaining_ms() == 0
        window._warm_next_page()
        _drain(app)
        assert window._page_initialized(index=12), "warmup did not resume after the quiet period"
    finally:
        window.close()
        app.processEvents()


def test_navigating_to_a_built_page_is_not_stalled_by_queued_warmup() -> None:
    """Warmup must not start a new page build in the window around a click.

    A build already in flight when the click lands still has to finish — page
    builders are not interruptible — but no *further* warmup build may run while
    the user is navigating, so stalls cannot compound across a burst of clicks.
    """
    app, window = _build_window()
    heartbeat_times: list[float] = []
    heartbeat = QTimer()
    heartbeat.setInterval(25)
    heartbeat.timeout.connect(lambda: heartbeat_times.append(time.perf_counter()))
    try:
        queue = [12, 22, 19, 33]
        window._lazy_warmup_queue = list(queue)
        window._lazy_page_warmup_timer.start(int(window._LAZY_WARMUP_STEP_MS))
        started_at = time.perf_counter()
        heartbeat.start()

        # Dashboard is built eagerly, so this switch does no build of its own and
        # isolates warmup as the only possible source of a stall.
        def navigate() -> None:
            window.switch_page(0)

        loop = QEventLoop()
        QTimer.singleShot(25, navigate)
        QTimer.singleShot(int(window._LAZY_WARMUP_QUIET_MS) - 50, loop.quit)
        loop.exec()

        assert window.stacked_widget.currentIndex() == 0
        assert window._lazy_warmup_queue == queue, "warmup built a page while the user navigated"
        assert len(heartbeat_times) >= 5, f"UI heartbeat fired only {len(heartbeat_times)} time(s)"
        samples = [started_at, *heartbeat_times]
        max_gap = max(right - left for left, right in zip(samples, samples[1:]))
        assert max_gap <= 0.20, f"UI heartbeat stalled for {max_gap:.3f}s during navigation"
    finally:
        heartbeat.stop()
        window.close()
        app.processEvents()


def test_a_failed_page_build_is_visible_and_retryable() -> None:
    """A builder that raises must not leave the page on its loading label forever.

    Before this, the rollback in `_build_page_now` restored the placeholder untouched, so a
    crash during construction looked exactly like a slow fetch — and recurred on every launch,
    because nothing on that screen could trigger another attempt.
    """
    app, window = _build_window()
    try:
        entry = window._lazy_page_entry(index=ECONOMIC_INDEX)
        placeholder = entry["widget"]
        assert not window._page_initialized(index=ECONOMIC_INDEX)
        assert "Loading" in _placeholder_text(placeholder)

        def exploding_init() -> None:
            raise RuntimeError("boom during init")

        window.init_page42 = exploding_init
        try:
            window._build_page_now(ECONOMIC_INDEX, reason="test")
        except RuntimeError:
            pass
        else:
            raise AssertionError("_build_page_now swallowed the initializer failure")

        # The placeholder is back in the stack, and now names the failure instead of pretending
        # to still be loading.
        assert not window._page_initialized(index=ECONOMIC_INDEX)
        assert window._lazy_page_entry(index=ECONOMIC_INDEX)["widget"] is placeholder
        text = _placeholder_text(placeholder)
        assert "failed to load" in text, text
        assert "boom during init" in text, text
        assert "Loading" not in text, text

        # Reload on a page that never built must not reach the widgets the failed attempt
        # destroyed. setCurrentIndex rather than switch_page, so no rebuild is scheduled.
        window.stacked_widget.setCurrentIndex(ECONOMIC_INDEX)
        window._refresh_current_page()

        # Retry rebuilds the page once the fault is gone.
        retry = _retry_button(placeholder)
        assert retry is not None, "the failure state offered no way to try again"
        del window.init_page42
        retry.click()
        _drain(app)
        assert window._page_initialized(index=ECONOMIC_INDEX)
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    test_first_visit_to_heavy_page_paints_before_building()
    test_rapid_switching_builds_only_the_final_page()
    test_warmup_stands_aside_while_navigating()
    test_navigating_to_a_built_page_is_not_stalled_by_queued_warmup()
    test_a_failed_page_build_is_visible_and_retryable()
    print("Navigation responsiveness smoke tests passed.")
