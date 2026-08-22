from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QProgressBar

from ..compat import *
from ..services.economic import (
    ECONOMIC_GROUPS,
    EconomicDataService,
    describe_freshness,
)
from ..widgets.table_render import render_table_rows
from ..workers.economic import EconomicDataWorker
from . import economic_presenters as presenters

#: The FRED series id must not live on ``Qt.ItemDataRole.UserRole``: that role is the sort
#: payload for ``widgets/table_render``, so a cell carrying both would have its series id read
#: back as a sort value the moment the column gained a sort key.
_P42_SERIES_ROLE = Qt.ItemDataRole.UserRole + 1

_P42_FETCH_KEY = ('economic', 'series')

#: Sub-tab key to catalog group. ``overview`` spans every group and so maps to nothing.
_P42_TAB_GROUPS = {
    'inflation': 'Inflation',
    'labor': 'Labor',
    'growth': 'Growth',
    'rates': 'Rates',
}

_P42_LOOKBACKS = (('1Y', '1y', 1), ('3Y', '3y', 3), ('5Y', '5y', 5), ('10Y', '10y', 10))

_P42_OVERVIEW_COLUMN_WIDTHS = (210, 88, 96, 96, 96, 104, 90, 200)
_P42_GROUP_COLUMN_WIDTHS = (210, 96, 96, 96, 104, 90, 260)
_P42_CURVE_COLUMN_WIDTHS = (70, 76, 76, 76)


