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


P27_MAX_WORKERS = 1
P27_SOURCES: tuple[tuple[str, str], ...] = (
    ("portfolio", "Portfolio"),
    ("spy", "SPY Holdings"),
    ("custom", "Custom"),
)
P27_TABLE_COLUMNS = (
    "#",
    "Ticker",
    "Name",
    "Last Close",
    "Interval Return",
    "Trading Days",
    "Days Up",
    "Days Down",
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
    def _get_up_down_data_service(self) -> UpDownDataService:
        service = getattr(self, "_up_down_data_service", None)
        if service is None:
            service = UpDownDataService()
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
        self._p27_render_or_refresh(force=False)

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
        cache_key = self._p27_cache_key()
        payload = self._p27_payload_cache.get(cache_key)
        if payload is not None and not force:
            self._p27_render_payload(self.p27_active_source, payload)
            return
        self._p27_request_refresh(force=force)

    def _p27_request_refresh(self, *, force: bool = False, source: Any = None) -> bool:
        source_key = str(source or getattr(self, "p27_active_source", "portfolio") or "portfolio").strip().lower()
        if source_key not in P27_SOURCE_LABELS:
            source_key = "portfolio"
        interval_key = str(getattr(self, "p27_interval_key", "1d") or "1d").strip().lower()
        if getattr(self, "_p27_fetching", False) and not force:
            return False
        symbols, names = self._p27_source_symbols(source_key)
        if source_key != "spy" and not symbols:
            payload = {"rows": [], "missing": [], "source": "Yahoo Finance", "as_of": ""}
            self._p27_payload_cache[self._p27_cache_key(source_key, interval_key, symbols)] = payload
            self._p27_render_payload(source_key, payload)
            self._p27_set_status(f"No {P27_SOURCE_LABELS[source_key].lower()} tickers to load.", "warning")
            return False
        self._p27_request_seq += 1
        request_id = self._p27_request_seq
        self._p27_active_request = request_id
        self._p27_fetching = True
        if hasattr(self, "p27_refresh_btn"):
            self.p27_refresh_btn.setEnabled(False)
        self._p27_set_status(f"Loading {P27_SOURCE_LABELS[source_key]} {UP_DOWN_INTERVAL_LABELS.get(interval_key, interval_key.upper())} up/down counts...", "warning")

        def _run() -> None:
            try:
                fetch_symbols = symbols
                fetch_names = names
                if source_key == "spy":
                    fetch_symbols, fetch_names = self._p27_load_spy_holdings_symbols()
                payload = self._get_up_down_data_service().fetch(fetch_symbols, interval_key, names=fetch_names)
                payload["source_key"] = source_key
                payload["symbols"] = list(fetch_symbols)
                self._invoke_main.emit(lambda result=payload, req=request_id, src=source_key, interval=interval_key: self._p27_apply_result(req, src, interval, result))
            except Exception as exc:
                self._invoke_main.emit(lambda message=str(exc), req=request_id, src=source_key: self._p27_handle_error(req, src, message))

        executor = getattr(self, "_p27_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=P27_MAX_WORKERS)
            self._p27_executor = executor
        executor.submit(_run)
        return True

    def _p27_apply_result(self, request_id: Any, source_key: str, interval_key: str, payload: Any) -> None:
        if int(request_id) != int(getattr(self, "_p27_active_request", 0)):
            return
        self._p27_fetching = False
        if hasattr(self, "p27_refresh_btn"):
            self.p27_refresh_btn.setEnabled(True)
        clean_payload = payload if isinstance(payload, dict) else {}
        symbols = clean_payload.get("symbols", self._p27_source_symbols(source_key)[0])
        self._p27_payload_cache[self._p27_cache_key(source_key, interval_key, symbols)] = clean_payload
        self._p27_render_payload(source_key, clean_payload)
        rows = clean_payload.get("rows", []) if isinstance(clean_payload, dict) else []
        missing = clean_payload.get("missing", []) if isinstance(clean_payload, dict) else []
        label = P27_SOURCE_LABELS.get(source_key, source_key)
        if missing:
            self._p27_set_status(f"Loaded {len(rows)} {label} ticker(s); {len(missing)} missing.", "warning")
        else:
            self._p27_set_status(f"Loaded {len(rows)} {label} ticker(s).", "positive")

    def _p27_handle_error(self, request_id: Any, source_key: str, message: Any) -> None:
        if int(request_id) != int(getattr(self, "_p27_active_request", 0)):
            return
        self._p27_fetching = False
        if hasattr(self, "p27_refresh_btn"):
            self.p27_refresh_btn.setEnabled(True)
        self._p27_set_status(f"Up/Down load failed for {P27_SOURCE_LABELS.get(source_key, source_key)}: {message}", "warning")

    def _p27_render_payload(self, source_key: str, payload: Any) -> None:
        table = self._p27_tables.get(source_key)
        if table is None:
            return
        rows = sort_up_down_rows(list((payload or {}).get("rows", []) if isinstance(payload, dict) else []))
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row_index, row in enumerate(rows):
            table.insertRow(row_index)
            values = (
                row_index + 1,
                str(row.get("ticker") or ""),
                str(row.get("name") or ""),
                self._p27_format_currency(row.get("last_close")),
                self._p27_format_percent(row.get("interval_return")),
                row.get("trading_days"),
                row.get("days_up"),
                row.get("days_down"),
            )
            numerics = {
                0: row_index + 1,
                3: row.get("last_close"),
                4: row.get("interval_return"),
                5: row.get("trading_days"),
                6: row.get("days_up"),
                7: row.get("days_down"),
            }
            for column, value in enumerate(values):
                item = _P27NumericItem(str(value if value is not None else "N/A")) if column in numerics else QTableWidgetItem(str(value))
                if column in numerics:
                    item.setData(P27_NUMERIC_ROLE, self._p27_sort_value(numerics.get(column)))
                if column in {0, 3, 4, 5, 6, 7}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)
        table.setSortingEnabled(True)
        table.sortItems(6, Qt.SortOrder.DescendingOrder)

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

    def _p27_load_spy_holdings_symbols(self) -> tuple[list[str], dict[str, str]]:
        from budget_terminal_app.etf_holdings import EtfHoldingsService

        result = EtfHoldingsService().load("SPY")
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
        return symbols, names

    def _p27_cache_key(self, source_key: Any = None, interval_key: Any = None, symbols: Any = None) -> tuple[Any, ...]:
        source = str(source_key or getattr(self, "p27_active_source", "portfolio") or "portfolio").strip().lower()
        interval = str(interval_key or getattr(self, "p27_interval_key", "1d") or "1d").strip().lower()
        if source == "spy":
            symbol_key: tuple[str, ...] = ("SPY_HOLDINGS",)
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
