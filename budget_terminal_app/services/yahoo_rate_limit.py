"""Process-wide pacing for every Yahoo Finance request the app makes.

yfinance 1.5.2 ships ``network.retries = 0`` and no pacing of its own: it issues a request the
moment it is asked to and raises :class:`yfinance.exceptions.YFRateLimitError` once Yahoo answers
429. Worse, its ``_make_request`` retries any 4xx once with the other cookie strategy, so a
throttled burst costs two requests per call before the error surfaces.

``YF_LOCK`` in ``dependencies`` cannot solve this. It is a mutex, so it bounds *concurrency* but not
*rate* -- serialized calls still fire back to back as fast as Yahoo will answer -- and roughly half
the app's yfinance call sites never take it. ``yf.download(..., threads=True)`` also fans out onto
yfinance's own worker threads *inside* one lock holder, so the lock never sees those requests.

So the gate lives below all of that, on the HTTP session itself. yfinance supports a caller-supplied
session (``YfData(session=...)``, validated by ``_http.is_supported_session``), and every verb on
both supported backends routes through ``Session.request``. Overriding that one method paces every
Yahoo request in the process regardless of which call site, thread, or yfinance internal issued it.

Two mechanisms, because Yahoo's real limits are undocumented and vary:

* A GCRA virtual-scheduling gate smooths bursts to a sustained rate while still allowing a short
  burst. Each caller reserves its slot under the lock and sleeps a distinct duration, so waiters do
  not stampede when the gate opens.
* An AIMD controller adapts to reality. Any 429 halves the effective rate and starts an exponential
  cooldown; a run of clean responses restores it. Whatever Yahoo's true ceiling is, the app settles
  below it instead of having to guess right up front.

This module is deliberately Qt-free so the smoke tests can drive it directly.
"""
from __future__ import annotations

import os
import random
import threading
import time
from typing import Any, Callable

#: Sustained request rate once the burst allowance is spent.
DEFAULT_REQUESTS_PER_SECOND = 2.0
#: Requests allowed to go out back-to-back before pacing bites, so a single page stays responsive.
DEFAULT_BURST = 8.0
#: Ceiling on requests in flight at once. yfinance's own download threads fan out past this
#: otherwise, which is what turns a batch download into a 429.
DEFAULT_MAX_CONCURRENCY = 4
#: First cooldown after a 429; doubles per consecutive penalty up to the maximum.
DEFAULT_COOLDOWN_SECONDS = 5.0
DEFAULT_MAX_COOLDOWN_SECONDS = 300.0
#: The adaptive rate never drops below this, or the app would appear hung.
MIN_REQUESTS_PER_SECOND = 0.1
#: Penalty halvings retained; 4 means the rate can fall to a sixteenth of the configured value.
MAX_PENALTY_LEVEL = 4
#: Clean responses required at one penalty level before easing back up.
SUCCESSES_TO_RECOVER = 20
#: Retries for a 429, on top of the cooldown the penalty installs. Deliberately one: yfinance's
#: ``_make_request`` already reissues any 4xx once with the other cookie strategy, and that second
#: call comes back through this gate, so each extra attempt here doubles against that. One paced
#: retry is still worth it -- it rides out a transient throttle and avoids triggering the app's own
#: per-ticker fallback paths, which cost far more requests than the retry does.
RETRY_ATTEMPTS = 1

RATE_LIMIT_STATUS = 429


