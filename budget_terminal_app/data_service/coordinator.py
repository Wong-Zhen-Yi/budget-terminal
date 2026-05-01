from __future__ import annotations

import copy
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from ..cache import CacheManager
from ..dependencies import logger
from ..workers.data import DataWorker
from ..workers.market_metrics import (
    MarketCapWorker,
    MonthReturnWorker,
    PortfolioAnalyticsWorker,
    PortfolioMomentumWorker,
)


class DashboardFetchCoordinator:
    """Coalesce identical dashboard fetches running behind the local API."""

    def __init__(self, max_workers: int = 3) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._inflight: dict[tuple[Any, ...], Future] = {}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def fetch_dashboard(self, request: dict[str, Any]) -> dict[str, Any]:
        key = self._request_key(request)
        with self._lock:
            future = self._inflight.get(key)
            if future is None:
                future = self._executor.submit(self._run_fetch, request)
                self._inflight[key] = future
        try:
            result = copy.deepcopy(future.result())
        finally:
            if future.done():
                with self._lock:
                    if self._inflight.get(key) is future:
                        self._inflight.pop(key, None)
        result["request_id"] = int(request.get("request_id", 0) or 0)
        return result

    def fetch_month_returns(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._coalesced_fetch(
            "month_returns",
            (
                tuple(self._symbols(request.get("tickers", []))),
                str(request.get("period", "1mo") or "1mo"),
                str(request.get("interval", "1d") or "1d"),
                str(request.get("start") or ""),
            ),
            lambda: MonthReturnWorker(
                self._symbols(request.get("tickers", [])),
                period=str(request.get("period", "1mo") or "1mo"),
                interval=str(request.get("interval", "1d") or "1d"),
                start=request.get("start"),
            ).fetch(),
        )

    def fetch_portfolio_momentum(self, request: dict[str, Any]) -> dict[str, Any]:
        tickers = self._symbols(request.get("tickers", []))
        shares_map = self._number_map(request.get("shares_map", {}))
        return self._coalesced_fetch(
            "portfolio_momentum",
            (
                tuple(tickers),
                tuple(sorted(shares_map.items())),
                str(request.get("period", "1mo") or "1mo"),
                str(request.get("interval", "1d") or "1d"),
                str(request.get("start") or ""),
            ),
            lambda: PortfolioMomentumWorker(
                tickers,
                shares_map,
                period=str(request.get("period", "1mo") or "1mo"),
                interval=str(request.get("interval", "1d") or "1d"),
                start=request.get("start"),
            ).fetch(),
        )

    def fetch_portfolio_analytics(self, request: dict[str, Any]) -> dict[str, Any]:
        tickers = self._symbols(request.get("tickers", []))
        shares_map = self._number_map(request.get("shares_map", {}))
        prices_map = self._number_map(request.get("prices_map", {}))
        return self._coalesced_fetch(
            "portfolio_analytics",
            (
                tuple(tickers),
                tuple(sorted(shares_map.items())),
                tuple(sorted(prices_map.items())),
                str(request.get("benchmark_symbol", "SPY") or "SPY").upper(),
                str(request.get("lookback_key", "1y") or "1y").lower(),
            ),
            lambda: PortfolioAnalyticsWorker(
                tickers,
                shares_map,
                prices_map=prices_map,
                benchmark_symbol=str(request.get("benchmark_symbol", "SPY") or "SPY"),
                lookback_key=str(request.get("lookback_key", "1y") or "1y"),
            ).fetch(),
        )

    def fetch_market_caps(self, request: dict[str, Any]) -> dict[str, Any]:
        tickers = self._symbols(request.get("tickers", []))
        return self._coalesced_fetch(
            "market_caps",
            (tuple(tickers),),
            lambda: MarketCapWorker(tickers).fetch(),
        )

    def _coalesced_fetch(self, namespace: str, key_parts: tuple[Any, ...], fetch_fn: Any) -> dict[str, Any]:
        key = (namespace, *key_parts)
        with self._lock:
            future = self._inflight.get(key)
            if future is None:
                future = self._executor.submit(fetch_fn)
                self._inflight[key] = future
        try:
            return copy.deepcopy(future.result())
        finally:
            if future.done():
                with self._lock:
                    if self._inflight.get(key) is future:
                        self._inflight.pop(key, None)

    def _request_key(self, request: dict[str, Any]) -> tuple[Any, ...]:
        tickers = tuple(str(item or "").upper().strip() for item in request.get("tickers", []) if str(item or "").strip())
        chart_configs = tuple(
            tuple(str(part or "") for part in config[:3])
            for config in request.get("chart_configs", [])
            if isinstance(config, (list, tuple)) and len(config) >= 3
        )
        return (
            tickers,
            chart_configs,
            str(request.get("refresh_reason", "full") or "full"),
            bool(request.get("allow_non_chart_reuse", False)),
        )

    def _symbols(self, values: Any) -> list[str]:
        seen = set()
        symbols = []
        for value in list(values or []):
            symbol = str(value or "").upper().strip()
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        return symbols

    def _number_map(self, values: Any) -> dict[str, float]:
        normalized = {}
        if not isinstance(values, dict):
            return normalized
        for key, value in values.items():
            symbol = str(key or "").upper().strip()
            if not symbol:
                continue
            try:
                normalized[symbol] = float(value)
            except (TypeError, ValueError):
                normalized[symbol] = 0.0
        return normalized

    def _run_fetch(self, request: dict[str, Any]) -> dict[str, Any]:
        worker = DataWorker(
            request.get("tickers", []),
            request.get("chart_configs", []),
            request_id=0,
            cache_manager=CacheManager(),
            refresh_reason=str(request.get("refresh_reason", "full") or "full"),
            allow_non_chart_reuse=bool(request.get("allow_non_chart_reuse", False)),
        )
        logger.info("Embedded data service fetching dashboard payload.")
        return worker.fetch()
