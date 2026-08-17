from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.services.up_down import (
    UP_DOWN_INTERVAL_LABELS,
    UP_DOWN_INTERVALS,
    UpDownDataService,
    normalize_up_down_symbols,
    sort_up_down_rows,
)
from budget_terminal_app.mixins.portfolio_presenters import analyst_target_cell_text_and_sort
from budget_terminal_app.widgets.batched_render import cancel_batched, run_batched


P27_MAX_WORKERS = 1
P27_SOURCES: tuple[tuple[str, str], ...] = (
    ("portfolio", "Portfolio"),
    ("spy", "SPY Holdings"),
    ("qqq", "QQQ Holdings"),
    ("custom", "Custom"),
)
P27_HOLDINGS_ETFS = {"spy": "SPY", "qqq": "QQQ"}
P27_TABLE_COLUMNS = (
    "#",
    "Ticker",
    "Name",
    "Last Close",
    "Interval Return",
    "Trading Days",
    "Days Up",
    "Days Down",
    "Price Targets",
)
P27_NUMERIC_ROLE = Qt.ItemDataRole.UserRole
P27_SOURCE_LABELS = {key: label for key, label in P27_SOURCES}


class _P27NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by the stored numeric value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            left = float(self.data(P27_NUMERIC_ROLE))
            right = float(other.data(P27_NUMERIC_ROLE))
            return left < right
        except Exception:
            return super().__lt__(other)


