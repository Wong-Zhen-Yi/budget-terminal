from __future__ import annotations

import datetime
import json
import math
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.workers import random_recommender as roll_worker
from budget_terminal_app.workers.random_recommender import RandomStockWorker


def _quote(symbol: str, *, score_seed: int = 0) -> dict[str, object]:
    return {
        "symbol": symbol,
        "longName": f"{symbol} Corporation",
        "quoteType": "EQUITY",
        "regularMarketPrice": 100.0 + score_seed,
        "regularMarketPreviousClose": 99.0 + score_seed,
        "regularMarketChangePercent": float(score_seed % 7) - 2.0,
        "marketCap": 10_000_000_000 + score_seed * 1_000_000,
        "averageDailyVolume3Month": 2_000_000 + score_seed * 10_000,
        "fiftyTwoWeekChangePercent": float(score_seed % 11) / 10.0,
        "sector": "Technology",
    }


def _history_frame(rows: int = 100, *, base: float = 100.0) -> pd.DataFrame:
    index = pd.date_range("2025-01-02", periods=rows, freq="B")
    closes = [base + index * 0.25 for index in range(rows)]
    return pd.DataFrame(
        {
            "Open": [value - 0.2 for value in closes],
            "High": [value + 0.8 for value in closes],
            "Low": [value - 0.9 for value in closes],
            "Close": closes,
            "Adj Close": [value * 0.5 for value in closes],
            "Volume": [1_000_000 + index * 1_000 for index in range(rows)],
        },
        index=index,
    )


def _consolidation_frame() -> pd.DataFrame:
    closes = [100.0 + (-1) ** index * 3.0 for index in range(80)]
    closes.extend([100.0 + (-1) ** index * 0.3 for index in range(19)])
    closes.append(100.0)
    spreads = [4.0] * 80 + [0.8] * 20
    return pd.DataFrame(
        {
            "Open": [value - 0.1 for value in closes],
            "High": [value + spread for value, spread in zip(closes, spreads)],
            "Low": [value - spread for value, spread in zip(closes, spreads)],
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        }
    )


def _downtrend_frame() -> pd.DataFrame:
    closes = [150.0 - index * 0.3 + 1.5 * math.sin(index * 1.1) for index in range(100)]
    opens = [value + (0.4 if index % 3 else -0.3) for index, value in enumerate(closes)]
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(open_value, close_value) + 0.8 for open_value, close_value in zip(opens, closes)],
            "Low": [min(open_value, close_value) - 0.9 for open_value, close_value in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000 + index * 1_000 for index in range(len(closes))],
        }
    )


