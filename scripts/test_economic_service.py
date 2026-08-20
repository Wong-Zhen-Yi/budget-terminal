from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.mixins import economic_presenters as presenters
from budget_terminal_app.services import economic

# A realistic FRED body: the newer 'observation_date' header, and the '.' sentinel FRED writes
# for an observation that does not exist yet.
CPI_CSV = """observation_date,CPIAUCSL
2023-01-01,300.000
2023-07-01,305.000
2024-01-01,309.000
2024-07-01,.
2024-08-01,312.000
"""

# The legacy 'DATE' header is still served for some series, so both must parse.
LEGACY_CSV = """DATE,DGS10
2024-08-01,4.10
2024-08-02,4.25
"""

# Treasury serves MM/DD/YYYY newest-first, with a blank where a tenor was not auctioned, and
# the column set changes between years ('4 Mo' did not exist before 2022).
TREASURY_CSV = """Date,"1 Mo","3 Mo","4 Mo","2 Yr","10 Yr"
08/19/2026,3.77,3.86,3.88,4.19,4.65
08/18/2026,3.75,3.84,,4.17,4.60
"""

TREASURY_REAL_CSV = """Date,"5 YR","10 YR"
08/19/2026,2.07,2.35
08/18/2026,2.05,2.30
"""

UMICH_CSV = """Month,YYYY,ICS_ALL
January,2026,58.1
February,2026,55.2
Notamonth,2026,99.9
"""

NYFED_JSON = """{"refRates":[
 {"effectiveDate":"2026-08-18","type":"EFFR","percentRate":3.63},
 {"effectiveDate":"2026-08-17","type":"EFFR","percentRate":3.62},
 {"effectiveDate":"2026-08-14","type":"EFFR","percentRate":null}
]}"""

BLS_PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "series": [
            {
                "seriesID": "LNS14000000",
                "data": [
                    {"year": "2026", "period": "M07", "value": "4.1"},
                    {"year": "2026", "period": "M06", "value": "4.2"},
                    {"year": "2025", "period": "M13", "value": "4.0"},
                    {"year": "2025", "period": "M07", "value": "4.3"},
                ],
            },
            {
                "seriesID": "CES0000000001",
                "data": [{"year": "2026", "period": "M07", "value": "158,858"}],
            },
        ]
    },
}


def test_parse_treasury_csv_by_column_name() -> None:
    curve = parse = economic.parse_treasury_csv(TREASURY_CSV)
    assert set(curve) == {"1 Mo", "3 Mo", "4 Mo", "2 Yr", "10 Yr"}
    # The file is newest-first; every consumer downstream assumes ascending dates.
    assert curve["10 Yr"] == [("2026-08-18", 4.60), ("2026-08-19", 4.65)]
    # A blank tenor is dropped for that date only, not for the whole column.
    assert curve["4 Mo"] == [("2026-08-19", 3.88)]
    assert economic.parse_treasury_csv("") == {}
    assert parse is curve


def test_align_difference_only_uses_shared_dates() -> None:
    nominal = economic.parse_treasury_csv(TREASURY_CSV)
    real = economic.parse_treasury_csv(TREASURY_REAL_CSV)
    breakeven = economic.align_difference(nominal["10 Yr"], real["10 YR"])
    assert [round(value, 4) for _stamp, value in breakeven] == [2.30, 2.30]
    # A date present on only one side cannot yield a difference, so it is skipped rather than
    # silently paired with the nearest other observation.
    assert economic.align_difference([("2024-01-01", 5.0)], [("2024-01-02", 2.0)]) == []


