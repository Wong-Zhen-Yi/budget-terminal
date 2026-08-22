from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from budget_terminal_app.mixins import quant_presenters as presenters
from budget_terminal_app.services.quant import (
    DICKEY_FULLER_CRITICAL_VALUES,
    QuantAnalyticsService,
    QuantPairRow,
    QuantScanPayload,
    QuantScreenRow,
    build_pair_spread,
    discover_pairs,
    hurst_exponent,
    mean_reversion_stats,
    ordinary_least_squares,
    rank_screen_rows,
    score_pair,
    screen_metrics,
)

COLORS = {
    "positive": "#00aa00",
    "negative": "#aa0000",
    "warning": "#aaaa00",
    "secondary": "#888888",
    "accent": "#0088ff",
}


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2022-01-03", periods=len(values), freq="B")
    return pd.Series(values, index=index)


def _random_walk(count: int, start: float, rng: random.Random, sigma: float = 0.012) -> list[float]:
    values = [start]
    for _ in range(count - 1):
        values.append(values[-1] * (1.0 + rng.gauss(0.0, sigma)))
    return values


def _cointegrated_pair(count: int, rng: random.Random) -> tuple[list[float], list[float]]:
    """Build a pair whose spread is a stationary AR(1) around a fixed hedge ratio of 2.0."""

    right = _random_walk(count, 100.0, rng)
    wobble = 0.0
    left = []
    for price in right:
        wobble = 0.85 * wobble + rng.gauss(0.0, 1.0)
        left.append(2.0 * price + wobble)
    return left, right


def test_ordinary_least_squares() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    fit = ordinary_least_squares(3.0 + 2.0 * x, x)
    assert fit is not None
    assert math.isclose(fit["beta"], 2.0, abs_tol=1e-9)
    assert math.isclose(fit["alpha"], 3.0, abs_tol=1e-9)
    assert fit["observations"] == 5
    # A perfect fit has no residual variance, so no standard error is claimed.
    assert fit["std_error"] is None
    assert fit["t_statistic"] is None

    # A constant regressor has no slope to estimate.
    assert ordinary_least_squares(x, pd.Series([1.0] * 5)) is None
    assert ordinary_least_squares(pd.Series([1.0]), pd.Series([1.0])) is None


def test_cointegrated_pair_is_detected() -> None:
    rng = random.Random(7)
    left, right = _cointegrated_pair(500, rng)
    info = build_pair_spread(_series(left), _series(right))

    # The hedge ratio recovers the construction constant.
    assert info["hedge_ratio"] is not None
    assert abs(info["hedge_ratio"] - 2.0) < 0.1
    assert info["observations"] == 500

    reversion = mean_reversion_stats(info["spread"])
    assert reversion["half_life"] is not None
    assert 0.0 < reversion["half_life"] < 30.0
    assert reversion["dickey_fuller"] < DICKEY_FULLER_CRITICAL_VALUES["5%"]
    assert reversion["stationary_at"] in {"1%", "5%"}

    hurst = hurst_exponent(info["spread"])
    assert hurst is not None and hurst < 0.45


def test_random_walk_pair_is_rejected() -> None:
    rng = random.Random(11)
    left = _random_walk(500, 100.0, rng)
    right = _random_walk(500, 50.0, rng)
    info = build_pair_spread(_series(left), _series(right))
    reversion = mean_reversion_stats(info["spread"])

    # Two independent random walks must not read as a stationary spread.
    assert reversion["dickey_fuller"] > DICKEY_FULLER_CRITICAL_VALUES["5%"]
    assert reversion["stationary_at"] == ""

    # The Hurst estimator carries a well-known finite-sample downward bias: at 500 points with
    # lags to 20, even a genuine random walk estimates nearer 0.45 than 0.50. So the meaningful
    # check is separation from the cointegrated case, not an absolute threshold.
    rng_pair = random.Random(7)
    cointegrated_left, cointegrated_right = _cointegrated_pair(500, rng_pair)
    cointegrated_spread = build_pair_spread(_series(cointegrated_left), _series(cointegrated_right))["spread"]
    walk_hurst = hurst_exponent(info["spread"])
    cointegrated_hurst = hurst_exponent(cointegrated_spread)
    assert walk_hurst is not None and cointegrated_hurst is not None
    assert cointegrated_hurst < 0.3 < walk_hurst
    assert walk_hurst - cointegrated_hurst > 0.1

    # Too little overlapping history yields no fit rather than a spurious one.
    short = build_pair_spread(_series(left[:30]), _series(right[:30]))
    assert short["hedge_ratio"] is None
    assert short["spread"].empty
    assert mean_reversion_stats(short["spread"])["half_life"] is None


