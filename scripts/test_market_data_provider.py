from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from budget_terminal_app.services.market_data_provider import (
    FreeTierRateLimiter,
    MassiveMarketDataProvider,
    resolve_massive_api_key,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None) -> FakeResponse:
        self.calls.append((url, dict(params or {})))
        for marker, response in self.responses.items():
            if marker in url:
                return response
        return FakeResponse({"message": "not found"}, status_code=404)


class FakeTicker:
    def __init__(self, symbol: str, frame: pd.DataFrame) -> None:
        self.symbol = symbol
        self._frame = frame

    def history(self, *args, **kwargs) -> pd.DataFrame:
        return self._frame.copy()


class FakeYF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.download_calls: list[dict] = []

    def download(self, symbols, **kwargs) -> pd.DataFrame:
        self.download_calls.append({"symbols": symbols, **kwargs})
        return self.frame.copy()

    def Ticker(self, symbol: str) -> FakeTicker:
        return FakeTicker(symbol, self.frame)


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [99.0, 100.0],
            "High": [101.0, 103.0],
            "Low": [98.0, 99.0],
            "Close": [100.0, 102.0],
            "Volume": [1000, 1200],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
    )


def _provider(session: FakeSession, *, yf_module: FakeYF | None = None, rate_limiter: FreeTierRateLimiter | None = None, cache_dir: Path | None = None) -> MassiveMarketDataProvider:
    return MassiveMarketDataProvider(
        settings={"enabled": True, "mode": "massive_free_safe"},
        api_key="test-key",
        api_key_source="settings",
        session=session,
        yf_module=yf_module or FakeYF(_sample_frame()),
        rate_limiter=rate_limiter or FreeTierRateLimiter(max_requests=100, window_seconds=60),
        cache_dir=cache_dir,
    )


def test_key_resolution_order() -> None:
    key, source = resolve_massive_api_key(secret_key="saved", env={"MASSIVE_API_KEY": "env"})
    _assert((key, source) == ("saved", "settings"), "saved key should win over environment")
    key, source = resolve_massive_api_key(secret_key="", env={"POLYGON_API_KEY": "polygon"})
    _assert((key, source) == ("polygon", "env"), "POLYGON_API_KEY should be accepted")
    key, source = resolve_massive_api_key(secret_key="", env={})
    _assert((key, source) == ("", "missing"), "missing keys should be reported")


def test_ohlcv_free_tier_gate_uses_yfinance_for_long_history() -> None:
    session = FakeSession({})
    fake_yf = FakeYF(_sample_frame())
    result = _provider(session, yf_module=fake_yf).get_ohlcv("AAPL", period="3y", interval="1d")
    _assert(result.source == "yfinance fallback", "3y daily data should fall back to yfinance on free tier")
    _assert(len(session.calls) == 0, "Massive should not be called for history beyond 2 years")
    _assert(len(fake_yf.download_calls) == 1, "yfinance fallback should be used")


