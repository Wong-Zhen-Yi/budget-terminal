from __future__ import annotations

import sys
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

    assert len(fallback_calls) == worker._QUOTE_FALLBACK_LIMIT
    assert len(quotes) == worker._QUOTE_FALLBACK_LIMIT


if __name__ == "__main__":
    test_quote_cache_reuses_overlapping_holdings()
    test_fallback_work_is_bounded()
    print("ETF heatmap worker tests passed")