class UpDownPageMixin:
    def _p27_has_page_visibility_api(self) -> bool:
        """Return whether the host provides the real window visibility guard."""
        return callable(getattr(self, "_is_current_page", None))

    def _p27_page_is_visible(self) -> bool:
        """Treat small standalone probes as visible while guarding the real app."""
        checker = getattr(self, "_is_current_page", None)
        if callable(checker):
            return bool(checker(getattr(self, "page27", None)))
        return True

    def _get_up_down_data_service(self) -> UpDownDataService:
        service = getattr(self, "_up_down_data_service", None)
        if service is None:
            cache_manager_factory = getattr(self, "_get_cache_manager", None)
            cache_manager = cache_manager_factory() if callable(cache_manager_factory) else None
            service = UpDownDataService(cache_manager=cache_manager)
            self._up_down_data_service = service
        return service

    def init_page27(self) -> None:
        """Build the standalone Up/Down page."""
        state = getattr(self, "up_down_page_state", load_up_down_page_settings())
        self.p27_active_source = str(state.get("active_source", "portfolio") or "portfolio").strip().lower()
        if self.p27_active_source not in P27_SOURCE_LABELS:
            self.p27_active_source = "portfolio"
        self.p27_interval_key = str(state.get("interval_key", "1d") or "1d").strip().lower()
        if self.p27_interval_key not in UP_DOWN_INTERVAL_LABELS:
            self.p27_interval_key = "1d"
        self.p27_custom_symbols = normalize_up_down_symbols(state.get("custom_symbols", []))
        self._p27_payload_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._p27_request_seq = 0
        self._p27_active_request = 0
        self._p27_fetching = False
        self._p27_target_fetching = False
        self._p27_render_generation = 0
        self._p27_cache_metadata: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._p27_inflight_keys: set[tuple[Any, ...]] = set()
        self._p27_target_request_tokens: dict[tuple[Any, ...], int] = {}
        self._p27_request_tokens: dict[tuple[Any, ...], int] = {}
        self._p27_closed = False
        self._p27_interval_buttons: dict[str, QPushButton] = {}
        self._p27_tables: dict[str, QTableWidget] = {}

        layout = QVBoxLayout(self.page27)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("<b>Up/Down</b>")
        self.set_theme_role(title, "page_title")
        header.addWidget(title)
        header.addSpacing(12)
        interval_label = QLabel("Interval")
        self.set_theme_role(interval_label, "muted")
        header.addWidget(interval_label)
        self.p27_interval_group = QButtonGroup(self.page27)
        self.p27_interval_group.setExclusive(True)
        for key, label in UP_DOWN_INTERVALS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumWidth(48)
            button.clicked.connect(lambda _checked=False, interval_key=key: self._p27_set_interval(interval_key))
            self._p27_interval_buttons[key] = button
            self.p27_interval_group.addButton(button)
            header.addWidget(button)
        header.addSpacing(12)
        self.p27_refresh_btn = QPushButton("Refresh")
        self.set_theme_variant(self.p27_refresh_btn, "accent")
        self.p27_refresh_btn.clicked.connect(lambda: self._p27_request_refresh(force=True))
        header.addWidget(self.p27_refresh_btn)
        header.addStretch()
        self.p27_status_label = QLabel("Ready")
        self.p27_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p27_status_label, "status_muted")
        header.addWidget(self.p27_status_label)
        layout.addLayout(header)

        self.p27_tabs = QTabWidget()
        for source_key, source_label in P27_SOURCES:
            self.p27_tabs.addTab(self._p27_build_source_tab(source_key), source_label)
        layout.addWidget(self.p27_tabs, 1)

        self._p27_update_interval_buttons()
        self._p27_select_source_tab(self.p27_active_source)
        self.p27_tabs.currentChanged.connect(self._p27_on_tab_changed)
        self._p27_hydrate_cached_payload(self.p27_active_source, self.p27_interval_key)

    def _p27_build_source_tab(self, source_key: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if source_key == "custom":
            custom_row = QHBoxLayout()
            self.p27_custom_input = QPlainTextEdit()
            self.p27_custom_input.setPlaceholderText("Enter tickers separated by commas, spaces, or new lines")
            self.p27_custom_input.setFixedHeight(70)
            self.p27_custom_input.setPlainText(" ".join(self.p27_custom_symbols))
            custom_row.addWidget(self.p27_custom_input, 1)
            actions = QVBoxLayout()
            self.p27_custom_apply_btn = QPushButton("Apply")
            self.p27_custom_apply_btn.clicked.connect(lambda: self._p27_apply_custom_symbols(save=False))
            self.p27_custom_save_btn = QPushButton("Save")
            self.set_theme_variant(self.p27_custom_save_btn, "positive")
            self.p27_custom_save_btn.clicked.connect(lambda: self._p27_apply_custom_symbols(save=True))
            actions.addWidget(self.p27_custom_apply_btn)
            actions.addWidget(self.p27_custom_save_btn)
            actions.addStretch()
            custom_row.addLayout(actions)
            layout.addLayout(custom_row)

        table = self._p27_new_table()
        self._p27_tables[source_key] = table
        layout.addWidget(table, 1)
        return tab

    def _p27_new_table(self) -> QTableWidget:
        table = QTableWidget(0, len(P27_TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(P27_TABLE_COLUMNS)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        header = table.horizontalHeader()
        header.setMinimumHeight(28)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(P27_TABLE_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(1, 90)
        table.setSortingEnabled(True)
        table.sortItems(6, Qt.SortOrder.DescendingOrder)
        return table

    def _p27_on_show(self) -> None:
        self._p27_sync_status_bar()
        self._p27_render_or_refresh(force=False)

    def _p27_sync_status_bar(self) -> None:
        if hasattr(self, "status_bar") and hasattr(self, "p27_status_label"):
            self.set_status_text(
                self.status_bar,
                self.p27_status_label.text(),
                status=str(self.p27_status_label.property("bt_status") or "muted"),
            )

    def _p27_set_status(self, text: Any, status: str = "muted") -> None:
        if hasattr(self, "p27_status_label"):
            self.set_status_text(self.p27_status_label, text, status=status)
        if hasattr(self, "status_bar"):
            self.set_status_text(self.status_bar, text, status=status)

    def _p27_update_interval_buttons(self) -> None:
        if hasattr(self, "update_checked_button_state"):
            self.update_checked_button_state(self._p27_interval_buttons, self.p27_interval_key)
        for key, button in self._p27_interval_buttons.items():
            button.setChecked(key == self.p27_interval_key)

    def _p27_set_interval(self, interval_key: Any) -> None:
        key = str(interval_key or "1d").strip().lower()
        if key not in UP_DOWN_INTERVAL_LABELS:
            return
        self.p27_interval_key = key
        self._p27_update_interval_buttons()
        self._p27_save_state()
        self._p27_render_or_refresh(force=False)

    def _p27_select_source_tab(self, source_key: Any) -> None:
        key = str(source_key or "portfolio").strip().lower()
        labels = list(P27_SOURCE_LABELS.keys())
        if key not in labels or not hasattr(self, "p27_tabs"):
            return
        self.p27_tabs.blockSignals(True)
        self.p27_tabs.setCurrentIndex(labels.index(key))
        self.p27_tabs.blockSignals(False)

    def _p27_on_tab_changed(self, index: int) -> None:
        try:
            self.p27_active_source = list(P27_SOURCE_LABELS.keys())[int(index)]
        except Exception:
            self.p27_active_source = "portfolio"
        self._p27_save_state()
        self._p27_render_or_refresh(force=False)

    def _p27_apply_custom_symbols(self, *, save: bool) -> None:
        text = self.p27_custom_input.toPlainText() if hasattr(self, "p27_custom_input") else ""
        symbols = normalize_up_down_symbols(text)
        self.p27_custom_symbols = symbols
        if hasattr(self, "p27_custom_input"):
            self.p27_custom_input.setPlainText(" ".join(symbols))
        self._p27_clear_source_cache("custom")
        if save:
            self._p27_save_state()
            self._p27_set_status(f"Saved {len(symbols)} custom ticker(s).", "positive")
        self._p27_request_refresh(force=True, source="custom")

    def _p27_save_state(self) -> None:
        self.up_down_page_state = save_up_down_page_settings({
            "active_source": getattr(self, "p27_active_source", "portfolio"),
            "interval_key": getattr(self, "p27_interval_key", "1d"),
            "custom_symbols": list(getattr(self, "p27_custom_symbols", [])),
        })

    def _p27_render_or_refresh(self, *, force: bool) -> None:
        self._p27_update_refresh_button()
        cache_key = self._p27_cache_key()
        if not force and cache_key not in self._p27_payload_cache:
            self._p27_hydrate_cached_payload(self.p27_active_source, self.p27_interval_key)
        payload = self._p27_payload_cache.get(cache_key)
        if payload is not None and not force:
            self._p27_render_payload(self.p27_active_source, payload)
            rows = list(payload.get("rows", [])) if isinstance(payload, dict) else []
            if not rows:
                label = P27_SOURCE_LABELS.get(self.p27_active_source, self.p27_active_source).lower()
                self._p27_set_status(f"No {label} tickers to load.", "warning")
                return
            metadata = self._p27_cache_metadata.get(cache_key, {"fresh": True, "cache_age_seconds": 0.0})
            if not bool(metadata.get("fresh", True)):
                age_text = self._p27_format_cache_age(metadata.get("cache_age_seconds"))
                label = P27_SOURCE_LABELS.get(self.p27_active_source, self.p27_active_source)
                self._p27_set_status(f"Showing cached {label} data ({age_text} old); refreshing...", "warning")
                self._p27_request_refresh(force=False)
                return
            unresolved = [row for row in rows if isinstance(row, dict) and "price_target_mean" not in row]
            if unresolved:
                request_id = self._p27_new_request_token(cache_key)
                label = P27_SOURCE_LABELS.get(self.p27_active_source, self.p27_active_source)
                age_text = self._p27_format_cache_age(metadata.get("cache_age_seconds"))
                self._p27_set_status(f"Loaded cached {label} data ({age_text} old); loading price targets...", "warning")
                self._p27_request_price_targets(request_id, self.p27_active_source, self.p27_interval_key, payload)
            else:
                available = sum(row.get("price_target_mean") is not None for row in rows if isinstance(row, dict))
                age_text = self._p27_format_cache_age(metadata.get("cache_age_seconds"))
                label = P27_SOURCE_LABELS.get(self.p27_active_source, self.p27_active_source)
                self._p27_set_status(
                    f"Loaded {len(rows)} cached {label} ticker(s) ({age_text} old); price targets available for {available}/{len(rows)}.",
                    "positive",
                )
            return
        self._p27_request_refresh(force=force)

    def _p27_hydrate_cached_payload(self, source_key: str, interval_key: str) -> bool:
        if source_key not in P27_HOLDINGS_ETFS:
            return False
        cached = self._get_up_down_data_service().load_cached_payload(source_key, interval_key)
        if cached is None:
            return False
        payload, metadata = cached
        cache_key = self._p27_cache_key(source_key, interval_key)
        self._p27_payload_cache[cache_key] = payload
        self._p27_cache_metadata[cache_key] = metadata
        return True

    def _p27_new_request_token(self, cache_key: tuple[Any, ...]) -> int:
        self._p27_request_seq += 1
        request_id = self._p27_request_seq
        self._p27_active_request = request_id
        self._p27_request_tokens[cache_key] = request_id
        return request_id

    def _p27_request_is_current(self, request_id: Any, source_key: str, interval_key: str) -> bool:
        if getattr(self, "_p27_closed", False):
            return False
        cache_key = self._p27_cache_key(source_key, interval_key)
        return int(request_id) == int(self._p27_request_tokens.get(cache_key, -1))

    def _p27_update_refresh_button(self) -> None:
        if not hasattr(self, "p27_refresh_btn"):
            return
        active_key = self._p27_cache_key()
        self.p27_refresh_btn.setEnabled(active_key not in getattr(self, "_p27_inflight_keys", set()))

    def _p27_request_refresh(self, *, force: bool = False, source: Any = None) -> bool:
        source_key = str(source or getattr(self, "p27_active_source", "portfolio") or "portfolio").strip().lower()
        if source_key not in P27_SOURCE_LABELS:
            source_key = "portfolio"
        interval_key = str(getattr(self, "p27_interval_key", "1d") or "1d").strip().lower()
        cache_key = self._p27_cache_key(source_key, interval_key)
        if cache_key in getattr(self, "_p27_inflight_keys", set()):
            return False
        symbols, names = self._p27_source_symbols(source_key)
        request_id = self._p27_new_request_token(cache_key)
        if source_key not in P27_HOLDINGS_ETFS and not symbols:
            payload = {"rows": [], "missing": [], "source": "Yahoo Finance", "as_of": ""}
            self._p27_payload_cache[cache_key] = payload
            self._p27_cache_metadata[cache_key] = {"fresh": True, "cache_age_seconds": 0.0}
            self._p27_render_payload(source_key, payload)
            self._p27_set_status(f"No {P27_SOURCE_LABELS[source_key].lower()} tickers to load.", "warning")
            return False
        self._p27_inflight_keys.add(cache_key)
        self._p27_fetching = True
        self._p27_target_fetching = False
        self._p27_update_refresh_button()
        if not force and cache_key in self._p27_payload_cache:
            metadata = self._p27_cache_metadata.get(cache_key, {})
            age_text = self._p27_format_cache_age(metadata.get("cache_age_seconds"))
            self._p27_set_status(
                f"Showing cached {P27_SOURCE_LABELS[source_key]} data ({age_text} old); refreshing in the background...",
                "warning",
            )
        else:
            self._p27_set_status(f"Loading {P27_SOURCE_LABELS[source_key]} {UP_DOWN_INTERVAL_LABELS.get(interval_key, interval_key.upper())} up/down counts...", "warning")

        def _run() -> None:
            try:
                fetch_symbols = symbols
                fetch_names = names
                holdings_symbol = P27_HOLDINGS_ETFS.get(source_key)
                if holdings_symbol:
                    fetch_symbols, fetch_names = self._p27_load_etf_holdings_symbols(holdings_symbol, force_refresh=force)
                payload = self._get_up_down_data_service().fetch(fetch_symbols, interval_key, names=fetch_names)
                payload["source_key"] = source_key
                payload["symbols"] = list(fetch_symbols)
                self._invoke_main.emit(lambda result=payload, req=request_id, src=source_key, interval=interval_key, forced=force: self._p27_apply_result(req, src, interval, result, force_refresh=forced))
            except Exception as exc:
                self._invoke_main.emit(lambda message=str(exc), req=request_id, src=source_key, interval=interval_key: self._p27_handle_error(req, src, interval, message))

        executor = getattr(self, "_p27_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=P27_MAX_WORKERS)
            self._p27_executor = executor
        executor.submit(_run)
        return True

    def _p27_apply_result(self, request_id: Any, source_key: str, interval_key: str, payload: Any, *, force_refresh: bool = False) -> None:
        if not self._p27_request_is_current(request_id, source_key, interval_key):
            return
        cache_key = self._p27_cache_key(source_key, interval_key)
        self._p27_inflight_keys.discard(cache_key)
        self._p27_fetching = bool(self._p27_inflight_keys)
        self._p27_update_refresh_button()
        clean_payload = payload if isinstance(payload, dict) else {}
        symbols = clean_payload.get("symbols", self._p27_source_symbols(source_key)[0])
        cache_key = self._p27_cache_key(source_key, interval_key, symbols)
        self._p27_payload_cache[cache_key] = clean_payload
        self._p27_cache_metadata[cache_key] = {"fresh": True, "cache_age_seconds": 0.0}
        if source_key in P27_HOLDINGS_ETFS:
            self._get_up_down_data_service().save_cached_payload(source_key, interval_key, clean_payload)
        self._p27_render_payload(source_key, clean_payload)
        rows = clean_payload.get("rows", []) if isinstance(clean_payload, dict) else []
        missing = clean_payload.get("missing", []) if isinstance(clean_payload, dict) else []
        label = P27_SOURCE_LABELS.get(source_key, source_key)
        if rows:
            suffix = f"; {len(missing)} missing" if missing else ""
            if source_key == self.p27_active_source and interval_key == self.p27_interval_key:
                self._p27_set_status(f"Loaded {len(rows)} {label} ticker(s){suffix}; loading price targets...", "warning")
            self._p27_request_price_targets(request_id, source_key, interval_key, clean_payload, force_refresh=force_refresh)
        elif missing:
            if source_key == self.p27_active_source and interval_key == self.p27_interval_key:
                self._p27_set_status(f"Loaded 0 {label} ticker(s); {len(missing)} missing.", "warning")
        else:
            if source_key == self.p27_active_source and interval_key == self.p27_interval_key:
                self._p27_set_status(f"Loaded 0 {label} ticker(s).", "positive")

    def _p27_handle_error(self, request_id: Any, source_key: str, interval_key: str, message: Any) -> None:
        if not self._p27_request_is_current(request_id, source_key, interval_key):
            return
        cache_key = self._p27_cache_key(source_key, interval_key)
        self._p27_inflight_keys.discard(cache_key)
        self._p27_fetching = bool(self._p27_inflight_keys)
        self._p27_update_refresh_button()
        if source_key == self.p27_active_source and interval_key == self.p27_interval_key:
            prefix = "Cached data retained; " if cache_key in self._p27_payload_cache else ""
            self._p27_set_status(f"{prefix}Up/Down load failed for {P27_SOURCE_LABELS.get(source_key, source_key)}: {message}", "warning")

    def _p27_render_payload(self, source_key: str, payload: Any) -> None:
        table = self._p27_tables.get(source_key)
        if table is None:
            return
        rows = sort_up_down_rows(list((payload or {}).get("rows", []) if isinstance(payload, dict) else []))
        if not self._p27_page_is_visible() or source_key != self.p27_active_source:
            return
        self._p27_render_generation += 1
        generation = self._p27_render_generation
        render_key = ("up-down", source_key)
        cancel_batched(self, render_key)
        previous_updates = True
        previous_signals = False
        sorting_enabled = False
        prepared = False
        selected_ticker = ""
        selected_row = table.currentRow()
        if selected_row >= 0 and table.item(selected_row, 1) is not None:
            selected_ticker = table.item(selected_row, 1).text()

        def _prepare() -> None:
            nonlocal previous_updates, previous_signals, sorting_enabled, prepared
            previous_updates = table.updatesEnabled()
            previous_signals = table.blockSignals(True)
            sorting_enabled = bool(table.isSortingEnabled())
            prepared = True
            table.setSortingEnabled(False)
            table.setUpdatesEnabled(False)
            table.setRowCount(len(rows))

        def _apply(row_index: int, row: dict[str, Any]) -> None:
            target_text, target_upside = self._p27_price_target_display(
                row.get("last_close"),
                row.get("price_target_mean"),
            )
            values = (
                row_index + 1,
                str(row.get("ticker") or ""),
                str(row.get("name") or ""),
                self._p27_format_currency(row.get("last_close")),
                self._p27_format_percent(row.get("interval_return")),
                row.get("trading_days"),
                row.get("days_up"),
                row.get("days_down"),
                target_text,
            )
            numerics = {
                0: row_index + 1,
                3: row.get("last_close"),
                4: row.get("interval_return"),
                5: row.get("trading_days"),
                6: row.get("days_up"),
                7: row.get("days_down"),
                8: target_upside,
            }
            for column, value in enumerate(values):
                item = _P27NumericItem(str(value if value is not None else "N/A")) if column in numerics else QTableWidgetItem(str(value))
                if column in numerics:
                    item.setData(P27_NUMERIC_ROLE, self._p27_sort_value(numerics.get(column)))
                if column == 8:
                    color_token = "text_muted" if target_upside is None else ("accent_positive" if target_upside >= 0 else "accent_negative")
                    item.setForeground(self.theme_qcolor(color_token))
                if column in {0, 3, 4, 5, 6, 7, 8}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)

        def _finish() -> None:
            if not prepared:
                return
            table.setUpdatesEnabled(previous_updates)
            if sorting_enabled:
                table.setSortingEnabled(True)
                table.sortItems(6, Qt.SortOrder.DescendingOrder)
            table.blockSignals(previous_signals)
            if selected_ticker:
                for row_index in range(table.rowCount()):
                    item = table.item(row_index, 1)
                    if item is not None and item.text() == selected_ticker:
                        table.selectRow(row_index)
                        break
            if previous_updates:
                table.viewport().update()

        if not self._p27_has_page_visibility_api():
            _prepare()
            try:
                for row_index, row in enumerate(rows):
                    _apply(row_index, row)
            finally:
                _finish()
            return

        # Publish the bounded first row with the result callback so callers can
        # immediately observe the new lightweight table state. Remaining rows
        # still render in guarded, time-sliced batches.
        _prepare()
        remaining_rows = rows
        row_offset = 0
        if rows:
            _apply(0, rows[0])
            remaining_rows = rows[1:]
            row_offset = 1

        run_batched(
            self,
            render_key,
            remaining_rows,
            lambda row_index, row: _apply(row_index + row_offset, row),
            generation=generation,
            finish=_finish,
            is_current=lambda value: value == self._p27_render_generation,
            is_visible=lambda: self._p27_page_is_visible() and source_key == self.p27_active_source,
        )

    def _p27_request_price_targets(
        self,
        request_id: int,
        source_key: str,
        interval_key: str,
        payload: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> None:
        cache_key = self._p27_cache_key(source_key, interval_key)
        if self._p27_target_request_tokens.get(cache_key) == int(request_id):
            return
        symbols = [
            str(row.get("ticker") or "")
            for row in list(payload.get("rows", []))
            if isinstance(row, dict) and (force_refresh or "price_target_mean" not in row)
        ]
        if not symbols:
            return
        self._p27_target_request_tokens[cache_key] = int(request_id)
        self._p27_target_fetching = True

        def _run() -> None:
            available = 0
            resolved = 0
            service = self._get_up_down_data_service()
            try:
                for batch in service.iter_price_target_batches(
                    symbols,
                    cancel_check=lambda: not self._p27_request_is_current(request_id, source_key, interval_key),
                    force_refresh=force_refresh,
                ):
                    resolved += len(batch)
                    available += sum(target is not None for target in batch.values())
                    self._invoke_main.emit(
                        lambda values=dict(batch), req=request_id, src=source_key, interval=interval_key:
                        self._p27_apply_target_batch(req, src, interval, values)
                    )
            except Exception as exc:
                logger.info("Up/Down price target stage failed: %s", exc)
            self._invoke_main.emit(
                lambda req=request_id, src=source_key, interval=interval_key, count=available, total=resolved:
                self._p27_finish_price_targets(req, src, interval, count, total)
            )

        executor = getattr(self, "_p27_target_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=1)
            self._p27_target_executor = executor
        executor.submit(_run)

    def _p27_apply_target_batch(
        self,
        request_id: Any,
        source_key: str,
        interval_key: str,
        targets: dict[str, float | None],
    ) -> None:
        if not self._p27_request_is_current(request_id, source_key, interval_key):
            return
        cache_key = self._p27_cache_key(source_key, interval_key)
        payload = self._p27_payload_cache.get(cache_key)
        if not isinstance(payload, dict):
            return
        display: dict[str, tuple[str, float | None]] = {}
        for row in list(payload.get("rows", [])):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("ticker") or "").upper().strip()
            if symbol not in targets:
                continue
            row["price_target_mean"] = targets[symbol]
            text, upside = self._p27_price_target_display(row.get("last_close"), targets[symbol])
            row["price_target_upside_pct"] = upside
            display[symbol] = (text, upside)
        self._p27_update_target_cells(source_key, display)

    def _p27_update_target_cells(self, source_key: str, display: dict[str, tuple[str, float | None]]) -> None:
        table = self._p27_tables.get(source_key)
        if table is None or not display or not self._p27_page_is_visible() or source_key != self.p27_active_source:
            return
        sorting_enabled = bool(table.isSortingEnabled())
        sort_column = int(table.horizontalHeader().sortIndicatorSection())
        sort_order = table.horizontalHeader().sortIndicatorOrder()
        selected_ticker = ""
        if table.currentRow() >= 0 and table.item(table.currentRow(), 1) is not None:
            selected_ticker = table.item(table.currentRow(), 1).text()
        previous_signals = table.blockSignals(True)
        table.setSortingEnabled(False)
        try:
            for row_index in range(table.rowCount()):
                ticker_item = table.item(row_index, 1)
                symbol = str(ticker_item.text() if ticker_item else "").upper().strip()
                if symbol not in display:
                    continue
                text, upside = display[symbol]
                item = _P27NumericItem(text)
                item.setData(P27_NUMERIC_ROLE, self._p27_sort_value(upside))
                color_token = "text_muted" if upside is None else ("accent_positive" if upside >= 0 else "accent_negative")
                item.setForeground(self.theme_qcolor(color_token))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, 8, item)
        finally:
            if sorting_enabled:
                table.setSortingEnabled(True)
                if sort_column >= 0:
                    table.sortItems(sort_column, sort_order)
            table.blockSignals(previous_signals)
        if selected_ticker:
            for row_index in range(table.rowCount()):
                ticker_item = table.item(row_index, 1)
                if ticker_item is not None and ticker_item.text() == selected_ticker:
                    table.selectRow(row_index)
                    break

    def _p27_finish_price_targets(
        self,
        request_id: Any,
        source_key: str,
        interval_key: str,
        available: int,
        resolved: int,
    ) -> None:
        cache_key = self._p27_cache_key(source_key, interval_key)
        if int(request_id) != int(self._p27_target_request_tokens.get(cache_key, -1)):
            return
        self._p27_target_request_tokens.pop(cache_key, None)
        self._p27_target_fetching = bool(self._p27_target_request_tokens)
        if not self._p27_request_is_current(request_id, source_key, interval_key):
            return
        label = P27_SOURCE_LABELS.get(source_key, source_key)
        payload = self._p27_payload_cache.get(cache_key) or {}
        if isinstance(payload, dict):
            payload["price_targets_as_of"] = datetime.datetime.now().isoformat(timespec="seconds")
            if source_key in P27_HOLDINGS_ETFS:
                self._get_up_down_data_service().save_cached_payload(source_key, interval_key, payload)
        row_count = len(payload.get("rows", [])) if isinstance(payload, dict) else 0
        missing_count = len(payload.get("missing", [])) if isinstance(payload, dict) else 0
        suffix = f"; {missing_count} missing" if missing_count else ""
        status = "positive" if available > 0 or resolved == 0 else "warning"
        if source_key == self.p27_active_source and interval_key == self.p27_interval_key:
            self._p27_set_status(
                f"Loaded {row_count} {label} ticker(s){suffix}; price targets available for {available}/{resolved}.",
                status,
            )

    def _p27_source_symbols(self, source_key: str) -> tuple[list[str], dict[str, str]]:
        if source_key == "portfolio":
            if hasattr(self, "_p4_heatmap_stock_symbols"):
                symbols = self._p4_heatmap_stock_symbols()
            elif hasattr(self, "_p4_active_tickers"):
                symbols = normalize_up_down_symbols(self._p4_active_tickers())
            else:
                symbols = []
            return symbols, {}
        if source_key == "custom":
            return list(getattr(self, "p27_custom_symbols", [])), {}
        return [], {}

    def _p27_load_etf_holdings_symbols(self, etf_symbol: Any, *, force_refresh: bool = False) -> tuple[list[str], dict[str, str]]:
        from budget_terminal_app.etf_holdings import EtfHoldingsService

        symbol_key = str(etf_symbol or "").upper().strip()
        service = self._get_up_down_data_service()
        if not force_refresh:
            cached = service.load_cached_holdings(symbol_key, fresh_only=True)
            if cached is not None:
                payload, _metadata = cached
                return normalize_up_down_symbols(payload.get("symbols", [])), {
                    str(key).upper().strip(): str(value or "").strip()
                    for key, value in dict(payload.get("names", {}) or {}).items()
                }
        try:
            result = EtfHoldingsService().load(symbol_key, enrich=False)
        except Exception:
            stale = service.load_cached_holdings(symbol_key, fresh_only=False)
            if stale is None:
                raise
            payload, metadata = stale
            logger.info(
                "Using stale Up/Down %s holdings cache after live load failure (age %.0fs).",
                symbol_key,
                float(metadata.get("cache_age_seconds", 0.0) or 0.0),
            )
            return normalize_up_down_symbols(payload.get("symbols", [])), {
                str(key).upper().strip(): str(value or "").strip()
                for key, value in dict(payload.get("names", {}) or {}).items()
            }
        symbols: list[str] = []
        names: dict[str, str] = {}
        for holding in list(getattr(result, "holdings", []) or []):
            symbol = str(getattr(holding, "symbol", "") or "").upper().strip()
            if not symbol or symbol == "CASH" or not any(ch.isalpha() for ch in symbol):
                continue
            if symbol not in symbols:
                symbols.append(symbol)
            name = str(getattr(holding, "name", "") or "").strip()
            if name:
                names[symbol] = name
        service.save_cached_holdings(symbol_key, symbols, names)
        return symbols, names

    def _p27_cache_key(self, source_key: Any = None, interval_key: Any = None, symbols: Any = None) -> tuple[Any, ...]:
        source = str(source_key or getattr(self, "p27_active_source", "portfolio") or "portfolio").strip().lower()
        interval = str(interval_key or getattr(self, "p27_interval_key", "1d") or "1d").strip().lower()
        holdings_symbol = P27_HOLDINGS_ETFS.get(source)
        if holdings_symbol:
            symbol_key: tuple[str, ...] = (f"{holdings_symbol}_HOLDINGS",)
        elif symbols is None:
            symbol_key = tuple(self._p27_source_symbols(source)[0])
        else:
            symbol_key = tuple(normalize_up_down_symbols(symbols))
        return (source, interval, symbol_key)

    def _p27_clear_source_cache(self, source_key: str) -> None:
        source = str(source_key or "").strip().lower()
        self._p27_payload_cache = {
            key: value for key, value in getattr(self, "_p27_payload_cache", {}).items()
            if not (isinstance(key, tuple) and key and key[0] == source)
        }
        self._p27_cache_metadata = {
            key: value for key, value in getattr(self, "_p27_cache_metadata", {}).items()
            if not (isinstance(key, tuple) and key and key[0] == source)
        }

    @staticmethod
    def _p27_format_cache_age(value: Any) -> str:
        try:
            seconds = max(float(value), 0.0)
        except (TypeError, ValueError):
            return "recently"
        if seconds < 60:
            return "under a minute"
        if seconds < 3600:
            return f"{max(1, int(seconds // 60))}m"
        if seconds < 86400:
            return f"{max(1, int(seconds // 3600))}h"
        return f"{max(1, int(seconds // 86400))}d"

    @staticmethod
    def _p27_sort_value(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return float("-inf")
        return numeric if math.isfinite(numeric) else float("-inf")

    @staticmethod
    def _p27_format_currency(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "N/A"
        if not math.isfinite(numeric):
            return "N/A"
        return f"${numeric:,.2f}"

    @staticmethod
    def _p27_format_percent(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "N/A"
        if not math.isfinite(numeric):
            return "N/A"
        return f"{numeric:+.2f}%"

    @staticmethod
    def _p27_price_target_display(current_price: Any, target: Any) -> tuple[str, float | None]:
        text, upside = analyst_target_cell_text_and_sort(current_price, target)
        if text in {"--", "N/A"} or not math.isfinite(float(upside)):
            return "N/A", None
        return text, float(upside)
