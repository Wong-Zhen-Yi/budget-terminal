from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.services.global_markets import (
    GLOBAL_INTERVALS,
    GlobalMarketsDataService,
)
from budget_terminal_app.widgets.global_market_map import GlobalMarketMapWidget


P26_MAX_WORKERS = 1
P26_TABLE_COLUMNS = ("Region", "Country", "Index", "Symbol", "Last Close", "Start Close", "End Close", "Performance %", "Last Date")


class GlobalPageMixin:
    def _get_global_markets_data_service(self) -> GlobalMarketsDataService:
        service = getattr(self, "_global_markets_data_service", None)
        if service is None:
            service = GlobalMarketsDataService()
            self._global_markets_data_service = service
        return service

    def init_page26(self) -> None:
        """Build the standalone Global market-index map page."""
        state = getattr(self, "global_page_state", load_global_page_settings())
        self.p26_interval_label = str(state.get("interval_label", "1D") or "1D").upper().strip()
        if self.p26_interval_label not in GLOBAL_INTERVALS:
            self.p26_interval_label = "1D"
        self._p26_request_seq = 0
        self._p26_active_request = 0
        self._p26_payload: dict[str, Any] = {}
        self._p26_interval_buttons = {}
        self._p26_interval_group = QButtonGroup(self)
        self._p26_interval_group.setExclusive(True)

        layout = QVBoxLayout(self.page26)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("<b>Global</b>")
        self.set_theme_role(title, "page_title")
        header.addWidget(title)
        header.addSpacing(12)
        interval_label = QLabel("Interval")
        self.set_theme_role(interval_label, "muted")
        header.addWidget(interval_label)
        for label in GLOBAL_INTERVALS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(partial(self._p26_set_interval, label))
            self._p26_interval_buttons[label] = button
            self._p26_interval_group.addButton(button)
            header.addWidget(button)
        header.addSpacing(12)
        self.p26_refresh_btn = QPushButton("Refresh")
        self.p26_refresh_btn.clicked.connect(lambda: self._p26_request_refresh(force=True))
        header.addWidget(self.p26_refresh_btn)
        self.p26_export_btn = QPushButton("Export for LLM")
        self.set_theme_variant(self.p26_export_btn, "positive")
        self.p26_export_btn.clicked.connect(self._p26_export_for_llm)
        header.addWidget(self.p26_export_btn)
        header.addStretch()
        self.p26_status_label = QLabel("Ready")
        self.p26_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p26_status_label, "status_muted")
        header.addWidget(self.p26_status_label)
        layout.addLayout(header)

        self.p26_map = GlobalMarketMapWidget()
        layout.addWidget(self.p26_map, 2)

        self.p26_table = QTableWidget(0, len(P26_TABLE_COLUMNS))
        self.p26_table.setHorizontalHeaderLabels(P26_TABLE_COLUMNS)
        self.p26_table.setAlternatingRowColors(True)
        self.p26_table.verticalHeader().setVisible(False)
        self.p26_table.horizontalHeader().setMinimumHeight(28)
        self.p26_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.p26_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.p26_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(P26_TABLE_COLUMNS)):
            self.p26_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.p26_table, 1)

        self._p26_update_button_styles()
        self._apply_global_page_theme()
        self._p26_render_payload()

    def _p26_on_show(self) -> None:
        self._p26_sync_status_bar()
        if not self._p26_rows():
            self._p26_request_refresh()

    def _p26_set_status(self, text: Any, status: str = "muted") -> None:
        if hasattr(self, "p26_status_label"):
            self.set_status_text(self.p26_status_label, text, status=status)
        if hasattr(self, "status_bar"):
            self.set_status_text(self.status_bar, text, status=status)

    def _p26_sync_status_bar(self) -> None:
        if hasattr(self, "status_bar") and hasattr(self, "p26_status_label"):
            self.set_status_text(
                self.status_bar,
                self.p26_status_label.text(),
                status=str(self.p26_status_label.property("bt_status") or "muted"),
            )

    def _p26_update_button_styles(self) -> None:
        self.update_checked_button_state(self._p26_interval_buttons, self.p26_interval_label)
        for label, button in self._p26_interval_buttons.items():
            button.setChecked(label == self.p26_interval_label)

    def _p26_set_interval(self, label: Any, *_: Any) -> None:
        text = str(label or "").upper().strip()
        if text not in GLOBAL_INTERVALS:
            return
        self.p26_interval_label = text
        self._p26_update_button_styles()
        self._p26_save_state()
        self._p26_render_payload()

    def _p26_save_state(self) -> None:
        self.global_page_state = save_global_page_settings({"interval_label": getattr(self, "p26_interval_label", "1D")})

    def _p26_request_refresh(self, *, force: bool = False) -> bool:
        if getattr(self, "_p26_fetching", False) and not force:
            return False
        self._p26_request_seq += 1
        request_id = self._p26_request_seq
        self._p26_active_request = request_id
        self._p26_fetching = True
        if hasattr(self, "p26_refresh_btn"):
            self.p26_refresh_btn.setEnabled(False)
        self._p26_set_status("Loading global market indexes...", "info")

        def _run() -> None:
            try:
                payload = self._get_global_markets_data_service().fetch()
                self._invoke_main.emit(lambda result=payload, req=request_id: self._p26_apply_result(req, result))
            except Exception as exc:
                self._invoke_main.emit(lambda message=str(exc), req=request_id: self._p26_handle_error(req, message))

        executor = getattr(self, "_p26_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=P26_MAX_WORKERS)
            self._p26_executor = executor
        executor.submit(_run)
        return True

    def _p26_apply_result(self, request_id: Any, payload: Any) -> None:
        if int(request_id) != int(getattr(self, "_p26_active_request", 0)):
            return
        self._p26_fetching = False
        if hasattr(self, "p26_refresh_btn"):
            self.p26_refresh_btn.setEnabled(True)
        self._p26_payload = payload if isinstance(payload, dict) else {}
        self._p26_render_payload()
        rows = self._p26_rows()
        missing = self._p26_payload.get("missing", []) if isinstance(self._p26_payload, dict) else []
        if missing:
            self._p26_set_status(f"Loaded {len(rows)} global index row(s); {len(missing)} symbol(s) unavailable.", "warning")
        else:
            self._p26_set_status(f"Loaded {len(rows)} global index row(s).", "positive")

    def _p26_handle_error(self, request_id: Any, message: Any) -> None:
        if int(request_id) != int(getattr(self, "_p26_active_request", 0)):
            return
        self._p26_fetching = False
        if hasattr(self, "p26_refresh_btn"):
            self.p26_refresh_btn.setEnabled(True)
        self._p26_set_status(f"Global indexes failed: {message}", "negative")

    def _p26_rows(self) -> list[dict[str, Any]]:
        payload = getattr(self, "_p26_payload", {})
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _p26_interval_payload(self, row: dict[str, Any], interval_label: Any = None) -> dict[str, Any]:
        label = str(interval_label or getattr(self, "p26_interval_label", "1D")).upper().strip()
        intervals = row.get("intervals", {})
        payload = intervals.get(label) if isinstance(intervals, dict) else None
        return payload if isinstance(payload, dict) else {}

    def _p26_render_payload(self) -> None:
        rows = self._p26_rows()
        if hasattr(self, "p26_map"):
            self.p26_map.set_data(rows, getattr(self, "p26_interval_label", "1D"))
        if not hasattr(self, "p26_table"):
            return
        self.p26_table.setSortingEnabled(False)
        self.p26_table.setRowCount(0)
        for row in rows:
            row_index = self.p26_table.rowCount()
            self.p26_table.insertRow(row_index)
            payload = self._p26_interval_payload(row)
            values = (
                row.get("region", "--"),
                row.get("country", "--"),
                row.get("index", "--"),
                row.get("symbol", "--"),
                self._p26_close(row.get("last_close")),
                self._p26_close(payload.get("start_close")),
                self._p26_close(payload.get("end_close")),
                self._p26_pct(payload.get("change_pct")) if payload.get("available") else "--",
                row.get("last_date") or payload.get("end_date") or "--",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif column in (3, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.p26_table.setItem(row_index, column, item)
        self.p26_table.setSortingEnabled(True)

    def _p26_close(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        if not math.isfinite(number):
            return "--"
        return f"{number:,.2f}"

    def _p26_pct(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        if not math.isfinite(number):
            return "--"
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.2f}%"

    def _p26_export_for_llm(self) -> None:
        rows = self._p26_rows()
        if not rows:
            self._p26_set_status("Load global index data before exporting.", "warning")
            return
        try:
            QApplication.clipboard().setText(self._p26_build_llm_export())
        except Exception as exc:
            self._p26_set_status(f"Export failed: {exc}", "negative")
            QMessageBox.critical(self, "Export Failed", f"Unable to copy Global data to the clipboard.\n\n{exc}")
            return
        self._p26_set_status("Global all-interval export copied to clipboard.", "positive")

    def _p26_build_llm_export(self) -> str:
        payload = getattr(self, "_p26_payload", {}) if isinstance(getattr(self, "_p26_payload", {}), dict) else {}
        generated = payload.get("generated_at") or datetime.datetime.now().isoformat(timespec="seconds")
        source = payload.get("source") or "yfinance"
        lines = [
            "# Global Market Index Export",
            f"Generated: {generated}",
            f"Source: {source}",
            "Coverage: major global market indexes mapped by country/region.",
            "Intervals: 1D, 5D, 30D, YTD, 1Y, 5Y. Performance is percent change from start close to latest close.",
            "",
            "| Region | Country | Index | Symbol | Last Date | Last Close | 1D | 5D | 30D | YTD | 1Y | 5Y |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in self._p26_rows():
            interval_values = []
            for label in GLOBAL_INTERVALS:
                interval_values.append(self._p26_pct(self._p26_interval_payload(row, label).get("change_pct")) if self._p26_interval_payload(row, label).get("available") else "--")
            lines.append(
                "| "
                + " | ".join(
                    [
                        self._p26_export_cell(row.get("region", "--")),
                        self._p26_export_cell(row.get("country", "--")),
                        self._p26_export_cell(row.get("index", "--")),
                        self._p26_export_cell(row.get("symbol", "--")),
                        self._p26_export_cell(row.get("last_date") or "--"),
                        self._p26_export_cell(self._p26_close(row.get("last_close"))),
                        *[self._p26_export_cell(value) for value in interval_values],
                    ]
                )
                + " |"
            )
        lines.extend(["", "## Interval Details"])
        for label in GLOBAL_INTERVALS:
            lines.extend([
                "",
                f"### {label}",
                "| Country | Index | Symbol | Start Date | Start Close | End Date | End Close | Performance |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ])
            for row in self._p26_rows():
                item = self._p26_interval_payload(row, label)
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            self._p26_export_cell(row.get("country", "--")),
                            self._p26_export_cell(row.get("index", "--")),
                            self._p26_export_cell(row.get("symbol", "--")),
                            self._p26_export_cell(item.get("start_date") if item.get("available") else "--"),
                            self._p26_export_cell(self._p26_close(item.get("start_close"))),
                            self._p26_export_cell(item.get("end_date") or row.get("last_date") or "--"),
                            self._p26_export_cell(self._p26_close(item.get("end_close"))),
                            self._p26_export_cell(self._p26_pct(item.get("change_pct")) if item.get("available") else "--"),
                        ]
                    )
                    + " |"
                )
        return "\n".join(lines)

    def _p26_export_cell(self, value: Any) -> str:
        return str(value if value is not None else "--").replace("|", "/").replace("\n", " ").strip() or "--"

    def _apply_global_page_theme(self) -> None:
        if hasattr(self, "p26_map"):
            self.p26_map.set_colors(
                {
                    "background": self.theme_color("background_primary"),
                    "ocean": self.theme_color("chart_bg"),
                    "grid": self.theme_color("chart_grid"),
                    "land": self.theme_color("panel_background"),
                    "land_border": self.theme_color("panel_border"),
                    "text": self.theme_color("text_primary"),
                    "muted": self.theme_color("text_muted"),
                    "positive": self.theme_color("accent_positive"),
                    "negative": self.theme_color("accent_negative"),
                    "neutral": self.theme_color("warning"),
                    "label_bg": self.theme_color("panel_background"),
                    "label_border": self.theme_color("panel_border"),
                    "country_border": self.theme_color("panel_border"),
                }
            )
        if hasattr(self, "p26_status_label"):
            self.set_status_text(
                self.p26_status_label,
                self.p26_status_label.text(),
                status=str(self.p26_status_label.property("bt_status") or "muted"),
            )
