from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.dependencies import QApplication, QObject
from budget_terminal_app.mixins.portfolio_metrics import PortfolioMetricsMixin

_QT_APP = None


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _qt_app():
    global _QT_APP
    app = QApplication.instance()
    if app is None:
        _QT_APP = QApplication([])
        app = _QT_APP
    else:
        _QT_APP = app
    return app


class _PortfolioExportProbe(QObject, PortfolioMetricsMixin):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.active_portfolio_id = "main"
        self.status_bar = object()
        self.tickers = ["AAA", "BBB"]
        self.tracker_data = {
            "AAA": {"shares": 2.0, "avg_price": 10.0},
            "BBB": {"shares": 4.0, "avg_price": 20.0},
        }
        self.last_data = {
            "portfolio": {
                "AAA": {"price": 15.0, "change": 2.345},
                "BBB": {"price": 25.0, "change": -1.25},
            }
        }
        self.active_options_data = [
            {
                "ticker": "AAA",
                "strategy": "Calls",
                "expiry": "2026-07-17",
                "strike": 20.0,
                "contracts": 2,
                "premium": 1.5,
                "current_price": 2.25,
                "volume": 1234,
                "open_interest": 5678,
                "iv": 0.42,
            },
            {
                "ticker": "BBB",
                "strategy": "Covered Call",
                "expiry": "2026-08-21",
                "strike": 30.0,
                "contracts": 1,
                "premium": 3.0,
                "current_price": 1.0,
                "volume": 10,
                "open_interest": 20,
                "iv": 0.30,
            },
        ]
        self.cash_balance = 50.0
        self._mktcap_cache = {
            "AAA": 5_000_000_000,
            "BBB": 15_000_000_000,
        }
        self.status_messages = []

    def _p4_active_tickers(self):
        return self.tickers

    def _p4_active_tracker_data(self):
        return self.tracker_data

    def _p4_active_cash_balance(self, portfolio_id=None) -> float:
        return self.cash_balance

    def _p4_get_active_portfolio_index(self) -> int:
        return 0

    def _p4_portfolio_name(self, index: int) -> str:
        return "Growth Book"

    def set_status_text(self, label, text: str, *, status: str = "muted") -> None:
        self.status_messages.append((label, text, status))


def test_compact_portfolio_llm_export() -> None:
    app = _qt_app()
    probe = _PortfolioExportProbe()

    probe._p4_export_for_llm()
    text = app.clipboard().text()
    lines = text.splitlines()

    _assert("=== PORTFOLIO EXPORT: Growth Book ===" in text, "export should include portfolio heading")
    _assert("| Ticker | Sh | Avg | Price | Day% | MV | Wt% | PnL | Gain% | MCap |" in text, "stock table header should be compact")
    _assert("| Ticker | Strat | Exp | Strike | Ctr | Prem | Cur | Vol | OI | IV% | PnL |" in text, "options table header should be compact")
    _assert("Cash Balance: $50.00" in text, "cash balance should be preserved")
    _assert("Total Portfolio Value: $180.00" in text, "total portfolio value should be preserved")

    stock_header_index = lines.index("| Ticker | Sh | Avg | Price | Day% | MV | Wt% | PnL | Gain% | MCap |")
    _assert(lines[stock_header_index + 2].startswith("| BBB |"), "stocks should remain sorted by market value descending")
    _assert(
        "| BBB | 4 | $20.00 | $25.00 | -1.25% | $100.00 | 55.6% | +$20.00 | +25.0% | Large $15.00B |" in text,
        "stock row should include compact key values",
    )
    _assert(
        "| AAA | Calls | 2026-07-17 | $20.00 | 2 | $1.50 | $2.25 | 1,234 | 5,678 | 42.0% | +$150.00 |" in text,
        "long option row should include buyer P&L",
    )
    _assert(
        "| BBB | Covered Call | 2026-08-21 | $30.00 | 1 | $3.00 | $1.00 | 10 | 20 | 30.0% | +$200.00 |" in text,
        "short option row should include seller P&L",
    )

    for verbose_label in (
        "Shares:",
        "Avg Price:",
        "Cost Basis:",
        "Current Price:",
        "Market Value:",
        "Contracts:",
        "Premium:",
    ):
        _assert(verbose_label not in text, f"export should omit verbose label {verbose_label}")

    _assert(
        probe.status_messages[-1][1] == "Exported Growth Book (5 positions) to clipboard",
        "status text should keep the existing item count",
    )
    _assert(probe.status_messages[-1][2] == "positive", "status should remain positive")


def main() -> None:
    test_compact_portfolio_llm_export()
    print("compact portfolio LLM export smoke test passed")


if __name__ == "__main__":
    main()
