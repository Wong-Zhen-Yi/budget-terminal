from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.services.strategies import equal_weight_performance, weighted_performance
from budget_terminal_app.strategies import (
    BUILTIN_INDEX_CARD_ID,
    STARTER_CARDS_VERSION,
    STARTER_CUSTOM_CARDS,
    clear_custom_strategies,
    create_custom_strategy,
    export_custom_strategies,
    load_custom_strategies_import,
    load_strategies_state,
    merge_custom_strategies_import,
    save_strategies_state,
)
import budget_terminal_app.strategies as strategies_module


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _ImmediateFuture:
    def __init__(self, fn: Any) -> None:
        try:
            self.value = fn()
            self.error = None
        except Exception as exc:
            self.value = None
            self.error = exc

    def result(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.value

    def add_done_callback(self, callback: Any) -> None:
        callback(self)


class _InlineExecutor:
    def submit(self, fn: Any) -> _ImmediateFuture:
        return _ImmediateFuture(fn)

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeStrategyService:
    def fetch(
        self,
        symbols: list[str],
        interval_key: Any,
        *,
        weighting: str = "equal",
        weights: dict[str, float] | None = None,
        shares: dict[str, float] | None = None,
        cash_balance: float = 0.0,
    ) -> dict[str, Any]:
        if weighting == "custom":
            resolved = dict(weights or {})
            mode = "custom"
            label = "Custom weights"
        elif weighting == "portfolio" and shares:
            prices = {"MSFT": 200.0, "META": 100.0, "CEG": 300.0, "COP": 100.0}
            values = {symbol: float(count) * prices.get(symbol, 100.0) for symbol, count in shares.items()}
            if cash_balance > 0.0:
                values["CASH"] = float(cash_balance)
            total = sum(values.values())
            resolved = {symbol: value / total * 100.0 for symbol, value in values.items()}
            mode = "portfolio"
            label = "Actual portfolio weights"
        else:
            resolved = {symbol: 100.0 / len(symbols) for symbol in symbols}
            mode = "equal" if weighting != "portfolio" else "equal_fallback"
            label = "Equal weight" if mode == "equal" else "Equal weight fallback"
        return {
            "values": [0.0, 1.0, 2.5],
            "return_pct": 2.5,
            "included_symbols": list(symbols),
            "missing_symbols": [],
            "source": "test",
            "interval_key": str(interval_key),
            "weights": resolved,
            "weighting": mode,
            "weighting_label": label,
        }


def test_equal_weight_math() -> None:
    index = pd.date_range("2026-01-02", periods=3, freq="D")
    payload = equal_weight_performance({
        "AAA": pd.Series([100.0, 105.0, 110.0], index=index),
        "BBB": pd.Series([100.0, 95.0, 90.0], index=index),
    })
    _assert(abs(payload["return_pct"]) < 0.0001, "opposite equal-weight returns should offset")
    _assert(payload["included_symbols"] == ["AAA", "BBB"], "both valid symbols should be included")

    custom = weighted_performance(
        {
            "AAA": pd.Series([100.0, 105.0, 110.0], index=index),
            "BBB": pd.Series([100.0, 95.0, 90.0], index=index),
        },
        weighting="custom",
        weights={"AAA": 80.0, "BBB": 20.0},
    )
    _assert(abs(custom["return_pct"] - 6.0) < 0.0001, "custom weights should drive weighted performance")
    _assert(custom["weights"] == {"AAA": 80.0, "BBB": 20.0}, "custom weights should remain normalized")

    actual = weighted_performance(
        {
            "AAA": pd.Series([100.0, 105.0, 110.0], index=index),
            "BBB": pd.Series([100.0, 95.0, 90.0], index=index),
        },
        weighting="portfolio",
        shares={"AAA": 2.0, "BBB": 1.0},
        cash_balance=100.0,
    )
    _assert(actual["weighting"] == "portfolio", "saved shares should select actual portfolio weighting")
    _assert(abs(sum(actual["weights"].values()) - 100.0) < 0.0001, "portfolio weights should normalize to 100%")
    _assert(actual["weights"]["AAA"] > actual["weights"]["BBB"], "market value should drive portfolio-card weights")
    _assert(actual["weights"]["CASH"] > 0.0, "brokerage cash should be included in actual portfolio weights")


def test_separate_strategy_persistence(temp_dir: Path) -> None:
    strategies_path = temp_dir / "strategies.json"
    export_path = temp_dir / "exported_cards.json"
    strategies_module.STRATEGIES_FILE = strategies_path
    card = create_custom_strategy(
        "Semis",
        "nvda, avgo nvda",
        weighting="custom",
        weights={"NVDA": 70.0, "AVGO": 30.0},
    )
    equal_card = create_custom_strategy("Quality", ["MSFT", "GOOGL"])
    state = save_strategies_state({
        "starter_cards_version": STARTER_CARDS_VERSION,
        "custom_cards": [card, equal_card],
        "card_order": [card["id"], equal_card["id"], BUILTIN_INDEX_CARD_ID],
        "hidden_portfolio_ids": ["portfolio_2"],
        "intervals": {card["id"]: "30d"},
    })
    _assert(strategies_path.exists(), "custom strategies should persist to their own JSON file")
    loaded = load_strategies_state()
    _assert(loaded["custom_cards"][0]["symbols"] == ["NVDA", "AVGO"], "symbols should normalize and de-duplicate")
    _assert(loaded["custom_cards"][0]["weights"] == {"NVDA": 70.0, "AVGO": 30.0}, "custom weights should persist")
    _assert(loaded["hidden_portfolio_ids"] == ["portfolio_2"], "portfolio-card visibility should persist")
    export_custom_strategies(export_path)
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    _assert(exported["weighting_modes"] == ["equal", "custom"], "custom-card export should declare supported weighting")
    _assert(len(exported["custom_cards"]) == 2, "custom-card export should omit built-in and portfolio cards")
    _assert(state["intervals"][card["id"]] == "30d", "selected card interval should persist")

    imported = load_custom_strategies_import(export_path)
    _assert(len(imported["custom_cards"]) == 2, "portable custom-card JSON should validate before merging")
    target_path = temp_dir / "merged_strategies.json"
    unrelated = create_custom_strategy("Existing", ["SPY"])
    save_strategies_state({
        "starter_cards_version": STARTER_CARDS_VERSION,
        "custom_cards": [{**card, "name": "Old Name"}, unrelated],
        "card_order": [BUILTIN_INDEX_CARD_ID, unrelated["id"], card["id"]],
    }, target_path)
    merged = merge_custom_strategies_import(imported, target_path)
    _assert(merged["updated_count"] == 1, "matching imported card IDs should update in place")
    _assert(merged["added_count"] == 1, "new imported card IDs should append")
    merged_by_id = {item["id"]: item for item in merged["state"]["custom_cards"]}
    _assert(merged_by_id[card["id"]]["name"] == "Semis", "import should replace fields on matching IDs")
    _assert(unrelated["id"] in merged_by_id, "import should preserve unrelated existing cards")

    cleared = clear_custom_strategies(target_path)
    _assert(cleared["custom_cards"] == [], "clearing cards should remove every custom card")
    _assert(cleared["card_order"] == [BUILTIN_INDEX_CARD_ID], "clearing cards should retain only the built-in index card")
    _assert(cleared["hidden_portfolio_ids"] == [], "clearing cards should restore portfolio-card visibility")
    _assert(cleared["intervals"] == {}, "clearing cards should remove saved card intervals")
    _assert(load_strategies_state(target_path) == cleared, "cleared card state should persist")


def _build_window(temp_dir: Path):
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.main import QApplication
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

    strategies_module.STRATEGIES_FILE = temp_dir / "page_strategies.json"
    app = QApplication.instance() or QApplication([])
    original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
    original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp()
        window.closeEvent = lambda event: event.accept()
        window.all_portfolios_state = {
            "main_portfolio_id": "portfolio_1",
            "active_portfolio_id": "portfolio_1",
            "portfolio_order": ["portfolio_1", "portfolio_2"],
            "portfolios": {
                "portfolio_1": {
                    "name": "Core",
                    "portfolio": ["MSFT", "META"],
                    "portfolio_tracker": {"MSFT": {"shares": 10}, "META": {"shares": 5}},
                    "cash_balance": 100.0,
                },
                "portfolio_2": {
                    "name": "Energy",
                    "portfolio": ["CEG", "COP"],
                    "portfolio_tracker": {
                        "CEG": {"shares": 20, "include_in_weight": False},
                        "COP": {"shares": 5},
                    },
                },
            },
        }
        window._ensure_page_initialized(28)
        window._p29_performance_service = _FakeStrategyService()
        window._p29_executor = _InlineExecutor()
        window._p29_refresh_cards(request_data=True)
        app.processEvents()
        window.switch_page(28)
        app.processEvents()
        app.processEvents()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
        WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
    return app, window


def test_strategies_page_smoke(temp_dir: Path) -> None:
    app, window = _build_window(temp_dir)
    try:
        _assert(window._PAGE_LABELS[28] == "Cards", "Cards page label should be registered")
        _assert(window.btn_page29.text() == "Cards", "Cards nav button should be registered")
        _assert(window._page_initialized(index=28), "Cards should initialize lazily")
        _assert(window._p29_visible_card_ids[:4] == [
            BUILTIN_INDEX_CARD_ID,
            *(card["id"] for card in STARTER_CUSTOM_CARDS),
        ], "Index and three starter templates should lead the page")
        _assert("portfolio:portfolio_1" in window._p29_visible_card_ids, "saved portfolios should be embedded")
        _assert("portfolio:portfolio_2" in window._p29_visible_card_ids, "all saved portfolios should receive cards")
        _assert(window._p29_models[BUILTIN_INDEX_CARD_ID]["symbols"] == ["SPY"], "Index should be 100% SPY")
        _assert(window._p29_models["portfolio:portfolio_2"]["symbols"] == ["COP"], "unchecked positions should stay out of portfolio weights")
        core_model = window._p29_models["portfolio:portfolio_1"]
        _assert(core_model["resolved_weights"]["MSFT"] > core_model["resolved_weights"]["META"], "portfolio cards should use market-value weights")
        _assert(core_model["resolved_weights"]["CASH"] > 0.0, "portfolio cards should include saved cash")
        positions = [window.p29_grid.layout.getItemPosition(index)[:2] for index in range(window.p29_grid.layout.count())]
        _assert(positions[:4] == [(0, 0), (0, 1), (0, 2), (0, 3)], "cards should fill a fixed four-column row")

        custom = create_custom_strategy(
            "AI Basket",
            ["NVDA", "AVGO", "ANET"],
            weighting="custom",
            weights={"NVDA": 50.0, "AVGO": 30.0, "ANET": 20.0},
        )
        window.strategies_state["custom_cards"].append(custom)
        window.strategies_state["card_order"].append(custom["id"])
        window._p29_save_state()
        window._p29_refresh_cards(request_data=True)
        app.processEvents()
        _assert(len(window._p29_visible_card_ids) == 7, "a custom card should join the built-in, starter, and portfolio cards")
        _assert(window.p29_grid.layout.getItemPosition(6)[:2] == (1, 2), "cards after the first four should continue on row two")
        _assert(window._p29_models[custom["id"]]["weights"]["NVDA"] == 50.0, "custom card weights should reach the page model")
        _assert("+2.50%" in window._p29_cards[custom["id"]].return_label.text(), "the area card should render performance")

        window._p29_select_interval(custom["id"], "30d")
        _assert(window.strategies_state["intervals"][custom["id"]] == "30d", "card interval selection should persist")
        window._p29_reorder_card(custom["id"], 0)
        _assert(window._p29_visible_card_ids[0] == custom["id"], "drag reorder callback should move and persist cards")
        window._p29_set_portfolio_card_visible("portfolio_2", False)
        _assert("portfolio:portfolio_2" not in window._p29_visible_card_ids, "portfolio cards should be hideable")
        window._p29_set_portfolio_card_visible("portfolio_2", True)
        _assert("portfolio:portfolio_2" in window._p29_visible_card_ids, "hidden portfolio cards should be restorable")

        settings_buttons = [button.text() for button in window.page9.findChildren(type(window.btn_page1))] if window._page_initialized(index=17) else []
        if not settings_buttons:
            window._ensure_page_initialized(17)
            settings_buttons = [button.text() for button in window.page9.findChildren(type(window.btn_page1))]
        _assert(
            "Export User Data, Cards and Paper Trading" in settings_buttons,
            "Settings should expose one combined backup-folder export",
        )
        _assert(
            "Import User Data, Cards and Paper Trading" in settings_buttons,
            "Settings should expose one combined backup-folder import",
        )
        for old_label in (
            "Export User Data",
            "Export Custom Cards",
            "Export Paper Trading",
            "Import User Data",
            "Import Custom Cards",
            "Import Paper Trading",
        ):
            _assert(old_label not in settings_buttons, f"Settings should remove {old_label!r}")
        _assert("Clear All User Data and Cards" in settings_buttons, "combined backups should not change clearing")
        _assert("Reset Cache" in settings_buttons, "combined backups should not change cache reset")
        _assert("Reset Paper Trading" in settings_buttons, "combined backups should not change Paper reset")

        window._refresh_main_tab_picker_items()
        picker_labels = [entry["label"] for entry in window._tab_picker_entries]
        _assert("Cards" in picker_labels, "Cards should be discoverable in page search")
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        test_equal_weight_math()
        test_separate_strategy_persistence(temp_dir)
        test_strategies_page_smoke(temp_dir)
    print("Cards page smoke passed.")
    sys.stdout.flush()
    os._exit(0)
