from __future__ import annotations

import logging
import time

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .paths import resource_path


# The loader stays up for this fixed window on every launch. main.py releases the main window on
# that deadline and on nothing else, so hidden startup work (page builds, startup data, session
# restores, cache warmup) always gets the same predictable amount of time before first paint.
STARTUP_HOLD_SECONDS = 30.0

# Ordered to match persistence.DEFAULT_NAVIGATION_PAGE_ORDER and named to match
# WindowSetupMixin._PAGE_LABELS. scripts/test_launch_stability.py asserts this stays in
# sync; drift would make the loader destroy and rebuild every page row mid-launch.
DEFAULT_PAGE_LABELS: tuple[tuple[int, str], ...] = (
    (0, 'Dashboard'),
    (25, 'Global'),
    (1, 'Portfolio'),
    (28, 'Cards'),
    (2, 'Personal Finance'),
    (13, 'Pre-Market'),
    (26, 'Up/Down'),
    (19, 'Trading Volumes'),
    (39, 'Signals'),
    (29, 'Price'),
    (6, 'Heatmap'),
    (33, 'News'),
    (3, 'Calendar'),
    (7, 'Stocks'),
    (8, 'Fundamentals'),
    (22, 'Valuation'),
    (9, 'Charts'),
    (27, 'Projections'),
    (11, 'Options'),
    (12, 'ETF'),
    (14, 'Crypto'),
    (24, 'Backtest'),
    (18, 'Roll'),
    (20, 'IPO'),
    (23, 'Institutions'),
    (15, 'Politics'),
    (16, 'YouTube'),
    (37, 'Dictionary'),
    (40, 'Quant'),
    (41, 'Economic'),
    (17, 'Settings'),
)

STARTUP_TASK_LABELS: tuple[tuple[str, str], ...] = (
    ('qt_app_init', 'Qt application'),
    ('app_icon', 'Application icon'),
    ('pyqtgraph_config', 'Chart engine'),
    ('import_app', 'Application modules'),
    ('window_init', 'Main window'),
    ('state_load', 'Saved state'),
    ('theme_init', 'Theme system'),
    ('ui_build', 'UI layout'),
    ('window_shell', 'Window shell'),
    ('lazy_registry', 'Page registry'),
    ('navigation', 'Navigation'),
    ('theme_apply', 'Theme styling'),
    ('session_restore', 'Session Restore'),
    ('startup_data', 'Startup Data'),
    ('first_show', 'First usable view'),
    ('lazy_warmup', 'Page warmup'),
)

REQUIRED_STARTUP_TASK_KEYS: tuple[str, ...] = tuple(
    key for key, _label in STARTUP_TASK_LABELS
    if key not in {'first_show', 'lazy_warmup'}
) + ('dashboard_data',)

# Every task is one progress bar with its name drawn inside it, arranged column-major in
# a grid. Column counts are chosen so the whole startup and page inventory always fits
# the available height without scrolling, widening further on short screens.
_PREFERRED_SECTION_COLUMNS = {'startup': 2, 'pages': 3}
_MIN_COLUMN_WIDTH = 150
_BAR_MIN_WIDTH = 132
_BAR_HEIGHT = 18
_GRID_VERTICAL_SPACING = 4
_LOG_HEIGHT_STEPS = (96, 64)

# Repaints are coalesced: startup runs synchronously on the GUI thread, so the loader
# flushes at a bounded rate instead of pumping the event loop on every progress call.
_FLUSH_INTERVAL_MS = 60
_FLUSH_MIN_SECONDS = 0.08
_LOG_FLUSH_INTERVAL_MS = 120
_LOG_FLUSH_MIN_SECONDS = 0.15
_PUMP_MIN_SECONDS = 0.025