def test_parse_bls_payload_maps_period_codes() -> None:
    parsed = economic.parse_bls_payload(BLS_PAYLOAD)
    # M13 is the annual average, not a monthly observation; it must not land on a real month.
    assert parsed["LNS14000000"] == [
        ("2025-07-01", 4.3),
        ("2026-06-01", 4.2),
        ("2026-07-01", 4.1),
    ]
    # BLS thousands separators must survive the float coercion.
    assert parsed["CES0000000001"] == [("2026-07-01", 158858.0)]
    assert economic.parse_bls_payload({}) == {}
    assert economic._bls_period_to_date("2026", "Q03") == "2026-09-01"
    assert economic._bls_period_to_date("2026", "S01") is None
    assert economic._bls_period_to_date("nope", "M01") is None


def test_parse_nyfed_and_umich() -> None:
    rates = economic.parse_nyfed_rates(NYFED_JSON)
    assert rates == [("2026-08-17", 3.62), ("2026-08-18", 3.63)]
    assert economic.parse_nyfed_rates("not json") == []

    sentiment = economic.parse_umich_csv(UMICH_CSV)
    assert sentiment == [("2026-01-01", 58.1), ("2026-02-01", 55.2)]
    assert economic.parse_umich_csv("") == []


def test_parse_fred_csv_drops_missing_sentinels() -> None:
    points = economic.parse_fred_csv(CPI_CSV)
    # The '.' row must not survive as a NaN: a NaN latest value would render as a real number
    # in the table and poison every change calculation downstream.
    assert [stamp for stamp, _value in points] == ['2023-01-01', '2023-07-01', '2024-01-01', '2024-08-01']
    assert points[-1][1] == 312.0

    legacy = economic.parse_fred_csv(LEGACY_CSV)
    assert legacy == [('2024-08-01', 4.10), ('2024-08-02', 4.25)]

    # An empty or malformed body degrades to no data rather than raising.
    assert economic.parse_fred_csv('') == []
    assert economic.parse_fred_csv('not,a,real\nbody') != [('x', 1.0)]


def test_latest_and_prior_handles_short_series() -> None:
    assert economic.latest_and_prior([]) == (None, None)
    assert economic.latest_and_prior(None) == (None, None)
    latest, prior = economic.latest_and_prior([('2024-01-01', 1.0)])
    assert latest == ('2024-01-01', 1.0) and prior is None
    latest, prior = economic.latest_and_prior([('2024-01-01', 1.0), ('2024-02-01', 2.0)])
    assert latest == ('2024-02-01', 2.0) and prior == ('2024-01-01', 1.0)


def test_yoy_transform_uses_dates_not_index_offsets() -> None:
    points = economic.parse_fred_csv(CPI_CSV)
    # 2024-01-01 against 2023-01-01 is exactly a year apart: 300 -> 309 is +3%.
    transformed = economic.apply_transform(points, economic.TRANSFORM_YOY_PCT, frequency='monthly')
    by_date = dict(transformed)
    assert round(by_date['2024-01-01'], 4) == 3.0
    # 2023-01-01 has no year-ago partner in this fixture, so it is dropped rather than paired
    # with an arbitrary earlier row.
    assert '2023-01-01' not in by_date
    # 2024-08-01 is thirteen months past 2023-07-01, outside the monthly tolerance, so the gap
    # left by the '.' row does not silently become a fourteen-month "year".
    assert '2024-08-01' not in by_date

    # A quarterly series has to look four periods back, which index arithmetic tuned for
    # monthly data would get wrong.
    quarterly = [
        ('2023-03-31', 100.0),
        ('2023-06-30', 101.0),
        ('2023-09-30', 102.0),
        ('2023-12-31', 103.0),
        ('2024-03-31', 110.0),
    ]
    assert round(economic.yoy_change(quarterly, frequency='quarterly'), 4) == 10.0


