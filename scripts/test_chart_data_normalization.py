from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.services.chart_data import ChartDataService
from budget_terminal_app.services.technical_analysis import calculate_rsi


def _service(temp_dir: str) -> ChartDataService:
    return ChartDataService(cache_manager=CacheManager(Path(temp_dir) / "chart-normalization.db"))


def _values() -> dict[str, list[float]]:
    return {
        "Open": [10, 11, 12, 13, 14],
        "High": [11, 12, 13, 14, 15],
        "Low": [9, 10, 11, 12, 13],
        "Close": [10.5, 11.5, 12.5, 13.5, 14.5],
        "Volume": [100, 110, 120, 130, 140],
    }


def test_field_first_and_duplicate_close_are_one_dimensional() -> None:
    dates = pd.date_range("2026-08-03", periods=5)
    values = _values()
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "PLTR"),
            ("High", "PLTR"),
            ("Low", "PLTR"),
            ("Close", "PLTR"),
            ("Close", "PLTR"),
            ("Volume", "PLTR"),
        ],
        names=["Price", "Ticker"],
    )
    raw = pd.DataFrame(
        list(
            zip(
                values["Open"],
                values["High"],
                values["Low"],
                values["Close"],
                [None, 11.5, 12.5, 13.5, 14.5],
                values["Volume"],
            )
        ),
        index=dates,
        columns=columns,
    )
    assert raw["Close"].shape == (5, 2)

    with tempfile.TemporaryDirectory(prefix="budget-terminal-chart-normalization-") as temp_dir:
        service = _service(temp_dir)
        try:
            normalized = service.normalize_frame("PLTR", raw)
        finally:
            service.close()

    assert list(normalized.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert isinstance(normalized["Close"], pd.Series)
    assert normalized["Close"].shape == (5,)
    assert calculate_rsi(normalized["Close"], 2).shape == (5,)


def test_ticker_first_low_symbol_does_not_collide_with_low_field() -> None:
    dates = pd.date_range("2026-08-03", periods=5)
    values = _values()
    columns = pd.MultiIndex.from_tuples(
        [("LOW", field) for field in ("Open", "High", "Low", "Close", "Volume")],
        names=["Ticker", "Price"],
    )
    raw = pd.DataFrame(
        [values[field] for field in ("Open", "High", "Low", "Close", "Volume")],
        index=columns,
        columns=dates,
    ).T
    raw.columns = columns

    with tempfile.TemporaryDirectory(prefix="budget-terminal-chart-low-") as temp_dir:
        service = _service(temp_dir)
        try:
            normalized = service.normalize_frame("LOW", raw)
        finally:
            service.close()

    assert normalized.shape == (5, 5)
    assert normalized["Low"].tolist() == values["Low"]
    assert normalized["Close"].tolist() == values["Close"]


if __name__ == "__main__":
    test_field_first_and_duplicate_close_are_one_dimensional()
    test_ticker_first_low_symbol_does_not_collide_with_low_field()
    print("chart data normalization regression tests passed")
