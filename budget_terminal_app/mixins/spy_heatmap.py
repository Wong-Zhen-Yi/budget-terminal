from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.data_service.results import data_sources_from_meta, describe_market_data_status
from budget_terminal_app.data_service.tasks import MarketDataTaskRunner
from budget_terminal_app.widgets.etf_heatmap import EtfHeatmapWidget


class SpyHeatmapMixin:
    _P17_REFRESH_TTL_SECONDS = 120
    _P17_ETFS = (
        ("SPY", "SPY", "SPY"),
        ("NDX", "QQQ", "QQQ"),
        ("DJI", "DIA", "DIA"),
    )
    _P17_INTERVALS = (
        ("live", "Live"),
        ("1d", "1D"),
        ("1w", "1W"),
        ("1m", "1M"),
        ("3m", "3M"),
        ("ytd", "YTD"),
        ("1y", "1Y"),
    )

    def init_page17(self) -> None:
        """Build the ETF holdings heatmap page."""
        self._p17_fetch_in_progress = False
        self._p17_fetching_symbols: set[str] = set()
        self._p17_last_fetch_by_etf: dict[str, float] = {}
        self._p17_rows: list[dict[str, Any]] = []
        self._p17_selected_row: dict[str, Any] | None = None
        self._p17_result: Any = None
        self._p17_results: dict[str, Any] = {}
        self._p17_etf_symbol = "SPY"
        self._p17_etf_buttons: dict[str, QPushButton] = {}
        self._p17_interval_key = "live"
        self._p17_interval_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self.page17)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)

        title_row = QHBoxLayout()
        self.p17_title_lbl = QLabel("<b>Heatmap</b>")
        self.set_theme_role(self.p17_title_lbl, "page_title")
        title_row.addWidget(self.p17_title_lbl)
        self.p17_etf_group = QButtonGroup(self.page17)
        self.p17_etf_group.setExclusive(True)
        for symbol, label, _fetch_symbol in self._P17_ETFS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, etf_symbol=symbol: self._p17_select_etf(etf_symbol))
            title_row.addWidget(button)
            self.p17_etf_group.addButton(button)
            self._p17_etf_buttons[symbol] = button
        self._p17_etf_buttons[self._p17_etf_symbol].setChecked(True)
        title_row.addStretch()
        self.p17_interval_group = QButtonGroup(self.page17)
        self.p17_interval_group.setExclusive(True)
        for key, label in self._P17_INTERVALS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, interval_key=key: self._p17_select_interval(interval_key))
            title_row.addWidget(button)
            self.p17_interval_group.addButton(button)
            self._p17_interval_buttons[key] = button
        self._p17_interval_buttons[self._p17_interval_key].setChecked(True)
        self.p17_refresh_btn = QPushButton("Refresh")
        self.set_theme_variant(self.p17_refresh_btn, "accent")
        self.p17_refresh_btn.clicked.connect(lambda: self._p17_request_refresh(force=True))
        title_row.addWidget(self.p17_refresh_btn)
        layout.addLayout(title_row)

        self.p17_summary_frame = QFrame()
        summary_layout = QHBoxLayout(self.p17_summary_frame)
        summary_layout.setContentsMargins(10, 4, 10, 4)
        summary_layout.setSpacing(0)
        self.p17_summary_labels: dict[str, QLabel] = {}
        for index, (key, label, default) in enumerate((
            ("updated", "Last Updated", "--"),
            ("holdings", "Holdings", "--"),
            ("coverage", "Quote Coverage", "--"),
            ("weighted", "Weighted Move", "--"),
            ("strongest", "Strongest", "--"),
            ("weakest", "Weakest", "--"),
        )):
            if index:
                sep = QFrame()
                sep.setFixedWidth(1)
                summary_layout.addWidget(sep)
            cell = QVBoxLayout()
            cell.setContentsMargins(8, 1, 8, 1)
            cell.setSpacing(1)
            header = QLabel(label)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel(default)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(header)
            cell.addWidget(value)
            summary_layout.addLayout(cell, 1)
            self.p17_summary_labels[key] = value
            self.p17_summary_labels[f"{key}_header"] = header
            self.p17_summary_labels[f"{key}_sep"] = sep if index else None
        layout.addWidget(self.p17_summary_frame)

        self.p17_status_lbl = QLabel("Ready")
        self.set_theme_role(self.p17_status_lbl, "status_muted")
        self.p17_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.p17_status_lbl)

        self.p17_heatmap = EtfHeatmapWidget()
        self.p17_heatmap.holdingSelected.connect(self._p17_on_holding_selected)
        self.p17_heatmap.holdingActivated.connect(self._p17_open_symbol_in_charts)
        layout.addWidget(self.p17_heatmap, 1)

        self.p17_detail_frame = QFrame()
        detail_layout = QHBoxLayout(self.p17_detail_frame)
        detail_layout.setContentsMargins(10, 6, 10, 6)
        detail_layout.setSpacing(12)
        self.p17_detail_symbol_lbl = QLabel("Select a holding")
        self.p17_detail_name_lbl = QLabel("--")
        self.p17_detail_sector_lbl = QLabel("Sector: --")
        self.p17_detail_weight_lbl = QLabel("Weight: --")
        self.p17_detail_price_lbl = QLabel("Price: --")
        self.p17_detail_change_lbl = QLabel("Change: --")
        for label in (
            self.p17_detail_symbol_lbl,
            self.p17_detail_name_lbl,
            self.p17_detail_sector_lbl,
            self.p17_detail_weight_lbl,
            self.p17_detail_price_lbl,
            self.p17_detail_change_lbl,
        ):
            label.setMinimumHeight(18)
            detail_layout.addWidget(label)
        detail_layout.addStretch()
        layout.addWidget(self.p17_detail_frame)

        self._apply_spy_heatmap_theme()

    def _p17_on_show(self) -> None:
        """Refresh selected ETF heatmap data when the tab is shown."""
        self._p17_request_refresh()

    def _p17_request_refresh(self, *, force: bool = False, symbol: Any = None) -> bool:
        """Start a heatmap refresh if not throttled or already running."""
        etf_symbol = self._p17_normalize_etf_symbol(symbol or getattr(self, "_p17_etf_symbol", "SPY"))
        fetching = getattr(self, "_p17_fetching_symbols", set())
        if etf_symbol in fetching:
            return False
        now = datetime.datetime.now().timestamp()
        cached_result = getattr(self, "_p17_results", {}).get(etf_symbol)
        last_fetch = float(getattr(self, "_p17_last_fetch_by_etf", {}).get(etf_symbol, 0.0) or 0.0)
        if not force and cached_result is not None and now - last_fetch <= self._P17_REFRESH_TTL_SECONDS:
            if etf_symbol == getattr(self, "_p17_etf_symbol", "SPY"):
                self._p17_render_interval_result(reset_view=False)
            return False
        fetching.add(etf_symbol)
        self._p17_fetching_symbols = fetching
        self._p17_fetch_in_progress = bool(fetching)
        self._p17_update_refresh_state()
        if etf_symbol == getattr(self, "_p17_etf_symbol", "SPY"):
            self.set_status_text(
                self.p17_status_lbl,
                f"Loading {self._p17_etf_label(etf_symbol)} holdings heatmap - {self._p17_interval_label()}...",
                status="warning",
            )

        def _run() -> None:
            try:
                from budget_terminal_app.workers.etf_heatmap import EtfHeatmapWorker

                task_result = MarketDataTaskRunner(default_timeout_seconds=120.0, default_retries=1).run(
                    f"etf_heatmap:{etf_symbol}",
                    lambda: EtfHeatmapWorker().fetch(self._p17_etf_fetch_symbol(etf_symbol)),
                    source="ETF holdings, yfinance",
                    success_check=lambda payload: payload is not None and int(getattr(payload, "holdings_loaded", 0) or 0) > 0,
                    failure_reason=f"{self._p17_etf_label(etf_symbol)} heatmap data could not be loaded.",
                )
                result = task_result.attach()
                if isinstance(result, dict):
                    raise RuntimeError(task_result.meta.get("failure_reason") or "ETF heatmap data could not be loaded.")
                self._invoke_main.emit(lambda payload=result, requested_symbol=etf_symbol: self._p17_apply_result(payload, requested_symbol))
            except Exception as exc:
                logger.error("%s heatmap refresh failed: %s", etf_symbol, exc)
                self._invoke_main.emit(lambda err=str(exc), requested_symbol=etf_symbol: self._p17_handle_error(err, requested_symbol))

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _p17_apply_result(self, result: Any, requested_symbol: Any = None) -> None:
        """Cache and render a fetched ETF heatmap payload."""
        etf_symbol = self._p17_normalize_etf_symbol(requested_symbol or getattr(result, "ticker", ""))
        if hasattr(self, '_record_data_health_payload'):
            self._record_data_health_payload('ETF heatmap', result, symbols=[etf_symbol])
        fetching = getattr(self, "_p17_fetching_symbols", set())
        fetching.discard(etf_symbol)
        self._p17_fetching_symbols = fetching
        self._p17_fetch_in_progress = bool(fetching)
        self._p17_results[etf_symbol] = result
        self._p17_last_fetch_by_etf[etf_symbol] = datetime.datetime.now().timestamp()
        if etf_symbol == getattr(self, "_p17_etf_symbol", "SPY"):
            self._p17_result = result
            self._p17_render_interval_result(reset_view=True)
        self._p17_update_refresh_state()

    def _p17_render_interval_result(self, *, reset_view: bool = False) -> None:
        """Render the cached ETF heatmap payload for the selected interval."""
        result = self._p17_current_result()
        if result is None:
            return
        rows = []
        etf_symbol = self._p17_normalize_etf_symbol(getattr(self, "_p17_etf_symbol", "SPY"))
        etf_label = self._p17_etf_label(etf_symbol)
        interval_key = self._p17_interval_key
        interval_label = self._p17_interval_label(interval_key)
        for holding in list(getattr(result, "holdings", []) or []):
            changes = dict(getattr(holding, "changes", {}) or {})
            change = changes.get(interval_key)
            if not isinstance(change, (int, float)) and interval_key == "live":
                change = getattr(holding, "change_pct", None)
            rows.append({
                "symbol": str(getattr(holding, "symbol", "") or "").upper().strip(),
                "name": str(getattr(holding, "name", "") or "").strip(),
                "sector": str(getattr(holding, "sector", "") or "Unclassified").strip() or "Unclassified",
                "weight": getattr(holding, "weight", None),
                "price": getattr(holding, "price", None),
                "change_pct": change,
                "changes": changes,
                "interval_key": interval_key,
                "interval_label": interval_label,
                "change_label": f"{interval_label} Change",
                "etf": etf_symbol,
                "etf_label": etf_label,
            })
        self._p17_rows = rows
        self.p17_heatmap.set_data(rows, reset_view=reset_view)
        self._p17_update_summary(result)
        selected_row = self._p17_selected_row if (self._p17_selected_row or {}).get("etf") == etf_symbol else None
        selected_symbol = str((selected_row or {}).get("symbol") or "").upper().strip()
        selected = next((row for row in rows if row.get("symbol") == selected_symbol), None)
        self._p17_on_holding_selected(selected or (rows[0] if rows else None))
        issuer = str(getattr(result, "issuer", "") or "ETF holdings source").strip()
        status_text, status_type = describe_market_data_status(
            result,
            f"Loaded {len(rows)} {etf_label} holdings from {issuer} - {interval_label}.",
        )
        self.set_status_text(self.p17_status_lbl, status_text, status=status_type if rows else "warning")
        self._set_data_collection_info(data_sources_from_meta(result, issuer or "ETF holdings source"))

    def _p17_update_summary(self, result: Any) -> None:
        """Update ETF heatmap summary metrics."""
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        holdings_loaded = int(getattr(result, "holdings_loaded", 0) or 0)
        summary = self._p17_interval_summary(result)
        quote_coverage = int(getattr(summary, "quote_coverage", getattr(result, "quote_coverage", 0)) or 0)
        self.p17_summary_labels["updated"].setText(now_str)
        self.p17_summary_labels["holdings"].setText(str(holdings_loaded))
        self.p17_summary_labels["coverage"].setText(f"{quote_coverage}/{holdings_loaded}" if holdings_loaded else "--")
        weighted = getattr(summary, "weighted_move", getattr(result, "weighted_day_move", None))
        self._p17_set_change_label(self.p17_summary_labels["weighted"], weighted, large=False)
        strongest = getattr(summary, "strongest", getattr(result, "strongest", None))
        weakest = getattr(summary, "weakest", getattr(result, "weakest", None))
        self._p17_set_holding_summary(self.p17_summary_labels["strongest"], strongest)
        self._p17_set_holding_summary(self.p17_summary_labels["weakest"], weakest)

    def _p17_set_holding_summary(self, label: QLabel, holding: Any) -> None:
        if label is None:
            return
        symbol = str(getattr(holding, "symbol", "") or "").upper().strip()
        change = (getattr(holding, "changes", {}) or {}).get(self._p17_interval_key)
        if not isinstance(change, (int, float)) and self._p17_interval_key == "live":
            change = getattr(holding, "change_pct", None)
        if not symbol or not isinstance(change, (int, float)):
            label.setText("--")
            label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; font-weight: bold; border: none;')
            return
        sign = "+" if float(change) >= 0 else ""
        label.setText(f"{symbol} {sign}{float(change):.2f}%")
        color = self.theme_color("accent_positive" if float(change) >= 0 else "accent_negative")
        label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; border: none;")

    def _p17_on_holding_selected(self, row: Any) -> None:
        """Render selected holding details."""
        payload = row if isinstance(row, dict) else {}
        if not payload:
            self._p17_selected_row = None
            self.p17_detail_symbol_lbl.setText("Select a holding")
            self.p17_detail_name_lbl.setText("--")
            self.p17_detail_sector_lbl.setText("Sector: --")
            self.p17_detail_weight_lbl.setText("Weight: --")
            self.p17_detail_price_lbl.setText("Price: --")
            self.p17_detail_change_lbl.setText("Change: --")
            return
        self._p17_selected_row = dict(payload)
        symbol = str(payload.get("symbol") or "--")
        self.p17_detail_symbol_lbl.setText(symbol)
        self.p17_detail_name_lbl.setText(str(payload.get("name") or "--"))
        self.p17_detail_sector_lbl.setText(f"Sector: {payload.get('sector') or 'Unclassified'}")
        self.p17_detail_weight_lbl.setText(f"Weight: {self._p17_format_weight_pct(payload.get('weight'))}")
        price = payload.get("price")
        self.p17_detail_price_lbl.setText(f"Price: ${float(price):,.2f}" if isinstance(price, (int, float)) else "Price: --")
        change = payload.get("change_pct")
        change_label = str(payload.get("change_label") or f"{self._p17_interval_label()} Change")
        self.p17_detail_change_lbl.setText(f"{change_label}: {self._p17_format_pct(change, signed=True)}")
        self._p17_set_change_label(self.p17_detail_change_lbl, change, large=True, prefix=f"{change_label}: ")

    def _p17_open_symbol_in_charts(self, symbol: Any) -> None:
        """Double-click a heatmap tile to open the holding in Charts."""
        ticker = str(symbol or "").upper().strip()
        if not ticker:
            return
        self.p10_symbol = ticker
        if isinstance(getattr(self, "chart_page_state", None), dict):
            self.chart_page_state = {**self.chart_page_state, "symbol": ticker}
        page_index = self.stacked_widget.indexOf(self.page10) if hasattr(self, "stacked_widget") and hasattr(self, "page10") else 9
        target_index = page_index if page_index >= 0 else 9
        self.switch_page(target_index)
        if hasattr(self, "p10_symbol_input"):
            self.p10_symbol_input.setText(ticker)
        if hasattr(self, "_p10_load_from_input"):
            self._p10_load_from_input()

    def _p17_handle_error(self, error: str, requested_symbol: Any = None) -> None:
        """Show a failed heatmap refresh state."""
        etf_symbol = self._p17_normalize_etf_symbol(requested_symbol or getattr(self, "_p17_etf_symbol", "SPY"))
        fetching = getattr(self, "_p17_fetching_symbols", set())
        fetching.discard(etf_symbol)
        self._p17_fetching_symbols = fetching
        self._p17_fetch_in_progress = bool(fetching)
        if etf_symbol == getattr(self, "_p17_etf_symbol", "SPY"):
            self.set_status_text(self.p17_status_lbl, f"{self._p17_etf_label(etf_symbol)} heatmap refresh failed: {error}", status="negative")
        if hasattr(self, '_record_data_health_exception'):
            self._record_data_health_exception('ETF heatmap', error, symbols=[etf_symbol])
        self._p17_update_refresh_state()

    def _apply_spy_heatmap_theme(self) -> None:
        """Refresh ETF heatmap colors after a theme change."""
        panel_style = (
            f'background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px;'
        )
        self.p17_summary_frame.setStyleSheet(panel_style)
        self.p17_detail_frame.setStyleSheet(panel_style)
        for key, label in getattr(self, "p17_summary_labels", {}).items():
            if label is None:
                continue
            if key.endswith("_header"):
                label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 12px; border: none;')
            elif key.endswith("_sep"):
                label.setStyleSheet(f'background: {self.theme_color("panel_border")};')
            elif key not in ("weighted", "strongest", "weakest"):
                label.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 14px; font-weight: bold; border: none;')
        for label in (
            self.p17_detail_symbol_lbl,
            self.p17_detail_name_lbl,
            self.p17_detail_sector_lbl,
            self.p17_detail_weight_lbl,
            self.p17_detail_price_lbl,
        ):
            label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self._p17_set_change_label(self.p17_summary_labels.get("weighted"), self._p17_current_weighted_change(), large=False)
        self._p17_set_change_label(
            self.p17_detail_change_lbl,
            (self._p17_selected_row or {}).get("change_pct") if self._p17_selected_row else None,
            large=True,
            prefix=f"{self._p17_interval_label()} Change: ",
        )
        self.set_status_text(
            self.p17_status_lbl,
            self.p17_status_lbl.text(),
            status=self.p17_status_lbl.property("bt_status") or "muted",
        )
        self.p17_heatmap.set_theme(
            background=self.theme_color("background_primary"),
            panel=self.theme_color("panel_background"),
            border=self.theme_color("panel_border"),
            text=self.theme_color("text_primary"),
            muted=self.theme_color("text_muted"),
            up=self.theme_color("accent_positive"),
            down=self.theme_color("accent_negative"),
            accent=self.theme_color("accent"),
        )
        self._p17_style_etf_buttons()
        self._p17_style_interval_buttons()

    def _p17_current_weighted_change(self) -> float | None:
        numerator = 0.0
        denominator = 0.0
        for row in getattr(self, "_p17_rows", []):
            weight = row.get("weight")
            change = row.get("change_pct")
            if isinstance(weight, (int, float)) and isinstance(change, (int, float)):
                numerator += float(weight) * float(change)
                denominator += float(weight)
        return numerator / denominator if denominator > 0 else None

    def _p17_select_etf(self, symbol: Any) -> None:
        etf_symbol = self._p17_normalize_etf_symbol(symbol)
        self._p17_etf_symbol = etf_symbol
        for button_key, button in getattr(self, "_p17_etf_buttons", {}).items():
            button.blockSignals(True)
            button.setChecked(button_key == etf_symbol)
            button.blockSignals(False)
        self._p17_style_etf_buttons()
        result = self._p17_current_result()
        if result is not None:
            self._p17_result = result
            self._p17_render_interval_result(reset_view=True)
            self._p17_update_refresh_state()
            self._p17_request_refresh(symbol=etf_symbol)
            return
        self._p17_result = None
        self._p17_rows = []
        self.p17_heatmap.set_data([], reset_view=True)
        self._p17_on_holding_selected(None)
        self._p17_reset_summary()
        if etf_symbol in getattr(self, "_p17_fetching_symbols", set()):
            self.set_status_text(self.p17_status_lbl, f"Loading {self._p17_etf_label(etf_symbol)} holdings heatmap - {self._p17_interval_label()}...", status="warning")
            self._p17_update_refresh_state()
            return
        self._p17_request_refresh(symbol=etf_symbol)

    def _p17_select_interval(self, interval_key: str) -> None:
        key = str(interval_key or "live").strip().lower()
        if key not in dict(self._P17_INTERVALS):
            key = "live"
        self._p17_interval_key = key
        for button_key, button in getattr(self, "_p17_interval_buttons", {}).items():
            button.blockSignals(True)
            button.setChecked(button_key == key)
            button.blockSignals(False)
        self._p17_style_interval_buttons()
        self._p17_render_interval_result(reset_view=False)

    def _p17_interval_label(self, interval_key: Any = None) -> str:
        key = str(interval_key or getattr(self, "_p17_interval_key", "live") or "live").strip().lower()
        return dict(self._P17_INTERVALS).get(key, "Live")

    def _p17_interval_summary(self, result: Any) -> Any:
        summaries = getattr(result, "interval_summaries", {}) or {}
        return summaries.get(getattr(self, "_p17_interval_key", "live")) or summaries.get("live") or result

    def _p17_current_result(self) -> Any:
        etf_symbol = self._p17_normalize_etf_symbol(getattr(self, "_p17_etf_symbol", "SPY"))
        result = getattr(self, "_p17_results", {}).get(etf_symbol)
        if result is not None:
            return result
        current = getattr(self, "_p17_result", None)
        if current is not None and self._p17_normalize_etf_symbol(getattr(current, "ticker", "")) == etf_symbol:
            return current
        return None

    def _p17_update_refresh_state(self) -> None:
        if not hasattr(self, "p17_refresh_btn"):
            return
        etf_symbol = self._p17_normalize_etf_symbol(getattr(self, "_p17_etf_symbol", "SPY"))
        self.p17_refresh_btn.setEnabled(etf_symbol not in getattr(self, "_p17_fetching_symbols", set()))

    def _p17_reset_summary(self) -> None:
        labels = getattr(self, "p17_summary_labels", {})
        now_label = labels.get("updated")
        if now_label is not None:
            now_label.setText("--")
        for key in ("holdings", "coverage"):
            if labels.get(key) is not None:
                labels[key].setText("--")
        self._p17_set_change_label(labels.get("weighted"), None, large=False)
        self._p17_set_holding_summary(labels.get("strongest"), None)
        self._p17_set_holding_summary(labels.get("weakest"), None)

    def _p17_style_etf_buttons(self) -> None:
        active_symbol = self._p17_normalize_etf_symbol(getattr(self, "_p17_etf_symbol", "SPY"))
        for symbol, button in getattr(self, "_p17_etf_buttons", {}).items():
            is_active = symbol == active_symbol
            background = self.theme_color("button_checked_bg" if is_active else "panel_background")
            text = self.theme_color("text_primary")
            border = self.theme_color("button_checked_border" if is_active else "panel_border")
            button.setStyleSheet(
                f"QPushButton {{ background: {background}; color: {text}; border: 1px solid {border}; "
                "border-radius: 4px; padding: 3px 10px; font-weight: bold; }"
            )

    def _p17_style_interval_buttons(self) -> None:
        active_key = getattr(self, "_p17_interval_key", "live")
        for key, button in getattr(self, "_p17_interval_buttons", {}).items():
            is_active = key == active_key
            background = self.theme_color("button_checked_bg" if is_active else "panel_background")
            text = self.theme_color("text_primary")
            border = self.theme_color("button_checked_border" if is_active else "panel_border")
            button.setStyleSheet(
                f"QPushButton {{ background: {background}; color: {text}; border: 1px solid {border}; "
                "border-radius: 4px; padding: 3px 8px; font-weight: bold; }"
            )

    def _p17_set_change_label(self, label: Any, value: Any, *, large: bool = False, prefix: str = "") -> None:
        if label is None:
            return
        if not isinstance(value, (int, float)):
            label.setText(f"{prefix}--")
            label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: {"14" if large else "12"}px; font-weight: bold; border: none;')
            return
        sign = "+" if float(value) >= 0 else ""
        label.setText(f"{prefix}{sign}{float(value):.2f}%")
        color = self.theme_color("accent_positive" if float(value) >= 0 else "accent_negative")
        label.setStyleSheet(f'color: {color}; font-size: {"14" if large else "12"}px; font-weight: bold; border: none;')

    def _p17_normalize_etf_symbol(self, symbol: Any) -> str:
        text = str(symbol or "").upper().strip()
        options = self._p17_etf_options()
        if text in options:
            return text
        for key, option in options.items():
            if text in {option["fetch"], option["label"].upper()}:
                return key
        return "SPY"

    def _p17_etf_options(self) -> dict[str, dict[str, str]]:
        return {
            key: {"label": label, "fetch": fetch_symbol}
            for key, label, fetch_symbol in self._P17_ETFS
        }

    def _p17_etf_label(self, symbol: Any = None) -> str:
        key = self._p17_normalize_etf_symbol(symbol or getattr(self, "_p17_etf_symbol", "SPY"))
        return self._p17_etf_options().get(key, {}).get("label", "SPY")

    def _p17_etf_fetch_symbol(self, symbol: Any = None) -> str:
        key = self._p17_normalize_etf_symbol(symbol or getattr(self, "_p17_etf_symbol", "SPY"))
        return self._p17_etf_options().get(key, {}).get("fetch", "SPY")

    @staticmethod
    def _p17_format_pct(value: Any, *, signed: bool = False) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        sign = "+" if signed and number >= 0 else ""
        return f"{sign}{number:.2f}%"

    @staticmethod
    def _p17_format_weight_pct(value: Any) -> str:
        try:
            number = float(value) * 100.0
        except (TypeError, ValueError):
            return "--"
        return f"{number:.2f}%"