def test_massive_ohlcv_normalizes_aggs() -> None:
    session = FakeSession(
        {
            "/v2/aggs/ticker/AAPL/range/1/day": FakeResponse(
                {
                    "results": [
                        {"t": 1767312000000, "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 12345},
                        {"t": 1767398400000, "o": 104.0, "h": 106.0, "l": 101.0, "c": 102.0, "v": 23456},
                    ]
                }
            )
        }
    )
    result = _provider(session).get_ohlcv("AAPL", period="1mo", interval="1d")
    _assert(result.source == "Massive EOD", "eligible daily bars should use Massive")
    _assert(list(result.data.columns) == ["Open", "High", "Low", "Close", "Volume"], "Massive bars should normalize to OHLCV")
    _assert(float(result.data["Close"].iloc[-1]) == 102.0, "latest close should be preserved")


def test_massive_403_falls_back_with_structured_error() -> None:
    session = FakeSession({"/v2/aggs/ticker/AAPL/range/1/day": FakeResponse({"message": "denied"}, status_code=403)})
    result = _provider(session).get_ohlcv("AAPL", period="1mo", interval="1d")
    _assert(result.source == "yfinance fallback", "403 should fall back to yfinance")
    _assert(not result.data.empty, "fallback frame should be returned")
    _assert(result.errors and result.errors[0]["source"] == "Massive EOD", "fallback should include Massive error metadata")


def test_grouped_daily_cache_reuses_massive_summary() -> None:
    latest_rows = {"results": [{"T": "AAPL", "c": 102.0}]}
    with tempfile.TemporaryDirectory() as temp_dir:
        session_one = FakeSession(
            {
                "/v2/aggs/grouped/locale/us/market/stocks/": FakeResponse(latest_rows),
            }
        )
        provider_one = _provider(session_one, cache_dir=Path(temp_dir))
        result_one = provider_one.get_stock_prices(["AAPL"])
        _assert(result_one.data["AAPL"]["price"] == 102.0, "first grouped summary should produce a price")
        _assert(len(session_one.calls) == 2, "first grouped summary should fetch latest and previous sessions")

        session_two = FakeSession({})
        provider_two = _provider(session_two, cache_dir=Path(temp_dir))
        result_two = provider_two.get_stock_prices(["AAPL"])
        _assert(result_two.data["AAPL"]["price"] == 102.0, "cached grouped summary should produce a price")
        _assert(len(session_two.calls) == 0, "second grouped summary should be served from cache")


def test_rate_limit_falls_back() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        session = FakeSession({"/v2/aggs/grouped/locale/us/market/stocks/": FakeResponse({"results": [{"T": "AAPL", "c": 102.0}]})})
        limiter = FreeTierRateLimiter(max_requests=1, window_seconds=60)
        result = _provider(session, rate_limiter=limiter, cache_dir=Path(temp_dir)).get_stock_prices(["AAPL"])
        _assert(result.source == "yfinance fallback", "local free-tier limiter should force fallback when quota is exhausted")
        _assert(result.errors and result.errors[0]["retryable"], "rate-limit fallback should be retryable")


def test_company_news_and_ipo_normalization() -> None:
    session = FakeSession(
        {
            "/v3/reference/tickers/AAPL": FakeResponse(
                {
                    "results": {
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "primary_exchange": "XNAS",
                        "currency_name": "usd",
                        "market_cap": 3000,
                        "description": "Consumer technology company.",
                    }
                }
            ),
            "/v2/reference/news": FakeResponse(
                {
                    "results": [
                        {
                            "title": "Apple news",
                            "article_url": "https://example.com/aapl",
                            "publisher": {"name": "Example"},
                            "published_utc": "2026-01-02T12:00:00Z",
                            "tickers": ["AAPL"],
                        }
                    ]
                }
            ),
            "/vX/reference/ipos": FakeResponse(
                {
                    "results": [
                        {
                            "listing_date": "2026-02-03",
                            "ticker": "TEST",
                            "issuer_name": "Test Co",
                            "expected_price_low": 10,
                            "expected_price_high": 12,
                        }
                    ]
                }
            ),
        }
    )
    provider = _provider(session)
    overview = provider.get_company_overview("AAPL")
    _assert(overview.data["longName"] == "Apple Inc.", "reference endpoint should map company name")
    news = provider.get_stock_news("AAPL")
    _assert(news.data[0]["source"] == "Example", "news publisher should be normalized")
    ipos = provider.get_ipos("2026-02-01", "2026-02-28")
    _assert(ipos.data[0]["symbol"] == "TEST", "IPO ticker should be normalized")


def main() -> None:
    tests = [
        test_key_resolution_order,
        test_ohlcv_free_tier_gate_uses_yfinance_for_long_history,
        test_massive_ohlcv_normalizes_aggs,
        test_massive_403_falls_back_with_structured_error,
        test_grouped_daily_cache_reuses_massive_summary,
        test_rate_limit_falls_back,
        test_company_news_and_ipo_normalization,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
