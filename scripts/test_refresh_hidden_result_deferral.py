"""Smoke-test hidden result deferral on additional refresh-heavy pages."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.backtest_page import BacktestPageMixin
from budget_terminal_app.mixins.crypto import CryptoMixin
from budget_terminal_app.mixins.fundamentals_setup import FundamentalsSetupMixin
from budget_terminal_app.mixins.global_page import GlobalPageMixin
from budget_terminal_app.mixins.ipo_page import IpoPageMixin
from budget_terminal_app.mixins.news import NewsMixin
from budget_terminal_app.mixins.politics import PoliticsMixin
from budget_terminal_app.mixins.pre_market import PreMarketMixin
from budget_terminal_app.mixins.random_recommender import RandomRecommenderMixin
from budget_terminal_app.mixins.sectors import SectorsMixin
from budget_terminal_app.mixins.spy_heatmap import SpyHeatmapMixin
from budget_terminal_app.mixins.stocks_page import StocksPageMixin
from budget_terminal_app.mixins.strategies_page import StrategiesPageMixin
from budget_terminal_app.mixins.valuation import ValuationMixin


class _Button:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _VisibilityProbe:
    def __init__(self) -> None:
        self.visible = False
        self.render_count = 0

    def _is_current_page(self, _page) -> bool:
        return self.visible


class _StocksProbe(_VisibilityProbe, StocksPageMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page12 = object()
        self._stocks_active_request = 1
        self._stocks_request_contexts = {1: {"include_global_status": True, "update_collection_info": True}}
        self._stocks_loaded_once = True
        self.stocks_load_btn = _Button()

    def _stocks_apply_payload_to_ui(self, *_args, **_kwargs) -> None:
        self.render_count += 1


class _FundamentalsProbe(_VisibilityProbe, FundamentalsSetupMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page2 = object()
        self._p2_active_request_id = 1
        self._p2_request_contexts = {1: {"update_collection_info": True}}
        self.p2_analyze_btn = _Button()

    def update_page2(self, *_args, **_kwargs) -> None:
        self.render_count += 1

    def _p2_relayout_charts(self) -> None:
        return None


class _ValuationProbe(_VisibilityProbe, ValuationMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page23 = object()
        self._valuation_active_request_id = 1
        self._valuation_request_contexts = {1: {"update_collection_info": True}}
        self.valuation_load_btn = _Button()
        self.valuation_current_data = None
        self.valuation_thread = object()

    def update_valuation_page(self, *_args, **_kwargs) -> None:
        self.render_count += 1


class _SectorsProbe(_VisibilityProbe, SectorsMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page8 = object()
        self._p8_all_results = {}
        self.p8_fetch_in_progress = True

    def _p8_apply_mktcap_cache_updates(self, _updates) -> None:
        return None

    def _p8_apply_all_data(self, _results) -> None:
        self.render_count += 1

    def _p8_relayout_cards(self) -> None:
        return None

    def _p8_request_refresh(self, **_kwargs) -> bool:
        return False


class _HeatmapProbe(_VisibilityProbe, SpyHeatmapMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page17 = object()
        self._p17_etf_symbol = "SPY"
        self._p17_results = {}
        self._p17_last_fetch_by_etf = {}
        self._p17_fetching_symbols = {"SPY"}
        self._p17_fetch_futures = {}

    def _p17_render_interval_result(self, **_kwargs) -> None:
        self._p17_render_pending = False
        self.render_count += 1

    def _p17_update_refresh_state(self) -> None:
        return None

    def _p17_request_all_etfs(self, **_kwargs):
        if self._p17_results.get(self._p17_etf_symbol) is not None:
            self._p17_render_interval_result(reset_view=False)
        return ()


class _PreMarketProbe(_VisibilityProbe, PreMarketMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page14 = object()
        self._p14_loaded_once = True
        self._p14_last_refresh_ts = time.time()
        self._p14_pending_result = None

    def _p14_apply_result(self, _result) -> None:
        self.render_count += 1

    def _p14_refresh(self, *_args, **_kwargs) -> bool:
        raise AssertionError("a cached show must not refetch")


class _CryptoProbe(_VisibilityProbe, CryptoMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page19 = object()
        self._p19_last_payload = {}
        self._p19_progress = {}
        self._p19_render_pending = False
        self._p19_thread = None

    def _p19_apply_payload(self, *_args, **_kwargs) -> None:
        self.render_count += 1


class _PoliticsProbe(_VisibilityProbe, PoliticsMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page15 = object()
        self._p15_current_page = 1
        self._p15_all_trades = []
        self._p15_current_raw_count = 0
        self._p15_current_fetched_at = None
        self._p15_render_pending = False
        self._p15_pending_restored = False
        self._p15_loaded_once = True
        self._p15_thread = None

    def _p15_render_current_result(self, **_kwargs) -> None:
        self.render_count += 1


class _IpoProbe(_VisibilityProbe, IpoPageMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page21 = object()
        self._p21_ipo_rows = []
        self._p21_completed_rows = []
        self._p21_ipo_pending_payload = None
        self._p21_completed_pending_payload = None
        self._p21_ipo_render_pending = False
        self._p21_completed_render_pending = False


class _GlobalProbe(_VisibilityProbe, GlobalPageMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page26 = object()
        self._p26_active_request = 1
        self._p26_fetching = True
        self._p26_payload = {}
        self._p26_render_pending = False
        self._p26_pending_error = ""
        self.p26_refresh_btn = _Button()

    def _p26_render_payload(self) -> None:
        self.render_count += 1

    def _p26_update_payload_status(self) -> None:
        return None

    def _p26_sync_status_bar(self) -> None:
        return None

    def _p26_rows(self):
        return list(self._p26_payload.get("rows", []))


class _BacktestProbe(_VisibilityProbe, BacktestPageMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page25 = object()
        self._p25_active_request = 1
        self._p25_fetching = True
        self.signature = (("AAA", 100.0),)
        self._p25_active_signature = self.signature
        self._p25_queued_signature = None
        self._p25_result_cache = {}
        self._p25_pending_result = None
        self._p25_pending_error = ""
        self.p25_interval_label = "1D"
        self.p25_run_btn = _Button()

    def _p25_render_result(self, *_args, **_kwargs) -> None:
        self.render_count += 1

    def _p25_input_signature(self):
        return self.signature

    def _p25_update_result_status(self, _result) -> None:
        return None

    def _p25_update_weight_total(self) -> None:
        return None

    def _p25_update_button_styles(self) -> None:
        return None

    def _p25_sync_status_bar(self) -> None:
        return None


class _CardsProbe(_VisibilityProbe, StrategiesPageMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page29 = object()
        self._p29_active_requests = {"card": 1}
        self._p29_cards = {
            "card": SimpleNamespace(
                set_error=lambda _message: None,
                set_loading=lambda: None,
                set_performance=lambda _payload: None,
            )
        }
        self._p29_models = {"card": {"symbols": ["AAA"], "weighting": "equal"}}
        self._p29_performance_cache = {}
        self._p29_inflight_signatures = {}
        self._p29_queued_signatures = {}
        self._p29_render_pending = False
        self._p29_visible_card_ids = ["card"]
        self.strategies_state = {"intervals": {"card": "1y"}}

    def _p29_refresh_cards(self, **_kwargs) -> None:
        self.render_count += 1

    def _p29_set_status(self, *_args, **_kwargs) -> None:
        return None


class _NewsProbe(_VisibilityProbe, NewsMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page34 = object()
        self.p34_portfolio_grid = object()
        self._p34_loaded_news = {"portfolio": [], "macro": [], "other": []}
        self._p34_render_pending = False
        self._p34_pending_preview = None
        self._p34_pending_status = None


class _NewsSingleFlightProbe(NewsMixin):
    def __init__(self) -> None:
        self.tickers = ["AAA"]
        self._p34_news_refresh_pending = False
        self._p34_news_refresh_signature = ()
        self._p34_news_refresh_queued_tickers = None
        self.starts: list[list[str]] = []

    def _p34_fetch_tickers(self) -> list[str]:
        return list(self.tickers)

    def _p34_start_news_refresh(self, tickers: list[str]) -> None:
        self.starts.append(list(tickers))
        self._p34_news_refresh_pending = True
        self._p34_news_refresh_signature = tuple(tickers)


class _RollProbe(_VisibilityProbe, RandomRecommenderMixin):
    def __init__(self) -> None:
        super().__init__()
        self.page18 = object()
        self._p18_active_request = 1
        self._p18_pending_payload = {}
        self._p18_loaded_payload = None
        self._p18_payload_request_id = 0
        self._p18_render_pending = False
        self._p18_pending_complete = False
        self._p18_pending_status = None
        self.statuses: list[tuple[str, str, bool]] = []

    def _p18_apply_payload(self, _payload, **_kwargs) -> None:
        self.render_count += 1

    def _p18_set_busy(self, *_args, **_kwargs) -> None:
        return None

    def _p18_set_status(self, text, status="muted", *, include_global=True) -> None:
        self.statuses.append((str(text), str(status), bool(include_global)))


def _assert_hidden_then_visible_once(probe, complete, show) -> None:
    complete()
    assert probe.render_count == 0
    probe.visible = True
    show()
    assert probe.render_count == 1
    show()
    assert probe.render_count == 1


def test_refresh_heavy_pages_defer_hidden_results() -> None:
    stocks = _StocksProbe()
    _assert_hidden_then_visible_once(
        stocks,
        lambda: stocks._stocks_apply_payload(1, {"symbol": "AAPL"}),
        stocks._stocks_on_show,
    )

    fundamentals = _FundamentalsProbe()
    _assert_hidden_then_visible_once(
        fundamentals,
        lambda: fundamentals._p2_handle_result(1, {"ticker": "AAPL"}),
        fundamentals._p2_on_show,
    )

    valuation = _ValuationProbe()
    _assert_hidden_then_visible_once(
        valuation,
        lambda: valuation._valuation_handle_result(1, {"ticker": "AAPL"}),
        valuation._valuation_on_show,
    )

    sectors = _SectorsProbe()
    _assert_hidden_then_visible_once(
        sectors,
        lambda: sectors._p8_complete_refresh({"AAPL": object()}),
        sectors._p8_on_show,
    )

    heatmap = _HeatmapProbe()
    heatmap._p17_apply_result(SimpleNamespace(ticker="SPY"), "SPY")
    assert heatmap.render_count == 0
    heatmap.visible = True
    heatmap._p17_on_show()
    assert heatmap.render_count == 1


def test_secondary_refresh_pages_defer_hidden_results() -> None:
    pre_market = _PreMarketProbe()
    _assert_hidden_then_visible_once(
        pre_market,
        lambda: pre_market._p14_on_data({"futures": []}),
        pre_market._p14_on_show,
    )

    crypto = _CryptoProbe()
    _assert_hidden_then_visible_once(
        crypto,
        lambda: crypto._p19_on_partial_data({"quotes": [{"symbol": "BTC"}]}),
        crypto._p19_on_show,
    )

    politics = _PoliticsProbe()
    _assert_hidden_then_visible_once(
        politics,
        lambda: politics._p15_apply_result({"page": 1, "trades": [{"ticker": "AAA"}]}),
        politics._p15_on_show,
    )

    ipo = _IpoProbe()
    ipo._p21_apply_ipo_payload({"rows": [{"symbol": "AAA"}]}, restored=False)
    assert ipo.render_count == 0
    assert ipo._p21_ipo_pending_payload is not None
    ipo._p21_apply_ipo_payload = lambda *_args, **_kwargs: setattr(ipo, "render_count", ipo.render_count + 1)
    ipo.visible = True
    ipo._p21_on_show()
    assert ipo.render_count == 1
    ipo._p21_on_show()
    assert ipo.render_count == 1

    global_page = _GlobalProbe()
    _assert_hidden_then_visible_once(
        global_page,
        lambda: global_page._p26_apply_result(1, {"rows": [{"symbol": "AAA"}]}),
        global_page._p26_on_show,
    )

    backtest = _BacktestProbe()
    _assert_hidden_then_visible_once(
        backtest,
        lambda: backtest._p25_apply_result(1, {"stats": {}}, interval_label="1D"),
        backtest._p25_on_show,
    )
    backtest = _BacktestProbe()
    backtest._p25_queued_signature = (("OLD", 100.0),)
    backtest._p25_run_backtest()
    assert backtest._p25_queued_signature is None
    backtest.signature = (("BBB", 100.0),)
    backtest._p25_run_backtest()
    assert backtest._p25_queued_signature == backtest.signature

    cards = _CardsProbe()
    cards_key = cards._p29_cache_key(cards._p29_models["card"], "1y")
    cards._p29_inflight_signatures["card"] = cards_key
    cards._p29_apply_performance("card", 1, cards_key, {"weights": {"AAA": 100.0}}, None)
    assert cards.render_count == 0
    assert cards._p29_render_pending
    assert cards_key in cards._p29_performance_cache
    cards.visible = True
    cards._p29_on_show()
    assert cards.render_count == 1

    news = _NewsProbe()
    news.update_page34({"news": [{"category": "portfolio", "title": "Example"}]})
    assert news._p34_render_pending
    news._p34_refresh_cards = lambda *_args: setattr(news, "render_count", news.render_count + 1)
    news.visible = True
    news._p34_on_show()
    assert news.render_count == 1

    cards = _CardsProbe()
    cards_key = cards._p29_cache_key(cards._p29_models["card"], "1y")
    cards._p29_inflight_signatures["card"] = cards_key
    cards._p29_request_card("card", force=True)
    assert cards._p29_queued_signatures == {}
    cards.strategies_state["intervals"]["card"] = "30d"
    cards._p29_request_card("card", force=True)
    assert cards._p29_queued_signatures["card"] != cards_key
    news._p34_on_show()
    assert news.render_count == 1

    roll = _RollProbe()
    roll._p18_handle_partial(
        1,
        {"section": "candidates", "payload": {"candidate_pool": [{"symbol": "AAA"}]}},
    )
    assert roll.render_count == 0
    assert roll._p18_render_pending
    roll.visible = True
    roll._p18_on_show()
    assert roll.render_count == 1
    roll._p18_on_show()
    assert roll.render_count == 1

    roll = _RollProbe()
    roll._p18_handle_result(1, {"symbol": "AAA", "candidate_pool": []})
    assert roll.render_count == 0
    assert roll.statuses == []
    roll.visible = True
    roll._p18_on_show()
    assert roll.render_count == 1
    assert roll.statuses[-1][1] == "positive"


def test_news_refresh_is_single_flight_with_one_changed_input_rerun() -> None:
    probe = _NewsSingleFlightProbe()
    assert probe._p34_request_news_refresh()
    assert not probe._p34_request_news_refresh()
    assert probe._p34_news_refresh_queued_tickers is None
    probe.tickers = ["BBB"]
    assert not probe._p34_request_news_refresh()
    probe.tickers = ["CCC"]
    assert not probe._p34_request_news_refresh()
    assert probe.starts == [["AAA"]]
    assert probe._p34_news_refresh_queued_tickers == ["CCC"]
    assert probe._p34_start_queued_news_refresh()
    assert probe.starts == [["AAA"], ["CCC"]]


if __name__ == "__main__":
    test_refresh_heavy_pages_defer_hidden_results()
    test_secondary_refresh_pages_defer_hidden_results()
    test_news_refresh_is_single_flight_with_one_changed_input_rerun()
    print("Additional hidden-result refresh smokes passed.")
