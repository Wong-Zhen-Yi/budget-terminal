from __future__ import annotations

from typing import Any

import httpx

from .serialization import deserialize_dashboard_payload


class DataServiceClient:
    """Small synchronous client for the embedded localhost data API."""

    def __init__(self, base_url: str, timeout_seconds: float = 180.0) -> None:
        self.base_url = str(base_url).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def health(self) -> bool:
        response = self._client.get("/health", timeout=2.0)
        response.raise_for_status()
        return response.json().get("status") == "ok"

    def fetch_dashboard(
        self,
        tickers: Any,
        chart_configs: Any,
        *,
        request_id: int = 0,
        refresh_reason: str = "full",
        allow_non_chart_reuse: bool = False,
    ) -> dict[str, Any]:
        response = self._client.post(
            "/dashboard/refresh",
            json={
                "tickers": list(tickers or []),
                "chart_configs": [list(config) for config in list(chart_configs or [])],
                "request_id": int(request_id),
                "refresh_reason": str(refresh_reason or "full"),
                "allow_non_chart_reuse": bool(allow_non_chart_reuse),
            },
        )
        response.raise_for_status()
        return deserialize_dashboard_payload(response.json())

    def fetch_month_returns(self, tickers: Any, *, period: str = "1mo", interval: str = "1d", start: Any = None) -> dict[str, Any]:
        payload = {
            "tickers": list(tickers or []),
            "period": str(period or "1mo"),
            "interval": str(interval or "1d"),
            "start": start,
        }
        response = self._client.post("/portfolio/month-returns", json=payload)
        response.raise_for_status()
        return deserialize_dashboard_payload(response.json())

    def fetch_portfolio_momentum(
        self,
        tickers: Any,
        shares_map: Any,
        *,
        period: str = "1mo",
        interval: str = "1d",
        start: Any = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            "/portfolio/momentum",
            json={
                "tickers": list(tickers or []),
                "shares_map": dict(shares_map or {}),
                "period": str(period or "1mo"),
                "interval": str(interval or "1d"),
                "start": start,
            },
        )
        response.raise_for_status()
        return deserialize_dashboard_payload(response.json())

    def fetch_portfolio_analytics(
        self,
        tickers: Any,
        shares_map: Any,
        *,
        prices_map: Any = None,
        benchmark_symbol: str = "SPY",
        lookback_key: str = "1y",
    ) -> dict[str, Any]:
        response = self._client.post(
            "/portfolio/analytics",
            json={
                "tickers": list(tickers or []),
                "shares_map": dict(shares_map or {}),
                "prices_map": dict(prices_map or {}),
                "benchmark_symbol": str(benchmark_symbol or "SPY"),
                "lookback_key": str(lookback_key or "1y"),
            },
        )
        response.raise_for_status()
        return deserialize_dashboard_payload(response.json())

    def fetch_market_caps(self, tickers: Any) -> dict[str, Any]:
        response = self._client.post("/market-caps", json={"tickers": list(tickers or [])})
        response.raise_for_status()
        return deserialize_dashboard_payload(response.json())