def test_mom_and_saar_transforms() -> None:
    payrolls = [('2024-06-01', 158_000.0), ('2024-07-01', 158_150.0)]
    diff = economic.apply_transform(payrolls, economic.TRANSFORM_MOM_DIFF, frequency='monthly')
    assert diff == [('2024-07-01', 150.0)]

    gdp = [('2024-03-31', 100.0), ('2024-06-30', 101.0)]
    saar = economic.apply_transform(gdp, economic.TRANSFORM_QOQ_SAAR, frequency='quarterly')
    # A 1% quarter compounds to roughly 4.06% annualized, not 4.00%.
    assert round(saar[0][1], 2) == 4.06

    # A zero base cannot produce a percent change; the point is dropped, not turned into inf.
    assert economic.apply_transform([('2024-01-01', 0.0), ('2024-02-01', 5.0)], economic.TRANSFORM_MOM_PCT) == []


def test_build_row_survives_an_empty_series() -> None:
    series = economic.SERIES_BY_ID['UNRATE']
    row = economic.build_row(series, [])
    assert row['series_id'] == 'UNRATE'
    assert row['latest'] is None and row['prior'] is None and row['change'] is None
    assert row['history'] == []
    # Formatting a missing value must not crash the table render.
    assert economic.format_value(row['latest'], row['units'], row['decimals']) == '—'


def test_build_yield_curve_orders_tenors_and_flags_inversion() -> None:
    rows = [
        economic.build_row(economic.SERIES_BY_ID['DGS10'], [('2024-08-01', 3.90)]),
        economic.build_row(economic.SERIES_BY_ID['DGS3MO'], [('2024-08-01', 5.30)]),
        economic.build_row(economic.SERIES_BY_ID['DGS2'], [('2024-08-01', 4.40)]),
        # A dead tenor must be skipped rather than plotted at zero.
        economic.build_row(economic.SERIES_BY_ID['DGS30'], []),
    ]
    curve = economic.build_yield_curve(rows)
    assert [item['series_id'] for item in curve['tenors']] == ['DGS3MO', 'DGS2', 'DGS10']
    assert round(curve['spread_10y2y'], 4) == -0.5
    assert curve['inverted_2s10s'] is True
    assert curve['inverted_3m10y'] is True

    normal = economic.build_yield_curve([
        economic.build_row(economic.SERIES_BY_ID['DGS2'], [('2024-08-01', 3.50)]),
        economic.build_row(economic.SERIES_BY_ID['DGS10'], [('2024-08-01', 4.10)]),
    ])
    assert normal['inverted_2s10s'] is False
    # 3M is absent here, so its spread stays unknown instead of defaulting to "not inverted".
    assert normal['spread_10y3m'] is None
    assert economic.build_yield_curve([])['tenors'] == []


def test_format_value_and_change_per_unit() -> None:
    assert economic.format_value(3.14159, 'percent', 2) == '3.14%'
    assert economic.format_value(158_150.0, 'thousands', 0) == '158,150K'
    assert economic.format_value(7_600_000.0, 'millions', 0) == '$7,600.0B'
    assert economic.format_value(221_000.0, 'count', 0) == '221,000'
    assert economic.format_value(103.4, 'index', 1) == '103.4'
    assert economic.format_value(None, 'percent', 1) == '—'
    assert economic.format_value(float('nan'), 'percent', 1) == '—'

    assert economic.format_change(0.2, 'percent', 1) == '+0.2 pp'
    assert economic.format_change(-0.2, 'percent', 1) == '-0.2 pp'
    assert economic.format_change(150.0, 'thousands', 0) == '+150K'
    assert economic.format_change(None, 'percent', 1) == '—'


