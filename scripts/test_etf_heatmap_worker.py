from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import budget_terminal_app.workers.etf_heatmap as heatmap_module
from budget_terminal_app.workers.etf_heatmap import EtfHeatmapWorker


def _batch(symbols: list[str]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=260)
    frames = {
        symbol: pd.DataFrame({"Close": range(100, 360)}, index=dates)
        for symbol in symbols
    }
    return pd.concat(frames, axis=1)


def test_quote_cache_reuses_overlapping_holdings() -> None:
    EtfHeatmapWorker._QUOTE_CACHE = {}
    calls: list[list[str]] = []
    original_download = heatmap_module.yf.download

    def fake_download(symbols, **_kwargs):
        requested = [symbols] if isinstance(symbols, str) else list(symbols)
        calls.append(requested)
        return _batch(requested)

    heatmap_module.yf.download = fake_download
    try:
        worker = EtfHeatmapWorker()
        first = worker._fetch_quotes(["AAPL", "MSFT"])
        second = EtfHeatmapWorker()._fetch_quotes(["AAPL"])
    finally:
        heatmap_module.yf.download = original_download
        EtfHeatmapWorker._QUOTE_CACHE = {}

    assert set(first) == {"AAPL", "MSFT"}
    assert set(second) == {"AAPL"}
    assert calls == [["AAPL", "MSFT"]]


def test_fallback_work_is_bounded() -> None:
    EtfHeatmapWorker._QUOTE_CACHE = {}
    original_download = heatmap_module.yf.download
    heatmap_module.yf.download = lambda *_args, **_kwargs: pd.DataFrame()
    worker = EtfHeatmapWorker()
    fallback_calls: list[str] = []

    def fake_fallback(symbol: str, _yahoo_symbol: str):
        fallback_calls.append(symbol)
        return symbol, {"price": 1.0, "change_pct": 0.0, "changes": {"live": 0.0}}

    worker._fetch_quote_fallback = fake_fallback
    symbols = [f"T{index:02d}" for index in range(20)]
    try:
        quotes = worker._fetch_quotes(symbols)
    finally:
        heatmap_module.yf.download = original_download
        EtfHeatmapWorker._QUOTE_CACHE = {}

    # Small universes stay on the flat floor.
    expected = worker._fallback_budget(len(symbols))
    assert expected == worker._QUOTE_FALLBACK_LIMIT
    assert len(fallback_calls) == expected
    assert len(quotes) == expected


def test_fallback_budget_scales_with_the_universe() -> None:
    """A flat 12 pinned SPY's recovery at 2% of its holdings, leaving the heatmap mostly blank."""
    worker = EtfHeatmapWorker()
    assert worker._fallback_budget(30) == worker._QUOTE_FALLBACK_LIMIT
    assert worker._fallback_budget(503) > worker._QUOTE_FALLBACK_LIMIT
    assert worker._fallback_budget(503) <= worker._QUOTE_FALLBACK_CEILING
    # Still bounded: a total outage must not become one request per holding through the rate gate.
    assert worker._fallback_budget(100000) == worker._QUOTE_FALLBACK_CEILING


def test_cache_hits_do_not_have_their_ttl_refreshed() -> None:
    """Re-stamping cache hits kept a price alive for the life of the process, frozen at first load."""
    EtfHeatmapWorker._QUOTE_CACHE = {}
    original_download = heatmap_module.yf.download
    heatmap_module.yf.download = lambda symbols, **_kwargs: _batch(
        [symbols] if isinstance(symbols, str) else list(symbols)
    )
    try:
        EtfHeatmapWorker()._fetch_quotes(["AAPL"])
        stamped_at = EtfHeatmapWorker._QUOTE_CACHE["AAPL"][0]
        time.sleep(0.05)
        EtfHeatmapWorker()._fetch_quotes(["AAPL"])
        assert EtfHeatmapWorker._QUOTE_CACHE["AAPL"][0] == stamped_at, (
            "a cache hit must keep its original timestamp so the entry can actually expire"
        )
    finally:
        heatmap_module.yf.download = original_download
        EtfHeatmapWorker._QUOTE_CACHE = {}


def test_issuer_placeholder_rows_are_rejected() -> None:
    """SSGA's SPY file carries a '-' cash line and Bloomberg placeholders for unlisted holdings."""
    for good in ("AAPL", "BRK.B", "BF.B", "BRK-B", "A"):
        assert EtfHeatmapWorker._is_usable_symbol(good), good
    for bad in ("2602335D", "-", "--", "", "1234", "   "):
        assert not EtfHeatmapWorker._is_usable_symbol(bad), bad


def test_sector_map_labels_without_dropping_holdings() -> None:
    """The wiki sector map must label holdings, not filter them: a lagging scrape hid real names."""
    worker = EtfHeatmapWorker()
    sector_map = {"AAPL": "Information Technology"}
    assert worker._resolve_sector("AAPL", "", sector_map) == "Information Technology"
    assert worker._resolve_sector("NEWLY", "", sector_map) == "Unclassified"
    # An issuer-supplied sector always wins over the scrape.
    assert worker._resolve_sector("AAPL", "Technology", sector_map) == "Technology"


if __name__ == "__main__":
    test_quote_cache_reuses_overlapping_holdings()
    test_fallback_work_is_bounded()
    test_fallback_budget_scales_with_the_universe()
    test_cache_hits_do_not_have_their_ttl_refreshed()
    test_issuer_placeholder_rows_are_rejected()
    test_sector_map_labels_without_dropping_holdings()
    print("ETF heatmap worker tests passed")
