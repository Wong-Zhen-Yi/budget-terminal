"""Embedded local data service for Budget Terminal."""

from __future__ import annotations

from .runtime import EmbeddedDataServiceRuntime
from .results import (
    MARKET_DATA_ERRORS_KEY,
    MARKET_DATA_META_KEY,
    attach_market_data_result,
    data_sources_from_meta,
    describe_market_data_status,
    market_data_errors,
    market_data_meta,
    strip_market_data_keys,
)
from .tasks import MarketDataTaskRunner

__all__ = [
    "EmbeddedDataServiceRuntime",
    "MARKET_DATA_ERRORS_KEY",
    "MARKET_DATA_META_KEY",
    "MarketDataTaskRunner",
    "attach_market_data_result",
    "data_sources_from_meta",
    "describe_market_data_status",
    "market_data_errors",
    "market_data_meta",
    "strip_market_data_keys",
]
