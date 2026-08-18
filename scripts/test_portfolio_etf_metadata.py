from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.data import DataWorker
from budget_terminal_app.workers.market_metrics import MarketCapWorker


class _FakeFastInfo(dict):
    pass


class _FakeTicker:
    def __init__(self, quote_type: str, market_cap=None, target=None) -> None:
        self.fast_info = _FakeFastInfo(quoteType=quote_type, marketCap=market_cap)
        self._info = {"quoteType": quote_type, "marketCap": market_cap, "targetMeanPrice": target}
        self.info_reads = 0

    @property
    def info(self):
        self.info_reads += 1
        return dict(self._info)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_etf_target_skips_info() -> None:
    ticker = _FakeTicker("ETF")
    worker = DataWorker([], [])
    worker._stock_details_cache = {}
    worker._portfolio_news_cache = {}
    worker._details_cache_lock = __import__("threading").Lock()
    worker._ticker = lambda _symbol: ticker
    worker._fetch_portfolio_news_with_status = lambda _symbol: ([], None)
    payload = worker._fetch_stock_details("IAU", {"IAU": {"price": 77.0}})
    _assert(ticker.info_reads == 0, "ETF analyst metadata must not request Ticker.info")
    _assert(payload["targets"]["quote_type"] == "ETF", "ETF quote type should be carried to the UI")
    _assert(payload["targets"]["unavailable_reason"] == "not_applicable_for_etf", "ETF target should be marked not applicable")


def test_mixed_size_metadata_and_aum_cache() -> None:
    tickers = {
        "AAPL": _FakeTicker("EQUITY", market_cap=3_000_000_000_000),
        "IAU": _FakeTicker("ETF"),
    }
    MarketCapWorker._ETF_AUM_CACHE = {}
    MarketCapWorker._ETF_AUM_CACHE_AT = 0.0
    screen_calls = []

    def fake_screen(*_args, **_kwargs):
        screen_calls.append(1)
        return {"total": 1, "quotes": [{"symbol": "IAU", "netAssets": 42_500_000_000}]}

    with patch("budget_terminal_app.workers.market_metrics.yf.Ticker", side_effect=lambda symbol: tickers[symbol]), patch(
        "budget_terminal_app.workers.market_metrics.yf.screen", side_effect=fake_screen
    ):
        first = MarketCapWorker(["AAPL", "IAU"]).fetch()
        second = MarketCapWorker(["IAU"]).fetch()

    _assert(first["AAPL"]["size_type"] == "market_cap", "equity should retain market-cap metadata")
    _assert(first["IAU"] == {"symbol": "IAU", "quote_type": "ETF", "size_type": "aum", "size_value": 42_500_000_000}, "ETF should return typed AUM metadata")
    _assert(second["IAU"]["size_value"] == 42_500_000_000, "ETF AUM should be reused from cache")
    _assert(len(screen_calls) == 1, "fresh ETF AUM cache should prevent duplicate screener requests")
    _assert(tickers["IAU"].info_reads == 0, "ETF size metadata must not request Ticker.info")


def main() -> None:
    test_etf_target_skips_info()
    test_mixed_size_metadata_and_aum_cache()
    print("portfolio ETF metadata smoke tests passed")


if __name__ == "__main__":
    main()
