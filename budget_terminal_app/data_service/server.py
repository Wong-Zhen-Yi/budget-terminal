from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .coordinator import DashboardFetchCoordinator
from .serialization import serialize_dashboard_payload


class DashboardRefreshRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    chart_configs: list[list[Any]] = Field(default_factory=list)
    request_id: int = 0
    refresh_reason: str = "full"
    allow_non_chart_reuse: bool = False


class MonthReturnsRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    period: str = "1mo"
    interval: str = "1d"
    start: str | None = None


class PortfolioMomentumRequest(MonthReturnsRequest):
    shares_map: dict[str, float] = Field(default_factory=dict)


class PortfolioAnalyticsRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    shares_map: dict[str, float] = Field(default_factory=dict)
    prices_map: dict[str, float] = Field(default_factory=dict)
    benchmark_symbol: str = "SPY"
    lookback_key: str = "1y"


class MarketCapsRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)


def _model_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def create_app(coordinator: DashboardFetchCoordinator | None = None) -> FastAPI:
    app = FastAPI(title="Budget Terminal Data Service", docs_url=None, redoc_url=None)
    app.state.coordinator = coordinator or DashboardFetchCoordinator()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/dashboard/refresh")
    def refresh_dashboard(request: DashboardRefreshRequest) -> dict[str, Any]:
        payload = app.state.coordinator.fetch_dashboard(_model_payload(request))
        return serialize_dashboard_payload(payload)

    @app.post("/portfolio/month-returns")
    def month_returns(request: MonthReturnsRequest) -> dict[str, Any]:
        payload = app.state.coordinator.fetch_month_returns(_model_payload(request))
        return serialize_dashboard_payload(payload)

    @app.post("/portfolio/momentum")
    def portfolio_momentum(request: PortfolioMomentumRequest) -> dict[str, Any]:
        payload = app.state.coordinator.fetch_portfolio_momentum(_model_payload(request))
        return serialize_dashboard_payload(payload)

    @app.post("/portfolio/analytics")
    def portfolio_analytics(request: PortfolioAnalyticsRequest) -> dict[str, Any]:
        payload = app.state.coordinator.fetch_portfolio_analytics(_model_payload(request))
        return serialize_dashboard_payload(payload)

    @app.post("/market-caps")
    def market_caps(request: MarketCapsRequest) -> dict[str, Any]:
        payload = app.state.coordinator.fetch_market_caps(_model_payload(request))
        return serialize_dashboard_payload(payload)

    @app.on_event("shutdown")
    def shutdown() -> None:
        app.state.coordinator.shutdown()

    return app