def test_discover_pairs_ranks_the_real_pair_first() -> None:
    rng = random.Random(7)
    left, right = _cointegrated_pair(500, rng)
    unrelated = _random_walk(500, 50.0, rng)
    pairs = discover_pairs(
        {"AAA": _series(left), "BBB": _series(right), "CCC": _series(unrelated)}
    )
    assert pairs, "expected at least one scored pair"
    assert pairs[0].rank == 1
    assert {pairs[0].left, pairs[0].right} == {"AAA", "BBB"}
    assert pairs[0].score > 60.0
    # Ranks are dense and ordered, and no spurious pair outscores the constructed one.
    assert [row.rank for row in pairs] == list(range(1, len(pairs) + 1))
    assert all(pairs[0].score > row.score for row in pairs[1:])

    # Fewer than two usable series cannot produce a pair.
    assert discover_pairs({"AAA": _series(left)}) == []
    assert discover_pairs({"AAA": _series(left[:10]), "BBB": _series(right[:10])}) == []


def test_score_pair_requires_correlation_and_half_life() -> None:
    assert score_pair({"correlation": None, "half_life": 10.0}) is None
    assert score_pair({"correlation": 0.9, "half_life": None}) is None
    fast = score_pair({"correlation": 0.9, "half_life": 10.0, "dickey_fuller": -4.0, "hurst": 0.2})
    slow = score_pair({"correlation": 0.9, "half_life": 400.0, "dickey_fuller": -1.0, "hurst": 0.6})
    assert fast is not None and slow is not None
    assert fast > slow


def _frame(values: list[float]) -> pd.DataFrame:
    index = pd.date_range("2022-01-03", periods=len(values), freq="B")
    return pd.DataFrame({"Close": values, "Volume": [1_000_000] * len(values)}, index=index)


def test_screen_metrics_on_a_monotonic_riser() -> None:
    # A steady 0.1%/session riser: momentum positive, no drawdown, effectively no volatility.
    values = [100.0 * (1.001 ** step) for step in range(400)]
    metrics = screen_metrics(_frame(values))
    assert metrics["observations"] == 400
    assert math.isclose(metrics["last_price"], values[-1], rel_tol=1e-9)
    assert metrics["momentum_1m"] > 0.0
    assert metrics["momentum_12m"] > metrics["momentum_1m"]
    assert math.isclose(metrics["max_drawdown_pct"], 0.0, abs_tol=1e-9)
    assert metrics["volatility_pct"] < 1e-6
    assert metrics["z_score"] is not None
    assert metrics["median_dollar_volume"] > 0.0

    # A series that never falls has no average loss, so services.technical_analysis.calculate_rsi
    # yields an all-NaN series. Reporting that as absent is correct; inventing an RSI is not.
    assert metrics["rsi"] is None


def test_screen_metrics_on_a_realistic_series() -> None:
    rng = random.Random(3)
    values = _random_walk(400, 100.0, rng, sigma=0.015)
    metrics = screen_metrics(_frame(values))
    assert metrics["observations"] == 400
    assert metrics["rsi"] is not None and 0.0 <= metrics["rsi"] <= 100.0
    assert metrics["volatility_pct"] > 0.0
    assert metrics["sharpe"] is not None and math.isfinite(metrics["sharpe"])
    # A real path drops below its own running peak at some point.
    assert metrics["max_drawdown_pct"] < 0.0

    # A frame with no usable close must not raise.
    empty = screen_metrics(pd.DataFrame())
    assert empty["observations"] == 0
    assert empty["last_price"] is None
    assert empty["rsi"] is None

    # Too little history leaves the long lookbacks absent rather than wrong.
    short = screen_metrics(_frame(values[:30]))
    assert short["momentum_12m"] is None
    assert short["momentum_6m"] is None
    assert short["last_price"] is not None