def test_normalize_groups_and_catalog_integrity() -> None:
    assert economic.normalize_groups(None) == economic.ECONOMIC_GROUPS
    assert economic.normalize_groups([]) == economic.ECONOMIC_GROUPS
    assert economic.normalize_groups('Rates') == ('Rates',)
    assert economic.normalize_groups(['Nonsense']) == economic.ECONOMIC_GROUPS
    # The requested order never overrides catalog order, so the cache key stays stable.
    assert economic.normalize_groups(['Rates', 'Inflation']) == ('Inflation', 'Rates')

    ids = [series.series_id for series in economic.ECONOMIC_SERIES]
    assert len(ids) == len(set(ids)), 'duplicate FRED series id in the catalog'
    for series in economic.ECONOMIC_SERIES:
        assert series.group in economic.ECONOMIC_GROUPS, series.series_id
        assert series.transform in economic.ECONOMIC_TRANSFORMS, series.series_id
        assert series.provider in economic.ECONOMIC_PROVIDERS, series.series_id
        # Every non-FRED provider resolves by its own identifier, so an empty key would
        # silently return nothing instead of failing loudly.
        if series.provider != economic.PROVIDER_FRED:
            assert series.provider_key, series.series_id
        if series.provider in (economic.PROVIDER_TREASURY_SPREAD, economic.PROVIDER_TREASURY_BREAKEVEN):
            assert '|' in series.provider_key, series.series_id
    # The headline strip must not depend on FRED, which some networks cannot reach.
    for series_id in economic.HEADLINE_SERIES:
        assert economic.SERIES_BY_ID[series_id].provider != economic.PROVIDER_FRED, series_id
    # Every headline tile must resolve to a real catalog entry.
    for series_id in economic.HEADLINE_SERIES:
        assert series_id in economic.SERIES_BY_ID, series_id
    # The curve needs at least the two tenors the spread readouts are built from.
    curve_ids = {series.series_id for series in economic.YIELD_CURVE_SERIES}
    assert {'DGS2', 'DGS3MO', 'DGS10'} <= curve_ids


def test_fetch_uses_the_cache_and_isolates_failures() -> None:
    with tempfile.TemporaryDirectory(prefix='budget-terminal-economic-') as tmp:
        cache = CacheManager(db_path=str(Path(tmp) / 'cache.db'))
        service = economic.EconomicDataService(cache)
        calls: list[str] = []

        def fake_fetcher(series_id: str) -> list[tuple[str, float]]:
            calls.append(series_id)
            if series_id == 'UNRATE':
                # One dead series must land in `missing`, not blank the payload.
                raise RuntimeError('series retired')
            return [('2024-07-01', 4.0), ('2024-08-01', 4.2)]

        payload = service.fetch(groups=['Labor'], force=True, fetcher=fake_fetcher)
        labor_ids = [s.series_id for s in economic.ECONOMIC_SERIES if s.group == 'Labor']
        assert sorted(calls) == sorted(labor_ids)
        assert payload['missing'] == ['UNRATE']
        assert len(payload['rows']) == len(labor_ids)
        assert 'BLS' in payload['source'] and 'Treasury' in payload['source']

        # A non-forced fetch inside the TTL must serve the cache without touching the network.
        calls.clear()
        again = service.fetch(groups=['Labor'], force=False, fetcher=fake_fetcher)
        assert calls == []
        assert again['generated_at'] == payload['generated_at']

        # Forcing goes back out even though the cache is fresh.
        calls.clear()
        service.fetch(groups=['Labor'], force=True, fetcher=fake_fetcher)
        assert sorted(calls) == sorted(labor_ids)

        # A payload older than the stale ceiling is discarded rather than shown.
        key = economic.EconomicDataService._payload_cache_key(['Labor'])
        with cache._connect() as conn:
            conn.execute(
                'UPDATE json_payload_cache SET last_updated = ? WHERE namespace = ? AND cache_key = ?',
                ('2000-01-01T00:00:00', economic.ECONOMIC_PAYLOAD_CACHE_NAMESPACE, key),
            )
            conn.commit()
        assert service.load_cached_payload(['Labor']) is None


