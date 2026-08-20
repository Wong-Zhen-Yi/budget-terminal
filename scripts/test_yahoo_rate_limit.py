"""Smoke tests for the process-wide Yahoo Finance request pacer.

Drives ``services/yahoo_rate_limit`` on a virtual clock so the pacing assertions are exact and the
suite stays fast. No network access.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.services.yahoo_rate_limit import (
    MAX_PENALTY_LEVEL,
    MIN_REQUESTS_PER_SECOND,
    SUCCESSES_TO_RECOVER,
    YahooRateLimiter,
    get_limiter,
    pace_session,
    paced_request,
    set_limiter,
)


class _VirtualClock:
    """Monotonic clock advanced only by the limiter's own sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _limiter(clock: _VirtualClock, **kwargs: Any) -> YahooRateLimiter:
    params: dict[str, Any] = {
        'requests_per_second': 2.0,
        'burst': 3.0,
        'cooldown_seconds': 4.0,
        'clock': clock.time,
        'sleep': clock.sleep,
    }
    params.update(kwargs)
    return YahooRateLimiter(**params)


def test_burst_is_free_then_requests_are_paced() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)

    # burst=3 means exactly three back-to-back requests from an idle gate.
    assert [limiter.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]

    # The fourth must wait for the 0.5s interval implied by 2 requests/second.
    assert abs(limiter.acquire() - 0.5) < 1e-9
    assert abs(limiter.acquire() - 0.5) < 1e-9
    assert clock.sleeps == [0.5, 0.5]


def test_sustained_rate_matches_configuration() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock, burst=1.0)
    start = clock.now
    for _ in range(20):
        limiter.acquire()
    elapsed = clock.now - start
    # 20 requests at 2/s, with the first slot free, is 19 intervals of 0.5s.
    assert abs(elapsed - 9.5) < 1e-9


def test_rate_limit_halves_rate_and_blocks_every_waiter() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    assert limiter.effective_rate == 2.0

    cooldown = limiter.note_rate_limited()
    assert limiter.penalty_level == 1
    assert limiter.effective_rate == 1.0
    # Base cooldown plus up to 10% jitter.
    assert 4.0 <= cooldown <= 4.4

    # Even a gate that was idle (burst available) must wait out the cooldown.
    waited = limiter.acquire()
    assert waited >= 4.0 - (1.0 / limiter.effective_rate) * 2

    limiter.note_rate_limited()
    assert limiter.penalty_level == 2
    assert limiter.effective_rate == 0.5


def test_penalty_and_rate_are_bounded() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock, requests_per_second=0.2, cooldown_seconds=1.0, max_cooldown_seconds=30.0)
    for _ in range(MAX_PENALTY_LEVEL + 5):
        cooldown = limiter.note_rate_limited()
        assert cooldown <= 30.0 * 1.1
    assert limiter.penalty_level == MAX_PENALTY_LEVEL
    assert limiter.effective_rate >= MIN_REQUESTS_PER_SECOND


def test_clean_responses_recover_the_rate() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    limiter.note_rate_limited()
    assert limiter.penalty_level == 1

    for _ in range(SUCCESSES_TO_RECOVER - 1):
        limiter.note_success()
    assert limiter.penalty_level == 1, 'recovery must require a sustained clean run'

    limiter.note_success()
    assert limiter.penalty_level == 0
    assert limiter.effective_rate == 2.0

    # A 429 resets the streak, so recovery cannot be reached by alternating outcomes.
    limiter.note_rate_limited()
    for _ in range(SUCCESSES_TO_RECOVER - 1):
        limiter.note_success()
    limiter.note_rate_limited()
    for _ in range(SUCCESSES_TO_RECOVER - 1):
        limiter.note_success()
    assert limiter.penalty_level == 2


def test_note_status_ignores_non_numeric_and_server_errors() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    limiter.note_status(None)
    limiter.note_status('not-a-status')
    assert limiter.penalty_level == 0
    assert limiter.total_rate_limited == 0

    limiter.note_rate_limited()
    # A 500 is not a throttle signal, so it must not count toward recovery either.
    for _ in range(SUCCESSES_TO_RECOVER):
        limiter.note_status(500)
    assert limiter.penalty_level == 1

    for _ in range(SUCCESSES_TO_RECOVER):
        limiter.note_status(200)
    assert limiter.penalty_level == 0


def test_paced_request_retries_429_then_returns_success() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    statuses = [429, 200]
    calls: list[int] = []

    def call() -> _Response:
        status = statuses[len(calls)]
        calls.append(status)
        return _Response(status)

    response = paced_request(limiter, call, sleep=clock.sleep)
    assert response.status_code == 200
    assert calls == [429, 200]
    assert limiter.total_rate_limited == 1


def test_paced_request_gives_up_and_returns_the_429() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    attempts = 0

    def call() -> _Response:
        nonlocal attempts
        attempts += 1
        return _Response(429)

    response = paced_request(limiter, call, sleep=clock.sleep)
    # Surfacing the 429 keeps yfinance's own YFRateLimitError handling intact.
    assert response.status_code == 429
    assert attempts == 2, 'one paced retry on top of the initial attempt'


