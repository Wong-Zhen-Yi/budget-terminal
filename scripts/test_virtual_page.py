from __future__ import annotations

import datetime as dt
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

from budget_terminal_app.compat import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)
from budget_terminal_app.mixins.virtual_trading import P32_SYMBOL_CHART_RANGES, VirtualTradingMixin
from budget_terminal_app.paper_trading import (
    PaperOrderRequest,
    PaperQuote,
    PaperTradingEngine,
    PaperTradingStore,
    RecurringScheduleSpec,
)
from budget_terminal_app.paper_trading.engine import MarketSession


class _VirtualPageProbe(VirtualTradingMixin, QWidget):
    def __init__(self, store: PaperTradingStore) -> None:
        super().__init__()
        self.page32 = QWidget()
        with patch("budget_terminal_app.mixins.virtual_trading.PaperTradingStore", return_value=store):
            self.init_page32()

    def set_theme_role(self, *args, **kwargs) -> None:
        return None

    def set_status_text(self, label, text, **kwargs) -> None:
        label.setText(str(text))

    def theme_color(self, token: str) -> str:
        return {
            "text_primary": "#f5f7fa",
            "text_secondary": "#b6beca",
            "text_muted": "#7f8997",
            "panel_background": "#11161d",
            "chart_bg": "#11161d",
            "panel_border": "#28313c",
            "accent_negative": "#ff5263",
        }.get(token, "#4f8cff")


def test_virtual_page_empty_state_shared_account_and_ticket() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        probe = _VirtualPageProbe(store)
        try:
            assert probe.p32_empty_state.isHidden() is False
            assert probe.p32_workspace.isHidden() is True
            assert probe.p32_account_combo.count() == 0

            account = store.create_account("Virtual Account", 50_000)
            probe._p32_refresh_accounts(account["id"])
            app.processEvents()

            assert probe.p32_empty_state.isHidden() is True
            assert probe.p32_workspace.isHidden() is False
            assert probe.p32_account_combo.currentText() == "Virtual Account"
            assert probe.p32_edit_account_btn.text() == "Edit account"
            assert probe.p32_equity_label.text() == "$50,000.00"
            assert probe.p32_summary_labels["buying_power"].text() == "$50,000.00"
            assert probe.p32_positions_table.columnCount() == 6
            assert probe.p32_orders_table.columnCount() == 9
            assert probe.p32_review_btn.text() == "Review Order"
            assert "inspired by Robinhood" in probe.p32_inspiration_note.text()
            assert "strict replica" in probe.p32_inspiration_note.text()
            assert probe.p32_chart_load_btn.text() == "Load"
            assert probe._p32_chart_range_key == "1M"
            assert probe.p32_chart_range_buttons["1M"].isChecked()
            assert P32_SYMBOL_CHART_RANGES == {
                "1D": ("1d", "5m"),
                "1W": ("5d", "30m"),
                "1M": ("1mo", "1h"),
                "3M": ("3mo", "1d"),
                "1Y": ("1y", "1wk"),
                "ALL": ("max", "1mo"),
            }
            assert probe._p32_chart_data_service is None
            assert probe._p32_chart_loaded_symbol == ""
            assert probe._p32_engine.instant_fill is True
            assert "without using bid/ask spreads" in probe.p32_status_label.text()

            probe.p32_order_type_combo.setCurrentIndex(1)
            assert probe.p32_limit_spin.isHidden() is False
            assert probe.p32_stop_spin.isHidden() is True
            assert probe.p32_tif_combo.isEnabled()
            probe.p32_trading_hours_combo.setCurrentIndex(1)
            assert probe.p32_order_type_combo.currentData() == "limit"
            assert probe.p32_tif_combo.currentData() == "day"
            assert probe.p32_tif_combo.isEnabled() is False
            assert "fills immediately" in probe.p32_session_hint.text()
            probe.p32_quantity_spin.setValue(3)
            probe.p32_limit_spin.setValue(25)
            assert probe.p32_estimate_label.text() == "$75.00"

            probe.p32_symbol_input.setText("msft")
            assert probe.p32_symbol_input.text() == "MSFT"
            probe.p32_sell_btn.setChecked(True)
            request = probe._p32_build_request()
            assert request.symbol == "MSFT"
            assert request.side == "sell"
            assert request.order_type == "limit"
            assert request.execution_session == "extended"
        finally:
            probe._p32_stop()
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
            "Volume": [1000 + index * 100 for index in range(len(closes))],
        },
        index=index,
    )


