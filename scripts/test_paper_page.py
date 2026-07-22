from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.compat import QApplication, QWidget
from budget_terminal_app.mixins.paper_trading import P31_SYMBOL_CHART_RANGES, PaperTradingMixin
from budget_terminal_app.paper_trading import PaperTradingStore


class _PaperPageProbe(PaperTradingMixin, QWidget):
    def __init__(self, store: PaperTradingStore) -> None:
        super().__init__()
        self.page31 = QWidget()
        self._test_store = store
        with patch("budget_terminal_app.mixins.paper_trading.PaperTradingStore", return_value=store):
            self.init_page31()

    def set_theme_role(self, *args, **kwargs) -> None:
        return None

    def set_theme_variant(self, *args, **kwargs) -> None:
        return None

    def set_status_text(self, label, text, **kwargs) -> None:
        label.setText(str(text))

    def theme_color(self, token: str) -> str:
        return "#4f8cff" if token == "accent" else "#10151f"

    def style_plot_widget(self, plot, **kwargs) -> None:
        plot.setBackground("#10151f")


def test_paper_page_empty_state_account_tables_and_journal() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        probe = _PaperPageProbe(PaperTradingStore(Path(directory) / "paper.db"))
        try:
            assert probe.p31_empty_state.isHidden() is False
            assert probe.p31_workspace.isHidden() is True
            assert probe.p31_account_combo.count() == 0
            account = probe._p31_store.create_account("UI Account", 100_000)
            probe._p31_refresh_accounts(account["id"])
            app.processEvents()
            assert probe.p31_empty_state.isHidden() is True
            assert probe.p31_workspace.isHidden() is False
            assert probe.p31_account_combo.currentText() == "UI Account"
            assert probe.p31_summary_labels["equity"].text() == "$100,000.00"
            assert probe.p31_positions_table.columnCount() == 8
            assert probe.p31_orders_table.columnCount() == 11
            assert probe.p31_chart_load_btn.text() == "Load"
            assert probe._p31_chart_range_key == "1M"
            assert probe.p31_chart_range_buttons["1M"].isChecked()
            assert P31_SYMBOL_CHART_RANGES == {
                "1D": ("1d", "5m"),
                "1W": ("5d", "30m"),
                "1M": ("1mo", "1h"),
                "3M": ("3mo", "1d"),
                "1Y": ("1y", "1wk"),
                "ALL": ("max", "1mo"),
            }
            assert probe._p31_chart_data_service is None
            assert probe._p31_chart_loaded_symbol == ""
            probe.p31_quantity_spin.setValue(2.345678)
            assert probe.p31_quantity_spin.decimals() == 6
            assert probe.p31_quantity_spin.value() == 2.345678

            probe.p31_order_type_combo.setCurrentIndex(1)
            probe._p31_update_ticket_fields()
            assert probe.p31_limit_spin.isEnabled()
            assert not probe.p31_stop_spin.isEnabled()
            assert probe.p31_tif_combo.isEnabled()
            probe.p31_order_type_combo.setCurrentIndex(0)
            probe._p31_update_ticket_fields()
            assert not probe.p31_tif_combo.isEnabled()
            assert probe.p31_tif_combo.currentData() == "day"

            probe.p31_journal_note.setPlainText("Review this setup")
            probe.p31_journal_tags.setText("review, discipline")
            probe._p31_save_journal()
            assert probe.p31_journal_table.rowCount() == 1
            assert "review" in probe.p31_journal_table.item(0, 1).text()
        finally:
            probe._p31_stop()
            probe.close()
            app.processEvents()


def _chart_frame(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-02 09:30", periods=len(closes), freq="h")
    return pd.DataFrame(
        {
            "Open": [value - 0.5 for value in closes],
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1000 + offset * 100 for offset in range(len(closes))],
        },
        index=index,
    )


