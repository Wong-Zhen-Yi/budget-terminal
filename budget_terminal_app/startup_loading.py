from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


DEFAULT_PAGE_LABELS: tuple[tuple[int, str], ...] = (
    (0, 'Dashboard'),
    (1, 'Portfolio'),
    (2, 'Personal Finance'),
    (3, 'Calendar'),
    (4, 'News'),
    (5, 'Sectors'),
    (6, 'Heatmap'),
    (7, 'Stocks'),
    (8, 'Fundamentals'),
    (9, 'Charts'),
    (10, 'Multi Charts'),
    (11, 'Options'),
    (12, 'ETF'),
    (13, 'Pre-Market'),
    (14, 'Politics'),
    (15, 'YouTube'),
    (16, 'Settings'),
    (17, 'Roll'),
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
    ('first_show', 'First usable view'),
    ('lazy_warmup', 'Page warmup'),
)


class StartupLoadingScreen(QDialog):
    """Single startup loader used for launch and page warmup progress."""

    startup_ready = pyqtSignal()

    def __init__(self, page_labels: tuple[tuple[int, str], ...] = DEFAULT_PAGE_LABELS) -> None:
        super().__init__(None)
        self._task_bars: dict[str, QProgressBar] = {}
        self._task_labels: dict[str, QLabel] = {}
        self._page_keys: set[str] = set()
        self._completed_tasks: set[str] = set()
        self._compact_parent: Any = None
        self._compact = False
        self._ready_emitted = False

        self.setWindowTitle('Budget Terminal Loading')
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._build_ui()
        for key, label in STARTUP_TASK_LABELS:
            self.register_task(key, label, section='startup')
        self.register_pages(page_labels)
        self.register_task('dashboard_data', 'Dashboard Data', section='pages')
        self._update_overall()
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
            QFrame[bt_role="panel"] {
                background: #11182b;
                border: 1px solid #29344d;
                border-radius: 6px;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QProgressBar {
                background: #151f33;
                color: #e5edf8;
                border: 1px solid #29344d;
                border-radius: 4px;
                height: 12px;
                text-align: center;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background: #4f8cff;
                border-radius: 3px;
            }
            """
        )
        self.setFixedSize(640, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(12)

        self.title_label = QLabel('Budget Terminal')
        self.title_label.setStyleSheet('font-size: 24px; font-weight: 800; color: #f3f7ff;')
        root.addWidget(self.title_label)

        self.status_label = QLabel('Starting application...')
        self.status_label.setProperty('bt_role', 'muted')
        root.addWidget(self.status_label)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        root.addWidget(self.overall_bar)

        self.startup_panel, self.startup_tasks_layout = self._new_panel('Startup')
        root.addWidget(self.startup_panel)

        pages_label = QLabel('Pages')
        pages_label.setProperty('bt_role', 'section')
        root.addWidget(pages_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        self.pages_layout.setSpacing(6)
        scroll.setWidget(self.pages_container)
        root.addWidget(scroll, 1)

    def _new_panel(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setProperty('bt_role', 'panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        label = QLabel(title)
        label.setProperty('bt_role', 'section')
        layout.addWidget(label)
        return panel, layout

    def _task_layout_for_section(self, section: str) -> QVBoxLayout:
        if section == 'pages':
            return self.pages_layout
        return self.startup_tasks_layout

    def register_task(self, key: str, label: str, *, section: str = 'startup') -> None:
        key = str(key or '').strip()
        if not key or key in self._task_bars:
            return
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        text_label = QLabel(str(label or key))
        text_label.setMinimumWidth(118)
        text_label.setProperty('bt_role', 'muted')
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        row_layout.addWidget(text_label)
        row_layout.addWidget(bar, 1)
        self._task_layout_for_section(section).addWidget(row)
        self._task_labels[key] = text_label
        self._task_bars[key] = bar
        if section == 'pages':
            self._page_keys.add(key)

    def register_pages(self, page_labels: Any) -> None:
        for index, label in tuple(page_labels or ()):
            self.register_task(self._page_key(index), str(label or f'Page {index}'), section='pages')

    def begin_task(self, key: str, label: str | None = None) -> None:
        self._ensure_task(key, label)
        bar = self._task_bars[str(key)]
        if bar.value() < 8:
            bar.setValue(8)
        self.status_label.setText(f'Loading {label or self._task_labels[str(key)].text()}...')
        self._update_overall()
        self._pump_events()

    def advance_task(self, key: str, value: int, label: str | None = None) -> None:
        self._ensure_task(key, label)
        self._task_bars[str(key)].setValue(max(0, min(99, int(value))))
        if label:
            self.status_label.setText(str(label))
        self._update_overall()
        self._pump_events()

    def complete_task(self, key: str, label: str | None = None) -> None:
        self._ensure_task(key, label)
        clean_key = str(key)
        self._task_bars[clean_key].setValue(100)
        self._completed_tasks.add(clean_key)
        self.status_label.setText(f'Loaded {label or self._task_labels[clean_key].text()}.')
        self._update_overall()
        self._pump_events()

    def begin_page(self, index: Any, label: str | None = None) -> None:
        key = self._page_key(index)
        self.begin_task(key, label or f'Page {index}')

    def complete_page(self, index: Any, label: str | None = None) -> None:
        key = self._page_key(index)
        self.complete_task(key, label or f'Page {index}')

    def switch_to_compact(self, parent: Any = None) -> None:
        if self._compact:
            self._position_compact()
            return
        self._compact = True
        self._compact_parent = parent
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.title_label.setText('Finishing Startup')
        self.status_label.setText('Warming page widgets...')
        self.startup_panel.hide()
        self.setFixedSize(460, 440)
        self._position_compact()
        self.show()
        self.raise_()
        self._pump_events()

    def finish_if_complete(self) -> bool:
        if self.all_pages_complete():
            self.complete_task('lazy_warmup', 'Page warmup')
            self.status_label.setText('Startup complete.')
            self._update_overall()
            self._pump_events()
            if not self._ready_emitted:
                self._ready_emitted = True
                self.startup_ready.emit()
            return True
        return False

    def all_pages_complete(self) -> bool:
        return all(self._task_bars[key].value() >= 100 for key in self._page_keys)

    def _ensure_task(self, key: str, label: str | None = None) -> None:
        clean_key = str(key or '').strip()
        if clean_key not in self._task_bars:
            self.register_task(clean_key, label or clean_key)
        elif label:
            self._task_labels[clean_key].setText(str(label))

    def _page_key(self, index: Any) -> str:
        try:
            numeric = int(index)
        except (TypeError, ValueError):
            numeric = -1
        return f'page_{numeric}'

    def _update_overall(self) -> None:
        bars = list(self._task_bars.values())
        if not bars:
            self.overall_bar.setValue(0)
            return
        progress = sum(bar.value() for bar in bars) / (len(bars) * 100)
        self.overall_bar.setValue(max(0, min(100, int(round(progress * 100)))))

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            geometry.x() + max(0, (geometry.width() - self.width()) // 2),
            geometry.y() + max(0, (geometry.height() - self.height()) // 2),
        )

    def _position_compact(self) -> None:
        parent = self._compact_parent
        if parent is not None and hasattr(parent, 'geometry') and hasattr(parent, 'mapToGlobal'):
            try:
                top_left = parent.mapToGlobal(parent.rect().topRight())
                self.move(top_left.x() - self.width() - 24, top_left.y() + 54)
                return
            except Exception:
                pass
        self._center_on_screen()

    def _pump_events(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()


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

    def switch_to_compact(self, parent: Any = None) -> None:
        if self.screen is not None:
            self.screen.switch_to_compact(parent)

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
