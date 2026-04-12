from __future__ import annotations
from typing import Any
from ..compat import *

class WindowLifecycleMixin:
    _STARTUP_SESSION_RESTORE_INITIAL_DELAY_MS = 350
    _STARTUP_SESSION_RESTORE_STEP_MS = 250

    def _get_tzinfo(self, idx: Any) -> Any:
        """Resolve a UI timezone selection into a tzinfo object."""
        if idx is None or idx < 0 or idx >= len(self._tz_choices):
            idx = 0
        _, zone_name = self._tz_choices[idx]
        if zone_name is None:
            return datetime.datetime.now().astimezone().tzinfo
        return ZoneInfo(zone_name)

    def _now_for_timezone_index(self, idx: Any) -> Any:
        """Return a timezone-aware current datetime for the selected zone."""
        tzinfo = self._get_tzinfo(idx)
        return datetime.datetime.now(tzinfo) if tzinfo else datetime.datetime.now().astimezone()

    def _register_navigation_pages(self) -> None:
        """Handle register navigation pages."""
        self._pages.clear()
        self._register_page(0, self.btn_page1)
        self._register_page(1, self.btn_page4, on_show=self._p4_on_show if hasattr(self, '_p4_on_show') else None)
        self._register_page(2, self.btn_page6)
        self._register_page(3, self.btn_page7)
        self._register_page(4, self.btn_page3, on_show=lambda: self.p3_crawler_timer.start(40) if hasattr(self, 'p3_crawler_timer') else None, on_hide=lambda: self.p3_crawler_timer.stop() if hasattr(self, 'p3_crawler_timer') else None)
        self._register_page(5, self.btn_page8, on_show=self._p8_on_show)
        self._register_page(6, self.btn_page12, on_show=self._stocks_on_show)
        self._register_page(7, self.btn_page2, on_show=lambda: self._p2_relayout_charts() if hasattr(self, '_p2_relayout_charts') else None)
        self._register_page(8, self.btn_page10, on_show=self._p10_on_show)
        self._register_page(9, self.btn_page11, on_show=self._mc_on_show)
        self._register_page(10, self.btn_page5)
        self._register_page(11, self.btn_page13)
        self._register_page(12, self.btn_page14, on_show=self._p14_refresh)
        self._register_page(13, self.btn_page15, on_show=self._p15_refresh)
        self._register_page(14, self.btn_page16, on_show=self._p16_on_show)
        self._register_page(15, self.btn_page17, on_show=self._p17_on_show if hasattr(self, '_p17_on_show') else None)
        self._register_page(16, self.btn_page9)
        self._refresh_main_tab_picker_items()

    def _is_current_page(self, page: Any) -> bool:
        """Return whether the provided stacked page is currently visible."""
        return hasattr(self, 'stacked_widget') and page is not None and self.stacked_widget.currentWidget() is page

    def resizeEvent(self, event: Any) -> None:
        """Handle resizeEvent."""
        super().resizeEvent(event)
        if hasattr(self, '_dashboard_fit_portfolio_table_height'):
            if not hasattr(self, 'stacked_widget') or self._is_current_page(getattr(self, 'page1', None)):
                self._dashboard_fit_portfolio_table_height()
        if hasattr(self, '_p4_apply_portfolio_table_widths') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page4', None)):
                self._p4_apply_portfolio_table_widths()
        if hasattr(self, '_p2_relayout_charts') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page2', None)):
                self._p2_relayout_charts()
        if hasattr(self, '_p8_relayout_cards') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page8', None)):
                self._p8_relayout_cards()
        if hasattr(self, '_p7_apply_detail_table_widths') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page7', None)):
                self._p7_apply_detail_table_widths()
        if hasattr(self, '_p17_refresh_image_preview') and hasattr(self, 'stacked_widget'):
            if self._is_current_page(getattr(self, 'page17', None)):
                self._p17_refresh_image_preview()

    def _register_page(self, index: Any, btn: Any, on_show: Any=None, on_hide: Any=None) -> None:
        """Register a page in the nav system. Wires the button and stores lifecycle callbacks."""
        self._pages[index] = {'btn': btn, 'on_show': on_show, 'on_hide': on_hide}
        btn.clicked.connect(partial(self.switch_page, index))

    def showEvent(self, event: Any) -> None:
        """Start deferred startup work only after the window has been shown once."""
        super().showEvent(event)
        if getattr(self, '_startup_show_completed', False):
            return
        self._startup_show_completed = True
        self._startup_profiler_stamp('window_shown')
        profiler = getattr(self, '_startup_profiler', None)
        if profiler is not None:
            profiler.log_summary()
        self._schedule_startup_refresh()
        self._schedule_startup_page_prefetches()
        self._schedule_startup_session_restores()
        self._start_lazy_warmup()

    def _schedule_startup_refresh(self) -> None:
        """Queue the first dashboard refresh for the next event turn after first paint."""
        if getattr(self, '_startup_refresh_pending', False):
            return
        self._startup_refresh_pending = True
        QTimer.singleShot(0, self._run_startup_refresh)

    def _run_startup_refresh(self) -> None:
        """Run the deferred startup refresh once the window is visible."""
        self._startup_refresh_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        self._startup_profiler_stamp('startup_refresh_start')
        self.refresh_data(force=True)

    def _schedule_startup_page_prefetches(self) -> None:
        """Queue eager post-show page data work without blocking first paint."""
        if getattr(self, '_startup_page_prefetch_pending', False):
            return
        self._startup_page_prefetch_pending = True
        QTimer.singleShot(0, self._run_startup_page_prefetches)

    def _run_startup_page_prefetches(self) -> None:
        """Kick off background data loads for startup-priority secondary pages."""
        self._startup_page_prefetch_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        self._ensure_page_initialized(5)
        self._call_if_page_initialized(
            '_p8_request_refresh',
            page_attr='page8',
            status_text='Loading sector data...',
        )

    def _startup_session_restore_specs(self) -> list[dict[str, Any]]:
        """Return the tab-session restore tasks that should run after first paint."""
        specs = [
            {'tab_key': 'stocks', 'page_index': 6, 'restore_method': '_stocks_restore_startup_session'},
            {'tab_key': 'fundamentals', 'page_index': 7, 'restore_method': '_p2_restore_startup_session'},
            {'tab_key': 'options', 'page_index': 10, 'restore_method': '_p5_restore_startup_session'},
            {'tab_key': 'etf', 'page_index': 11, 'restore_method': '_p13_restore_startup_session'},
            {'tab_key': 'youtube', 'page_index': 14, 'restore_method': '_p16_restore_startup_session'},
        ]
        queue = []
        for spec in specs:
            snapshot = self._get_tab_session_snapshot(spec['tab_key']) if hasattr(self, '_get_tab_session_snapshot') else None
            if snapshot:
                queue.append({**spec, 'snapshot': snapshot})
        return queue

    def _schedule_startup_session_restores(self) -> None:
        """Queue hidden last-session tab restores after the dashboard has started loading."""
        if getattr(self, '_startup_session_restore_pending', False):
            return
        queue = self._startup_session_restore_specs()
        self._startup_session_restore_queue = list(queue)
        if not queue:
            return
        self._startup_session_restore_pending = True
        QTimer.singleShot(self._STARTUP_SESSION_RESTORE_INITIAL_DELAY_MS, self._run_startup_session_restore_step)

    def _run_startup_session_restore_step(self) -> None:
        """Build, restore, and silently refresh one cached tab at a time."""
        self._startup_session_restore_pending = False
        if not getattr(self, '_startup_show_completed', False) or not self.isVisible():
            return
        queue = list(getattr(self, '_startup_session_restore_queue', []))
        if not queue:
            return
        current = queue.pop(0)
        self._startup_session_restore_queue = queue
        try:
            self._ensure_page_initialized(current.get('page_index'))
            restore_fn = getattr(self, str(current.get('restore_method', '') or ''), None)
            if callable(restore_fn):
                restore_fn(current.get('snapshot'))
        except Exception:
            logger.exception('Startup session restore failed for %s.', current.get('tab_key'))
        if self._startup_session_restore_queue:
            self._startup_session_restore_pending = True
            QTimer.singleShot(self._STARTUP_SESSION_RESTORE_STEP_MS, self._run_startup_session_restore_step)

    def _start_lazy_warmup(self) -> None:
        """Warm secondary pages one at a time after the window becomes interactive."""
        queue = []
        for button in getattr(self, '_nav_buttons', []):
            page_index = self._page_index_for_button(button)
            if page_index in (None, 0) or self._page_initialized(index=page_index):
                continue
            if page_index not in queue:
                queue.append(page_index)
        priority = {
            1: 10,
            2: 20,
            4: 30,
            5: 40,
            6: 50,
            7: 60,
            10: 70,
            11: 80,
            12: 90,
            13: 100,
            14: 110,
            15: 120,
            16: 130,
            8: 140,
            3: 150,
        }
        queue.sort(key=lambda value: priority.get(int(value), 999))
        self._lazy_warmup_queue = queue
        timer = getattr(self, '_lazy_page_warmup_timer', None)
        if timer is None or not queue:
            return
        timer.start(getattr(self, '_LAZY_WARMUP_INITIAL_DELAY_MS', 500))

    def _warm_next_page(self) -> None:
        """Initialize one pending lazy page and reschedule the next warmup step."""
        while getattr(self, '_lazy_warmup_queue', []):
            page_index = self._lazy_warmup_queue.pop(0)
            if self._page_initialized(index=page_index):
                continue
            try:
                with self._startup_profiler_step(f'lazy_page_{int(page_index)}'):
                    self._build_page_now(page_index)
            except Exception:
                logger.exception('Lazy page warmup failed for page index %s.', page_index)
            break
        timer = getattr(self, '_lazy_page_warmup_timer', None)
        if timer is not None and getattr(self, '_lazy_warmup_queue', []):
            timer.start(getattr(self, '_LAZY_WARMUP_STEP_MS', 75))

    def _ensure_page_initialized(self, index: Any) -> None:
        """Synchronously build a lazy page before it becomes visible."""
        if self._page_initialized(index=index):
            return
        self._build_page_now(index)

    def switch_page(self, index: Any, *_: Any) -> None:
        """Switch page."""
        try:
            numeric_index = int(index)
        except (TypeError, ValueError):
            return
        self._ensure_page_initialized(numeric_index)
        self.stacked_widget.setCurrentIndex(numeric_index)
        for i, page in self._pages.items():
            page['btn'].setChecked(i == numeric_index)
            cb = page['on_show'] if i == numeric_index else page['on_hide']
            if cb:
                cb()

    def _refresh_main_tab_picker_items(self) -> None:
        """Sync the top-bar tab picker with the registered main navigation pages."""
        if not hasattr(self, '_tab_picker_list'):
            return
        items = []
        item_map = {}
        for button in getattr(self, '_nav_buttons', []):
            page_index = self._page_index_for_button(button)
            if page_index is None:
                continue
            label = button.text().strip()
            if not label:
                continue
            items.append(label)
            item_map[label.casefold()] = page_index
        self._tab_picker_items = items
        self._tab_picker_map = item_map
        self._filter_tab_picker_items(getattr(self, '_tab_picker_input', None).text() if hasattr(self, '_tab_picker_input') else '')

    def _page_index_for_button(self, button: Any) -> Any:
        """Return the registered page index for a nav button."""
        for index, page in self._pages.items():
            if page.get('btn') is button:
                return index
        return None

    def _find_main_tab_match(self, text: Any) -> Any:
        """Resolve user-entered tab text into a main page index."""
        query = str(text or '').strip()
        if not query:
            return None
        lowered = query.casefold()
        exact = self._tab_picker_map.get(lowered)
        if exact is not None:
            return exact
        for label in self._tab_picker_items:
            if lowered in label.casefold():
                return self._tab_picker_map.get(label.casefold())
        return None

    def _filter_tab_picker_items(self, text: Any) -> None:
        """Filter popup picker rows from the current query text."""
        if not hasattr(self, '_tab_picker_list'):
            return
        query = str(text or '').strip().casefold()
        self._tab_picker_list.clear()
        for label in self._tab_picker_items:
            if not query or query in label.casefold():
                self._tab_picker_list.addItem(label)
        if self._tab_picker_list.count() > 0:
            self._tab_picker_list.setCurrentRow(0)

    def _activate_tab_picker_item(self, item: Any) -> None:
        """Open a page from a popup list selection."""
        label = item.text() if hasattr(item, 'text') else str(item or '')
        page_index = self._find_main_tab_match(label)
        if page_index is None:
            return
        self.switch_page(page_index)
        self._hide_tab_picker()

    def _show_tab_picker(self) -> None:
        """Reveal the top-bar picker and focus it for typed navigation."""
        if not hasattr(self, '_tab_picker_popup'):
            return
        self._refresh_main_tab_picker_items()
        popup_margin = 16
        popup_x = max(self.width() - self._tab_picker_popup.width() - popup_margin, popup_margin)
        popup_pos = self.mapToGlobal(QPoint(popup_x, 52))
        self._tab_picker_popup.move(popup_pos)
        self._tab_picker_input.clear()
        self._filter_tab_picker_items('')
        self._tab_picker_popup.show()
        self._tab_picker_popup.raise_()
        self._tab_picker_popup.activateWindow()
        self._tab_picker_input.setFocus()

    def _current_main_nav_button(self) -> Any:
        """Return the navigation button for the active main page."""
        if not hasattr(self, 'stacked_widget'):
            return None
        return self._pages.get(self.stacked_widget.currentIndex(), {}).get('btn')

    def _hide_tab_picker(self) -> None:
        """Collapse the top-bar picker after selection or cancellation."""
        if not hasattr(self, '_tab_picker_popup'):
            return
        self._tab_picker_popup.hide()
        self._tab_picker_input.clear()
        self._tab_picker_list.clearSelection()
        current_button = self._current_main_nav_button()
        if current_button is not None:
            current_button.setFocus()

    def _is_plain_escape_key(self, event: Any) -> bool:
        """Return whether the event is an unmodified Escape keypress."""
        return (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        )

    def _is_plain_backtick_key(self, event: Any) -> bool:
        """Return whether the event is an unmodified backtick keypress."""
        if event.type() != QEvent.Type.KeyPress or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if str(event.text() or '') == '`':
            return True
        quote_left = getattr(Qt.Key, 'Key_QuoteLeft', None)
        return quote_left is not None and event.key() == quote_left

    def _resolve_main_window_text_input(self, widget: Any) -> Any:
        """Resolve a focused child widget back to an editable main-window text input."""
        current = widget
        while current is not None:
            if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit)):
                if current.window() is not self:
                    return None
                if hasattr(current, 'isReadOnly') and current.isReadOnly():
                    return None
                return current
            if current is self or current is getattr(self, '_tab_picker_popup', None):
                return None
            current = current.parentWidget()
        return None

    def _dismiss_main_window_text_input(self, widget: Any=None, *, focus_current_button: bool=True) -> bool:
        """Exit the active main-window text input and restore non-editing focus."""
        target = self._resolve_main_window_text_input(widget if widget is not None else QApplication.focusWidget())
        if target is None:
            return False
        target.clearFocus()
        if focus_current_button:
            current_button = self._current_main_nav_button()
            if current_button is not None:
                current_button.setFocus()
        return True

    def _handle_global_input_exit_event(self, obj: Any, event: Any) -> bool:
        """Handle app-wide Escape/backtick behavior for text entry widgets."""
        if hasattr(self, '_tab_picker_popup') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event) or self._is_plain_backtick_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            return False
        if self._is_plain_escape_key(event) and self._dismiss_main_window_text_input(obj):
            event.accept()
            return True
        if self._is_plain_backtick_key(event) and self._dismiss_main_window_text_input(obj, focus_current_button=False):
            self._show_tab_picker()
            event.accept()
            return True
        return False

    def _should_handle_main_tab_navigation_keys(self) -> bool:
        """Limit global navigation shortcuts to non-editing contexts."""
        if hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible():
            return False
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return True
        blocked_types = (QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget, QTabWidget)
        widget = focus_widget
        while widget is not None:
            if isinstance(widget, blocked_types):
                return False
            widget = widget.parentWidget()
        return True

    def _step_main_tab(self, direction: int) -> bool:
        """Move between registered main tabs with wraparound."""
        current_index = self.stacked_widget.currentIndex()
        current_pos = None
        for pos, button in enumerate(getattr(self, '_nav_buttons', [])):
            page_index = self._page_index_for_button(button)
            if page_index == current_index:
                current_pos = pos
                break
        if current_pos is None or not self._nav_buttons:
            return False
        next_pos = (current_pos + direction) % len(self._nav_buttons)
        next_index = self._page_index_for_button(self._nav_buttons[next_pos])
        if next_index is None:
            return False
        self.switch_page(next_index)
        return True

    def _handle_main_tab_arrow_shortcut(self, direction: int) -> None:
        """Move between main tabs from a global shortcut when safe to do so."""
        if self._should_handle_main_tab_navigation_keys():
            self._step_main_tab(direction)

    def _handle_tab_picker_shortcut(self) -> None:
        """Open or close the popup tab picker from the global shortcut."""
        if hasattr(self, '_tab_picker_popup') and self._tab_picker_popup.isVisible():
            self._hide_tab_picker()
            return
        if self._should_handle_main_tab_navigation_keys():
            self._show_tab_picker()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Handle picker-specific keyboard and focus behavior before other filters."""
        if hasattr(self, '_tab_picker_popup') and hasattr(self, '_tab_picker_list') and obj in (self._tab_picker_popup, self._tab_picker_input, self._tab_picker_list):
            if self._is_plain_escape_key(event) or self._is_plain_backtick_key(event):
                self._hide_tab_picker()
                event.accept()
                return True
            if obj is self._tab_picker_input and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Down and self._tab_picker_list.count() > 0:
                    self._tab_picker_list.setFocus()
                    self._tab_picker_list.setCurrentRow(max(self._tab_picker_list.currentRow(), 0))
                    event.accept()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._tab_picker_list.currentItem() is not None:
                    self._activate_tab_picker_item(self._tab_picker_list.currentItem())
                    event.accept()
                    return True
            if obj is self._tab_picker_list and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Up and self._tab_picker_list.currentRow() <= 0:
                    self._tab_picker_input.setFocus()
                    event.accept()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._tab_picker_list.currentItem() is not None:
                    self._activate_tab_picker_item(self._tab_picker_list.currentItem())
                    event.accept()
                    return True
            if obj is self._tab_picker_popup and event.type() == QEvent.Type.Hide:
                self._tab_picker_input.clear()
        return super().eventFilter(obj, event)

    def _toggle_time_format(self) -> None:
        """Handle toggle time format."""
        self._time_12h = not self._time_12h
        self.time_fmt_btn.setText('12h' if self._time_12h else '24h')
        self.time_fmt_btn.setChecked(self._time_12h)
        save_time_format(self._time_12h)
        self.update_time()

    def update_time(self, *_: Any) -> None:
        """Update time."""
        now = self._now_for_timezone_index(self.tz_combo.currentIndex())
        if self._time_12h:
            self.time_label.setText(now.strftime('%I:%M:%S %p'))
        else:
            self.time_label.setText(now.strftime('%H:%M:%S'))
        self._refresh_data_collection_label()
        if self._page_initialized(page_attr='page17') and hasattr(self, '_p17_refresh_timestamp_labels'):
            self._p17_refresh_timestamp_labels()

    def _set_data_collection_info(self, sources: Any, collected_at: Any=None) -> None:
        """Persist footer metadata about the latest completed data fetch."""
        source_list = []
        if isinstance(sources, str):
            source_list = [sources]
        else:
            try:
                source_list = list(sources or [])
            except Exception:
                source_list = []
        cleaned = []
        for source in source_list:
            text = str(source or '').strip()
            if text and text not in cleaned:
                cleaned.append(text)
        self._data_collection_sources = cleaned
        if collected_at is None:
            now = self._now_for_timezone_index(self.tz_combo.currentIndex())
            self._data_collection_ts = now.timestamp()
        else:
            try:
                self._data_collection_ts = float(collected_at)
            except Exception:
                self._data_collection_ts = None
        self._refresh_data_collection_label()

    def _refresh_data_collection_label(self) -> None:
        """Refresh the footer label that summarizes the latest collected data."""
        if not hasattr(self, 'data_collection_label'):
            return
        if not self._data_collection_ts:
            self.data_collection_label.setText('Data collected: awaiting first refresh')
            return
        try:
            tzinfo = self._get_tzinfo(self.tz_combo.currentIndex()) if hasattr(self, 'tz_combo') else None
            collected_dt = datetime.datetime.fromtimestamp(float(self._data_collection_ts), tz=tzinfo)
        except Exception:
            self.data_collection_label.setText('Data collected: unavailable')
            return
        sources = ', '.join(self._data_collection_sources) if self._data_collection_sources else 'Unknown source'
        time_fmt = '%b %d, %Y %I:%M:%S %p' if getattr(self, '_time_12h', False) else '%b %d, %Y %H:%M:%S'
        self.data_collection_label.setText(f'Data collected: {sources} | {collected_dt.strftime(time_fmt)}')

    def _on_close_hold_complete(self) -> None:
        """Handle close hold complete."""
        reply = QMessageBox.question(self, 'Close Application', 'Are you sure you want to close Budget Terminal?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.close()

    def closeEvent(self, event: Any) -> None:
        """Closeevent."""
        warmup_timer = getattr(self, '_lazy_page_warmup_timer', None)
        if warmup_timer is not None:
            warmup_timer.stop()
        session_timer = getattr(self, '_session_cache_persist_timer', None)
        if session_timer is not None:
            session_timer.stop()
        app = QApplication.instance()
        global_filter = getattr(self, '_global_input_exit_filter', None)
        if app is not None and global_filter is not None and getattr(self, '_app_keyboard_event_filter_installed', False):
            app.removeEventFilter(global_filter)
            self._app_keyboard_event_filter_installed = False
        main_entry = self._get_portfolio_entry(self.main_portfolio_id)
        main_entry['portfolio'] = self.tickers
        main_entry['chart_slots'] = self.chart_slots
        main_entry['portfolio_tracker'] = self.tracker_data
        active_entry = self._get_portfolio_entry(self.active_portfolio_id)
        active_entry['portfolio'] = getattr(self, 'active_tickers', active_entry.get('portfolio', []))
        active_entry['portfolio_tracker'] = getattr(self, 'active_tracker_data', active_entry.get('portfolio_tracker', {}))
        active_entry['options_tracker'] = self.options_data
        if self._page_initialized(page_attr='page17') and hasattr(self, '_p17_flush_pending_save'):
            self._p17_flush_pending_save()
        if self._page_initialized(page_attr='page17') and hasattr(self, '_p17_finalize_startup_draft_on_close'):
            self._p17_finalize_startup_draft_on_close()
        self._persist_all_portfolios(immediate=True)
        if hasattr(self, '_dashboard_save_state'):
            self._dashboard_save_state()
        if hasattr(self, '_persist_dashboard_state'):
            self._persist_dashboard_state(immediate=True)
        if self._page_initialized(page_attr='page12') and hasattr(self, '_stocks_save_session_snapshot'):
            self._stocks_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page2') and hasattr(self, '_p2_save_session_snapshot'):
            self._p2_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page5') and hasattr(self, '_p5_save_session_snapshot'):
            self._p5_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page13') and hasattr(self, '_p13_save_session_snapshot'):
            self._p13_save_session_snapshot(immediate=True)
        if self._page_initialized(page_attr='page16') and hasattr(self, '_p16_save_session_snapshot'):
            self._p16_save_session_snapshot(immediate=True)
        if hasattr(self, '_persist_tab_session_cache'):
            self._persist_tab_session_cache(immediate=True)
        save_networth_data(self.networth_data)
        executor = getattr(self, '_options_fetch_executor', None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        mc_executor = getattr(self, '_mc_executor', None)
        if mc_executor is not None:
            mc_executor.shutdown(wait=False, cancel_futures=True)
        compare_executor = getattr(self, '_p10_compare_executor', None)
        if compare_executor is not None:
            compare_executor.shutdown(wait=False, cancel_futures=True)
        handler = getattr(self, '_session_log_handler', None)
        if handler is not None:
            logger.removeHandler(handler)
            self._session_log_handler = None
        event.accept()

    def take_screenshot(self) -> None:
        """Handle take screenshot."""
        screen = QApplication.primaryScreen()
        if screen is None:
            QMessageBox.warning(self, 'Screenshot Failed', 'No screen is available for capturing a screenshot.')
            return
        screenshot = screen.grabWindow(self.winId())
        if screenshot.isNull():
            QMessageBox.warning(self, 'Screenshot Failed', 'The screenshot capture returned an empty image.')
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            QMessageBox.warning(self, 'Screenshot Failed', 'Clipboard access is unavailable.')
            return
        clipboard.setPixmap(screenshot)
        self.set_status_text(self.status_bar, 'Screenshot copied to clipboard', status='positive')
