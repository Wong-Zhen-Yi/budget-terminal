"""Long-term risk-free rate snapshot for market-anchored valuation assumptions.

The valuation model needs one number — the 10-year Treasury yield — and needs it from a worker
thread, without turning every ticker load into a request to ``home.treasury.gov``. This module
wraps :func:`budget_terminal_app.services.economic.fetch_treasury_curve` in four tiers so the
common case costs nothing and the failure case degrades to the previous heuristic rather than
to an error.

Qt-free and presentation-independent, like the rest of ``services/``.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .economic import TREASURY_KIND_NOMINAL, TREASURY_KIND_REAL, fetch_treasury_curve

logger = logging.getLogger(__name__)

RISK_FREE_CACHE_NAMESPACE = 'risk_free_curve'
RISK_FREE_CACHE_KEY = 'us_treasury'

#: The 10-year yield moves in basis points per day; half a day of staleness is invisible in a DCF.
RISK_FREE_TTL_SECONDS = 12 * 60 * 60
#: A month-old yield is still far closer to the truth than the 10% heuristic baseline.
RISK_FREE_STALE_TTL_SECONDS = 30 * 24 * 60 * 60
#: Each ValuationWorker is a fresh object on a fresh QThread, so without a process memo two
#: back-to-back loads would both re-open sqlite.
MEMO_TTL_SECONDS = 15 * 60
#: treasury.gov consistently answers in 10-11 seconds, so a tighter budget would never succeed.
#: This cost lands on a worker thread at most once per 12 hours, behind the page's own spinner.
RISK_FREE_TIMEOUT_SECONDS = 20.0
#: The current-year CSV is nearly empty in early January, so always ask for last year too.
RISK_FREE_YEARS = 2

TENOR_LABEL = '10Y'
#: The nominal curve spells it ``10 Yr`` and the real curve spells it ``10 YR``; match either.
_TENOR_KEY = '10 yr'

_memo_lock = threading.Lock()
_memo: dict[str, Any] = {'payload': None, 'stamp': 0.0}


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _latest_tenor_point(curve: Any) -> tuple[str, float] | None:
    """Return the most recent ``(date, rate)`` for the 10-year tenor, whatever its spelling."""
    if not isinstance(curve, dict):
        return None
    for label, points in curve.items():
        if ' '.join(str(label or '').split()).casefold() != _TENOR_KEY:
            continue
        for stamp, value in reversed(list(points or [])):
            rate = _finite(value)
            if rate is not None:
                return str(stamp), rate
        return None
    return None


def _curve_tenor(kind: str) -> tuple[str, float] | None:
    try:
        return _latest_tenor_point(
            fetch_treasury_curve(kind=kind, years=RISK_FREE_YEARS, timeout=RISK_FREE_TIMEOUT_SECONDS)
        )
    except Exception as exc:
        logger.debug('Treasury %s curve unavailable: %s', kind, exc)
        return None


def _build_snapshot() -> dict[str, Any] | None:
    """Read the 10-year nominal and TIPS tenors, fetching both curves at once.

    Each curve costs a full round-trip to treasury.gov, so running them concurrently keeps the
    cold path at one round-trip rather than two. Losing TIPS costs only the breakeven anchor.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        nominal_future = executor.submit(_curve_tenor, TREASURY_KIND_NOMINAL)
        real_future = executor.submit(_curve_tenor, TREASURY_KIND_REAL)
        latest = nominal_future.result()
        real_latest = real_future.result()
    if latest is None:
        return None
    as_of, risk_free_rate = latest
    payload: dict[str, Any] = {
        'risk_free_rate': risk_free_rate,
        'real_rate': None,
        'breakeven_inflation': None,
        'as_of': as_of,
        'tenor': TENOR_LABEL,
        'freshness': 'fresh',
        'source': 'US Treasury daily par yield curve, 10Y',
    }
    if real_latest is not None:
        payload['real_rate'] = real_latest[1]
        payload['breakeven_inflation'] = risk_free_rate - real_latest[1]
    return payload


def _resolve_cache_manager(cache_manager: Any) -> Any:
    if cache_manager is not None:
        return cache_manager
    try:
        from ..cache import CacheManager
    except Exception as exc:
        logger.debug('Risk-free cache unavailable: %s', exc)
        return None
    try:
        return CacheManager()
    except Exception as exc:
        logger.debug('Risk-free cache construction failed: %s', exc)
        return None


def _read_cache(manager: Any, max_age_seconds: float) -> dict[str, Any] | None:
    if manager is None:
        return None
    try:
        payload = manager.get_json_payload(
            RISK_FREE_CACHE_NAMESPACE,
            RISK_FREE_CACHE_KEY,
            max_age_seconds=max_age_seconds,
        )
    except Exception as exc:
        logger.debug('Risk-free cache read failed: %s', exc)
        return None
    if not isinstance(payload, dict) or _finite(payload.get('risk_free_rate')) is None:
        return None
    return dict(payload)


def _remember(payload: dict[str, Any]) -> dict[str, Any]:
    with _memo_lock:
        _memo['payload'] = dict(payload)
        _memo['stamp'] = time.monotonic()
    return payload


def reset_risk_free_memo() -> None:
    """Clear the process memo so a test or a forced refresh starts from a known state."""
    with _memo_lock:
        _memo['payload'] = None
        _memo['stamp'] = 0.0


def fetch_risk_free_snapshot(*, cache_manager: Any = None, force_refresh: bool = False) -> dict[str, Any] | None:
    """Return the latest 10-year Treasury snapshot, or ``None`` when every tier fails.

    Tiers, first hit wins: a 15-minute process memo, a 12-hour sqlite entry, the Treasury CSVs,
    and finally a sqlite entry up to 30 days old marked ``freshness='stale'``. Callers treat
    ``None`` as "no market anchor" and fall back to the pre-CAPM heuristic.
    """
    if not force_refresh:
        with _memo_lock:
            payload = _memo['payload']
            fresh = payload is not None and (time.monotonic() - float(_memo['stamp'])) < MEMO_TTL_SECONDS
        if fresh:
            return dict(payload)

    manager = _resolve_cache_manager(cache_manager)
    if not force_refresh:
        cached = _read_cache(manager, RISK_FREE_TTL_SECONDS)
        if cached is not None:
            return dict(_remember(cached))

    try:
        snapshot = _build_snapshot()
    except Exception as exc:
        logger.info('Treasury risk-free fetch failed: %s', exc)
        snapshot = None
    if snapshot is not None:
        if manager is not None:
            try:
                manager.save_json_payload(RISK_FREE_CACHE_NAMESPACE, RISK_FREE_CACHE_KEY, snapshot)
            except Exception as exc:
                logger.debug('Risk-free cache write failed: %s', exc)
        return dict(_remember(snapshot))

    stale = _read_cache(manager, RISK_FREE_STALE_TTL_SECONDS)
    if stale is not None:
        stale['freshness'] = 'stale'
        return dict(_remember(stale))
    return None
