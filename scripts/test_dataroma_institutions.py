from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.compat import QApplication, QTableWidget, Qt
from budget_terminal_app.mixins.institutions import InstitutionsMixin
from budget_terminal_app.workers.dataroma import DataromaWorker


SAMPLE_ACTIVITY_PAYLOAD = {
    'facet': 'institution_activity',
    'active_period': 'Q1 2026',
    'buy_rows': [
        {
            'period': 'Q1 2026',
            'symbol': 'AAA',
            'company': 'Alpha | Beta',
            'manager': 'Example Manager',
            'activity': 'Buy',
            'share_change': '1,000',
            'approx_flow': '$1.34B',
            'hold_price': '$134.00',
            'change_to_portfolio': '15.26%',
            'source_url': 'https://example.test/buy',
        },
    ],
    'sell_rows': [
        {
            'period': 'Q1 2026',
            'symbol': 'BBB',
            'company': 'Beta Corp',
            'manager': 'Example Seller',
            'activity': 'Reduce 10.00%',
            'share_change': '500',
            'approx_flow': '$35.40M',
            'hold_price': '$70.80',
            'change_to_portfolio': '5.60%',
            'source_url': 'https://example.test/sell',
        },
    ],
    'manager_rows': [
        {
            'manager': 'Example Manager',
            'manager_id': 'EXM',
            'period': 'Q1 2026',
            'buy_count': 1,
            'sell_count': 1,
            'top_activity': ['AAA Buy', 'BBB Reduce 10.00%'],
            'source_url': 'https://example.test/manager',
        },
    ],
}


def assert_approx_flow_sorting() -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])
    try:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Symbol', 'Approx Inflow $'])

        class Probe(InstitutionsMixin):
            pass

        Probe()._p24_set_rows(
            table,
            [
                {'symbol': 'LOW', 'approx_flow': '$35.40M', 'approx_flow_value': 35_400_000.0},
                {'symbol': 'HIGH', 'approx_flow': '$1.34B', 'approx_flow_value': 1_340_000_000.0},
            ],
            [('Symbol', 'symbol'), ('Approx Inflow $', 'approx_flow')],
        )
        table.sortItems(1, Qt.SortOrder.DescendingOrder)
        assert table.item(0, 0).text() == 'HIGH', 'Expected billion-dollar flow to sort above million-dollar flow.'
        table.sortItems(1, Qt.SortOrder.AscendingOrder)
        assert table.item(0, 0).text() == 'LOW', 'Expected million-dollar flow to sort below billion-dollar flow.'
    finally:
        if owns_app:
            app.quit()


def assert_export_builders() -> None:
    class Probe(InstitutionsMixin):
        pass

    probe = Probe()
    buys_sells = probe._p24_build_buys_sells_export(SAMPLE_ACTIVITY_PAYLOAD)
    assert '# Institutions Buys/Sells Export' in buys_sells
    assert 'Active quarter: Q1 2026' in buys_sells
    assert 'Approximate dollar flow uses share change multiplied by DATAROMA Hold Price' in buys_sells
    assert '## Top Institutional Buying' in buys_sells
    assert '## Top Institutional Selling' in buys_sells
    assert 'period | symbol | company | manager | activity | share_change | approx_flow | hold_price | change_to_portfolio | source_url' in buys_sells
    assert 'Alpha / Beta' in buys_sells, 'Markdown table pipes should be escaped.'
    assert '$1.34B' in buys_sells
    assert '$35.40M' in buys_sells

    managers = probe._p24_build_superinvestors_export(SAMPLE_ACTIVITY_PAYLOAD)
    assert '# Institutions Superinvestors Export' in managers
    assert '## Superinvestors' in managers
    assert 'manager | id | period | buys | sells | top_activity | source_url' in managers
    assert 'Example Manager | EXM | Q1 2026 | 1 | 1 | AAA Buy, BBB Reduce 10.00% | https://example.test/manager' in managers