def test_concurrency_is_capped() -> None:
    limiter = YahooRateLimiter(requests_per_second=1000.0, burst=1000.0, max_concurrency=3)
    lock = threading.Lock()
    in_flight = 0
    peak = 0

    def worker() -> None:
        nonlocal in_flight, peak
        limiter.acquire()
        with limiter.concurrency_slot():
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak <= 3, f'concurrency cap breached: {peak}'
    assert limiter.total_requests == 12


def test_reservations_are_thread_safe_and_do_not_stampede() -> None:
    clock = _VirtualClock()
    guard = threading.Lock()

    def locked_sleep(seconds: float) -> None:
        with guard:
            clock.sleep(seconds)

    limiter = YahooRateLimiter(
        requests_per_second=100.0,
        burst=1.0,
        clock=clock.time,
        sleep=locked_sleep,
    )
    waits: list[float] = []

    def worker() -> None:
        wait = limiter.acquire()
        with guard:
            waits.append(wait)

    threads = [threading.Thread(target=worker) for _ in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert limiter.total_requests == 25
    assert len(waits) == 25
    # Each caller reserves a distinct slot, so at most one gets a free pass.
    assert sum(1 for wait in waits if wait == 0.0) <= 1


def test_pace_session_routes_every_verb_through_the_limiter() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    set_limiter(limiter)
    try:
        session = _FakeSession()
        assert pace_session(session) is session
        session.get('https://query2.finance.yahoo.com/v1/test')
        session.post('https://query2.finance.yahoo.com/v1/test')
        assert limiter.total_requests == 2
        assert session.methods == ['GET', 'POST']

        # Idempotent: a second pass must not stack another wrapper.
        pace_session(session)
        session.get('https://query2.finance.yahoo.com/v1/test')
        assert limiter.total_requests == 3
    finally:
        set_limiter(None)


def test_pace_session_feeds_429_back_into_the_limiter() -> None:
    clock = _VirtualClock()
    limiter = _limiter(clock)
    session = _FakeSession(statuses=[429, 200])
    pace_session(session, limiter)
    response = session.get('https://query2.finance.yahoo.com/v1/test')
    assert response.status_code == 200
    assert limiter.penalty_level == 1


def test_shared_limiter_is_a_singleton() -> None:
    set_limiter(None)
    try:
        first = get_limiter()
        assert get_limiter() is first
    finally:
        set_limiter(None)


class _FakeSession:
    """Stands in for a curl_cffi/requests Session: every verb dispatches through ``request``."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self._statuses = list(statuses or [])
        self.methods: list[str] = []

    def request(self, method: str, url: str, **_kwargs: Any) -> _Response:
        self.methods.append(method)
        status = self._statuses.pop(0) if self._statuses else 200
        return _Response(status)

    def get(self, url: str, **kwargs: Any) -> _Response:
        return self.request(method='GET', url=url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _Response:
        return self.request(method='POST', url=url, **kwargs)


def test_installed_session_is_the_one_yfinance_uses() -> None:
    """The gate is only real if yfinance's singleton actually holds the paced session."""
    from budget_terminal_app.services.yahoo_rate_limit import install_yahoo_rate_limit

    try:
        from yfinance import _http
        from yfinance.data import YfData
    except Exception as exc:  # pragma: no cover - yfinance is a hard dependency in CI
        raise AssertionError(f'yfinance must be importable: {exc}') from exc

    assert install_yahoo_rate_limit(force=True), 'installation should succeed'
    session = getattr(YfData(), '_session', None)
    assert session is not None
    assert getattr(session, '_budget_terminal_paced', False), 'YfData session is not paced'
    # yfinance validates the session it is handed; the patch must not break that contract.
    assert _http.is_supported_session(session)


def test_lazy_proxy_installs_the_pacer_on_first_yfinance_use() -> None:
    """Touching the shared proxy must arm the gate before any call site can issue a request."""
    from budget_terminal_app import dependencies
    from budget_terminal_app.services import yahoo_rate_limit

    assert dependencies.yf.__version__
    assert yahoo_rate_limit.is_installed()


if __name__ == '__main__':
    test_burst_is_free_then_requests_are_paced()
    test_sustained_rate_matches_configuration()
    test_rate_limit_halves_rate_and_blocks_every_waiter()
    test_penalty_and_rate_are_bounded()
    test_clean_responses_recover_the_rate()
    test_note_status_ignores_non_numeric_and_server_errors()
    test_paced_request_retries_429_then_returns_success()
    test_paced_request_gives_up_and_returns_the_429()
    test_concurrency_is_capped()
    test_reservations_are_thread_safe_and_do_not_stampede()
    test_pace_session_routes_every_verb_through_the_limiter()
    test_pace_session_feeds_429_back_into_the_limiter()
    test_shared_limiter_is_a_singleton()
    test_installed_session_is_the_one_yfinance_uses()
    test_lazy_proxy_installs_the_pacer_on_first_yfinance_use()
    print('yahoo rate limit smoke tests passed')
