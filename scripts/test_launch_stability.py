"""Focused offscreen regressions for Budget Terminal launch stability."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _authoritative_page_labels(window_setup_mixin: Any) -> tuple[tuple[int, str], ...]:
    specs = window_setup_mixin._lazy_page_specs(None)
    labels = [(0, window_setup_mixin._PAGE_LABELS.get(0, 'Dashboard'))]
    labels.extend(
        (
            int(spec['index']),
            window_setup_mixin._PAGE_LABELS.get(
                int(spec['index']),
                f"Page {spec['index']}",
            ),
        )
        for spec in specs
        if not spec.get('placeholder_only')
    )
    return tuple(labels)


def test_loader_reconciles_authoritative_pages(
    app: Any,
    startup_loading_screen: Any,
    required_task_keys: tuple[str, ...],
    window_setup_mixin: Any,
) -> None:
    screen = startup_loading_screen()
    try:
        page_labels = _authoritative_page_labels(window_setup_mixin)
        screen.register_pages(page_labels)
        expected_keys = {screen._page_key(index) for index, _label in page_labels}
        actual_page_keys = {key for key in screen._page_keys if key.startswith('page_')}
        assert actual_page_keys == expected_keys, (
            'loader page registry retained stale or non-authoritative keys: '
            f'expected={sorted(expected_keys)!r} actual={sorted(actual_page_keys)!r}'
        )

        for key in required_task_keys:
            screen.complete_task(key, key)
        for index, label in page_labels:
            screen.complete_page(index, label)

        assert screen.all_pages_complete(), 'authoritative page tasks did not all complete'
        assert screen.required_startup_complete(), 'loader remained blocked after all required work completed'
        assert screen.finish_if_complete(), 'loader did not emit readiness after all required work completed'
    finally:
        screen.close()
        app.processEvents()


def test_failed_lazy_build_rolls_back(window: Any, app: Any) -> None:
    page_index = 1
    entry = window._lazy_page_registry[page_index]
    placeholder = entry['widget']
    page_attr = str(entry['page_attr'])
    original_init_method = entry['init_method']
    original_rollback_hook = entry.get('rollback_hook')
    original_count = window.stacked_widget.count()
    original_index = window.stacked_widget.indexOf(placeholder)
    rollback_calls = 0

    def fail_initializer() -> None:
        raise RuntimeError('intentional lazy initializer failure')

    def record_rollback() -> None:
        nonlocal rollback_calls
        rollback_calls += 1

    window._test_failing_lazy_initializer = fail_initializer
    window._test_lazy_rollback = record_rollback
    entry['init_method'] = '_test_failing_lazy_initializer'
    entry['rollback_hook'] = '_test_lazy_rollback'
    caught_error: BaseException | None = None
    try:
        window._build_page_now(page_index, reason='launch stability smoke')
    except BaseException as exc:  # The rollback contract must hold for initializer failures.
        caught_error = exc
    finally:
        entry['init_method'] = original_init_method
        if original_rollback_hook is None:
            entry.pop('rollback_hook', None)
        else:
            entry['rollback_hook'] = original_rollback_hook
        del window._test_failing_lazy_initializer
        del window._test_lazy_rollback

    assert isinstance(caught_error, RuntimeError), (
        f'lazy initializer did not surface the expected RuntimeError: {caught_error!r}'
    )
    assert rollback_calls == 1, f'lazy rollback cleanup ran {rollback_calls} times'

    attr_widget = getattr(window, page_attr)
    rolled_back = (
        entry['widget'] is placeholder
        and not entry.get('initialized')
        and attr_widget is placeholder
        and window.stacked_widget.count() == original_count
        and window.stacked_widget.indexOf(placeholder) == original_index
    )

    if not rolled_back:
        # Keep this smoke hermetic even when exercising the pre-fix failure mode.
        if attr_widget is not placeholder:
            window.stacked_widget.removeWidget(attr_widget)
            attr_widget.deleteLater()
        setattr(window, page_attr, placeholder)
        entry['widget'] = placeholder
        entry['initialized'] = False
        app.processEvents()

    assert rolled_back, 'failed lazy-page initialization left a provisional widget or corrupted stack index'


def test_reentrant_lazy_build_initializes_once(window: Any, app: Any) -> None:
    page_index = 1
    entry = window._lazy_page_registry[page_index]
    original_init_method = entry['init_method']
    original_progress_begin = window._startup_progress_begin_page
    original_count = window.stacked_widget.count()
    init_calls = 0
    navigation_requested = False

    def count_initializer() -> None:
        nonlocal init_calls
        init_calls += 1

    def reentrant_progress_begin(index: int, _label: str) -> None:
        nonlocal navigation_requested
        if int(index) == page_index and not navigation_requested:
            navigation_requested = True
            window.switch_page(page_index)

    window._test_counting_lazy_initializer = count_initializer
    window._startup_progress_begin_page = reentrant_progress_begin
    entry['init_method'] = '_test_counting_lazy_initializer'
    try:
        page = window._build_page_now(page_index, reason='reentrant launch stability smoke')
        app.processEvents()
    finally:
        entry['init_method'] = original_init_method
        window._startup_progress_begin_page = original_progress_begin
        del window._test_counting_lazy_initializer

    assert navigation_requested, 'test did not exercise reentrant navigation during page progress'
    assert init_calls == 1, f'reentrant lazy initialization ran {init_calls} times'
    assert entry.get('initialized') and not entry.get('building')
    assert not entry.get('show_after_build')
    assert window.stacked_widget.count() == original_count, 'reentrant build shifted the page stack'
    assert entry['widget'] is page
    assert window.stacked_widget.currentWidget() is page, 'deferred navigation did not show the built page'


def test_close_with_retired_page_placeholders(window: Any, app: Any) -> None:
    assert 30 not in window._lazy_page_registry
    assert 31 not in window._lazy_page_registry
    assert not window._page_initialized(index=31)
    assert window.stacked_widget.indexOf(window._retired_page31) == 31

    callback_errors: list[tuple[type[BaseException], BaseException]] = []
    original_excepthook = sys.excepthook

    def capture_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        _traceback: Any,
    ) -> None:
        callback_errors.append((exc_type, exc_value))

    sys.excepthook = capture_exception
    try:
        closed = window.close()
        app.processEvents()
    finally:
        sys.excepthook = original_excepthook

    if callback_errors:
        window.close()
        app.processEvents()

    assert closed, 'Qt refused to close the unshown main window'
    assert not callback_errors, f'closeEvent raised with lazy pages uninitialized: {callback_errors!r}'


def main() -> int:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    with tempfile.TemporaryDirectory(prefix='budget-terminal-launch-stability-') as temp_dir:
        isolated_root = Path(temp_dir)
        os.environ['LOCALAPPDATA'] = str(isolated_root / 'local')
        os.environ['APPDATA'] = str(isolated_root / 'roaming')
        os.environ['USERPROFILE'] = str(isolated_root / 'profile')

        from budget_terminal_app.app import BudgetTerminalApp
        from budget_terminal_app.dependencies import QApplication
        from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
        from budget_terminal_app.mixins.window_setup import WindowSetupMixin
        from budget_terminal_app.startup_loading import (
            REQUIRED_STARTUP_TASK_KEYS,
            StartupLoadingScreen,
        )

        original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
        original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
        WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
        WindowLifecycleMixin._start_lazy_warmup = lambda self: None

        app = QApplication.instance() or QApplication([])
        window = None
        try:
            test_loader_reconciles_authoritative_pages(
                app,
                StartupLoadingScreen,
                REQUIRED_STARTUP_TASK_KEYS,
                WindowSetupMixin,
            )
            window = BudgetTerminalApp()
            test_failed_lazy_build_rolls_back(window, app)
            test_reentrant_lazy_build_initializes_once(window, app)
            test_close_with_retired_page_placeholders(window, app)
            window = None
        finally:
            if window is not None:
                window.close()
                app.processEvents()
            WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
            WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
            app.quit()

    print('PASS launch loader, lazy rollback/reentrancy, and uninitialized close stability')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
