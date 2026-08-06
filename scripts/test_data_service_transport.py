from __future__ import annotations

import copy
import socket
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.data_service.client import (
    DataServiceClient,
    DataServiceClientProtocol,
    InProcessDataServiceClient,
)
from budget_terminal_app.data_service.coordinator import DashboardFetchCoordinator
from budget_terminal_app.data_service.runtime import EmbeddedDataServiceRuntime
from budget_terminal_app.data_service.serialization import serialize_dashboard_payload
from budget_terminal_app.data_service.tasks import MarketDataTaskRunner
from budget_terminal_app.workers.data import DataWorker


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _EchoCoordinator:
    def __init__(self, rows: int = 4) -> None:
        self.closed = False
        self.rows = rows

    def shutdown(self) -> None:
        self.closed = True

    def _result(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        index = pd.date_range("2026-01-01", periods=self.rows, freq="D")
        index.name = "Date"
        return {
            "operation": operation,
            "request": copy.deepcopy(request),
            "frame": pd.DataFrame({"Close": range(self.rows)}, index=index),
            "series": pd.Series(range(self.rows), index=index, name="Volume"),
            "empty": {},
            "missing": None,
        }

    def fetch_dashboard(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("dashboard", request)

    def fetch_portfolio_quotes(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("portfolio_quotes", request)

    def fetch_month_returns(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("month_returns", request)

    def fetch_portfolio_momentum(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("portfolio_momentum", request)

    def fetch_portfolio_analytics(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("portfolio_analytics", request)

    def fetch_market_caps(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._result("market_caps", request)


class _LoopbackHttpxClient:
    def __init__(self, coordinator: _EchoCoordinator) -> None:
        self.coordinator = coordinator
        self.closed = False

    def get(self, path: str, **_kwargs: Any) -> _Response:
        assert path == "/health"
        return _Response({"status": "ok"})

    def post(self, path: str, json: dict[str, Any]) -> _Response:
        handlers = {
            "/dashboard/refresh": self.coordinator.fetch_dashboard,
            "/portfolio/quotes": self.coordinator.fetch_portfolio_quotes,
            "/portfolio/month-returns": self.coordinator.fetch_month_returns,
            "/portfolio/momentum": self.coordinator.fetch_portfolio_momentum,
            "/portfolio/analytics": self.coordinator.fetch_portfolio_analytics,
            "/market-caps": self.coordinator.fetch_market_caps,
        }
        return _Response(serialize_dashboard_payload(handlers[path](json)))

    def close(self) -> None:
        self.closed = True


def _http_client(coordinator: _EchoCoordinator) -> DataServiceClient:
    client = DataServiceClient("http://loopback.invalid")
    client._client.close()
    client._client = _LoopbackHttpxClient(coordinator)
    return client


def _assert_equivalent(left: dict[str, Any], right: dict[str, Any]) -> None:
    assert left["operation"] == right["operation"]
    assert left["request"] == right["request"]
    assert left["empty"] == right["empty"]
    assert left["missing"] is right["missing"]
    pd.testing.assert_frame_equal(left["frame"], right["frame"], check_dtype=False, check_freq=False)
    pd.testing.assert_series_equal(
        left["series"], right["series"], check_dtype=False, check_names=False, check_freq=False
    )


def test_transport_contract_parity() -> None:
    direct_coordinator = _EchoCoordinator()
    http_coordinator = _EchoCoordinator()
    direct = InProcessDataServiceClient(direct_coordinator)
    http = _http_client(http_coordinator)
    assert isinstance(direct, DataServiceClientProtocol)
    assert isinstance(http, DataServiceClientProtocol)

    calls = [
        lambda client: client.fetch_dashboard(
            ["AAPL"], [("SPY", "1y", "1d")], request_id=7,
            refresh_reason="manual_refresh", allow_non_chart_reuse=True,
        ),
        lambda client: client.fetch_portfolio_quotes(["AAPL", "MSFT"]),
        lambda client: client.fetch_month_returns(["AAPL"], period="3mo", interval="1d", start="2026-01-01"),
        lambda client: client.fetch_portfolio_momentum(
            ["AAPL"], {"AAPL": 2}, period="1y", interval="1d", cash_amount=10,
        ),
        lambda client: client.fetch_portfolio_analytics(
            ["AAPL"], {"AAPL": 2}, prices_map={"AAPL": 100}, benchmark_symbol="QQQ",
            lookback_key="3y", cash_amount=10,
        ),
        lambda client: client.fetch_market_caps(["AAPL", "MSFT"]),
    ]
    for call in calls:
        _assert_equivalent(call(direct), call(http))

    direct.close()
    http.close()
    assert direct_coordinator.closed
    assert not direct.health()


def test_identical_requests_are_coalesced() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        coordinator = DashboardFetchCoordinator(
            max_workers=2,
            cache_manager=CacheManager(Path(temp_dir) / "cache.db"),
        )
        count = 0
        count_lock = threading.Lock()

        def slow_fetch(_request: dict[str, Any]) -> dict[str, Any]:
            nonlocal count
            with count_lock:
                count += 1
            time.sleep(0.1)
            return {"payload": [1, 2, 3]}

        coordinator._run_fetch = slow_fetch
        request_a = {"tickers": ["AAPL"], "chart_configs": [], "request_id": 1}
        request_b = {"tickers": ["AAPL"], "chart_configs": [], "request_id": 2}
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(coordinator.fetch_dashboard, request_a)
            second = executor.submit(coordinator.fetch_dashboard, request_b)
            result_a = first.result(timeout=5)
            result_b = second.result(timeout=5)
        coordinator.shutdown(wait=True)

    assert count == 1
    assert result_a["request_id"] == 1
    assert result_b["request_id"] == 2
    assert result_a["payload"] == result_b["payload"] == [1, 2, 3]


def test_portfolio_quote_worker_excludes_dashboard_fanout() -> None:
    worker = DataWorker(["AAPL"], [])
    worker._download_batch_data = lambda _symbols: pd.DataFrame()
    worker._load_close_series = lambda *_args: pd.Series([100.0, 102.0])
    payload = worker.fetch_portfolio_quotes()

    assert payload["portfolio"]["AAPL"]["price"] == 102.0
    assert not ({"news", "targets", "market", "charts", "chart_options"} & payload.keys())


def test_task_runner_reuses_executor_and_closes() -> None:
    runner = MarketDataTaskRunner(default_timeout_seconds=1, max_workers=2)
    executor_id = id(runner._executor)
    assert runner.run("first", lambda: {"value": 1}).data == {"value": 1}
    assert runner.run("second", lambda: {"value": 2}).data == {"value": 2}
    assert id(runner._executor) == executor_id
    runner.shutdown(wait=True)
    failed = runner.run("closed", lambda: {"value": 3})
    assert failed.errors
    assert "closed" in failed.errors[-1]["reason"]


def test_cache_supports_concurrent_readers_and_writers() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cache = CacheManager(Path(temp_dir) / "concurrent.db")
        index = pd.date_range("2026-01-01", periods=3, name="Date")

        def write_and_read(number: int) -> tuple[str, int]:
            symbol = f"T{number}"
            cache.save_data(symbol, "1d", pd.DataFrame({"Close": [number, number + 1, number + 2]}, index=index))
            loaded = cache.get_data(symbol, "1d")
            return symbol, 0 if loaded is None else len(loaded)

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(write_and_read, range(12)))
    assert all(row_count == 3 for _symbol, row_count in results)


def test_inprocess_transport_avoids_serialization_overhead() -> None:
    direct = InProcessDataServiceClient(_EchoCoordinator(rows=2_000))
    http = _http_client(_EchoCoordinator(rows=2_000))
    direct.fetch_market_caps(["AAPL"])
    http.fetch_market_caps(["AAPL"])

    started = time.perf_counter()
    for _ in range(5):
        direct.fetch_market_caps(["AAPL"])
    direct_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    for _ in range(5):
        http.fetch_market_caps(["AAPL"])
    http_elapsed = time.perf_counter() - started
    direct.close()
    http.close()

    assert direct_elapsed < http_elapsed
    print(f"transport benchmark: inprocess={direct_elapsed:.4f}s http-loopback={http_elapsed:.4f}s")


def test_concurrent_http_runtimes_reserve_distinct_ports() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        preferred_port = int(probe.getsockname()[1])

    synchronized_selection = threading.Barrier(2)
    synchronized_reservation = threading.Barrier(2)

    class SynchronizedPortSelectionRuntime(EmbeddedDataServiceRuntime):
        def _reserve_available_socket(self) -> socket.socket:
            server_socket = super()._reserve_available_socket()
            synchronized_reservation.wait(timeout=5.0)
            return server_socket

        # This hook keeps the regression red-capable against the former
        # check-then-bind implementation. The current reservation path above
        # is the hook exercised by production.
        def _port_available(self, port: int) -> bool:
            available = super()._port_available(port)
            if int(port) == preferred_port:
                synchronized_selection.wait(timeout=5.0)
            return available

    runtimes = [
        SynchronizedPortSelectionRuntime(preferred_port=preferred_port, transport="http")
        for _ in range(2)
    ]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            started = list(executor.map(lambda runtime: runtime.start(timeout_seconds=5.0), runtimes))
        assert started == [True, True]
        assert None not in {runtime.port for runtime in runtimes}
        assert len({runtime.port for runtime in runtimes}) == 2
        assert all(runtime.client is not None and runtime.client.health() for runtime in runtimes)
    finally:
        for runtime in runtimes:
            runtime.stop()


if __name__ == "__main__":
    test_transport_contract_parity()
    test_identical_requests_are_coalesced()
    test_portfolio_quote_worker_excludes_dashboard_fanout()
    test_task_runner_reuses_executor_and_closes()
    test_cache_supports_concurrent_readers_and_writers()
    test_inprocess_transport_avoids_serialization_overhead()
    test_concurrent_http_runtimes_reserve_distinct_ports()
    print("data service transport smoke tests passed")
