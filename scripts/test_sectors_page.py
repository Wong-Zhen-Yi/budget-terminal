from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt

from budget_terminal_app.constants import SECTOR_DATA
from budget_terminal_app.mixins.sectors import SectorTickerSnapshot
from budget_terminal_app.mixins.sectors_presenters import calculate_sector_stats, filter_sector_rows
from budget_terminal_app.sector_universe import (
    SECTORS_PAGE_DATA,
    SECTORS_PAGE_SOURCE_AS_OF,
    sectors_page_symbols,
    sectors_page_unique_symbols,
)
from scripts.test_tab_picker_search import _build_window


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_page_local_universe_contract() -> None:
    _assert(SECTORS_PAGE_SOURCE_AS_OF == "2026-07-09", "universe should retain its source date")
    _assert(len(SECTORS_PAGE_DATA) == 13, "Sectors page should expose 13 groups")
    _assert(sum(len(rows) for rows in SECTORS_PAGE_DATA.values()) == 260, "page should expose 260 memberships")
    _assert(len(sectors_page_unique_symbols()) == 253, "overlapping themes should dedupe to 253 fetch symbols")
    for sector, constituents in SECTORS_PAGE_DATA.items():
        symbols = [constituent.symbol for constituent in constituents]
        _assert(len(symbols) == 20, f"{sector} should contain exactly 20 equities")
        _assert(len(symbols) == len(set(symbols)), f"{sector} should not repeat symbols")
        _assert(
            all(re.fullmatch(r"[A-Z0-9-]+", symbol) for symbol in symbols),
            f"{sector} symbols should be Yahoo-compatible uppercase values",
        )
        _assert(all(constituent.name.strip() for constituent in constituents), f"{sector} should include company names")
    _assert(sectors_page_symbols("Financials")[0] == "BRK-B", "Berkshire should use Yahoo ticker syntax")
    _assert("IBIT" not in sectors_page_symbols("Crypto"), "Crypto group should be equities-only")
    _assert("GLD" not in sectors_page_symbols("Metals"), "Metals group should be equities-only")

    _assert(len(SECTOR_DATA["Technology"]) == 10, "shared Technology map should remain unchanged")
    _assert("ASML" in SECTOR_DATA["Technology"], "shared sector consumers should retain their current universe")
    _assert("IBIT" in SECTOR_DATA["Crypto"], "shared Crypto map should remain unchanged")


def test_sector_stats_and_filtering() -> None:
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    results = {
        "AAA": SimpleNamespace(price=10.0, change=2.0),
        "BBB": SimpleNamespace(price=20.0, change=-1.0),
        "CCC": SimpleNamespace(price=30.0, change=0.0),
        "DDD": SimpleNamespace(price=None, change=3.0),
        "EEE": SimpleNamespace(price=50.0, change=None),
    }
    stats = calculate_sector_stats(symbols, results)
    _assert(stats.total == 5, "stats should preserve sector membership count")
    _assert(stats.quote_count == 4, "coverage should count available prices")
    _assert(stats.average_change == 1.0, "average should be equal-weighted across available changes")
    _assert((stats.advancers, stats.decliners, stats.unchanged) == (2, 1, 1), "breadth should classify changes")
    _assert(stats.leaders == (("DDD", 3.0), ("AAA", 2.0)), "leaders should be ordered descending")
    _assert(stats.laggards == (("BBB", -1.0), ("CCC", 0.0)), "laggards should be ordered ascending")

    technology = SECTORS_PAGE_DATA["Technology"]
    _assert([row.symbol for row in filter_sector_rows(technology, "crowd")] == ["CRWD"], "company filtering should work")
    _assert([row.symbol for row in filter_sector_rows(technology, "NVDA")] == ["NVDA"], "ticker filtering should work")
    _assert(len(filter_sector_rows(technology, "")) == 20, "empty filter should retain every constituent")


def _fake_results() -> dict[str, SectorTickerSnapshot]:
    results = {}
    for index, symbol in enumerate(sectors_page_unique_symbols()):
        change = float((index % 9) - 4)
        results[symbol] = SectorTickerSnapshot(
            price=50.0 + index,
            change=change,
            mkt_cap=float(index + 1) * 1_000_000_000.0,
        )
    return results