def test_virtual_focused_account_dialog_uses_exact_cash_target() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Editable Account", 25_000)
        probe = _VirtualPageProbe(store)
        try:
            def inspect_and_accept(dialog: QDialog) -> QDialog.DialogCode:
                cash = next(spin for spin in dialog.findChildren(QDoubleSpinBox) if spin.maximum() >= 1_000_000_000)
                assert cash.value() == 25_000
                cash.setValue(27_500)
                label_text = [label.text() for label in dialog.findChildren(QLabel)]
                assert any("Deposit $2,500.00" in text for text in label_text)
                button_text = [button.text() for button in dialog.findChildren(QPushButton)]
                assert "Save changes" in button_text
                assert "Future order settings" in dialog.findChild(QGroupBox).title()
                return QDialog.DialogCode.Accepted

            with patch("budget_terminal_app.mixins.virtual_trading.QDialog.exec", new=inspect_and_accept):
                payload = probe._p32_account_dialog("Edit Virtual Account", account)
            assert payload is not None
            assert payload["name"] == "Editable Account"
            assert payload["target_cash"] == 27_500
            assert "initial_cash" not in payload
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


def test_virtual_recurring_tab_controls_and_fractional_ticket() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Recurring UI", 25_000)
        probe = _VirtualPageProbe(store)
        try:
            probe._p32_refresh_accounts(account["id"])
            assert probe.p32_tabs.tabText(3) == "Recurring"
            assert probe.p32_add_funding_btn.isEnabled()
            assert probe.p32_add_buy_btn.isEnabled()

            probe.p32_quantity_spin.setValue(1.234567)
            probe.p32_symbol_input.setText("AAPL")
            assert probe.p32_quantity_spin.decimals() == 6
            assert probe._p32_build_request().quantity == 1.234567

            funding = store.create_recurring_schedule(
                RecurringScheduleSpec(
                    account_id=account["id"],
                    kind="funding",
                    cadence="weekly",
                    amount=250,
                    timezone="Asia/Singapore",
                    local_time="08:30",
                    weekday=4,
                ),
                next_run_at="2026-07-17T00:30:00Z",
            )
            probe._p32_refresh_recurring(funding["id"])
            assert probe.p32_recurring_table.rowCount() == 1
            assert probe.p32_recurring_table.item(0, 0).text() == "Funding"
            assert "$250.00 deposit" in probe.p32_recurring_table.item(0, 1).text()
            assert "Friday 08:30" in probe.p32_recurring_table.item(0, 2).text()
            assert probe.p32_edit_schedule_btn.isEnabled()

            probe._p32_toggle_selected_schedule()
            assert store.get_recurring_schedule(funding["id"])["status"] == "paused"
            assert probe.p32_toggle_schedule_btn.text() == "Resume"
            probe._p32_toggle_selected_schedule()
            assert store.get_recurring_schedule(funding["id"])["status"] == "active"

            with patch(
                "budget_terminal_app.mixins.virtual_trading.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                probe._p32_cancel_selected_schedule()
            assert store.get_recurring_schedule(funding["id"])["status"] == "cancelled"
            assert probe.p32_recurring_table.rowCount() == 1
            assert not probe.p32_edit_schedule_btn.isEnabled()

            active = store.create_recurring_schedule(
                RecurringScheduleSpec(
                    account_id=account["id"],
                    kind="buy",
                    cadence="daily",
                    amount=20,
                    symbol="AAPL",
                    timezone="Asia/Singapore",
                    local_time="09:00",
                ),
                next_run_at="2026-07-17T01:00:00Z",
            )
            store.archive_account(account["id"])
            probe._p32_refresh_accounts(account["id"])
            assert store.get_recurring_schedule(active["id"])["status"] == "paused"
            assert not probe.p32_add_funding_btn.isEnabled()
            assert not probe.p32_add_buy_btn.isEnabled()
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


def test_virtual_recurring_dialog_uses_clock_timezone_and_focused_fields() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Recurring Dialog", 25_000)
        probe = _VirtualPageProbe(store)
        try:
            probe._p32_refresh_accounts(account["id"])
            probe._current_clock_country_code = lambda: "SG"
            probe._clock_country_by_code = lambda _code: {"zone": "Asia/Singapore"}

            def inspect_and_accept(dialog: QDialog) -> QDialog.DialogCode:
                labels = [label.text() for label in dialog.findChildren(QLabel)]
                assert "Total USD budget" in labels
                assert "Frequency" in labels
                assert "Local time" in labels
                assert "Day of month" in labels
                assert "Asia/Singapore" in labels
                symbol = dialog.findChild(QLineEdit)
                assert symbol is not None
                symbol.setText("AAPL")
                return QDialog.DialogCode.Accepted

            with patch("budget_terminal_app.mixins.virtual_trading.QDialog.exec", new=inspect_and_accept):
                payload = probe._p32_schedule_dialog("buy")
            assert payload is not None
            spec, next_run = payload
            assert spec.symbol == "AAPL"
            assert spec.timezone == "Asia/Singapore"
            assert spec.cadence == "monthly"
            assert next_run.endswith("+00:00")
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


def test_virtual_symbol_chart_explicit_load_render_ranges_and_stale_guards() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Chart Account", 75_000)
        probe = _VirtualPageProbe(store)
        try:
            probe._p32_refresh_accounts(account["id"])
            requests = []
            chart_fetches = []
            probe._p32_get_chart_data_service = lambda: type(
                "ChartServiceProbe",
                (),
                {
                    "fetch_base_frame_payload": lambda _self, symbol, **kwargs: (
                        chart_fetches.append({"symbol": symbol, **kwargs})
                        or {"df": _chart_frame([100.0, 101.0, 99.0, 103.0]), "_market_data_meta": {"source": "yfinance"}}
                    )
                },
            )()
            probe._p32_submit_chart_background = lambda **kwargs: requests.append(kwargs)
            probe.p32_symbol_input.setText("msft")
            assert requests == []
            probe.p32_symbol_input.returnPressed.emit()

            assert len(requests) == 1
            first_request = requests[-1]
            assert first_request["symbol"] == "MSFT"
            assert first_request["range_key"] == "1M"
            assert probe._p32_chart_inflight is True
            assert probe.p32_chart_load_btn.isEnabled() is False
            assert probe.p32_review_btn.isEnabled() is True

            payload = {
                "df": _chart_frame([100.0, 101.0, 99.0, 103.0]),
                "_market_data_meta": {"source": "cache", "freshness": "fresh"},
            }
            first_request["work"]()
            assert chart_fetches[-1]["include_extended_hours"] is False
            probe._p32_on_chart_complete(
                first_request["request_id"],
                first_request["symbol"],
                first_request["range_key"],
                payload,
            )
            assert probe._p32_chart_inflight is False
            assert probe.p32_chart_load_btn.isEnabled() is True
            assert probe._p32_chart_loaded_symbol == "MSFT"
            assert probe.p32_chart_symbol_label.text() == "MSFT · 1M"
            assert probe.p32_chart_price_label.text() == "$103.00"
            assert probe.p32_chart_change_label.text() == "+3.00%"
            assert probe.p32_chart_change_label.property("chartState") == "positive"
            assert len(probe.p32_chart_candle_item.data) == 4
            assert len(probe.p32_chart_axis.dates) == 4
            assert "local chart cache" in probe.p32_chart_status_label.text()

            rendered_price = probe.p32_chart_price_label.text()
            probe._p32_select_chart_range("3M")
            assert len(requests) == 2
            second_request = requests[-1]
            assert second_request["range_key"] == "3M"
            probe._p32_on_chart_complete(
                first_request["request_id"],
                "MSFT",
                "1M",
                {"df": _chart_frame([10.0, 20.0])},
            )
            assert probe.p32_chart_price_label.text() == rendered_price

            stale_payload = {
                "df": _chart_frame([103.0, 102.0, 101.0]),
                "_market_data_meta": {
                    "source": "cache",
                    "freshness": "stale",
                    "cache_age_seconds": 120,
                },
            }
            probe._p32_on_chart_complete(
                second_request["request_id"],
                second_request["symbol"],
                second_request["range_key"],
                stale_payload,
            )
            assert probe.p32_chart_symbol_label.text() == "MSFT · 3M"
            assert probe.p32_chart_price_label.text() == "$101.00"
            assert probe.p32_chart_change_label.property("chartState") == "negative"
            assert "stale cache data" in probe.p32_chart_status_label.text()

            probe._p32_select_chart_range("1D")
            extended_request = requests[-1]
            extended_payload = extended_request["work"]()
            assert chart_fetches[-1]["include_extended_hours"] is True
            probe._p32_on_chart_complete(
                extended_request["request_id"],
                extended_request["symbol"],
                extended_request["range_key"],
                extended_payload,
            )
            assert probe.p32_chart_symbol_label.text() == "MSFT · 1D · PRE included"
            assert "delayed pre-market candles" in probe.p32_chart_status_label.text()

            shares_before = probe.p32_quantity_spin.value()
            invalidated_request_id = probe._p32_chart_request_id
            probe.p32_symbol_input.setText("TSLA")
            assert probe._p32_chart_loaded_symbol == ""
            assert probe.p32_chart_symbol_label.text() == "Symbol chart"
            assert probe.p32_quantity_spin.value() == shares_before
            probe._p32_on_chart_complete(
                invalidated_request_id,
                "MSFT",
                "3M",
                payload,
            )
            assert probe._p32_chart_loaded_symbol == ""

            probe._p32_request_symbol_chart()
            third_request = requests[-1]
            probe._p32_on_chart_complete(
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
            assert probe._p32_chart_loaded_symbol == ""
            assert "No usable candles" in probe.p32_chart_status_label.text()

            probe._p32_request_symbol_chart()
            fourth_request = requests[-1]
            probe._p32_on_chart_error(fourth_request["request_id"], "network unavailable")
            assert "network unavailable" in probe.p32_chart_status_label.text()
            assert probe.p32_review_btn.isEnabled() is True
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


def test_virtual_page_premarket_marks_revalue_account_and_label_prices() -> None:
    app = QApplication.instance() or QApplication([])
    now = dt.datetime(2026, 7, 15, 11, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Pre-market Account", 10_000)
        regular_quote = PaperQuote(
            symbol="AAPL",
            bid=99.0,
            ask=100.0,
            bid_size=10,
            ask_size=10,
            last_price=99.5,
            exchange="NMS",
            currency="USD",
            quote_type="EQUITY",
            market_state="REGULAR",
            source_timestamp=now,
            fetched_at=now,
        )
        engine = PaperTradingEngine(
            store,
            now=lambda: now,
            session_resolver=lambda _now: MarketSession(True, now + dt.timedelta(hours=2), now + dt.timedelta(hours=2)),
        )
        order = engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 2, "market", "day"),
            quote=regular_quote,
        )
        assert engine.process_pending_orders(quotes={"AAPL": regular_quote})["filled"] == 1
        assert store.get_order(order["id"])["status"] == "filled"
        store.update_position_mark(
            account["id"],
            PaperQuote(
                **{
                    **regular_quote.__dict__,
                    "market_state": "PRE",
                    "mark_price": 105.0,
                    "mark_timestamp": now,
                    "mark_session": "PRE",
                }
            ),
            stale=False,
        )

        probe = _VirtualPageProbe(store)
        try:
            probe._p32_market_phase = "premarket"
            probe._p32_refresh_accounts(account["id"])
            app.processEvents()
            assert probe.p32_positions_table.horizontalHeaderItem(2).text() == "Price (PRE)"
            assert probe.p32_positions_table.item(0, 2).text() == "$105.0000"
            assert probe.p32_equity_label.text() == "$10,009.90"
            assert probe.p32_market_state_label.text() == "PRE · delayed Yahoo marks"

            store.set_position_mark_stale(account["id"], "AAPL")
            probe._p32_refresh_all()
            assert probe.p32_market_state_label.text() == "PRE · delayed Yahoo marks · 1 stale"
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


def test_virtual_cash_flows_do_not_distort_returns_or_chart() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        store = PaperTradingStore(Path(directory) / "paper.db")
        account = store.create_account("Cash Flow Account", 10_000)
        now = dt.datetime.now(dt.timezone.utc)
        quote = PaperQuote(
            symbol="AAPL",
            bid=99.0,
            ask=100.0,
            bid_size=10,
            ask_size=10,
            last_price=99.5,
            exchange="NMS",
            currency="USD",
            quote_type="EQUITY",
            market_state="REGULAR",
            source_timestamp=now,
            fetched_at=now,
        )
        engine = PaperTradingEngine(
            store,
            now=lambda: now,
            session_resolver=lambda _now: MarketSession(True, now + dt.timedelta(hours=2), now + dt.timedelta(hours=2)),
        )
        engine.submit_order(
            PaperOrderRequest(account["id"], "AAPL", "buy", 1, "market", "day"),
            quote=quote,
        )
        assert engine.process_pending_orders(quotes={"AAPL": quote})["filled"] == 1
        store.record_equity_snapshot(account["id"], force=True)
        probe = _VirtualPageProbe(store)
        try:
            probe._p32_refresh_accounts(account["id"])
            before_return = probe.p32_return_label.text()
            before_equity = store.account_summary(account["id"])["equity"]

            prior_cash = store.cash_balance(account["id"])
            store.update_account(account["id"], target_cash=prior_cash + 5_000)
            store.record_equity_snapshot(account["id"], force=True)
            probe._p32_refresh_all()
            app.processEvents()

            assert probe.p32_return_label.text() == before_return
            assert store.account_summary(account["id"])["equity"] == before_equity + 5_000
            curve = probe.p32_performance_plot.listDataItems()[0]
            _x_values, y_values = curve.getData()
            assert len(y_values) >= 2
            assert abs(float(y_values[-1]) - float(y_values[-2])) < 1e-7
        finally:
            probe._p32_stop()
            probe.close()
            app.processEvents()


if __name__ == "__main__":
    test_virtual_page_empty_state_shared_account_and_ticket()
    test_virtual_focused_account_dialog_uses_exact_cash_target()
    test_virtual_recurring_tab_controls_and_fractional_ticket()
    test_virtual_recurring_dialog_uses_clock_timezone_and_focused_fields()
    test_virtual_symbol_chart_explicit_load_render_ranges_and_stale_guards()
    test_virtual_page_premarket_marks_revalue_account_and_label_prices()
    test_virtual_cash_flows_do_not_distort_returns_or_chart()
    print("virtual trading page smoke passed")