def _env_float(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _env_int(name: str, fallback: int) -> int:
    return max(1, int(_env_float(name, float(fallback))))


class YahooRateLimiter:
    """Thread-safe request pacer with adaptive backoff.

    ``acquire`` blocks the calling thread until its reserved slot arrives; ``note_status`` feeds the
    response code back so the limiter can tighten or relax.
    """

    def __init__(
        self,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        burst: float = DEFAULT_BURST,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        max_cooldown_seconds: float = DEFAULT_MAX_COOLDOWN_SECONDS,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._base_rate = max(MIN_REQUESTS_PER_SECOND, float(requests_per_second))
        self._burst = max(1.0, float(burst))
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._max_cooldown_seconds = max(self._cooldown_seconds, float(max_cooldown_seconds))
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_concurrency)))
        # GCRA theoretical arrival time: the instant the next unreserved slot becomes due.
        self._tat = self._clock()
        self._blocked_until = 0.0
        self._penalty_level = 0
        self._success_streak = 0
        self.total_requests = 0
        self.total_waited_seconds = 0.0
        self.total_rate_limited = 0

    @property
    def effective_rate(self) -> float:
        """Requests per second currently permitted, after any penalty halvings."""
        with self._lock:
            return self._effective_rate_locked()

    def _effective_rate_locked(self) -> float:
        return max(MIN_REQUESTS_PER_SECOND, self._base_rate / float(2 ** self._penalty_level))

    @property
    def penalty_level(self) -> int:
        with self._lock:
            return self._penalty_level

    def _reserve(self) -> float:
        """Claim the next slot and return how long the caller must sleep to use it."""
        with self._lock:
            now = self._clock()
            interval = 1.0 / self._effective_rate_locked()
            # A penalty pushes the whole schedule out, so one cooldown applies to every waiter.
            tat = max(self._tat, now, self._blocked_until)
            # Burst tolerance lets the schedule run ahead of now without forcing a wait. The first
            # slot is free by construction, so N-1 intervals of slack yield exactly N back-to-back
            # requests from an idle gate.
            allow_at = tat - ((self._burst - 1.0) * interval)
            self._tat = tat + interval
            self.total_requests += 1
            wait = allow_at - now
            if wait <= 0:
                return 0.0
            self.total_waited_seconds += wait
            return wait

    def acquire(self) -> float:
        """Block until this caller's paced slot is due. Returns the seconds actually slept."""
        wait = self._reserve()
        if wait > 0:
            self._sleep(wait)
        return wait

    def note_rate_limited(self) -> float:
        """Record a 429: halve the rate and push every pending slot past a cooldown."""
        with self._lock:
            self.total_rate_limited += 1
            self._success_streak = 0
            self._penalty_level = min(MAX_PENALTY_LEVEL, self._penalty_level + 1)
            cooldown = min(
                self._max_cooldown_seconds,
                self._cooldown_seconds * float(2 ** (self._penalty_level - 1)),
            )
            # Jitter so threads throttled together do not resume in lockstep.
            cooldown += random.uniform(0.0, max(0.001, cooldown * 0.1))
            self._blocked_until = max(self._blocked_until, self._clock() + cooldown)
            return cooldown

    def note_success(self) -> None:
        """Record a clean response, easing the penalty off after a sustained good run."""
        with self._lock:
            if self._penalty_level == 0:
                return
            self._success_streak += 1
            if self._success_streak >= SUCCESSES_TO_RECOVER:
                self._success_streak = 0
                self._penalty_level -= 1

    def note_status(self, status_code: Any) -> None:
        try:
            code = int(status_code)
        except (TypeError, ValueError):
            return
        if code == RATE_LIMIT_STATUS:
            self.note_rate_limited()
        elif code < 400:
            self.note_success()

    def concurrency_slot(self) -> Any:
        """Context manager bounding how many requests are in flight at once."""
        return _ConcurrencySlot(self._semaphore)

    def snapshot(self) -> dict[str, Any]:
        """Counters for diagnostics and tests."""
        with self._lock:
            return {
                'total_requests': self.total_requests,
                'total_waited_seconds': round(self.total_waited_seconds, 3),
                'total_rate_limited': self.total_rate_limited,
                'penalty_level': self._penalty_level,
                'effective_rate': round(self._effective_rate_locked(), 4),
            }


class _ConcurrencySlot:
    def __init__(self, semaphore: threading.BoundedSemaphore) -> None:
        self._semaphore = semaphore

    def __enter__(self) -> None:
        self._semaphore.acquire()

    def __exit__(self, *_exc: Any) -> bool:
        try:
            self._semaphore.release()
        except ValueError:
            pass
        return False


def build_limiter_from_env() -> YahooRateLimiter:
    """Construct the shared limiter, letting the rate be retuned without a code change."""
    return YahooRateLimiter(
        requests_per_second=_env_float('BUDGET_TERMINAL_YF_REQUESTS_PER_SECOND', DEFAULT_REQUESTS_PER_SECOND),
        burst=_env_float('BUDGET_TERMINAL_YF_BURST', DEFAULT_BURST),
        max_concurrency=_env_int('BUDGET_TERMINAL_YF_MAX_CONCURRENCY', DEFAULT_MAX_CONCURRENCY),
        cooldown_seconds=_env_float('BUDGET_TERMINAL_YF_COOLDOWN_SECONDS', DEFAULT_COOLDOWN_SECONDS),
        max_cooldown_seconds=_env_float('BUDGET_TERMINAL_YF_MAX_COOLDOWN_SECONDS', DEFAULT_MAX_COOLDOWN_SECONDS),
    )