def test_rank_screen_rows() -> None:
    rows = [
        QuantScreenRow(ticker="AAA", momentum_3m=10.0, momentum_6m=20.0, momentum_12m=30.0, sharpe=1.5,
                       volatility_pct=20.0),
        QuantScreenRow(ticker="BBB", momentum_3m=-5.0, momentum_6m=0.0, momentum_12m=5.0, sharpe=0.2,
                       volatility_pct=45.0),
        QuantScreenRow(ticker="CCC", momentum_3m=3.0, sharpe=None, volatility_pct=30.0),
    ]
    ranked = rank_screen_rows(rows)
    assert [row.rank for row in ranked] == [1, 2, 3]
    assert ranked[0].ticker == "AAA"
    assert ranked[0].composite == 100.0
    # A row missing a factor still scores, on the factors it does have.
    missing = next(row for row in ranked if row.ticker == "CCC")
    assert missing.composite is not None
    assert rank_screen_rows([]) == []


def test_payload_round_trip() -> None:
    payload = QuantScanPayload(
        rows=[QuantScreenRow(ticker="AAA", composite=91.5, rank=1)],
        pairs=[QuantPairRow(left="AAA", right="BBB", score=70.0, rank=1, stationary_at="5%")],
        universe_size=25,
        errors={"ZZZ": "no history"},
    )
    restored = QuantAnalyticsService.payload_from_dict(QuantAnalyticsService.payload_to_dict(payload))
    assert [row.ticker for row in restored.rows] == ["AAA"]
    assert restored.rows[0].composite == 91.5
    assert restored.pairs[0].stationary_at == "5%"
    assert restored.universe_size == 25
    assert restored.errors == {"ZZZ": "no history"}


def test_presenter_rows_always_carry_finite_sort_values() -> None:
    # Every cell in a sortable column needs a finite sort payload: one None silently downgrades
    # that whole column to string comparison in widgets/table_render.
    rows = [
        QuantScreenRow(ticker="AAA", last_price=10.0, momentum_1m=5.0, sharpe=1.0, rsi=70.0, composite=90.0, rank=1),
        QuantScreenRow(ticker="BBB"),
    ]
    for row in rows:
        cells = presenters.build_screen_row(row, colors=COLORS, ticker_role=1000)
        assert len(cells) == len(presenters.SCREEN_HEADERS)
        for cell in cells[2:]:
            assert cell.sort_value is not None
            assert not math.isnan(float(cell.sort_value))

    pair_rows = [
        QuantPairRow(left="AAA", right="BBB", correlation=0.9, hedge_ratio=2.0, spread_z=-2.4,
                     half_life=8.0, hurst=0.3, dickey_fuller=-4.1, stationary_at="1%", score=80.0, rank=1),
        QuantPairRow(left="CCC", right="DDD"),
    ]
    for row in pair_rows:
        cells = presenters.build_pair_row(row, colors=COLORS, pair_role=1001)
        assert len(cells) == len(presenters.PAIR_HEADERS)
        for cell in cells[3:]:
            assert cell.sort_value is not None
            assert not math.isnan(float(cell.sort_value))

    # The pair payload rides on its own role so it cannot collide with the sort role.
    first = presenters.build_pair_row(pair_rows[0], colors=COLORS, pair_role=1001)
    assert first[1].data_roles == ((1001, "AAA/BBB"),)


