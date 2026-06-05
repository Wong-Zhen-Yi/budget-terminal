from __future__ import annotations

import datetime
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import budget_terminal_app.workers.earnings_calendar as earnings_module
from budget_terminal_app.dependencies import pd
from budget_terminal_app.workers.earnings_calendar import (
    EARNINGS_DEFAULT_RANGE_KEY,
    EarningsCalendarService,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _use_temp_user_data(tmp_dir: Path) -> Any:
    original_user_data_path = earnings_module.user_data_path

    def _temp_user_data_path(*parts: Any) -> Path:
        path = tmp_dir.joinpath(*map(str, parts))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    earnings_module.user_data_path = _temp_user_data_path
    with earnings_module._EARNINGS_MEMORY_CACHE_LOCK:
        earnings_module._EARNINGS_MEMORY_CACHE.clear()
    with earnings_module._SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK:
        earnings_module._SYMBOL_UNIVERSE_MEMORY_CACHE = None
    return original_user_data_path


def _restore_user_data_path(original: Any) -> None:
    earnings_module.user_data_path = original
    with earnings_module._EARNINGS_MEMORY_CACHE_LOCK:
        earnings_module._EARNINGS_MEMORY_CACHE.clear()
    with earnings_module._SYMBOL_UNIVERSE_MEMORY_CACHE_LOCK:
        earnings_module._SYMBOL_UNIVERSE_MEMORY_CACHE = None


def _row(
    symbol: str,
    date_text: str,
    *,
    event_name: str = "Q1 2026 Earnings Announcement",
    reported_eps: str = "--",
    changed_date: bool = False,
    previous_date: str = "",
    market_cap_value: float | None = 1_000_000_000.0,
) -> dict[str, Any]:
    event_date = datetime.date.fromisoformat(date_text)
    market_cap = "--" if market_cap_value is None else f"${market_cap_value / 1_000_000_000:.2f}B"
    return {
        "date": date_text,
        "date_display": event_date.strftime("%b %d, %Y"),
        "datetime_utc": f"{date_text}T20:00:00+00:00",
        "time_display": "20:00 UTC",
        "symbol": symbol,
        "company": f"{symbol} Corp.",
        "event_name": event_name,
        "timing": "AMC",
        "eps_estimate": "1.00",
        "eps_estimate_value": 1.0,
        "reported_eps": reported_eps,
        "reported_eps_value": None if reported_eps == "--" else float(reported_eps),
        "surprise_pct": "--",
        "surprise_pct_value": None,
        "market_cap": market_cap,
        "market_cap_value": market_cap_value,
        "status": "Upcoming",
        "previous_date": previous_date,
        "previous_datetime_utc": "",
        "changed_date": changed_date,
    }


def test_symbol_universe_filter() -> None:
    sample = "\n".join(
        [
            "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares",
            "Y|A|Agilent Technologies, Inc. Common Stock|N| |N|100|N||A|A|N",
            "Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N",
            "Y|ADRA|Example plc American Depositary Shares|Q|Q|N|100|N|N||ADRA|N",
            "Y|ABCW|Example Corp. Warrant|Q|Q|N|100|N|N||ABCW|N",
            "Y|PREF|Example Corp. Depositary Shares|N| |N|100|N||PREF|PREF|N",
            "Y|TEST|Test Corp. Common Stock|Q|Q|N|100|Y|N||TEST|N",
            "File Creation Time: 0603202608:32|||||",
        ]
    )
    symbols = EarningsCalendarService.parse_nasdaq_traded_symbols(sample)
    _assert("A" in symbols, "common stock should be included")
    _assert("ADRA" in symbols, "ADR should be included")
    _assert("SPY" not in symbols, "ETF should be excluded")
    _assert("ABCW" not in symbols, "warrant should be excluded")
    _assert("PREF" not in symbols, "preferred depositary share should be excluded")
    _assert("TEST" not in symbols, "test issue should be excluded")


def test_yfinance_frame_parser() -> None:
    start = datetime.date(2026, 6, 1)
    end = datetime.date(2026, 6, 30)
    frame = pd.DataFrame(
        {
            "Company": ["Agilent", "SPDR ETF", "ADR Co"],
            "Marketcap": [1_000_000_000, 2_000_000_000, 3_000_000_000],
            "Event Name": ["Q2 2026 Earnings Announcement", "ETF Event", "Q2 2026 Earnings Announcement"],
            "Event Start Date": [
                pd.Timestamp("2026-06-10T20:00:00Z"),
                pd.Timestamp("2026-06-11T20:00:00Z"),
                pd.Timestamp("2026-06-12T12:30:00Z"),
            ],
            "Timing": ["AMC", "AMC", "BMO"],
            "EPS Estimate": [1.25, 0.0, 2.5],
            "Reported EPS": [pd.NA, pd.NA, pd.NA],
            "Surprise(%)": [pd.NA, pd.NA, pd.NA],
        },
        index=["A", "SPY", "ADRA"],
    )
    rows = EarningsCalendarService.parse_yfinance_frame(
        frame,
        start_date=start,
        end_date=end,
        allowed_symbols={"A", "ADRA"},
        today=datetime.date(2026, 6, 1),
    )
    symbols = [row["symbol"] for row in rows]
    _assert(symbols == ["A", "ADRA"], "parser should keep only allowed company symbols")
    _assert(rows[0]["date"] == "2026-06-10", "event date should be normalized")
    _assert(rows[1]["timing"] == "BMO", "timing should be preserved")


def test_yfinance_pagination_dedupe() -> None:
    original_yf = earnings_module.yf

    def _frame(symbol: str, date_text: str, *, full_page: bool = False) -> Any:
        symbols = [symbol]
        if full_page:
            symbols.extend(f"ZZ{index}{symbol}" for index in range(99))
        return pd.DataFrame(
            {
                "Company": [f"{item} Corp." for item in symbols],
                "Marketcap": [1_000_000_000] * len(symbols),
                "Event Name": ["Q2 2026 Earnings Announcement"] * len(symbols),
                "Event Start Date": [pd.Timestamp(f"{date_text}T20:00:00Z")] * len(symbols),
                "Timing": ["AMC"] * len(symbols),
                "EPS Estimate": [1.0] * len(symbols),
                "Reported EPS": [pd.NA] * len(symbols),
                "Surprise(%)": [pd.NA] * len(symbols),
            },
            index=symbols,
        )

    class _FakeCalendars:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def get_earnings_calendar(self, *, limit: int, offset: int, force: bool, **_: Any) -> Any:
            if offset == 0:
                return _frame("A", "2026-06-10", full_page=True)
            if offset == 100:
                return _frame("B", "2026-06-11", full_page=True)
            return pd.DataFrame()

    class _FakeYf:
        Calendars = _FakeCalendars

    try:
        earnings_module.yf = _FakeYf()
        rows = EarningsCalendarService._fetch_yfinance_rows(
            datetime.date(2026, 6, 1),
            datetime.date(2026, 6, 30),
            allowed_symbols={"A", "B"},
        )
    finally:
        earnings_module.yf = original_yf
    _assert([row["symbol"] for row in rows] == ["A", "B"], "pagination should collect rows across pages")


def test_cache_round_trip_and_stale_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original_path = _use_temp_user_data(Path(tmp))
        original_fetch_live_payload = EarningsCalendarService.fetch_live_payload
        try:
            start = datetime.date.today()
            end = start + datetime.timedelta(days=30)
            cached_row = _row("A", (start + datetime.timedelta(days=5)).isoformat())
            EarningsCalendarService.save_cached_payload(
                {
                    "fetched_at": "2000-01-01T00:00:00",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "rows": [cached_row],
                    "symbol_universe": {"count": 1},
                },
                cache_key=EARNINGS_DEFAULT_RANGE_KEY,
            )
            cached = EarningsCalendarService.load_cached_payload(
                start_date=start,
                end_date=end,
                cache_key=EARNINGS_DEFAULT_RANGE_KEY,
                allow_stale=True,
            )
            _assert(cached is not None and cached["rows"][0]["symbol"] == "A", "cached row should round trip")

            @classmethod
            def _raise_fetch(cls: type[EarningsCalendarService], **_: Any) -> dict[str, Any]:
                raise RuntimeError("network down")

            EarningsCalendarService.fetch_live_payload = _raise_fetch
            fallback = EarningsCalendarService.fetch(
                start_date=start,
                end_date=end,
                cache_key=EARNINGS_DEFAULT_RANGE_KEY,
                force=True,
            )
            _assert(fallback.get("stale") is True, "failed refresh should mark stale cache")
            _assert(fallback["rows"][0]["symbol"] == "A", "stale fallback should preserve cached row")
        finally:
            EarningsCalendarService.fetch_live_payload = original_fetch_live_payload
            _restore_user_data_path(original_path)


def test_completed_preservation_and_date_change_detection() -> None:
    today = datetime.date(2026, 6, 3)
    cached_rows = [
        _row("DONE", "2026-05-20", reported_eps="1.20"),
        _row("MOVE", "2026-06-10"),
    ]
    fresh_rows = [_row("MOVE", "2026-06-12")]
    rows, changes = EarningsCalendarService.merge_with_cached_rows(
        fresh_rows=fresh_rows,
        cached_rows=cached_rows,
        prior_changes=[],
        today=today,
    )
    by_symbol = {row["symbol"]: row for row in rows}
    _assert("DONE" in by_symbol, "completed cached row should be preserved when absent from fresh data")
    _assert(by_symbol["MOVE"]["changed_date"] is True, "future date movement should be flagged")
    _assert(by_symbol["MOVE"]["previous_date"] == "Jun 10, 2026", "previous date should be displayed")
    _assert(len(changes) == 1, "date change should be recorded once")


def test_calendar_earnings_tab_smoke() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original_path = _use_temp_user_data(Path(tmp))
        try:
            start, end = EarningsCalendarService.default_date_range()
            fixture_date = start if start.weekday() < 5 else start + datetime.timedelta(days=7 - start.weekday())
            fixture_week_start = fixture_date - datetime.timedelta(days=fixture_date.weekday())
            weekend_fixture_date = fixture_week_start + datetime.timedelta(days=5)
            empty_day_index = next(index for index in range(5) if index != fixture_date.weekday())
            EarningsCalendarService.save_cached_payload(
                {
                    "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "rows": [
                        _row(
                            "A",
                            fixture_date.isoformat(),
                            changed_date=True,
                            previous_date=(fixture_date - datetime.timedelta(days=2)).strftime("%b %d, %Y"),
                            market_cap_value=1_000_000_000.0,
                        ),
                        _row("BIG", fixture_date.isoformat(), market_cap_value=5_000_000_000.0),
                        _row("NOCAP", fixture_date.isoformat(), market_cap_value=None),
                        _row("WKND", weekend_fixture_date.isoformat()),
                    ],
                    "symbol_universe": {"count": 4},
                },
                cache_key=EARNINGS_DEFAULT_RANGE_KEY,
            )

            from budget_terminal_app.app import BudgetTerminalApp
            from budget_terminal_app.main import QApplication
            from budget_terminal_app.mixins.calendar_page import CalendarPageMixin
            from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin

            app = QApplication.instance() or QApplication([])
            original_schedule_startup_refresh = WindowLifecycleMixin._schedule_startup_refresh
            original_start_lazy_warmup = WindowLifecycleMixin._start_lazy_warmup
            original_render_month = CalendarPageMixin._p7_render_month
            original_fetch_events = CalendarPageMixin._p7_fetch_events
            original_queue_holidays = CalendarPageMixin._p7_queue_market_holiday_year
            WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
            WindowLifecycleMixin._start_lazy_warmup = lambda self: None
            CalendarPageMixin._p7_render_month = lambda self: None
            CalendarPageMixin._p7_fetch_events = lambda self: None
            CalendarPageMixin._p7_queue_market_holiday_year = lambda self, *args, **kwargs: None
            try:
                window = BudgetTerminalApp()
                window.closeEvent = lambda event: event.accept()
                window._ensure_page_initialized(3)
                app.processEvents()
                _assert(window.p7_tabs.tabText(0) == "Calendar", "first Calendar subtab should be Calendar")
                _assert(window.p7_tabs.tabText(1) == "Earnings", "second Calendar subtab should be Earnings")
                window.p7_tabs.setCurrentWidget(window.p7_earnings_tab)
                app.processEvents()
                window._p7_earnings_week_start = window._p7_start_of_week(fixture_date)
                window._p7_render_earnings_rows()
                app.processEvents()
                _assert(hasattr(window, "p7_earnings_week_grid"), "earnings subtab should create a weekly grid")
                _assert(hasattr(window, "p7_earnings_week_label"), "earnings subtab should expose a week label")
                _assert(hasattr(window, "p7_earnings_export_llm_btn"), "earnings subtab should expose an LLM export button")
                _assert(len(window.p7_earnings_day_card_symbols) == 5, "weekly grid should have five weekday columns")
                day_index = fixture_date.weekday()
                _assert("A" in window.p7_earnings_day_card_symbols[day_index], "cached row should render in its weekday column")
                _assert(
                    window.p7_earnings_day_card_symbols[day_index][:3] == ["BIG", "A", "NOCAP"],
                    "same-day earnings should sort by known market cap descending with missing caps last",
                )
                _assert(
                    all("WKND" not in symbols for symbols in window.p7_earnings_day_card_symbols),
                    "weekend rows should not render in the weekday-only earnings grid",
                )
                _assert(
                    any(bool(card.property("changed_date")) for card in window.p7_earnings_day_cards[day_index]),
                    "changed-date rows should expose a visible card marker",
                )
                _assert(
                    not window.p7_earnings_day_empty_labels[empty_day_index].isHidden(),
                    "empty weekdays should show an empty-state label",
                )
                original_week_start = window._p7_earnings_week_start
                window._p7_change_earnings_week(1)
                app.processEvents()
                _assert(
                    window._p7_earnings_week_start == original_week_start + datetime.timedelta(days=7),
                    "next-week navigation should move by seven days",
                )
                window._p7_jump_earnings_current_week()
                app.processEvents()
                _assert(
                    window._p7_earnings_week_start == window._p7_start_of_week(datetime.date.today()),
                    "current-week navigation should restore the actual current week",
                )
                window._p7_earnings_week_start = original_week_start
                window._p7_render_earnings_rows()
                window.p7_earnings_search_input.setText("no-match")
                app.processEvents()
                _assert(
                    all(not symbols for symbols in window.p7_earnings_day_card_symbols),
                    "search filter should remove non-matching weekly cards",
                )
                window.p7_earnings_search_input.clear()
                window.p7_earnings_changed_only_cb.setChecked(True)
                app.processEvents()
                _assert("A" in window.p7_earnings_day_card_symbols[day_index], "changed-only filter should keep changed rows")
                window.p7_earnings_export_llm_btn.click()
                app.processEvents()
                clipboard_text = app.clipboard().text()
                _assert("BUDGET TERMINAL - EARNINGS WEEK EXPORT" in clipboard_text, "LLM export should include an earnings heading")
                _assert("Monday-Friday" in clipboard_text, "LLM export should identify the business-week scope")
                _assert("A | A Corp." in clipboard_text, "LLM export should include the visible earnings row")
                _assert("DATE CHANGED" in clipboard_text, "LLM export should include changed-date markers")
                _assert("WKND" not in clipboard_text, "LLM export should not include weekend rows")
                _assert("\nSat " not in clipboard_text and "\nSun " not in clipboard_text, "LLM export should not include weekend headers")
            finally:
                WindowLifecycleMixin._schedule_startup_refresh = original_schedule_startup_refresh
                WindowLifecycleMixin._start_lazy_warmup = original_start_lazy_warmup
                CalendarPageMixin._p7_render_month = original_render_month
                CalendarPageMixin._p7_fetch_events = original_fetch_events
                CalendarPageMixin._p7_queue_market_holiday_year = original_queue_holidays
                try:
                    window.close()
                    app.processEvents()
                except Exception:
                    pass
        finally:
            _restore_user_data_path(original_path)


if __name__ == "__main__":
    test_symbol_universe_filter()
    test_yfinance_frame_parser()
    test_yfinance_pagination_dedupe()
    test_cache_round_trip_and_stale_fallback()
    test_completed_preservation_and_date_change_detection()
    test_calendar_earnings_tab_smoke()
    print("Earnings calendar cache smoke tests passed")
    sys.stdout.flush()
    os._exit(0)