class StartupLoadingScreen(QDialog):
    """Single startup loader showing every startup and page progress bar at once."""

    startup_ready = Signal()
    log_message = Signal(str)

    def __init__(self, page_labels: tuple[tuple[int, str], ...] = DEFAULT_PAGE_LABELS) -> None:
        super().__init__(None)
        self._task_bars: dict[str, QProgressBar] = {}
        self._task_titles: dict[str, str] = {}
        self._task_values: dict[str, int] = {}
        self._task_sections: dict[str, str] = {}
        self._section_keys: dict[str, list[str]] = {'startup': [], 'pages': []}
        self._section_columns: dict[str, int] = {'startup': 0, 'pages': 0}
        self._panel_titles: dict[Any, QLabel] = {}
        self._page_keys: set[str] = set()
        self._completed_tasks: set[str] = set()
        self._dirty_keys: set[str] = set()
        self._progress_total = 0
        self._pending_status = ''
        self._pending_log_lines: list[str] = []
        self._last_flush_at = 0.0
        self._last_log_flush_at = 0.0
        self._last_pump_at = 0.0
        self._pumping = False
        self._sized = False
        self._fitting = False
        self._ready_emitted = False
        self._elapsed_started_at = time.monotonic()

        self.setWindowTitle('Budget Terminal Loading')
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
        )
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.log_message.connect(self.append_log_message)
        self._build_ui()

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(_FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_progress)
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(_LOG_FLUSH_INTERVAL_MS)
        self._log_flush_timer.timeout.connect(self._flush_log_lines)

        for key, label in STARTUP_TASK_LABELS:
            self.register_task(key, label, section='startup', reflow=False)
        self._reflow_section('startup')
        self.register_pages(page_labels)
        self.register_task('dashboard_data', 'Dashboard Data', section='pages')
        self._update_overall()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_label)
        self._update_elapsed_label()
        self._elapsed_timer.start()
        self._apply_startup_size()
        self._center_on_screen()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #0b1020;
                color: #e5edf8;
                border: 1px solid #29344d;
            }
            QLabel {
                color: #e5edf8;
                background: transparent;
            }
            QLabel[bt_role="muted"] {
                color: #8ea0bd;
            }
            QLabel[bt_role="section"] {
                color: #c8d4e6;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel[bt_role="elapsed"] {
                color: #a9b9d4;
                background: #11182b;
                border: 1px solid #29344d;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QFrame[bt_role="panel"] {
                background: #11182b;
                border: 1px solid #29344d;
                border-radius: 6px;
            }
            QPlainTextEdit {
                background: #080d19;
                color: #c8d4e6;
                border: 1px solid #29344d;
                border-radius: 6px;
                padding: 6px;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 10px;
                selection-background-color: #264f78;
            }
            QProgressBar {
                background: #151f33;
                color: #e5edf8;
                border: 1px solid #29344d;
                border-radius: 4px;
                text-align: center;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background: #4f8cff;
                border-radius: 3px;
            }
            QProgressBar[bt_role="overall"] {
                font-size: 10px;
                font-weight: 700;
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        header = self.header_widget = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(14)

        self.logo_label = QLabel()
        self.logo_label.setFixedSize(56, 56)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = self._load_logo_pixmap()
        if not logo.isNull():
            self.logo_label.setPixmap(
                logo.scaled(
                    52,
                    52,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            header_layout.addWidget(self.logo_label)

        title_group = QWidget()
        title_layout = QVBoxLayout(title_group)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(3)

        self.title_label = QLabel('Budget Terminal')
        self.title_label.setStyleSheet('font-size: 24px; font-weight: 800; color: #f3f7ff;')
        title_layout.addWidget(self.title_label)

        self.status_label = QLabel('Starting application...')
        self.status_label.setProperty('bt_role', 'muted')
        title_layout.addWidget(self.status_label)

        header_layout.addWidget(title_group, 1)
        self.elapsed_label = QLabel('Loading: 0:00')
        self.elapsed_label.setProperty('bt_role', 'elapsed')
        self.elapsed_label.setMinimumWidth(112)
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.elapsed_label)
        root.addWidget(header)

        self.overall_bar = QProgressBar()
        self.overall_bar.setProperty('bt_role', 'overall')
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedHeight(20)
        root.addWidget(self.overall_bar)

        self.startup_panel, self.startup_tasks_layout = self._new_panel('Startup')
        self.pages_panel, self.pages_layout = self._new_panel('Pages')
        root.addWidget(self.startup_panel)
        root.addWidget(self.pages_panel)

        self.logs_label = QLabel('Startup Logs')
        self.logs_label.setProperty('bt_role', 'section')
        root.addWidget(self.logs_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.document().setMaximumBlockCount(300)
        self.log_output.setMinimumHeight(_LOG_HEIGHT_STEPS[0])
        self.log_output.setMaximumHeight(140)
        root.addWidget(self.log_output)

    def _load_logo_pixmap(self) -> QPixmap:
        logo_path = resource_path('budget_terminal_app', 'assets', 'app_icon.png')
        if not logo_path.exists():
            return QPixmap()
        return QPixmap(str(logo_path))

    def _new_panel(self, title: str) -> tuple[QFrame, QGridLayout]:
        panel = QFrame()
        panel.setProperty('bt_role', 'panel')
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 9, 12, 10)
        outer.setSpacing(6)
        label = QLabel(title)
        label.setProperty('bt_role', 'section')
        outer.addWidget(label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(_GRID_VERTICAL_SPACING)
        outer.addLayout(grid)
        self._panel_titles[panel] = label
        return panel, grid

    def _grid_for_section(self, section: str) -> QGridLayout:
        if section == 'pages':
            return self.pages_layout
        return self.startup_tasks_layout

    # -- task registry ---------------------------------------------------

    def register_task(self, key: str, label: str, *, section: str = 'startup', reflow: bool = True) -> None:
        key = str(key or '').strip()
        if not key or key in self._task_bars:
            return
        section = 'pages' if section == 'pages' else 'startup'
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.setFixedHeight(_BAR_HEIGHT)
        bar.setMinimumWidth(_BAR_MIN_WIDTH)
        self._task_bars[key] = bar
        self._task_values[key] = 0
        self._task_sections[key] = section
        self._section_keys[section].append(key)
        self._set_task_title(key, str(label or key))
        if section == 'pages':
            self._page_keys.add(key)
        if reflow:
            self._reflow_section(section)

    def register_pages(self, page_labels: Any) -> None:
        """Replace page progress rows with the live page registry."""
        normalized_pages: list[tuple[Any, str]] = []
        expected_keys: list[str] = []
        seen: set[str] = set()
        for index, label in tuple(page_labels or ()):
            key = self._page_key(index)
            if key in seen:
                continue
            seen.add(key)
            expected_keys.append(key)
            normalized_pages.append((index, str(label or f'Page {index}')))

        current_keys = [key for key in self._section_keys['pages'] if key.startswith('page_')]
        if current_keys == expected_keys:
            # Normal launch path: the authoritative registry matches the built-in
            # defaults, so only the titles need refreshing and nothing is torn down.
            for index, label in normalized_pages:
                self._set_task_title(self._page_key(index), label)
            return

        for key in [key for key in current_keys if key not in seen]:
            bar = self._task_bars.pop(key, None)
            self._progress_total -= self._task_values.pop(key, 0)
            self._task_titles.pop(key, None)
            self._task_sections.pop(key, None)
            self._completed_tasks.discard(key)
            self._dirty_keys.discard(key)
            self._page_keys.discard(key)
            self._section_keys['pages'].remove(key)
            if bar is not None:
                bar.setParent(None)
                bar.deleteLater()

        for index, label in normalized_pages:
            key = self._page_key(index)
            if key in self._task_bars:
                self._set_task_title(key, label)
                self._page_keys.add(key)
                continue
            self.register_task(key, label, section='pages', reflow=False)

        # Keep the grid order aligned with the authoritative page order, leaving any
        # non-page task in this section (dashboard_data) at the end.
        extras = [key for key in self._section_keys['pages'] if not key.startswith('page_')]
        self._section_keys['pages'] = expected_keys + extras
        self._reflow_section('pages')
        self._schedule_flush()

    def _set_task_title(self, key: str, label: str) -> None:
        title = str(label or key)
        if self._task_titles.get(key) == title:
            return
        self._task_titles[key] = title
        bar = self._task_bars.get(key)
        if bar is not None:
            bar.setFormat(f'{title}  %p%')

    def _task_title(self, key: str) -> str:
        return self._task_titles.get(key, key)

    # -- layout ------------------------------------------------------------

    def _chrome_height(self) -> int:
        """Height consumed by everything except the two task grids."""
        root = self.layout()
        if root is None:
            return 0
        margins = root.contentsMargins()
        total = margins.top() + margins.bottom() + root.spacing() * max(0, root.count() - 1)
        for widget in (self.header_widget, self.overall_bar, self.logs_label):
            total += widget.sizeHint().height()
        total += self.log_output.minimumHeight()
        for panel in (self.startup_panel, self.pages_panel):
            panel_layout = panel.layout()
            panel_margins = panel_layout.contentsMargins()
            total += panel_margins.top() + panel_margins.bottom() + panel_layout.spacing() + 2
            total += self._panel_titles[panel].sizeHint().height()
        return total

    def _max_columns_for_width(self) -> int:
        budget = max(0, self.width() - 76)
        return max(1, budget // _MIN_COLUMN_WIDTH)

    def _plan_columns(self) -> dict[str, int]:
        """Pick per-section column counts that keep every bar visible without scrolling."""
        counts = {section: len(keys) for section, keys in self._section_keys.items()}
        total_count = sum(counts.values())
        preferred = dict(_PREFERRED_SECTION_COLUMNS)
        if not self._sized or not total_count:
            return {
                section: max(1, min(preferred.get(section, 2), count or 1))
                for section, count in counts.items()
            }

        planned = {
            section: max(1, min(preferred.get(section, 2), count or 1))
            for section, count in counts.items()
        }
        row_height = _BAR_HEIGHT + _GRID_VERTICAL_SPACING
        available = max(row_height * 2, self.height() - self._chrome_height())
        rows_budget = max(2, available // row_height)
        max_columns = self._max_columns_for_width()

        def section_rows(section: str) -> int:
            count = counts.get(section, 0)
            return -(-count // planned[section]) if count else 0

        # Keep the preferred shape when it fits, and otherwise widen the tallest
        # section one column at a time until the grids fit the available height.
        while sum(section_rows(section) for section in counts) > rows_budget:
            widenable = [
                section for section, count in counts.items()
                if count and planned[section] < min(count, max_columns)
            ]
            if not widenable:
                break
            planned[max(widenable, key=section_rows)] += 1
        return planned

    def _reflow_section(self, section: str, columns: int | None = None) -> None:
        keys = self._section_keys.get(section, [])
        grid = self._grid_for_section(section)
        if columns is None:
            columns = self._plan_columns().get(section, 1)
        columns = max(1, min(int(columns), len(keys) or 1))
        self._section_columns[section] = columns
        while grid.count():
            grid.takeAt(0)
        rows = (len(keys) + columns - 1) // columns if keys else 0
        for position, key in enumerate(keys):
            bar = self._task_bars.get(key)
            if bar is None or not rows:
                continue
            grid.addWidget(bar, position % rows, position // rows)
            bar.show()
        for column in range(grid.columnCount()):
            grid.setColumnStretch(column, 1 if column < columns else 0)

    def _reflow_changed_sections(self) -> None:
        planned = self._plan_columns()
        for section, columns in planned.items():
            if columns != self._section_columns.get(section):
                self._reflow_section(section, columns)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if not self._sized or self._fitting:
            return
        self._fitting = True
        try:
            self._fit_content_to_height()
        finally:
            self._fitting = False

    # -- progress state ----------------------------------------------------

    def _set_task_value(self, key: str, value: int) -> None:
        clean_value = max(0, min(100, int(value)))
        previous = self._task_values.get(key, 0)
        if previous == clean_value:
            return
        self._task_values[key] = clean_value
        self._progress_total += clean_value - previous
        self._dirty_keys.add(key)

    def begin_task(self, key: str, label: str | None = None) -> None:
        self._ensure_task(key, label)
        clean_key = str(key)
        if self._task_values.get(clean_key, 0) < 8:
            self._set_task_value(clean_key, 8)
        self._pending_status = f'Loading {label or self._task_title(clean_key)}...'
        self._schedule_flush()

    def advance_task(self, key: str, value: int, label: str | None = None) -> None:
        self._ensure_task(key, label)
        self._set_task_value(str(key), min(99, int(value)))
        if label:
            self._pending_status = str(label)
        self._schedule_flush()

    def complete_task(self, key: str, label: str | None = None) -> None:
        self._ensure_task(key, label)
        clean_key = str(key)
        self._set_task_value(clean_key, 100)
        self._completed_tasks.add(clean_key)
        self._pending_status = f'Loaded {label or self._task_title(clean_key)}.'
        self._schedule_flush()

    def begin_page(self, index: Any, label: str | None = None) -> None:
        self.begin_task(self._page_key(index), label or f'Page {index}')

    def complete_page(self, index: Any, label: str | None = None) -> None:
        self.complete_task(self._page_key(index), label or f'Page {index}')

    def append_log_message(self, message: str) -> None:
        text = str(message or '').rstrip()
        if not text or not hasattr(self, 'log_output'):
            return
        self._pending_log_lines.append(text)
        if time.monotonic() - self._last_log_flush_at >= _LOG_FLUSH_MIN_SECONDS:
            self._flush_log_lines()
        elif not self._log_flush_timer.isActive():
            self._log_flush_timer.start()

    def _flush_log_lines(self) -> None:
        self._log_flush_timer.stop()
        self._last_log_flush_at = time.monotonic()
        if not self._pending_log_lines or not hasattr(self, 'log_output'):
            return
        block = '\n'.join(self._pending_log_lines)
        self._pending_log_lines.clear()
        self.log_output.appendPlainText(block)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event: Any) -> None:
        for attribute in ('_elapsed_timer', '_flush_timer', '_log_flush_timer'):
            timer = getattr(self, attribute, None)
            if timer is not None:
                timer.stop()
        super().closeEvent(event)

    def finish_if_complete(self) -> bool:
        if self.required_startup_complete():
            # The window is released on the fixed startup hold in main.py, never here, so the
            # elapsed timer keeps running and the countdown keeps ticking while background
            # warmup spends whatever time is left.
            self._pending_status = 'Startup complete; warming background data until launch...'
            self._flush_progress()
            if not self._ready_emitted:
                self._ready_emitted = True
                self.startup_ready.emit()
            return True
        return False

    def all_pages_complete(self) -> bool:
        return all(self._task_values.get(key, 0) >= 100 for key in self._page_keys)

    def required_startup_complete(self) -> bool:
        for key in REQUIRED_STARTUP_TASK_KEYS:
            if self._task_values.get(key, -1) < 100:
                return False
        return self.all_pages_complete()

    def _ensure_task(self, key: str, label: str | None = None) -> None:
        clean_key = str(key or '').strip()
        if clean_key not in self._task_bars:
            section = 'pages' if clean_key.startswith('page_') else 'startup'
            self.register_task(clean_key, label or clean_key, section=section)
        elif label:
            self._set_task_title(clean_key, str(label))

    def _page_key(self, index: Any) -> str:
        try:
            numeric = int(index)
        except (TypeError, ValueError):
            numeric = -1
        return f'page_{numeric}'

    # -- repaint scheduling --------------------------------------------------

    def _schedule_flush(self) -> None:
        # Startup runs synchronously on the GUI thread, so a queued timer alone would
        # never fire. Flush inline once the minimum interval has elapsed and otherwise
        # let the single-shot timer catch the tail when the event loop is free again.
        if time.monotonic() - self._last_flush_at >= _FLUSH_MIN_SECONDS:
            self._flush_progress()
        elif not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_progress(self) -> None:
        self._flush_timer.stop()
        self._last_flush_at = time.monotonic()
        for key in self._dirty_keys:
            bar = self._task_bars.get(key)
            if bar is not None:
                bar.setValue(self._task_values.get(key, 0))
        self._dirty_keys.clear()
        self._update_overall()
        if self._pending_status:
            self.status_label.setText(self._pending_status)
            self._pending_status = ''
        self._pump_events()

    def _update_overall(self) -> None:
        count = len(self._task_values)
        if not count:
            self.overall_bar.setValue(0)
            return
        self.overall_bar.setValue(max(0, min(100, int(round(self._progress_total / count)))))

    def _update_elapsed_label(self) -> None:
        if not hasattr(self, 'elapsed_label'):
            return
        elapsed_seconds = max(0, int(time.monotonic() - self._elapsed_started_at))
        minutes, seconds = divmod(elapsed_seconds, 60)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            elapsed_text = f'{hours}:{minutes:02d}:{seconds:02d}'
        else:
            elapsed_text = f'{minutes}:{seconds:02d}'
        remaining_seconds = int(max(0.0, STARTUP_HOLD_SECONDS - (time.monotonic() - self._elapsed_started_at)))
        if remaining_seconds > 0:
            self.elapsed_label.setText(f'Loading: {elapsed_text}  ·  Opens in {remaining_seconds}s')
        else:
            self.elapsed_label.setText(f'Loading: {elapsed_text}  ·  Opening...')

    # -- geometry ------------------------------------------------------------

    def _apply_startup_size(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        hint = self.sizeHint()
        width = max(760, hint.width())
        height = max(620, hint.height())
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            width = min(width, max(480, geometry.width() - 80))
            height = min(height, max(420, geometry.height() - 80))
        self.setMinimumSize(min(720, width), min(560, height))
        self.resize(width, height)
        self._sized = True
        self._fitting = True
        try:
            self._fit_content_to_height()
        finally:
            self._fitting = False

    def _fit_content_to_height(self) -> None:
        """Widen the grids, then trade log height, until nothing needs to scroll."""
        layout = self.layout()
        for log_height in _LOG_HEIGHT_STEPS:
            if self.log_output.minimumHeight() != log_height:
                self.log_output.setMinimumHeight(log_height)
                self.log_output.setMaximumHeight(max(log_height, 140))
            self._reflow_changed_sections()
            if layout is None:
                return
            layout.activate()
            if layout.minimumSize().height() <= self.height():
                return

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            geometry.x() + max(0, (geometry.width() - self.width()) // 2),
            geometry.y() + max(0, (geometry.height() - self.height()) // 2),
        )

    def _pump_events(self) -> None:
        # Only pump while this screen is actually on-screen. The reporter stays
        # attached to the window for the whole session, so every post-startup
        # lazy page build would otherwise re-enter the event loop mid-build and
        # deliver queued navigation clicks against a half-constructed page.
        if self._pumping or not self.isVisible():
            return
        now = time.monotonic()
        if now - self._last_pump_at < _PUMP_MIN_SECONDS:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._pumping = True
        self._last_pump_at = now
        try:
            app.processEvents()
        finally:
            self._pumping = False


class StartupLoadingLogHandler(logging.Handler):
    """Stream startup log records into the startup loading screen."""

    def __init__(self, screen: StartupLoadingScreen) -> None:
        super().__init__(level=logging.INFO)
        self.screen: StartupLoadingScreen | None = screen

    def emit(self, record: logging.LogRecord) -> None:
        screen = self.screen
        if screen is None:
            return
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        try:
            screen.log_message.emit(message)
        except RuntimeError:
            self.screen = None

    def close(self) -> None:
        self.screen = None
        super().close()


class StartupProgressReporter:
    """Thin safe interface used by startup code without coupling it to widgets."""

    def __init__(self, screen: StartupLoadingScreen | None) -> None:
        self.screen = screen

    def register_pages(self, page_labels: Any) -> None:
        if self.screen is not None:
            self.screen.register_pages(page_labels)

    def begin(self, key: str, label: str | None = None) -> None:
        if self.screen is not None:
            self.screen.begin_task(key, label)

    def advance(self, key: str, value: int, label: str | None = None) -> None:
        if self.screen is not None:
            self.screen.advance_task(key, value, label)

    def complete(self, key: str, label: str | None = None) -> None:
        if self.screen is not None:
            self.screen.complete_task(key, label)

    def begin_page(self, index: Any, label: str | None = None) -> None:
        if self.screen is not None:
            self.screen.begin_page(index, label)

    def complete_page(self, index: Any, label: str | None = None) -> None:
        if self.screen is not None:
            self.screen.complete_page(index, label)

    def on_ready(self, callback: Any) -> None:
        if self.screen is not None and callable(callback):
            self.screen.startup_ready.connect(callback)

    def finish_if_complete(self) -> bool:
        if self.screen is None:
            return False
        return self.screen.finish_if_complete()

    def close(self) -> None:
        if self.screen is not None:
            self.screen.close()
