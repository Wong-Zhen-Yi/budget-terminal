from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.compat import QApplication, QLabel, QPlainTextEdit, QTableWidget, pd
from budget_terminal_app.mixins.stocks_page import STOCKS_CHART_INTERVAL, StocksPageMixin


class _StocksProbe(StocksPageMixin):
    pass


def _assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_synthetic_institutional_change_formatting() -> None:
    probe = _StocksProbe()
    raw_rows = pd.DataFrame(
        [
            {
                "Holder": "Alpha Capital",
                "pctHeld": 0.02,
                "Shares": 1000,
                "Value": 100000,
                "pctChange": 1.25,
                "Date Reported": "2026-03-31",
            },
            {
                "Holder": "Beta Partners",
                "pctHeld": 0.01,
                "Shares": 500,
                "Value": 50000,
                "pctChange": 1.5241001,
                "Date Reported": "2026-03-31",
            },
            {
                "Holder": "Gamma Fund",
                "pctHeld": 0.005,
                "Shares": 250,
                "Value": 25000,
                "pctChange": -1.5,
                "Date Reported": "2026-03-31",
            },
            {
                "Holder": "Delta Advisors",
                "pctHeld": 0.004,
                "Shares": 200,
                "Value": 20000,
                "pctChange": 1.0,
                "Date Reported": "2026-03-31",
            },
        ]
    )

    normalized = probe._stocks_normalize_institutional_rows(raw_rows)
    by_holder = {row["holder"]: row for row in normalized}

    _assert_equal(by_holder["Alpha Capital"]["pct_change"], "+125.00%", "fractional change above 100% should not be capped")
    _assert_equal(by_holder["Beta Partners"]["pct_change"], "+152.41%", "fractional change should preserve values above 150%")
    _assert_equal(by_holder["Gamma Fund"]["pct_change"], "-150.00%", "negative fractional change below -100% should not be capped")
    _assert_equal(by_holder["Delta Advisors"]["pct_change"], "+100.00%", "Yahoo exact 1.0 values should remain exactly +100.00%")
    _assert_equal(probe._stocks_format_holder_change("not-a-number"), "N/A", "invalid holder change should be N/A")


def test_table_and_llm_export_use_uncapped_change() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    probe = _StocksProbe()
    row = {
        "holder": "Alpha Capital",
        "pct_held": "2.00%",
        "shares": "1K",
        "value": "$100K",
        "pct_change": "+125.00%",
        "reported": "Mar 31, 2026",
    }

    probe.stocks_institutional_empty = QLabel()
    probe.stocks_institutional_table = QTableWidget(0, 6)
    probe._stocks_render_institutional_rows([row])
    _assert_equal(probe.stocks_institutional_table.item(0, 4).text(), "+125.00%", "table should render uncapped change")

    probe._stocks_loaded_symbol = "TEST"
    probe.stocks_chart_symbol_label = QLabel("TEST")
    probe.stocks_symbol = "TEST"
    probe._stocks_info = {"longName": "Test Corp"}
    probe.stocks_description_output = QPlainTextEdit()
    probe.stocks_description_output.setPlainText("Synthetic verification company.")
    probe.stocks_mfi_enabled = False
    probe.stocks_auto_follow = True
    probe._stocks_mfi_series = None
    probe._stocks_chart_interval = STOCKS_CHART_INTERVAL
    probe._stocks_chart_stats = {
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "volume": 1000,
        "change_value": 1,
        "change_pct": 10,
    }
    probe._stocks_chart_df = pd.DataFrame(
        [{"Open": 10.0, "High": 12.0, "Low": 9.0, "Close": 11.0, "Volume": 1000}],
        index=pd.to_datetime(["2026-03-31"]),
    )
    probe.stocks_metric_labels = {}
    probe.stocks_target_labels = {}
    probe._stocks_loaded_news = []
    probe._stocks_loaded_institutional_rows = [row]
    probe._stocks_loaded_insider_rows = []
    export_text = probe._stocks_build_llm_export()
    expected_row = "| Alpha Capital | 2.00% | 1K | $100K | +125.00% | Mar 31, 2026 |"
    if expected_row not in export_text:
        raise AssertionError("LLM export should include uncapped institutional-holder change.")


if __name__ == "__main__":
    test_synthetic_institutional_change_formatting()
    test_table_and_llm_export_use_uncapped_change()
    print("stocks institutional holder change formatting checks passed")
