from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.data_service.results import (
    attach_market_data_result,
    make_market_data_error,
    make_market_data_meta,
)
from budget_terminal_app.mixins.data_health import DataHealthMixin


class _HealthProbe(DataHealthMixin):
    pass


def test_failed_event_resolves_after_fresh_payload() -> None:
    probe = _HealthProbe()
    probe._init_data_health_state()
    failed = attach_market_data_result(
        {},
        meta=make_market_data_meta(source="yfinance", freshness="failed", failure_reason="timed out"),
        errors=make_market_data_error(source="yfinance", operation="market_caps", reason="timed out"),
    )
    probe._record_data_health_payload("Market caps", failed, symbols=["PLTR", "NVDA"])
    assert probe._data_health_counts() == (1, 0)

    fresh = attach_market_data_result(
        {"PLTR": {}, "NVDA": {}},
        meta=make_market_data_meta(source="yfinance", freshness="fresh"),
    )
    probe._record_data_health_payload("Market caps", fresh, symbols=["PLTR", "NVDA"])

    assert probe._data_health_counts() == (0, 0)
    assert probe._data_health_summary()[0] == "Data health: OK"
    assert probe._data_health_events[0]["active"] is False
    assert probe._data_health_events[0]["resolved_at"] is not None
    assert "RESOLVED" in probe._build_data_health_report()


def test_successful_retry_error_is_resolved_history() -> None:
    probe = _HealthProbe()
    probe._init_data_health_state()
    recovered = attach_market_data_result(
        {"request_id": 1},
        meta=make_market_data_meta(source="yfinance", freshness="fresh"),
        errors=make_market_data_error(source="yfinance", operation="dashboard_refresh", reason="first attempt failed"),
    )

    probe._record_data_health_payload("Dashboard", recovered, symbols=["PLTR"])

    assert probe._data_health_counts() == (0, 0)
    assert len(probe._data_health_events) == 1
    assert probe._data_health_events[0]["active"] is False


if __name__ == "__main__":
    test_failed_event_resolves_after_fresh_payload()
    test_successful_retry_error_is_resolved_history()
    print("data health resolution tests passed")
