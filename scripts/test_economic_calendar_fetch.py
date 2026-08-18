from __future__ import annotations

import datetime
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import budget_terminal_app.workers.calendar as calendar_module


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _event_names(events: list[tuple[datetime.date, str, str]]) -> set[str]:
    return {name for _event_date, name, _importance in events}


def _test_source_parsers() -> None:
    original_http_get = calendar_module._http_get_text
    try:
        calendar_module._http_get_text = lambda _url: '''
            <main>
              <p>2026 FOMC Meetings</p>
              <p>January</p><p>27-28</p>
              <p>March</p><p>17-18*</p>
              <p>2027 FOMC Meetings</p>
            </main>
        '''
        _assert(
            calendar_module._fetch_fomc_events_for_year(2026) == [
                (datetime.date(2026, 1, 28), 'FOMC Decision', 'high'),
                (datetime.date(2026, 3, 18), 'FOMC Decision', 'high'),
            ],
            'FOMC parser should retain the decision date from each official meeting range',
        )
    finally:
        calendar_module._http_get_text = original_http_get

    bls_events = calendar_module._parse_bls_schedule_events(
        '''
        <main>
          <p>Tuesday, January 13, 2026</p><p>08:30 AM</p><p>Consumer Price Index for December 2025</p>
          <p>Friday, February 06, 2026</p><p>08:30 AM</p><p>Employment Situation for January 2026</p>
          <p>Thursday, February 12, 2026</p><p>08:30 AM</p><p>Producer Price Index for January 2026</p>
          <p>Tuesday, March 03, 2026</p><p>10:00 AM</p><p>Job Openings and Labor Turnover Survey for January 2026</p>
          <p>Thursday, March 05, 2026</p><p>10:00 AM</p><p>State Employment and Unemployment (Monthly) for January 2026</p>
        </main>
        ''',
        2026,
    )
    _assert(
        bls_events == [
            (datetime.date(2026, 1, 13), 'CPI Release', 'high'),
            (datetime.date(2026, 2, 6), 'Jobs Report', 'high'),
            (datetime.date(2026, 2, 12), 'PPI Release', 'medium'),
            (datetime.date(2026, 3, 3), 'JOLTS Report', 'medium'),
        ],
        'BLS parser should retain only the selected national releases',
    )

    fred_fixture_template = '''
    <table class="table table-condensed table-standard-theme">
      <tbody>
        <tr><td colspan="2"><span style="font-weight: bold;">Monday December 15, 2025</span></td></tr>
        <tr><td>7:30 am</td><td><a href="/release?rid={release_id}">{source_name}</a></td></tr>
        <tr><td colspan="2"><span style="font-weight: bold;">{release_date}</span><span>Updated</span></td></tr>
        <tr><td>7:30 am</td><td><a href="/release?rid={release_id}">{source_name}</a></td></tr>
      </tbody>
    </table>
    '''
    fred_cases = [
        (10, 'Consumer Price Index', 'CPI Release', 'high', 'Tuesday July 14, 2026', datetime.date(2026, 7, 14)),
        (46, 'Producer Price Index', 'PPI Release', 'medium', 'Wednesday July 15, 2026', datetime.date(2026, 7, 15)),
        (50, 'Employment Situation', 'Jobs Report', 'high', 'Friday August 07, 2026', datetime.date(2026, 8, 7)),
        (
            192,
            'Job Openings and Labor Turnover Survey',
            'JOLTS Report',
            'medium',
            'Tuesday August 04, 2026',
            datetime.date(2026, 8, 4),
        ),
    ]
    for release_id, source_name, event_name, importance, release_date, expected_date in fred_cases:
        fred_events = calendar_module._parse_fred_release_calendar_events(
            fred_fixture_template.format(
                release_id=release_id,
                source_name=source_name,
                release_date=release_date,
            ),
            2026,
            source_name=source_name,
            event_name=event_name,
            importance=importance,
        )
        _assert(
            fred_events == [(expected_date, event_name, importance)],
            f'FRED parser should normalize and year-filter {event_name}',
        )

    bea_events = calendar_module._parse_bea_schedule_events(
        '''
        <main>
          <p>Year 2026</p>
          <p>January 29</p><p>GDP (Advance Estimate), 4th Quarter and Year 2025</p>
          <p>February 27</p><p>GDP (Second Estimate), 4th Quarter and Year 2025</p>
          <p>March 27</p><p>Gross Domestic Product, 4th Quarter 2025 (Third Estimate)</p>
          <p>April 30</p><p>Personal Income and Outlays, March 2026</p>
          <p>May 01</p><p>Gross Domestic Product by State and Personal Income by State, 4th Quarter 2025</p>
        </main>
        ''',
        2026,
    )
    _assert(
        bea_events == [
            (datetime.date(2026, 1, 29), 'GDP Report', 'high'),
            (datetime.date(2026, 2, 27), 'GDP Report', 'high'),
            (datetime.date(2026, 3, 27), 'GDP Report', 'high'),
            (datetime.date(2026, 4, 30), 'PCE Inflation', 'medium'),
        ],
        'BEA parser should retain all GDP estimates and PCE releases',
    )

    census_events = calendar_module._parse_census_schedule_events(
        '''
        <table>
          <tr><th>Indicator</th><th>Release Date</th></tr>
          <tr><td>Advance Monthly Sales for Retail and Food Services</td><td>January 14, 2026</td></tr>
          <tr><td>Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders</td><td>January 27, 2026</td></tr>
          <tr><td>New Residential Construction (Building Permits, Housing Starts, and Housing Completions)</td><td>February 19, 2026</td></tr>
          <tr><td>New Residential Sales</td><td>February 25, 2026</td></tr>
          <tr><td>Monthly Wholesale Trade: Sales and Inventories</td><td>February 26, 2026</td></tr>
          <tr><td>New Residential Sales</td><td>not a date</td></tr>
        </table>
        ''',
        2026,
    )
    _assert(
        census_events == [
            (datetime.date(2026, 1, 14), 'Retail Sales', 'high'),
            (datetime.date(2026, 1, 27), 'Durable Goods Report', 'medium'),
            (datetime.date(2026, 2, 19), 'Housing Starts & Permits', 'medium'),
            (datetime.date(2026, 2, 25), 'New Home Sales', 'medium'),
        ],
        'Census parser should retain only the selected market-moving releases',
    )


