from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.valuation import _peer_symbols


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_semiconductor_peers_are_close() -> None:
    symbols = _peer_symbols(
        "NVDA",
        {"industry": "Semiconductors", "sector": "Technology", "marketCap": 3_000_000_000_000},
    )
    _assert(symbols[0] == "NVDA", "current ticker should be first")
    _assert(symbols[1:3] == ["AMD", "AVGO"], f"NVDA should prefer semiconductor peers, got {symbols}")
    _assert("MSFT" not in symbols[1:], f"NVDA peer set should not fall back to broad tech too early: {symbols}")


def test_bank_peers_are_financials() -> None:
    symbols = _peer_symbols(
        "JPM",
        {"industry": "Banks - Diversified", "sector": "Financial Services", "marketCap": 700_000_000_000},
    )
    _assert(symbols[0] == "JPM", "current ticker should be first")
    _assert({"BAC", "WFC"}.issubset(set(symbols[1:])), f"JPM should prefer bank peers, got {symbols}")
    _assert(not {"MSFT", "AAPL", "GOOGL", "AMZN"} & set(symbols[1:]), f"JPM should not use tech defaults, got {symbols}")


def test_unknown_ticker_uses_stable_default() -> None:
    symbols = _peer_symbols("ZZZZ", {"industry": "", "sector": ""})
    _assert(symbols == ["ZZZZ", "MSFT", "AAPL", "GOOGL", "AMZN"], f"unknown fallback changed: {symbols}")


def test_current_ticker_is_not_duplicated() -> None:
    symbols = _peer_symbols("MSFT", {"industry": "Software - Infrastructure", "sector": "Technology"})
    _assert(symbols[0] == "MSFT", "current ticker should remain the anchor row")
    _assert(symbols.count("MSFT") == 1, f"current ticker should not be duplicated: {symbols}")
    _assert(len(symbols) == len(set(symbols)), f"peer symbols should be deduped: {symbols}")


def test_custom_peers_are_pinned_after_anchor() -> None:
    symbols = _peer_symbols(
        "NVDA",
        {"industry": "Semiconductors", "sector": "Technology", "marketCap": 3_000_000_000_000},
        custom_peers=["MSFT", "AMD"],
    )
    _assert(symbols[:3] == ["NVDA", "MSFT", "AMD"], f"custom peers should be pinned after anchor, got {symbols}")
    _assert("AVGO" in symbols[3:], f"automatic peers should still fill after custom peers, got {symbols}")


def test_custom_peers_are_deduped_and_exclude_anchor() -> None:
    symbols = _peer_symbols(
        "NVDA",
        {"industry": "Semiconductors", "sector": "Technology", "marketCap": 3_000_000_000_000},
        custom_peers=["NVDA", "AMD", "AMD", ""],
    )
    _assert(symbols[:2] == ["NVDA", "AMD"], f"custom peer dedupe/exclusion failed: {symbols}")
    _assert(symbols.count("NVDA") == 1, f"anchor ticker should not be duplicated: {symbols}")
    _assert(symbols.count("AMD") == 1, f"custom ticker should not be duplicated: {symbols}")


def main() -> None:
    test_semiconductor_peers_are_close()
    test_bank_peers_are_financials()
    test_unknown_ticker_uses_stable_default()
    test_current_ticker_is_not_duplicated()
    test_custom_peers_are_pinned_after_anchor()
    test_custom_peers_are_deduped_and_exclude_anchor()
    print("valuation peer selection tests passed")


if __name__ == "__main__":
    main()
