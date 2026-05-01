from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description='Measure Budget Terminal startup timings.')
    parser.add_argument('--offscreen', action='store_true', help='Use the Qt offscreen platform plugin.')
    args = parser.parse_args()
    if args.offscreen:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

    import_started = time.perf_counter()
    from budget_terminal_app.main import QApplication
    import_main_seconds = time.perf_counter() - import_started

    app_import_started = time.perf_counter()
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.dependencies import logger
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
    from budget_terminal_app.startup_profile import StartupProfiler
    import_app_seconds = time.perf_counter() - app_import_started

    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None

    app = QApplication([])
    profiler = StartupProfiler(logger)
    try:
        init_started = time.perf_counter()
        window = BudgetTerminalApp(startup_profiler=profiler)
        init_seconds = time.perf_counter() - init_started

        show_started = time.perf_counter()
        window.show()
        app.processEvents()
        show_seconds = time.perf_counter() - show_started

        print('Startup timing snapshot')
        print(f'- import budget_terminal_app.main: {import_main_seconds:.3f}s')
        print(f'- import BudgetTerminalApp: {import_app_seconds:.3f}s')
        print(f'- BudgetTerminalApp(): {init_seconds:.3f}s')
        print(f'- show + processEvents: {show_seconds:.3f}s')
        for record in profiler.records():
            name = str(record.get('name', '') or '')
            kind = str(record.get('kind', '') or '')
            seconds = float(record.get('seconds', 0.0) or 0.0)
            print(f'- profiler[{kind}] {name}: {seconds:.3f}s')
        window.close()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
        app.quit()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