def test_blackout_stops_early_and_keeps_the_cached_payload() -> None:
    with tempfile.TemporaryDirectory(prefix='budget-terminal-economic-blackout-') as tmp:
        cache = CacheManager(db_path=str(Path(tmp) / 'cache.db'))
        service = economic.EconomicDataService(cache)
        good = [('2024-07-01', 4.0), ('2024-08-01', 4.2)]
        service.fetch(groups=['Labor'], force=True, fetcher=lambda series_id: good)

        calls: list[str] = []

        def dead(series_id: str) -> list[tuple[str, float]]:
            calls.append(series_id)
            raise TimeoutError('FRED unreachable')

        payload = service.fetch(groups=['Labor'], force=True, fetcher=dead)
        labor_count = len([s for s in economic.ECONOMIC_SERIES if s.group == 'Labor'])
        # The good cached payload survives rather than being replaced by an empty one.
        assert payload['rows'] and payload['rows'][0]['latest'] is not None
        assert payload['missing'] == []

        # Across the whole catalog the breaker has to bite well short of one call per series:
        # the probe, plus whatever the pool had already dispatched before it tripped.
        calls.clear()
        empty_service = economic.EconomicDataService(None)
        blackout = empty_service.fetch(force=True, fetcher=dead)
        ceiling = 1 + economic.FRED_BLACKOUT_THRESHOLD + economic.MAX_WORKERS
        assert len(calls) <= ceiling < len(economic.ECONOMIC_SERIES)

        # A blackout still returns a usable (if empty) payload rather than raising.
        assert len(blackout['missing']) == len(economic.ECONOMIC_SERIES)
        assert blackout['rows'] and all(not row['available'] for row in blackout['rows'])
        assert blackout['yield_curve']['tenors'] == []
        assert labor_count > 0


def test_presenters_build_rows_without_qt() -> None:
    colors = {
        'positive': '#00aa00',
        'negative': '#aa0000',
        'warning': '#aa8800',
        'secondary': '#888888',
        'accent': '#0088ff',
    }
    rows = [
        economic.build_row(economic.SERIES_BY_ID['UNRATE'], [('2024-06-01', 4.0), ('2024-07-01', 4.3)]),
        economic.build_row(economic.SERIES_BY_ID['DGS10'], [('2024-08-01', 4.10), ('2024-08-02', 4.25)]),
    ]

    overview = presenters.build_overview_rows(rows, colors=colors)
    assert len(overview) == 2
    assert len(overview[0]) == len(presenters.OVERVIEW_HEADERS)
    # The Source column tells the user which provider each number came from.
    assert overview[0][-1].text == economic.SERIES_BY_ID['UNRATE'].source_label
    assert 'BLS' in overview[0][-1].text
    # A rising unemployment rate is unhelpful, so its change must be painted negative.
    assert overview[0][5].foreground == colors['negative']
    # Every cell in a sortable column carries a finite payload; one None would downgrade the
    # whole column to string comparison.
    for row in overview:
        for cell in row[2:]:
            if cell.sort_value is not None:
                assert cell.sort_value == cell.sort_value

    # `higher_is_better is None` means the direction carries no judgement, so it stays neutral.
    neutral = economic.build_row(economic.SERIES_BY_ID['M2SL'], [('2023-08-01', 100.0), ('2024-08-01', 103.0)])
    assert presenters.build_overview_rows([neutral], colors=colors)[0][5].foreground is None

    group_rows = presenters.build_group_rows(presenters.rows_for_group(rows, 'Rates'), colors=colors)
    assert len(group_rows) == 1
    assert len(group_rows[0]) == len(presenters.GROUP_HEADERS)

    assert presenters.filter_rows(rows, 'labor') == [rows[0]]
    assert presenters.filter_rows(rows, 'all') == rows
    assert presenters.search_rows(rows, 'DGS') == [rows[1]]
    assert presenters.search_rows(rows, 'unemployment') == [rows[0]]
    assert presenters.search_rows(rows, '') == rows

    curve = economic.build_yield_curve(rows)
    curve_rows = presenters.build_curve_rows(curve, colors=colors)
    assert len(curve_rows) == 1 and len(curve_rows[0]) == len(presenters.CURVE_HEADERS)
    assert 'Treasury curve' in presenters.describe_curve({}) or presenters.describe_curve({})

    headlines = presenters.summarize_headlines({'rows': rows})
    assert headlines['UNRATE'] == '4.3%'
    # A headline whose series is absent from the payload still gets a placeholder.
    assert set(headlines) == set(economic.HEADLINE_SERIES)
    assert headlines['PAYEMS'] == '—'

    assert presenters.missing_summary({'missing': []}) == ''
    dead_row = economic.build_row(economic.SERIES_BY_ID['GDPC1'], [])
    summary = presenters.missing_summary({
        'missing': ['GDPC1'],
        'rows': [dead_row],
        'unreachable': [economic.PROVIDER_FRED],
    })
    # The footer has to name the provider that owes the data, not just the count, because that
    # is what tells the user whether it is their network or a stale release.
    assert 'FRED' in summary and '1 series unavailable' in summary

    # Rows a provider never returned are hidden by default so the table does not read as broken.
    assert presenters.drop_unavailable([rows[0], dead_row]) == [rows[0]]


