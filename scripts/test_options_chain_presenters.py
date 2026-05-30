from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.dependencies import pd
from budget_terminal_app.mixins.options_chain_presenters import (
    build_chain_rows,
    build_option_summary_rows,
    format_top_volume_expiration,
    prepare_strike_records,
    prepare_top_volume_records,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_expiration_formatting() -> None:
    _assert(format_top_volume_expiration("2026-06-19") == "JUN 19 '26", "ISO expiry should use compact label")
    _assert(format_top_volume_expiration("") == "", "empty expiry should stay empty")
    _assert(format_top_volume_expiration("weekly") == "weekly", "non-date expiry labels should pass through")


def test_top_volume_preparation_and_rows() -> None:
    frame = pd.DataFrame(
        [
            {"type": "Call", "strike": "100", "lastPrice": "1.20", "volume": "50", "openInterest": "200"},
            {"type": "Put", "strike": "95", "lastPrice": "2.25", "volume": "75", "openInterest": "10"},
            {"type": "Call", "strike": "105", "lastPrice": "0.80", "volume": "90", "openInterest": "5"},
        ]
    )
    call_records = prepare_top_volume_records(
        frame,
        ticker="SPY",
        expiry="2026-06-19",
        option_type="Call",
        pd_module=pd,
    )
    _assert(len(call_records) == 2, "type filter should keep only calls")
    _assert(call_records[0]["strike"] == 105, "top-volume rows should sort by volume first")
    _assert(call_records[0]["ticker"] == "SPY", "missing ticker should be filled")
    _assert(call_records[0]["expiration"] == "2026-06-19", "missing expiration should be filled")

    rows = build_option_summary_rows(
        call_records,
        ticker="SPY",
        expiry="2026-06-19",
        positive_color="#00ff00",
        negative_color="#ff0000",
        pd_module=pd,
    )
    _assert(rows[0][1].text == "Call", "type cell should render call")
    _assert(rows[0][1].foreground == "#00ff00", "call type should use positive color")
    _assert(rows[0][3].text == "JUN 19 '26", "expiry cell should use compact label")
    _assert(rows[0][5].text == "90", "volume cell should format integer-like values")


def test_strike_preparation() -> None:
    frame = pd.DataFrame(
        [
            {"type": "Put", "strike": 100.0, "lastPrice": 2.0, "volume": 20, "openInterest": 10},
            {"type": "Call", "strike": 100.0, "lastPrice": 1.5, "volume": 5, "openInterest": 50},
            {"type": "Call", "strike": 101.0, "lastPrice": 1.1, "volume": 999, "openInterest": 999},
        ]
    )
    records = prepare_strike_records(
        frame,
        ticker="SPY",
        expiry="2026-06-19",
        selected_strike=100.0,
        tolerance=0.0001,
        pd_module=pd,
    )
    _assert([record["type"] for record in records] == ["Call", "Put"], "strike rows should order calls before puts")
    _assert(all(record["strike"] == 100.0 for record in records), "strike rows should keep only matching strike")


def test_chain_rows() -> None:
    empty_rows = build_chain_rows(
        pd.DataFrame(),
        [("Strike", "strike", "{:.1f}")],
        {},
        {},
        strategy_tooltip=lambda rank, detail: "",
        strategy_bg=lambda rank: None,
        positive_color="#00ff00",
        negative_color="#ff0000",
        muted_color="#999999",
        pd_module=pd,
    )
    _assert(empty_rows == [], "empty chain should render no rows")

    frame = pd.DataFrame(
        [
            {
                "strike": 100.0,
                "lastPrice": 1.25,
                "change": 0.2,
                "iv_percent": 31.25,
            }
        ]
    )
    rows = build_chain_rows(
        frame,
        [
            ("Strike", "strike", "{:.1f}"),
            ("Last", "lastPrice", "{:.2f}"),
            ("Chg", "change", "{:+.2f}"),
            ("IV", "iv_percent", "{:.1f}%"),
        ],
        {0: 1},
        {0: {"score": 10}},
        strategy_tooltip=lambda rank, detail: f"rank {rank}" if rank else "",
        strategy_bg=lambda rank: "#101010" if rank else None,
        positive_color="#00ff00",
        negative_color="#ff0000",
        muted_color="#999999",
        pd_module=pd,
    )
    _assert(rows[0][0].text == "100.0  #1", "ranked strike should show rank suffix")
    _assert(rows[0][0].background == "#101010", "ranked cells should get strategy background")
    _assert(rows[0][0].tooltip == "rank 1", "ranked cells should get strategy tooltip")
    _assert(rows[0][2].foreground == "#00ff00", "positive change should use positive color")
    _assert(rows[0][3].foreground == "#999999", "IV should use muted color")


def main() -> None:
    test_expiration_formatting()
    test_top_volume_preparation_and_rows()
    test_strike_preparation()
    test_chain_rows()
    print("options chain presenter smoke tests passed")


if __name__ == "__main__":
    main()
