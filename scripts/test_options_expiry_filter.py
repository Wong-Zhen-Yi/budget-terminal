from __future__ import annotations

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from budget_terminal_app.services.options_data import OPTIONS_MARKET_TIMEZONE, OptionsMarketDataService


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


def test_cached_expiries_are_filtered() -> None:
    cache = FakeCache([_expiry(-3), _expiry(0), _expiry(14), _expiry(14)])
    runner = FakeTaskRunner([_expiry(30)])
    service = OptionsMarketDataService(cache_manager=cache, task_runner=runner)

    payload = service.fetch_expiries_payload("AAPL")

    _assert(payload["expiries"] == [_expiry(0), _expiry(14)], "cached expiries should keep same-day/future dates only")
    _assert(cache.saved == [_expiry(0), _expiry(14)], "filtered cache expiries should be saved back")
    _assert(runner.calls == 0, "live cached expiries should avoid network fetch")


def test_expired_only_cache_falls_through_to_fetch() -> None:
    cache = FakeCache([_expiry(-10), _expiry(-1)])
    runner = FakeTaskRunner([_expiry(-2), _expiry(7)])
    service = OptionsMarketDataService(cache_manager=cache, task_runner=runner)

    payload = service.fetch_expiries_payload("MSFT")

    _assert(payload["expiries"] == [_expiry(7)], "expired-only cache should be treated as a miss")
    _assert(cache.saved == [], "expired-only cache should not be re-saved as live expiries")
    _assert(runner.calls == 1, "expired-only cache should trigger a fresh fetch")


def main() -> None:
    test_cached_expiries_are_filtered()
    test_expired_only_cache_falls_through_to_fetch()
    print("options expiry filter smoke tests passed")


if __name__ == "__main__":
    main()