def test_history_series_respects_the_lookback() -> None:
    row = {'history': [['2015-01-01', 1.0], ['2020-01-01', 2.0], ['2024-01-01', 3.0]]}
    dates, values = presenters.history_series(row, years=None)
    assert values == [1.0, 2.0, 3.0]
    dates, values = presenters.history_series(row, years=5)
    assert dates == ['2020-01-01', '2024-01-01'] and values == [2.0, 3.0]
    assert presenters.history_series({}, years=5) == ([], [])
    assert presenters.history_series(None) == ([], [])


def test_describe_freshness_reports_missing_series() -> None:
    text, status = economic.describe_freshness(None)
    assert status == 'muted' and 'No economic data' in text
    text, status = economic.describe_freshness({'rows': [{'series_id': 'UNRATE', 'available': True}], 'missing': []})
    assert status == 'positive' and '1 of 1 series loaded' in text
    text, status = economic.describe_freshness({
        'rows': [{'series_id': 'UNRATE', 'available': True}, {'series_id': 'GDPC1', 'available': False}],
        'missing': ['GDPC1'],
    })
    assert status == 'warning' and '1 of 2 series loaded' in text
    # An unreachable provider is named, so the user can tell a network block from a stale release.
    text, status = economic.describe_freshness({
        'rows': [{'series_id': 'UNRATE', 'available': True}],
        'missing': ['GDPC1'],
        'unreachable': [economic.PROVIDER_FRED],
    })
    assert status == 'warning' and 'unreachable: FRED' in text


def test_a_payload_from_an_older_schema_is_discarded() -> None:
    """The exact shape that hung the Economic page: a dev-era payload with `unreachable` as a bool.

    It reached the render path through `init_page42`, raised `TypeError: 'bool' object is not
    iterable`, and left the page on its loading placeholder forever - the crash happened before
    any code that could have refreshed the cache.
    """
    poisoned = {
        'generated_at': '2026-08-20T14:18:02',
        'source': 'FRED (Federal Reserve Bank of St. Louis)',
        'groups': ['Inflation', 'Labor', 'Growth', 'Rates'],
        'rows': [{'series_id': 'UNRATE', 'available': False, 'provider': economic.PROVIDER_FRED}],
        'missing': ['UNRATE'],
        'unreachable': True,
        'yield_curve': {'tenors': []},
    }
    # No schema stamp, so it is dropped at the cache boundary rather than coerced and shown.
    assert economic.normalize_payload(poisoned) is None
    assert economic.normalize_payload(dict(poisoned, schema=99)) is None
    assert economic.normalize_payload(None) is None
    assert economic.normalize_payload({'schema': economic.ECONOMIC_PAYLOAD_SCHEMA}) is None

    # Even reached directly, neither reader may raise on the bad field.
    assert 'unreachable' not in economic.describe_freshness(poisoned)[1]
    assert isinstance(presenters.missing_summary(poisoned), str)

    # A current payload survives, with the bad-shape fields coerced rather than trusted.
    salvaged = economic.normalize_payload(dict(poisoned, schema=economic.ECONOMIC_PAYLOAD_SCHEMA))
    assert salvaged is not None
    assert salvaged['unreachable'] == [] and salvaged['missing'] == ['UNRATE']
    assert salvaged['rows'] == poisoned['rows']

    with tempfile.TemporaryDirectory(prefix='budget-terminal-economic-schema-') as tmp:
        cache = CacheManager(db_path=str(Path(tmp) / 'cache.db'))
        service = economic.EconomicDataService(cache)
        cache.save_json_payload(
            economic.ECONOMIC_PAYLOAD_CACHE_NAMESPACE,
            economic.EconomicDataService._payload_cache_key(None),
            poisoned,
        )
        # The page must paint from nothing rather than from an entry it cannot render.
        assert service.load_latest_payload() is None

        # And the next fetch overwrites it, so the page heals itself with no manual cleanup.
        service.fetch(groups=['Labor'], force=True, fetcher=lambda sid: [('2024-08-01', 4.2)])
        healed = service.load_latest_payload(['Labor'])
        assert healed is not None
        assert healed['schema'] == economic.ECONOMIC_PAYLOAD_SCHEMA
        assert healed['unreachable'] == []


