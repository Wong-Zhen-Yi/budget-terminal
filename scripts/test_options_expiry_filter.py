from __future__ import annotations

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from budget_terminal_app.data_service.results import MARKET_DATA_ERRORS_KEY, MARKET_DATA_META_KEY
from budget_terminal_app.data_service.tasks import MarketDataTaskRunner
from budget_terminal_app.dependencies import pd
from budget_terminal_app.services import options_data
from budget_terminal_app.services.options_data import OPTIONS_MARKET_TIMEZONE, OptionsMarketDataService, is_options_expiry_closed


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expiry(days: int) -> str:
    market_today = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()
    return (market_today + datetime.timedelta(days=days)).isoformat()


class FakeCache:
    def __init__(self, expiries: list[str]) -> None:
        self.expiries = list(expiries)
        self.saved: list[str] = []
        self.save_calls = 0

    def get_options_expiries(
        self,
        ticker: Any,
        max_age_hours: Any = 24,
        *,
        allow_stale: bool = False,
        return_metadata: bool = False,
    ) -> Any:
        payload = list(self.expiries)
        if return_metadata:
            return payload, {"cache_age_seconds": 12.0}
        return payload

    def save_options_expiries(self, ticker: Any, expiries: Any) -> None:
        self.saved = list(expiries or [])
        self.expiries = list(self.saved)
        self.save_calls += 1


class FakeTaskRunner:
    def __init__(self, expiries: list[str]) -> None:
        self.expiries = list(expiries)
        self.calls = 0

    def run(self, *_: Any, **__: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            data=list(self.expiries),
            meta={"source": "fake-yfinance", "freshness": "fresh"},
            errors=[],
        )


class FakeChainCache:
    def __init__(self) -> None:
        self.stale_chain = pd.DataFrame([{"strike": 100.0, "type": "Call"}])

    def get_options_chain(
        self,
        ticker: Any,
        expiry: Any,
        max_age_minutes: Any = 60,
        *,
        allow_stale: bool = False,
        return_metadata: bool = False,
    ) -> Any:
        if not allow_stale:
            return None
        if return_metadata:
            return self.stale_chain.copy(), {"cache_age_seconds": 7200.0}
        return self.stale_chain.copy()

    def save_options_chain(self, ticker: Any, expiry: Any, frame: Any) -> None:
        raise AssertionError("failed chain requests must not update the cache")


class FakeYahoo:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def Ticker(self, ticker: Any) -> Any:
        owner = self

        class FakeTicker:
            def option_chain(self, expiry: Any) -> Any:
                owner.calls += 1
                raise owner.error

        return FakeTicker()


def test_cached_expiries_are_filtered() -> None:
    cache = FakeCache([_expiry(-3), _expiry(14), _expiry(14)])
    runner = FakeTaskRunner([_expiry(30)])
    service = OptionsMarketDataService(cache_manager=cache, task_runner=runner)

    payload = service.fetch_expiries_payload("AAPL")

    _assert(payload["expiries"] == [_expiry(14)], "cached expiries should keep unique future dates only")
    _assert(cache.saved == [_expiry(14)], "closed and duplicate cache expiries should be removed when saved back")
    _assert(cache.save_calls >= 1, "cleaned cache expiries should be persisted")
    _assert(runner.calls == 0, "live cached expiries should avoid network fetch")


def test_expired_only_cache_falls_through_to_fetch() -> None:
    cache = FakeCache([_expiry(-10), _expiry(-1)])
    runner = FakeTaskRunner([_expiry(-2), _expiry(7)])
    service = OptionsMarketDataService(cache_manager=cache, task_runner=runner)

    payload = service.fetch_expiries_payload("MSFT")

    _assert(payload["expiries"] == [_expiry(7)], "expired-only cache should be treated as a miss")
    _assert(cache.saved == [], "expired-only cache should not be re-saved as live expiries")
    _assert(cache.save_calls == 1, "expired-only cache should be persisted as an empty list")
    _assert(runner.calls == 1, "expired-only cache should trigger a fresh fetch")