def _test_cache_version_and_stale_category_merge() -> None:
    original_user_data_path = calendar_module.user_data_path
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _temp_user_data_path(*parts: Any) -> Path:
                path = root.joinpath(*map(str, parts))
                path.parent.mkdir(parents=True, exist_ok=True)
                return path

            calendar_module.user_data_path = _temp_user_data_path
            with calendar_module._ECONOMIC_EVENTS_CACHE_LOCK:
                calendar_module._ECONOMIC_EVENTS_MEMORY_CACHE.clear()

            path = calendar_module._economic_cache_path_for_year(2026)
            path.write_text(
                json.dumps({'year': 2026, 'calendar_version': 2, 'fetched_at': 1, 'events': []}),
                encoding='utf-8',
            )
            _assert(calendar_module._load_economic_events_cache(2026) is None, 'old cache payloads should be invalidated')

            saved_events = [(datetime.date(2026, 1, 13), 'CPI Release', 'high')]
            calendar_module._save_economic_events_cache(2026, saved_events)
            cached = calendar_module._load_economic_events_cache(2026)
            _assert(cached is not None and cached[0] == saved_events, 'current cache payload should round-trip')
            payload = json.loads(path.read_text(encoding='utf-8'))
            _assert(payload['calendar_version'] == calendar_module._ECONOMIC_EVENTS_CACHE_VERSION, 'cache should record its schema version')
    finally:
        calendar_module.user_data_path = original_user_data_path
        with calendar_module._ECONOMIC_EVENTS_CACHE_LOCK:
            calendar_module._ECONOMIC_EVENTS_MEMORY_CACHE.clear()

    merged = calendar_module._merge_missing_economic_categories(
        [(datetime.date(2026, 1, 13), 'CPI Release', 'high')],
        [
            (datetime.date(2026, 1, 13), 'CPI Release', 'high'),
            (datetime.date(2026, 2, 6), 'Jobs Report', 'high'),
        ],
    )
    _assert(_event_names(merged) == {'CPI Release', 'Jobs Report'}, 'partial refreshes should retain missing stale categories')