def test_llm_export_matches_the_visible_rows() -> None:
    rows = [
        QuantScreenRow(ticker="AAA", rank=1, last_price=101.5, composite=90.0, momentum_6m=12.0, rsi=70.0),
        QuantScreenRow(ticker="BBB", rank=2, last_price=20.0, composite=40.0, momentum_6m=-3.0, rsi=30.0),
    ]
    pairs = [QuantPairRow(left="AAA", right="BBB", rank=1, stationary_at="1%", spread_z=2.5, half_life=5.0)]
    payload = QuantScanPayload(rows=list(rows), pairs=list(pairs), universe_size=9, errors={"ZZZ": "no history"})

    # An empty payload must still produce something safe to paste.
    empty = presenters.build_llm_export(None, screen_rows=[], pair_rows=[])
    assert "No scan has been run yet" in empty

    export = presenters.build_llm_export(
        payload,
        screen_rows=rows[:1],
        pair_rows=list(pairs),
        screen_filter_label="Top quartile",
        search="aaa",
        pair_detail={"left": "AAA", "right": "BBB", "hedge_ratio": 2.0, "observations": 300},
    )
    # The export follows the filtered view, not the full payload.
    assert "| AAA |" in export and "| BBB |" not in export.split("## Pairs")[0]
    assert "1 of 2 rows shown" in export
    assert "Filter: Top quartile" in export and "ticker search: AAA" in export
    assert "## Inspected pair" in export and "long AAA / short BBB" in export
    assert "ZZZ: no history" in export
    # Pipes in free text would break the markdown tables.
    piped = presenters.build_llm_export(
        payload,
        screen_rows=[QuantScreenRow(ticker="A|B", rank=1)],
        pair_rows=[],
    )
    assert "| A/B |" in piped


def test_presenter_filters_and_summaries() -> None:
    rows = [
        QuantScreenRow(ticker="AAA", composite=90.0, momentum_6m=12.0, rsi=70.0, volatility_pct=15.0),
        QuantScreenRow(ticker="BBB", composite=40.0, momentum_6m=-3.0, rsi=30.0, volatility_pct=60.0),
        QuantScreenRow(ticker="CCC", composite=None, momentum_6m=None, rsi=None, volatility_pct=None),
    ]
    assert [row.ticker for row in presenters.filter_screen_rows(rows, "top_quartile")] == ["AAA"]
    assert [row.ticker for row in presenters.filter_screen_rows(rows, "momentum")] == ["AAA"]
    assert [row.ticker for row in presenters.filter_screen_rows(rows, "oversold")] == ["BBB"]
    assert [row.ticker for row in presenters.filter_screen_rows(rows, "overbought")] == ["AAA"]
    assert len(presenters.filter_screen_rows(rows, "all")) == 3

    pairs = [
        QuantPairRow(left="A", right="B", stationary_at="1%", spread_z=2.5, half_life=5.0),
        QuantPairRow(left="C", right="D", stationary_at="", spread_z=0.1, half_life=90.0),
    ]
    assert len(presenters.filter_pair_rows(pairs, "stationary")) == 1
    assert len(presenters.filter_pair_rows(pairs, "stretched")) == 1
    assert len(presenters.filter_pair_rows(pairs, "fast")) == 1
    assert len(presenters.filter_pair_rows(pairs, "all")) == 2

    text, status = presenters.describe_scan_freshness(None)
    assert status == "muted"
    payload = QuantScanPayload(rows=list(rows), pairs=list(pairs), universe_size=9)
    text, status = presenters.describe_scan_freshness(payload)
    assert status == "positive" and "3 ranked" in text
    metrics = presenters.summarize_metrics(payload)
    assert metrics["ranked"] == "3" and metrics["pairs"] == "2" and metrics["universe"] == "9"

    # The stationarity wording must never imply a p-value we cannot compute.
    described = presenters.describe_dickey_fuller(-4.0, "1%")
    assert "no lags" in described and "p-value" not in described.lower()
    assert "not enough history" in presenters.describe_dickey_fuller(None, "")


if __name__ == "__main__":
    test_ordinary_least_squares()
    test_cointegrated_pair_is_detected()
    test_random_walk_pair_is_rejected()
    test_discover_pairs_ranks_the_real_pair_first()
    test_score_pair_requires_correlation_and_half_life()
    test_screen_metrics_on_a_monotonic_riser()
    test_screen_metrics_on_a_realistic_series()
    test_rank_screen_rows()
    test_payload_round_trip()
    test_presenter_rows_always_carry_finite_sort_values()
    test_presenter_filters_and_summaries()
    test_llm_export_matches_the_visible_rows()
    print("quant analytics tests passed")