def test_normalize_name_list_rejects_non_lists() -> None:
    assert economic.normalize_name_list(True) == []
    assert economic.normalize_name_list(False) == []
    assert economic.normalize_name_list(None) == []
    assert economic.normalize_name_list(3) == []
    assert economic.normalize_name_list('FRED') == ['FRED']
    assert economic.normalize_name_list('') == []
    assert economic.normalize_name_list(['FRED', ' BLS ', '', None]) == ['FRED', 'BLS']
    assert economic.normalize_name_list(('FRED',)) == ['FRED']


def test_user_agent_is_not_browser_spoofed() -> None:
    """A browser user-agent here loses every FRED series - 20 of the 49 in the catalog.

    FRED sits behind Akamai, which reads a request claiming to be Chrome without Chrome's TLS
    fingerprint as a bot and tarpits it until the client times out. The fetch then trips its own
    blackout breaker and reports `unreachable: FRED`, which looks like a network block rather
    than a header the app chose. A plain product token answers in under a second, and Treasury,
    BLS, NY Fed and UMich all return identical responses under it.
    """
    agent = economic.REQUEST_HEADERS['User-Agent']
    for token in ('Mozilla', 'Chrome', 'AppleWebKit', 'Safari'):
        assert token not in agent, f'economic user-agent must not spoof a browser: {agent!r}'
    assert agent.startswith('BudgetTerminal/'), f'economic user-agent must identify the app: {agent!r}'
    # The BLS POST builds its headers from the same dict, so it inherits the fix.
    assert economic.FRED_REQUEST_HEADERS is economic.REQUEST_HEADERS


if __name__ == '__main__':
    test_parse_fred_csv_drops_missing_sentinels()
    test_parse_treasury_csv_by_column_name()
    test_align_difference_only_uses_shared_dates()
    test_parse_bls_payload_maps_period_codes()
    test_parse_nyfed_and_umich()
    test_latest_and_prior_handles_short_series()
    test_yoy_transform_uses_dates_not_index_offsets()
    test_mom_and_saar_transforms()
    test_build_row_survives_an_empty_series()
    test_build_yield_curve_orders_tenors_and_flags_inversion()
    test_format_value_and_change_per_unit()
    test_normalize_groups_and_catalog_integrity()
    test_fetch_uses_the_cache_and_isolates_failures()
    test_blackout_stops_early_and_keeps_the_cached_payload()
    test_presenters_build_rows_without_qt()
    test_history_series_respects_the_lookback()
    test_describe_freshness_reports_missing_series()
    test_a_payload_from_an_older_schema_is_discarded()
    test_normalize_name_list_rejects_non_lists()
    test_user_agent_is_not_browser_spoofed()
    print('Economic service tests passed.')
