from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from budget_terminal_app.data_service.results import (
    MARKET_DATA_ERRORS_KEY,
    MARKET_DATA_META_KEY,
    attach_market_data_result,
    describe_market_data_status,
)
from budget_terminal_app.data_service.tasks import MarketDataTaskRunner
from budget_terminal_app.persistence_schema import (
    TAB_SESSION_CACHE_SCHEMA_VERSION,
    USER_DATA_SCHEMA_VERSION,
    migrate_tab_session_payload,
    migrate_user_data_payload,
)
from budget_terminal_app.services.options_data import OptionsMarketDataService


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_result_metadata() -> None:
    payload = attach_market_data_result(
        {"price": 10.0},
        meta={"source": "unit", "freshness": "partial", "failure_reason": "missing one field"},
        errors=[{"source": "unit", "reason": "missing one field"}],
    )
    _assert(payload[MARKET_DATA_META_KEY]["source"] == "unit", "metadata source should be preserved")
    _assert(payload[MARKET_DATA_META_KEY]["is_partial"], "partial metadata should set is_partial")
    _assert(payload[MARKET_DATA_ERRORS_KEY][0]["reason"] == "missing one field", "error reason should be preserved")
    text, status = describe_market_data_status(payload, "Loaded")
    _assert(status == "warning" and "missing one field" in text, "partial payload should produce warning status")


def test_task_cache_fallback() -> None:
    runner = MarketDataTaskRunner(default_timeout_seconds=0.0, default_retries=0)

    def fail() -> dict[str, float]:
        raise RuntimeError("network unavailable")

    result = runner.run(
        "unit_task",
        fail,
        source="unit-network",
        cache_fallback=lambda: {"cached": 1.0},
        cache_source="unit-cache",
        cache_age_seconds=123.0,
        failure_reason="Unable to fetch unit data.",
    ).attach()
    _assert(result["cached"] == 1.0, "cache fallback payload should be returned")
    _assert(result[MARKET_DATA_META_KEY]["freshness"] == "stale", "cache fallback should be marked stale")
    _assert(result[MARKET_DATA_META_KEY]["cache_age_seconds"] == 123.0, "cache age should be preserved")


def test_schema_migrations() -> None:
    user_default = {"version": USER_DATA_SCHEMA_VERSION, "portfolios": {}}
    migrated_user = migrate_user_data_payload({"portfolio": ["SPY"], "version": 1}, user_default)
    _assert(migrated_user.target_version == USER_DATA_SCHEMA_VERSION, "user-data target version should be current")
    _assert(migrated_user.payload["version"] == USER_DATA_SCHEMA_VERSION, "user-data payload should be stamped current")

    migrated_session = migrate_tab_session_payload({"stocks": {"symbol": "SPY"}}, ("stocks", "options"))
    _assert(migrated_session.payload["version"] == TAB_SESSION_CACHE_SCHEMA_VERSION, "session cache should be stamped current")
    _assert(migrated_session.payload["tabs"]["stocks"]["symbol"] == "SPY", "legacy session tabs should migrate")
    _assert(migrated_session.payload["tabs"]["options"] is None, "missing session tabs should default to None")


def test_options_failure_reason() -> None:
    payload = OptionsMarketDataService().fetch_option_quote_payload("AAPL", "", 0, "Calls")
    _assert(payload.get("error") == "Incomplete Data", "missing expiry should preserve legacy error label")
    _assert(payload[MARKET_DATA_META_KEY]["freshness"] == "failed", "missing expiry should be marked failed")
    _assert("expiry" in payload[MARKET_DATA_META_KEY]["failure_reason"].lower(), "failure reason should be user-readable")


def main() -> None:
    test_result_metadata()
    test_task_cache_fallback()
    test_schema_migrations()
    test_options_failure_reason()
    print("market data foundation smoke tests passed")


if __name__ == "__main__":
    main()
