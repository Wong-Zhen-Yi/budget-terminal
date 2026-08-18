from __future__ import annotations

from typing import Any

from ..compat import *
from budget_terminal_app.services.strategies import (
    STRATEGY_INTERVALS,
    StrategyPerformanceService,
    strategy_signature,
)
from budget_terminal_app.strategies import (
    BUILTIN_INDEX_CARD_ID,
    create_custom_strategy,
    load_strategies_state,
    normalize_strategy_symbols,
    normalize_strategy_weights,
    save_strategies_state,
)
from budget_terminal_app.widgets.strategy_cards import StrategyCardWidget, StrategyGridWidget


P29_MAX_WORKERS = 4


class StrategiesPageMixin:
    """First-class page for equal-weight strategy and portfolio baskets."""

    def _p29_page_is_visible(self) -> bool:
        """Return whether Cards is the current real-app page."""
        checker = getattr(self, "_is_current_page", None)
        if callable(checker):
            return bool(checker(getattr(self, "page29", None)))
        return True

    def init_page29(self) -> None:
        self.strategies_state = load_strategies_state()
        self._p29_cards: dict[str, StrategyCardWidget] = {}
        self._p29_models: dict[str, dict[str, Any]] = {}
        self._p29_visible_card_ids: list[str] = []
        self._p29_performance_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._p29_request_seq = 0
        self._p29_active_requests: dict[str, int] = {}
        self._p29_inflight_signatures: dict[str, tuple[Any, ...]] = {}
        self._p29_queued_signatures: dict[str, tuple[Any, ...]] = {}
        self._p29_render_pending = False

        layout = QVBoxLayout(self.page29)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("<b>Cards</b>")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel("Equal-weight, custom-weight, and live portfolio baskets")
        self.set_theme_role(subtitle, "muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch()
        self.p29_status_label = QLabel("Ready")
        self.p29_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p29_status_label, "status_muted")
        header.addWidget(self.p29_status_label)
        self.p29_portfolio_cards_btn = QPushButton("Portfolio Cards")
        header.addWidget(self.p29_portfolio_cards_btn)
        self.p29_new_btn = QPushButton("New Card")
        self.set_theme_variant(self.p29_new_btn, "accent")
        self.p29_new_btn.clicked.connect(self._p29_add_custom_strategy)
        header.addWidget(self.p29_new_btn)
        self.p29_refresh_btn = QPushButton("Refresh")
        self.p29_refresh_btn.clicked.connect(lambda: self._p29_refresh_performance(force=True))
        header.addWidget(self.p29_refresh_btn)
        layout.addLayout(header)

        self.p29_scroll = QScrollArea()
        self.p29_scroll.setWidgetResizable(True)
        self.p29_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p29_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p29_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p29_grid = StrategyGridWidget(self._p29_reorder_card)
        self.p29_scroll.setWidget(self.p29_grid)
        layout.addWidget(self.p29_scroll, 1)
        self._p29_refresh_cards(request_data=False)

    def _p29_get_service(self) -> StrategyPerformanceService:
        service = getattr(self, "_p29_performance_service", None)
        if service is None:
            service = StrategyPerformanceService(getattr(self, "_cache_manager", None))
            self._p29_performance_service = service
        return service

    def _p29_get_executor(self) -> ThreadPoolExecutor:
        executor = getattr(self, "_p29_executor", None)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=P29_MAX_WORKERS)
            self._p29_executor = executor
        return executor

    def _p29_portfolio_models(self) -> list[dict[str, Any]]:
        state = getattr(self, "all_portfolios_state", {})
        portfolios = state.get("portfolios", {}) if isinstance(state, dict) else {}
        order = state.get("portfolio_order", []) if isinstance(state, dict) else []
        if not isinstance(order, list):
            order = []
        models = []
        for portfolio_id in order:
            entry = portfolios.get(portfolio_id, {}) if isinstance(portfolios, dict) else {}
            if not isinstance(entry, dict):
                continue
            saved_symbols = normalize_strategy_symbols(entry.get("portfolio", []))
            tracker = entry.get("portfolio_tracker", {}) if isinstance(entry.get("portfolio_tracker"), dict) else {}
            symbols = []
            shares = {}
            for symbol in saved_symbols:
                tracker_entry = tracker.get(symbol)
                if not isinstance(tracker_entry, dict):
                    tracker_entry = next(
                        (
                            value for saved_symbol, value in tracker.items()
                            if str(saved_symbol or "").upper().strip() == symbol and isinstance(value, dict)
                        ),
                        {},
                    )
                if tracker_entry.get("include_in_weight") is False:
                    continue
                symbols.append(symbol)
                try:
                    share_count = float(tracker_entry.get("shares", 0.0) or 0.0)
                except (TypeError, ValueError):
                    share_count = 0.0
                if share_count > 0.0:
                    shares[symbol] = share_count
            models.append({
                "id": f"portfolio:{portfolio_id}",
                "portfolio_id": str(portfolio_id),
                "type": "portfolio",
                "name": str(entry.get("name", "Portfolio") or "Portfolio"),
                "symbols": symbols,
                "weighting": "portfolio",
                "shares": shares,
                "cash_balance": max(float(entry.get("cash_balance", 0.0) or 0.0), 0.0),
                "weights": {},
                "meta_prefix": f"Portfolio basket | {len(symbols)} holdings",
                "meta": f"Portfolio basket | {len(symbols)} holdings | actual weights",
                "action_label": "Open Basket",
            })
        return models

    def _p29_all_models(self) -> list[dict[str, Any]]:
        models = [{
            "id": BUILTIN_INDEX_CARD_ID,
            "type": "builtin",
            "name": "Index",
            "symbols": ["SPY"],
            "weighting": "custom",
            "weights": {"SPY": 100.0},
            "shares": {},
            "cash_balance": 0.0,
            "meta_prefix": "Default basket | SPY 100%",
            "meta": "Default basket | SPY 100%",
            "action_label": "Open Basket",
        }]
        models.extend(self._p29_portfolio_models())
        for card in self.strategies_state.get("custom_cards", []):
            symbols = list(card.get("symbols", []))
            weighting = str(card.get("weighting", "equal") or "equal")
            weighting_label = "Custom weights" if weighting == "custom" else "Equal weight"
            models.append({
                **card,
                "type": "custom",
                "shares": {},
                "cash_balance": 0.0,
                "meta_prefix": f"Starter/custom basket | {len(symbols)} holdings",
                "meta": f"Starter/custom basket | {len(symbols)} holdings | {weighting_label}",
                "action_label": "Edit Basket",
            })
        return models

    def _p29_sorted_visible_models(self) -> list[dict[str, Any]]:
        all_models = self._p29_all_models()
        model_map = {model["id"]: model for model in all_models}
        hidden_ids = {f"portfolio:{value}" for value in self.strategies_state.get("hidden_portfolio_ids", [])}
        ordered_ids = []
        for card_id in self.strategies_state.get("card_order", []):
            if card_id in model_map and card_id not in hidden_ids and card_id not in ordered_ids:
                ordered_ids.append(card_id)
        for model in all_models:
            card_id = model["id"]
            if card_id not in hidden_ids and card_id not in ordered_ids:
                ordered_ids.append(card_id)
        return [model_map[card_id] for card_id in ordered_ids]

    def _p29_refresh_cards(self, *, request_data: bool = True) -> None:
        if not hasattr(self, "p29_grid"):
            return
        models = self._p29_sorted_visible_models()
        self._p29_models = {model["id"]: model for model in models}
        self._p29_visible_card_ids = [model["id"] for model in models]
        intervals = self.strategies_state.get("intervals", {})
        cards = []
        for model in models:
            card_id = model["id"]
            card = StrategyCardWidget(
                model,
                interval_key=str(intervals.get(card_id, "1y") or "1y"),
                on_interval=self._p29_select_interval,
                on_action=self._p29_open_card,
                on_remove=self._p29_remove_custom_strategy if model.get("type") == "custom" else None,
                on_hide=self._p29_hide_portfolio_card if model.get("type") == "portfolio" else None,
            )
            cards.append(card)
            self._p29_cards[card_id] = card
        self.p29_grid.set_cards(cards)
        self._p29_cards = {card.card_id: card for card in cards}
        self._p29_rebuild_portfolio_menu()
        self._apply_strategies_theme()
        # After the theme so hydrated cards pick up the themed positive/negative colours.
        self._p29_hydrate_cached_cards()
        if request_data:
            QTimer.singleShot(0, lambda: self._p29_request_visible_cards(force=False))

    def _p29_rebuild_portfolio_menu(self) -> None:
        if not hasattr(self, "p29_portfolio_cards_btn"):
            return
        menu = QMenu(self.p29_portfolio_cards_btn)
        hidden = set(self.strategies_state.get("hidden_portfolio_ids", []))
        portfolio_models = self._p29_portfolio_models()
        if not portfolio_models:
            empty_action = menu.addAction("No saved portfolios")
            empty_action.setEnabled(False)
        for model in portfolio_models:
            portfolio_id = model["portfolio_id"]
            action = menu.addAction(model["name"])
            action.setCheckable(True)
            action.setChecked(portfolio_id not in hidden)
            action.toggled.connect(
                lambda checked, selected=portfolio_id: self._p29_set_portfolio_card_visible(selected, checked)
            )
        self.p29_portfolio_cards_btn.setMenu(menu)

    def _p29_save_state(self) -> None:
        self.strategies_state = save_strategies_state(self.strategies_state)

    def _p29_set_status(self, text: Any, status: str = "muted") -> None:
        if hasattr(self, "p29_status_label"):
            self.set_status_text(self.p29_status_label, text, status=status)
        if hasattr(self, "status_bar"):
            self.set_status_text(self.status_bar, text, status=status)

    def _p29_on_show(self) -> None:
        self._p29_render_pending = False
        self._p29_refresh_cards(request_data=True)
        self._p29_set_status(f"Showing {len(self._p29_visible_card_ids)} card(s).")

    def _p29_select_interval(self, card_id: str, interval_key: str) -> None:
        if interval_key not in STRATEGY_INTERVALS or card_id not in self._p29_models:
            return
        self.strategies_state.setdefault("intervals", {})[card_id] = interval_key
        self._p29_save_state()
        card = self._p29_cards.get(card_id)
        if card is not None:
            card.set_active_interval(interval_key)
        self._p29_request_card(card_id, force=False)

    def _p29_card_interval(self, card_id: str) -> str:
        return str(self.strategies_state.get("intervals", {}).get(card_id, "1y") or "1y")

    def _p29_cache_key(self, model: dict[str, Any], interval_key: str) -> tuple[Any, ...]:
        return strategy_signature(
            model.get("symbols", []),
            interval_key,
            weighting=str(model.get("weighting", "equal") or "equal"),
            weights=model.get("weights", {}),
            shares=model.get("shares", {}),
            cash_balance=model.get("cash_balance", 0.0),
        )

    def _p29_cached_payload(
        self,
        model: dict[str, Any],
        interval_key: str,
        cache_key: tuple[Any, ...],
    ) -> tuple[dict[str, Any] | None, bool]:
        """Return (payload, is_fresh) from memory first, then the on-disk cache."""
        payload = self._p29_performance_cache.get(cache_key)
        if payload is not None:
            return payload, True
        reader = getattr(self._p29_get_service(), "cached_payload", None)
        if not callable(reader):
            return None, False
        try:
            payload, is_fresh = reader(
                list(model.get("symbols", [])),
                interval_key,
                weighting=str(model.get("weighting", "equal") or "equal"),
                weights=dict(model.get("weights", {})),
                shares=dict(model.get("shares", {})),
                cash_balance=float(model.get("cash_balance", 0.0) or 0.0),
            )
        except Exception:
            return None, False
        if payload is not None and is_fresh:
            self._p29_performance_cache[cache_key] = payload
        return payload, bool(is_fresh)

    def _p29_render_payload(self, card_id: str, payload: dict[str, Any]) -> None:
        """Apply one payload to its model, and to its card when the page is on screen."""
        model = self._p29_models.get(card_id)
        if model is not None:
            model["resolved_weights"] = dict(payload.get("weights", {}))
            model["resolved_weighting"] = str(payload.get("weighting", "") or "")
        if not self._p29_page_is_visible():
            self._p29_render_pending = True
            return
        card = self._p29_cards.get(card_id)
        if card is not None:
            card.set_performance(payload)

    def _p29_hydrate_cached_cards(self) -> None:
        """Paint every card that already has a cached payload so revisits skip 'Loading...'."""
        for card_id in list(self._p29_visible_card_ids):
            model = self._p29_models.get(card_id)
            card = self._p29_cards.get(card_id)
            if model is None or card is None:
                continue
            interval_key = self._p29_card_interval(card_id)
            payload, _ = self._p29_cached_payload(model, interval_key, self._p29_cache_key(model, interval_key))
            if payload is None:
                continue
            model["resolved_weights"] = dict(payload.get("weights", {}))
            model["resolved_weighting"] = str(payload.get("weighting", "") or "")
            card.set_performance(payload)
        self._p29_render_pending = False

    def _p29_request_visible_cards(self, *, force: bool) -> None:
        """Fan every stale visible card into one batched download per interval."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for card_id in list(self._p29_visible_card_ids):
            entry = self._p29_prepare_request(card_id, force=force)
            if entry is not None:
                groups.setdefault(entry["interval_key"], []).append(entry)
        for interval_key, entries in groups.items():
            self._p29_submit_batch(interval_key, entries, force=force)

    def _p29_refresh_performance(self, *, force: bool) -> None:
        if force:
            self._p29_performance_cache.clear()
        self._p29_set_status("Refreshing card performance...", "warning")
        self._p29_request_visible_cards(force=force)

    def _p29_request_card(self, card_id: str, *, force: bool) -> None:
        entry = self._p29_prepare_request(card_id, force=force)
        if entry is not None:
            self._p29_submit_batch(entry["interval_key"], [entry], force=force)

    def _p29_prepare_request(self, card_id: str, *, force: bool) -> dict[str, Any] | None:
        """Claim one card's in-flight slot and return its batch entry, or None when nothing is due."""
        model = self._p29_models.get(card_id)
        card = self._p29_cards.get(card_id)
        if model is None or card is None:
            return None
        symbols = normalize_strategy_symbols(model.get("symbols", []))
        if not symbols:
            card.set_error("This basket has no holdings.")
            return None
        interval_key = self._p29_card_interval(card_id)
        cache_key = self._p29_cache_key(model, interval_key)
        active_signature = self._p29_inflight_signatures.get(card_id)
        if active_signature is not None:
            if active_signature == cache_key:
                self._p29_queued_signatures.pop(card_id, None)
            else:
                self._p29_queued_signatures[card_id] = cache_key
            return None
        payload, is_fresh = (None, False) if force else self._p29_cached_payload(model, interval_key, cache_key)
        if payload is not None:
            # Paint the known values straight away; a stale payload still triggers a refresh below.
            self._p29_render_payload(card_id, payload)
            if is_fresh:
                return None
        else:
            card.set_loading()
        self._p29_request_seq += 1
        request_id = self._p29_request_seq
        self._p29_active_requests[card_id] = request_id
        self._p29_inflight_signatures[card_id] = cache_key
        return {
            "card_id": card_id,
            "request_id": request_id,
            "cache_key": cache_key,
            "interval_key": interval_key,
            "request": {
                "key": card_id,
                "symbols": symbols,
                "weighting": str(model.get("weighting", "equal") or "equal"),
                "weights": dict(model.get("weights", {})),
                "shares": dict(model.get("shares", {})),
                "cash_balance": float(model.get("cash_balance", 0.0) or 0.0),
            },
        }

    def _p29_submit_batch(self, interval_key: str, entries: list[dict[str, Any]], *, force: bool) -> None:
        """Run one fetch covering every entry, then deliver results card by card."""
        if not entries:
            return
        service = self._p29_get_service()
        payload_requests = [entry["request"] for entry in entries]

        def _fetch() -> dict[Any, Any]:
            return service.fetch_many(payload_requests, interval_key, force=force)

        future = self._p29_get_executor().submit(_fetch)

        def _done(completed: Any) -> None:
            try:
                results = completed.result()
                batch_error = None
            except Exception as exc:
                results = {}
                batch_error = str(exc)
            for entry in entries:
                outcome = results.get(entry["card_id"])
                if isinstance(outcome, dict):
                    payload, error = outcome, None
                elif isinstance(outcome, Exception):
                    payload, error = None, str(outcome)
                else:
                    payload, error = None, batch_error or "Performance data unavailable."
                self._invoke_main.emit(
                    lambda cid=entry["card_id"], rid=entry["request_id"], key=entry["cache_key"],
                    result=payload, message=error:
                    self._p29_apply_performance(cid, rid, key, result, message)
                )

        future.add_done_callback(_done)

    def _p29_apply_performance(
        self,
        card_id: str,
        request_id: int,
        cache_key: tuple[Any, ...],
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        if self._p29_active_requests.get(card_id) != request_id:
            return
        self._p29_inflight_signatures.pop(card_id, None)
        queued_signature = self._p29_queued_signatures.pop(card_id, None)
        card = self._p29_cards.get(card_id)
        model = self._p29_models.get(card_id)
        interval_key = self._p29_card_interval(card_id)
        current_key = self._p29_cache_key(model, interval_key) if model is not None else None
        is_current_input = current_key == cache_key
        if error or payload is None:
            if is_current_input and self._p29_page_is_visible() and card is not None:
                card.set_error(error or "Performance data unavailable.")
        else:
            self._p29_performance_cache[cache_key] = payload
        if queued_signature is not None and current_key is not None and current_key != cache_key:
            self._p29_request_card(card_id, force=False)
            return
        if payload is None or error or not is_current_input:
            return
        self._p29_render_payload(card_id, payload)
        if self._p29_page_is_visible():
            self._p29_set_status("Card performance updated.", "positive")

    def _p29_strategy_editor(self, card: dict[str, Any] | None = None) -> dict[str, Any] | None:
        current = card or {}
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Card" if card else "New Card")
        dialog.resize(500, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Card name"))
        name_input = QLineEdit(str(current.get("name", "") or ""))
        name_input.setPlaceholderText("Example: AI Infrastructure")
        layout.addWidget(name_input)

        weighting_row = QHBoxLayout()
        weighting_row.addWidget(QLabel("Weighting"))
        weighting_combo = QComboBox()
        weighting_combo.addItem("Equal Weight", "equal")
        weighting_combo.addItem("Custom Weights", "custom")
        weighting_combo.setCurrentIndex(1 if current.get("weighting") == "custom" else 0)
        weighting_row.addWidget(weighting_combo, 1)
        layout.addLayout(weighting_row)

        holdings_table = QTableWidget(0, 2)
        holdings_table.setHorizontalHeaderLabels(["Ticker", "Weight %"])
        holdings_table.verticalHeader().setVisible(False)
        holdings_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        holdings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(holdings_table, 1)

        table_actions = QHBoxLayout()
        add_holding_btn = QPushButton("Add Holding")
        remove_holding_btn = QPushButton("Remove Holding")
        table_actions.addWidget(add_holding_btn)
        table_actions.addWidget(remove_holding_btn)
        table_actions.addStretch()
        total_label = QLabel("Total: 100.00%")
        self.set_theme_role(total_label, "muted")
        table_actions.addWidget(total_label)
        layout.addLayout(table_actions)

        table_guard = {"active": False}

        def _add_row(symbol: str = "", weight: float = 0.0) -> None:
            row = holdings_table.rowCount()
            holdings_table.insertRow(row)
            holdings_table.setItem(row, 0, QTableWidgetItem(str(symbol or "").upper()))
            holdings_table.setItem(row, 1, QTableWidgetItem(f"{float(weight):.2f}"))

        current_symbols = normalize_strategy_symbols(current.get("symbols", []))
        current_weights = dict(current.get("weights", {}))
        for symbol in current_symbols:
            _add_row(symbol, float(current_weights.get(symbol, 0.0) or 0.0))
        if holdings_table.rowCount() == 0:
            _add_row()

        def _refresh_weight_rows() -> None:
            if table_guard["active"]:
                return
            table_guard["active"] = True
            try:
                custom_mode = weighting_combo.currentData() == "custom"
                active_rows = [
                    row for row in range(holdings_table.rowCount())
                    if holdings_table.item(row, 0) is not None and holdings_table.item(row, 0).text().strip()
                ]
                equal_weight = 100.0 / len(active_rows) if active_rows else 0.0
                total = 0.0
                for row in range(holdings_table.rowCount()):
                    item = holdings_table.item(row, 1)
                    if item is None:
                        item = QTableWidgetItem("0.00")
                        holdings_table.setItem(row, 1, item)
                    if not custom_mode:
                        item.setText(f"{equal_weight if row in active_rows else 0.0:.2f}")
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    try:
                        total += max(float(item.text() or 0.0), 0.0) if row in active_rows else 0.0
                    except (TypeError, ValueError):
                        pass
                total_label.setText(f"Total: {total:.2f}%" + (" (normalized on save)" if custom_mode else ""))
            finally:
                table_guard["active"] = False

        add_holding_btn.clicked.connect(lambda: (_add_row(), _refresh_weight_rows()))

        def _remove_row() -> None:
            row = holdings_table.currentRow()
            if row < 0:
                row = holdings_table.rowCount() - 1
            if row >= 0:
                holdings_table.removeRow(row)
            if holdings_table.rowCount() == 0:
                _add_row()
            _refresh_weight_rows()

        remove_holding_btn.clicked.connect(_remove_row)
        weighting_combo.currentIndexChanged.connect(lambda *_: _refresh_weight_rows())
        holdings_table.itemChanged.connect(lambda *_: _refresh_weight_rows())
        _refresh_weight_rows()

        weight_label = QLabel("Custom positive weights are normalized to 100% when saved.")
        self.set_theme_role(weight_label, "muted")
        layout.addWidget(weight_label)
        error_label = QLabel("")
        self.set_theme_role(error_label, "status_negative")
        layout.addWidget(error_label)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save Card")
        self.set_theme_variant(save_button, "accent")
        actions.addWidget(cancel_button)
        actions.addWidget(save_button)
        layout.addLayout(actions)
        cancel_button.clicked.connect(dialog.reject)

        result: dict[str, Any] = {}

        def _save() -> None:
            symbols = []
            raw_weights = {}
            for row in range(holdings_table.rowCount()):
                symbol_item = holdings_table.item(row, 0)
                symbol = str(symbol_item.text() if symbol_item is not None else "").upper().strip()
                if not symbol or symbol in symbols:
                    continue
                symbols.append(symbol)
                weight_item = holdings_table.item(row, 1)
                try:
                    raw_weights[symbol] = float(weight_item.text() if weight_item is not None else 0.0)
                except (TypeError, ValueError):
                    raw_weights[symbol] = 0.0
            if not symbols:
                error_label.setText("Enter at least one ticker.")
                return
            weighting = str(weighting_combo.currentData() or "equal")
            weights = normalize_strategy_weights(symbols, raw_weights) if weighting == "custom" else {}
            if weighting == "custom" and not weights:
                error_label.setText("Enter at least one positive custom weight.")
                return
            result.update({
                "name": name_input.text().strip() or "Untitled Card",
                "symbols": symbols,
                "weighting": weighting,
                "weights": weights,
            })
            dialog.accept()

        save_button.clicked.connect(_save)
        name_input.setFocus()
        return result if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _p29_add_custom_strategy(self) -> None:
        values = self._p29_strategy_editor()
        if values is None:
            return
        card = create_custom_strategy(
            values["name"],
            values["symbols"],
            weighting=values["weighting"],
            weights=values["weights"],
        )
        self.strategies_state.setdefault("custom_cards", []).append(card)
        self.strategies_state.setdefault("card_order", []).append(card["id"])
        self._p29_save_state()
        self._p29_refresh_cards(request_data=True)
        self._p29_set_status(f"Added {card['name']}.", "positive")

    def _p29_edit_custom_strategy(self, card_id: str) -> None:
        cards = self.strategies_state.get("custom_cards", [])
        target = next((card for card in cards if card.get("id") == card_id), None)
        if target is None:
            return
        values = self._p29_strategy_editor(target)
        if values is None:
            return
        target["name"] = values["name"]
        target["symbols"] = values["symbols"]
        target["weighting"] = values["weighting"]
        target["weights"] = values["weights"]
        self._p29_performance_cache.clear()
        self._p29_save_state()
        self._p29_refresh_cards(request_data=True)
        self._p29_set_status(f"Updated {target['name']}.", "positive")

    def _p29_open_card(self, card_id: str) -> None:
        model = self._p29_models.get(card_id)
        if model is None:
            return
        if model.get("type") == "custom":
            self._p29_edit_custom_strategy(card_id)
            return
        self._p29_show_basket_dialog(model)

    def _p29_show_basket_dialog(self, model: dict[str, Any]) -> None:
        symbols = normalize_strategy_symbols(model.get("symbols", []))
        dialog = QDialog(self)
        dialog.setWindowTitle(str(model.get("name", "Basket")))
        dialog.resize(430, 360)
        layout = QVBoxLayout(dialog)
        resolved_weights = dict(model.get("resolved_weights", {}))
        weighting = str(model.get("weighting", "equal") or "equal")
        if not resolved_weights and weighting == "custom":
            resolved_weights = dict(model.get("weights", {}))
        if not resolved_weights and weighting == "equal" and symbols:
            resolved_weights = {symbol: 100.0 / len(symbols) for symbol in symbols}
        display_symbols = list(symbols)
        if "CASH" in resolved_weights:
            display_symbols.append("CASH")
        if weighting == "portfolio":
            weighting_label = "Actual portfolio weights" if resolved_weights else "Actual weights loading"
        elif weighting == "custom":
            weighting_label = "Custom weights"
        else:
            weighting_label = "Equal weight"
        description = QLabel(f"Basket holdings | {weighting_label}")
        self.set_theme_role(description, "section_title")
        layout.addWidget(description)
        table = QTableWidget(len(display_symbols), 2)
        table.setHorizontalHeaderLabels(["Ticker", "Weight"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for row, symbol in enumerate(display_symbols):
            table.setItem(row, 0, QTableWidgetItem(symbol))
            weight = resolved_weights.get(symbol)
            weight_text = f"{float(weight):.2f}%" if isinstance(weight, (int, float)) else "--"
            table.setItem(row, 1, QTableWidgetItem(weight_text))
        layout.addWidget(table, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        if model.get("type") == "portfolio":
            open_button = QPushButton("Open Portfolio")
            self.set_theme_variant(open_button, "accent")

            def _open_portfolio() -> None:
                portfolio_id = str(model.get("portfolio_id", ""))
                order = list(getattr(self, "all_portfolios_state", {}).get("portfolio_order", []))
                if portfolio_id in order:
                    self.set_active_portfolio_index(order.index(portfolio_id))
                dialog.accept()
                self.switch_page(1)

            open_button.clicked.connect(_open_portfolio)
            actions.addWidget(open_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        dialog.exec()

    def _p29_remove_custom_strategy(self, card_id: str) -> None:
        target = next(
            (card for card in self.strategies_state.get("custom_cards", []) if card.get("id") == card_id),
            None,
        )
        if target is None:
            return
        reply = QMessageBox.question(
            self,
            "Remove Card",
            f"Remove {target.get('name', 'this card')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.strategies_state["custom_cards"] = [
            card for card in self.strategies_state.get("custom_cards", []) if card.get("id") != card_id
        ]
        self.strategies_state["card_order"] = [
            value for value in self.strategies_state.get("card_order", []) if value != card_id
        ]
        self.strategies_state.get("intervals", {}).pop(card_id, None)
        self._p29_save_state()
        self._p29_refresh_cards(request_data=False)
        self._p29_set_status("Card removed.", "positive")

    def _p29_hide_portfolio_card(self, card_id: str) -> None:
        if card_id.startswith("portfolio:"):
            self._p29_set_portfolio_card_visible(card_id.split(":", 1)[1], False)

    def _p29_set_portfolio_card_visible(self, portfolio_id: str, visible: bool) -> None:
        hidden = list(self.strategies_state.get("hidden_portfolio_ids", []))
        if visible:
            hidden = [value for value in hidden if value != portfolio_id]
        elif portfolio_id not in hidden:
            hidden.append(portfolio_id)
        self.strategies_state["hidden_portfolio_ids"] = hidden
        self._p29_save_state()
        self._p29_refresh_cards(request_data=True)
        self._p29_set_status("Portfolio card shown." if visible else "Portfolio card hidden.", "positive")

    def _p29_reorder_card(self, card_id: str, target_index: int) -> None:
        visible_ids = list(self._p29_visible_card_ids)
        if card_id not in visible_ids:
            return
        source_index = visible_ids.index(card_id)
        target_index = min(max(int(target_index), 0), len(visible_ids) - 1)
        if source_index == target_index:
            return
        visible_ids.pop(source_index)
        visible_ids.insert(target_index, card_id)
        remaining_ids = [
            value for value in self.strategies_state.get("card_order", []) if value not in visible_ids
        ]
        self.strategies_state["card_order"] = visible_ids + remaining_ids
        self._p29_save_state()
        self._p29_refresh_cards(request_data=False)
        self._p29_set_status("Card order saved.", "positive")

    def _apply_strategies_theme(self) -> None:
        for card in getattr(self, "_p29_cards", {}).values():
            card.set_colors(
                background=self.theme_color("panel_background"),
                border=self.theme_color("panel_border"),
                muted=self.theme_color("text_muted"),
                positive=self.theme_color("accent_positive"),
                negative=self.theme_color("accent_negative"),
            )
        if hasattr(self, "p29_status_label"):
            self.set_status_text(
                self.p29_status_label,
                self.p29_status_label.text(),
                status=str(self.p29_status_label.property("bt_status") or "muted"),
            )