def test_offscreen_sectors_workspace() -> None:
    app, window = _build_window()
    try:
        window._p8_request_refresh = lambda *args, **kwargs: False
        window.switch_page(5)
        window._p8_request_detail_market_caps = lambda *args, **kwargs: False
        window.resize(1280, 800)
        window.show()
        app.processEvents()

        window._p8_complete_refresh(_fake_results())
        window._p8_select_sector("Technology")
        app.processEvents()

        _assert(not window.p8_main_splitter.childrenCollapsible(), "Sectors panes should not collapse")
        _assert(all(size > 0 for size in window.p8_main_splitter.sizes()), "both Sectors panes should remain visible")
        _assert(window.p8_detail_table.rowCount() == 20, "selected sector should render every constituent")
        _assert(
            window.p8_detail_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            "detail rows should use vertical scrolling",
        )
        _assert(window.p8_detail_table.verticalScrollBar().maximum() > 0, "20 rows should be reachable through scrolling")
        _assert(window.p8_detail_table.horizontalScrollBar().maximum() == 0, "detail table should avoid horizontal overflow")
        _assert(window.p8_summary_labels["coverage"].text() == "260/260", "summary should report membership coverage")
        _assert("253 unique symbols" in window.p8_status_lbl.text(), "status should distinguish unique fetch symbols")

        window.p8_detail_table.sortItems(3, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        sorted_changes = [
            float(window.p8_detail_table.item(row, 3).data(Qt.ItemDataRole.UserRole))
            for row in range(window.p8_detail_table.rowCount())
        ]
        _assert(sorted_changes == sorted(sorted_changes, reverse=True), "Day % should sort numerically")

        window.p8_detail_filter.setText("Crowd")
        app.processEvents()
        _assert(window.p8_detail_table.rowCount() == 1, "company filter should narrow the detail table")
        _assert(window.p8_detail_table.item(0, 0).text() == "CRWD", "filter should retain the matching ticker")
        window._p8_complete_refresh(_fake_results())
        app.processEvents()
        _assert(window.p8_detail_filter.text() == "Crowd", "data refresh should preserve the active filter")
        _assert(window.p8_detail_table.rowCount() == 1, "refresh should preserve filtered rows")
        window._p8_select_sector("Financials")
        app.processEvents()
        _assert(window.p8_detail_filter.text() == "", "changing sector should clear the detail filter")
        _assert(window.p8_detail_table.rowCount() == 20, "new sector should show all rows after filter reset")

        window._p8_on_market_caps_ready(
            {
                "BRK-B": {
                    "symbol": "BRK-B",
                    "quote_type": "EQUITY",
                    "size_type": "market_cap",
                    "size_value": 9_000_000_000_000.0,
                }
            }
        )
        app.processEvents()
        _assert(
            window._p8_all_results["BRK-B"].mkt_cap == 9_000_000_000_000.0,
            "typed market-cap payload should unwrap to the numeric Sectors value",
        )
        window.p8_detail_table.sortItems(4, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        _assert(window.p8_detail_table.item(0, 0).text() == "BRK-B", "market cap should sort numerically after updates")

        selected = []
        window._p8_analyze_ticker = selected.append
        window._p8_on_detail_double_click(window.p8_detail_table.model().index(0, 0))
        _assert(selected == [window.p8_detail_table.item(0, 0).text()], "double-click should keep Charts navigation contract")

        window._apply_sectors_theme()
        app.processEvents()
        _assert(window.p8_detail_table.rowCount() == 20, "theme refresh should preserve detail rows")

        window.resize(900, 600)
        app.processEvents()
        window._p8_relayout_cards()
        app.processEvents()
        _assert(all(size > 0 for size in window.p8_main_splitter.sizes()), "narrow layout should keep both panes usable")
        _assert(window.p8_detail_table.horizontalScrollBar().maximum() == 0, "narrow layout should still fit table columns")
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def main() -> None:
    test_page_local_universe_contract()
    test_sector_stats_and_filtering()
    test_offscreen_sectors_workspace()
    print("sectors page smoke passed")


if __name__ == "__main__":
    main()