class EconomicPageMixin:
    """US macroeconomic indicators sourced from FRED.

    The page owns its own catalog of series and needs no ticker input, so every sub-tab
    populates from one fetch. Decision support only.
    """

    # ------------------------------------------------------------------ controller

    def _p42_get_service(self) -> EconomicDataService:
        service = getattr(self, '_p42_service', None)
        if service is None:
            service = EconomicDataService(self._get_cache_manager())
            self._p42_service = service
        return service

    def _p42_get_refresh_coordinator(self) -> Any:
        coordinator = getattr(self, '_refresh_coordinator', None)
        if coordinator is None:
            from budget_terminal_app.services.refresh_control import RefreshCoordinator

            coordinator = RefreshCoordinator()
            self._refresh_coordinator = coordinator
        return coordinator

    def _p42_page_is_visible(self) -> bool:
        page = getattr(self, 'page42', None)
        if page is None or not hasattr(self, '_is_current_page'):
            return False
        try:
            return bool(self._is_current_page(page))
        except Exception:
            return False

    def _p42_stop_controller(self) -> None:
        """Release the fetch thread and the single-flight slot at shutdown."""
        worker = getattr(self, '_p42_worker', None)
        cancel = getattr(worker, 'cancel', None)
        if callable(cancel):
            cancel()
        thread = getattr(self, '_p42_thread', None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)
        coordinator = getattr(self, '_refresh_coordinator', None)
        if coordinator is not None:
            coordinator.cancel(_P42_FETCH_KEY)
        self._p42_fetch_contexts = {}

    # ------------------------------------------------------------------ page construction

    def init_page42(self) -> None:
        settings = load_economic_page_settings()
        self._p42_settings = settings
        self._p42_service = None
        self._p42_worker = None
        self._p42_thread = None
        self._p42_fetch_contexts: dict[int, dict[str, Any]] = {}
        self._p42_active_token: Any = None
        self._p42_render_pending = False
        self._p42_pending_error = ''
        self._p42_group_tables: dict[str, Any] = {}
        self._p42_group_plots: dict[str, Any] = {}
        self._p42_group_axes: dict[str, Any] = {}
        self._p42_group_titles: dict[str, Any] = {}
        self._p42_selected_series: dict[str, str] = {}
        self._p42_payload = self._p42_get_service().load_latest_payload()

        layout = QVBoxLayout(self.page42)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel('<b>Economic</b>')
        self.set_theme_role(title, 'page_title')
        subtitle = QLabel(
            'Headline US macro releases straight from FRED — inflation, labour, growth and the '
            'full treasury curve. Decision support only.'
        )
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_theme_role(subtitle, 'status_muted')
        heading.addWidget(title)
        heading.addSpacing(10)
        heading.addWidget(subtitle, 1)
        layout.addLayout(heading)

        layout.addWidget(self._p42_build_controls(settings))
        layout.addWidget(self._p42_build_headline_strip())

        self.p42_progress = QProgressBar()
        self.p42_progress.setRange(0, 1)
        self.p42_progress.setValue(0)
        self.p42_progress.setMaximumHeight(18)
        self.p42_progress.setVisible(False)
        layout.addWidget(self.p42_progress)

        self.p42_tabs = QTabWidget()
        self.p42_tabs.setDocumentMode(True)
        self.p42_overview_tab = self._p42_build_overview_tab(settings)
        self.p42_tabs.addTab(self.p42_overview_tab, 'Overview')
        self._p42_tab_widgets = {'overview': self.p42_overview_tab}
        for key, group in _P42_TAB_GROUPS.items():
            tab = self._p42_build_group_tab(group)
            self.p42_tabs.addTab(tab, group)
            self._p42_tab_widgets[key] = tab
        active = str(settings.get('active_tab', 'overview'))
        if active in self._p42_tab_widgets:
            self.p42_tabs.setCurrentWidget(self._p42_tab_widgets[active])
        self.p42_tabs.currentChanged.connect(self._p42_on_subtab_changed)
        layout.addWidget(self.p42_tabs, 1)

        self.p42_footer_lbl = QLabel('')
        self.p42_footer_lbl.setWordWrap(True)
        self.set_theme_role(self.p42_footer_lbl, 'status_muted')
        layout.addWidget(self.p42_footer_lbl)

        self._p42_render_payload()
        text, status = describe_freshness(self._p42_payload)
        self._p42_update_status(text, status)

    def _p42_build_controls(self, settings: Any) -> Any:
        controls = QFrame()
        self.set_theme_role(controls, 'panel')
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(8)

        self.p42_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p42_refresh_btn, 'accent')
        self.p42_refresh_btn.setToolTip('Reuse the cached payload when it is still fresh, otherwise pull FRED again.')
        self.p42_refresh_btn.clicked.connect(self._p42_manual_refresh)
        controls_layout.addWidget(self.p42_refresh_btn)

        self.p42_force_btn = QPushButton('Force refresh')
        self.p42_force_btn.setToolTip('Re-download every series from FRED, ignoring the cached payload.')
        self.p42_force_btn.clicked.connect(self._p42_force_refresh)
        controls_layout.addWidget(self.p42_force_btn)

        controls_layout.addWidget(QLabel('Chart span'))
        self.p42_lookback_combo = QComboBox()
        for label, key, _years in _P42_LOOKBACKS:
            self.p42_lookback_combo.addItem(label, key)
        saved = self.p42_lookback_combo.findData(str(settings.get('lookback_key', '5y')))
        if saved >= 0:
            self.p42_lookback_combo.setCurrentIndex(saved)
        self.p42_lookback_combo.currentIndexChanged.connect(self._p42_on_lookback_changed)
        controls_layout.addWidget(self.p42_lookback_combo)

        controls_layout.addStretch(1)

        self.p42_status_lbl = QLabel('Ready')
        self.p42_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p42_status_lbl, 'status_muted')
        controls_layout.addWidget(self.p42_status_lbl, 1)
        return controls

    def _p42_build_headline_strip(self) -> Any:
        strip = QFrame()
        self.set_theme_role(strip, 'panel')
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(10, 6, 10, 6)
        strip_layout.setSpacing(18)
        self.p42_headline_labels: dict[str, Any] = {}
        for series_id, caption_text in presenters.headline_captions():
            cell = QVBoxLayout()
            cell.setSpacing(0)
            caption = QLabel(caption_text)
            self.set_theme_role(caption, 'muted')
            value = QLabel('—')
            self.set_theme_role(value, 'metric')
            cell.addWidget(caption)
            cell.addWidget(value)
            strip_layout.addLayout(cell)
            self.p42_headline_labels[series_id] = value
        strip_layout.addStretch(1)
        return strip

    def _p42_build_overview_tab(self, settings: Any) -> Any:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 8, 0, 0)
        tab_layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel('Group'))
        self.p42_group_filter = QComboBox()
        for label, value in presenters.GROUP_FILTERS:
            self.p42_group_filter.addItem(label, value)
        saved = self.p42_group_filter.findData(str(settings.get('group_filter', 'all')))
        if saved >= 0:
            self.p42_group_filter.setCurrentIndex(saved)
        self.p42_group_filter.currentIndexChanged.connect(self._p42_on_group_filter_changed)
        filters.addWidget(self.p42_group_filter)

        filters.addWidget(QLabel('Search'))
        self.p42_search_input = QLineEdit()
        self.p42_search_input.setPlaceholderText('Indicator or FRED id')
        self.p42_search_input.setFixedWidth(190)
        self.p42_search_input.setText(str(settings.get('search', '')))
        self.p42_search_input.textChanged.connect(self._p42_on_search_changed)
        filters.addWidget(self.p42_search_input)

        self.p42_hide_unavailable = QCheckBox('Hide unavailable')
        self.p42_hide_unavailable.setToolTip(
            'Hide indicators whose provider returned nothing on this network, so the tables show '
            'only series that actually loaded.'
        )
        self.p42_hide_unavailable.setChecked(bool(settings.get('hide_unavailable', True)))
        self.p42_hide_unavailable.toggled.connect(self._p42_on_hide_unavailable_changed)
        filters.addWidget(self.p42_hide_unavailable)
        filters.addStretch(1)

        self.p42_overview_table = self._p42_new_table(presenters.OVERVIEW_HEADERS, _P42_OVERVIEW_COLUMN_WIDTHS)
        tab_layout.addLayout(filters)
        tab_layout.addWidget(self.p42_overview_table, 1)
        return tab

    def _p42_build_group_tab(self, group: str) -> Any:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 8, 0, 0)
        tab_layout.setSpacing(8)

        table = self._p42_new_table(presenters.GROUP_HEADERS, _P42_GROUP_COLUMN_WIDTHS)
        table.itemSelectionChanged.connect(lambda name=group: self._p42_on_group_selection_changed(name))
        self._p42_group_tables[group] = table

        chart_title = QLabel('Select an indicator')
        self.set_theme_role(chart_title, 'section_title')
        self._p42_group_titles[group] = chart_title

        axis = DateAxisItem(orientation='bottom')
        plot = pg.PlotWidget(axisItems={'bottom': axis})
        plot.getPlotItem().setMenuEnabled(False)
        plot.getPlotItem().hideAxis('left')
        plot.getPlotItem().showAxis('right')
        plot.setMinimumHeight(160)
        self._p42_group_plots[group] = plot
        self._p42_group_axes[group] = axis

        if group == 'Rates':
            tab_layout.addWidget(self._p42_build_curve_panel(), 2)
        tab_layout.addWidget(table, 3)
        tab_layout.addWidget(chart_title)
        tab_layout.addWidget(plot, 2)
        return tab

    def _p42_build_curve_panel(self) -> Any:
        panel = QFrame()
        self.set_theme_role(panel, 'panel')
        panel_layout = QHBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(4)
        self.p42_curve_title = QLabel('Treasury curve')
        self.set_theme_role(self.p42_curve_title, 'section_title')
        left.addWidget(self.p42_curve_title)
        self.p42_curve_table = self._p42_new_table(presenters.CURVE_HEADERS, _P42_CURVE_COLUMN_WIDTHS)
        self.p42_curve_table.setSortingEnabled(False)
        self.p42_curve_table.setMinimumWidth(320)
        left.addWidget(self.p42_curve_table, 1)
        panel_layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.p42_curve_summary = QLabel('Treasury curve unavailable.')
        self.p42_curve_summary.setWordWrap(True)
        self.set_theme_role(self.p42_curve_summary, 'status_muted')
        right.addWidget(self.p42_curve_summary)
        self.p42_curve_percent_axis = PercentAxisItem(orientation='right')
        self.p42_curve_plot = pg.PlotWidget(axisItems={'right': self.p42_curve_percent_axis})
        self.p42_curve_plot.getPlotItem().setMenuEnabled(False)
        self.p42_curve_plot.getPlotItem().hideAxis('left')
        self.p42_curve_plot.getPlotItem().showAxis('right')
        self.p42_curve_plot.setMinimumHeight(170)
        right.addWidget(self.p42_curve_plot, 1)
        panel_layout.addLayout(right, 2)
        return panel

    def _p42_new_table(self, headers: Any, widths: Any) -> Any:
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
        # Qt defaults the sort indicator to column 0 descending, and ``render_table_rows``
        # re-applies whatever indicator is set once it finishes inserting. Left alone that would
        # reorder the treasury tenors alphabetically instead of by maturity, so clear the
        # indicator and let catalog order stand until the user clicks a header.
        table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        return table

    # ------------------------------------------------------------------ sub-tabs

    def _p42_active_subtab_key(self) -> str:
        if not hasattr(self, 'p42_tabs'):
            return 'overview'
        current = self.p42_tabs.currentWidget()
        for key, widget in getattr(self, '_p42_tab_widgets', {}).items():
            if widget is current:
                return key
        return 'overview'

    def _p42_on_subtab_changed(self, _index: Any = None) -> None:
        self._p42_persist_settings()
        self._p42_sync_status_bar()

    # ------------------------------------------------------------------ settings

    def _p42_persist_settings(self) -> None:
        if not hasattr(self, 'p42_tabs'):
            return
        payload = {
            'active_tab': self._p42_active_subtab_key(),
            'lookback_key': str(self.p42_lookback_combo.currentData() or '5y'),
            'group_filter': str(self.p42_group_filter.currentData() or 'all'),
            'search': self.p42_search_input.text(),
            'hide_unavailable': bool(self.p42_hide_unavailable.isChecked()),
        }
        try:
            self._p42_settings = save_economic_page_settings(payload)
        except Exception:
            logger.debug('Economic page settings could not be persisted', exc_info=True)

    def _p42_on_group_filter_changed(self, _index: Any = None) -> None:
        self._p42_persist_settings()
        self._p42_render_overview_table()

    def _p42_on_search_changed(self, _text: Any = None) -> None:
        self._p42_persist_settings()
        self._p42_render_overview_table()

    def _p42_on_hide_unavailable_changed(self, _checked: Any = None) -> None:
        self._p42_persist_settings()
        self._p42_render_payload()

    def _p42_on_lookback_changed(self, _index: Any = None) -> None:
        self._p42_persist_settings()
        for group in ECONOMIC_GROUPS:
            self._p42_render_group_chart(group)

    def _p42_lookback_years(self) -> int:
        key = str(self.p42_lookback_combo.currentData() or '5y') if hasattr(self, 'p42_lookback_combo') else '5y'
        for _label, candidate, years in _P42_LOOKBACKS:
            if candidate == key:
                return years
        return 5

    # ------------------------------------------------------------------ fetching

    def _p42_manual_refresh(self) -> None:
        self._p42_request_fetch(force=False)

    def _p42_force_refresh(self) -> None:
        self._p42_request_fetch(force=True)

    def _p42_refresh_series(self, *, force: bool = False) -> None:
        """Refresh entry point for the Overview and group sub-tabs."""
        self._p42_request_fetch(force=bool(force))

    def _p42_refresh_curve(self, *, force: bool = False) -> None:
        """Refresh entry point for the Rates sub-tab.

        The curve is derived from the same payload as every other tab, so this is the same
        fetch — it exists so the refresh route can name the active sub-tab honestly.
        """
        self._p42_request_fetch(force=bool(force))

    def _p42_request_fetch(self, *, force: bool = False) -> bool:
        if getattr(self, '_refresh_shutdown', False):
            return False
        coordinator = self._p42_get_refresh_coordinator()
        signature = (bool(force),)
        token, should_start = coordinator.request(_P42_FETCH_KEY, signature)
        context = {'force': bool(force)}
        contexts = getattr(self, '_p42_fetch_contexts', {})
        contexts[token.generation] = context
        retained = {
            item.generation
            for item in (coordinator.active_token(_P42_FETCH_KEY), coordinator.pending_token(_P42_FETCH_KEY))
            if item is not None
        }
        self._p42_fetch_contexts = {key: value for key, value in contexts.items() if key in retained}
        if not should_start:
            # A newer request replaces any queued one, so the latest click always wins instead
            # of being refused outright.
            self._p42_update_status('Refresh queued; it will start when the current one finishes.', 'info')
            return False
        return self._p42_launch_fetch(token, context)

    def _p42_launch_fetch(self, token: Any, context: dict[str, Any]) -> bool:
        worker = EconomicDataWorker(self._p42_get_service(), force=bool(context.get('force')))
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._p42_on_fetch_progress)
        self._connect_worker_signal(worker.finished, self._p42_on_data_ready, token)
        self._connect_worker_signal(worker.error, self._p42_on_fetch_error, token)
        self._connect_worker_signal(worker.cancelled, self._p42_on_fetch_cancelled, token)
        for signal in (worker.finished, worker.error, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._connect_worker_signal(thread.finished, self._p42_cleanup_worker, worker, thread)
        self._p42_worker = worker
        self._p42_thread = thread
        self._p42_active_token = token
        self._p42_set_busy(True)
        self._p42_update_status('Pulling series from FRED…', 'warning')
        thread.start()
        return True

    def _p42_cleanup_worker(self, worker: Any, thread: Any) -> None:
        if getattr(self, '_p42_worker', None) is worker:
            self._p42_worker = None
        if getattr(self, '_p42_thread', None) is thread:
            self._p42_thread = None

    def _p42_set_busy(self, busy: bool) -> None:
        if hasattr(self, 'p42_refresh_btn'):
            self.p42_refresh_btn.setEnabled(not busy)
            self.p42_refresh_btn.setText('Fetching…' if busy else 'Refresh')
        if hasattr(self, 'p42_force_btn'):
            self.p42_force_btn.setEnabled(not busy)
        if hasattr(self, 'p42_progress'):
            self.p42_progress.setVisible(busy)
            if busy:
                self.p42_progress.setRange(0, 0)
                self.p42_progress.setFormat('Contacting FRED…')

    def _p42_on_fetch_progress(self, completed: int, total: int, label: str) -> None:
        if not hasattr(self, 'p42_progress') or getattr(self, '_refresh_shutdown', False):
            return
        bound = max(int(total), 1)
        self.p42_progress.setRange(0, bound)
        self.p42_progress.setValue(min(max(int(completed), 0), bound))
        self.p42_progress.setFormat(f'{completed}/{total} — {label}')

    def _p42_finish_fetch(self, token: Any) -> None:
        """Release the single-flight slot and start whatever was queued behind it."""
        coordinator = getattr(self, '_refresh_coordinator', None)
        if coordinator is None:
            return
        contexts = getattr(self, '_p42_fetch_contexts', {})
        contexts.pop(getattr(token, 'generation', None), None)
        next_token = coordinator.complete(token)
        if next_token is not None:
            next_context = contexts.get(next_token.generation)
            if isinstance(next_context, dict):
                self._p42_launch_fetch(next_token, next_context)
                return
            coordinator.complete(next_token)
        self._p42_active_token = None
        self._p42_set_busy(False)

    def _p42_on_data_ready(self, token: Any, payload: Any) -> None:
        if getattr(self, '_refresh_shutdown', False):
            return
        coordinator = getattr(self, '_refresh_coordinator', None)
        try:
            accepted = coordinator is None or coordinator.is_active(token)
            if accepted and isinstance(payload, dict):
                self._p42_payload = payload
                self._p42_record_health(payload)
            current = coordinator is None or coordinator.is_current(token)
            if accepted and current:
                self._p42_publish_results()
        except RuntimeError:
            return
        finally:
            self._p42_finish_fetch(token)

    def _p42_publish_results(self) -> None:
        """Render and announce a completed fetch, deferring both if the page is off screen."""
        if not self._p42_page_is_visible():
            self._p42_render_pending = True
            return
        self._p42_render_payload()
        text, status = describe_freshness(self._p42_payload)
        self._p42_update_status(text, status)

    def _p42_on_fetch_error(self, token: Any, message: Any) -> None:
        if getattr(self, '_refresh_shutdown', False):
            return
        coordinator = getattr(self, '_refresh_coordinator', None)
        try:
            if coordinator is None or coordinator.is_current(token):
                text = f'Economic refresh failed: {message}'
                if self._p42_page_is_visible():
                    self._p42_update_status(text, 'negative')
                else:
                    self._p42_pending_error = str(message)
            if hasattr(self, '_record_data_health_exception'):
                self._record_data_health_exception('Economic', message)
        except RuntimeError:
            return
        finally:
            self._p42_finish_fetch(token)

    def _p42_on_fetch_cancelled(self, token: Any) -> None:
        if getattr(self, '_refresh_shutdown', False):
            return
        try:
            self._p42_update_status('Economic refresh cancelled.', 'muted')
        except RuntimeError:
            return
        finally:
            self._p42_finish_fetch(token)

    def _p42_record_health(self, payload: Any) -> None:
        if not hasattr(self, '_record_data_health_event'):
            return
        missing = [str(item) for item in (payload or {}).get('missing') or []]
        if not missing:
            return
        try:
            self._record_data_health_event(
                'Economic',
                f'{len(missing)} FRED series returned no observations.',
                severity='issue',
                symbols=sorted(missing),
            )
        except Exception:
            logger.debug('Economic data-health reporting failed', exc_info=True)

    # ------------------------------------------------------------------ rendering

    def _p42_theme_colors(self) -> dict[str, str]:
        return {
            'positive': self.theme_color('accent_positive'),
            'negative': self.theme_color('accent_negative'),
            'warning': self.theme_color('warning'),
            'secondary': self.theme_color('text_secondary'),
            'accent': self.theme_color('accent'),
        }

    def _p42_all_rows(self) -> list[dict[str, Any]]:
        payload = getattr(self, '_p42_payload', None)
        rows = (payload or {}).get('rows', []) if isinstance(payload, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    def _p42_hides_unavailable(self) -> bool:
        toggle = getattr(self, 'p42_hide_unavailable', None)
        return True if toggle is None else bool(toggle.isChecked())

    def _p42_visible_overview_rows(self) -> list[dict[str, Any]]:
        rows = self._p42_all_rows()
        if self._p42_hides_unavailable():
            rows = presenters.drop_unavailable(rows)
        key = str(self.p42_group_filter.currentData() or 'all') if hasattr(self, 'p42_group_filter') else 'all'
        rows = presenters.filter_rows(rows, key)
        text = self.p42_search_input.text() if hasattr(self, 'p42_search_input') else ''
        return presenters.search_rows(rows, text)

    def _p42_render_overview_table(self) -> None:
        if not hasattr(self, 'p42_overview_table'):
            return
        rows = presenters.build_overview_rows(
            self._p42_visible_overview_rows(),
            colors=self._p42_theme_colors(),
            series_role=_P42_SERIES_ROLE,
        )
        render_table_rows(self.p42_overview_table, rows)

    def _p42_render_group_table(self, group: str) -> None:
        table = self._p42_group_tables.get(group) if hasattr(self, '_p42_group_tables') else None
        if table is None:
            return
        source_rows = self._p42_all_rows()
        if self._p42_hides_unavailable():
            source_rows = presenters.drop_unavailable(source_rows)
        blocked = table.blockSignals(True)
        try:
            rows = presenters.build_group_rows(
                presenters.rows_for_group(source_rows, group),
                colors=self._p42_theme_colors(),
                series_role=_P42_SERIES_ROLE,
            )
            render_table_rows(table, rows)
        finally:
            table.blockSignals(blocked)

    def _p42_on_group_selection_changed(self, group: str) -> None:
        table = self._p42_group_tables.get(group) if hasattr(self, '_p42_group_tables') else None
        if table is None:
            return
        items = table.selectedItems()
        if not items:
            return
        series_id = table.item(items[0].row(), 0)
        if series_id is None:
            return
        value = series_id.data(_P42_SERIES_ROLE)
        if value:
            self._p42_selected_series[group] = str(value)
            self._p42_render_group_chart(group)

    def _p42_selected_row(self, group: str) -> dict[str, Any] | None:
        rows = presenters.rows_for_group(self._p42_all_rows(), group)
        # Default the chart to a series that actually has history; falling back to the first
        # catalog entry would draw an empty plot whenever that provider is unreachable.
        populated = [row for row in rows if row.get('history')]
        rows = populated or rows
        if not rows:
            return None
        wanted = str(getattr(self, '_p42_selected_series', {}).get(group) or '')
        for row in rows:
            if str(row.get('series_id')) == wanted:
                return row
        return rows[0]

    def _p42_render_group_chart(self, group: str) -> None:
        plot = self._p42_group_plots.get(group) if hasattr(self, '_p42_group_plots') else None
        if plot is None:
            return
        plot.clear()
        row = self._p42_selected_row(group)
        title = self._p42_group_titles.get(group)
        if row is None:
            if title is not None:
                title.setText('Select an indicator')
            return
        if title is not None:
            title.setText(f"{row.get('label', '')} · {row.get('source') or row.get('series_id', '')}")
        dates, values = presenters.history_series(row, years=self._p42_lookback_years())
        if not values:
            return
        axis = self._p42_group_axes.get(group)
        if axis is not None:
            axis.set_dates(list(dates), '1d')
        plot.plot(list(range(len(values))), values, pen=self.theme_pen('accent', width=2))
        if min(values) < 0.0 < max(values):
            plot.addItem(pg.InfiniteLine(
                pos=0.0,
                angle=0,
                pen=self.theme_pen('chart_reference', width=1, style=Qt.PenStyle.DashLine),
            ))

    def _p42_render_curve(self) -> None:
        if not hasattr(self, 'p42_curve_plot'):
            return
        payload = getattr(self, '_p42_payload', None)
        curve = (payload or {}).get('yield_curve', {}) if isinstance(payload, dict) else {}
        render_table_rows(self.p42_curve_table, presenters.build_curve_rows(curve, colors=self._p42_theme_colors()))
        summary = presenters.describe_curve(curve)
        status = 'negative' if (curve or {}).get('inverted_2s10s') else 'muted'
        self.set_status_text(self.p42_curve_summary, summary, status=status)
        self.p42_curve_plot.clear()
        tenors = [item for item in (curve or {}).get('tenors', []) if isinstance(item, dict)]
        if not tenors:
            return
        positions = list(range(len(tenors)))
        # The x axis is tenor, not time, so the ticks are the tenor labels themselves.
        self.p42_curve_plot.getPlotItem().getAxis('bottom').setTicks(
            [[(index, str(item.get('label') or '')) for index, item in enumerate(tenors)]]
        )
        yields = [float(item.get('yield') or 0.0) for item in tenors]
        self.p42_curve_plot.plot(
            positions,
            yields,
            pen=self.theme_pen('accent', width=2),
            symbol='o',
            symbolSize=6,
            symbolBrush=self.theme_color('accent'),
        )

    def _p42_render_payload(self) -> None:
        if not hasattr(self, 'p42_overview_table'):
            return
        self._p42_render_overview_table()
        for group in ECONOMIC_GROUPS:
            self._p42_render_group_table(group)
            self._p42_render_group_chart(group)
        self._p42_render_curve()
        headlines = presenters.summarize_headlines(getattr(self, '_p42_payload', None))
        for series_id, label in getattr(self, 'p42_headline_labels', {}).items():
            label.setText(headlines.get(series_id, '—'))
        if hasattr(self, 'p42_footer_lbl'):
            self.p42_footer_lbl.setText(presenters.missing_summary(getattr(self, '_p42_payload', None)))

    # ------------------------------------------------------------------ status

    def _p42_update_status(self, text: str, status: str) -> None:
        if hasattr(self, 'p42_status_lbl'):
            self.set_status_text(self.p42_status_lbl, text, status=status)
        # Only the visible page owns the shared status bar.
        if hasattr(self, 'status_bar') and self._p42_page_is_visible():
            self.set_status_text(self.status_bar, text, status=status)

    def _p42_sync_status_bar(self) -> None:
        if hasattr(self, 'status_bar') and hasattr(self, 'p42_status_lbl'):
            self.set_status_text(
                self.status_bar,
                self.p42_status_lbl.text(),
                status=str(self.p42_status_lbl.property('bt_status') or 'muted'),
            )

    # ------------------------------------------------------------------ hooks

    def _p42_on_show(self) -> None:
        if getattr(self, '_p42_render_pending', False):
            self._p42_render_pending = False
            self._p42_render_payload()
        # The status line always describes the payload actually on screen, whether or not this
        # visit drained a deferred render.
        text, status = describe_freshness(getattr(self, '_p42_payload', None))
        self._p42_update_status(text, status)
        pending_error = str(getattr(self, '_p42_pending_error', '') or '')
        if pending_error:
            self._p42_pending_error = ''
            self._p42_update_status(f'Economic refresh failed: {pending_error}', 'negative')
        if not getattr(self, '_p42_payload', None) and not getattr(self, '_p42_active_token', None):
            # First visit with an empty cache: fetch rather than showing an empty grid.
            self._p42_request_fetch(force=False)
        self._p42_sync_status_bar()

    def _apply_economic_theme(self) -> None:
        if not hasattr(self, 'p42_overview_table'):
            return
        for plot in list(getattr(self, '_p42_group_plots', {}).values()):
            self.style_plot_widget(plot)
        curve_plot = getattr(self, 'p42_curve_plot', None)
        if curve_plot is not None:
            self.style_plot_widget(curve_plot)
        # Row colours are baked into the items, so a theme change has to rebuild them.
        self._p42_render_payload()
        if hasattr(self, 'p42_status_lbl'):
            self.set_status_text(
                self.p42_status_lbl,
                self.p42_status_lbl.text(),
                status=str(self.p42_status_lbl.property('bt_status') or 'muted'),
            )
