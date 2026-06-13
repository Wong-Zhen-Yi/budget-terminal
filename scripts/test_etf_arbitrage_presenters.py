from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.services.etf_arbitrage import build_etf_arbitrage_snapshot


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _holding(symbol: str, weight: float, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, name=name, weight=weight)


def _quote(price: float, move_pct: float) -> dict[str, object]:
    return {"price": price, "change_pct": move_pct, "changes": {"live": move_pct, "1d": move_pct}}


def _close(left: float | None, right: float, message: str, tolerance: float = 0.000001) -> None:
    _assert(left is not None and abs(float(left) - right) <= tolerance, message)


def test_empty_holdings() -> None:
    payload = build_etf_arbitrage_snapshot("SPY", [], {"SPY": _quote(500.0, 1.0)})
    _assert(payload["rows"] == [], "empty holdings should produce no component rows")
    _assert(payload["quote_coverage"] == 0, "empty holdings should have zero component quote coverage")
    _assert(payload["total_holdings"] == 0, "empty holdings should preserve zero total holdings")
    _assert(payload["basket_move_pct"] is None, "empty holdings should not invent a basket move")
    _assert(payload["gap_bps"] is None, "empty holdings should not invent a gap")
    _assert(payload["signal"] == "--", "empty holdings should use placeholder signal")


def test_missing_etf_quote_preserves_basket_move() -> None:
    payload = build_etf_arbitrage_snapshot(
        "SPY",
        [_holding("AAA", 0.6), _holding("BBB", 0.4)],
        {"AAA": _quote(10.0, 2.0), "BBB": _quote(20.0, -1.0)},
    )
    _close(payload["basket_move_pct"], 0.8, "basket move should normalize quoted weights")
    _assert(payload["etf_move_pct"] is None, "missing ETF quote should leave ETF move blank")
    _assert(payload["gap_bps"] is None, "missing ETF quote should leave gap blank")
    _assert(payload["signal"] == "--", "missing ETF quote should use placeholder signal")


def test_partial_coverage_weights_and_contributions() -> None:
    payload = build_etf_arbitrage_snapshot(
        "SPY",
        [_holding("AAA", 0.6), _holding("BBB", 0.4), _holding("CCC", 0.2)],
        {"SPY": _quote(500.0, 1.0), "AAA": _quote(10.0, 2.0), "BBB": _quote(20.0, -1.0)},
    )
    rows = {row["symbol"]: row for row in payload["rows"]}
    _assert(payload["quote_coverage"] == 2, "partial coverage should count quoted holdings")
    _assert(payload["total_holdings"] == 3, "partial coverage should preserve positive-weight holdings count")
    _close(payload["quoted_weight"], 1.0, "quoted raw weight should sum only available quotes")
    _close(payload["basket_move_pct"], 0.8, "basket move should use quoted-weight normalization")
    _close(rows["AAA"]["normalized_weight"], 0.6, "AAA normalized weight should be 60%")
    _close(rows["AAA"]["contribution_pct"], 1.2, "AAA contribution should be weighted move")
    _close(rows["BBB"]["normalized_weight"], 0.4, "BBB normalized weight should be 40%")
    _close(rows["BBB"]["contribution_pct"], -0.4, "BBB contribution should be weighted move")


def test_gap_signal_signs() -> None:
    holdings = [_holding("AAA", 0.5), _holding("BBB", 0.5)]
    quotes = {"AAA": _quote(10.0, 1.0), "BBB": _quote(20.0, -1.0), "SPY": _quote(500.0, 0.0)}
    flat = build_etf_arbitrage_snapshot("SPY", holdings, quotes)
    _close(flat["basket_move_pct"], 0.0, "flat basket should calculate to zero")
    _close(flat["gap_bps"], 0.0, "flat ETF-vs-basket should have zero bps gap")
    _assert(flat["signal"] == "No gap", "flat gap should be labelled No gap")

    rich = build_etf_arbitrage_snapshot(
        "SPY",
        holdings,
        {"AAA": _quote(10.0, 2.0), "BBB": _quote(20.0, -1.0), "SPY": _quote(500.0, 1.0)},
    )
    _close(rich["basket_move_pct"], 0.5, "rich fixture basket move should be 0.5%")
    _close(rich["gap_bps"], 50.0, "positive 0.5 percentage-point gap should be 50 bps")
    _assert(rich["signal"] == "ETF rich vs basket", "positive gap should label ETF rich")

    cheap = build_etf_arbitrage_snapshot(
        "SPY",
        holdings,
        {"AAA": _quote(10.0, 2.0), "BBB": _quote(20.0, -1.0), "SPY": _quote(500.0, 0.25)},
    )
    _close(cheap["gap_bps"], -25.0, "negative 0.25 percentage-point gap should be -25 bps")
    _assert(cheap["signal"] == "ETF cheap vs basket", "negative gap should label ETF cheap")


def main() -> None:
    test_empty_holdings()
    test_missing_etf_quote_preserves_basket_move()
    test_partial_coverage_weights_and_contributions()
    test_gap_signal_signs()
    print("ETF arbitrage presenter smoke tests passed")


if __name__ == "__main__":
    main()