def test_paper_symbol_chart_explicit_load_render_ranges_and_stale_guards() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Chart Account", 75_000)
        probe = _PaperPageProbe(store)
        try:
            probe._p31_refresh_accounts(account["id"])
            requests = []
            probe._p31_submit_chart_background = lambda **kwargs: requests.append(kwargs)

            probe.p31_symbol_input.setText("msft")
            assert probe.p31_symbol_input.text() == "MSFT"
            assert requests == []
            assert probe._p31_chart_data_service is None
            probe.p31_symbol_input.returnPressed.emit()

            assert len(requests) == 1
            first_request = requests[-1]
            assert first_request["symbol"] == "MSFT"
            assert first_request["range_key"] == "1M"
            assert probe._p31_chart_inflight is True
            assert probe.p31_chart_load_btn.isEnabled() is False
            assert probe.p31_submit_btn.isEnabled() is True

            payload = {
                "df": _chart_frame([100.0, 101.0, 99.0, 103.0]),
                "_market_data_meta": {"source": "cache", "freshness": "fresh"},
            }
            probe._p31_on_chart_complete(
                first_request["request_id"],
                first_request["symbol"],
                first_request["range_key"],
                payload,
            )
            assert probe._p31_chart_inflight is False
            assert probe.p31_chart_load_btn.isEnabled() is True
            assert probe._p31_chart_loaded_symbol == "MSFT"
            assert probe.p31_chart_symbol_label.text() == "MSFT · 1M"
            assert probe.p31_chart_price_label.text() == "$103.00"
            assert probe.p31_chart_change_label.text() == "+3.00%"
            assert len(probe.p31_chart_candle_item.data) == 4
            assert len(probe.p31_chart_axis.dates) == 4
            assert "historical prices" in probe.p31_chart_status_label.text()
            assert "local chart cache" in probe.p31_chart_status_label.text()

            rendered_price = probe.p31_chart_price_label.text()
            probe._p31_select_chart_range("3M")
            assert len(requests) == 2
            second_request = requests[-1]
            assert second_request["range_key"] == "3M"
            probe._p31_on_chart_complete(
                first_request["request_id"],
                "MSFT",
                "1M",
                {"df": _chart_frame([10.0, 20.0])},
            )
            assert probe.p31_chart_price_label.text() == rendered_price

            stale_payload = {
                "df": _chart_frame([103.0, 102.0, 101.0]),
                "_market_data_meta": {
                    "source": "cache",
                    "freshness": "stale",
                    "cache_age_seconds": 120,
                },
            }
            probe._p31_on_chart_complete(
                second_request["request_id"],
                second_request["symbol"],
                second_request["range_key"],
                stale_payload,
            )
            assert probe.p31_chart_symbol_label.text() == "MSFT · 3M"
            assert probe.p31_chart_price_label.text() == "$101.00"
            assert probe.p31_chart_change_label.text() == "-1.94%"
            assert "stale cache historical data" in probe.p31_chart_status_label.text()

            quantity_before = probe.p31_quantity_spin.value()
            invalidated_request_id = probe._p31_chart_request_id
            probe.p31_symbol_input.setText("TSLA")
            assert probe._p31_chart_loaded_symbol == ""
            assert probe.p31_chart_symbol_label.text() == "Symbol chart"
            assert probe.p31_quantity_spin.value() == quantity_before
            probe._p31_on_chart_complete(invalidated_request_id, "MSFT", "3M", payload)
            assert probe._p31_chart_loaded_symbol == ""

            probe._p31_request_symbol_chart()
            third_request = requests[-1]
            probe._p31_on_chart_complete(
                third_request["request_id"],
                third_request["symbol"],
                third_request["range_key"],
                {
                    "df": pd.DataFrame(),
                    "_market_data_meta": {
                        "source": "yfinance",
                        "freshness": "failed",
                        "failure_reason": "No usable candles.",
                    },
                },
            )
            assert probe._p31_chart_loaded_symbol == ""
            assert "No usable candles" in probe.p31_chart_status_label.text()

            probe._p31_request_symbol_chart()
            fourth_request = requests[-1]
            probe._p31_on_chart_error(fourth_request["request_id"], "network unavailable")
            assert "network unavailable" in probe.p31_chart_status_label.text()
            assert probe.p31_submit_btn.isEnabled() is True
        finally:
            probe._p31_stop()
            probe.close()
            app.processEvents()


if __name__ == "__main__":
    test_paper_page_empty_state_account_tables_and_journal()
    test_paper_symbol_chart_explicit_load_render_ranges_and_stale_guards()
    print("paper trading page smoke passed")