def test_history_normalization_retains_open_adjusts_and_drops_live_bar() -> None:
    worker = RandomStockWorker()
    current_day = pd.Timestamp("2026-07-13")
    frame = pd.DataFrame(
        {
            "Open": ["18", "9", "20", "30"],
            "High": ["22", "12", "24", "34"],
            "Low": ["17", "8", "19", "29"],
            "Close": ["20", "10", "22", "32"],
            "Adj Close": ["10", "5", "11", "16"],
            "Volume": ["2000", "1000", "2200", "3200"],
        },
        index=[pd.Timestamp("2026-07-10"), pd.Timestamp("2026-07-09"), pd.Timestamp("2026-07-10"), current_day],
    )
    now = datetime.datetime(2026, 7, 13, 10, 30, tzinfo=ZoneInfo("America/New_York"))

    normalized = worker._normalize_history_frame(frame, now=now)

    assert normalized is not None
    assert list(normalized.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert list(normalized.index) == [pd.Timestamp("2026-07-09"), pd.Timestamp("2026-07-10")]
    assert normalized.loc[pd.Timestamp("2026-07-09"), "Open"] == 4.5
    assert normalized.loc[pd.Timestamp("2026-07-10"), "Open"] == 10.0
    assert normalized.loc[pd.Timestamp("2026-07-10"), "Close"] == 11.0
    assert current_day not in normalized.index

    early_close_frame = frame.loc[[pd.Timestamp("2026-07-10"), current_day]].copy()
    after_early_close = datetime.datetime(2026, 7, 13, 13, 30, tzinfo=ZoneInfo("America/New_York"))
    with patch.object(worker, "_nyse_close_time", return_value=datetime.time(13, 0)):
        completed = worker._normalize_history_frame(early_close_frame, now=after_early_close)
    assert completed is not None
    assert current_day in completed.index


def test_breakout_consolidation_and_downtrend_positive_patterns() -> None:
    worker = RandomStockWorker()

    breakout_match, breakout_score, _reasons, breakout_snapshot = worker._evaluate_breakout_pattern(_history_frame(70))
    assert breakout_match
    assert breakout_score >= 58.0
    assert breakout_snapshot["setup_stage"] in {"Pre-Breakout", "Fresh Breakout"}

    consolidation_match, consolidation_score, _reasons, consolidation_snapshot = worker._evaluate_consolidation_pattern(
        _consolidation_frame()
    )
    assert consolidation_match
    assert consolidation_score == 100.0
    assert consolidation_snapshot["range_pct"] <= 14.0
    assert consolidation_snapshot["atr20"] <= consolidation_snapshot["atr60"] * 0.85

    downtrend_match, downtrend_score, _reasons, downtrend_snapshot = worker._evaluate_downtrend_pattern(_downtrend_frame())
    assert downtrend_match
    assert downtrend_score >= 58.0
    assert downtrend_snapshot["daily_ma_stack"] == "bearish"
    assert downtrend_snapshot["lower_highs"] is True
    assert downtrend_snapshot["lower_lows"] is True
    assert downtrend_snapshot["volume_state"] == "downside participation"


def test_pattern_history_threshold_and_nan_rows_fail_safely() -> None:
    worker = RandomStockWorker()
    frame = _history_frame(70)
    frame.iloc[-1, frame.columns.get_loc("Close")] = float("nan")
    normalized = worker._normalize_history_frame(frame)
    assert normalized is not None
    assert len(normalized) == 69
    for evaluator in (
        worker._evaluate_breakout_pattern,
        worker._evaluate_consolidation_pattern,
        worker._evaluate_downtrend_pattern,
    ):
        matched, score, reasons, snapshot = evaluator(normalized)
        assert (matched, score, reasons, snapshot) == (False, 0.0, [], {})


def test_screen_buckets_are_unique_bounded_and_round_robin_keeps_losers() -> None:
    worker = RandomStockWorker(pattern_modes=["downtrend"])
    calls: list[tuple[str, bool, int]] = []
    calls_lock = threading.Lock()
    prefixes = {
        ("intradaymarketcap", False): "LIQ",
        ("avgdailyvol3m", False): "VOL",
        ("percentchange", False): "MOM",
        ("fiftytwowkpercentchange", False): "YRM",
        ("percentchange", True): "LOS",
        ("fiftytwowkpercentchange", True): "YRL",
        ("ticker", True): "RND",
    }

    def fake_screen_quotes(
        _query: object,
        _total: int,
        *,
        offset: int,
        size: int,
        sort_field: str,
        sort_asc: bool,
    ) -> list[dict[str, object]]:
        del size
        with calls_lock:
            calls.append((sort_field, sort_asc, offset))
        prefix = prefixes[(sort_field, sort_asc)]
        return [_quote(f"{prefix}{offset:03d}{index:02d}", score_seed=index) for index in range(40)]

    real_executor = roll_worker.ThreadPoolExecutor
    executor_sizes: list[int] = []

    def executor_factory(*args: object, **kwargs: object):
        max_workers = int(kwargs.get("max_workers") or args[0])
        executor_sizes.append(max_workers)
        return real_executor(*args, **kwargs)

    with (
        patch.object(worker, "_screen_quotes", side_effect=fake_screen_quotes),
        patch.object(roll_worker.random, "randint", side_effect=[10, 20, 30]),
        patch.object(roll_worker, "ThreadPoolExecutor", side_effect=executor_factory),
    ):
        buckets = worker._fetch_screen_buckets(object(), 500)

    assert len(calls) == len(set(calls))
    assert executor_sizes == [4]
    assert set(buckets) == {"liquidity", "momentum", "loser", "random"}
    candidates = worker._build_candidate_pool(object(), 500, buckets=buckets)
    symbols = [str(candidate["symbol"]) for candidate in candidates]
    assert len(candidates) == worker._PATTERN_CANDIDATE_LIMIT
    assert any(symbol.startswith(("LOS", "YRL")) for symbol in symbols)
    assert any(symbol.startswith("RND") for symbol in symbols)
    first_four = symbols[:4]
    assert any(symbol.startswith(("LIQ", "VOL")) for symbol in first_four)
    assert any(symbol.startswith(("MOM", "YRM")) for symbol in first_four)
    assert any(symbol.startswith(("LOS", "YRL")) for symbol in first_four)
    assert any(symbol.startswith("RND") for symbol in first_four)


def test_history_retry_is_one_bounded_batch_and_warm_load_uses_cache() -> None:
    RandomStockWorker.clear_caches()
    worker = RandomStockWorker(pattern_modes=["breakout"])
    first = pd.concat({"AAA": _history_frame(), "BBB": _history_frame(base=120.0)}, axis=1)
    retry = _history_frame(base=80.0)
    requests: list[list[str]] = []

    def fake_download(symbols: list[str]):
        requests.append(list(symbols))
        return first if len(requests) == 1 else retry

    with patch.object(worker, "_download_pattern_history", side_effect=fake_download):
        histories = worker._prepare_pattern_histories(["AAA", "BBB", "CCC", "AAA"])

    assert set(histories) == {"AAA", "BBB", "CCC"}
    assert requests == [["AAA", "BBB", "CCC"], ["CCC"]]
    assert worker._fetch_meta["history_retry_count"] == 1
    assert worker._fetch_meta["history_downloaded"] == 3
    assert all(list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"] for frame in histories.values())

    warm_worker = RandomStockWorker(pattern_modes=["breakout"])
    with patch.object(warm_worker, "_download_pattern_history", side_effect=AssertionError("warm history must not download")):
        warm_histories = warm_worker._prepare_pattern_histories(["AAA", "BBB", "CCC"])
    assert set(warm_histories) == {"AAA", "BBB", "CCC"}
    assert warm_worker._fetch_meta["history_cache_hits"] == 3
    RandomStockWorker.clear_caches()


def test_screening_snapshot_and_selected_evaluations_use_ten_minute_caches() -> None:
    RandomStockWorker.clear_caches()
    buckets = {
        "liquidity": [_quote("AAA")],
        "momentum": [_quote("BBB")],
        "loser": [_quote("CCC")],
        "random": [_quote("DDD")],
    }
    cold = RandomStockWorker(pattern_modes=["breakout", "downtrend"])
    with (
        patch.object(cold, "_screen_total", return_value=400) as screen_total,
        patch.object(cold, "_fetch_screen_buckets", return_value=buckets) as fetch_buckets,
    ):
        total, cold_buckets = cold._screening_snapshot(object())
    assert total == 400
    assert cold_buckets == buckets
    screen_total.assert_called_once()
    fetch_buckets.assert_called_once()

    warm = RandomStockWorker(pattern_modes=["breakout", "downtrend"])
    with (
        patch.object(warm, "_screen_total", side_effect=AssertionError("warm screen must not refetch")),
        patch.object(warm, "_fetch_screen_buckets", side_effect=AssertionError("warm buckets must not refetch")),
    ):
        warm_total, warm_buckets = warm._screening_snapshot(object())
    assert warm_total == 400
    assert warm_buckets == buckets
    assert warm._fetch_meta["screen_cache_hit"] is True

    frame = _history_frame()
    calls = {"breakout": 0, "downtrend": 0}

    def breakout(_frame: object):
        calls["breakout"] += 1
        return True, 71.0, ["breakout"], {"setup_stage": "Breakout Setup"}

    def downtrend(_frame: object):
        calls["downtrend"] += 1
        return False, 59.0, ["downtrend"], {"setup_stage": "Downtrend"}

    cold._evaluate_breakout_pattern = breakout
    cold._evaluate_downtrend_pattern = downtrend
    cold._evaluate_consolidation_pattern = lambda _frame: (_ for _ in ()).throw(
        AssertionError("unselected consolidation evaluator ran")
    )
    first = cold._evaluate_selected_patterns("AAA", frame)
    second = cold._evaluate_selected_patterns("AAA", frame.copy())
    assert set(first) == {"breakout", "downtrend"}
    assert second == first
    assert calls == {"breakout": 1, "downtrend": 1}
    assert cold._fetch_meta["evaluation_cache_hits"] == 2
    RandomStockWorker.clear_caches()


def test_or_matching_uses_strict_only_and_near_fallback_is_labelled() -> None:
    frame = _history_frame()
    candidates = [
        {"symbol": "AAA", "score": 90.0, "rank": 1},
        {"symbol": "BBB", "score": 60.0, "rank": 2},
        {"symbol": "CCC", "score": 99.0, "rank": 3},
    ]
    worker = RandomStockWorker(pattern_modes=["breakout", "downtrend"])

    def strict_results(symbol: str, _frame: object):
        if symbol == "AAA":
            return {
                "breakout": (True, 70.0, ["AAA breakout"], {"setup_stage": "Breakout Setup"}),
                "downtrend": (False, 0.0, [], {}),
            }
        if symbol == "BBB":
            return {
                "breakout": (False, 0.0, [], {}),
                "downtrend": (True, 80.0, ["BBB downtrend"], {"setup_stage": "Downtrend"}),
            }
        return {
            "breakout": (False, 92.0, ["near"], {"setup_stage": "Breakout Setup"}),
            "downtrend": (False, 0.0, [], {}),
        }

    with (
        patch.object(worker, "_prepare_pattern_histories", return_value={symbol: frame for symbol in ("AAA", "BBB", "CCC")}),
        patch.object(worker, "_evaluate_selected_patterns", side_effect=strict_results),
    ):
        strict_pool, strict_status = worker._apply_pattern_analysis(candidates)

    assert [candidate["symbol"] for candidate in strict_pool] == ["BBB", "AAA"]
    assert strict_status["fallback_reason"] == ""
    assert all(candidate["match_tier"] == "strict" for candidate in strict_pool)
    assert all(candidate["pattern_match"] is True for candidate in strict_pool)
    assert strict_pool[0]["matched_modes"] == ["downtrend"]
    assert strict_pool[1]["matched_modes"] == ["breakout"]

    near_worker = RandomStockWorker(pattern_modes=["breakout", "downtrend"])

    def near_results(symbol: str, _frame: object):
        if symbol == "AAA":
            return {
                "breakout": (False, 61.0, ["near breakout"], {"setup_stage": "Breakout Setup"}),
                "downtrend": (False, 0.0, [], {}),
            }
        return {"breakout": (False, 0.0, [], {}), "downtrend": (False, 0.0, [], {})}

    with (
        patch.object(near_worker, "_prepare_pattern_histories", return_value={"AAA": frame, "BBB": frame}),
        patch.object(near_worker, "_evaluate_selected_patterns", side_effect=near_results),
    ):
        near_pool, near_status = near_worker._apply_pattern_analysis(candidates)

    assert [candidate["symbol"] for candidate in near_pool] == ["AAA"]
    assert near_pool[0]["match_tier"] == "near"
    assert near_pool[0]["pattern_match"] is False
    assert near_pool[0]["matched_modes"] == []
    assert near_pool[0]["pattern_type"].startswith("Near ")
    assert near_status["fallback_reason"].startswith("No strict setup matched")

    unavailable_worker = RandomStockWorker(pattern_modes=["breakout"])
    with (
        patch.object(unavailable_worker, "_prepare_pattern_histories", return_value={}),
        patch.object(unavailable_worker, "_evaluate_selected_patterns", return_value={"breakout": (False, 0.0, [], {})}),
    ):
        unavailable_pool, unavailable_status = unavailable_worker._apply_pattern_analysis(candidates[:1])
    assert unavailable_pool[0]["match_tier"] == "unavailable"
    assert unavailable_pool[0]["pattern_match"] is False
    assert unavailable_status["fallback_reason"].startswith("Technical pattern history was unavailable")


def test_fallback_candidates_keep_technical_scores_and_rank_before_general_score() -> None:
    frame = _history_frame()
    candidates = [
        {"symbol": "TECH", "score": 40.0, "rank": 1},
        {"symbol": "GENERAL", "score": 99.0, "rank": 2},
    ]
    worker = RandomStockWorker(pattern_modes=["breakout"])

    def fallback_results(symbol: str, _frame: object):
        score = 49.0 if symbol == "TECH" else 10.0
        return {
            "breakout": (
                False,
                score,
                [f"{symbol} technical evidence"],
                {"setup_stage": "Breakout Setup", "distance_to_resistance_pct": -3.0},
            )
        }

    with (
        patch.object(worker, "_prepare_pattern_histories", return_value={symbol: frame for symbol in ("TECH", "GENERAL")}),
        patch.object(worker, "_evaluate_selected_patterns", side_effect=fallback_results),
    ):
        pool, status = worker._apply_pattern_analysis(candidates)

    assert [candidate["symbol"] for candidate in pool] == ["TECH", "GENERAL"]
    assert [candidate["pattern_score"] for candidate in pool] == [49.0, 10.0]
    assert all(candidate["match_tier"] == "fallback" for candidate in pool)
    assert pool[0]["primary_pattern_mode"] == "breakout"
    assert pool[0]["pattern_type"] == "Breakout Setup"
    assert status["fallback_reason"].startswith("No strong technical setup")


def test_exact_symbol_stages_core_before_optional_failure_and_reuses_chart_frame() -> None:
    worker = RandomStockWorker(target_symbol="AAA", request_id=91)
    frame = worker._normalize_history_frame(_history_frame())
    assert frame is not None
    worker._history_frames["AAA"] = frame
    progress_updates: list[dict[str, object]] = []
    partial_updates: list[dict[str, object]] = []
    worker.progress.connect(progress_updates.append)
    worker.partial.connect(partial_updates.append)
    metadata = {
        "info": {"longName": "AAA Corporation", "currentPrice": 101.0},
        "quote": _quote("AAA"),
        "website": "https://example.test",
        "ir_url": "https://example.test/ir",
    }

    with (
        patch.object(worker, "_query", return_value=object()),
        patch.object(worker, "_screening_snapshot", side_effect=AssertionError("exact-symbol fetch must skip screener")),
        patch.object(worker, "_metadata_patch", return_value=metadata) as load_metadata,
        patch.object(worker, "_load_exact_symbol_history", side_effect=AssertionError("selected chart must reuse scan frame")),
        patch.object(worker, "_news_patch", side_effect=RuntimeError("news unavailable")) as load_news,
        patch.object(worker, "_options_patch", return_value={"top_options": [], "top_options_status": "No options"}),
    ):
        payload = worker.fetch()

    load_metadata.assert_called_once()
    load_news.assert_called_once()
    sections = [str(update["section"]) for update in partial_updates]
    assert sections[0:3] == ["candidates", "core", "metadata"]
    assert sections.index("core") < sections.index("chart")
    assert sections.index("core") < sections.index("news")
    assert sections.index("core") < sections.index("options")
    assert [str(update["stage"]) for update in progress_updates][0] == "screening"
    assert {str(update["stage"]) for update in progress_updates} >= {"screening", "candidates", "core", "enrichment"}
    assert payload["chart_history"]["dates"]
    assert "News data could not be loaded." in payload["warnings"]
    assert payload["fetch_meta"] == worker._fetch_meta
    assert all("quote" not in candidate for candidate in payload["candidate_pool"])
    assert len(json.dumps(payload["candidate_pool"], default=str)) < 250_000


def test_run_emits_cancelled_instead_of_error_or_finished() -> None:
    worker = RandomStockWorker()
    signals = {"cancelled": 0, "error": 0, "finished": 0}
    worker.cancelled.connect(lambda: signals.__setitem__("cancelled", signals["cancelled"] + 1))
    worker.error.connect(lambda _message: signals.__setitem__("error", signals["error"] + 1))
    worker.finished.connect(lambda _payload: signals.__setitem__("finished", signals["finished"] + 1))
    worker.cancel()
    worker.run()
    assert signals == {"cancelled": 1, "error": 0, "finished": 0}


def test_stale_option_chain_requires_fresh_expiry_membership_and_is_labelled() -> None:
    RandomStockWorker.clear_caches()
    worker = RandomStockWorker()
    stale_record = {
        "ticker": "AAA",
        "type": "Call",
        "expiration": "2026-08-21",
        "strike": 100.0,
        "lastPrice": 2.5,
        "volume": 500,
        "openInterest": 1_000,
        "impliedVolatility": 0.25,
    }
    expired_at = time.monotonic() - max(
        worker._OPTION_EXPIRY_CACHE_TTL_SECONDS,
        worker._OPTION_CHAIN_CACHE_TTL_SECONDS,
    ) - 1.0
    with worker._CACHE_LOCK:
        worker._option_expiry_cache["AAA"] = (expired_at, ["2026-07-17", "2026-08-21"])
        worker._option_chain_cache[("AAA", "2026-08-21")] = (expired_at, {"record": stale_record})

    class _Ticker:
        options = ["2026-08-21"]

        @staticmethod
        def option_chain(_expiry: str):
            raise RuntimeError("temporary chain failure")

    records, status = worker._load_top_options(_Ticker(), "AAA")
    assert records == [stale_record]
    assert "stale cached chains" in status
    assert "expirations were revalidated" in status
    assert all(record["expiration"] != "2026-07-17" for record in records)
    RandomStockWorker.clear_caches()


def test_progress_partial_contract_and_cooperative_cancellation() -> None:
    worker = RandomStockWorker(request_id=77)
    progress_updates: list[dict[str, object]] = []
    partial_updates: list[dict[str, object]] = []
    worker.progress.connect(progress_updates.append)
    worker.partial.connect(partial_updates.append)

    worker._emit_progress("history", "Fetching histories", current=2, total=5)
    worker._emit_partial("candidates", {"candidate_pool": [{"symbol": "AAA"}]}, stage="candidates")

    assert progress_updates == [{
        "stage": "history",
        "message": "Fetching histories",
        "current": 2,
        "total": 5,
        "request_id": 77,
    }]
    assert partial_updates == [{
        "section": "candidates",
        "payload": {"candidate_pool": [{"symbol": "AAA"}]},
        "stage": "candidates",
        "request_id": 77,
    }]
    worker.cancel()
    assert worker._is_cancelled()
    try:
        worker._raise_if_cancelled()
    except RuntimeError:
        pass
    else:
        raise AssertionError("cancelled worker did not stop cooperatively")


def test_inflight_screen_cancellation_returns_without_waiting_for_network_tasks() -> None:
    worker = RandomStockWorker()
    gate = threading.Event()

    def blocked_screen(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        gate.wait(1.0)
        return []

    cancel_timer = threading.Timer(0.03, worker.cancel)
    started_at = time.monotonic()
    cancel_timer.start()
    try:
        with patch.object(worker, "_screen_quotes", side_effect=blocked_screen):
            try:
                worker._fetch_screen_buckets(object(), 500)
            except RuntimeError:
                pass
            else:
                raise AssertionError("in-flight cancellation did not stop the screening stage")
    finally:
        elapsed = time.monotonic() - started_at
        gate.set()
        cancel_timer.join(timeout=1.0)
    assert elapsed < 0.3

    direct_worker = RandomStockWorker()
    direct_gate = threading.Event()
    direct_timer = threading.Timer(0.03, direct_worker.cancel)
    direct_started_at = time.monotonic()
    direct_timer.start()
    try:
        with patch.object(direct_worker, "_screen_total", side_effect=lambda _query: direct_gate.wait(1.0)):
            try:
                direct_worker._screening_snapshot(object())
            except RuntimeError:
                pass
            else:
                raise AssertionError("direct screening cancellation did not stop the worker")
    finally:
        direct_elapsed = time.monotonic() - direct_started_at
        direct_gate.set()
        direct_timer.join(timeout=1.0)
    assert direct_elapsed < 0.3


def test_no_pattern_warm_roll_prefetches_every_candidate_history() -> None:
    RandomStockWorker.clear_caches()
    candidates = [
        {
            "symbol": symbol,
            "name": f"{symbol} Corporation",
            "sector": "Technology",
            "score": score,
            "reasons": ["liquid"],
            "rank": index,
            "quote": _quote(symbol, score_seed=index),
        }
        for index, (symbol, score) in enumerate((("AAA", 90.0), ("BBB", 80.0), ("CCC", 70.0)), start=1)
    ]
    batch = pd.concat(
        {candidate["symbol"]: _history_frame(base=90.0 + index * 10.0) for index, candidate in enumerate(candidates)},
        axis=1,
    )
    metadata = {
        "info": {"longName": "Candidate Corporation", "currentPrice": 101.0},
        "quote": _quote("AAA"),
        "website": "",
        "ir_url": "",
    }

    def run_roll(
        selected_index: int,
        *,
        download: object,
    ) -> tuple[RandomStockWorker, dict[str, object], list[str]]:
        worker = RandomStockWorker()
        fresh_candidates = [dict(candidate, quote=dict(candidate["quote"])) for candidate in candidates]
        sections: list[str] = []
        worker.partial.connect(lambda update: sections.append(str(update.get("section") or "")))
        with (
            patch.object(worker, "_query", return_value=object()),
            patch.object(worker, "_screening_snapshot", return_value=(500, {})),
            patch.object(worker, "_build_candidate_pool", return_value=fresh_candidates),
            patch.object(worker, "_select_candidate", side_effect=lambda pool: pool[selected_index]),
            patch.object(worker, "_download_pattern_history", side_effect=download),
            patch.object(worker, "_metadata_patch", return_value=metadata),
            patch.object(worker, "_news_patch", return_value={"news": []}),
            patch.object(worker, "_options_patch", return_value={"top_options": [], "top_options_status": ""}),
        ):
            return worker, worker.fetch(), sections

    cold_calls = 0

    def cold_download(_symbols: list[str]):
        nonlocal cold_calls
        cold_calls += 1
        return batch

    cold_worker, cold_payload, cold_sections = run_roll(0, download=cold_download)
    assert cold_payload["symbol"] == "AAA"
    assert cold_calls == 1
    assert cold_worker._fetch_meta["history_downloaded"] == 3
    assert cold_sections.index("candidates") < cold_sections.index("core") < cold_sections.index("chart")

    warm_worker, warm_payload, warm_sections = run_roll(
        1,
        download=AssertionError("warm same-filter roll must not download candidate history"),
    )
    assert warm_payload["symbol"] == "BBB"
    assert warm_worker._fetch_meta["history_cache_hits"] == 3
    assert warm_worker._fetch_meta["history_downloaded"] == 0
    assert warm_sections.index("candidates") < warm_sections.index("core") < warm_sections.index("chart")
    RandomStockWorker.clear_caches()


def test_optional_failures_are_labelled_and_expired_cache_entries_are_pruned() -> None:
    worker = RandomStockWorker()

    class _BrokenTicker:
        @property
        def info(self):
            raise RuntimeError("metadata unavailable")

        @property
        def news(self):
            raise RuntimeError("news unavailable")

    info, metadata_warning = worker._load_info(_BrokenTicker(), "AAA", _quote("AAA"))
    articles, news_warning = worker._load_news(_BrokenTicker(), "AAA")
    assert info["longName"] == "AAA Corporation"
    assert "using screener quote data" in metadata_warning
    assert articles == []
    assert "Recent headlines could not be loaded" in news_warning

    class _EmptyTicker:
        info: dict[str, object] = {}

    _info, empty_warning = worker._load_info(_EmptyTicker(), "AAA", _quote("AAA"))
    assert "returned no usable data" in empty_warning

    expired_at = time.monotonic() - worker._HISTORY_CACHE_TTL_SECONDS - 1.0
    with worker._CACHE_LOCK:
        worker._history_cache["EXPIRED"] = (expired_at, _history_frame())
    worker._cache_put(worker._history_cache, "FRESH", _history_frame(base=120.0))
    with worker._CACHE_LOCK:
        assert "EXPIRED" not in worker._history_cache
        assert "FRESH" in worker._history_cache
    RandomStockWorker.clear_caches()


def main() -> None:
    test_history_normalization_retains_open_adjusts_and_drops_live_bar()
    test_breakout_consolidation_and_downtrend_positive_patterns()
    test_pattern_history_threshold_and_nan_rows_fail_safely()
    test_screen_buckets_are_unique_bounded_and_round_robin_keeps_losers()
    test_history_retry_is_one_bounded_batch_and_warm_load_uses_cache()
    test_screening_snapshot_and_selected_evaluations_use_ten_minute_caches()
    test_or_matching_uses_strict_only_and_near_fallback_is_labelled()
    test_fallback_candidates_keep_technical_scores_and_rank_before_general_score()
    test_exact_symbol_stages_core_before_optional_failure_and_reuses_chart_frame()
    test_run_emits_cancelled_instead_of_error_or_finished()
    test_stale_option_chain_requires_fresh_expiry_membership_and_is_labelled()
    test_progress_partial_contract_and_cooperative_cancellation()
    test_inflight_screen_cancellation_returns_without_waiting_for_network_tasks()
    test_no_pattern_warm_roll_prefetches_every_candidate_history()
    test_optional_failures_are_labelled_and_expired_cache_entries_are_pruned()
    print("Roll pipeline tests passed.")


if __name__ == "__main__":
    main()