def assert_export_buttons_exist() -> None:
    from budget_terminal_app.app import BudgetTerminalApp
    from budget_terminal_app.dependencies import logger
    from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
    from budget_terminal_app.startup_profile import StartupProfiler

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])
    original_schedule = WindowLifecycleMixin._schedule_startup_refresh
    original_warmup = WindowLifecycleMixin._start_lazy_warmup
    WindowLifecycleMixin._schedule_startup_refresh = lambda self: None
    WindowLifecycleMixin._start_lazy_warmup = lambda self: None
    try:
        window = BudgetTerminalApp(startup_profiler=StartupProfiler(logger))
        for page in window._pages.values():
            page['on_show'] = None
            page['on_hide'] = None
        window.switch_page(23)
        assert hasattr(window, 'p24_export_activity_btn'), 'Expected Export Buys/Sells button.'
        assert hasattr(window, 'p24_export_managers_btn'), 'Expected Export Superinvestors button.'
        assert window.p24_export_activity_btn.text() == 'Export Buys/Sells'
        assert window.p24_export_managers_btn.text() == 'Export Superinvestors'
        window.close()
    finally:
        WindowLifecycleMixin._schedule_startup_refresh = original_schedule
        WindowLifecycleMixin._start_lazy_warmup = original_warmup
        if owns_app:
            app.quit()


def main() -> None:
    assert_approx_flow_sorting()
    assert_export_builders()
    assert_export_buttons_exist()

    activity = DataromaWorker.fetch('institution_activity', force=False, limit=10)
    buy_rows = activity.get('buy_rows') or []
    sell_rows = activity.get('sell_rows') or []
    manager_rows = activity.get('manager_rows') or []
    assert activity.get('active_period'), 'Expected an active DATAROMA activity period.'
    assert buy_rows, 'Expected institutional buy activity rows.'
    assert sell_rows, 'Expected institutional sell activity rows.'
    assert manager_rows, 'Expected superinvestor activity rows.'
    assert any(row.get('approx_flow') for row in buy_rows), 'Expected approximate inflow values.'
    assert any(row.get('approx_flow') for row in sell_rows), 'Expected approximate outflow values.'

    quarter = str(activity.get('active_period') or '')
    quarter_activity = DataromaWorker.fetch('institution_activity', force=False, limit=10, quarter=quarter)
    assert quarter_activity.get('active_period') == quarter, 'Expected selected quarter to load.'
    assert quarter_activity.get('buy_rows'), 'Expected selected-quarter buy rows.'
    assert quarter_activity.get('sell_rows'), 'Expected selected-quarter sell rows.'
    periods = [str(period or '') for period in list(activity.get('periods') or []) if str(period or '')]
    if len(periods) > 1:
        alternate_quarter = periods[1]
        alternate_activity = DataromaWorker.fetch('institution_activity', force=False, limit=10, quarter=alternate_quarter)
        assert alternate_activity.get('active_period') == alternate_quarter, 'Expected alternate quarter to load.'
        assert alternate_activity.get('buy_rows') or alternate_activity.get('sell_rows'), 'Expected alternate-quarter activity rows.'

    ticker = DataromaWorker.fetch('institution_ticker_activity', force=False, symbol='MSFT')
    ticker_rows = ticker.get('activity_rows') or []
    assert ticker.get('symbol') == 'MSFT', 'Expected ticker activity for MSFT.'
    assert ticker_rows, 'Expected MSFT ticker activity rows.'

    print(
        'DATAROMA institutions smoke passed: '
        f"{activity.get('active_period')} "
        f"buys={len(buy_rows)} sells={len(sell_rows)} managers={len(manager_rows)} "
        f"sample_inflow={buy_rows[0].get('approx_flow')} "
        f"sample_outflow={sell_rows[0].get('approx_flow')} "
        f"MSFT_activity={len(ticker_rows)}"
    )


if __name__ == '__main__':
    main()
