from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.paths import user_data_path

class WindowLifecycleMixin:
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
        self._register_page(0, self.btn_page1)
        self._register_page(1, self.btn_page4)
        self._register_page(2, self.btn_page6)
        self._register_page(3, self.btn_page7)
        self._register_page(4, self.btn_page3, on_show=lambda: self.p3_crawler_timer.start(40) if hasattr(self, 'p3_crawler_timer') else None, on_hide=lambda: self.p3_crawler_timer.stop() if hasattr(self, 'p3_crawler_timer') else None)
        self._register_page(5, self.btn_page8)
        self._register_page(6, self.btn_page10, on_show=self._p10_on_show)
        self._register_page(7, self.btn_page2, on_show=lambda: self._p2_relayout_charts() if hasattr(self, '_p2_relayout_charts') else None)
        self._register_page(8, self.btn_page5)
        self._register_page(9, self.btn_page9)

    def resizeEvent(self, event: Any) -> None:
        """Handle resizeEvent."""
        super().resizeEvent(event)
        if self.last_data:
            self.repopulate_portfolio()
        if hasattr(self, '_p2_relayout_charts') and hasattr(self, 'stacked_widget'):
            if self.stacked_widget.currentIndex() == 7:
                self._p2_relayout_charts()
        if hasattr(self, '_p8_relayout_cards') and hasattr(self, 'stacked_widget'):
            if self.stacked_widget.currentIndex() == 5:
                self._p8_relayout_cards()

    def _register_page(self, index: Any, btn: Any, on_show: Any=None, on_hide: Any=None) -> None:
        """Register a page in the nav system. Wires the button and stores lifecycle callbacks."""
        self._pages[index] = {'btn': btn, 'on_show': on_show, 'on_hide': on_hide}
        btn.clicked.connect(partial(self.switch_page, index))

    def switch_page(self, index: Any, *_: Any) -> None:
        """Switch page."""
        self.stacked_widget.setCurrentIndex(index)
        for i, page in self._pages.items():
            page['btn'].setChecked(i == index)
            cb = page['on_show'] if i == index else page['on_hide']
            if cb:
                cb()

    def _toggle_time_format(self) -> None:
        """Handle toggle time format."""
        self._time_12h = not self._time_12h
        self.time_fmt_btn.setText('12h' if self._time_12h else '24h')
        self.time_fmt_btn.setChecked(self._time_12h)
        self.update_time()

    def update_time(self, *_: Any) -> None:
        """Update time."""
        now = self._now_for_timezone_index(self.tz_combo.currentIndex())
        if self._time_12h:
            self.time_label.setText(now.strftime('%I:%M:%S %p'))
        else:
            self.time_label.setText(now.strftime('%H:%M:%S'))
        self._refresh_data_collection_label()

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
        main_entry = self._get_portfolio_entry(self.main_portfolio_id)
        main_entry['portfolio'] = self.tickers
        main_entry['chart_slots'] = self.chart_slots
        main_entry['portfolio_tracker'] = self.tracker_data
        active_entry = self._get_portfolio_entry(self.active_portfolio_id)
        active_entry['portfolio'] = getattr(self, 'active_tickers', active_entry.get('portfolio', []))
        active_entry['portfolio_tracker'] = getattr(self, 'active_tracker_data', active_entry.get('portfolio_tracker', {}))
        active_entry['options_tracker'] = self.options_data
        self._persist_all_portfolios()
        save_networth_data(self.networth_data)
        event.accept()

    def take_screenshot(self) -> None:
        """Handle take screenshot."""
        screen = QApplication.primaryScreen()
        screenshot = screen.grabWindow(self.winId())
        folder = user_data_path('screenshots')
        folder.mkdir(exist_ok=True)
        path = folder / f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        screenshot.save(str(path), 'png')