def test_same_day_expiry_closes_at_regular_market_close() -> None:
    expiry = "2026-06-18"
    before_close = datetime.datetime(2026, 6, 18, 15, 59, tzinfo=OPTIONS_MARKET_TIMEZONE)
    at_close = datetime.datetime(2026, 6, 18, 16, 0, tzinfo=OPTIONS_MARKET_TIMEZONE)

    _assert(not is_options_expiry_closed(expiry, now=before_close), "same-day expiry should remain live before 4 PM ET")
    _assert(is_options_expiry_closed(expiry, now=at_close), "same-day expiry should close at 4 PM ET")
    _assert(not is_options_expiry_closed("2026-06-19", now=at_close), "future expiry should remain live")
    _assert(not is_options_expiry_closed("not-a-date", now=at_close), "invalid dates should preserve existing handling")


def test_closed_expiry_does_not_request_yahoo() -> None:
    market_now = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE)
    closed_expiry = (market_now.date() - datetime.timedelta(days=1)).isoformat()
    fake_yahoo = FakeYahoo(RuntimeError("must not be called"))
    original_yf = options_data.yf
    options_data.yf = fake_yahoo
    try:
        service = OptionsMarketDataService(cache_manager=FakeChainCache())
        payload = service.fetch_chain_payload("AAPL", closed_expiry)
    finally:
        options_data.yf = original_yf

    _assert(fake_yahoo.calls == 0, "closed expiry should be rejected before Yahoo is called")
    _assert(payload["chain"].empty, "closed expiry should not return stale chain data")
    _assert(payload[MARKET_DATA_META_KEY]["freshness"] == "failed", "closed expiry should return failed metadata")


def _fetch_failed_chain(error: Exception) -> tuple[dict[str, Any], int]:
    fake_yahoo = FakeYahoo(error)
    original_yf = options_data.yf
    options_data.yf = fake_yahoo
    try:
        service = OptionsMarketDataService(
            cache_manager=FakeChainCache(),
            task_runner=MarketDataTaskRunner(default_timeout_seconds=0.0, default_retries=0),
        )
        payload = service.fetch_chain_payload("AAPL", _expiry(7))
    finally:
        options_data.yf = original_yf
    return payload, fake_yahoo.calls


def test_unlisted_expiry_does_not_use_stale_chain() -> None:
    error = ValueError("Expiration `2099-01-01` cannot be found. Available expirations are: [2099-01-08]")
    payload, calls = _fetch_failed_chain(error)

    _assert(calls == 1, "unlisted expiry should make one configured Yahoo attempt")
    _assert(payload["chain"].empty, "unlisted expiry should not return stale chain data")
    _assert(payload[MARKET_DATA_META_KEY]["freshness"] == "failed", "unlisted expiry should be marked failed")
    _assert("cannot be found" in payload[MARKET_DATA_META_KEY]["failure_reason"], "Yahoo rejection should be preserved")
    _assert(payload[MARKET_DATA_ERRORS_KEY], "Yahoo rejection should be retained as structured error metadata")


def test_transient_failure_can_use_stale_chain() -> None:
    payload, calls = _fetch_failed_chain(RuntimeError("temporary network failure"))

    _assert(calls == 1, "transient failure should make one configured Yahoo attempt")
    _assert(not payload["chain"].empty, "transient failure should preserve stale chain fallback")
    _assert(payload[MARKET_DATA_META_KEY]["freshness"] == "stale", "transient fallback should be marked stale")


def main() -> None:
    test_cached_expiries_are_filtered()
    test_expired_only_cache_falls_through_to_fetch()
    test_same_day_expiry_closes_at_regular_market_close()
    test_closed_expiry_does_not_request_yahoo()
    test_unlisted_expiry_does_not_use_stale_chain()
    test_transient_failure_can_use_stale_chain()
    print("options expiry filter smoke tests passed")


if __name__ == "__main__":
    main()
