from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# This script talks to Yahoo from the same IP as the app, so it shares the app's pacer rather than
# running unthrottled alongside it. Imported directly (not via `dependencies`) to keep the
# diagnostic free of the Qt import chain -- the limiter module is stdlib-only.
from budget_terminal_app.services.yahoo_rate_limit import install_yahoo_rate_limit

install_yahoo_rate_limit()


def _symbol_frame(batch: Any, symbol: str) -> Any:
    if batch is None or batch.empty:
        return None
    if getattr(batch.columns, "nlevels", 1) > 1:
        if symbol in batch.columns.get_level_values(0):
            return batch[symbol]
        if symbol in batch.columns.get_level_values(1):
            return batch.xs(symbol, axis=1, level=1)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect current Yahoo Finance download shapes and optional metadata.")
    parser.add_argument("symbols", nargs="*", default=["AAPL", "MSFT", "SPY"])
    parser.add_argument("--period", default="5d")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--include-info", action="store_true")
    args = parser.parse_args()

    symbols = [str(symbol).upper().strip() for symbol in args.symbols if str(symbol).strip()]
    batch = yf.download(
        symbols,
        period=args.period,
        interval=args.interval,
        group_by="ticker",
        progress=False,
        auto_adjust=False,
    )
    print("Columns:", batch.columns)
    for symbol in symbols:
        frame = _symbol_frame(batch, symbol)
        print(f"\n{symbol}: rows={0 if frame is None else len(frame)}")
        if frame is not None:
            print(frame.tail(3))
        if args.include_info:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            print("targetMeanPrice:", info.get("targetMeanPrice"))
            print("news items:", len(ticker.news or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