def _test_bls_fred_fallback_routing() -> None:
    original_bls_fetch = calendar_module._fetch_bls_events_for_year
    original_fred_fetch = calendar_module._fetch_fred_bls_fallback_events_for_year
    fallback_rows = {
        'CPI Release': (datetime.date(2026, 7, 14), 'CPI Release', 'high'),
        'PPI Release': (datetime.date(2026, 7, 15), 'PPI Release', 'medium'),
        'Jobs Report': (datetime.date(2026, 8, 7), 'Jobs Report', 'high'),
        'JOLTS Report': (datetime.date(2026, 8, 4), 'JOLTS Report', 'medium'),
    }
    requested_categories: list[set[str]] = []

    def _fake_fred_fetch(_year: Any, missing_names: set[str]) -> list[tuple[datetime.date, str, str]]:
        requested_categories.append(set(missing_names))
        return [fallback_rows[name] for name in sorted(missing_names)]

    try:
        calendar_module._fetch_fred_bls_fallback_events_for_year = _fake_fred_fetch
        calendar_module._fetch_bls_events_for_year = lambda _year: []
        complete_fallback = calendar_module._fetch_bls_events_with_fred_fallback(2026)
        _assert(
            _event_names(complete_fallback) == set(fallback_rows),
            'a complete BLS failure should restore all four core categories from FRED',
        )
        _assert(requested_categories[-1] == set(fallback_rows), 'complete BLS failure should request every fallback category')

        bls_cpi = (datetime.date(2026, 7, 13), 'CPI Release', 'high')
        calendar_module._fetch_bls_events_for_year = lambda _year: [bls_cpi, bls_cpi]
        partial_fallback = calendar_module._fetch_bls_events_with_fred_fallback(2026)
        _assert('CPI Release' not in requested_categories[-1], 'FRED should not replace a category supplied by BLS')
        _assert(
            [event for event in partial_fallback if event[1] == 'CPI Release'] == [bls_cpi],
            'BLS dates should retain precedence and duplicate rows should be removed',
        )
        _assert(
            _event_names(partial_fallback) == set(fallback_rows),
            'partial BLS results should fill only missing core categories',
        )
    finally:
        calendar_module._fetch_bls_events_for_year = original_bls_fetch
        calendar_module._fetch_fred_bls_fallback_events_for_year = original_fred_fetch


def _test_monthly_event_pipeline() -> None:
    original_year_fetch = calendar_module._get_economic_events_for_year
    try:
        calendar_module._get_economic_events_for_year = lambda _year: [
            (datetime.date(2026, 7, 14), 'CPI Release', 'high'),
            (datetime.date(2026, 7, 15), 'PPI Release', 'medium'),
            (datetime.date(2026, 8, 7), 'Jobs Report', 'high'),
        ]
        _assert(
            calendar_module._get_economic_events(2026, 7) == [
                (datetime.date(2026, 7, 14), 'CPI Release', 'high'),
                (datetime.date(2026, 7, 15), 'PPI Release', 'medium'),
            ],
            'monthly Calendar consumers should receive CPI and PPI through the existing event pipeline',
        )
    finally:
        calendar_module._get_economic_events_for_year = original_year_fetch


def main() -> None:
    _test_source_parsers()
    _test_cache_version_and_stale_category_merge()
    _test_bls_fred_fallback_routing()
    _test_monthly_event_pipeline()
    print('Economic calendar fetch smoke tests passed')


if __name__ == '__main__':
    main()