_LIMITER_LOCK = threading.Lock()
_limiter: YahooRateLimiter | None = None


def get_limiter() -> YahooRateLimiter:
    """Return the process-wide limiter, building it on first use."""
    global _limiter
    limiter = _limiter
    if limiter is not None:
        return limiter
    with _LIMITER_LOCK:
        if _limiter is None:
            _limiter = build_limiter_from_env()
        return _limiter


def set_limiter(limiter: YahooRateLimiter | None) -> None:
    """Replace the shared limiter. Tests use this; application code should not."""
    global _limiter
    with _LIMITER_LOCK:
        _limiter = limiter


def _status_of(response: Any) -> Any:
    return getattr(response, 'status_code', None)


def paced_request(
    limiter: YahooRateLimiter,
    call: Callable[[], Any],
    *,
    retry_attempts: int = RETRY_ATTEMPTS,
    sleep: Callable[[float], None] | None = None,
) -> Any:
    """Run one Yahoo request through the gate, retrying a 429 a bounded number of times.

    The retry is deliberately small: ``note_rate_limited`` has already pushed the shared schedule
    out by a cooldown, so a later attempt waits inside ``acquire`` rather than hammering. Returning
    the 429 response after the final attempt keeps yfinance's own error handling intact.
    """
    sleeper = sleep or time.sleep
    attempts = max(1, int(retry_attempts) + 1)
    response = None
    for attempt in range(attempts):
        limiter.acquire()
        with limiter.concurrency_slot():
            response = call()
        status = _status_of(response)
        limiter.note_status(status)
        try:
            rate_limited = int(status) == RATE_LIMIT_STATUS
        except (TypeError, ValueError):
            rate_limited = False
        if not rate_limited or attempt == attempts - 1:
            return response
        # Nudge past the cooldown the penalty just installed before re-entering the gate.
        sleeper(min(2.0, 0.25 * float(2 ** attempt)))
    return response


_PACED_FLAG = '_budget_terminal_paced'


def pace_session(session: Any, limiter: YahooRateLimiter | None = None) -> Any:
    """Route a session's requests through the limiter, in place.

    The bound ``request`` method is replaced on the *instance* rather than by subclassing the
    backend Session: every verb (``get``/``post``/``stream``/...) dispatches through ``self.request``
    on both supported backends, an instance attribute shadows the class method, and the object stays
    an instance of the real Session class so ``_http.is_supported_session`` still accepts it.
    Subclassing would mean reproducing ``new_session``'s backend-specific construction, which is
    exactly the detail most likely to drift on a yfinance upgrade.
    """
    if session is None or getattr(session, _PACED_FLAG, False):
        return session
    original_request = session.request

    def paced(*args: Any, **kwargs: Any) -> Any:
        gate = limiter or get_limiter()
        return paced_request(gate, lambda: original_request(*args, **kwargs))

    session.request = paced
    setattr(session, _PACED_FLAG, True)
    return session


_INSTALL_LOCK = threading.Lock()
_installed = False


def is_installed() -> bool:
    return _installed


def install_yahoo_rate_limit(*, force: bool = False) -> bool:
    """Install the paced session into yfinance's ``YfData`` singleton.

    Imports yfinance, so call it from the lazy-load hook in ``dependencies`` rather than at startup:
    eagerly importing yfinance would undo the lazy proxy that keeps launch fast. Returns whether a
    paced session is in place. Never raises -- losing pacing degrades to the previous behaviour,
    which must not be allowed to break startup.

    Set ``BUDGET_TERMINAL_YF_RATE_LIMIT=0`` to opt out (useful when bisecting a data bug).
    """
    global _installed
    if _installed and not force:
        return True
    if str(os.environ.get('BUDGET_TERMINAL_YF_RATE_LIMIT', '1')).strip().lower() in ('0', 'false', 'no'):
        return False
    with _INSTALL_LOCK:
        if _installed and not force:
            return True
        try:
            from yfinance import _http
            from yfinance.data import YfData

            # Reuse the singleton's existing session when it already has one, so any cookie/crumb
            # state Yahoo has already handed us survives the swap.
            existing = getattr(YfData(), '_session', None)
            session = existing if existing is not None else _http.new_session()
            pace_session(session)
            YfData(session=session)
            _installed = True
            return True
        except Exception:
            return False
